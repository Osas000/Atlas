"""Tests for the health monitor."""

import pytest

from atlas_core.monitoring import HealthMonitor
from atlas_core.registry import ServiceRegistry
from tests.conftest import MockService


@pytest.fixture
def monitor(registry: ServiceRegistry) -> HealthMonitor:
    return HealthMonitor(registry)


class TestHealthMonitor:
    async def test_all_healthy(self, monitor: HealthMonitor, registry: ServiceRegistry) -> None:
        registry.register(MockService("a"))
        registry.register(MockService("b"))
        summary = await monitor.check_all()
        assert summary.status == "healthy"
        assert summary.healthy_services == 2
        assert summary.failed_services == 0

    async def test_some_unhealthy(self, monitor: HealthMonitor, registry: ServiceRegistry) -> None:
        registry.register(MockService("good"))
        registry.register(MockService("bad", health_override=False))
        summary = await monitor.check_all()
        assert summary.status == "degraded"
        assert summary.healthy_services == 1
        assert summary.failed_services == 1

    async def test_all_unhealthy(self, monitor: HealthMonitor, registry: ServiceRegistry) -> None:
        registry.register(MockService("bad1", health_override=False))
        registry.register(MockService("bad2", health_override=False))
        summary = await monitor.check_all()
        assert summary.status == "unhealthy"

    async def test_check_exception_handled(self, monitor: HealthMonitor, registry: ServiceRegistry) -> None:
        registry.register(MockService("broken", fail_health=True))
        summary = await monitor.check_all()
        assert summary.status == "unhealthy"
        assert summary.failed_services == 1

    async def test_empty_registry(self, monitor: HealthMonitor) -> None:
        summary = await monitor.check_all()
        assert summary.status == "healthy"
        assert summary.total_services == 0

    async def test_last_summary(self, monitor: HealthMonitor, registry: ServiceRegistry) -> None:
        assert monitor.last_summary is None
        registry.register(MockService("a"))
        await monitor.check_all()
        assert monitor.last_summary is not None
        assert monitor.last_summary.status == "healthy"
