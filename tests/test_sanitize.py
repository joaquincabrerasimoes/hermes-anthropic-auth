from hermes_anthropic_auth.sanitize import (
    sanitize_description_text,
    sanitize_system_text,
)


def test_removes_paragraph_containing_help_url_anchor():
    text = (
        "First paragraph stays.\n\n"
        "You run on Hermes Agent (by Nous Research). Docs at "
        "https://hermes-agent.nousresearch.com/docs are your reference.\n\n"
        "Last paragraph stays too."
    )
    result = sanitize_system_text(text)
    assert "nousresearch.com" not in result
    assert "First paragraph stays." in result
    assert "Last paragraph stays too." in result


def test_replaces_bare_hermes_platform_hint_tui():
    text = "You are running in the Hermes terminal UI (TUI)."
    assert sanitize_system_text(text) == "You are running in the terminal UI (TUI)."


def test_replaces_bare_hermes_platform_hint_desktop():
    text = "You are chatting inside the Hermes desktop app — a graphical surface."
    result = sanitize_system_text(text)
    assert "Hermes" not in result
    assert "the desktop app" in result


def test_replaces_bare_hermes_platform_hint_webui():
    text = "You are in the Hermes WebUI, a browser-based chat interface."
    result = sanitize_system_text(text)
    assert "Hermes" not in result


def test_replaces_steer_channel_hermes_mention():
    text = (
        "While you work, the user can send an out-of-band message that Hermes "
        "appends to the end of a tool result."
    )
    result = sanitize_system_text(text)
    assert "Hermes" not in result
    assert "gets appended" in result


def test_replaces_remote_backend_hermes_mention():
    text = "The host OS, home, and cwd of the Hermes process are irrelevant."
    result = sanitize_system_text(text)
    assert "Hermes" not in result


def test_replaces_active_profile_hermes_mention():
    text = "Active Hermes profile: default. Other profiles live elsewhere."
    result = sanitize_system_text(text)
    assert result.startswith("Active profile: default.")


def test_identity_and_brand_replacements_compose():
    text = "Hermes Agent by Nous Research, also called hermes-agent."
    assert sanitize_system_text(text) == "Claude Code by Anthropic, also called claude-code."


def test_empty_and_falsy_input_safe():
    assert sanitize_system_text("") == ""
    assert sanitize_description_text("") == ""
    assert sanitize_system_text(None) is None  # type: ignore[arg-type]


def test_text_without_any_leak_passes_through_unchanged():
    text = "This paragraph has nothing to sanitize.\n\nNeither does this one."
    assert sanitize_system_text(text) == text


def test_description_bold_hermes_replaced():
    text = "Uses **Hermes** memory features when available."
    result = sanitize_description_text(text)
    assert result == "Uses the agent memory features when available."


def test_description_never_removed_even_if_containing_anchor():
    # Descriptions are never paragraph-removed — only phrase-replaced.
    text = "See hermes-agent.nousresearch.com for details."
    result = sanitize_description_text(text)
    assert result  # content preserved, not blanked
    assert "for details." in result
