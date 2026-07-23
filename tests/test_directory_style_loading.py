"""Proves Method B (directory-style install, README) actually works.

Simulates hermes_cli.plugins.PluginManager's directory-plugin loader —
``importlib.util.spec_from_file_location(name, __init__.py,
submodule_search_locations=[plugin_dir])`` — against the real
``hermes_anthropic_auth/`` folder, the exact same mechanism used when that
folder (or the whole repo, since it's now only one level of nesting either
way) is copied/symlinked/cloned into ``~/.hermes/plugins/hermes-anthropic-auth/``.
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

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "hermes_anthropic_auth"


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


# ---------------------------------------------------------------------------
# Regression tests for the reported bug: cloning the WHOLE repo directly as
# ~/.hermes/plugins/<name>/ (instead of copying just the inner package
# folder) failed with "Plugin 'hermes-anthropic-auth' is not installed or
# bundled" because plugin.yaml lived two directory levels deep
# (src/hermes_anthropic_auth/plugin.yaml) and Hermes's directory-plugin
# scanner only recurses one level looking for it. These tests simulate that
# scanner's exact depth-limited recursion (mirroring
# hermes_cli.plugins.PluginManager._scan_directory_level) against synthetic
# directory trees, proving (a) the fix works and (b) documenting why the
# pre-fix src/ layout didn't.
# ---------------------------------------------------------------------------


def _simulate_scanner_find_plugin_yaml(start_dir: Path, max_depth: int = 1):
    """Mirrors PluginManager._scan_directory_level's depth-limited search."""

    def _scan(path: Path, depth: int):
        for child in sorted(path.iterdir()):
            if not child.is_dir():
                continue
            candidate = child / "plugin.yaml"
            if candidate.exists():
                return candidate
            if depth >= max_depth:
                continue
            found = _scan(child, depth + 1)
            if found is not None:
                return found
        return None

    return _scan(start_dir, 0)


def test_whole_repo_clone_is_discoverable_by_scanner_depth_limit(tmp_path):
    """The actual bug report: `git clone <repo> ~/.hermes/plugins/hermes-anthropic-auth`
    (whole repo, not just the inner package folder) must be discoverable,
    because the flat `hermes_anthropic_auth/plugin.yaml` layout is exactly
    one level deep from the cloned-repo root — matching the scanner's
    recursion limit.
    """
    plugins_dir = tmp_path / "plugins"
    cloned_repo = plugins_dir / "hermes-anthropic-auth"  # arbitrary folder name
    package_dir = cloned_repo / "hermes_anthropic_auth"
    package_dir.mkdir(parents=True)
    (package_dir / "plugin.yaml").write_text("name: hermes-anthropic-auth\nkind: standalone\n")
    (cloned_repo / "pyproject.toml").write_text("[project]\nname = 'hermes-anthropic-auth'\n")
    (cloned_repo / "tests").mkdir()

    found = _simulate_scanner_find_plugin_yaml(plugins_dir, max_depth=1)

    assert found == package_dir / "plugin.yaml"


def test_two_levels_deep_manifest_documents_the_original_bug(tmp_path):
    """Documents WHY the old src/-layout broke: plugin.yaml nested two
    levels deep (src/hermes_anthropic_auth/plugin.yaml) is invisible to the
    scanner's depth-1 recursion when the whole repo is cloned directly as
    the plugin folder — reproducing the exact reported failure mode.
    """
    plugins_dir = tmp_path / "plugins"
    cloned_repo = plugins_dir / "hermes-anthropic-auth"
    nested_two_deep = cloned_repo / "src" / "hermes_anthropic_auth"
    nested_two_deep.mkdir(parents=True)
    (nested_two_deep / "plugin.yaml").write_text("name: hermes-anthropic-auth\n")

    found = _simulate_scanner_find_plugin_yaml(plugins_dir, max_depth=1)

    assert found is None
