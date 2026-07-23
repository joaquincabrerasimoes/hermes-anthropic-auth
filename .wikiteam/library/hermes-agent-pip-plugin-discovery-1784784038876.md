Name: hermes-agent pip plugin discovery
Keywords: hermes-agent, plugins, entry_points, hermes_agent.plugins, model-provider, PluginContext
FilePathReference: hermes_cli/plugins.py
Short Description: hermes-agent pip plugins use single entry-point group hermes_agent.plugins; model-provider kind only applies to directory plugins.
---
SOURCE REPO: hermes-agent (Nous Research), cloned at C:\Users\Joaquin\AppData\Local\Temp\opencode\hermes-agent-src
Package name/version (pyproject.toml root, lines 4-5): name = "hermes-agent", version = "0.19.0"

=== Entry-point group ===
hermes_cli/plugins.py:217 → `ENTRY_POINTS_GROUP = "hermes_agent.plugins"`
This is the ONLY entry-point group in the whole codebase. There is NO separate group for model-provider plugins (no `hermes_agent.model_providers` group exists anywhere — verified via full-repo grep). Model providers distributed via pip use the SAME `hermes_agent.plugins` group.

pyproject.toml entry-point declaration form (from docs, consistent w/ loader code):
```toml
[project.entry-points."hermes_agent.plugins"]
my-plugin = "my_plugin_package"
```
Value MUST be a bare importable module name (NOT "module:function" — see contradiction note below). `_load_entrypoint_module` (hermes_cli/plugins.py:1870-1886) does `ep.load()` then the caller does `getattr(module, "register", None)` — so `ep.load()` must return a MODULE object exposing a top-level `register(ctx)` function, exactly like directory plugins.

CONTRADICTION FOUND: website/docs/developer-guide/model-provider-plugin.md:254-255 shows
`acme-inference = "acme_hermes_plugin:register"` — this "module:attr" form would make `ep.load()` return the `register` FUNCTION itself (per importlib.metadata semantics), not a module, so `getattr(module, "register", None)` in hermes_cli/plugins.py:1772 would fail (functions don't have a `.register` attribute) → plugin logs "no register() function" and silently fails to load. The canonical/consistent form is in website/docs/developer-guide/plugins/index.md:1213 (`my-plugin = "my_plugin_package"`, module only) and in tests/hermes_cli/test_plugins.py:419-441 (mocked, doesn't actually exercise real importlib.metadata resolution). Flag this as a docs bug if building a real third-party model-provider plugin — use the bare-module form.

=== Model-provider plugins: NOT discoverable via entry_points in practice ===
providers/__init__.py `_discover_providers()` (lines 140-191) is the SEPARATE lazy discovery system that model-provider plugins actually need to hook into (calls `register_provider(ProviderProfile(...))`). Its discovery order is ONLY:
  1. `<repo>/plugins/model-providers/<name>/` (bundled)
  2. `$HERMES_HOME/plugins/model-providers/<name>/` (user, directory only)
  3. legacy `providers/<name>.py` single-file modules via pkgutil (back-compat, requires literal `providers` package namespace)
It NEVER scans `importlib.metadata.entry_points()`. 

Meanwhile the general PluginManager (`hermes_cli/plugins.py` `_discover_and_load_inner`, lines 1317-1477) explicitly SKIPS importing any manifest with `kind == "model-provider"` (lines 1418-1425: "Skipping ... model-provider, handled by providers/ discovery") — it only records the manifest for introspection.

BUT: entry-point-sourced manifests (built in `_scan_entry_points`, hermes_cli/plugins.py:1658-1682) NEVER get a `kind` other than the dataclass default `"standalone"` (hermes_cli/plugins.py:308) because `_scan_entry_points` does not read any plugin.yaml / does not set `manifest.kind` at all — it only sets `name`, `source="entrypoint"`, `path=ep.value`, `key=ep.name`. So the `kind == "model-provider"` skip branch NEVER triggers for pip/entry-point plugins.

CONSEQUENCE (verified against providers/__init__.py + plugins.py code, and confirmed by website/docs/developer-guide/model-provider-plugin.md:245-258 "General PluginManager integration" section): a pip-distributed model-provider plugin is loaded like ANY OTHER standalone plugin — opt-in via `plugins.enabled` config (hermes_cli/plugins.py:1450-1469, "Everything else ... is opt-in"), its `register(ctx)` function IS called by `_load_plugin`, and INSIDE that `register(ctx)` function the plugin must directly do:
```python
from providers import register_provider
from providers.base import ProviderProfile
def register(ctx):
    register_provider(ProviderProfile(name="acme-inference", ...))
```
This bypasses `providers/__init__.py`'s own `_discover_providers()` entirely — `register_provider()` is a plain module-level function call, populating the shared `_REGISTRY` dict regardless of caller. `ctx` (PluginContext) is NOT used for this — PluginContext has NO `register_model_provider`/`register_provider` method (confirmed: full grep of `def register_` in hermes_cli/plugins.py yields register_tool, register_cli_command, register_command, register_context_engine, register_image_gen_provider, register_dashboard_auth_provider, register_video_gen_provider, register_web_search_provider, register_browser_provider, register_secret_source, register_tts_provider, register_transcription_provider, register_platform, register_slack_action_handler, register_auxiliary_task, register_hook, register_middleware, register_skill — 17 methods total, NO provider-registration method).

The `kind: model-provider` field in plugin.yaml is meaningful ONLY for directory-based plugins (bundled/user/project), where `_parse_manifest` (hermes_cli/plugins.py:1563-1652) either reads it explicitly or auto-detects it via source-text heuristic (lines 1600-1629: scans `__init__.py` first 8192 bytes for `"register_provider"` + `"ProviderProfile"` substrings → coerces kind to "model-provider"). This heuristic does NOT run for entry-point plugins either (only inside `_parse_manifest`, called only from `_scan_directory_level`).

=== Opt-in requirement ===
Pip/entry-point plugins are NEVER auto-enabled. `_get_enabled_plugins()` (hermes_cli/plugins.py:243-270) returns `None` by default (nothing enabled) unless `config.yaml` has an explicit `plugins.enabled: [...]` list. End users must run `hermes plugins enable <name>` after `pip install <package>` for the plugin (including a model-provider plugin) to actually load. `hermes plugins install` (hermes_cli/plugins_cmd.py:550) only handles git/local-directory plugin installs, NOT pip entry-point installs — pip installation is the user's own `pip install <pkg>` step, entirely outside Hermes' `plugins install` command.

=== No in-repo third-party pip plugin example ===
Repo has exactly ONE pyproject.toml (root, hermes-agent's own). No vendored example third-party pip plugin package exists anywhere in the tree (checked recursively). Docs reference an EXTERNAL example repo: https://github.com/ogallotti/rtk-hermes (mentioned in website/docs/getting-started/nix-setup.md:647 and its zh-Hans translation) — not vendored, not verified by this research (external link only).
