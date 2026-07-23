"""Shared pytest fixtures.

``fake_hermes_env`` simulates just enough of hermes-agent's
``agent.anthropic_adapter`` module surface (via ``sys.modules`` injection)
for ``hermes_anthropic_auth.patch`` to import and patch it, without needing
the real (large) hermes-agent package installed. Mirrors the real function
signatures/behavior of the functions our patch depends on, closely enough
that a regression in our assumptions about those signatures would show up
as a test failure here.
"""

from __future__ import annotations

import sys
import types

import pytest


class FakeTransport:
    """Stand-in for the httpx transport normally on a real SDK client."""

    def __init__(self) -> None:
        self._pool = "sentinel-pool"


class FakeHTTPXClient:
    """Stand-in for the ``httpx.Client`` an Anthropic SDK client wraps as ``._client``."""

    def __init__(self) -> None:
        self._transport = FakeTransport()


class FakeSDKClient:
    """Stand-in for what ``anthropic.Anthropic(...)`` returns."""

    def __init__(self, api_key) -> None:
        self.api_key = api_key
        self._client = FakeHTTPXClient()


def _fake_is_oauth_token(key) -> bool:
    # Mirrors the real prefix-sniffing logic closely enough for test purposes.
    if not isinstance(key, str):
        return False
    if key.startswith("sk-ant-api"):
        return False
    if key.startswith(("sk-ant-", "eyJ", "cc-")):
        return True
    return False


def _fake_get_claude_code_version() -> str:
    return "9.9.9-test"


@pytest.fixture
def fake_hermes_env(monkeypatch):
    """Install a fake ``agent.anthropic_adapter`` module into sys.modules."""
    agent_pkg = types.ModuleType("agent")
    anthropic_adapter_mod = types.ModuleType("agent.anthropic_adapter")

    build_calls: list = []

    def build_anthropic_client(
        api_key, base_url=None, timeout=None, *, drop_context_1m_beta=False
    ):
        build_calls.append(api_key)
        return FakeSDKClient(api_key)

    anthropic_adapter_mod.build_anthropic_client = build_anthropic_client
    anthropic_adapter_mod._is_oauth_token = _fake_is_oauth_token
    anthropic_adapter_mod._get_claude_code_version = _fake_get_claude_code_version
    agent_pkg.anthropic_adapter = anthropic_adapter_mod

    monkeypatch.setitem(sys.modules, "agent", agent_pkg)
    monkeypatch.setitem(sys.modules, "agent.anthropic_adapter", anthropic_adapter_mod)

    env = types.SimpleNamespace(
        agent=agent_pkg,
        anthropic_adapter=anthropic_adapter_mod,
        build_calls=build_calls,
        FakeSDKClient=FakeSDKClient,
    )

    yield env

    # Reset hermes_anthropic_auth.patch's module-level singleton state so
    # tests don't leak patched state into each other.
    from hermes_anthropic_auth import patch as patch_module

    patch_module._installed = False
    patch_module._original_build_anthropic_client = None
