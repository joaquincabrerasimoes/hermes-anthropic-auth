"""Keeps the two install methods in sync.

``hermes_anthropic_auth/plugin.yaml`` (directory-style install, Method B in
the README) and ``pyproject.toml``'s entry-point (pip install, Method A)
must agree on plugin name/version — otherwise `hermes plugins enable
hermes-anthropic-auth` would resolve to two different ids depending on which
install method a user picked.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

yaml = pytest.importorskip(
    "yaml", reason="pyyaml only needed for this manifest-consistency test (dev extra)"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_YAML = REPO_ROOT / "hermes_anthropic_auth" / "plugin.yaml"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"


def _load_plugin_yaml() -> dict:
    return yaml.safe_load(PLUGIN_YAML.read_text(encoding="utf-8"))


def _load_pyproject() -> dict:
    return tomllib.loads(PYPROJECT_TOML.read_text(encoding="utf-8"))


def test_plugin_yaml_exists_and_parses():
    assert PLUGIN_YAML.exists(), (
        "hermes_anthropic_auth/plugin.yaml is required for the "
        "directory-style install method (README Method B) to work — "
        "the directory-plugin discovery scanner requires plugin.yaml "
        "directly alongside __init__.py."
    )
    data = _load_plugin_yaml()
    assert isinstance(data, dict)


def test_plugin_yaml_kind_is_standalone():
    # NOT "model-provider" — that kind routes to the separate providers/
    # discovery system and hermes's PluginManager skips calling
    # register(ctx) entirely for it (see patch.py's module docstring for
    # why this plugin is a monkey-patch, not a ProviderProfile).
    data = _load_plugin_yaml()
    assert data.get("kind", "standalone") == "standalone"


def test_plugin_yaml_name_matches_pip_entry_point_name():
    plugin_data = _load_plugin_yaml()
    pyproject_data = _load_pyproject()

    entry_points = pyproject_data["project"]["entry-points"]["hermes_agent.plugins"]
    entry_point_names = list(entry_points.keys())

    assert plugin_data["name"] in entry_point_names, (
        "plugin.yaml's `name` must match the pip entry-point name so "
        "`hermes plugins enable <name>` resolves to the same plugin "
        "regardless of install method."
    )


def test_plugin_yaml_version_matches_pyproject_version():
    plugin_data = _load_plugin_yaml()
    pyproject_data = _load_pyproject()
    assert str(plugin_data["version"]) == pyproject_data["project"]["version"], (
        "plugin.yaml and pyproject.toml versions drifted — bump both together."
    )


def test_entry_point_target_module_matches_plugin_directory_name():
    # The entry-point's target module name must be the actual importable
    # package name, which must also match the directory name shipped for
    # the directory-style install (both point at the same source tree).
    pyproject_data = _load_pyproject()
    entry_points = pyproject_data["project"]["entry-points"]["hermes_agent.plugins"]
    target_module = next(iter(entry_points.values()))
    assert target_module == PLUGIN_YAML.parent.name
