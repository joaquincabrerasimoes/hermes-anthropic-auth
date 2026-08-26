"""Standalone Anthropic Claude Pro/Max PKCE OAuth helper for the web dashboard.

Deliberately does NOT import anything from ``agent.anthropic_adapter`` (or any
other hermes-agent internal). The OAuth client id / endpoints / scopes below
are the same public PKCE client hermes-agent's own native CLI login
(``run_hermes_oauth_login_pure()``) and Anthropic's Claude Code CLI use --
protocol constants, not private symbols -- so hardcoding them here keeps the
dashboard login flow working even if hermes-agent renames or refactors its
internal adapter module (this plugin already assumes that risk for
``patch.py``; no need to double it here).

Flow (mirrors the CLI flow, but split into two HTTP-friendly steps since a
web backend can't block on ``input()``):

1. ``generate_pkce()`` + ``build_authorize_url()`` -- server hands the
   frontend a claude.ai URL to open in a new tab.
2. User approves on Anthropic's site and is shown a ``CODE#STATE`` string
   (Anthropic's OAuth redirect_uri is hardcoded to a console.anthropic.com
   page, not ours -- there is no way to auto-capture the code via HTTP
   redirect). User pastes it back into the dashboard form.
3. ``parse_code_state()`` + ``exchange_code()`` -- server completes the
   token exchange.

Every network call is best-effort across both known Anthropic token URLs and
raises a plain ``RuntimeError``/``ValueError`` on failure -- callers (the
FastAPI routes in ``dashboard/plugin_api.py``) are responsible for catching
these and returning a JSON error instead of a 500, consistent with this
project's fail-open policy.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
OAUTH_AUTHORIZE_URL = "https://claude.ai/oauth/authorize"
OAUTH_REDIRECT_URI = "https://console.anthropic.com/oauth/code/callback"
OAUTH_SCOPES = "org:create_api_key user:profile user:inference"
OAUTH_TOKEN_URLS = (
    "https://platform.claude.com/v1/oauth/token",
    "https://console.anthropic.com/v1/oauth/token",
)
# Anthropic's token endpoint 429s any User-Agent starting with "claude-code/".
OAUTH_TOKEN_USER_AGENT = "axios/1.7.9"


@dataclass(frozen=True)
class PkceChallenge:
    verifier: str
    challenge: str
    state: str


def generate_pkce() -> PkceChallenge:
    """Generate an S256 PKCE verifier/challenge pair plus a CSRF state token."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    state = secrets.token_urlsafe(24)
    return PkceChallenge(verifier=verifier, challenge=challenge, state=state)


def build_authorize_url(pkce: PkceChallenge) -> str:
    params = {
        "code": "true",
        "client_id": OAUTH_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OAUTH_REDIRECT_URI,
        "scope": OAUTH_SCOPES,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
        "state": pkce.state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def parse_code_state(raw: str) -> tuple[str, str]:
    """Parse the ``CODE#STATE`` string Anthropic shows the user after approval."""
    raw = (raw or "").strip()
    if "#" not in raw:
        raise ValueError(
            "Expected a 'CODE#STATE' string (the value Anthropic shows after "
            "you approve) -- got something without a '#'."
        )
    code, _, state = raw.partition("#")
    code, state = code.strip(), state.strip()
    if not code or not state:
        raise ValueError("Malformed code#state pair -- both parts must be non-empty.")
    return code, state


def exchange_code(code: str, state: str, verifier: str) -> dict[str, Any]:
    """Exchange an authorization code for tokens. Tries both known token URLs."""
    body = {
        "grant_type": "authorization_code",
        "client_id": OAUTH_CLIENT_ID,
        "code": code,
        "state": state,
        "redirect_uri": OAUTH_REDIRECT_URI,
        "code_verifier": verifier,
    }
    return _post_token(body)


def refresh_token(refresh_token_value: str) -> dict[str, Any]:
    """Exchange a refresh token for a new access token. Not currently wired
    into any automatic caller -- provided for completeness / future use by a
    background refresh route."""
    body = {
        "grant_type": "refresh_token",
        "client_id": OAUTH_CLIENT_ID,
        "refresh_token": refresh_token_value,
    }
    return _post_token(body)


def _post_token(body: dict[str, Any]) -> dict[str, Any]:
    headers = {"Content-Type": "application/json", "User-Agent": OAUTH_TOKEN_USER_AGENT}
    last_error: Exception | None = None
    for url in OAUTH_TOKEN_URLS:
        try:
            resp = httpx.post(url, json=body, headers=headers, timeout=30.0)
            resp.raise_for_status()
            return _normalize_token_response(resp.json())
        except Exception as exc:  # noqa: BLE001 - try the next known endpoint
            last_error = exc
            continue
    raise RuntimeError(f"OAuth token request failed against all endpoints: {last_error}")


def _normalize_token_response(data: dict[str, Any]) -> dict[str, Any]:
    expires_at_ms = data.get("expires_at_ms")
    if expires_at_ms is None and data.get("expires_in") is not None:
        expires_at_ms = int(time.time() * 1000) + int(data["expires_in"]) * 1000
    return {
        "access_token": data.get("access_token"),
        "refresh_token": data.get("refresh_token"),
        "expires_at_ms": int(expires_at_ms) if expires_at_ms is not None else None,
        "scopes": data.get("scope"),
    }
