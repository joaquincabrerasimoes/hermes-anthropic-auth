Name: Anthropic OAuth already in hermes-agent
Keywords: anthropic, oauth, claude-code, pkce, credential_pool, anthropic_adapter
FilePathReference: agent/anthropic_adapter.py, hermes_cli/auth.py, hermes_cli/auth_commands.py, hermes_cli/runtime_provider.py
Short Description: hermes-agent already has full Claude Pro/Max OAuth PKCE login + Claude Code credential auto-detect + refresh
---
KEY FINDING: hermes-agent already ships a COMPLETE native Anthropic OAuth (Claude Pro/Max subscription login) implementation. No plugin/patch needed to add the core capability — it exists end-to-end. A prospective task should focus on gaps (UX exposure, `hermes model` wizard entry, docs), not building OAuth from scratch.

## 1. agent/anthropic_adapter.py — Full picture (2826 lines)

### SDK usage
Uses the official `anthropic` Python SDK (`anthropic.Anthropic`, `anthropic.AnthropicBedrock`), NOT raw HTTP for inference calls. SDK imported lazily via `_get_anthropic_sdk()` (line 37-54) to avoid ~220ms cold-import cost; caches result, returns None if not installed.
Raw HTTP (`urllib.request`) is used only for the OAuth token endpoints (login exchange + refresh) — see `refresh_anthropic_oauth_pure()` (1036-1097) and `run_hermes_oauth_login_pure()` (1434-1561).

### Client construction — `build_anthropic_client(api_key, base_url, timeout, drop_context_1m_beta=False)` (727-853)
Auto-detects auth shape from key format and base_url:
- Kimi `/coding` endpoint → `api_key=` (x-api-key) + `User-Agent: claude-code/0.1.0` (809-817)
- `_requires_bearer_auth()` hosts (MiniMax, Azure, Palantir Foundry) → `auth_token=` (Bearer) (818-827)
- Third-party Anthropic-compatible proxies → `api_key=` (x-api-key), skip OAuth detection (828-835)
- `_is_oauth_token(api_key)` True → `auth_token=` (Bearer) + betas `["interleaved-thinking-2025-05-14","fine-grained-tool-streaming-2025-05-14","claude-code-20250219","oauth-2025-04-20"]` + headers `user-agent: claude-code/{version} (external, cli)` and `x-app: cli` (836-846)
- Else (plain API key) → `api_key=` (x-api-key) + common betas (847-851)

Callable `api_key` (for Entra ID/Azure) routes through `_build_anthropic_client_with_bearer_hook()` (651-724) which installs an httpx event hook to mint bearer tokens per request — SDK itself only accepts static-string keys.

Base URL: trailing `/v1` stripped (SDK appends `/v1/messages` itself, line 780-783,690-693). Azure endpoints get `default_query={"api-version":"2025-04-15"}`.

### OAuth token classification — `_is_oauth_token(key)` (395-420)
```python
def _is_oauth_token(key: str) -> bool:
    if not key: return False
    if key.startswith("sk-ant-api"): return False   # regular API key
    if key.startswith("sk-ant-"): return True        # setup-tokens, managed keys
    if key.startswith("eyJ"): return True             # JWT from OAuth flow
    if key.startswith("cc-"): return True              # Claude Code OAuth access tokens
    return False
```

### Claude Code credential file / Keychain reading
- `_read_claude_code_credentials_from_file()` (953-978): reads `~/.claude/.credentials.json`, JSON key `claudeAiOauth` → `{accessToken, refreshToken, expiresAt, source:"claude_code_credentials_file"}`.
- `_read_claude_code_credentials_from_keychain()` (895-950): macOS only (`platform.system()=="Darwin"`), runs `security find-generic-password -s "Claude Code-credentials" -w`, parses JSON, same `claudeAiOauth` shape, source=`"macos_keychain"`.
- `read_claude_code_credentials()` (981-1018): reconciles both sources — prefers whichever is non-expired if only one is valid, else the one with later `expiresAt`.
- `is_claude_code_token_valid(creds)` (1021-1033): `expiresAt` in ms since epoch; 60s buffer.
- Comment at line 995-998: intentionally excludes `~/.claude.json` primaryApiKey — native provider only follows OAuth/setup-token refreshable path.

