"""Resolve Hermes profiles and read/write the Anthropic slot of their
credential pool (``auth.json``) without importing any hermes-agent internal
module -- only the documented, stable on-disk layout is relied on:

- "Profiles: Running Multiple Agents" -- a profile is a directory,
  ``~/.hermes`` for ``default``, ``~/.hermes/profiles/<name>`` for named
  profiles; ``HERMES_HOME`` is the active profile's directory.
- "Credential Pools" -- pool state lives in ``<profile home>/auth.json``
  under the ``credential_pool`` key, keyed by provider name, as a list of
  credential dicts.

The web dashboard is a machine-level process that can address *any*
profile (see docs: "the dashboard's profile switcher... no per-profile
dashboard needed"), so this module always resolves the *root* ``~/.hermes``
first (regardless of which profile the dashboard process itself happens to
be running under) and lists/addresses profiles relative to that root.

Every public function is best-effort: read failures return empty results
rather than raising, and writes use a read-merge-atomic-replace pattern so a
failure never corrupts an existing ``auth.json``. Callers (the FastAPI
routes in ``dashboard/plugin_api.py``) still wrap calls in try/except per
this project's fail-open policy -- this module raises only from
``write_anthropic_oauth_credential`` on genuine I/O errors, by design, so
the caller can surface a real error to the user instead of silently
pretending the login succeeded.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

#: Prefix used for the ``source`` field of credentials this plugin writes,
#: so ``read_anthropic_pool``/status routes can distinguish "ours" from
#: entries created by other means (env var, Claude Code file, `hermes auth`).
SOURCE_PREFIX = "manual:hermes-anthropic-auth"


def _root_hermes_home() -> Path:
    """Resolve the root ``~/.hermes`` directory (the ``default`` profile),
    regardless of which profile this process is currently running under.
    """
    raw = os.environ.get("HERMES_HOME")
    home = Path(raw).expanduser() if raw else (Path.home() / ".hermes")
    # If HERMES_HOME currently points at .../profiles/<name>, walk up to root.
    if home.parent.name == "profiles":
        return home.parent.parent
    return home


def list_profiles() -> list[dict[str, str]]:
    """Return ``[{"name": "default", "home": "<path>"}, ...]``, default first."""
    root = _root_hermes_home()
    profiles = [{"name": "default", "home": str(root)}]
    profiles_dir = root / "profiles"
    if profiles_dir.is_dir():
        for child in sorted(profiles_dir.iterdir()):
            if child.is_dir():
                profiles.append({"name": child.name, "home": str(child)})
    return profiles


def profile_home(name: str) -> Path:
    root = _root_hermes_home()
    if not name or name == "default":
        return root
    return root / "profiles" / name


def _auth_json_path(name: str) -> Path:
    return profile_home(name) / "auth.json"


def read_anthropic_pool(name: str) -> list[dict[str, Any]]:
    path = _auth_json_path(name)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - corrupt/unreadable file, treat as empty
        return []
    if not isinstance(data, dict):
        return []
    pool = data.get("credential_pool")
    if not isinstance(pool, dict):
        return []
    entries = pool.get("anthropic")
    return entries if isinstance(entries, list) else []


def write_anthropic_oauth_credential(
    profile_name: str,
    *,
    access_token: str,
    refresh_token: str | None,
    expires_at_ms: int | None,
    scopes: str | None,
    label: str = "Claude Pro/Max (dashboard login)",
) -> None:
    """Merge a new OAuth credential into ``<profile>/auth.json``'s
    ``credential_pool.anthropic`` list, replacing any prior entry from this
    same source (re-login overwrites, it does not accumulate stale entries).

    Raises on genuine I/O failure -- callers should catch and surface it.
    """
    path = _auth_json_path(profile_name)
    path.parent.mkdir(parents=True, exist_ok=True)

    data: dict[str, Any] = {"version": 1, "credential_pool": {}}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data = existing
        except Exception:  # noqa: BLE001 - corrupt file: start fresh, don't crash
            pass

    if not isinstance(data.get("credential_pool"), dict):
        data["credential_pool"] = {}
    pool = data["credential_pool"].setdefault("anthropic", [])
    if not isinstance(pool, list):
        pool = []
        data["credential_pool"]["anthropic"] = pool

    source = f"{SOURCE_PREFIX}:{label}"
    entry = {
        "id": uuid.uuid4().hex[:12],
        "label": label,
        "auth_type": "oauth",
        "priority": 0,
        "source": source,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at_ms": expires_at_ms,
        "scopes": scopes,
        "last_status": "ok",
        "request_count": 0,
        "updated_at": int(time.time() * 1000),
    }
    pool[:] = [c for c in pool if c.get("source") != source] + [entry]

    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
