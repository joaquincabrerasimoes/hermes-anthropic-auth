# hermes-anthropic-auth

> [!WARNING]
> This plugin comes with no guarantees. You might be flagged for breaking Anthropic's TOS, you might not be. Neither Anthropic nor Nous Research are affiliated with this project. Use your best judgment and don't abuse the subscription — heavy automated/looped usage is more likely to draw scrutiny regardless of this plugin.

A plugin for [Hermes Agent](https://hermes-agent.nousresearch.com/) that fixes a false-positive billing block on Claude Pro/Max OAuth traffic:

```
Billing or credits exhausted: HTTP 400: You're out of extra usage. Add more at claude.ai/settings/usage and keep going.

    anthropic reported that your Claude subscription usage is exhausted for claude-sonnet-5 (included quota + extra-usage credits).
    Options: wait for the billing cycle to reset, or add extra usage at Claude
    You can also switch to an Anthropic API key or another provider with /model <model> --provider <provider>.
```

## This is not what it looks like

Hermes Agent already ships a fully working, native Claude Pro/Max OAuth login (`hermes auth add anthropic --type oauth`), automatic token refresh, and Claude-Code request spoofing. **You don't need this plugin to log in with your subscription — that already works.**

The error above is usually not real quota exhaustion. Anthropic's API has a server-side classifier that fingerprints whether a request "looks like" genuine Claude Code CLI traffic. Requests that don't pass get silently routed to the metered "extra usage" bucket instead of your Pro/Max plan quota — and once that's depleted, you get the misleading 400 above, worded exactly like a real billing message. Hermes's own built-in request spoofing has real gaps (see below), which is what actually triggers this for a lot of users.

The same class of problem happened to [OpenCode](https://github.com/anomalyco/opencode) and was fixed by [`opencode-anthropic-auth`](https://github.com/ex-machina-co/opencode-anthropic-auth) (see `referenceCode/` in this repo). This plugin ports that project's detection-evasion techniques into Hermes.

## What's actually broken in Hermes today

Hermes's OAuth request path (`agent/anthropic_adapter.py`) already does some of the right things — it prepends a Claude Code identity block, renames tool names to the `mcp__` double-underscore form, and sets the OAuth-only beta headers. Two things it's still missing:

1. **No billing-header fingerprint.** Genuine Claude Code sends a pseudo-header line (`x-anthropic-billing-header: cc_version=...; cc_entrypoint=...; cch=...;`) embedded as the first `system` block on every request — a content-consistency hash reverse-engineered from a decompiled Claude Code binary by the `opencode-anthropic-auth` project. Hermes never sends this at all.
2. **Incomplete branding sanitization.** Hermes's built-in sanitizer is 4 literal `.replace()` calls. It misses the bare `nousresearch.com` domain (its own help-guidance block ships `https://hermes-agent.nousresearch.com/docs` in every single session, unconditionally), several bare `"Hermes"` mentions across platform hints and the mid-turn steering explanation, and it never touches tool/parameter `description` strings at all — three of which currently ship literal `**Hermes**` mentions.

Neither gap is huge on its own, but Anthropic's classifier only needs one signal to misclassify a request.

## How this plugin fixes it

It's a monkey-patch, not a new provider. Hermes's plugin system has no declarative hook for "rewrite an existing native provider's outgoing request" — OAuth providers are wired through hardcoded core files, confirmed by reading `providers/base.py`, `agent/auxiliary_client.py`, and the project's own [Adding Providers](https://hermes-agent.nousresearch.com/docs/developer-guide/adding-providers) docs. So instead of fighting the plugin system, this patches the single confirmed choke point: `agent.anthropic_adapter.build_anthropic_client()`.

On load, the plugin wraps that function. For clients built with a genuine OAuth token (`_is_oauth_token(api_key)` — Claude Pro/Max subscription auth, never plain API keys), it attaches a custom `httpx` transport to the SDK client that, immediately before every `/v1/messages` request goes out on the wire:

1. Injects the billing-header fingerprint as `system[0]`.
2. Extends the branding sanitization to cover the leaks above (anchor-based paragraph removal + targeted phrase replacement, same architecture `opencode-anthropic-auth` uses — see `sanitize.py`).
3. Sanitizes tool/parameter `description` strings the same way.

It never touches message content, tool output, or anything dynamic — only Hermes-authored static prompt/schema text. Plain API-key traffic, AWS Bedrock, and Azure Entra ID clients are completely untouched; the wrap only ever attaches to OAuth clients.

If anything in the rewrite path throws, it fails open — the original, unmodified request goes out instead of raising. A bug in this plugin should never be able to break your actual API calls.

## Install

Two supported install methods. Both register under the same plugin id (`hermes-anthropic-auth`), so enabling, disabling, and the diagnostic command work identically either way — pick based on your setup.

| Method | Best for | Docker rebuild needed? |
|---|---|---|
| **A — pip** | Bare-metal / venv installs; also the right choice for Docker if you're comfortable maintaining a small derived image | Yes, once (baked into the image) |
| **B — directory** | Docker without maintaining a derived image; quick trials anywhere | No — drop-in, picked up on next restart |

Hermes's plugin system is opt-in either way: installing the files (via either method) is not enough on its own, you always still need `hermes plugins enable hermes-anthropic-auth`.

### Method A — pip (entry-point plugin)

**Bare metal / venv:**

```bash
pip install hermes-anthropic-auth
hermes plugins enable hermes-anthropic-auth
```

(Not yet on PyPI? Install straight from GitHub: `pip install "git+https://github.com/joaquincabrerasimoes/hermes-anthropic-auth.git"`.)

**Docker:** the official image's `/opt/hermes` (where the Python venv lives) is root-owned, read-only at runtime, and has lazy installs disabled by design — `docker exec ... pip install` will not work or persist. Build a small derived image instead (this is Hermes's own documented pattern for durable installs, just swapped from an apt package to ours):

```dockerfile
# Dockerfile
FROM nousresearch/hermes-agent:latest
USER root
RUN /opt/hermes/.venv/bin/python -m pip install --no-cache-dir \
    "git+https://github.com/joaquincabrerasimoes/hermes-anthropic-auth.git"
USER hermes
```

```bash
docker build -t hermes-agent-fixed:latest .
```

Then swap `nousresearch/hermes-agent:latest` → `hermes-agent-fixed:latest` in your `docker run` command or `docker-compose.yml` (volumes/ports/env stay unchanged), recreate the container, then enable it:

```bash
docker exec hermes hermes plugins enable hermes-anthropic-auth
```

Rebuild + recreate whenever you pull a newer upstream `nousresearch/hermes-agent`.

### Method B — directory (drop-in, no pip, no rebuild)

The plugin's package folder (`src/hermes_anthropic_auth/`) is *also* a valid flat directory-style plugin — it already ships its own `plugin.yaml` alongside `__init__.py`. Hermes's own `httpx` dependency (already required by Hermes itself) covers this method's only import — nothing else to install.

**Bare metal:**

```bash
git clone https://github.com/joaquincabrerasimoes/hermes-anthropic-auth.git /tmp/hermes-anthropic-auth
mkdir -p ~/.hermes/plugins
cp -r /tmp/hermes-anthropic-auth/src/hermes_anthropic_auth ~/.hermes/plugins/hermes-anthropic-auth
hermes plugins enable hermes-anthropic-auth
```

(Symlink instead of `cp -r` if you want `git pull` in the clone to update the live plugin without re-copying.)

**Docker:** `/opt/data` (your bind-mounted `~/.hermes`) is the one persistent, writable volume — and `plugins/` lives there, so this needs zero image rebuild. Run the same clone + copy on the **host**, then restart the container:

```bash
git clone https://github.com/joaquincabrerasimoes/hermes-anthropic-auth.git /tmp/hermes-anthropic-auth
mkdir -p ~/.hermes/plugins
cp -r /tmp/hermes-anthropic-auth/src/hermes_anthropic_auth ~/.hermes/plugins/hermes-anthropic-auth
docker restart hermes
docker exec hermes hermes plugins enable hermes-anthropic-auth
```

### Verify (either method)

```bash
hermes anthropic-oauth-fix status
```
```
hermes-anthropic-auth
  patch installed: yes
  example billing header: x-anthropic-billing-header: cc_version=2.1.87.6ff; cc_entrypoint=sdk-cli; cch=4ffc3;
  Active for OAuth (Claude Pro/Max) requests only — plain API key traffic is untouched.
```
(Prefix with `docker exec hermes` if running in Docker.)

If you haven't logged in with Claude Pro/Max yet, see the [native OAuth flow](https://hermes-agent.nousresearch.com/docs/developer-guide/adding-providers) — `hermes auth add anthropic --type oauth`, then set your model with `--provider anthropic --model claude-sonnet-4-6` or in `~/.hermes/config.yaml`. This plugin doesn't handle login; it only fixes what happens to requests after you're already authenticated.

## Compatibility

Targets the current Hermes Agent release line (`v2026.7.20` / `hermes-agent==0.19.0` and later). It imports a handful of Hermes internals directly (`agent.anthropic_adapter.build_anthropic_client`, `_is_oauth_token`, `_get_claude_code_version`) — if a future Hermes release renames or removes these, the plugin logs a warning and does nothing (fails closed at install time, never breaks Hermes itself), rather than crashing.

Requires `httpx` (already a Hermes dependency) and Python 3.11–3.13, matching Hermes's own constraint.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests use fake stand-ins for `agent.anthropic_adapter` (see `tests/conftest.py`) so the suite runs without needing the real hermes-agent package installed. `tests/test_billing_header.py` includes the exact test vectors from `opencode-anthropic-auth`'s `cch.test.ts` — same input, same hash output, verifying the Python port is byte-for-byte faithful to the reverse-engineered algorithm. `tests/test_plugin_manifest.py` asserts `src/hermes_anthropic_auth/plugin.yaml` and `pyproject.toml` never drift apart on plugin name/version — both install methods (Method A and B above) must resolve to the exact same plugin id.

## License

MIT
