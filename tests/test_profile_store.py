"""Tests for hermes_anthropic_auth.profile_store — file-layout logic only,
no hermes-agent internals. Uses a temp directory as HERMES_HOME."""

from __future__ import annotations

import json

import pytest

from hermes_anthropic_auth import profile_store


@pytest.fixture
def hermes_home(tmp_path, monkeypatch):
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


def test_list_profiles_default_only(hermes_home):
    profiles = profile_store.list_profiles()
    assert profiles == [{"name": "default", "home": str(hermes_home)}]


def test_list_profiles_includes_named_profiles(hermes_home):
    (hermes_home / "profiles" / "coder").mkdir(parents=True)
    (hermes_home / "profiles" / "assistant").mkdir(parents=True)
    (hermes_home / "profiles" / "not-a-dir.txt").write_text("x")

    profiles = profile_store.list_profiles()
    names = [p["name"] for p in profiles]
    assert names == ["default", "assistant", "coder"]


def test_list_profiles_resolves_root_when_running_under_named_profile(tmp_path, monkeypatch):
    root = tmp_path / "hermes-home"
    coder_home = root / "profiles" / "coder"
    coder_home.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(coder_home))

    profiles = profile_store.list_profiles()
    names = [p["name"] for p in profiles]
    assert "default" in names
    assert "coder" in names


def test_read_anthropic_pool_missing_file_returns_empty(hermes_home):
    assert profile_store.read_anthropic_pool("default") == []


def test_read_anthropic_pool_corrupt_file_returns_empty(hermes_home):
    (hermes_home / "auth.json").write_text("{not valid json")
    assert profile_store.read_anthropic_pool("default") == []


def test_write_and_read_roundtrip(hermes_home):
    profile_store.write_anthropic_oauth_credential(
        "default",
        access_token="at-1",
        refresh_token="rt-1",
        expires_at_ms=1234567890,
        scopes="user:inference",
    )
    pool = profile_store.read_anthropic_pool("default")
    assert len(pool) == 1
    entry = pool[0]
    assert entry["access_token"] == "at-1"
    assert entry["refresh_token"] == "rt-1"
    assert entry["expires_at_ms"] == 1234567890
    assert entry["auth_type"] == "oauth"
    assert entry["source"].startswith(profile_store.SOURCE_PREFIX)


def test_write_preserves_unrelated_auth_json_content(hermes_home):
    existing = {
        "version": 1,
        "credential_pool": {
            "openrouter": [{"id": "x", "label": "OPENROUTER_API_KEY"}],
        },
        "some_other_key": "keep-me",
    }
    (hermes_home / "auth.json").write_text(json.dumps(existing))

    profile_store.write_anthropic_oauth_credential(
        "default",
        access_token="at-1",
        refresh_token=None,
        expires_at_ms=None,
        scopes=None,
    )

    data = json.loads((hermes_home / "auth.json").read_text())
    assert data["some_other_key"] == "keep-me"
    assert data["credential_pool"]["openrouter"] == [{"id": "x", "label": "OPENROUTER_API_KEY"}]
    assert len(data["credential_pool"]["anthropic"]) == 1


def test_write_replaces_prior_entry_from_same_source_not_appends(hermes_home):
    profile_store.write_anthropic_oauth_credential(
        "default", access_token="at-1", refresh_token="rt-1", expires_at_ms=1, scopes=None
    )
    profile_store.write_anthropic_oauth_credential(
        "default", access_token="at-2", refresh_token="rt-2", expires_at_ms=2, scopes=None
    )
    pool = profile_store.read_anthropic_pool("default")
    assert len(pool) == 1
    assert pool[0]["access_token"] == "at-2"


def test_write_for_named_profile_uses_profiles_subdir(hermes_home):
    profile_store.write_anthropic_oauth_credential(
        "coder", access_token="at-1", refresh_token=None, expires_at_ms=None, scopes=None
    )
    expected_path = hermes_home / "profiles" / "coder" / "auth.json"
    assert expected_path.is_file()
    assert profile_store.read_anthropic_pool("default") == []
    assert len(profile_store.read_anthropic_pool("coder")) == 1
