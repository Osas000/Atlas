"""Plugin Framework — enables external modules to extend Atlas.

Plugins may register IService implementations, Event Bus subscribers,
mission handlers, agent capabilities, notification rules, and
monitoring providers.  Plugins never bypass the Event Bus and never
access private subsystem state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional as _Optional

from atlas_core.interfaces import IPlugin


@dataclass
class ModuleDefinition:
    """Legacy module definition — preserved for backward compatibility."""
    name: str
    version: str = "0.1.0"
    module_path: _Optional[Path] = None
    plugin_class: _Optional[type[IPlugin]] = None
    dependencies: list[str] = field(default_factory=list)
    enabled: bool = True


class ModuleLoader:
    """Legacy module loader — preserved for backward compatibility."""

    def __init__(self) -> None:
        self._modules: dict[str, ModuleDefinition] = {}

    def register(self, definition: ModuleDefinition) -> None:
        if definition.name in self._modules:
            raise ValueError(f"Module '{definition.name}' is already registered")
        self._modules[definition.name] = definition

    def discover(self, plugin_dirs: list[Path]) -> list[ModuleDefinition]:
        discovered: list[ModuleDefinition] = []
        for plugin_dir in plugin_dirs:
            if not plugin_dir.is_dir():
                continue
            for entry in plugin_dir.iterdir():
                if entry.is_dir() and (entry / "__init__.py").exists():
                    discovered.append(
                        ModuleDefinition(
                            name=entry.name,
                            version="0.1.0",
                            module_path=entry,
                        )
                    )
        return discovered

    def resolve(self, name: str) -> _Optional[ModuleDefinition]:
        return self._modules.get(name)

    @property
    def modules(self) -> dict[str, ModuleDefinition]:
        return dict(self._modules)

import importlib
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority
from atlas_core.registry import ServiceRegistry


# ======================================================================
# Enums
# ======================================================================


class PluginState(Enum):
    DISCOVERED = auto()
    LOADED = auto()
    ENABLED = auto()
    DISABLED = auto()
    UNLOADED = auto()
    FAILED = auto()


class PluginCapability(Enum):
    SERVICE = auto()
    EVENT_SUBSCRIBER = auto()
    MISSION_HANDLER = auto()
    AGENT_CAPABILITY = auto()
    NOTIFICATION_RULE = auto()
    MONITORING_PROVIDER = auto()


# ======================================================================
# PluginManifest
# ======================================================================


@dataclass(frozen=True)
class PluginManifest:
    name: str = ""
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    requires_atlas_version: str = "0.1.0"
    capabilities: tuple[PluginCapability, ...] = ()
    dependencies: tuple[str, ...] = ()


# ======================================================================
# PluginMetadata
# ======================================================================


@dataclass
class PluginMetadata:
    manifest: PluginManifest = field(default_factory=PluginManifest)
    state: PluginState = PluginState.DISCOVERED
    enabled: bool = False
    loaded_at: Optional[datetime] = None
    error_count: int = 0
    last_error: str = ""


# ======================================================================
# Plugin (base class)
# ======================================================================


class Plugin:
    """Base class that plugin implementations should extend."""

    def __init__(self, manifest: PluginManifest) -> None:
        self._manifest = manifest
        self._context: Optional[PluginContext] = None

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    @property
    def context(self) -> Optional[PluginContext]:
        return self._context

    async def on_load(self, context: PluginContext) -> None:
        self._context = context

    async def on_unload(self) -> None: ...

    async def on_enable(self) -> None: ...

    async def on_disable(self) -> None: ...

    def __repr__(self) -> str:
        return f"Plugin(name={self._manifest.name}, version={self._manifest.version})"


# ======================================================================
# PluginContext
# ======================================================================


@dataclass
class PluginContext:
    event_bus: EventBus
    registry: ServiceRegistry
    plugin_manager: Optional[PluginManager] = None
    data_dir: Optional[Path] = None
    config: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# PluginLoader
# ======================================================================


class PluginLoader:
    def __init__(self, plugin_dirs: list[Path] | None = None) -> None:
        self._plugin_dirs = plugin_dirs or []
        self._logger = logging.getLogger(__name__)

    def discover(self, directory: Path) -> list[PluginManifest]:
        manifests: list[PluginManifest] = []
        if not directory.is_dir():
            return manifests
        for entry in directory.iterdir():
            if entry.is_dir() and (entry / "__init__.py").exists():
                manifest = self._load_manifest_from_dir(entry)
                if manifest is not None:
                    manifests.append(manifest)
        return manifests

    def load_plugin(self, manifest: PluginManifest) -> Optional[Plugin]:
        try:
            module = importlib.import_module(f"atlas_plugins.{manifest.name}")
            if hasattr(module, "create_plugin"):
                plugin = module.create_plugin()
                if isinstance(plugin, Plugin):
                    return plugin
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, Plugin) and attr is not Plugin:
                    return attr(manifest)
        except Exception:
            self._logger.exception("Failed to load plugin: %s", manifest.name)
        return None

    def _load_manifest_from_dir(self, directory: Path) -> Optional[PluginManifest]:
        try:
            module = importlib.import_module(f"atlas_plugins.{directory.name}")
            if hasattr(module, "manifest"):
                m = module.manifest
                if isinstance(m, PluginManifest):
                    return m
            if hasattr(module, "__plugin_manifest__"):
                data = module.__plugin_manifest__
                if isinstance(data, dict):
                    return PluginManifest(
                        name=data.get("name", directory.name),
                        version=data.get("version", "0.1.0"),
                        description=data.get("description", ""),
                        author=data.get("author", ""),
                        requires_atlas_version=data.get("requires_atlas_version", "0.1.0"),
                        capabilities=tuple(
                            PluginCapability[c] for c in data.get("capabilities", [])
                            if c in PluginCapability.__members__
                        ),
                        dependencies=tuple(data.get("dependencies", [])),
                    )
            return PluginManifest(name=directory.name)
        except Exception:
            self._logger.exception("Failed to read manifest from: %s", directory.name)
        return None

    def set_plugin_dirs(self, dirs: list[Path]) -> None:
        self._plugin_dirs = dirs


# ======================================================================
# PluginRegistry
# ======================================================================


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._metadata: dict[str, PluginMetadata] = {}
        self._lock = threading.RLock()

    def register(self, plugin: Plugin, metadata: PluginMetadata | None = None) -> None:
        with self._lock:
            name = plugin.manifest.name
            if name in self._plugins:
                raise ValueError(f"Plugin already registered: {name}")
            self._plugins[name] = plugin
            self._metadata[name] = metadata or PluginMetadata(
                manifest=plugin.manifest,
                state=PluginState.DISCOVERED,
            )

    def unregister(self, name: str) -> None:
        with self._lock:
            self._plugins.pop(name, None)
            self._metadata.pop(name, None)

    def get_plugin(self, name: str) -> Optional[Plugin]:
        with self._lock:
            return self._plugins.get(name)

    def get_metadata(self, name: str) -> Optional[PluginMetadata]:
        with self._lock:
            return self._metadata.get(name)

    def list_plugins(self) -> list[str]:
        with self._lock:
            return sorted(self._plugins.keys())

    def list_by_state(self, state: PluginState) -> list[str]:
        with self._lock:
            return [n for n, m in self._metadata.items() if m.state == state]

    def list_by_capability(self, capability: PluginCapability) -> list[Plugin]:
        with self._lock:
            return [p for p in self._plugins.values() if capability in p.manifest.capabilities]

    def count(self) -> int:
        with self._lock:
            return len(self._plugins)

    def update_state(self, name: str, state: PluginState) -> None:
        with self._lock:
            if name in self._metadata:
                self._metadata[name].state = state

    def update_metadata(self, name: str, **kwargs: Any) -> None:
        with self._lock:
            meta = self._metadata.get(name)
            if meta is not None:
                for k, v in kwargs.items():
                    if hasattr(meta, k):
                        setattr(meta, k, v)

    def has_plugin(self, name: str) -> bool:
        with self._lock:
            return name in self._plugins


# ======================================================================
# PluginDependencyResolver
# ======================================================================


class PluginDependencyResolver:
    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    def resolve(self, name: str) -> list[str]:
        visited: set[str] = set()
        resolved: list[str] = []
        self._dfs(name, visited, set(), resolved)
        return resolved

    def validate(self, name: str) -> list[str]:
        errors: list[str] = []
        manifest = self._get_manifest(name)
        if manifest is None:
            errors.append(f"Plugin not found: {name}")
            return errors
        for dep in manifest.dependencies:
            dep_manifest = self._get_manifest(dep)
            if dep_manifest is None:
                errors.append(f"Missing dependency: {dep} (required by {name})")
            elif not self._registry.has_plugin(dep):
                errors.append(f"Dependency not registered: {dep} (required by {name})")
        return errors

    def validate_manifest(self, manifest: PluginManifest) -> list[str]:
        errors: list[str] = []
        for dep in manifest.dependencies:
            if not self._registry.has_plugin(dep):
                meta = self._registry.get_metadata(dep)
                if meta is None:
                    errors.append(f"Missing dependency: {dep} (required by {manifest.name})")
        return errors

    def dependency_graph(self) -> dict[str, list[str]]:
        graph: dict[str, list[str]] = {}
        for name in self._registry.list_plugins():
            manifest = self._get_manifest(name)
            graph[name] = list(manifest.dependencies) if manifest else []
        return graph

    def _get_manifest(self, name: str) -> Optional[PluginManifest]:
        meta = self._registry.get_metadata(name)
        if meta is not None:
            return meta.manifest
        return None

    def _dfs(
        self,
        name: str,
        visited: set[str],
        stack: set[str],
        resolved: list[str],
    ) -> None:
        if name in stack:
            raise ValueError(f"Circular dependency detected involving: {name}")
        if name in visited:
            return
        visited.add(name)
        stack.add(name)
        manifest = self._get_manifest(name)
        if manifest is not None:
            for dep in manifest.dependencies:
                self._dfs(dep, visited, stack, resolved)
        stack.discard(name)
        resolved.append(name)


# ======================================================================
# PluginSandbox
# ======================================================================


class PluginSandbox:
    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    async def execute(self, plugin: Plugin, action: str, *args: Any, **kwargs: Any) -> Any:
        try:
            if action == "load":
                context = kwargs.get("context")
                if context:
                    await plugin.on_load(context)
            elif action == "unload":
                await plugin.on_unload()
            elif action == "enable":
                await plugin.on_enable()
            elif action == "disable":
                await plugin.on_disable()
            else:
                raise ValueError(f"Unknown action: {action}")
        except Exception:
            self._logger.exception("Plugin %s failed during %s", plugin.manifest.name, action)
            raise


# ======================================================================
# PluginMetrics
# ======================================================================


@dataclass
class PluginMetrics:
    plugins_loaded: int = 0
    plugins_unloaded: int = 0
    plugins_enabled: int = 0
    plugins_disabled: int = 0
    plugins_failed: int = 0
    plugins_reloaded: int = 0
    total_load_errors: int = 0
    total_execution_errors: int = 0

    def record_load(self) -> None:
        self.plugins_loaded += 1

    def record_unload(self) -> None:
        self.plugins_unloaded += 1

    def record_enable(self) -> None:
        self.plugins_enabled += 1

    def record_disable(self) -> None:
        self.plugins_disabled += 1

    def record_failure(self) -> None:
        self.plugins_failed += 1

    def record_reload(self) -> None:
        self.plugins_reloaded += 1

    def record_load_error(self) -> None:
        self.total_load_errors += 1

    def record_execution_error(self) -> None:
        self.total_execution_errors += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "plugins_loaded": self.plugins_loaded,
            "plugins_unloaded": self.plugins_unloaded,
            "plugins_enabled": self.plugins_enabled,
            "plugins_disabled": self.plugins_disabled,
            "plugins_failed": self.plugins_failed,
            "plugins_reloaded": self.plugins_reloaded,
            "total_load_errors": self.total_load_errors,
            "total_execution_errors": self.total_execution_errors,
        }


# ======================================================================
# PluginEventBridge
# ======================================================================


class PluginEventBridge:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = Event(
            source="plugin_manager",
            category=EventCategory.PLUGIN,
            priority=EventPriority.NORMAL,
            payload={
                "event_type": event_type,
                **(payload or {}),
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish plugin event: %s", event_type)

    async def plugin_loaded(self, name: str, version: str) -> None:
        await self.publish("PLUGIN_LOADED", {"name": name, "version": version})

    async def plugin_unloaded(self, name: str) -> None:
        await self.publish("PLUGIN_UNLOADED", {"name": name})

    async def plugin_enabled(self, name: str) -> None:
        await self.publish("PLUGIN_ENABLED", {"name": name})

    async def plugin_disabled(self, name: str) -> None:
        await self.publish("PLUGIN_DISABLED", {"name": name})

    async def plugin_failed(self, name: str, error: str) -> None:
        await self.publish("PLUGIN_FAILED", {"name": name, "error": error})

    async def plugin_reloaded(self, name: str) -> None:
        await self.publish("PLUGIN_RELOADED", {"name": name})


# ======================================================================
# PluginManager (IService)
# ======================================================================


class PluginManager(IService):
    def __init__(
        self,
        event_bus: EventBus,
        registry: ServiceRegistry,
        plugin_dirs: list[Path] | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._service_registry = registry
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)

        self._plugin_dirs = plugin_dirs or []
        self._loader = PluginLoader(self._plugin_dirs)
        self._plugin_registry = PluginRegistry()
        self._dependency_resolver = PluginDependencyResolver(self._plugin_registry)
        self._sandbox = PluginSandbox()
        self._metrics = PluginMetrics()
        self._event_bridge = PluginEventBridge(event_bus)

    @property
    def name(self) -> str:
        return "plugin_manager"

    @property
    def plugin_registry(self) -> PluginRegistry:
        return self._plugin_registry

    @property
    def loader(self) -> PluginLoader:
        return self._loader

    @property
    def dependency_resolver(self) -> PluginDependencyResolver:
        return self._dependency_resolver

    @property
    def sandbox(self) -> PluginSandbox:
        return self._sandbox

    @property
    def metrics(self) -> PluginMetrics:
        return self._metrics

    @property
    def event_bridge(self) -> PluginEventBridge:
        return self._event_bridge

    async def start(self) -> None:
        await super().start()
        self._state = ServiceState.RUNNING
        self._logger.info("Plugin Manager started")

    async def stop(self) -> None:
        for name in self._plugin_registry.list_plugins():
            await self.unload_plugin(name)
        self._state = ServiceState.STOPPED
        await super().stop()
        self._logger.info("Plugin Manager stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=self._state == ServiceState.RUNNING,
            state=self._state,
            message=f"Plugin Manager: {self._plugin_registry.count()} plugins loaded",
            metadata=self._metrics.snapshot(),
        )

    def discover_plugins(self, directory: Path | None = None) -> list[PluginManifest]:
        dirs = [directory] if directory else self._plugin_dirs
        all_manifests: list[PluginManifest] = []
        for d in dirs:
            all_manifests.extend(self._loader.discover(d))
        return all_manifests

    async def load_plugin(self, manifest: PluginManifest) -> Optional[Plugin]:
        name = manifest.name
        if self._plugin_registry.has_plugin(name):
            self._logger.warning("Plugin already loaded: %s", name)
            return self._plugin_registry.get_plugin(name)

        errors = self._dependency_resolver.validate_manifest(manifest)
        if errors:
            self._metrics.record_load_error()
            await self._event_bridge.plugin_failed(name, "; ".join(errors))
            raise ValueError(f"Cannot load plugin '{name}': {'; '.join(errors)}")

        plugin = self._loader.load_plugin(manifest)
        if plugin is None:
            self._metrics.record_load_error()
            await self._event_bridge.plugin_failed(name, "Failed to instantiate plugin")
            raise RuntimeError(f"Failed to load plugin: {name}")

        context = PluginContext(
            event_bus=self._event_bus,
            registry=self._service_registry,
            plugin_manager=self,
        )
        metadata = PluginMetadata(
            manifest=manifest,
            state=PluginState.LOADED,
            enabled=False,
            loaded_at=datetime.now(),
        )
        self._plugin_registry.register(plugin, metadata)

        try:
            await self._sandbox.execute(plugin, "load", context=context)
            self._metrics.record_load()
            self._plugin_registry.update_state(name, PluginState.LOADED)
            await self._event_bridge.plugin_loaded(name, manifest.version)
            self._logger.info("Loaded plugin: %s v%s", name, manifest.version)
        except Exception:
            self._plugin_registry.update_state(name, PluginState.FAILED)
            self._metrics.record_failure()
            await self._event_bridge.plugin_failed(name, "Load failed")
            raise

        return plugin

    async def unload_plugin(self, name: str) -> None:
        plugin = self._plugin_registry.get_plugin(name)
        if plugin is None:
            return
        try:
            await self._sandbox.execute(plugin, "unload")
        except Exception:
            self._metrics.record_execution_error()
        self._plugin_registry.update_state(name, PluginState.UNLOADED)
        self._plugin_registry.unregister(name)
        self._metrics.record_unload()
        await self._event_bridge.plugin_unloaded(name)
        self._logger.info("Unloaded plugin: %s", name)

    async def reload_plugin(self, name: str) -> Optional[Plugin]:
        plugin = self._plugin_registry.get_plugin(name)
        if plugin is None:
            raise ValueError(f"Plugin not loaded: {name}")
        await self.unload_plugin(name)
        manifest = plugin.manifest
        result = await self.load_plugin(manifest)
        if result is not None:
            self._metrics.record_reload()
            await self._event_bridge.plugin_reloaded(name)
        return result

    async def enable_plugin(self, name: str) -> None:
        plugin = self._plugin_registry.get_plugin(name)
        if plugin is None:
            raise ValueError(f"Plugin not loaded: {name}")
        try:
            await self._sandbox.execute(plugin, "enable")
            self._plugin_registry.update_state(name, PluginState.ENABLED)
            self._plugin_registry.update_metadata(name, enabled=True)
            self._metrics.record_enable()
            await self._event_bridge.plugin_enabled(name)
            self._logger.info("Enabled plugin: %s", name)
        except Exception:
            self._plugin_registry.update_state(name, PluginState.FAILED)
            self._metrics.record_failure()
            await self._event_bridge.plugin_failed(name, "Enable failed")
            raise

    async def disable_plugin(self, name: str) -> None:
        plugin = self._plugin_registry.get_plugin(name)
        if plugin is None:
            raise ValueError(f"Plugin not loaded: {name}")
        try:
            await self._sandbox.execute(plugin, "disable")
        except Exception:
            self._metrics.record_execution_error()
        self._plugin_registry.update_state(name, PluginState.DISABLED)
        self._plugin_registry.update_metadata(name, enabled=False)
        self._metrics.record_disable()
        await self._event_bridge.plugin_disabled(name)
        self._logger.info("Disabled plugin: %s", name)

    def get_plugin(self, name: str) -> Optional[Plugin]:
        return self._plugin_registry.get_plugin(name)

    def get_metadata(self, name: str) -> Optional[PluginMetadata]:
        return self._plugin_registry.get_metadata(name)

    def list_plugins(self) -> list[str]:
        return self._plugin_registry.list_plugins()

    def list_by_state(self, state: PluginState) -> list[str]:
        return self._plugin_registry.list_by_state(state)

    def list_by_capability(self, capability: PluginCapability) -> list[Plugin]:
        return self._plugin_registry.list_by_capability(capability)

    async def load_plugins_from_directory(self, directory: Path) -> list[Plugin]:
        manifests = self.discover_plugins(directory)
        loaded: list[Plugin] = []
        for manifest in manifests:
            try:
                plugin = await self.load_plugin(manifest)
                if plugin is not None:
                    loaded.append(plugin)
            except Exception:
                self._logger.exception("Failed to load plugin: %s", manifest.name)
        return loaded
