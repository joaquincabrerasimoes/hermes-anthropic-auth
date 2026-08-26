"""Tests for hermes_anthropic_auth.oauth_web — pure logic, no network, no
hermes-agent internals."""

from __future__ import annotations

import base64
import hashlib

import pytest

from hermes_anthropic_auth import oauth_web


def test_generate_pkce_is_unique_each_call():
    a = oauth_web.generate_pkce()
    b = oauth_web.generate_pkce()
    assert a.verifier != b.verifier
    assert a.state != b.state


def test_generate_pkce_challenge_matches_s256_of_verifier():
    pkce = oauth_web.generate_pkce()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(pkce.verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    assert pkce.challenge == expected


def test_build_authorize_url_contains_required_params():
    pkce = oauth_web.generate_pkce()
    url = oauth_web.build_authorize_url(pkce)
    assert url.startswith(oauth_web.OAUTH_AUTHORIZE_URL)
    assert f"client_id={oauth_web.OAUTH_CLIENT_ID}" in url
    assert "code_challenge_method=S256" in url
    assert f"state={pkce.state}" in url
    assert "response_type=code" in url


def test_parse_code_state_valid():
    code, state = oauth_web.parse_code_state("  abc123#xyz789  ")
    assert code == "abc123"
    assert state == "xyz789"


@pytest.mark.parametrize("raw", ["", "no-hash-here", "#missing-code", "missing-state#"])
def test_parse_code_state_rejects_malformed_input(raw):
    with pytest.raises(ValueError):
        oauth_web.parse_code_state(raw)


def test_normalize_token_response_computes_expiry_from_expires_in():
    before = oauth_web._normalize_token_response(
        {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "scope": "s1 s2"}
    )
    assert before["access_token"] == "at"
    assert before["refresh_token"] == "rt"
    assert before["scopes"] == "s1 s2"
    assert before["expires_at_ms"] is not None
    assert before["expires_at_ms"] > 0


def test_normalize_token_response_passes_through_explicit_expires_at_ms():
    result = oauth_web._normalize_token_response(
        {"access_token": "at", "expires_at_ms": 1234567890}
    )
    assert result["expires_at_ms"] == 1234567890


def test_normalize_token_response_no_expiry_info():
    result = oauth_web._normalize_token_response({"access_token": "at"})
    assert result["expires_at_ms"] is None