### OAuth refresh
- `refresh_anthropic_oauth_pure(refresh_token, use_json=False)` (1036-1097): POSTs to `https://platform.claude.com/v1/oauth/token` then falls back to `https://console.anthropic.com/v1/oauth/token`. `client_id = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"`. grant_type=refresh_token. Returns `{access_token, refresh_token, expires_at_ms}`.
- `_refresh_oauth_token(creds)` (1100-1150): race-avoidance — re-reads live Claude Code credential sources first (Claude Code itself may have already rotated the single-use refresh token); only POSTs its own refresh if no fresher credential found. Persists result via `_write_claude_code_credentials()`.
- `_write_claude_code_credentials(access_token, refresh_token, expires_at_ms, scopes=None)` (1153-1218): writes back to `~/.claude/.credentials.json` atomically (0o600, O_EXCL temp file + os.replace), preserves `scopes` field (Claude Code >=2.1.81 requires `"user:inference"` present).

### Token resolution priority — `resolve_anthropic_token()` (1298-1345)
1. `ANTHROPIC_TOKEN` env var (Hermes-managed OAuth/setup token)
2. `CLAUDE_CODE_OAUTH_TOKEN` env var
3. Claude Code credential file/keychain (`_resolve_claude_code_token_from_credentials`), auto-refreshing if expired
4. Hermes `credential_pool` OAuth entry (`~/.hermes/auth.json`)
5. `ANTHROPIC_API_KEY` env var (plain key or legacy OAuth fallback)

`_prefer_refreshable_claude_code_token()` (1236-1255): if a static env OAuth token would shadow a refreshable Claude Code credential file entry, prefers the refreshable one so refresh can proceed.

