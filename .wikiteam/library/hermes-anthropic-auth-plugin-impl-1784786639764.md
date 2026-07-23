Name: hermes-anthropic-auth plugin impl
Keywords: hermes-anthropic-auth, monkey-patch, build_anthropic_client, billing header, OAuth sanitizer
FilePathReference: src/hermes_anthropic_auth/
Short Description: Pip plugin monkey-patches build_anthropic_client to fix false-positive Anthropic OAuth billing block.
---
## What this project is

hermes-anthropic-auth: Hermes Agent plugin fixing a real production bug — Anthropic's server-side classifier false-positive-blocks Hermes's native Claude Pro/Max OAuth traffic with a misleading HTTP 400 "You're out of extra usage" error, because Hermes's own OAuth request fingerprinting is incomplete compared to genuine Claude Code.

**Ships with TWO supported install methods, both tested, both resolve to the same plugin id** (see "Dual install methods" section below — added after initial build, in response to a Docker deployment question).

## Critical prerequisite finding (do not re-litigate)

Hermes Agent (Python, NousResearch/hermes-agent, current release v2026.7.20 / pyproject version 0.19.0) ALREADY ships a complete, working, native Claude Pro/Max OAuth PKCE login flow (`agent/anthropic_adapter.py::run_hermes_oauth_login_pure()`, wired via `hermes auth add anthropic --type oauth` in `hermes_cli/auth_commands.py:224-248`), automatic token refresh, Claude Code identity spoofing, and `mcp__` tool-name normalization (GH-25255 fix). This is NOT something that needed building — verified by cloning the actual repo and reading source, not just docs. Do not build OAuth login/auth flow — it exists. The interactive `hermes model` picker still uses an OLDER external-`claude`-CLI-dependent path (`_run_anthropic_oauth_flow` in `hermes_cli/main.py:4311`) instead of the native one — a separate, minor, NOT-yet-fixed UX inconsistency (picker's `has_creds` check in `hermes_cli/model_setup_flows.py:2932` doesn't see `credential_pool` entries) — out of scope for this plugin, not fixed.

## The actual bug this plugin fixes

Two confirmed gaps in `agent/anthropic_adapter.py`'s `is_oauth` branch of `build_anthropic_kwargs()` (lines 2572-2650):
1. No billing-header fingerprint at all (genuine Claude Code sends `x-anthropic-billing-header: cc_version=X.Y.ZZZ; cc_entrypoint=sdk-cli; cch=XXXXX;` as system[0], a SHA-256 content-consistency hash reverse-engineered from decompiled Claude Code binary — algorithm ported verbatim from `referenceCode/opencode-anthropic-auth/src/cch.ts`: `CCH_SALT="59cf53e54c78"`, `CCH_POSITIONS=(4,7,20)`).
2. Sanitizer is only 4 literal `.replace()` calls (`"Hermes Agent"→"Claude Code"`, `"Hermes agent"→"Claude Code"`, `"hermes-agent"→"claude-code"`, `"Nous Research"→"Anthropic"`) — misses bare `nousresearch.com` domain (leaked via `HERMES_AGENT_HELP_GUIDANCE` in `agent/prompt_builder.py:149-158`, unconditionally injected every session at `agent/system_prompt.py:199`), misses bare "Hermes" in `PLATFORM_HINTS` (tui/desktop/webui, `prompt_builder.py:764-900`), `STEER_CHANNEL_NOTE` (`:640-651`), remote-backend hints (`:1170-1200`, includes "the Hermes process" phrase), active-profile hint (`agent/system_prompt.py:396-410`) — and NEVER touches tool `description`/`input_schema.properties.*.description` fields at all (3 confirmed live leaks: `tools/browser_tool.py:1973`, `tools/file_tools.py:1971,2022`, all containing literal `**Hermes**`).

## Why the fix is a monkey-patch, not a "provider plugin"

