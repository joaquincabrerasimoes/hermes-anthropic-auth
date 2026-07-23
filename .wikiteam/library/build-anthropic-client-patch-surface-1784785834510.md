Name: build_anthropic_client patch surface
Keywords: build_anthropic_client, monkey-patch, httpx transport, OAuth, function-local import, is_oauth branch
FilePathReference: agent/anthropic_adapter.py:350-393,640-900,2572-2733
Short Description: Full verbatim of build_anthropic_client family + import-pattern proof enabling single-point monkey-patch for OAuth-only httpx transport injection.
---
## Patch target verified: single-point monkeypatch sufficient

All 6 call-site files (run_agent.py, agent/agent_init.py, agent/agent_runtime_helpers.py, agent/chat_completion_helpers.py, agent/conversation_loop.py [indirect only], agent/auxiliary_client.py) use FUNCTION-LOCAL `from agent.anthropic_adapter import build_anthropic_client` — never top-of-file. This means the import re-resolves from `agent.anthropic_adapter.__dict__` on every call. Patching `agent.anthropic_adapter.build_anthropic_client = wrapper` BEFORE any agent code runs is sufficient — no need to patch each file's local namespace. Proven by existing test suite pattern: every test in tests/run_agent/test_run_agent.py, test_switch_model_rollback.py, test_anthropic_third_party_oauth_guard.py, test_63425_credential_pool_auto_detect.py etc. uses `patch("agent.anthropic_adapter.build_anthropic_client", ...)` (module-qualified) and it works against all these call sites.

Call sites (all function-local import + call, same file):
- run_agent.py:4499-4500 (per-request client), 4779/4798 (init), 4922/4931 (credential swap), 5023/5024 (inside `_rebuild_anthropic_client()` method, called from conversation_loop.py:3095)
- agent/agent_init.py:942,1003
- agent/agent_runtime_helpers.py:1188/1191, 1360/1363, 2113(import)/2141(call)
- agent/chat_completion_helpers.py:1765/1770
- agent/auxiliary_client.py: 4 separate sites — 1653/1663, 2595/2596, 2799/2851, 5055/5056
- agent/conversation_loop.py:3095 only calls `agent._rebuild_anthropic_client()` method — no direct import of build_anthropic_client in this file.

## build_anthropic_client() full source — agent/anthropic_adapter.py:727-853

```python
def build_anthropic_client(
    api_key,
    base_url: str = None,
    timeout: float = None,
    *,
    drop_context_1m_beta: bool = False,
):
    """Create an Anthropic client, auto-detecting setup-tokens vs API keys.
    ...
    """
    _anthropic_sdk = _get_anthropic_sdk()
    if _anthropic_sdk is None:
        raise ImportError(...)

    # Callable api_key → Entra ID bearer provider path.
    if callable(api_key) and not isinstance(api_key, str):
        return _build_anthropic_client_with_bearer_hook(
            api_key, base_url, timeout,
            drop_context_1m_beta=drop_context_1m_beta,
        )

    normalize_proxy_env_vars()
    from httpx import Timeout

    normalized_base_url = _normalize_base_url_text(base_url)
    if normalized_base_url:
        import re as _re
        normalized_base_url = _re.sub(r"/v1/?$", "", normalized_base_url.rstrip("/"))
    _read_timeout = timeout if (isinstance(timeout, (int, float)) and timeout > 0) else 900.0
    kwargs = {
        "timeout": Timeout(timeout=float(_read_timeout), connect=10.0),
        "max_retries": 0,
    }
    if normalized_base_url:
        if _is_azure_anthropic_endpoint(normalized_base_url) and "api-version" not in normalized_base_url:
            kwargs["base_url"] = normalized_base_url.rstrip("/")
            kwargs["default_query"] = {"api-version": "2025-04-15"}
        else:
            kwargs["base_url"] = normalized_base_url
    common_betas = _common_betas_for_base_url(
        normalized_base_url, drop_context_1m_beta=drop_context_1m_beta,
    )

    if _is_kimi_coding_endpoint(base_url):
        kwargs["api_key"] = api_key
        kwargs["default_headers"] = {
            "User-Agent": "claude-code/0.1.0",
            **( {"anthropic-beta": ",".join(common_betas)} if common_betas else {} )
        }
    elif _requires_bearer_auth(normalized_base_url):
        kwargs["auth_token"] = api_key
        if common_betas:
            kwargs["default_headers"] = {"anthropic-beta": ",".join(common_betas)}
    elif _is_third_party_anthropic_endpoint(base_url):
        kwargs["api_key"] = api_key
        if common_betas:
            kwargs["default_headers"] = {"anthropic-beta": ",".join(common_betas)}
    elif _is_oauth_token(api_key):
        # OAuth access token / setup-token → Bearer auth + Claude Code identity.
        all_betas = common_betas + _OAUTH_ONLY_BETAS
        kwargs["auth_token"] = api_key
        kwargs["default_headers"] = {
            "anthropic-beta": ",".join(all_betas),
            "user-agent": f"claude-code/{_get_claude_code_version()} (external, cli)",
            "x-app": "cli",
        }
    else:
        kwargs["api_key"] = api_key
        if common_betas:
            kwargs["default_headers"] = {"anthropic-beta": ",".join(common_betas)}

    return _anthropic_sdk.Anthropic(**kwargs)
```

