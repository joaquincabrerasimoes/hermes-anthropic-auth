"""httpx transport wrapper that rewrites outgoing Anthropic OAuth requests.

Wraps an existing ``httpx.BaseTransport`` (whatever the ``anthropic`` SDK's
``httpx.Client`` was already using — normally ``httpx.HTTPTransport``) and
intercepts ``POST .../v1/messages`` requests to rewrite the JSON body via
``body_rewrite.rewrite_oauth_body`` before handing off to the real transport.

Design constraints, all deliberate:

- **Fail-open.** Any exception while inspecting/rewriting a request falls
  back to sending the ORIGINAL, unmodified request. A bug in this plugin
  must never break the user's actual API calls.
- **Attribute passthrough (`__getattr__`).** Hermes's own interrupt-handling
  code walks ``client._client._transport._pool._connections`` to force-close
  sockets (``agent/agent_runtime_helpers.py::_iter_pool_sockets``). Wrapping
  the transport must not hide that internal shape, so any attribute we don't
  explicitly define proxies through to the wrapped transport.
- **Only touches `/v1/messages` POST bodies.** Every other request (model
  listing, etc.) passes through completely untouched.
"""

from __future__ import annotations

import json
import logging
from typing import Callable

import httpx

from .body_rewrite import rewrite_oauth_body

logger = logging.getLogger(__name__)

_MESSAGES_PATH_SUFFIX = "/v1/messages"


class OAuthRequestSanitizingTransport(httpx.BaseTransport):
    """Wraps a real transport; sanitizes OAuth /v1/messages request bodies."""

    def __init__(
        self,
        wrapped: httpx.BaseTransport,
        *,
        version_provider: Callable[[], str],
    ) -> None:
        self._wrapped = wrapped
        self._version_provider = version_provider

    def __getattr__(self, name: str):
        # Proxy anything we don't define (e.g. `_pool`) to the real transport
        # so introspection code that assumes the default transport shape
        # keeps working.
        return getattr(self._wrapped, name)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            request = self._maybe_rewrite(request)
        except Exception:  # noqa: BLE001 - fail-open by design, see module docstring
            logger.exception(
                "hermes-anthropic-auth: request sanitization failed, "
                "sending request unmodified"
            )
        return self._wrapped.handle_request(request)

    def close(self) -> None:
        self._wrapped.close()

    def _maybe_rewrite(self, request: httpx.Request) -> httpx.Request:
        if request.method != "POST":
            return request
        if not request.url.path.endswith(_MESSAGES_PATH_SUFFIX):
            return request

        raw = request.content
        if not raw:
            return request

        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            return request

        version = self._safe_version()
        rewritten = rewrite_oauth_body(parsed, version=version)
        new_body = json.dumps(rewritten).encode("utf-8")

        headers = httpx.Headers(request.headers)
        headers.pop("content-length", None)

        return httpx.Request(
            method=request.method,
            url=request.url,
            headers=headers,
            content=new_body,
            extensions=request.extensions,
        )

    def _safe_version(self) -> str:
        from .billing_header import FALLBACK_CLAUDE_CODE_VERSION

        try:
            version = self._version_provider()
        except Exception:  # noqa: BLE001
            return FALLBACK_CLAUDE_CODE_VERSION
        if isinstance(version, str) and version:
            return version
        return FALLBACK_CLAUDE_CODE_VERSION
