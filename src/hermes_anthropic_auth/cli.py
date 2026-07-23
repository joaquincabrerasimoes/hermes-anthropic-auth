"""Optional ``hermes anthropic-oauth-fix`` diagnostic subcommand.

Not required for the fix to work — purely a self-check convenience so users
can confirm the patch installed and inspect what a billing header looks like
without digging through logs.
"""

from __future__ import annotations

from .billing_header import FALLBACK_CLAUDE_CODE_VERSION, build_billing_header_value
from .patch import is_installed

_COMMAND_NAME = "anthropic-oauth-fix"


def _setup_argparse(subparser) -> None:
    subs = subparser.add_subparsers(dest="anthropic_oauth_fix_command")
    subs.add_parser("status", help="Show whether the OAuth request sanitizer is active")

    header_parser = subs.add_parser(
        "test-header", help="Print the billing header computed for sample text"
    )
    header_parser.add_argument(
        "text",
        nargs="?",
        default="hello world test message",
        help="Sample first-user-message text (default: a fixed test string)",
    )
    subparser.set_defaults(func=_handle)


def _handle(args) -> None:
    command = getattr(args, "anthropic_oauth_fix_command", None) or "status"

    if command == "test-header":
        text = getattr(args, "text", "") or "hello world test message"
        header = build_billing_header_value(
            [{"role": "user", "content": text}],
            version=FALLBACK_CLAUDE_CODE_VERSION,
        )
        print(header)
        return

    _print_status()


def _print_status() -> None:
    installed = is_installed()
    print("hermes-anthropic-auth")
    print(f"  patch installed: {'yes' if installed else 'no'}")
    if not installed:
        print(
            "  Not patched. Check `hermes plugins list` — this plugin must be "
            "enabled (`hermes plugins enable hermes-anthropic-auth`) and "
            "agent.anthropic_adapter must be importable (i.e. actually "
            "running inside hermes-agent)."
        )
        return
    example = build_billing_header_value(
        [{"role": "user", "content": "hello world test message"}],
        version=FALLBACK_CLAUDE_CODE_VERSION,
    )
    print(f"  example billing header: {example}")
    print(
        "  Active for OAuth (Claude Pro/Max) requests only — plain API key "
        "traffic is untouched."
    )


def register_cli(ctx) -> None:
    ctx.register_cli_command(
        name=_COMMAND_NAME,
        help="Diagnostics for the Anthropic OAuth request sanitizer",
        setup_fn=_setup_argparse,
        handler_fn=_handle,
    )