KEY FACT: NONE of the branches (Kimi/bearer/third-party/OAuth/plain-key) pass `http_client=`. Only `_build_anthropic_client_with_bearer_hook()` (callable-api_key path, Entra ID only) does, at line 699, via `agent.azure_identity_adapter.build_bearer_http_client()`. To inject a custom httpx transport ONLY for OAuth tokens, a wrapper must replicate the `_is_oauth_token(api_key)` check (same as line 836) and either (a) construct the Anthropic client itself with `http_client=` set, duplicating lines 840-846's header logic, or (b) call through to original then attempt post-hoc client mutation (risky — SDK client stores httpx.Client internally, may not support post-construction swap cleanly).

## _build_anthropic_client_with_bearer_hook — template for http_client injection, agent/anthropic_adapter.py:651-724

Existing precedent: builds `httpx.Client(event_hooks={"request": [_inject_bearer]}, **httpx_kwargs)` via `agent.azure_identity_adapter.build_bearer_http_client()` (agent/azure_identity_adapter.py:462-540), then passes as `kwargs["http_client"]` into `_anthropic_sdk.Anthropic(**kwargs)` at line 724. This is the reusable pattern shape for the new OAuth-only transport-injection plugin.

## build_anthropic_bedrock_client — agent/anthropic_adapter.py:856-892
Not OAuth-relevant (boto3 creds). No http_client involved. Full source read, no patch surface needed here.

## Claude Code version detection — agent/anthropic_adapter.py:350-393

```python
_CLAUDE_CODE_VERSION_FALLBACK = "2.1.74"
_claude_code_version_cache: Optional[str] = None

def _detect_claude_code_version() -> str:
    import subprocess as _sp
    for cmd in ("claude", "claude-code"):
        try:
            result = _sp.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                version = result.stdout.strip().split()[0]
                if version and version[0].isdigit():
                    return version
        except Exception:
            pass
    return _CLAUDE_CODE_VERSION_FALLBACK

_CLAUDE_CODE_SYSTEM_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."
_MCP_TOOL_PREFIX = "mcp__"

def _get_claude_code_version() -> str:
    global _claude_code_version_cache
    if _claude_code_version_cache is None:
        _claude_code_version_cache = _detect_claude_code_version()
    return _claude_code_version_cache
```

Shells `claude --version` / `claude-code --version` (NOT shutil.which — that's a separate unrelated function at line 1361 inside the `setup-token` CLI login flow). Result cached process-globally in `_claude_code_version_cache` — first successful/failed detection wins for process lifetime; a plugin wanting to override the version string must set this global BEFORE first OAuth client build, or monkeypatch `_get_claude_code_version`/`_detect_claude_code_version` directly.

## is_oauth branch in build_anthropic_kwargs() — agent/anthropic_adapter.py:2572-2733 (full, not just 2572-2636)

Covers: (1) Claude Code system-prompt prefix injection (2574-2581), (2) 4-string blunt sanitizer — KNOWN GAP leaves nousresearch.com domain intact, see evidence `oauth-sanitizer-misses-nousresearch-url` (2583-2592), (3) tool name → mcp__ normalization for GH-25255 classifier evasion (2594-2623), (4) same normalization applied to tool_use blocks in message history (2625-2635), (5) THEN separately, later in the same function: fast-mode beta header assembly at 2716-2731 also references `is_oauth` (adds `_OAUTH_ONLY_BETAS` at line 2729) — this is NOT part of the immediate if-block at 2573 but is a second, later use of the `is_oauth` parameter in the same function. Both locations matter for any OAuth-header-related patch.

## httpx pin

pyproject.toml:44: `"httpx[socks]==0.28.1",`
uv.lock:1796: `{ name = "httpx", extras = ["socks"], specifier = "==0.28.1" },`
uv.lock:1979-1980: `name = "httpx"` / `version = "0.28.1"`
Confirmed exact: httpx 0.28.1, with socks extra, both files agree.

## message_sanitization.py (477 lines, full read) — NO reusable generic sanitizer

No regex-replace/paragraph-filter/anchor-removal utility exists for the OAuth branding/URL sanitization problem. Only regexes present: `_SURROGATE_RE` (surrogate codepoints, line 28) and trailing-comma JSON repair pattern (line 226) — neither applicable. `_strip_non_ascii` (314-320) is character-class based (ascii encode/ignore), wrong tool for targeted literal/URL removal. Reusable SHAPE (not drop-in) for a new sanitizer: `_sanitize_structure_surrogates` (42-72) and `_sanitize_structure_non_ascii` (435-461) — recursive nested dict/list walker closures — good template to model a new `_sanitize_structure_urls_and_brands()` on, but actual regex/literal substitution list must be written fresh. Any nousresearch.com-domain-leak fix (or new OAuth sanitizer for the transport-injection plugin) cannot reuse existing logic — must write new.
