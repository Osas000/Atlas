"""Tests for the Plugin Framework."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory
from atlas_core.plugins import (
    Plugin,
    PluginCapability,
    PluginContext,
    PluginDependencyResolver,
    PluginEventBridge,
    PluginLoader,
    PluginManager,
    PluginManifest,
    PluginMetadata,
    PluginMetrics,
    PluginRegistry,
    PluginSandbox,
    PluginState,
)
from atlas_core.registry import ServiceRegistry


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def registry() -> ServiceRegistry:
    return ServiceRegistry()


@pytest.fixture
def plugin_manager(event_bus: EventBus, registry: ServiceRegistry) -> PluginManager:
    return PluginManager(event_bus, registry)


@pytest.fixture
def sample_manifest() -> PluginManifest:
    return PluginManifest(
        name="test_plugin",
        version="1.0.0",
        description="A test plugin",
        author="tester",
        capabilities=(PluginCapability.SERVICE,),
        dependencies=(),
    )


@pytest.fixture
def sample_plugin(sample_manifest: PluginManifest) -> Plugin:
    return Plugin(sample_manifest)


# ======================================================================
# PluginState
# ======================================================================


class TestPluginState:
    def test_has_expected_members(self) -> None:
        assert len(PluginState) == 6
        assert PluginState.DISCOVERED.name == "DISCOVERED"
        assert PluginState.LOADED.name == "LOADED"
        assert PluginState.ENABLED.name == "ENABLED"
        assert PluginState.DISABLED.name == "DISABLED"
        assert PluginState.UNLOADED.name == "UNLOADED"
        assert PluginState.FAILED.name == "FAILED"


# ======================================================================
# PluginCapability
# ======================================================================


class TestPluginCapability:
    def test_has_expected_members(self) -> None:
        assert len(PluginCapability) == 6
        assert PluginCapability.SERVICE.name == "SERVICE"
        assert PluginCapability.EVENT_SUBSCRIBER.name == "EVENT_SUBSCRIBER"
        assert PluginCapability.MISSION_HANDLER.name == "MISSION_HANDLER"
        assert PluginCapability.AGENT_CAPABILITY.name == "AGENT_CAPABILITY"
        assert PluginCapability.NOTIFICATION_RULE.name == "NOTIFICATION_RULE"
        assert PluginCapability.MONITORING_PROVIDER.name == "MONITORING_PROVIDER"


# ======================================================================
# PluginManifest
# ======================================================================


class TestPluginManifest:
    def test_is_frozen(self) -> None:
        m = PluginManifest(name="p1")
        with pytest.raises(FrozenInstanceError):
            m.name = "p2"

    def test_defaults(self) -> None:
        m = PluginManifest()
        assert m.name == ""
        assert m.version == "0.1.0"
        assert m.description == ""
        assert m.author == ""
        assert m.requires_atlas_version == "0.1.0"
        assert m.capabilities == ()
        assert m.dependencies == ()

    def test_custom_values(self) -> None:
        m = PluginManifest(
            name="my_plugin",
            version="2.0.0",
            description="Does stuff",
            author="dev",
            capabilities=(PluginCapability.SERVICE, PluginCapability.EVENT_SUBSCRIBER),
            dependencies=("core", "utils"),
        )
        assert m.name == "my_plugin"
        assert len(m.capabilities) == 2
        assert "core" in m.dependencies


# ======================================================================
# PluginMetadata
# ======================================================================


class TestPluginMetadata:
    def test_defaults(self) -> None:
        m = PluginMetadata()
        assert m.state == PluginState.DISCOVERED
        assert m.enabled is False
        assert m.loaded_at is None
        assert m.error_count == 0
        assert m.last_error == ""

    def test_custom_values(self) -> None:
        m = PluginMetadata(
            manifest=PluginManifest(name="p1"),
            state=PluginState.LOADED,
            enabled=True,
            loaded_at=datetime(2026, 1, 1),
        )
        assert m.manifest.name == "p1"
        assert m.state == PluginState.LOADED
        assert m.enabled is True


# ======================================================================
# Plugin (base class)
# ======================================================================


class TestPlugin:
    def test_constructor(self, sample_manifest: PluginManifest) -> None:
        p = Plugin(sample_manifest)
        assert p.manifest == sample_manifest
        assert p.context is None

    def test_repr(self, sample_manifest: PluginManifest) -> None:
        p = Plugin(sample_manifest)
        assert "test_plugin" in repr(p)

    @pytest.mark.asyncio
    async def test_lifecycle_methods(self, sample_plugin: Plugin) -> None:
        ctx = PluginContext(event_bus=MagicMock(), registry=MagicMock())
        await sample_plugin.on_load(ctx)
        assert sample_plugin.context is not None
        await sample_plugin.on_enable()
        await sample_plugin.on_disable()
        await sample_plugin.on_unload()

    @pytest.mark.asyncio
    async def test_on_load_sets_context(self, sample_plugin: Plugin) -> None:
        ctx = PluginContext(event_bus=MagicMock(), registry=MagicMock())
        await sample_plugin.on_load(ctx)
        assert sample_plugin._context is ctx


# ======================================================================
# PluginContext
# ======================================================================


class TestPluginContext:
    def test_defaults(self) -> None:
        ctx = PluginContext(event_bus=MagicMock(), registry=MagicMock())
        assert ctx.plugin_manager is None
        assert ctx.data_dir is None
        assert ctx.config == {}

    def test_custom_values(self) -> None:
        ctx = PluginContext(
            event_bus=MagicMock(),
            registry=MagicMock(),
            config={"key": "value"},
        )
        assert ctx.config["key"] == "value"


# ======================================================================
# PluginLoader
# ======================================================================


class TestPluginLoader:
    def test_discover_empty_directory(self, tmp_path: Path) -> None:
        loader = PluginLoader()
        manifests = loader.discover(tmp_path / "nonexistent")
        assert manifests == []

    def test_discover_empty_dir(self, tmp_path: Path) -> None:
        loader = PluginLoader()
        d = tmp_path / "plugins"
        d.mkdir()
        manifests = loader.discover(d)
        assert manifests == []

    def test_discover_skips_non_dirs(self, tmp_path: Path) -> None:
        loader = PluginLoader()
        (tmp_path / "file.py").write_text("")
        manifests = loader.discover(tmp_path)
        assert manifests == []

    def test_set_plugin_dirs(self) -> None:
        loader = PluginLoader()
        d = Path("/test/plugins")
        loader.set_plugin_dirs([d])
        assert d in loader._plugin_dirs

    def test_load_plugin_nonexistent(self) -> None:
        loader = PluginLoader()
        m = PluginManifest(name="nonexistent_module")
        plugin = loader.load_plugin(m)
        assert plugin is None

    def test_load_manifest_from_dir_nonexistent(self) -> None:
        loader = PluginLoader()
        result = loader._load_manifest_from_dir(Path("/nonexistent"))
        assert result is None

    def test_scanned_dir_with_manifest_var(self, tmp_path: Path) -> None:
        import sys
        atlas_plugins_dir = tmp_path / "atlas_plugins"
        atlas_plugins_dir.mkdir()
        (atlas_plugins_dir / "__init__.py").write_text("")
        plugin_dir = atlas_plugins_dir / "my_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text(
            'from atlas_core.plugins import PluginCapability\n'
            '__plugin_manifest__ = {\n'
            '    "name": "my_plugin",\n'
            '    "version": "2.0.0",\n'
            '    "description": "A plugin",\n'
            '    "capabilities": ["SERVICE", "EVENT_SUBSCRIBER"],\n'
            '    "dependencies": ["core"],\n'
            '}\n'
        )
        try:
            sys.path.insert(0, str(tmp_path))
            import atlas_plugins  # noqa: F811
            loader = PluginLoader()
            manifests = loader.discover(atlas_plugins_dir)
            assert len(manifests) == 1
            assert manifests[0].name == "my_plugin"
            assert manifests[0].version == "2.0.0"
            assert PluginCapability.SERVICE in manifests[0].capabilities
        finally:
            sys.path.pop(0)
            if "atlas_plugins" in sys.modules:
                del sys.modules["atlas_plugins"]
            for k in list(sys.modules):
                if k.startswith("atlas_plugins."):
                    del sys.modules[k]

    def test_scanned_dir_fallback_name(self, tmp_path: Path) -> None:
        import sys
        atlas_plugins_dir = tmp_path / "atlas_plugins"
        atlas_plugins_dir.mkdir()
        (atlas_plugins_dir / "__init__.py").write_text("")
        plugin_dir = atlas_plugins_dir / "simple_plugin"
        plugin_dir.mkdir()
        (plugin_dir / "__init__.py").write_text("# empty plugin")
        try:
            sys.path.insert(0, str(tmp_path))
            import atlas_plugins  # noqa: F811
            loader = PluginLoader()
            manifests = loader.discover(atlas_plugins_dir)
            assert len(manifests) == 1
            assert manifests[0].name == "simple_plugin"
        finally:
            sys.path.pop(0)
            if "atlas_plugins" in sys.modules:
                del sys.modules["atlas_plugins"]
            for k in list(sys.modules):
                if k.startswith("atlas_plugins."):
                    del sys.modules[k]


# ======================================================================
# Legacy ModuleLoader
# ======================================================================


class TestLegacyModuleLoader:
    def test_register(self) -> None:
        from atlas_core.plugins import ModuleLoader, ModuleDefinition
        ml = ModuleLoader()
        ml.register(ModuleDefinition(name="test"))
        assert "test" in ml.modules

    def test_register_duplicate_raises(self) -> None:
        from atlas_core.plugins import ModuleLoader, ModuleDefinition
        ml = ModuleLoader()
        ml.register(ModuleDefinition(name="test"))
        with pytest.raises(ValueError):
            ml.register(ModuleDefinition(name="test"))

    def test_resolve(self) -> None:
        from atlas_core.plugins import ModuleLoader, ModuleDefinition
        ml = ModuleLoader()
        ml.register(ModuleDefinition(name="test"))
        assert ml.resolve("test") is not None
        assert ml.resolve("missing") is None

    def test_discover(self, tmp_path: Path) -> None:
        from atlas_core.plugins import ModuleLoader
        ml = ModuleLoader()
        (tmp_path / "p1" / "__init__.py").parent.mkdir(parents=True)
        (tmp_path / "p1" / "__init__.py").write_text("")
        discovered = ml.discover([tmp_path])
        assert len(discovered) == 1
        assert discovered[0].name == "p1"

    def test_discover_skips_non_dirs(self, tmp_path: Path) -> None:
        from atlas_core.plugins import ModuleLoader
        ml = ModuleLoader()
        (tmp_path / "file.py").write_text("")
        discovered = ml.discover([tmp_path])
        assert discovered == []

    def test_discover_nonexistent(self, tmp_path: Path) -> None:
        from atlas_core.plugins import ModuleLoader
        ml = ModuleLoader()
        discovered = ml.discover([tmp_path / "nonexistent"])
        assert discovered == []


# ======================================================================
# PluginRegistry
# ======================================================================


class TestPluginRegistry:
    def test_register_and_get(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        pr.register(sample_plugin)
        assert pr.count() == 1
        assert pr.get_plugin("test_plugin") is sample_plugin

    def test_register_duplicate_raises(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        pr.register(sample_plugin)
        with pytest.raises(ValueError, match="already registered"):
            pr.register(sample_plugin)

    def test_unregister(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        pr.register(sample_plugin)
        pr.unregister("test_plugin")
        assert pr.count() == 0

    def test_unregister_nonexistent(self) -> None:
        pr = PluginRegistry()
        pr.unregister("missing")

    def test_get_metadata(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        meta = PluginMetadata(manifest=sample_plugin.manifest)
        pr.register(sample_plugin, meta)
        assert pr.get_metadata("test_plugin") is meta

    def test_get_metadata_missing(self) -> None:
        pr = PluginRegistry()
        assert pr.get_metadata("missing") is None

    def test_get_plugin_missing(self) -> None:
        pr = PluginRegistry()
        assert pr.get_plugin("missing") is None

    def test_list_plugins(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        pr.register(sample_plugin)
        m2 = Plugin(PluginManifest(name="plugin_b"))
        pr.register(m2)
        assert pr.list_plugins() == ["plugin_b", "test_plugin"]

    def test_list_by_state(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        pr.register(sample_plugin, PluginMetadata(state=PluginState.LOADED))
        assert "test_plugin" in pr.list_by_state(PluginState.LOADED)
        assert "test_plugin" not in pr.list_by_state(PluginState.ENABLED)

    def test_list_by_capability(self) -> None:
        pr = PluginRegistry()
        p1 = Plugin(PluginManifest(name="p1", capabilities=(PluginCapability.SERVICE,)))
        p2 = Plugin(PluginManifest(name="p2", capabilities=(PluginCapability.EVENT_SUBSCRIBER,)))
        pr.register(p1)
        pr.register(p2)
        assert len(pr.list_by_capability(PluginCapability.SERVICE)) == 1
        assert len(pr.list_by_capability(PluginCapability.EVENT_SUBSCRIBER)) == 1

    def test_update_state(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        pr.register(sample_plugin)
        pr.update_state("test_plugin", PluginState.LOADED)
        assert pr.get_metadata("test_plugin").state == PluginState.LOADED

    def test_update_state_nonexistent(self) -> None:
        pr = PluginRegistry()
        pr.update_state("missing", PluginState.LOADED)

    def test_update_metadata(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        pr.register(sample_plugin)
        pr.update_metadata("test_plugin", enabled=True, error_count=5)
        meta = pr.get_metadata("test_plugin")
        assert meta.enabled is True
        assert meta.error_count == 5

    def test_update_metadata_nonexistent(self) -> None:
        pr = PluginRegistry()
        pr.update_metadata("missing", enabled=True)

    def test_has_plugin(self, sample_plugin: Plugin) -> None:
        pr = PluginRegistry()
        pr.register(sample_plugin)
        assert pr.has_plugin("test_plugin") is True
        assert pr.has_plugin("missing") is False

    def test_thread_safety(self) -> None:
        pr = PluginRegistry()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [
                ex.submit(pr.register, Plugin(PluginManifest(name=f"p{i}")))
                for i in range(100)
            ]
            concurrent.futures.wait(futures)
        assert pr.count() == 100


# ======================================================================
# PluginDependencyResolver
# ======================================================================


class TestPluginDependencyResolver:
    def test_resolve_no_deps(self) -> None:
        pr = PluginRegistry()
        pr.register(Plugin(PluginManifest(name="p1")))
        resolver = PluginDependencyResolver(pr)
        resolved = resolver.resolve("p1")
        assert resolved == ["p1"]

    def test_resolve_with_deps(self) -> None:
        pr = PluginRegistry()
        pr.register(Plugin(PluginManifest(name="core")))
        pr.register(Plugin(PluginManifest(name="utils", dependencies=("core",))))
        pr.register(Plugin(PluginManifest(name="app", dependencies=("utils",))))
        resolver = PluginDependencyResolver(pr)
        resolved = resolver.resolve("app")
        assert resolved == ["core", "utils", "app"]

    def test_resolve_circular_dependency(self) -> None:
        pr = PluginRegistry()
        pr.register(Plugin(PluginManifest(name="a", dependencies=("b",))))
        pr.register(Plugin(PluginManifest(name="b", dependencies=("a",))))
        resolver = PluginDependencyResolver(pr)
        with pytest.raises(ValueError, match="Circular"):
            resolver.resolve("a")

    def test_validate_no_errors(self) -> None:
        pr = PluginRegistry()
        pr.register(Plugin(PluginManifest(name="core")))
        pr.register(Plugin(PluginManifest(name="app", dependencies=("core",))))
        resolver = PluginDependencyResolver(pr)
        errors = resolver.validate("app")
        assert errors == []

    def test_validate_missing_dep(self) -> None:
        pr = PluginRegistry()
        pr.register(Plugin(PluginManifest(name="app", dependencies=("missing",))))
        resolver = PluginDependencyResolver(pr)
        errors = resolver.validate("app")
        assert len(errors) >= 1

    def test_validate_plugin_not_found(self) -> None:
        pr = PluginRegistry()
        resolver = PluginDependencyResolver(pr)
        errors = resolver.validate("nonexistent")
        assert len(errors) == 1

    def test_dependency_graph(self) -> None:
        pr = PluginRegistry()
        pr.register(Plugin(PluginManifest(name="a", dependencies=("b",))))
        pr.register(Plugin(PluginManifest(name="b")))
        resolver = PluginDependencyResolver(pr)
        graph = resolver.dependency_graph()
        assert "a" in graph
        assert "b" in graph
        assert "b" in graph["a"]


# ======================================================================
# PluginSandbox
# ======================================================================


class TestPluginSandbox:
    @pytest.mark.asyncio
    async def test_execute_load(self, sample_plugin: Plugin) -> None:
        sandbox = PluginSandbox()
        ctx = PluginContext(event_bus=MagicMock(), registry=MagicMock())
        await sandbox.execute(sample_plugin, "load", context=ctx)
        assert sample_plugin.context is not None

    @pytest.mark.asyncio
    async def test_execute_enable(self, sample_plugin: Plugin) -> None:
        sandbox = PluginSandbox()
        await sandbox.execute(sample_plugin, "enable")

    @pytest.mark.asyncio
    async def test_execute_disable(self, sample_plugin: Plugin) -> None:
        sandbox = PluginSandbox()
        await sandbox.execute(sample_plugin, "disable")

    @pytest.mark.asyncio
    async def test_execute_unload(self, sample_plugin: Plugin) -> None:
        sandbox = PluginSandbox()
        await sandbox.execute(sample_plugin, "unload")

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self, sample_plugin: Plugin) -> None:
        sandbox = PluginSandbox()
        with pytest.raises(ValueError, match="Unknown action"):
            await sandbox.execute(sample_plugin, "unknown")

    @pytest.mark.asyncio
    async def test_execute_load_without_context(self, sample_plugin: Plugin) -> None:
        sandbox = PluginSandbox()
        await sandbox.execute(sample_plugin, "load")

    @pytest.mark.asyncio
    async def test_execute_propagates_exception(self) -> None:
        class BrokenPlugin(Plugin):
            async def on_load(self, context: PluginContext) -> None:
                raise RuntimeError("broken")

        sandbox = PluginSandbox()
        plugin = BrokenPlugin(PluginManifest(name="broken"))
        ctx = PluginContext(event_bus=MagicMock(), registry=MagicMock())
        with pytest.raises(RuntimeError, match="broken"):
            await sandbox.execute(plugin, "load", context=ctx)


# ======================================================================
# PluginMetrics
# ======================================================================


class TestPluginMetrics:
    def test_initial_values(self) -> None:
        m = PluginMetrics()
        s = m.snapshot()
        assert s["plugins_loaded"] == 0
        assert s["plugins_unloaded"] == 0
        assert s["plugins_enabled"] == 0
        assert s["plugins_disabled"] == 0
        assert s["plugins_failed"] == 0
        assert s["plugins_reloaded"] == 0
        assert s["total_load_errors"] == 0
        assert s["total_execution_errors"] == 0

    def test_record_load(self) -> None:
        m = PluginMetrics()
        m.record_load()
        assert m.plugins_loaded == 1

    def test_record_unload(self) -> None:
        m = PluginMetrics()
        m.record_unload()
        assert m.plugins_unloaded == 1

    def test_record_enable(self) -> None:
        m = PluginMetrics()
        m.record_enable()
        assert m.plugins_enabled == 1

    def test_record_disable(self) -> None:
        m = PluginMetrics()
        m.record_disable()
        assert m.plugins_disabled == 1

    def test_record_failure(self) -> None:
        m = PluginMetrics()
        m.record_failure()
        assert m.plugins_failed == 1

    def test_record_reload(self) -> None:
        m = PluginMetrics()
        m.record_reload()
        assert m.plugins_reloaded == 1

    def test_record_load_error(self) -> None:
        m = PluginMetrics()
        m.record_load_error()
        assert m.total_load_errors == 1

    def test_record_execution_error(self) -> None:
        m = PluginMetrics()
        m.record_execution_error()
        assert m.total_execution_errors == 1


# ======================================================================
# PluginEventBridge
# ======================================================================


class TestPluginEventBridge:
    @pytest.mark.asyncio
    async def test_publish(self, event_bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        event_bus.subscribe(EventCategory.PLUGIN.value, handler)
        bridge = PluginEventBridge(event_bus)
        await bridge.publish("TEST", {"key": "val"})
        assert len(received) == 1
        assert received[0].category == EventCategory.PLUGIN

    @pytest.mark.asyncio
    async def test_plugin_loaded(self, event_bus: EventBus) -> None:
        bridge = PluginEventBridge(event_bus)
        await bridge.plugin_loaded("test", "1.0")

    @pytest.mark.asyncio
    async def test_plugin_unloaded(self, event_bus: EventBus) -> None:
        bridge = PluginEventBridge(event_bus)
        await bridge.plugin_unloaded("test")

    @pytest.mark.asyncio
    async def test_plugin_enabled(self, event_bus: EventBus) -> None:
        bridge = PluginEventBridge(event_bus)
        await bridge.plugin_enabled("test")

    @pytest.mark.asyncio
    async def test_plugin_disabled(self, event_bus: EventBus) -> None:
        bridge = PluginEventBridge(event_bus)
        await bridge.plugin_disabled("test")

    @pytest.mark.asyncio
    async def test_plugin_failed(self, event_bus: EventBus) -> None:
        bridge = PluginEventBridge(event_bus)
        await bridge.plugin_failed("test", "error msg")

    @pytest.mark.asyncio
    async def test_plugin_reloaded(self, event_bus: EventBus) -> None:
        bridge = PluginEventBridge(event_bus)
        await bridge.plugin_reloaded("test")

    @pytest.mark.asyncio
    async def test_publish_exception_does_not_raise(self, event_bus: EventBus) -> None:
        bridge = PluginEventBridge(event_bus)
        event_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))
        await bridge.publish("TEST")


# ======================================================================
# PluginManager (IService)
# ======================================================================


class TestPluginManager:
    def test_name(self, plugin_manager: PluginManager) -> None:
        assert plugin_manager.name == "plugin_manager"

    def test_properties(self, plugin_manager: PluginManager) -> None:
        assert plugin_manager.plugin_registry is not None
        assert plugin_manager.loader is not None
        assert plugin_manager.dependency_resolver is not None
        assert plugin_manager.sandbox is not None
        assert plugin_manager.metrics is not None
        assert plugin_manager.event_bridge is not None

    @pytest.mark.asyncio
    async def test_start_stop(self, plugin_manager: PluginManager) -> None:
        await plugin_manager.start()
        assert plugin_manager._state == ServiceState.RUNNING
        await plugin_manager.stop()
        assert plugin_manager._state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_health_check(self, plugin_manager: PluginManager) -> None:
        await plugin_manager.start()
        health = await plugin_manager.health_check()
        assert health.healthy is True
        await plugin_manager.stop()

    @pytest.mark.asyncio
    async def test_health_check_initial(self, plugin_manager: PluginManager) -> None:
        health = await plugin_manager.health_check()
        assert health.healthy is False

    @pytest.mark.asyncio
    async def test_load_plugin(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            result = await plugin_manager.load_plugin(sample_manifest)
            assert result is not None
            assert plugin_manager.plugin_registry.count() == 1
            assert plugin_manager.metrics.plugins_loaded == 1

    @pytest.mark.asyncio
    async def test_load_plugin_duplicate(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(sample_manifest)
            result = await plugin_manager.load_plugin(sample_manifest)
            assert result is not None

    @pytest.mark.asyncio
    async def test_load_plugin_fails_validation(self, plugin_manager: PluginManager) -> None:
        manifest = PluginManifest(name="app", dependencies=("missing",))
        with pytest.raises(ValueError, match="Cannot load plugin"):
            await plugin_manager.load_plugin(manifest)

    @pytest.mark.asyncio
    async def test_load_plugin_loader_fails(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin", return_value=None):
            with pytest.raises(RuntimeError, match="Failed to load"):
                await plugin_manager.load_plugin(sample_manifest)

    @pytest.mark.asyncio
    async def test_load_plugin_on_load_fails(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            p = Plugin(sample_manifest)
            orig_load = p.on_load

            async def failing_load(ctx: PluginContext) -> None:
                raise RuntimeError("on_load failed")

            p.on_load = failing_load  # type: ignore[method-assign]
            mock_load.return_value = p
            with pytest.raises(RuntimeError):
                await plugin_manager.load_plugin(sample_manifest)
            assert plugin_manager.metrics.plugins_failed == 1

    @pytest.mark.asyncio
    async def test_unload_plugin(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(sample_manifest)
            await plugin_manager.unload_plugin("test_plugin")
            assert plugin_manager.plugin_registry.count() == 0
            assert plugin_manager.metrics.plugins_unloaded == 1

    @pytest.mark.asyncio
    async def test_unload_nonexistent(self, plugin_manager: PluginManager) -> None:
        await plugin_manager.unload_plugin("missing")

    @pytest.mark.asyncio
    async def test_enable_plugin(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(sample_manifest)
            await plugin_manager.enable_plugin("test_plugin")
            meta = plugin_manager.get_metadata("test_plugin")
            assert meta.state == PluginState.ENABLED
            assert meta.enabled is True
            assert plugin_manager.metrics.plugins_enabled == 1

    @pytest.mark.asyncio
    async def test_enable_nonexistent(self, plugin_manager: PluginManager) -> None:
        with pytest.raises(ValueError, match="not loaded"):
            await plugin_manager.enable_plugin("missing")

    @pytest.mark.asyncio
    async def test_enable_fails(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            p = Plugin(sample_manifest)

            async def failing_enable() -> None:
                raise RuntimeError("enable failed")

            p.on_enable = failing_enable  # type: ignore[method-assign]
            mock_load.return_value = p
            await plugin_manager.load_plugin(sample_manifest)
            with pytest.raises(RuntimeError):
                await plugin_manager.enable_plugin("test_plugin")
            assert plugin_manager.metrics.plugins_failed == 1

    @pytest.mark.asyncio
    async def test_disable_plugin(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(sample_manifest)
            await plugin_manager.disable_plugin("test_plugin")
            meta = plugin_manager.get_metadata("test_plugin")
            assert meta.state == PluginState.DISABLED
            assert meta.enabled is False
            assert plugin_manager.metrics.plugins_disabled == 1

    @pytest.mark.asyncio
    async def test_disable_nonexistent(self, plugin_manager: PluginManager) -> None:
        with pytest.raises(ValueError, match="not loaded"):
            await plugin_manager.disable_plugin("missing")

    @pytest.mark.asyncio
    async def test_reload_plugin(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(sample_manifest)
            result = await plugin_manager.reload_plugin("test_plugin")
            assert result is not None
            assert plugin_manager.metrics.plugins_reloaded == 1

    @pytest.mark.asyncio
    async def test_reload_nonexistent(self, plugin_manager: PluginManager) -> None:
        with pytest.raises(ValueError, match="not loaded"):
            await plugin_manager.reload_plugin("missing")

    @pytest.mark.asyncio
    async def test_get_plugin(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(sample_manifest)
            assert plugin_manager.get_plugin("test_plugin") is not None
            assert plugin_manager.get_plugin("missing") is None

    @pytest.mark.asyncio
    async def test_list_plugins(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(sample_manifest)
            assert "test_plugin" in plugin_manager.list_plugins()

    @pytest.mark.asyncio
    async def test_list_by_state(self, plugin_manager: PluginManager, sample_manifest: PluginManifest) -> None:
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(sample_manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(sample_manifest)
            assert "test_plugin" in plugin_manager.list_by_state(PluginState.LOADED)

    @pytest.mark.asyncio
    async def test_list_by_capability(self, plugin_manager: PluginManager) -> None:
        manifest = PluginManifest(name="cap_plugin", capabilities=(PluginCapability.SERVICE,))
        with patch.object(plugin_manager._loader, "load_plugin") as mock_load:
            mock_plugin = Plugin(manifest)
            mock_load.return_value = mock_plugin
            await plugin_manager.load_plugin(manifest)
            assert len(plugin_manager.list_by_capability(PluginCapability.SERVICE)) == 1

    @pytest.mark.asyncio
    async def test_discover_plugins(self, plugin_manager: PluginManager, tmp_path: Path) -> None:
        manifests = plugin_manager.discover_plugins(tmp_path)
        assert manifests == []

    @pytest.mark.asyncio
    async def test_load_plugins_from_directory(self, plugin_manager: PluginManager, tmp_path: Path) -> None:
        loaded = await plugin_manager.load_plugins_from_directory(tmp_path)
        assert loaded == []

    @pytest.mark.asyncio
    async def test_iservice_compliance(self, plugin_manager: PluginManager) -> None:
        assert isinstance(plugin_manager, IService)


# ======================================================================
# EventCategory
# ======================================================================


class TestEventCategory:
    def test_plugin_category_exists(self) -> None:
        assert hasattr(EventCategory, "PLUGIN")
        assert EventCategory.PLUGIN.value == "plugin"


# ======================================================================
# Kernel integration
# ======================================================================


class TestKernelIntegration:
    @pytest.mark.asyncio
    async def test_kernel_registers_plugin_manager(self, tmp_path):
        from atlas_core.kernel import AtlasKernel
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "default.yaml").write_text(
            "app_name: TestKernel\n"
            "version: 9.9.9\n"
            "log_level: DEBUG\n"
            "log_dir: '" + str(tmp_path / "logs").replace("\\", "\\\\") + "'\n"
        )
        kernel = AtlasKernel(config_dir)
        kernel.initialize()
        kernel.boot()
        assert kernel.registry.count == 11
        assert kernel.plugin_manager is not None
        from atlas_core.plugins import PluginManager
        assert isinstance(kernel.plugin_manager, PluginManager)

    @pytest.mark.asyncio
    async def test_kernel_before_init_raises(self):
        from atlas_core.kernel import AtlasKernel
        k = AtlasKernel()
        k.initialize()
        with pytest.raises(RuntimeError):
            _ = k.plugin_manager
