"""Tests for the lifecycle manager."""

import pytest

from atlas_core.interfaces import ServiceState
from atlas_core.lifecycle import LifecycleManager
from atlas_core.registry import ServiceRegistry
from tests.conftest import MockService


@pytest.fixture
def lifecycle(registry: ServiceRegistry) -> LifecycleManager:
    return LifecycleManager(registry)


class TestLifecycleManager:
    async def test_initialize_all(self, lifecycle: LifecycleManager, registry: ServiceRegistry) -> None:
        svc = MockService("test")
        registry.register(svc)
        await lifecycle.initialize_all()
        assert svc.initialized is True
        assert lifecycle.get_state("test") == ServiceState.INITIALIZED

    async def test_start_all(self, lifecycle: LifecycleManager, registry: ServiceRegistry) -> None:
        svc = MockService("test")
        registry.register(svc)
        await lifecycle.initialize_all()
        await lifecycle.start_all()
        assert svc.started is True
        assert lifecycle.get_state("test") == ServiceState.RUNNING

    async def test_stop_all(self, lifecycle: LifecycleManager, registry: ServiceRegistry) -> None:
        svc = MockService("test")
        registry.register(svc)
        await lifecycle.initialize_all()
        await lifecycle.start_all()
        await lifecycle.stop_all()
        assert svc.stopped is True
        assert lifecycle.get_state("test") == ServiceState.STOPPED

    async def test_dependency_order_init(self, lifecycle: LifecycleManager, registry: ServiceRegistry) -> None:
        a = MockService("a")
        b = MockService("b", deps=["a"])
        registry.register(b)
        registry.register(a)
        await lifecycle.initialize_all()
        # Both should be initialized regardless of registration order
        assert a.initialized is True
        assert b.initialized is True

    async def test_failed_init_does_not_block_others(self, lifecycle: LifecycleManager, registry: ServiceRegistry) -> None:
        good = MockService("good")
        bad = MockService("bad", fail_init=True)
        registry.register(good)
        registry.register(bad)
        await lifecycle.initialize_all()
        assert good.initialized is True
        assert bad.initialized is False
        assert lifecycle.get_state("bad") == ServiceState.FAILED

    async def test_failed_service_is_skipped_on_start(self, lifecycle: LifecycleManager, registry: ServiceRegistry) -> None:
        good = MockService("good")
        bad = MockService("bad", fail_init=True)
        registry.register(good)
        registry.register(bad)
        await lifecycle.initialize_all()
        await lifecycle.start_all()
        assert good.started is True
        assert bad.started is False

    async def test_states_property(self, lifecycle: LifecycleManager, registry: ServiceRegistry) -> None:
        svc = MockService("s")
        registry.register(svc)
        assert lifecycle.states == {}
        await lifecycle.initialize_all()
        assert lifecycle.states["s"] == ServiceState.INITIALIZED
