Name: Anthropic SDK: single choke point
Keywords: build_anthropic_client, anthropic_adapter, http_client, event_hooks, OAuth interception
FilePathReference: agent/anthropic_adapter.py
Short Description: build_anthropic_client() is the ONLY Anthropic SDK constructor call path repo-wide; Entra hook pattern shows http_client event_hooks precedent.
---
Confirmed by full-repo grep (excl. tests) for `Anthropic(`, `AsyncAnthropic(`, `AnthropicBedrock(`, `AnthropicVertex(`:

Only 3 SDK constructor call sites exist, all in agent/anthropic_adapter.py:
- anthropic_adapter.py:724 `_anthropic_sdk.Anthropic(**kwargs)` inside `_build_anthropic_client_with_bearer_hook()` (Azure Entra ID path — already passes `http_client=` built via `agent.azure_identity_adapter.build_bearer_http_client()`)
- anthropic_adapter.py:853 `_anthropic_sdk.Anthropic(**kwargs)` inside `build_anthropic_client()` (main sync path — static key / OAuth Bearer string path, NO http_client passed here)
- anthropic_adapter.py:885 `_anthropic_sdk.AnthropicBedrock(...)` inside `build_anthropic_bedrock_client()` (boto3 creds, not OAuth-relevant)

No `AsyncAnthropic` used anywhere in the entire codebase (0 hits).

agent/credential_pool.py does NOT construct any SDK client — only manages OAuth token storage/rotation (read_credential_pool/write_credential_pool).

agent/auxiliary_client.py has ZERO direct `Anthropic(...)` calls. All 5 call sites (lines 1653/1663, 2799/2851, 5055/5056) import and call `build_anthropic_client()` from anthropic_adapter — confirmed no duplicate/parallel construction path exists anywhere.

run_agent.py stores result in `self._anthropic_client` (NOT `self.client` — that's set to None for anthropic_messages mode, see agent_init.py:956,1005). Rebuilt (not once) at: init (agent_init.py:1003), credential refresh (run_agent.py:4798), credential swap (run_agent.py:4931), explicit rebuild after interrupt (run_agent.py:5024, called from conversation_loop.py:3095), per-request local client (run_agent.py:4500, NOT assigned to self._anthropic_client — separate fresh client per in-flight call for thread-safety), model switch (agent_runtime_helpers.py:2141), snapshot restore (agent_runtime_helpers.py:1191,1363), fallback model (chat_completion_helpers.py:1770). All 9 sites call build_anthropic_client()/build_anthropic_bedrock_client() identically — zero exceptions.

EXISTING PATTERN for header-rewrite-via-httpx-hook (template to follow/extend for OAuth interception):
agent/azure_identity_adapter.py:462-540 `build_bearer_http_client(token_provider, **httpx_kwargs)`:
```python
def _inject_bearer(request: "httpx.Request") -> None:
    token = materialize_bearer_for_http(token_provider)
    for header_name in ("Authorization","authorization","Api-Key","api-key","X-Api-Key","x-api-key"):
        request.headers.pop(header_name, None)
    request.headers["Authorization"] = f"Bearer {token}"

return httpx.Client(event_hooks={"request": [_inject_bearer]}, **httpx_kwargs)
```
Wired in at anthropic_adapter.py:695-699 into `kwargs["http_client"]` then `Anthropic(**kwargs)`.

GAP: this hook only rewrites headers (request.headers), never JSON body. No existing precedent anywhere in repo for rewriting outgoing JSON body via httpx — would require new code, likely a custom `transport=` (httpx.BaseTransport subclass overriding handle_request) rather than event_hooks, since event_hooks receive Request but body/content mutation via hook is unreliable especially for pre-encoded/streamed content. Must verify against httpx docs before design.

RISK: agent/agent_runtime_helpers.py:3152-3155 reads `client._client._transport` for TCP-socket force-close on interrupt — any custom transport injected must still support this introspection path or that force-close logic silently breaks.

pyproject.toml:145 pins `anthropic==0.87.0` exact (optional extra, not core dep). uv.lock:298 confirms `version = "0.87.0"`.

OAuth branch specifically: anthropic_adapter.py:836-846 (`elif _is_oauth_token(api_key):`) currently does NOT pass http_client — only sets `auth_token` + `default_headers` (anthropic-beta, user-agent claude-code fingerprint, x-app). Any OAuth-only interception patch must extend precisely this branch (or wrap build_anthropic_client itself) to inject http_client conditionally only when api_key is OAuth-shaped, without affecting the plain API-key branch (else at 847-851) or third-party/bearer-auth branches (818-835).