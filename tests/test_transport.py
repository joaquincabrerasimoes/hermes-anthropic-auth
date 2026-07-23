import json

import httpx

from hermes_anthropic_auth.transport import OAuthRequestSanitizingTransport


class _RecordingTransport(httpx.BaseTransport):
    """Stub 'real' transport that records what it receives and echoes 200 OK."""

    def __init__(self) -> None:
        self.received: list[httpx.Request] = []
        self._pool = "sentinel-pool"  # for __getattr__ passthrough test

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.received.append(request)
        return httpx.Response(200, request=request, json={"ok": True})

    def close(self) -> None:
        pass


def _version_provider() -> str:
    return "2.1.87"


def test_rewrites_messages_post_body():
    wrapped = _RecordingTransport()
    transport = OAuthRequestSanitizingTransport(wrapped, version_provider=_version_provider)
    body = json.dumps(
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hello world test message"}],
            "system": [{"type": "text", "text": "hi"}],
        }
    ).encode()
    request = httpx.Request(
        "POST", "https://api.anthropic.com/v1/messages", content=body
    )

    with httpx.Client(transport=transport) as client:
        response = client.send(request)

    assert response.status_code == 200
    assert len(wrapped.received) == 1
    sent_body = json.loads(wrapped.received[0].content)
    assert sent_body["system"][0]["text"].startswith("x-anthropic-billing-header: ")


def test_passes_through_non_messages_requests_untouched():
    wrapped = _RecordingTransport()
    transport = OAuthRequestSanitizingTransport(wrapped, version_provider=_version_provider)
    request = httpx.Request("GET", "https://api.anthropic.com/v1/models")

    with httpx.Client(transport=transport) as client:
        client.send(request)

    assert wrapped.received[0].method == "GET"
    assert wrapped.received[0].url.path == "/v1/models"


def test_passes_through_non_post_to_messages_path():
    wrapped = _RecordingTransport()
    transport = OAuthRequestSanitizingTransport(wrapped, version_provider=_version_provider)
    request = httpx.Request("GET", "https://api.anthropic.com/v1/messages")

    with httpx.Client(transport=transport) as client:
        client.send(request)

    assert wrapped.received[0].method == "GET"


def test_getattr_proxies_to_wrapped_transport():
    wrapped = _RecordingTransport()
    transport = OAuthRequestSanitizingTransport(wrapped, version_provider=_version_provider)
    assert transport._pool == "sentinel-pool"


def test_fails_open_on_malformed_json_body():
    wrapped = _RecordingTransport()
    transport = OAuthRequestSanitizingTransport(wrapped, version_provider=_version_provider)
    request = httpx.Request(
        "POST", "https://api.anthropic.com/v1/messages", content=b"not valid json"
    )

    with httpx.Client(transport=transport) as client:
        response = client.send(request)

    assert response.status_code == 200
    assert wrapped.received[0].content == b"not valid json"


def test_fails_open_when_version_provider_raises():
    wrapped = _RecordingTransport()

    def _broken_version_provider() -> str:
        raise RuntimeError("boom")

    transport = OAuthRequestSanitizingTransport(
        wrapped, version_provider=_broken_version_provider
    )
    body = json.dumps(
        {
            "model": "claude-sonnet-4-6",
            "messages": [{"role": "user", "content": "hello world test message"}],
            "system": [{"type": "text", "text": "hi"}],
        }
    ).encode()
    request = httpx.Request(
        "POST", "https://api.anthropic.com/v1/messages", content=body
    )

    with httpx.Client(transport=transport) as client:
        response = client.send(request)

    # Falls back to FALLBACK_CLAUDE_CODE_VERSION rather than crashing the request.
    assert response.status_code == 200
    sent_body = json.loads(wrapped.received[0].content)
    assert sent_body["system"][0]["text"].startswith("x-anthropic-billing-header: ")


def test_close_delegates_to_wrapped():
    wrapped = _RecordingTransport()
    closed = {"called": False}

    def fake_close():
        closed["called"] = True

    wrapped.close = fake_close
    transport = OAuthRequestSanitizingTransport(wrapped, version_provider=_version_provider)
    transport.close()
    assert closed["called"] is True
