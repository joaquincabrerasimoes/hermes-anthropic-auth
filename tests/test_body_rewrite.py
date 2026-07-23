import copy

from hermes_anthropic_auth.body_rewrite import rewrite_oauth_body


def _base_body():
    return {
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "hello world test message"}],
        "system": [
            {
                "type": "text",
                "text": "You are Claude Code, Anthropic's official CLI for Claude.",
            }
        ],
        "tools": [
            {
                "name": "mcp__read_file",
                "description": "Reads files. Part of **Hermes** toolset.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path to read.",
                        }
                    },
                },
            }
        ],
    }


def test_injects_billing_header_as_first_system_block():
    body = _base_body()
    result = rewrite_oauth_body(body, version="2.1.87")
    assert result["system"][0]["text"].startswith("x-anthropic-billing-header: ")
    assert "cch=4ffc3" in result["system"][0]["text"]  # known test vector, see test_billing_header.py
    # Original identity block preserved as the second block.
    assert result["system"][1]["text"] == (
        "You are Claude Code, Anthropic's official CLI for Claude."
    )


def test_sanitizes_tool_description():
    body = _base_body()
    result = rewrite_oauth_body(body, version="2.1.87")
    description = result["tools"][0]["description"]
    assert "Hermes" not in description
    assert "the agent" in description


def test_sanitizes_nested_property_description_when_matched():
    body = _base_body()
    body["tools"][0]["input_schema"]["properties"]["path"]["description"] = (
        "Opt out of **Hermes** cross-profile guard."
    )
    result = rewrite_oauth_body(body, version="2.1.87")
    prop_desc = result["tools"][0]["input_schema"]["properties"]["path"]["description"]
    assert "Hermes" not in prop_desc


def test_no_billing_header_without_user_message():
    body = _base_body()
    body["messages"] = [{"role": "assistant", "content": "no user turn here"}]
    original_system = copy.deepcopy(body["system"])
    result = rewrite_oauth_body(body, version="2.1.87")
    assert result["system"] == original_system


def test_does_not_touch_message_content():
    body = _base_body()
    result = rewrite_oauth_body(body, version="2.1.87")
    assert result["messages"][0]["content"] == "hello world test message"


def test_string_system_normalized_to_list_with_header():
    body = _base_body()
    body["system"] = "Plain string system prompt mentioning Hermes Agent."
    result = rewrite_oauth_body(body, version="2.1.87")
    assert isinstance(result["system"], list)
    assert result["system"][0]["text"].startswith("x-anthropic-billing-header: ")
    assert "Claude Code" in result["system"][1]["text"]


def test_non_dict_input_returns_unchanged():
    assert rewrite_oauth_body([], version="2.1.87") == []
    assert rewrite_oauth_body(None, version="2.1.87") is None


def test_missing_tools_field_does_not_crash():
    body = _base_body()
    del body["tools"]
    result = rewrite_oauth_body(body, version="2.1.87")
    assert "tools" not in result
