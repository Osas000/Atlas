# Milestone 18: Plugin Framework

**Date:** 2026-07-23

## Summary

Plugin framework enables external modules to extend Atlas without modifying `atlas_core`. Plugins communicate through public interfaces and the Event Bus, never accessing private subsystem state.

## Components

### Core Plugin Types (`plugins/__init__.py`)
- **PluginState** — lifecycle states: DISCOVERED, LOADING, LOADED, UNLOADING, UNLOADED, FAILED
- **PluginCapability** — capability flags: SERVICE, EVENT_SUBSCRIBER, MISSION_HANDLER, AGENT_CAPABILITY, NOTIFICATION_RULE, MONITORING_PROVIDER
- **PluginManifest** — frozen dataclass with name, version, description, author, capabilities, dependencies
- **PluginMetadata** — runtime metadata: state, loaded_at, errors, metrics
- **Plugin** — base class for all plugins with `on_load()`, `on_unload()`, `on_reload()` lifecycle hooks

### Plugin Infrastructure
- **PluginContext** — sandboxed runtime context for plugins (service registry, event bus access)
- **PluginLoader** — discovers manifest files and loads plugin modules from `atlas_plugins.*` namespace
- **PluginRegistry** — thread-safe in-memory registry of loaded plugins with metadata
- **PluginDependencyResolver** — validates dependencies, resolves execution order (topological sort)
- **PluginSandbox** — isolated execution context with timeout and exception safety
- **PluginMetrics** — tracks load/unload counts, errors, timing
- **PluginEventBridge** — publishes plugin lifecycle events to the Event Bus

### PluginManager (IService)
- Full IService lifecycle (`create` → `boot` → `start` → `stop` → `dispose`)
- Registers as `plugin_manager` in the kernel service registry
- Health check reports loaded plugin count and metrics snapshot
- Methods: `discover_plugins()`, `load_plugin()`, `unload_plugin()`, `reload_plugin()`, `get_health_status()`

### Backward Compatibility
- Legacy `ModuleDefinition` dataclass and `ModuleLoader` class preserved for kernel interoperability
- `EventCategory.PLUGIN` added for plugin lifecycle events

## Files Changed

- `src/atlas_core/plugins/__init__.py` — 12 components, ~470 lines
- `src/atlas_core/interfaces/events.py` — added `PLUGIN` to `EventCategory`
- `src/atlas_core/kernel/__init__.py` — updated imports, registers PluginManager
- `tests/test_plugins.py` — 103 tests for all plugin components
- `tests/test_kernel.py` — service count expectations updated
- `tests/test_monitor.py` — `kernel.registry.count` updated to 11
- `tests/test_monitor_api.py` — `kernel.registry.count` updated to 11

## Test Results

- **Total:** 1687 tests passing (up from 1584)
- **Plugin coverage:** 95%
- No regressions in kernel, persistence, monitor, or monitoring API modules

## Notes

- Plugin framework is pure infrastructure — no AI, no browser, no business logic
- All plugin communication goes through public interfaces and Event Bus
- Private state access (`_`-prefixed members) is prohibited for plugins
- `PluginDependencyResolver.validate_manifest()` validates dependencies without requiring the plugin itself to be pre-registered
