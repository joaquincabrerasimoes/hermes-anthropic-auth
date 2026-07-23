# AGENTS.md

Pip plugin for [Hermes Agent](https://hermes-agent.nousresearch.com/) that fixes a false-positive "out of extra usage" billing block on Claude Pro/Max OAuth traffic. See `README.md` for the full what/why.

## Commands

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

**Python version gotcha:** `pyproject.toml` pins `requires-python = ">=3.11,<3.14"` to match hermes-agent's own constraint. `pip install -e .` hard-fails on Python 3.14+ (`requires a different Python`). If your default interpreter is 3.14+, either use a 3.11–3.13 venv, or skip the install for quick iteration:

```powershell
$env:PYTHONPATH = "src"; python -m pytest tests/ -v
```

No lint/typecheck/build-config exists yet — `pytest` is the only check in this repo.

## Architecture — read before editing `patch.py` / `transport.py`

This is a **monkey-patch**, not a Hermes "model provider plugin". Hermes's plugin system (`providers/`, `ProviderProfile`) only auto-wires `auth_type="api_key"` providers — OAuth request/credential handling is hardcoded per-provider in hermes-agent core with no declarative hook for rewriting an existing provider's outgoing request. So this patches the one confirmed choke point instead: `agent.anthropic_adapter.build_anthropic_client()` — verified as the sole Anthropic SDK-client constructor call site in hermes-agent; all 9 call sites there use function-local imports, so one reassignment at plugin-load time intercepts everything.

Design invariants — violating these reintroduces the bug this plugin exists to fix, or breaks something else:

- **Fail-open everywhere.** Any exception in `transport.py` / `body_rewrite.py` must fall back to sending the original, unmodified request — never raise into a real API call.
- **Only wrap OAuth clients.** Gate is `_is_oauth_token(api_key)`, imported from hermes-agent itself, not reimplemented. Plain API keys, Bedrock, and Azure Entra ID (callable `api_key`) must never be touched.
- **Never touch `messages[].content`.** Only Hermes-authored static text (`system[]` blocks, tool/property `description` strings) gets sanitized — message content is user/tool-output data.
- **Tool descriptions: phrase-replace only, never paragraph-remove** (`sanitize.py`). Blanking a description is worse than a branded one. Paragraph-anchor removal is only safe on `system[]` blocks.
- `build_anthropic_client`, `_is_oauth_token`, `_get_claude_code_version` are pulled from hermes-agent internals at runtime, not a declared dependency (the plugin only runs inside an already-running hermes-agent process). If a future hermes-agent release renames these, `patch.py::install()` must log a warning and no-op — never crash hermes-agent.

**Packaging:** discovery is via `[project.entry-points."hermes_agent.plugins"]` in `pyproject.toml`. The value must be a bare module name (`"hermes_anthropic_auth"`), not `"module:function"` — hermes-agent's own loader calls `ep.load()` expecting a module object with a `register(ctx)` attribute, and its docs contradict this in one place. Don't change the entry-point format without re-checking hermes-agent's `_load_entrypoint_module`.

## `billing_header.py` — don't touch the constants

`CCH_SALT`, `CCH_POSITIONS`, and the hash truncation lengths are reverse-engineered from a decompiled Claude Code binary, ported from `referenceCode/opencode-anthropic-auth/src/cch.ts` (source of truth for the algorithm). `tests/test_billing_header.py` asserts the exact same input/output pairs as that project's `cch.test.ts` — a cross-language correctness proof, not an arbitrary snapshot. If it fails, the algorithm broke; don't edit the test to match new output.

## `referenceCode/`

Gitignored, not part of this package. It's the TypeScript/Bun OpenCode plugin (`opencode-anthropic-auth`) this project ports its Anthropic-classifier-evasion techniques from. Consult as prior art; never build or import from it.

## Testing

`tests/conftest.py::fake_hermes_env` injects a fake `agent.anthropic_adapter` module into `sys.modules`. The real hermes-agent package is never installed or imported for tests — if a test needs a new attribute on it, extend the fake in `conftest.py` rather than adding hermes-agent as a test dependency.

## Status

Not yet live-verified against a running hermes-agent instance or a real Anthropic OAuth account — unit-tested only (43/43 passing). No git commits yet as of this writing.