### Native Hermes PKCE OAuth login flow (Claude Pro/Max) — lines 1391-1575
THIS IS THE FULL "Login with Claude" IMPLEMENTATION:
- `_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"` (same as Claude Code's client_id)
- `_OAUTH_TOKEN_URLS = ["https://platform.claude.com/v1/oauth/token", "https://console.anthropic.com/v1/oauth/token"]`
- `_OAUTH_TOKEN_USER_AGENT = "axios/1.7.9"` — token endpoint 429s any UA starting with `claude-code/`; mirrors Claude Code's own axios-based token exchange.
- `_OAUTH_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"`
- `_OAUTH_SCOPES = "org:create_api_key user:profile user:inference"`
- `_generate_pkce()` (1421-1431): S256 PKCE verifier/challenge.
- `run_hermes_oauth_login_pure()` (1434-1561): builds authorize URL `https://claude.ai/oauth/authorize?...`, opens browser (or prints link), prompts user to paste back `code#state`, validates CSRF `state`, POSTs code exchange to token endpoint, returns `{access_token, refresh_token, expires_at_ms}`.
- `read_hermes_oauth_credentials()` (1564-1574): reads `~/.hermes/.anthropic_oauth.json` (Hermes' OWN oauth store, separate from Claude Code's).
- Wired into CLI: `hermes_cli/auth_commands.py:224-248` — `hermes auth add anthropic --type oauth` calls `run_hermes_oauth_login_pure()` and stores result as a `PooledCredential` (auth_type=OAUTH) in the credential pool, source=`"manual:hermes_pkce"`.

### `run_oauth_setup_token()` (1348-1388)
Alternative flow: shells out to `claude setup-token` (requires Claude Code CLI installed via `npm install -g @anthropic-ai/claude-code`), then reads back credentials from file/env.

### Request/response transform (system prompt, tools, betas)
- `convert_messages_to_anthropic()` (2433-2495): OpenAI-format messages → Anthropic Messages format; extracts `system` role into separate `system` param (string or block-list w/ cache_control); handles assistant/tool/user role conversion, thinking-block signature management (`_manage_thinking_signatures`, 2277-2378), orphaned tool_use/tool_result stripping, consecutive-role merging, leading-user-turn enforcement, old-screenshot eviction.
- `convert_tools_to_anthropic()` (1688-1723): OpenAI tool defs → Anthropic `{name, description, input_schema}`; strips nullable unions/oneOf/anyOf/allOf Anthropic's validator rejects; dedups tool names; forwards `cache_control`.
- `build_anthropic_kwargs()` (2498-2733): assembles final `messages.create()` kwargs — model name normalization, max_tokens resolution/clamping, tool_choice mapping, adaptive vs manual thinking mode selection, sampling-param stripping for 4.7+, fast-mode beta injection.

### OAuth-specific request transforms inside `build_anthropic_kwargs` when `is_oauth=True` (2572-2636)
1. Prepends system block `{"type":"text","text":"You are Claude Code, Anthropic's official CLI for Claude."}` (`_CLAUDE_CODE_SYSTEM_PREFIX`, line 383) — REQUIRED for OAuth to be accepted/billed correctly against Pro/Max plan.
2. Sanitizes system prompt text: replaces "Hermes Agent"/"Hermes agent"/"hermes-agent"/"Nous Research" → "Claude Code"/"claude-code"/"Anthropic" to avoid Anthropic's content filters flagging non-Claude-Code identity.
3. Renames ALL tool names to `mcp__<name>` (double underscore) wire format — Anthropic's OAuth billing classifier treats single-underscore `mcp_` as a third-party-app fingerprint and rejects with HTTP 400 "Third-party apps now draw from extra usage, not plan limits" (verified empirically, GH-25255). Applies to both `tools[]` definitions and replayed `tool_use` blocks in message history.

### Beta headers
- `_COMMON_BETAS = ["interleaved-thinking-2025-05-14", "fine-grained-tool-streaming-2025-05-14"]` (326-329)
- `_OAUTH_ONLY_BETAS = ["claude-code-20250219", "oauth-2025-04-20"]` (345-348) — added ONLY for OAuth/setup-token auth.
- `_CONTEXT_1M_BETA = "context-1m-2025-08-07"` — NOT sent to native Anthropic by default (some subscriptions reject it, HTTP 400); only added for Azure/Bedrock.
- `_FAST_MODE_BETA = "fast-mode-2026-02-01"` — Opus 4.6 only.
- Claude Code identity spoofing required for OAuth: `_detect_claude_code_version()` (358-380) shells `claude --version` / `claude-code --version`, falls back to `_CLAUDE_CODE_VERSION_FALLBACK = "2.1.74"`. Sent as `user-agent: claude-code/{version} (external, cli)` header — Anthropic's OAuth infra intermittently 500s without correct Claude Code fingerprint/recent-enough version.

### Anthropic account usage endpoint (OAuth-only)
`agent/account_usage.py:751-770`: `_fetch_anthropic_account_usage()` — only works for OAuth tokens (`_is_oauth_token(token)` check at line 755), calls `GET https://api.anthropic.com/api/oauth/usage` with header `"anthropic-beta": "oauth-2025-04-20"`.

## 2. hermes_cli/auth.py — Anthropic registry & resolution

### PROVIDER_REGISTRY["anthropic"] (lines 312-319)
```python
"anthropic": ProviderConfig(
    id="anthropic",
    name="Anthropic",
    auth_type="api_key",
    inference_base_url="https://api.anthropic.com",
    api_key_env_vars=("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    base_url_env_var="ANTHROPIC_BASE_URL",
),
```
Note: `auth_type="api_key"` even though OAuth is supported — OAuth detection happens downstream in anthropic_adapter via key-prefix sniffing, not via a separate `auth_type`.

### `get_anthropic_key()` (486-503)
Checks env vars in order `ANTHROPIC_API_KEY -> ANTHROPIC_TOKEN -> CLAUDE_CODE_OAUTH_TOKEN` via `get_env_value_prefer_dotenv` (prefers `~/.hermes/.env` over shell env).

### Provider aliases (line 1771)
`"claude": "anthropic", "claude-code": "anthropic"` — so `provider: claude` or `provider: claude-code` in config.yaml resolves to the anthropic provider.

### `is_provider_explicitly_configured("anthropic")` (1567-1648)
Gates auto-discovery of Claude Code credentials — explicitly excludes `CLAUDE_CODE_OAUTH_TOKEN` from the "implicit env var" set (line 1606: `_IMPLICIT_ENV_VARS = {"CLAUDE_CODE_OAUTH_TOKEN"}`) so merely having Claude Code installed doesn't silently activate Anthropic as the provider — user must explicitly select it (config.yaml `model.provider: anthropic`, `active_provider` in auth.json, or an explicit env var / credential-pool entry from a manual/device-code/PKCE flow).

### config.py save/clear helpers (lines 8217-8232, found via broader grep)
`save_anthropic_oauth_token(value, save_fn=None)` — writes `ANTHROPIC_TOKEN`, clears `ANTHROPIC_API_KEY`.
`use_anthropic_claude_code_credentials(save_fn=None)` — clears BOTH `ANTHROPIC_TOKEN` and `ANTHROPIC_API_KEY` (so resolution falls through to auto-detected Claude Code credential file).
`save_anthropic_api_key(value, save_fn=None)` — writes `ANTHROPIC_API_KEY`, clears OAuth slot.

## 3. hermes_cli/runtime_provider.py — Anthropic branch

### `_resolve_explicit_runtime()` provider=="anthropic" branch (1380-1405)
When explicit_api_key/explicit_base_url given: base_url from explicit > config.yaml (if `_anthropic_base_url_override_ok`) > `https://api.anthropic.com`. api_key = explicit_api_key or `resolve_anthropic_token()` (agent.anthropic_adapter). Raises AuthError with message "No Anthropic credentials found. Set ANTHROPIC_TOKEN or ANTHROPIC_API_KEY, run 'claude setup-token', or authenticate with 'claude /login'." if unresolved.

### Main `resolve_runtime_provider()` anthropic branch (1895-1962)
- base_url resolution honors `model.base_url` from config.yaml ONLY when `model.provider=="anthropic"` AND `_anthropic_base_url_override_ok()` passes (only official anthropic.com/claude.com hosts, `.azure.com`, or hosts detected as `anthropic_messages` api_mode) — else falls back to `https://api.anthropic.com`.
- Azure endpoint special-case (`"azure.com" in base_url`): bypasses OAuth priority chain entirely, reads `key_env`/`api_key_env` hint from model_cfg, then `model_cfg["api_key"]`, then `AZURE_ANTHROPIC_KEY`/`ANTHROPIC_API_KEY` env — Claude Code OAuth tokens are NOT accepted by Azure.
- Else: `token = resolve_anthropic_token()` (full priority chain from anthropic_adapter).
- Returns `{"provider":"anthropic","api_mode":"anthropic_messages","base_url":...,"api_key":token,"source":"env",...}`.

### `_anthropic_base_url_override_ok(base_url)` (221-255)
Whitelists which base_url values are trusted to back native anthropic provider: `api.anthropic.com` / `*.anthropic.com` / `*.claude.com` / `*.azure.com` / any URL where `_detect_api_mode_for_url()==anthropic_messages` (i.e. path ends `/anthropic` or `/anthropic/v1`, or Kimi `/coding`). Prevents a stale non-Anthropic base_url in config.yaml from hijacking OAuth/setup-token traffic to e.g. OpenRouter.

### `_detect_api_mode_for_url()` (101-139)
`api.anthropic.com` exact-hostname match (rejects lookalikes/path-spoofing) → `"anthropic_messages"`. Path ending `/anthropic` or `/anthropic/v1` → `anthropic_messages`. Kimi `/coding` → `anthropic_messages`.

### Credential pool integration — `_resolve_runtime_from_pool_entry()` provider=="anthropic" branch (435-443)
`api_mode="anthropic_messages"`; base_url from config.yaml (if provider matches and override_ok) else pool entry's base_url else `https://api.anthropic.com`.

## 4. agent/model_metadata.py — Anthropic entries

### Context length table (208-228)
Bare Claude 4.6+ model IDs mapped to `1_000_000` (1M context): `claude-fable-5`, `claude-fable`, `claude-sonnet-5`, `claude-opus-4-8`/`4.8`, `claude-opus-4-7`/`4.7`, `claude-opus-4-6`/`4.6`, `claude-sonnet-4-6`/`4.6`. Catch-all `"claude": 200000` for older/unmatched Claude models.

### `api.anthropic.com` → `"anthropic"` provider mapping (line 467)

### `_query_anthropic_context_length(model, base_url, api_key)` (1867-1895)
Queries `GET {base}/v1/models?limit=1000` with headers `x-api-key`, `anthropic-version: 2023-06-01`. Explicitly SKIPPED for OAuth tokens: `if not api_key or api_key.startswith("sk-ant-oat"): return None  # OAuth tokens can't access /v1/models` (1873-1874). Only works with regular `ANTHROPIC_API_KEY`.

### Context-length resolution step 4 (2466-2472)
Only called when `provider=="anthropic"` or hostname is `api.anthropic.com`; result used only if non-OAuth key resolves it.

## 5. agent/auxiliary_client.py — Anthropic aux entries

### Aux model default (line 499)
`_API_KEY_PROVIDER_AUX_MODELS_FALLBACK["anthropic"] = "claude-haiku-4-5-20251001"`

### `_AnthropicCompletionsAdapter` / `AnthropicAuxiliaryClient` (1301-1470)
OpenAI-client-compatible wrapper over native `anthropic.Anthropic` client, used so the rest of Hermes's aux-call code (summaries, title-gen, reflection) can treat Anthropic like any OpenAI-shaped client. Delegates to `build_anthropic_kwargs`/`create_anthropic_message` from anthropic_adapter.

### `_maybe_wrap_anthropic()` (1597-1676)
Auto-wraps a plain OpenAI-style client into `AnthropicAuxiliaryClient` when the endpoint speaks Anthropic Messages (native `api.anthropic.com`, `/anthropic` suffix hosts, or `api.kimi.com/coding`), unless api_mode is explicitly non-anthropic or the `anthropic` SDK isn't installed (fails soft, falls back to OpenAI wire).

### `_try_anthropic()` (2797-2856+) — aux-client fallback chain entry for Anthropic
Gated by `is_provider_explicitly_configured("anthropic")` at the call site (auxiliary_client.py:1941-1951) — "Without this gate, Claude Code credentials get silently used as auxiliary fallback when the user's primary provider fails." Resolves token via credential pool first, else `resolve_anthropic_token()`. Detects `is_oauth = _is_oauth_token(token)` and passes to `build_anthropic_client`.

## Practical implication for the requested task
The user's stated goal ("add Anthropic OAuth for Claude Pro/Max login") is ALREADY FULLY IMPLEMENTED in this codebase:
- `hermes auth add anthropic --type oauth` → PKCE browser login flow (agent/anthropic_adapter.py:1434-1561)
- Auto-detection + refresh of Claude Code's own `~/.claude/.credentials.json` / macOS Keychain credentials
- Correct OAuth request shaping (Claude Code system prompt prefix, mcp__ tool renaming, required beta headers, Claude Code UA spoofing)
- Full priority-ordered token resolution chain in `resolve_anthropic_token()`

A "plugin/patch" task should verify: (a) whether this is exposed in `hermes model` interactive wizard, (b) whether it's documented, (c) whether any of it is broken/incomplete, rather than re-implementing OAuth from scratch. Any new work should extend/wire this existing implementation, not duplicate it.
