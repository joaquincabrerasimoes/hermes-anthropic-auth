Name: hermes-agent PluginContext + manifest
Keywords: hermes-agent, PluginContext, plugin.yaml, PluginManifest, requires_env, kind
FilePathReference: hermes_cli/plugins.py
Short Description: Full PluginContext register_* method inventory and PluginManifest/plugin.yaml field schema with file:line citations.
---
=== PluginManifest dataclass (hermes_cli/plugins.py:280-314) ===
```python
@dataclass
class PluginManifest:
    name: str
    version: str = ""
    description: str = ""
    author: str = ""
    requires_env: List[Union[str, Dict[str, Any]]] = field(default_factory=list)
    provides_tools: List[str] = field(default_factory=list)
    provides_hooks: List[str] = field(default_factory=list)
    source: str = ""        # "user", "project", "bundled", or "entrypoint"
    path: Optional[str] = None
    kind: str = "standalone"   # standalone|backend|exclusive|platform|model-provider
    key: str = ""
```
Valid kinds set: `_VALID_PLUGIN_KINDS = {"standalone", "backend", "exclusive", "platform", "model-provider"}` (hermes_cli/plugins.py:277).

Parsed by `_parse_manifest` (hermes_cli/plugins.py:1563-1652), only for DIRECTORY-based plugins (bundled/user/project) — reads `child/plugin.yaml` or `child/plugin.yml` via `fast_safe_load(text)`. Recognized top-level yaml keys read directly: `name`, `version`, `kind`, `description`, `author`, `requires_env`, `provides_tools`, `provides_hooks`. Unknown `kind` value → warning + coerced to "standalone" (lines 1587-1592). If `kind` absent AND source-text heuristic on `__init__.py` (first 8192 bytes) finds `register_memory_provider`/`MemoryProvider` → coerced to "exclusive"; finds `register_provider` + `ProviderProfile` → coerced to "model-provider" (lines 1600-1629).

`requires_env` accepts two shapes (mixed freely in one list):
  - bare string: `"MY_API_KEY"` 
  - rich dict: `{name: str (required), description: str (optional), url: str (optional), secret: bool (optional)}`
Parsed/consumed by `hermes_cli/plugins_cmd.py:_missing_requires_env_names` (line 299) and `_prompt_plugin_env_vars` (line 317) — used ONLY by the interactive `hermes plugins install` flow to prompt+save to `.env`; it is NOT an enforced auto-disable gate inside the core `PluginManager` loader (no check found in `_load_plugin`/`_discover_and_load_inner`).

=== Entry-point-sourced manifests are minimal ===
`_scan_entry_points` (hermes_cli/plugins.py:1658-1682) builds `PluginManifest(name=ep.name, source="entrypoint", path=ep.value, key=ep.name)` — every other field (including `kind`) stays at dataclass default. No yaml is read for pip plugins by the general loader.

=== PluginContext (hermes_cli/plugins.py:339-1242) — full method inventory ===
Constructor: `__init__(self, manifest: PluginManifest, manager: "PluginManager")` (line 342).
Property `llm` (line 350-365): lazy `agent.plugin_llm.PluginLlm` facade for host-owned LLM calls.
Property `profile_name` (line 369-387): active Hermes profile name.

Methods (all `def register_*` in this class per grep):
1. `register_tool(name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False, description="", emoji="", override=False)` — line 391. Delegates to `tools.registry.registry.register(...)`; `override=True` gated by `plugins.entries.<id>.allow_tool_override` config unless plugin source is "bundled" (`_tool_override_allowed`, line 450).
2. `inject_message(content, role="user") -> bool` — line 476. Injects into active conversation via `self._manager._cli_ref`.
3. `register_cli_command(name, help, setup_fn, handler_fn=None, description="")` — line 504. Registers `hermes <name>` subcommand.
4. `register_command(name, handler, description="", args_hint="")` — line 529. Registers in-session slash command `/<name>`.
5. `dispatch_tool(tool_name, args, **kwargs) -> str` — line 585. Calls `tools.registry.registry.dispatch`.
6. `register_context_engine(engine)` — line 616. Must be instance of `agent.context_engine.ContextEngine`; only one allowed globally.
7. `register_image_gen_provider(provider)` — line 648. Must be `agent.image_gen_provider.ImageGenProvider`; delegates to `agent.image_gen_registry.register_provider`.
8. `register_dashboard_auth_provider(provider)` — line 675. `hermes_cli.dashboard_auth.DashboardAuthProvider`.
9. `register_video_gen_provider(provider)` — line 715. `agent.video_gen_provider.VideoGenProvider`.
10. `register_web_search_provider(provider)` — line 742. `agent.web_search_provider.WebSearchProvider`.
11. `register_browser_provider(provider)` — line 770. `agent.browser_provider.BrowserProvider`.
12. `register_secret_source(source)` — line 802. `agent.secret_sources.base.SecretSource`.
13. `register_tts_provider(provider)` — line 849. `agent.tts_provider.TTSProvider`; built-ins win name collisions.
14. `register_transcription_provider(provider)` — line 887. `agent.transcription_provider.TranscriptionProvider`.
15. `register_platform(name, label, adapter_factory, check_fn, validate_config=None, required_env=None, install_hint="", **entry_kwargs)` — line 931. Registers gateway `PlatformEntry` via `gateway.platform_registry.platform_registry`.
16. `register_slack_action_handler(action_id, callback)` — line 987. Slack Block Kit action handler.
17. `register_auxiliary_task(key, *, display_name, description, defaults=None)` — line 1047. Registers `auxiliary.<key>` LLM task config block.
18. `register_hook(hook_name, callback)` — line 1158. Adds to `VALID_HOOKS` lifecycle callbacks.
19. `register_middleware(kind, callback)` — line 1177. kind checked against `VALID_MIDDLEWARE` (from `hermes_cli.middleware`).
20. `register_skill(name, path: Path, description="")` — line 1198. Registers plugin skill as `'<plugin_name>:<name>'`.

NOTE: NO `register_model_provider`/`register_provider` method exists on PluginContext — model providers use the standalone `providers.register_provider()` function directly (see companion evidence "hermes-agent pip plugin discovery").

=== Loader/discovery functions (full quotes — see file directly) ===
- `_discover_and_load_inner` — hermes_cli/plugins.py:1317-1477 (orders: 1.bundled dir, 2.user dir `~/.hermes/plugins/`, 3.project dir `.hermes/plugins/` opt-in via `HERMES_ENABLE_PROJECT_PLUGINS`, 4. `_scan_entry_points()`).
- `_scan_directory`/`_scan_directory_level` — hermes_cli/plugins.py:1482-1561 (bundled/user/project dir scanner; flat OR one-level category nesting, e.g. `plugins/image_gen/openai/`).
- `_scan_entry_points` — hermes_cli/plugins.py:1658-1682 (pip plugins via `importlib.metadata.entry_points().select(group="hermes_agent.plugins")`).
- `_load_plugin` — hermes_cli/plugins.py:1748-1830 (imports module, calls `register(ctx)`, tracks what was registered via before/after diffing).
- `_load_directory_module` — hermes_cli/plugins.py:1832-1868 (imports directory plugin as `hermes_plugins.<slug>` via `importlib.util.spec_from_file_location`).
- `_load_entrypoint_module` — hermes_cli/plugins.py:1870-1886 (finds matching `ep.name==manifest.name` in group, calls `ep.load()`).

get_bundled_plugins_dir() — hermes_cli/plugins.py:55-65 — resolves to `<repo>/plugins` (or `HERMES_BUNDLED_PLUGINS` env override).
