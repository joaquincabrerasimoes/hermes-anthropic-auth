"""Rewrite a parsed Anthropic ``/v1/messages`` OAuth request body in place.

Pure-dict transform, deliberately decoupled from JSON encoding/httpx so it's
directly unit-testable. Combines:

1. Billing-header injection (``billing_header.py``) — prepended as the first
   ``system`` text block, matching genuine Claude Code's wire shape.
2. System-prompt sanitization (``sanitize.py``) — anchor-based paragraph
   removal + phrase replacement on every ``system`` text block.
3. Tool description sanitization — phrase replacement only (never removes
   content) on ``tools[].description`` and
   ``tools[].input_schema.properties.*.description``.

Never touches ``messages[].content`` (user/assistant/tool_result content) —
that's dynamic data (user input, file contents, command output) and is out
of scope; mangling it would corrupt real conversation data for a cosmetic
branding fix.
"""

from __future__ import annotations

from typing import Any

from .billing_header import build_billing_header_value, has_user_message
from .sanitize import sanitize_description_text, sanitize_system_text


def _sanitize_system_field(parsed: dict[str, Any]) -> None:
    system = parsed.get("system")
    if isinstance(system, list):
        for block in system:
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                block["text"] = sanitize_system_text(block["text"])
    elif isinstance(system, str) and system:
        parsed["system"] = sanitize_system_text(system)


def _sanitize_tool_descriptions(parsed: dict[str, Any]) -> None:
    tools = parsed.get("tools")
    if not isinstance(tools, list):
        return
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if isinstance(tool.get("description"), str) and tool["description"]:
            tool["description"] = sanitize_description_text(tool["description"])
        schema = tool.get("input_schema")
        if not isinstance(schema, dict):
            continue
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        for prop in properties.values():
            if (
                isinstance(prop, dict)
                and isinstance(prop.get("description"), str)
                and prop["description"]
            ):
                prop["description"] = sanitize_description_text(prop["description"])


def _inject_billing_header(parsed: dict[str, Any], *, version: str) -> None:
    messages = parsed.get("messages")
    if not has_user_message(messages):
        return

    header_text = build_billing_header_value(messages, version=version)
    header_block = {"type": "text", "text": header_text}

    system = parsed.get("system")
    if isinstance(system, list):
        system.insert(0, header_block)
    elif isinstance(system, str) and system:
        parsed["system"] = [header_block, {"type": "text", "text": system}]
    else:
        parsed["system"] = [header_block]


def rewrite_oauth_body(parsed: dict[str, Any], *, version: str) -> dict[str, Any]:
    """Rewrite a parsed OAuth request body in place. Returns the same dict.

    Order matters: sanitize the ORIGINAL Hermes-authored system text first,
    then prepend the billing header — the header itself must never be run
    through the branding sanitizer (it's synthetic, not Hermes prose).
    """
    if not isinstance(parsed, dict):
        return parsed

    _sanitize_system_field(parsed)
    _sanitize_tool_descriptions(parsed)
    _inject_billing_header(parsed, version=version)

    return parsed
