from hermes_anthropic_auth import patch as patch_module
from hermes_anthropic_auth.transport import OAuthRequestSanitizingTransport


def test_install_wraps_oauth_client_transport(fake_hermes_env):
    assert patch_module.install() is True
    assert patch_module.is_installed() is True

    client = fake_hermes_env.anthropic_adapter.build_anthropic_client(
        "sk-ant-oat01-something"
    )
    assert isinstance(client._client._transport, OAuthRequestSanitizingTransport)


def test_install_does_not_wrap_plain_api_key_client(fake_hermes_env):
    patch_module.install()
    client = fake_hermes_env.anthropic_adapter.build_anthropic_client(
        "sk-ant-api03-something"
    )
    assert not isinstance(client._client._transport, OAuthRequestSanitizingTransport)


def test_install_does_not_wrap_callable_api_key(fake_hermes_env):
    patch_module.install()
    client = fake_hermes_env.anthropic_adapter.build_anthropic_client(lambda: "token")
    assert not isinstance(client._client._transport, OAuthRequestSanitizingTransport)


def test_wrapped_transport_proxies_pool_attribute(fake_hermes_env):
    # Guards the TCP force-close introspection path in
    # agent/agent_runtime_helpers.py::_iter_pool_sockets, which walks
    # client._client._transport._pool.
    patch_module.install()
    client = fake_hermes_env.anthropic_adapter.build_anthropic_client(
        "sk-ant-oat01-something"
    )
    assert client._client._transport._pool == "sentinel-pool"


def test_install_is_idempotent(fake_hermes_env):
    assert patch_module.install() is True
    patched_fn = fake_hermes_env.anthropic_adapter.build_anthropic_client
    assert patch_module.install() is True
    assert fake_hermes_env.anthropic_adapter.build_anthropic_client is patched_fn


def test_uninstall_restores_original(fake_hermes_env):
    original_fn = fake_hermes_env.anthropic_adapter.build_anthropic_client
    patch_module.install()
    assert fake_hermes_env.anthropic_adapter.build_anthropic_client is not original_fn
    patch_module.uninstall()
    assert fake_hermes_env.anthropic_adapter.build_anthropic_client is original_fn


def test_install_returns_false_when_module_not_importable(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "agent", None)  # forces ImportError on `from agent import ...`
    assert patch_module.install() is False
    assert patch_module.is_installed() is False
