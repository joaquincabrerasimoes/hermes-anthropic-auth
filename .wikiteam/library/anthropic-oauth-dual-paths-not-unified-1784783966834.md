Name: Anthropic OAuth: dual paths, not unified
Keywords: anthropic, oauth, claude, model_setup_flows, PROVIDER_REGISTRY, auth_commands
FilePathReference: hermes_cli/model_setup_flows.py, hermes_cli/main.py, agent/anthropic_adapter.py, hermes_cli/auth_commands.py, hermes_cli/auth.py
Short Description: hermes-agent already ships two separate Anthropic OAuth login paths, not yet unified.
---

hermes-agent (Nous Research CLI) ALREADY has Claude Pro/Max OAuth login — but via TWO divergent, non-unified code paths:

1. `hermes model` interactive picker → `_model_flow_anthropic()` (hermes_cli/model_setup_flows.py:2912) → on missing creds, shows 3-choice menu:
   "1. Claude Pro/Max subscription (OAuth login)" / "2. Anthropic API key" / "3. Cancel" (model_setup_flows.py:2989-2993)
   → choice "1" calls `_run_anthropic_oauth_flow()` (hermes_cli/main.py:4311), which SHELLS OUT to external `claude setup-token` CLI subprocess (agent/anthropic_adapter.py:1348 `run_oauth_setup_token()`). Requires `npm install -g @anthropic-ai/claude-code` installed. If `claude` binary missing → FileNotFoundError → falls back to manual paste of an existing setup-token.

2. `hermes auth add anthropic --type oauth` (hermes_cli/auth_commands.py:224-248) → calls `anthropic_adapter.run_hermes_oauth_login_pure()` (agent/anthropic_adapter.py:1434) — Hermes' OWN native browser PKCE OAuth flow (client_id "9d1c250a-e61b-44d9-88ed-5944d1962f5e", opens https://claude.ai/oauth/authorize, no external CLI needed, user pastes auth code back). This is the SAME UX pattern used by openai-codex/xai-oauth/qwen-oauth device-code flows conceptually but is PKCE not device-code.

Key gap: path #2 (the CLI-independent native OAuth) is NOT exposed from the `hermes model` interactive picker (_model_flow_anthropic only offers path #1, the external-CLI-dependent one). `_OAUTH_CAPABLE_PROVIDERS = {"anthropic", "nous", "openai-codex", "xai-oauth", "qwen-oauth", "minimax-oauth"}` (auth_commands.py:37) drives the generic `hermes auth add` API-key-vs-OAuth choice menu (auth_commands.py:678-689), separate from `hermes model`'s bespoke per-provider flows.

Registry inconsistency: PROVIDER_REGISTRY["anthropic"].auth_type = "api_key" (auth.py:315) even though OAuth is supported — unlike openai-codex/xai-oauth/qwen-oauth which are auth_type="oauth_external" (auth.py:189,203,209). This means get_auth_status("anthropic") routes to get_api_key_provider_status (auth.py:6644-6647), i.e. env-var/dotenv-only status check — it does NOT check for a valid Hermes-native PKCE token file (~/.hermes/.anthropic_oauth.json) or Claude Code creds in that generic status path; `_model_flow_anthropic` handles that detection itself, ad hoc, by directly calling get_anthropic_key() + read_claude_code_credentials().

`hermes logout --provider` choices=["nous","openai-codex","xai-oauth","spotify"] (hermes_cli/subcommands/logout.py:24) — "anthropic" is MISSING from logout's provider choices despite being OAuth-capable.

CANONICAL_PROVIDERS entry: ProviderEntry("anthropic", "Anthropic", "Anthropic (Claude models via API key or Claude Code)") — models.py:1072. Description string doesn't mention "OAuth"/"Pro/Max" despite the picker supporting it.

Implication for any future UX work: to add a unified "Login with browser" choice to `hermes model`'s anthropic branch, the correct native (non-external-CLI) building block is `agent.anthropic_adapter.run_hermes_oauth_login_pure()` — already used by `hermes auth add anthropic --type oauth` — NOT `run_oauth_setup_token()` (external CLI subprocess) which is what `_model_flow_anthropic` currently calls first.
