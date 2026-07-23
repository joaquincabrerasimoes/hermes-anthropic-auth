Name: Provider plugin: OAuth needs core edits
Keywords: provider plugin, OAuth, api_mode, auth_type, PROVIDER_REGISTRY, anthropic_messages
FilePathReference: providers/base.py, providers/__init__.py, hermes_cli/auth.py, agent/auxiliary_client.py, hermes_cli/main.py
Short Description: plugins/model-providers/ auto-wires only auth_type=api_key; OAuth needs hardcoded core-file branches, no plugin callback hook exists.
---
FINDING: hermes-agent's "model provider plugin" system (plugins/model-providers/<name>/, providers/__init__.py, providers/base.py ProviderProfile) supports FULL drop-in zero-core-edit registration ONLY for auth_type="api_key" providers. This is verified with exact code, not just docs.

1. ProviderProfile (providers/base.py:38-232) fields: name, api_mode(default "chat_completions"), aliases, display_name, description, signup_url, env_vars, base_url, models_url, auth_type(default "api_key", comment lists api_key|oauth_device_code|oauth_external|copilot|aws_sdk), supports_health_check, supports_vision, supports_vision_tool_messages, fallback_models, hostname, default_headers, fixed_temperature, default_max_tokens, default_aux_model. Hooks (overridable methods, NOT fields): get_hostname(), prepare_messages(), build_extra_body(), build_api_kwargs_extras(), default_vision_model(), get_max_tokens(), fetch_models(). NO field/hook exists for: token refresh callback, OAuth flow callback, custom HTTP client/adapter injection, or credential-resolution hook. The dataclass is purely declarative (base_url/env_vars/headers/message-shaping) — it never owns credential acquisition (base.py:7-9 docstring explicitly states this).

2. Discovery (providers/__init__.py `_discover_providers()` lines 140-191): lazy, scans plugins/model-providers/ (bundled) then $HERMES_HOME/plugins/model-providers/ (user, last-writer-wins via register_provider() lines 53-62), then legacy providers/*.py via pkgutil. This part IS fully generic/pluggable for ANY provider regardless of auth_type — the ProviderProfile object itself always registers fine.

3. THE GAP is downstream consumption, not registration. Two separate hardcoded per-provider dispatch points prove OAuth cannot be plugin-driven:

   a) hermes_cli/auth.py:447-478 — auto-extends PROVIDER_REGISTRY (a SEPARATE dataclass ProviderConfig, auth.py:159-174, distinct from providers.base.ProviderProfile) from any registered plugin ONLY `if _pp.auth_type != "api_key" or not _pp.env_vars: continue` (line 455) — non-api_key profiles are skipped entirely, i.e. never added to PROVIDER_REGISTRY at all.

   b) agent/auxiliary_client.py:5382-5395 — the actual client-resolution dispatcher for OAuth providers:
   ```
   elif pconfig.auth_type in {"oauth_device_code", "oauth_external"}:
       # OAuth providers — route through their specific try functions
       if provider == "nous":
           return resolve_provider_client("nous", model, async_mode)
       if provider == "openai-codex":
           return resolve_provider_client("openai-codex", model, async_mode)
       if provider == "xai-oauth":
           return resolve_provider_client("xai-oauth", model, async_mode)
       # Other OAuth providers not directly supported
       ...
       return None, None
   ```
   Literal string-equality if/elif on hardcoded provider IDs. A new OAuth plugin's provider name never matches → falls through to `return None, None`. No plugin-supplied callback/adapter is ever consulted.

   c) Each existing OAuth provider needs its own hand-written credential-refresh function in hermes_cli/auth.py: resolve_qwen_runtime_credentials (auth.py:2462), resolve_codex_runtime_credentials (auth.py:3725), resolve_xai_oauth_runtime_credentials (auth.py:4690), resolve_nous_runtime_credentials (auth.py:5857), resolve_minimax_oauth_runtime_credentials (auth.py:8199), plus bespoke login functions (_xai_oauth_device_code_login auth.py:7571, _minimax_oauth_login auth.py:7978). No generic OAuth engine exists that a plugin could parameterize.

   d) hermes_cli/main.py:3286-3359 `select_provider_and_model()` — explicit elif chain hardcodes OAuth providers ("nous","openai-codex","xai-oauth","qwen-oauth","minimax-oauth", each calling bespoke _model_flow_<x>()). Only the final branch (3337-3359) is generic via `_is_profile_api_key_provider()` (main.py:2920-2932, checks `_p.auth_type == "api_key"`) → `_model_flow_api_key_provider`. Non-api_key plugins never reach this generic path.

4. api_mode reuse: a plugin CAN declare `api_mode="anthropic_messages"` (plugins/model-providers/anthropic/__init__.py:47) and reuse EXISTING Anthropic Messages wire-protocol dispatch already hardcoded throughout the codebase (65+ matches of `api_mode == "anthropic_messages"` across agent/agent_init.py, agent/chat_completion_helpers.py, agent/conversation_loop.py, run_agent.py, hermes_cli/models.py). Works only because "anthropic_messages" already exists as a first-class hardcoded mode; a plugin cannot invent a NEW api_mode without editing run_agent.py/agent_init.py/chat_completion_helpers.py/conversation_loop.py/auxiliary_client.py/models.py (per adding-providers.md:39,270-304).

5. plugins/model-providers/anthropic/__init__.py uses auth_type="api_key" (NOT true OAuth) — env_vars includes CLAUDE_CODE_OAUTH_TOKEN treated as static bearer token. The actual "OAuth" UX (main.py:4311 `_run_anthropic_oauth_flow`) shells out to Claude Code CLI or asks user to paste a token manually — Hermes itself implements no PKCE/device-code flow or auto-refresh for Anthropic. Even Anthropic's OAuth support required hardcoded PROVIDER_REGISTRY entry (auth.py:312-319) + hardcoded main.py dispatch (main.py:3325-3326) + hardcoded login flow (main.py:4311+).

6. Docs corroborate exactly: website/docs/developer-guide/adding-providers.md:96-124 "Fast path: Simple API-key providers" vs :126-136 "Full path: OAuth and complex providers" (lists required core files: hermes_cli/auth.py, models.py, runtime_provider.py, main.py, agent/auxiliary_client.py, agent/model_metadata.py, agent/<provider>_adapter.py, run_agent.py). website/docs/developer-guide/model-provider-plugin.md:203: "`auth_type` gates which codepaths treat your provider as a 'simple api-key provider' — if it's not `api_key`, the PluginManager still records the manifest but Hermes' CLI-level automation ... may skip over it."

CONCLUSION: A new OAuth-based native-adapter provider (Anthropic Claude Pro/Max style, PKCE/device-code + token refresh) CANNOT be implemented entirely as a drop-in plugin under plugins/model-providers/<name>/ with zero core edits. It can reuse the existing anthropic_messages api_mode's request/response dispatch code, but credential acquisition/refresh and CLI wiring require edits to hermes_cli/auth.py (ProviderConfig + resolve_<x>_runtime_credentials + login fn), agent/auxiliary_client.py (oauth branch at 5382), and hermes_cli/main.py (elif chain + _model_flow_<x>). The plugin system's "zero-edit" guarantee applies exclusively to the auth_type="api_key" fast path.