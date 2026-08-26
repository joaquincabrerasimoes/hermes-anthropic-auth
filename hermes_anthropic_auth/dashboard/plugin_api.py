"""Dashboard backend routes for hermes-anthropic-auth.

Mounted by the Hermes web dashboard at
``/api/plugins/hermes-anthropic-auth/`` (per the dashboard plugin backend
contract -- see "Extending the Dashboard" in the hermes-agent docs). Runs
inside the dashboard's own FastAPI process, so it uses a plain absolute
import of the pip-installed ``hermes_anthropic_auth`` package rather than a
relative import (this file is loaded as a standalone module by the
dashboard, not as part of the package it lives inside).

Provides:
- ``GET  /profiles``      -- list Hermes profiles on this machine
- ``GET  /status``        -- this plugin's Anthropic OAuth status for a profile
- ``POST /oauth/start``   -- begin a PKCE login, returns a claude.ai URL
- ``POST /oauth/complete``-- finish login with the pasted ``CODE#STATE``

Every route catches its own exceptions and returns a JSON error body
instead of raising -- a stack trace here should never take down the
dashboard process or another plugin's routes.
"""

from __future__ import annotations

import logging
import threading
import time

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

try:
    from hermes_anthropic_auth import oauth_web, profile_store

    _IMPORT_ERROR: str | None = None
except Exception as exc:  # noqa: BLE001 - surfaced via every route below
    oauth_web = None  # type: ignore[assignment]
    profile_store = None  # type: ignore[assignment]
    _IMPORT_ERROR = str(exc)
    logger.exception("hermes-anthropic-auth: dashboard backend failed to import package")

_pending_lock = threading.Lock()
_pending: dict[str, dict] = {}  # state -> {"verifier": str, "created": float}
_PENDING_TTL_SECONDS = 600


def _prune_pending() -> None:
    now = time.time()
    with _pending_lock:
        for state in [s for s, v in _pending.items() if now - v["created"] > _PENDING_TTL_SECONDS]:
            _pending.pop(state, None)


@router.get("/profiles")
async def get_profiles():
    if profile_store is None:
        return {"profiles": [{"name": "default"}], "error": _IMPORT_ERROR}
    try:
        return {"profiles": profile_store.list_profiles()}
    except Exception as exc:  # noqa: BLE001
        logger.exception("hermes-anthropic-auth: list_profiles failed")
        return {"profiles": [{"name": "default"}], "error": str(exc)}


@router.get("/status")
async def get_status(profile: str = "default"):
    if profile_store is None:
        return {"profile": profile, "connected": False, "error": _IMPORT_ERROR}
    try:
        creds = profile_store.read_anthropic_pool(profile)
        ours = [c for c in creds if str(c.get("source", "")).startswith(profile_store.SOURCE_PREFIX)]
        return {
            "profile": profile,
            "connected": bool(ours),
            "credential_count": len(creds),
            "entries": [
                {
                    "label": c.get("label"),
                    "source": c.get("source"),
                    "expires_at_ms": c.get("expires_at_ms"),
                }
                for c in ours
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("hermes-anthropic-auth: status check failed")
        return {"profile": profile, "connected": False, "error": str(exc)}


@router.post("/oauth/start")
async def oauth_start():
    if oauth_web is None:
        return {"error": _IMPORT_ERROR}
    _prune_pending()
    try:
        pkce = oauth_web.generate_pkce()
        with _pending_lock:
            _pending[pkce.state] = {"verifier": pkce.verifier, "created": time.time()}
        return {"authorize_url": oauth_web.build_authorize_url(pkce), "state": pkce.state}
    except Exception as exc:  # noqa: BLE001
        logger.exception("hermes-anthropic-auth: oauth start failed")
        return {"error": str(exc)}


class CompleteBody(BaseModel):
    code_state: str
    profile: str = "default"


@router.post("/oauth/complete")
async def oauth_complete(body: CompleteBody):
    if oauth_web is None or profile_store is None:
        return {"ok": False, "error": _IMPORT_ERROR}

    _prune_pending()

    try:
        code, state = oauth_web.parse_code_state(body.code_state)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    with _pending_lock:
        pending = _pending.pop(state, None)

    if pending is None:
        return {
            "ok": False,
            "error": "No matching login attempt found (it expired after 10 minutes, "
            "or was already used). Click \"Login with Claude\" again.",
        }

    try:
        tokens = oauth_web.exchange_code(code, state, pending["verifier"])
    except Exception as exc:  # noqa: BLE001
        logger.exception("hermes-anthropic-auth: token exchange failed")
        return {"ok": False, "error": f"Token exchange failed: {exc}"}

    if not tokens.get("access_token"):
        return {"ok": False, "error": "Anthropic did not return an access token."}

    try:
        profile_store.write_anthropic_oauth_credential(
            body.profile,
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token"),
            expires_at_ms=tokens.get("expires_at_ms"),
            scopes=tokens.get("scopes"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("hermes-anthropic-auth: saving credential failed")
        return {"ok": False, "error": f"Login succeeded but saving the credential failed: {exc}"}

    return {"ok": True, "profile": body.profile}
