"""Claude Code "billing header" fingerprint — content-consistency hashing.

Genuine Claude Code CLI sends a pseudo-header line embedded as the first
``system`` text block on every ``/v1/messages`` request:

    x-anthropic-billing-header: cc_version=2.1.87.6ff; cc_entrypoint=sdk-cli; cch=4ffc3;

The algorithm (salt, sampled character positions, SHA-256 truncation scheme)
was reverse-engineered from a decompiled Claude Code binary by the
``opencode-anthropic-auth`` project. This is a faithful port of that same
algorithm — same salt, same positions, same truncation lengths — so Hermes's
OAuth requests carry the same fingerprint shape as genuine Claude Code
traffic instead of omitting it entirely.

Reference (TypeScript original): opencode-anthropic-auth/src/cch.ts
"""

from __future__ import annotations

import hashlib
from typing import Any, Sequence

# Reverse-engineered constants — do not change without re-verifying against
# a decompiled Claude Code binary. These are intentionally identical to the
# opencode-anthropic-auth TypeScript implementation.
CCH_SALT = "59cf53e54c78"
CCH_POSITIONS: tuple[int, ...] = (4, 7, 20)
DEFAULT_ENTRYPOINT = "sdk-cli"

# Fallback version used only if the caller can't supply a detected one.
# Matches the last version opencode-anthropic-auth captured/validated against.
FALLBACK_CLAUDE_CODE_VERSION = "2.1.87"


def extract_first_user_message_text(messages: Sequence[dict[str, Any]]) -> str:
    """Extract text from the first user message's first text block.

    Mirrors ``cch.ts::extractFirstUserMessageText``. Accepts Anthropic-wire
    shaped messages: ``content`` is either a plain string or a list of
    content blocks (``{"type": "text", "text": ...}`` among others).
    """
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                    and block.get("text")
                ):
                    return block["text"]
        return ""
    return ""


def compute_cch(message_text: str) -> str:
    """First 5 hex characters of SHA-256(messageText)."""
    return hashlib.sha256(message_text.encode("utf-8")).hexdigest()[:5]


def compute_version_suffix(
    message_text: str, version: str = FALLBACK_CLAUDE_CODE_VERSION
) -> str:
    """3-char version suffix from salt + sampled message characters + version."""
    chars = "".join(
        message_text[i] if 0 <= i < len(message_text) else "0"
        for i in CCH_POSITIONS
    )
    payload = f"{CCH_SALT}{chars}{version}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:3]


def build_billing_header_value(
    messages: Sequence[dict[str, Any]],
    *,
    version: str = FALLBACK_CLAUDE_CODE_VERSION,
    entrypoint: str = DEFAULT_ENTRYPOINT,
) -> str:
    """Build the complete billing header string for insertion into system[0]."""
    text = extract_first_user_message_text(messages)
    suffix = compute_version_suffix(text, version)
    cch = compute_cch(text)
    return (
        "x-anthropic-billing-header: "
        f"cc_version={version}.{suffix}; "
        f"cc_entrypoint={entrypoint}; "
        f"cch={cch};"
    )


def has_user_message(messages: Any) -> bool:
    """True if ``messages`` is a list containing at least one user-role message."""
    if not isinstance(messages, list):
        return False
    return any(
        isinstance(message, dict) and message.get("role") == "user"
        for message in messages
    )