Confirmed via research (`.wikiteam/library/provider-plugin-oauth-needs-core-edits-*.md`): Hermes's `providers/` plugin system (`ProviderProfile`, `register_provider()`) only auto-wires `auth_type="api_key"` providers into `PROVIDER_REGISTRY`. OAuth credential resolution/dispatch is hardcoded per-provider-ID in `agent/auxiliary_client.py` (literal `if provider == "..."` chain, no plugin hook). No declarative hook exists for "rewrite an existing native provider's outgoing request." So the plugin monkey-patches instead.

## The patch mechanism (single choke point, verified safe)

`agent.anthropic_adapter.build_anthropic_client()` is the ONLY Anthropic SDK client constructor call site in the entire hermes-agent repo (confirmed by full-repo grep, `.wikiteam/library/anthropic-sdk-single-choke-point-*.md` and `build-anthropic-client-patch-surface-*.md`). All 9 call sites across `run_agent.py`, `agent/agent_init.py`, `agent/agent_runtime_helpers.py`, `agent/chat_completion_helpers.py`, `agent/auxiliary_client.py` use FUNCTION-LOCAL `from agent.anthropic_adapter import build_anthropic_client` (re-resolved from module `__dict__` on every call, never top-of-file) — proven by Hermes's OWN test suite mocking pattern (`patch("agent.anthropic_adapter.build_anthropic_client", ...)`). This means reassigning `agent.anthropic_adapter.build_anthropic_client` once at plugin-load time intercepts ALL of them. No AsyncAnthropic used anywhere (0 hits) — sync-only, simpler.

`_is_oauth_token(api_key)` (checks token prefix: `sk-ant-api*`→False, `sk-ant-*`/`eyJ*`/`cc-*`→True) gates whether a client gets wrapped — plain API keys, Bedrock, Azure Entra ID (callable api_key) clients are NEVER touched, zero behavior change for non-OAuth users.

Wrapping mechanism: reach into the SDK client's `._client` (confirmed httpx.Client instance — Hermes's OWN `agent/agent_runtime_helpers.py:3143-3167::_iter_pool_sockets` does `getattr(client, "_client")` then `getattr(http_client, "_transport")` for TCP force-close on interrupt, proving this attribute path), reassign `._transport` to a custom `httpx.BaseTransport` subclass wrapping the original transport. Custom transport implements `__getattr__` proxy-through to the wrapped transport so `_pool` introspection (used by the force-close code) keeps working transparently.

httpx pinned exact `0.28.1` in hermes-agent (`pyproject.toml:44`, `uv.lock:1979`). Our plugin declares `httpx>=0.27,<1.0` (BaseTransport API stable across that range).

## Package structure (built, tested, 50/50 tests passing)

```
hermes-anthropic-auth/
├── pyproject.toml          # hatchling, entry-point group "hermes_agent.plugins" = "hermes_anthropic_auth"
├── src/hermes_anthropic_auth/
│   ├── plugin.yaml          # kind: standalone — makes this SAME folder also a valid directory-style plugin
│   ├── __init__.py         # register(ctx) — calls patch.install(), registers optional CLI diagnostic
│   ├── billing_header.py   # ported cch.ts verbatim — compute_cch, compute_version_suffix, build_billing_header_value
│   ├── sanitize.py         # PARAGRAPH_REMOVAL_ANCHORS + TEXT_REPLACEMENTS, ported transform.ts architecture
│   ├── body_rewrite.py     # orchestrates sanitize+billing_header over a parsed JSON dict (pure, testable)
│   ├── transport.py        # OAuthRequestSanitizingTransport(httpx.BaseTransport) — wire-level interception, fail-open on any exception
│   ├── patch.py            # install()/uninstall()/is_installed() — the monkey-patch itself
│   └── cli.py               # `hermes anthropic-oauth-fix status|test-header` diagnostic (optional, non-fatal if registration fails)
└── tests/                  # pytest, fake agent.anthropic_adapter via sys.modules injection (conftest.py) — no real hermes-agent dependency needed to test
```

