"""hermes-anthropic-auth — fixes Anthropic's false-positive OAuth billing block.

Hermes Agent already ships native Claude Pro/Max OAuth login and token
refresh (``agent/anthropic_adapter.py``). What it's missing is full request
fingerprinting: Anthropic's server-side classifier flags requests that don't
look enough like genuine Claude Code CLI traffic and routes them to the
metered "extra usage" bucket instead of Pro/Max plan quota, surfacing as a
misleading HTTP 400 ``You're out of extra usage`` error.

This plugin monkey-patches the single confirmed Anthropic SDK client
construction choke point (see ``patch.py`` for why this is safe and
sufficient) to attach a custom httpx transport that, ONLY for OAuth-token
clients:

1. Injects the Claude Code "billing header" content-consistency fingerprint
   (``billing_header.py`` — ported from opencode-anthropic-auth's
   decompiled-binary-derived algorithm).
2. Sanitizes Hermes/Nous-Research branding out of the system prompt and tool
   descriptions beyond what Hermes's own built-in 4-string sanitizer catches
   (``sanitize.py`` / ``body_rewrite.py``).

Plain API-key traffic, Bedrock, and Azure Entra ID clients are never
touched — zero behavior change for non-OAuth users.
"""

from __future__ import annotations

import logging

from .patch import install, is_installed, uninstall

logger = logging.getLogger(__name__)

__all__ = ["register", "install", "is_installed", "uninstall"]

__version__ = "0.1.0"


def register(ctx) -> None:
    """Hermes plugin entry point — called once at plugin load time."""
    install()

    try:
        from .cli import register_cli

        register_cli(ctx)
    except Exception:  # noqa: BLE001 - diagnostic command is optional, never fatal
        logger.exception("hermes-anthropic-auth: failed to register CLI diagnostics")
