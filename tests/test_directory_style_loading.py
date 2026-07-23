"""Proves Method B (directory-style install, README) actually works.

Simulates hermes_cli.plugins.PluginManager's directory-plugin loader —
``importlib.util.spec_from_file_location(name, __init__.py,
submodule_search_locations=[plugin_dir])`` — against the real
``src/hermes_anthropic_auth/`` folder, the exact same mechanism used when
that folder is copied/symlinked into ``~/.hermes/plugins/hermes-anthropic-auth/``.
This is NOT the same code path as a normal ``import hermes_anthropic_auth``
(which test_patch.py etc. exercise) — relative imports between sibling
modules (``from .patch import install``) need ``submodule_search_locations``
set correctly to resolve, and this is the one place that gets verified
without needing a real running hermes-agent instance.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "src" / "hermes_anthropic_auth"


def _load_as_directory_plugin(module_name: str):
    init_path = PLUGIN_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        module_name,
        init_path,
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _cleanup(module_name: str) -> None:
    sys.modules.pop(module_name, None)
    for key in list(sys.modules):
        if key.startswith(module_name + "."):
            del sys.modules[key]


def test_directory_style_load_succeeds_with_relative_imports():
    module_name = "_test_dirstyle_hermes_anthropic_auth_a"
    try:
        module = _load_as_directory_plugin(module_name)
        assert hasattr(module, "register")
        assert callable(module.register)
        # Confirm the sibling modules actually resolved via relative import
        # (not just that __init__.py itself parsed).
        assert hasattr(module, "install")
        assert hasattr(module, "uninstall")
    finally:
        _cleanup(module_name)


def test_directory_style_register_wraps_oauth_client(fake_hermes_env):
    module_name = "_test_dirstyle_hermes_anthropic_auth_b"
    try:
        module = _load_as_directory_plugin(module_name)

        registered_cli = {}

        class FakeCtx:
            def register_cli_command(self, **kwargs):
                registered_cli.update(kwargs)

        module.register(FakeCtx())

        assert registered_cli.get("name") == "anthropic-oauth-fix"

        client = fake_hermes_env.anthropic_adapter.build_anthropic_client(
            "sk-ant-oat01-something"
        )
        assert (
            type(client._client._transport).__name__
            == "OAuthRequestSanitizingTransport"
        )
    finally:
        _cleanup(module_name)