Key design invariants (do not violate in future edits):
- Fail-open everywhere: any exception in the rewrite path → original unmodified request goes out, never crash a real API call.
- Never touch `messages[].content` (dynamic user/tool data) — only Hermes-authored static `system[]` text and tool/property `description` strings.
- Tool descriptions: phrase-replace only, NEVER paragraph-remove (would blank out a tool's description entirely).
- System prompt: paragraph-anchor removal allowed (safe to drop whole non-essential self-referential paragraphs) + phrase replacement for load-bearing paragraphs.
- `_get_claude_code_version()` reused from hermes (not reimplemented) so billing-header `cc_version` matches the User-Agent header hermes already sends — self-consistent fingerprint.

## Dual install methods (added for Docker deployment support)

Hermes's official Docker image (`nousresearch/hermes-agent`) has `/opt/hermes` (the Python venv) root-owned + read-only at runtime, with lazy installs explicitly disabled (`HERMES_DISABLE_LAZY_INSTALLS=1`) — confirmed by reading the actual Dockerfile + official docs. `docker exec ... pip install` does not work/persist. Only `/opt/data` (bind-mounted `~/.hermes`) is writable, and Hermes's own docs explicitly list `plugins/` as living there.

This drove supporting BOTH install shapes from the SAME source tree (no duplication):
- **Method A — pip/entry-point**: `pip install hermes-anthropic-auth` (or git+https) + `hermes plugins enable hermes-anthropic-auth`. For Docker: requires a derived image (`FROM nousresearch/hermes-agent:latest`, `USER root`, `RUN /opt/hermes/.venv/bin/python -m pip install ...`, `USER hermes`) — matches hermes's own documented "Durable installs — build a derived image" pattern exactly (Docker docs page: "Installing more tools in the container").
- **Method B — directory-style drop-in**: `src/hermes_anthropic_auth/` ALSO ships its own `plugin.yaml` (kind: standalone — critically NOT `model-provider`, which would make Hermes's PluginManager skip calling `register(ctx)` entirely per its own discovery code) sitting flat alongside `__init__.py` and all sibling modules. Copy/symlink that exact folder to `~/.hermes/plugins/hermes-anthropic-auth/` (or Docker: same copy on the HOST's bind-mounted `~/.hermes/plugins/`, since that volume persists) — zero pip install, zero image rebuild, just a container restart to pick it up. `httpx` (our only runtime dep) is already guaranteed present since hermes-agent itself depends on it.

Both methods resolve to the SAME plugin id `hermes-anthropic-auth` for `hermes plugins enable/disable/status` — verified by `tests/test_plugin_manifest.py` which cross-checks `plugin.yaml`'s `name`/`version` against `pyproject.toml`'s entry-point name/version, catching future drift.

`tests/test_directory_style_loading.py` proves Method B actually works by SIMULATING hermes's own directory-plugin loader mechanism (`importlib.util.spec_from_file_location(name, __init__.py, submodule_search_locations=[plugin_dir])`) directly against the real `src/hermes_anthropic_auth/` folder — confirms relative imports between sibling modules (`from .patch import install` etc.) resolve correctly under that loading scheme, not just under normal `import hermes_anthropic_auth` package resolution (which is a materially different Python import code path).

Repo: https://github.com/joaquincabrerasimoes/hermes-anthropic-auth. Reference implementation this was ported from: `referenceCode/opencode-anthropic-auth/` (gitignored, TypeScript/Bun, OpenCode plugin, same underlying Anthropic classifier problem, MIT licensed).

Verified locally: `pytest tests/ -v` → 50 passed (Python 3.14.2 venv via PYTHONPATH=src, since actual `pip install -e .` correctly refuses on this constraint — pyproject.toml declares `requires-python = ">=3.11,<3.14"` matching hermes-agent's own constraint; this is intentional, not a bug). NOT live-tested against a real running hermes-agent instance or real Anthropic OAuth credentials — that requires the user's own environment/account.
