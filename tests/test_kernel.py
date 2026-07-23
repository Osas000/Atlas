"""Integration tests for the AtlasKernel."""

from pathlib import Path

import pytest

from atlas_core import __version__
from atlas_core.interfaces import IService, KernelState, ServiceState
from atlas_core.kernel import AtlasKernel
from tests.conftest import MockService


@pytest.fixture
def kernel(tmp_path: Path) -> AtlasKernel:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "default.yaml").write_text(
        "app_name: TestKernel\n"
        "version: 9.9.9\n"
        "log_level: DEBUG\n"
        "log_dir: '" + str(tmp_path / "logs").replace("\\", "\\\\") + "'\n"
    )
    return AtlasKernel(config_dir)


class TestAtlasKernel:
    async def test_initialize(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        assert kernel.state == KernelState.INITIALIZED
        assert kernel.config.app_name == "TestKernel"
        assert kernel.config.log_level == "DEBUG"
        assert kernel.registry.count == 0
        assert kernel.event_bus is not None

    async def test_boot(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.state == KernelState.BOOTED
        assert kernel.registry.count == 12  # memory_manager + operations_core + opportunity_engine + mission_control + notification_service + agent_runtime + multi_agent_runtime + persistence_manager + system_monitor + monitoring_api + plugin_manager + connector_manager
        assert kernel.operations_core is not None
        assert kernel.memory_manager is not None

    async def test_full_lifecycle(self, kernel: AtlasKernel) -> None:
        svc = MockService("test_svc")
        kernel.initialize()
        kernel.registry.register(svc)
        kernel.boot()
        await kernel.start()
        assert kernel.state == KernelState.RUNNING
        assert svc.initialized is True
        assert svc.started is True

        await kernel.stop()
        assert kernel.state == KernelState.STOPPED
        assert svc.stopped is True

    async def test_health_check(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        kernel.registry.register(MockService("healthy"))
        kernel.boot()
        await kernel.start()
        health = await kernel.health_check()
        assert health.status == "healthy"
        assert health.healthy_services == 13  # healthy + memory_manager + operations_core + opportunity_engine + mission_control + notification_service + agent_runtime + multi_agent_runtime + persistence_manager + system_monitor + monitoring_api + plugin_manager + connector_manager

    async def test_restart(self, kernel: AtlasKernel) -> None:
        svc = MockService("r")
        kernel.initialize()
        kernel.registry.register(svc)
        kernel.boot()
        await kernel.start()
        assert svc.started is True
        assert svc.stopped is False

        await kernel.restart()
        assert kernel.state == KernelState.RUNNING
        assert svc.stopped is True
        # After restart the service was re-registered so it's a new reference
        # (the old one was stopped).  In practice services re-register on boot.

    async def test_initialize_twice_raises(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        with pytest.raises(RuntimeError):
            kernel.initialize()

    async def test_boot_before_init_raises(self, kernel: AtlasKernel) -> None:
        with pytest.raises(RuntimeError):
            kernel.boot()

    async def test_start_before_boot_raises(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        with pytest.raises(RuntimeError):
            await kernel.start()

    async def test_config_before_init_raises(self) -> None:
        k = AtlasKernel()
        with pytest.raises(RuntimeError):
            _ = k.config

    async def test_registry_before_init_raises(self) -> None:
        k = AtlasKernel()
        with pytest.raises(RuntimeError):
            _ = k.registry

    async def test_event_bus_before_init_raises(self) -> None:
        k = AtlasKernel()
        with pytest.raises(RuntimeError):
            _ = k.event_bus

    async def test_operations_core_before_boot_raises(self) -> None:
        k = AtlasKernel()
        k.initialize()
        with pytest.raises(RuntimeError):
            _ = k.operations_core

    async def test_memory_manager_before_boot_raises(self) -> None:
        k = AtlasKernel()
        k.initialize()
        with pytest.raises(RuntimeError):
            _ = k.memory_manager

    async def test_memory_manager_property(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.memory_manager is not None
        from atlas_core.memory import MemoryManager
        assert isinstance(kernel.memory_manager, MemoryManager)
        assert kernel.memory_engine is kernel.memory_manager  # alias works

    async def test_event_bus_publishes_through_kernel(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        kernel.event_bus.subscribe("system", handler)
        from atlas_core.interfaces.events import Event, EventCategory
        await kernel.event_bus.publish(Event(source="kernel_test", category=EventCategory.SYSTEM))
        assert len(received) == 1
