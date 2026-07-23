"""Monkey-patch ``agent.anthropic_adapter.build_anthropic_client``.

Why a monkey-patch instead of a first-class provider plugin: Hermes's plugin
system (``providers/`` / ``plugins/model-providers/``) only auto-wires
``auth_type="api_key"`` providers. OAuth credential resolution, refresh, and
CLI wiring for native providers are hardcoded per-provider in Hermes core
(confirmed: ``agent/auxiliary_client.py``'s OAuth client dispatch is a
literal ``if provider == "..."`` chain with no plugin hook). Since Hermes
already ships a fully-working native Anthropic OAuth provider, there is
nothing to *add* — the actual bug is that outgoing OAuth requests don't look
enough like genuine Claude Code traffic and get false-positive-blocked by
Anthropic's billing classifier. Fixing that means rewriting bytes on the
wire for an existing code path, which the plugin system has no declarative
hook for. A monkey-patch of the single confirmed choke point is the
narrowest correct fix.

Why this specific choke point is safe: every call site in Hermes
(``run_agent.py``, ``agent/agent_init.py``, ``agent/agent_runtime_helpers.py``,
``agent/chat_completion_helpers.py``, ``agent/auxiliary_client.py`` — 9 sites
total) imports ``build_anthropic_client`` with a FUNCTION-LOCAL
``from agent.anthropic_adapter import build_anthropic_client``, re-resolving
the name from the module's ``__dict__`` on every call. Reassigning
``agent.anthropic_adapter.build_anthropic_client`` before any of those calls
happen is therefore sufficient to intercept all of them — this is the same
pattern Hermes's own test suite uses to mock this function
(``patch("agent.anthropic_adapter.build_anthropic_client", ...)``).

Scope: only clients built for genuine OAuth tokens
(``anthropic_adapter._is_oauth_token(api_key)`` — Claude Pro/Max subscription
auth) get the sanitizing transport attached. Plain API keys, Bedrock, Azure
Entra ID, and third-party proxy clients are never touched — zero behavior
change for non-OAuth users.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_installed = False
_original_build_anthropic_client = None


def is_installed() -> bool:
    return _installed


def install() -> bool:
    """Patch ``build_anthropic_client``. Idempotent. Returns True on success."""
    global _installed, _original_build_anthropic_client

    if _installed:
        return True

    try:
        from agent import anthropic_adapter
    except ImportError:
        logger.warning(
            "hermes-anthropic-auth: agent.anthropic_adapter not importable "
            "(not running inside hermes-agent?) — patch not installed"
        )
        return False

    original = getattr(anthropic_adapter, "build_anthropic_client", None)
    if original is None:
        logger.warning(
            "hermes-anthropic-auth: agent.anthropic_adapter.build_anthropic_client "
            "not found — hermes-agent internals may have changed, patch not installed"
        )
        return False

    _original_build_anthropic_client = original

    def patched_build_anthropic_client(
        api_key,
        base_url=None,
        timeout=None,
        *,
        drop_context_1m_beta: bool = False,
    ):
        client = _original_build_anthropic_client(
            api_key,
            base_url,
            timeout,
            drop_context_1m_beta=drop_context_1m_beta,
        )
        try:
            _maybe_wrap_client(client, api_key, anthropic_adapter)
        except Exception:  # noqa: BLE001 - never let our wrapping break auth
            logger.exception(
                "hermes-anthropic-auth: failed to attach OAuth sanitizing transport"
            )
        return client

    anthropic_adapter.build_anthropic_client = patched_build_anthropic_client
    _installed = True
    logger.info(
        "hermes-anthropic-auth: build_anthropic_client patched — OAuth requests "
        "will be sanitized before send"
    )
    return True


def uninstall() -> None:
    """Restore the original ``build_anthropic_client``. Mainly for tests."""
    global _installed, _original_build_anthropic_client

    if not _installed or _original_build_anthropic_client is None:
        return

    try:
        from agent import anthropic_adapter

        anthropic_adapter.build_anthropic_client = _original_build_anthropic_client
    except ImportError:
        pass

    _installed = False
    _original_build_anthropic_client = None


def _maybe_wrap_client(client, api_key, anthropic_adapter_module) -> None:
    if callable(api_key):
        return  # Entra ID / callable-token path — not consumer OAuth, skip.

    is_oauth_token = getattr(anthropic_adapter_module, "_is_oauth_token", None)
    if is_oauth_token is None or not is_oauth_token(api_key):
        return  # plain API key (or unrecognized shape) — leave untouched.

    from .transport import OAuthRequestSanitizingTransport

    http_client = getattr(client, "_client", None)
    if http_client is None:
        return

    current_transport = getattr(http_client, "_transport", None)
    if current_transport is None:
        return
    if isinstance(current_transport, OAuthRequestSanitizingTransport):
        return  # already wrapped — defensive, shouldn't normally happen.

    version_provider = getattr(
        anthropic_adapter_module, "_get_claude_code_version", None
    )
    if version_provider is None:
        from .billing_header import FALLBACK_CLAUDE_CODE_VERSION

        def version_provider() -> str:  # type: ignore[no-redef]
            return FALLBACK_CLAUDE_CODE_VERSION

    http_client._transport = OAuthRequestSanitizingTransport(
        current_transport, version_provider=version_provider
    )
