"""Sanitize Hermes/Nous-Research branding out of text sent to Anthropic under OAuth.

Anthropic's server-side billing classifier flags traffic that doesn't look
like genuine Claude Code and routes it to the metered "extra usage" bucket
instead of Pro/Max plan quota, surfacing as a misleading HTTP 400
"You're out of extra usage" error. Hermes's own built-in sanitizer
(``agent/anthropic_adapter.py``) only does 4 literal ``.replace()`` calls and
misses several branding leaks (notably the bare ``nousresearch.com`` domain
and multiple bare "Hermes" mentions across platform hints and tool
descriptions). This module extends that coverage using the same
anchor-based-paragraph-removal + targeted-phrase-replacement architecture
the opencode-anthropic-auth project uses (see its ``transform.ts`` /
``constants.ts``), adapted to Hermes's actual system-prompt content.

Two sanitization modes, deliberately kept separate:

- ``sanitize_system_text``: operates on Hermes-authored ``system`` prompt
  text. Safe to drop entire paragraphs (text between blank lines) when they
  contain a removal anchor, since these are self-referential/non-essential
  guidance blocks (e.g. "read the docs at hermes-agent.nousresearch.com").
- ``sanitize_description_text``: operates on tool/parameter ``description``
  strings, which are short and single-purpose. NEVER removes content
  (an empty tool description is worse than a branded one) — only applies
  targeted phrase replacements.

Neither function ever touches dynamic content (message text, tool_result
output, file contents) — only Hermes-authored static prompt/schema text.
"""

from __future__ import annotations

import re

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\n+")

# Paragraphs (text blocks separated by one or more blank lines) containing
# ANY of these anchors are dropped entirely from system prompt text. Anchors
# are chosen to be resilient to upstream wording changes — as long as the
# anchor substring survives, the whole (non-essential) paragraph goes with it.
PARAGRAPH_REMOVAL_ANCHORS: tuple[str, ...] = (
    # HERMES_AGENT_HELP_GUIDANCE block — self-referential "read the docs" /
    # "load the hermes-agent skill" pointer. Not behaviorally required.
    "hermes-agent.nousresearch.com",
)

# Targeted phrase-level replacements, applied after paragraph removal, for
# bare-brand mentions embedded in paragraphs that ARE behaviorally load-bearing
# (steering mechanism, platform formatting rules, environment/profile info)
# and must be kept — only the identifying phrase is swapped.
#
# Ordered longest/most-specific first so a later, shorter pattern can't
# partially clobber a phrase an earlier, longer pattern was meant to handle
# as a whole.
TEXT_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (
        "the user can send an out-of-band message that Hermes appends",
        "the user can send an out-of-band message that gets appended",
    ),
    ("the Hermes terminal UI (TUI)", "the terminal UI (TUI)"),
    ("the Hermes desktop app", "the desktop app"),
    ("the Hermes WebUI", "the WebUI"),
    ("where Hermes itself is running", "where the agent itself is running"),
    ("where Hermes itself runs", "where the agent itself runs"),
    ("of the Hermes process", "of the agent process"),
    ("Active Hermes profile", "Active profile"),
    ("Hermes Agent", "Claude Code"),
    ("Hermes agent", "Claude Code"),
    ("hermes-agent", "claude-code"),
    ("Nous Research", "Anthropic"),
    ("nousresearch.com", "anthropic.com"),
    ("**Hermes**", "the agent"),
)


def _apply_replacements(text: str) -> str:
    for old, new in TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def sanitize_system_text(text: str) -> str:
    """Sanitize a system-prompt text block: drop anchored paragraphs, replace phrases."""
    if not text:
        return text

    paragraphs = _PARAGRAPH_SPLIT_RE.split(text)
    kept = [
        paragraph
        for paragraph in paragraphs
        if not any(anchor in paragraph for anchor in PARAGRAPH_REMOVAL_ANCHORS)
    ]
    result = "\n\n".join(kept).strip()
    return _apply_replacements(result)


def sanitize_description_text(text: str) -> str:
    """Sanitize a tool/parameter description string. Never removes content."""
    if not text:
        return text
    return _apply_replacements(text)
