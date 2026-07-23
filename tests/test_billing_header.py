"""Cross-language parity tests against opencode-anthropic-auth's cch.test.ts.

Same input MUST produce the same hash output as the TypeScript original —
these test vectors are copied verbatim from
referenceCode/opencode-anthropic-auth/src/tests/cch.test.ts.
"""

from hermes_anthropic_auth.billing_header import (
    build_billing_header_value,
    compute_cch,
    compute_version_suffix,
    extract_first_user_message_text,
    has_user_message,
)


def test_extracts_text_from_first_user_message():
    messages = [
        {"role": "assistant", "content": "ignore me"},
        {
            "role": "user",
            "content": [
                {"type": "image", "text": "ignored"},
                {"type": "text", "text": "hello world test message"},
            ],
        },
    ]
    assert extract_first_user_message_text(messages) == "hello world test message"


def test_extracts_text_from_plain_string_content():
    messages = [{"role": "user", "content": "plain string content"}]
    assert extract_first_user_message_text(messages) == "plain string content"


def test_no_user_message_returns_empty_string():
    assert extract_first_user_message_text([{"role": "assistant", "content": "hi"}]) == ""
    assert extract_first_user_message_text([]) == ""


def test_computes_5_character_cch_hash():
    assert compute_cch("hello world test message") == "4ffc3"


def test_computes_3_character_version_suffix():
    assert compute_version_suffix("hello world test message", "2.1.87") == "6ff"


def test_builds_full_billing_header_value():
    result = build_billing_header_value(
        [{"role": "user", "content": "hello world test message"}],
        version="2.1.87",
        entrypoint="sdk-cli",
    )
    assert result == (
        "x-anthropic-billing-header: cc_version=2.1.87.6ff; "
        "cc_entrypoint=sdk-cli; cch=4ffc3;"
    )


def test_has_user_message_true_when_present():
    assert has_user_message([{"role": "user", "content": "hi"}]) is True


def test_has_user_message_false_when_absent_or_wrong_type():
    assert has_user_message([{"role": "assistant", "content": "hi"}]) is False
    assert has_user_message([]) is False
    assert has_user_message(None) is False
    assert has_user_message("not a list") is False


def test_short_position_indices_pad_with_zero():
    # CCH_POSITIONS = (4, 7, 20) — a message shorter than 21 chars must not
    # raise; missing positions are padded with '0', matching the TS
    # `messageText[index] || '0'` fallback.
    short_text = "hi"
    # Should not raise, and must be deterministic.
    result_a = compute_version_suffix(short_text, "2.1.87")
    result_b = compute_version_suffix(short_text, "2.1.87")
    assert result_a == result_b
    assert len(result_a) == 3
