"""Tests for the System Monitor subsystem."""

from __future__ import annotations

import asyncio
import time
from dataclasses import FrozenInstanceError
from datetime import datetime
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory
from atlas_core.monitor import (
    AlertManager,
    AlertRule,
    HealthChecker,
    HealthStatus,
    MonitorEventBridge,
    MonitorHistory,
    MonitorMetrics,
    PerformanceMonitor,
    ResourceMonitor,
    ResourceSnapshot,
    ServiceSnapshot,
    SystemMonitor,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def system_monitor(event_bus: EventBus) -> SystemMonitor:
    return SystemMonitor(event_bus)


@pytest.fixture
def mock_service() -> IService:
    svc = MagicMock(spec=IService)
    svc.name = "test_service"
    svc.health_check = AsyncMock(
        return_value=ServiceHealth(healthy=True, state=ServiceState.RUNNING)
    )
    return svc


# ======================================================================
# HealthStatus
# ======================================================================


class TestHealthStatus:
    def test_has_expected_members(self) -> None:
        assert len(HealthStatus) == 6
        assert HealthStatus.UNKNOWN.name == "UNKNOWN"
        assert HealthStatus.HEALTHY.name == "HEALTHY"
        assert HealthStatus.WARNING.name == "WARNING"
        assert HealthStatus.DEGRADED.name == "DEGRADED"
        assert HealthStatus.UNHEALTHY.name == "UNHEALTHY"
        assert HealthStatus.OFFLINE.name == "OFFLINE"

    def test_is_enum(self) -> None:
        assert issubclass(HealthStatus, Enum)

    def test_values_are_auto(self) -> None:
        values = [e.value for e in HealthStatus]
        assert values == [1, 2, 3, 4, 5, 6]


# ======================================================================
# ResourceSnapshot
# ======================================================================


class TestResourceSnapshot:
    def test_is_frozen_dataclass(self) -> None:
        snap = ResourceSnapshot()
        assert isinstance(snap, ResourceSnapshot)
        assert snap.cpu_percent == 0.0
        assert snap.memory_percent == 0.0
        assert snap.memory_used == 0
        assert snap.memory_available == 0
        assert snap.disk_percent == 0.0
        assert snap.disk_used == 0
        assert snap.disk_free == 0
        assert snap.process_count == 0
        assert snap.thread_count == 0
        assert snap.uptime == 0.0

    def test_is_frozen(self) -> None:
        snap = ResourceSnapshot()
        with pytest.raises(FrozenInstanceError):
            snap.cpu_percent = 50.0

    def test_timestamp_defaults(self) -> None:
        snap = ResourceSnapshot()
        assert isinstance(snap.timestamp, datetime)

    def test_custom_values(self) -> None:
        snap = ResourceSnapshot(
            cpu_percent=45.5,
            memory_percent=60.0,
            memory_used=8192,
            memory_available=4096,
            disk_percent=70.0,
            disk_used=50000,
            disk_free=20000,
            process_count=150,
            thread_count=800,
            uptime=12345.0,
        )
        assert snap.cpu_percent == 45.5
        assert snap.memory_percent == 60.0
        assert snap.memory_used == 8192
        assert snap.memory_available == 4096
        assert snap.disk_percent == 70.0
        assert snap.disk_used == 50000
        assert snap.disk_free == 20000
        assert snap.process_count == 150
        assert snap.thread_count == 800
        assert snap.uptime == 12345.0


# ======================================================================
# ServiceSnapshot
# ======================================================================


class TestServiceSnapshot:
    def test_is_frozen_dataclass(self) -> None:
        snap = ServiceSnapshot()
        assert snap.service_name == ""
        assert snap.state == ServiceState.CREATED
        assert snap.health == HealthStatus.UNKNOWN
        assert snap.uptime == 0.0
        assert snap.last_error == ""
        assert snap.restart_count == 0

    def test_is_frozen(self) -> None:
        snap = ServiceSnapshot()
        with pytest.raises(FrozenInstanceError):
            snap.service_name = "test"

    def test_custom_values(self) -> None:
        snap = ServiceSnapshot(
            service_name="atlas_kernel",
            state=ServiceState.RUNNING,
            health=HealthStatus.HEALTHY,
            uptime=3600.0,
            last_error="",
            restart_count=0,
        )
        assert snap.service_name == "atlas_kernel"
        assert snap.state == ServiceState.RUNNING
        assert snap.health == HealthStatus.HEALTHY
        assert snap.uptime == 3600.0


# ======================================================================
# AlertRule
# ======================================================================


class TestAlertRule:
    def test_is_frozen_dataclass(self) -> None:
        rule = AlertRule()
        assert rule.name == ""
        assert rule.condition == ""
        assert rule.severity == "info"
        assert rule.enabled is True

    def test_is_frozen(self) -> None:
        rule = AlertRule(name="test", condition="cpu>90", severity="critical")
        with pytest.raises(FrozenInstanceError):
            rule.name = "new_name"

    def test_custom_values(self) -> None:
        rule = AlertRule(
            name="high_cpu",
            condition="cpu_percent>90",
            severity="critical",
            enabled=True,
        )
        assert rule.name == "high_cpu"
        assert rule.condition == "cpu_percent>90"
        assert rule.severity == "critical"


# ======================================================================
# ResourceMonitor
# ======================================================================


class TestResourceMonitor:
    def test_snapshot_returns_resource_snapshot(self) -> None:
        rm = ResourceMonitor()
        snap = rm.snapshot()
        assert isinstance(snap, ResourceSnapshot)
        assert isinstance(snap.timestamp, datetime)
        assert snap.cpu_percent >= 0.0
        assert snap.process_count >= 0
        assert snap.thread_count >= 0

    def test_snapshot_includes_uptime(self) -> None:
        rm = ResourceMonitor()
        snap = rm.snapshot()
        assert snap.uptime >= 0.0

    def test_multiple_snapshots_increase_uptime(self) -> None:
        rm = ResourceMonitor()
        snap1 = rm.snapshot()
        time.sleep(0.01)
        snap2 = rm.snapshot()
        assert snap2.uptime > snap1.uptime

    def test_fallback_no_psutil(self) -> None:
        with patch("atlas_core.monitor._HAS_PSUTIL", False):
            rm = ResourceMonitor()
            snap = rm.snapshot()
            assert snap.cpu_percent == 0.0
            assert snap.memory_percent == 0.0
            assert snap.memory_used == 0
            assert snap.memory_available == 0
            assert snap.disk_percent == 0.0
            assert snap.disk_used == 0
            assert snap.disk_free == 0
            assert snap.process_count == 0
            assert snap.thread_count >= 0

    def test_psutil_path_integration(self) -> None:
        rm = ResourceMonitor()
        snap = rm.snapshot()
        assert isinstance(snap.cpu_percent, float)

    def test_get_cpu_returns_float(self) -> None:
        rm = ResourceMonitor()
        cpu = rm._get_cpu()
        assert isinstance(cpu, float)

    def test_get_memory_returns_object(self) -> None:
        rm = ResourceMonitor()
        mem = rm._get_memory()
        assert hasattr(mem, "percent")
        assert hasattr(mem, "used")
        assert hasattr(mem, "available")

    def test_get_disk_returns_object(self) -> None:
        rm = ResourceMonitor()
        disk = rm._get_disk()
        assert hasattr(disk, "percent")
        assert hasattr(disk, "used")
        assert hasattr(disk, "free")

    def test_get_processes_returns_int(self) -> None:
        rm = ResourceMonitor()
        count = rm._get_processes()
        assert isinstance(count, int)

    def test_get_threads_returns_int(self) -> None:
        rm = ResourceMonitor()
        count = rm._get_threads()
        assert isinstance(count, int)

    def test_fallback_get_cpu(self) -> None:
        with patch("atlas_core.monitor._HAS_PSUTIL", False):
            rm = ResourceMonitor()
            assert rm._get_cpu() == 0.0

    def test_fallback_get_memory(self) -> None:
        with patch("atlas_core.monitor._HAS_PSUTIL", False):
            rm = ResourceMonitor()
            mem = rm._get_memory()
            assert mem.percent == 0.0
            assert mem.used == 0
            assert mem.available == 0

    def test_fallback_get_disk(self) -> None:
        with patch("atlas_core.monitor._HAS_PSUTIL", False):
            rm = ResourceMonitor()
            disk = rm._get_disk()
            assert disk.percent == 0.0
            assert disk.used == 0
            assert disk.free == 0

    def test_fallback_get_processes(self) -> None:
        with patch("atlas_core.monitor._HAS_PSUTIL", False):
            rm = ResourceMonitor()
            assert rm._get_processes() == 0

    def test_fallback_get_threads_fallback(self) -> None:
        with patch("atlas_core.monitor._HAS_PSUTIL", False):
            rm = ResourceMonitor()
            assert rm._get_threads() >= 0

    def test_threading_active_count(self) -> None:
        rm = ResourceMonitor()
        threads = rm._get_threads()
        import threading
        assert threads == threading.active_count()


# ======================================================================
# HealthChecker
# ======================================================================


class TestHealthChecker:
    def test_check_healthy_service(self, mock_service: IService) -> None:
        hc = HealthChecker({"svc1": mock_service})
        hc.register_service_start_time("svc1")
        snap = asyncio.run(hc.check("svc1", mock_service))
        assert snap.service_name == "svc1"
        assert snap.health == HealthStatus.HEALTHY
        assert snap.state == ServiceState.RUNNING
        assert snap.uptime >= 0.0

    def test_check_unhealthy_service(self) -> None:
        svc = MagicMock(spec=IService)
        svc.name = "bad"
        svc.health_check = AsyncMock(
            return_value=ServiceHealth(healthy=False, state=ServiceState.RUNNING)
        )
        hc = HealthChecker({"bad": svc})
        hc.register_service_start_time("bad")
        snap = asyncio.run(hc.check("bad", svc))
        assert snap.health == HealthStatus.UNHEALTHY

    def test_check_exception_during_health(self) -> None:
        svc = MagicMock(spec=IService)
        svc.name = "broken"
        svc.health_check = AsyncMock(side_effect=RuntimeError("broken"))
        hc = HealthChecker({"broken": svc})
        snap = asyncio.run(hc.check("broken", svc))
        assert snap.health == HealthStatus.UNHEALTHY
        assert snap.last_error == "broken"
        assert snap.restart_count == 1

    def test_check_all_returns_dict(self, mock_service: IService) -> None:
        svc2 = MagicMock(spec=IService)
        svc2.name = "svc2"
        svc2.health_check = AsyncMock(
            return_value=ServiceHealth(healthy=True, state=ServiceState.RUNNING)
        )
        hc = HealthChecker({"svc1": mock_service, "svc2": svc2})
        hc.register_service_start_time("svc1")
        hc.register_service_start_time("svc2")
        results = asyncio.run(hc.check_all())
        assert len(results) == 2
        assert "svc1" in results
        assert "svc2" in results

    def test_map_health_running(self) -> None:
        h = HealthChecker._map_health(
            ServiceHealth(healthy=True, state=ServiceState.RUNNING)
        )
        assert h == HealthStatus.HEALTHY

    def test_map_health_starting(self) -> None:
        h = HealthChecker._map_health(
            ServiceHealth(healthy=True, state=ServiceState.STARTING)
        )
        assert h == HealthStatus.WARNING

    def test_map_health_initialized(self) -> None:
        h = HealthChecker._map_health(
            ServiceHealth(healthy=True, state=ServiceState.INITIALIZED)
        )
        assert h == HealthStatus.WARNING

    def test_map_health_stopped(self) -> None:
        h = HealthChecker._map_health(
            ServiceHealth(healthy=True, state=ServiceState.STOPPED)
        )
        assert h == HealthStatus.OFFLINE

    def test_map_health_disposed(self) -> None:
        h = HealthChecker._map_health(
            ServiceHealth(healthy=True, state=ServiceState.DISPOSED)
        )
        assert h == HealthStatus.OFFLINE

    def test_map_health_unhealthy(self) -> None:
        h = HealthChecker._map_health(
            ServiceHealth(healthy=False, state=ServiceState.RUNNING)
        )
        assert h == HealthStatus.UNHEALTHY

    def test_map_health_unknown(self) -> None:
        h = HealthChecker._map_health(
            ServiceHealth(healthy=True, state=ServiceState.CREATED)
        )
        assert h == HealthStatus.UNKNOWN

    def test_record_error_increments_restart_count(self) -> None:
        hc = HealthChecker({})
        hc.record_error("svc1", "error 1")
        assert hc._restart_counts["svc1"] == 1
        hc.record_error("svc1", "error 2")
        assert hc._restart_counts["svc1"] == 2

    def test_register_service_start_time(self) -> None:
        hc = HealthChecker({})
        hc.register_service_start_time("svc1")
        assert "svc1" in hc._start_times

    def test_check_without_start_time(self, mock_service: IService) -> None:
        hc = HealthChecker({"test": mock_service})
        snap = asyncio.run(hc.check("test", mock_service))
        assert snap.uptime >= 0.0

    def test_stopped_service_returns_offline(self) -> None:
        svc = MagicMock(spec=IService)
        svc.health_check = AsyncMock(
            return_value=ServiceHealth(healthy=True, state=ServiceState.STOPPED)
        )
        hc = HealthChecker({"s": svc})
        hc.register_service_start_time("s")
        snap = asyncio.run(hc.check("s", svc))
        assert snap.health == HealthStatus.OFFLINE


# ======================================================================
# PerformanceMonitor
# ======================================================================


class TestPerformanceMonitor:
    def test_event_throughput_initially_empty(self) -> None:
        pm = PerformanceMonitor()
        assert pm.event_throughput == {}

    def test_record_event_increments_count(self) -> None:
        pm = PerformanceMonitor()
        pm.record_event("system", 0.1)
        assert pm.event_throughput == {"system": 1.0}

    def test_record_event_multiple_categories(self) -> None:
        pm = PerformanceMonitor()
        pm.record_event("system", 0.1)
        pm.record_event("browser", 0.2)
        assert pm.event_throughput == {"system": 1.0, "browser": 1.0}

    def test_average_response_time_initially_zero(self) -> None:
        pm = PerformanceMonitor()
        assert pm.average_response_time == 0.0

    def test_average_response_time_computed(self) -> None:
        pm = PerformanceMonitor()
        pm.record_event("system", 0.1)
        pm.record_event("system", 0.3)
        assert pm.average_response_time == 0.2

    def test_service_latency_initially_empty(self) -> None:
        pm = PerformanceMonitor()
        assert pm.service_latency == {}

    def test_record_service_latency(self) -> None:
        pm = PerformanceMonitor()
        pm.record_service_latency("memory", 0.05)
        pm.record_service_latency("memory", 0.15)
        assert pm.service_latency["memory"] == 0.1

    def test_queue_sizes_initially_empty(self) -> None:
        pm = PerformanceMonitor()
        assert pm.queue_sizes == {}

    def test_set_queue_size(self) -> None:
        pm = PerformanceMonitor()
        pm.set_queue_size("events", 42)
        assert pm.queue_sizes == {"events": 42}

    def test_set_queue_size_overwrites(self) -> None:
        pm = PerformanceMonitor()
        pm.set_queue_size("events", 10)
        pm.set_queue_size("events", 20)
        assert pm.queue_sizes == {"events": 20}

    def test_execution_timings_initially_empty(self) -> None:
        pm = PerformanceMonitor()
        assert pm.execution_timings == {}

    def test_record_execution(self) -> None:
        pm = PerformanceMonitor()
        pm.record_execution("task1", 0.5)
        pm.record_execution("task1", 1.5)
        assert pm.execution_timings["task1"] == 1.0

    def test_snapshot_returns_dict(self) -> None:
        pm = PerformanceMonitor()
        pm.record_event("sys", 0.1)
        pm.record_service_latency("svc", 0.05)
        pm.set_queue_size("q", 5)
        s = pm.snapshot()
        assert "event_throughput" in s
        assert "average_response_time" in s
        assert "service_latency" in s
        assert "queue_sizes" in s
        assert "execution_timings" in s

    def test_thread_safety(self) -> None:
        pm = PerformanceMonitor()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(pm.record_event, "sys", i * 0.1) for i in range(100)]
            concurrent.futures.wait(futures)
        assert pm.event_throughput["sys"] == 100.0


# ======================================================================
# AlertManager
# ======================================================================


class TestAlertManager:
    def test_register_rule(self) -> None:
        am = AlertManager()
        rule = AlertRule(name="high_cpu", condition="cpu_percent>90", severity="critical")
        am.register(rule)
        assert len(am.list_rules()) == 1

    def test_remove_rule(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="r1", condition="cpu>50"))
        am.remove("r1")
        assert len(am.list_rules()) == 0

    def test_remove_nonexistent_does_not_raise(self) -> None:
        am = AlertManager()
        am.remove("nonexistent")

    def test_enable_rule(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="r1", condition="cpu>50", enabled=False))
        am.enable("r1")
        rule = am.list_rules()[0]
        assert rule.enabled is True

    def test_disable_rule(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="r1", condition="cpu>50"))
        am.disable("r1")
        rule = am.list_rules()[0]
        assert rule.enabled is False

    def test_enable_nonexistent_does_not_raise(self) -> None:
        am = AlertManager()
        am.enable("nonexistent")

    def test_disable_nonexistent_does_not_raise(self) -> None:
        am = AlertManager()
        am.disable("nonexistent")

    def test_evaluate_triggers_alert(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="cpu", condition="cpu_percent>90", severity="critical"))
        result = am.evaluate({"cpu_percent": 95})
        assert len(result) == 1
        assert result[0] == ("cpu", "critical", "triggered")

    def test_evaluate_no_match(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="cpu", condition="cpu_percent>90"))
        result = am.evaluate({"cpu_percent": 50})
        assert len(result) == 0

    def test_evaluate_disabled_rule(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="cpu", condition="cpu_percent>90", enabled=False))
        result = am.evaluate({"cpu_percent": 95})
        assert len(result) == 0

    def test_evaluate_resolved_alert(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="cpu", condition="cpu_percent>90"))
        am.evaluate({"cpu_percent": 95})
        result = am.evaluate({"cpu_percent": 50})
        assert len(result) == 1
        assert result[0][2] == "resolved"

    def test_active_alerts(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="cpu", condition="cpu_percent>90"))
        am.evaluate({"cpu_percent": 95})
        active = am.active_alerts()
        assert active == {"cpu": "info"}

    def test_active_alerts_empty_initially(self) -> None:
        am = AlertManager()
        assert am.active_alerts() == {}

    def test_list_rules_sorted(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="z_rule"))
        am.register(AlertRule(name="a_rule"))
        rules = am.list_rules()
        assert rules[0].name == "a_rule"
        assert rules[1].name == "z_rule"

    def test_evaluate_multiple_rules(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="cpu", condition="cpu_percent>80"))
        am.register(AlertRule(name="mem", condition="memory_percent>90"))
        result = am.evaluate({"cpu_percent": 85, "memory_percent": 50})
        assert len(result) == 1
        assert result[0][0] == "cpu"

    def test_evaluate_condition_greater(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("cpu>50", {"cpu": 60}) is True
        assert am._evaluate_condition("cpu>50", {"cpu": 40}) is False

    def test_evaluate_condition_less(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("mem<80", {"mem": 50}) is True
        assert am._evaluate_condition("mem<80", {"mem": 90}) is False

    def test_evaluate_condition_equal(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("count==5", {"count": 5}) is True
        assert am._evaluate_condition("count==5", {"count": 6}) is False

    def test_evaluate_condition_not_equal(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("status!=0", {"status": 1}) is True
        assert am._evaluate_condition("status!=0", {"status": 0}) is False

    def test_evaluate_condition_gte(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("cpu>=50", {"cpu": 50}) is True
        assert am._evaluate_condition("cpu>=50", {"cpu": 49}) is False

    def test_evaluate_condition_lte(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("cpu<=50", {"cpu": 50}) is True
        assert am._evaluate_condition("cpu<=50", {"cpu": 51}) is False

    def test_evaluate_condition_empty(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("", {}) is False

    def test_evaluate_condition_missing_key(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("missing>50", {}) is False

    def test_evaluate_condition_bad_format(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("invalid", {}) is False

    def test_evaluate_condition_bad_rhs(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("cpu>abc", {"cpu": 50}) is False

    def test_evaluate_condition_bad_lhs(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("cpu>50", {"cpu": "bad"}) is False

    def test_remove_clears_active_alert(self) -> None:
        am = AlertManager()
        am.register(AlertRule(name="cpu", condition="cpu>90"))
        am.evaluate({"cpu": 95})
        am.remove("cpu")
        assert am.active_alerts() == {}

    def test_evaluate_unregistered_condition_ops(self) -> None:
        am = AlertManager()
        assert am._evaluate_condition("cpu~50", {"cpu": 50}) is False


# ======================================================================
# MonitorHistory
# ======================================================================


class TestMonitorHistory:
    def test_snapshots_initially_empty(self) -> None:
        mh = MonitorHistory()
        assert mh.snapshots == []

    def test_record_snapshot(self) -> None:
        mh = MonitorHistory()
        snap = ResourceSnapshot(cpu_percent=50.0)
        mh.record_snapshot(snap)
        assert len(mh.snapshots) == 1

    def test_record_alert(self) -> None:
        mh = MonitorHistory()
        mh.record_alert("cpu", "critical", "triggered")
        assert len(mh.alerts) == 1
        name, severity, status, ts = mh.alerts[0]
        assert name == "cpu"
        assert severity == "critical"
        assert status == "triggered"

    def test_record_health_report(self) -> None:
        mh = MonitorHistory()
        report = {"svc1": ServiceSnapshot(service_name="svc1")}
        mh.record_health_report(report)
        assert len(mh.health_reports) == 1

    def test_max_size(self) -> None:
        mh = MonitorHistory(max_size=3)
        for i in range(5):
            mh.record_snapshot(ResourceSnapshot(cpu_percent=float(i)))
        assert len(mh.snapshots) == 3
        assert mh.snapshots[0].cpu_percent == 2.0
        assert mh.snapshots[-1].cpu_percent == 4.0

    def test_latest_snapshot(self) -> None:
        mh = MonitorHistory()
        assert mh.latest_snapshot is None
        mh.record_snapshot(ResourceSnapshot(cpu_percent=42.0))
        assert mh.latest_snapshot is not None
        assert mh.latest_snapshot.cpu_percent == 42.0

    def test_latest_health(self) -> None:
        mh = MonitorHistory()
        assert mh.latest_health is None
        mh.record_health_report({"svc": ServiceSnapshot()})
        assert mh.latest_health is not None

    def test_clear(self) -> None:
        mh = MonitorHistory()
        mh.record_snapshot(ResourceSnapshot())
        mh.record_alert("a", "warn", "triggered")
        mh.record_health_report({"s": ServiceSnapshot()})
        mh.clear()
        assert mh.snapshots == []
        assert mh.alerts == []
        assert mh.health_reports == []

    def test_alerts_initially_empty(self) -> None:
        mh = MonitorHistory()
        assert mh.alerts == []

    def test_health_reports_initially_empty(self) -> None:
        mh = MonitorHistory()
        assert mh.health_reports == []

    def test_max_size_default(self) -> None:
        mh = MonitorHistory()
        assert mh._max_size == 1000


# ======================================================================
# MonitorMetrics
# ======================================================================


class TestMonitorMetrics:
    def test_initial_values(self) -> None:
        m = MonitorMetrics()
        assert m.snapshots_taken == 0
        assert m.health_checks == 0
        assert m.alerts_generated == 0
        assert m.warnings == 0
        assert m.failures == 0
        assert m.average_health_latency == 0.0
        assert m.average_snapshot_latency == 0.0

    def test_record_snapshot(self) -> None:
        m = MonitorMetrics()
        m.record_snapshot(1.0)
        assert m.snapshots_taken == 1
        assert m.average_snapshot_latency == 1.0
        m.record_snapshot(3.0)
        assert m.snapshots_taken == 2
        assert m.average_snapshot_latency == 2.0

    def test_record_health_check(self) -> None:
        m = MonitorMetrics()
        m.record_health_check(0.5)
        assert m.health_checks == 1
        assert m.average_health_latency == 0.5

    def test_record_alert(self) -> None:
        m = MonitorMetrics()
        m.record_alert()
        assert m.alerts_generated == 1

    def test_record_warning(self) -> None:
        m = MonitorMetrics()
        m.record_warning()
        assert m.warnings == 1

    def test_record_failure(self) -> None:
        m = MonitorMetrics()
        m.record_failure()
        assert m.failures == 1

    def test_snapshot(self) -> None:
        m = MonitorMetrics()
        m.record_health_check(0.5)
        m.record_snapshot(1.0)
        s = m.snapshot()
        assert s["snapshots_taken"] == 1
        assert s["health_checks"] == 1
        assert s["average_health_latency"] == 0.5
        assert s["average_snapshot_latency"] == 1.0


# ======================================================================
# MonitorEventBridge
# ======================================================================


class TestMonitorEventBridge:
    @pytest.mark.asyncio
    async def test_publish(self, event_bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        event_bus.subscribe(EventCategory.MONITOR.value, handler)
        bridge = MonitorEventBridge(event_bus)
        await bridge.publish("TEST_EVENT", {"key": "value"})
        assert len(received) == 1
        assert received[0].category == EventCategory.MONITOR
        assert received[0].payload["event_type"] == "TEST_EVENT"

    @pytest.mark.asyncio
    async def test_publish_without_payload(self, event_bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        event_bus.subscribe(EventCategory.MONITOR.value, handler)
        bridge = MonitorEventBridge(event_bus)
        await bridge.publish("NO_PAYLOAD")
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_health_check_completed(self, event_bus: EventBus) -> None:
        bridge = MonitorEventBridge(event_bus)
        await bridge.health_check_completed({"svc": ServiceSnapshot()})

    @pytest.mark.asyncio
    async def test_resource_snapshot(self, event_bus: EventBus) -> None:
        bridge = MonitorEventBridge(event_bus)
        await bridge.resource_snapshot(ResourceSnapshot())

    @pytest.mark.asyncio
    async def test_service_degraded(self, event_bus: EventBus) -> None:
        bridge = MonitorEventBridge(event_bus)
        await bridge.service_degraded("svc", HealthStatus.DEGRADED)

    @pytest.mark.asyncio
    async def test_service_recovered(self, event_bus: EventBus) -> None:
        bridge = MonitorEventBridge(event_bus)
        await bridge.service_recovered("svc")

    @pytest.mark.asyncio
    async def test_alert_triggered(self, event_bus: EventBus) -> None:
        bridge = MonitorEventBridge(event_bus)
        await bridge.alert_triggered("cpu", "critical")

    @pytest.mark.asyncio
    async def test_alert_resolved(self, event_bus: EventBus) -> None:
        bridge = MonitorEventBridge(event_bus)
        await bridge.alert_resolved("cpu", "warning")

    @pytest.mark.asyncio
    async def test_publish_exception_does_not_raise(self, event_bus: EventBus) -> None:
        bridge = MonitorEventBridge(event_bus)
        event_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))
        await bridge.publish("TEST")  # should not raise


# ======================================================================
# SystemMonitor
# ======================================================================


class TestSystemMonitor:
    def test_name(self, system_monitor: SystemMonitor) -> None:
        assert system_monitor.name == "system_monitor"

    def test_properties(self, system_monitor: SystemMonitor) -> None:
        assert system_monitor.resource_monitor is not None
        assert system_monitor.health_checker is not None
        assert system_monitor.performance_monitor is not None
        assert system_monitor.alert_manager is not None
        assert system_monitor.history is not None
        assert system_monitor.metrics is not None
        assert system_monitor.event_bridge is not None

    def test_register_service(self, system_monitor: SystemMonitor, mock_service: IService) -> None:
        system_monitor.register_service("svc1", mock_service)
        assert "svc1" in system_monitor._services

    def test_set_monitor_interval(self, system_monitor: SystemMonitor) -> None:
        system_monitor.set_monitor_interval(5.0)
        assert system_monitor._monitor_interval == 5.0

    @pytest.mark.asyncio
    async def test_snapshot(self, system_monitor: SystemMonitor) -> None:
        snap = await system_monitor.snapshot()
        assert isinstance(snap, ResourceSnapshot)
        assert len(system_monitor.history.snapshots) == 1
        assert system_monitor.metrics.snapshots_taken == 1

    @pytest.mark.asyncio
    async def test_health(self, system_monitor: SystemMonitor) -> None:
        system_monitor.register_service("svc1", MagicMock(spec=IService, health_check=AsyncMock(
            return_value=ServiceHealth(healthy=True, state=ServiceState.RUNNING)
        )))
        results = await system_monitor.health()
        assert "svc1" in results
        assert system_monitor.metrics.health_checks == 1

    @pytest.mark.asyncio
    async def test_health_with_exception(self, system_monitor: SystemMonitor) -> None:
        bad = MagicMock(spec=IService, health_check=AsyncMock(side_effect=RuntimeError("fail")))
        system_monitor.register_service("bad", bad)
        results = await system_monitor.health()
        assert results["bad"].health == HealthStatus.UNHEALTHY

    @pytest.mark.asyncio
    async def test_performance(self, system_monitor: SystemMonitor) -> None:
        perf = await system_monitor.performance()
        assert isinstance(perf, dict)

    def test_register_alert(self, system_monitor: SystemMonitor) -> None:
        rule = AlertRule(name="cpu", condition="cpu>90")
        system_monitor.register_alert(rule)
        assert len(system_monitor.alert_manager.list_rules()) == 1

    def test_remove_alert(self, system_monitor: SystemMonitor) -> None:
        system_monitor.register_alert(AlertRule(name="cpu", condition="cpu>90"))
        system_monitor.remove_alert("cpu")
        assert system_monitor.alert_manager.list_rules() == []

    @pytest.mark.asyncio
    async def test_health_check_initial(self, system_monitor: SystemMonitor) -> None:
        health = await system_monitor.health_check()
        assert health.healthy is False
        assert health.state == ServiceState.CREATED

    @pytest.mark.asyncio
    async def test_health_check_after_start_stop(self, system_monitor: SystemMonitor) -> None:
        await system_monitor.start()
        health = await system_monitor.health_check()
        assert health.healthy is True
        assert health.state == ServiceState.RUNNING
        await system_monitor.stop()

    @pytest.mark.asyncio
    async def test_start_stop(self, system_monitor: SystemMonitor) -> None:
        await system_monitor.start()
        assert system_monitor._state == ServiceState.RUNNING
        assert system_monitor._running is True
        await system_monitor.stop()
        assert system_monitor._state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_monitoring_loop_runs_and_cancels(self, system_monitor: SystemMonitor) -> None:
        system_monitor.set_monitor_interval(0.01)
        await system_monitor.start()
        await asyncio.sleep(0.05)
        assert system_monitor.metrics.snapshots_taken > 0
        assert system_monitor.metrics.health_checks > 0
        await system_monitor.stop()

    @pytest.mark.asyncio
    async def test_start_monitoring(self, system_monitor: SystemMonitor) -> None:
        system_monitor.start_monitoring()
        assert system_monitor._running is True

    @pytest.mark.asyncio
    async def test_stop_monitoring(self, system_monitor: SystemMonitor) -> None:
        system_monitor.start_monitoring()
        system_monitor.stop_monitoring()
        assert system_monitor._running is False

    @pytest.mark.asyncio
    async def test_alert_integration(self, system_monitor: SystemMonitor) -> None:
        system_monitor.register_alert(AlertRule(name="cpu", condition="cpu_percent>90", severity="critical"))
        system_monitor.history.record_snapshot(ResourceSnapshot(cpu_percent=95.0))
        await system_monitor._evaluate_and_publish_alerts()
        assert system_monitor.metrics.alerts_generated > 0

    @pytest.mark.asyncio
    async def test_detect_state_change_degraded(self, system_monitor: SystemMonitor) -> None:
        healthy = ServiceSnapshot(service_name="svc", health=HealthStatus.HEALTHY)
        degraded = ServiceSnapshot(service_name="svc", health=HealthStatus.UNHEALTHY)
        system_monitor._last_health = {"svc": healthy}
        await system_monitor._detect_state_changes({"svc": degraded})

    @pytest.mark.asyncio
    async def test_detect_state_change_recovered(self, system_monitor: SystemMonitor) -> None:
        degraded = ServiceSnapshot(service_name="svc", health=HealthStatus.UNHEALTHY)
        healthy = ServiceSnapshot(service_name="svc", health=HealthStatus.HEALTHY)
        system_monitor._last_health = {"svc": degraded}
        await system_monitor._detect_state_changes({"svc": healthy})

    @pytest.mark.asyncio
    async def test_detect_state_no_previous(self, system_monitor: SystemMonitor) -> None:
        snap = ServiceSnapshot(service_name="svc", health=HealthStatus.HEALTHY)
        await system_monitor._detect_state_changes({"svc": snap})

    @pytest.mark.asyncio
    async def test_build_alert_context_with_history(self, system_monitor: SystemMonitor) -> None:
        system_monitor.history.record_snapshot(ResourceSnapshot(cpu_percent=50.0, memory_percent=60.0, disk_percent=70.0))
        ctx = system_monitor._build_alert_context()
        assert ctx["cpu_percent"] == 50.0
        assert ctx["memory_percent"] == 60.0
        assert ctx["disk_percent"] == 70.0

    @pytest.mark.asyncio
    async def test_build_alert_context_empty(self, system_monitor: SystemMonitor) -> None:
        ctx = system_monitor._build_alert_context()
        assert ctx == {}

    @pytest.mark.asyncio
    async def test_build_alert_context_with_health(self, system_monitor: SystemMonitor) -> None:
        report = {
            "svc1": ServiceSnapshot(service_name="svc1", health=HealthStatus.HEALTHY),
            "svc2": ServiceSnapshot(service_name="svc2", health=HealthStatus.UNHEALTHY),
        }
        system_monitor.history.record_health_report(report)
        ctx = system_monitor._build_alert_context()
        assert ctx["unhealthy_services"] == 1
        assert ctx["total_services"] == 2

    @pytest.mark.asyncio
    async def test_loop_error_does_not_stop_monitor(self, system_monitor: SystemMonitor) -> None:
        original = system_monitor.snapshot
        call_count = 0

        async def failing_snapshot():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("snapshot fail")
            return await original()

        system_monitor.snapshot = failing_snapshot  # type: ignore[assignment]
        system_monitor.set_monitor_interval(0.01)
        await system_monitor.start()
        await asyncio.sleep(0.05)
        assert system_monitor.metrics.failures > 0
        await system_monitor.stop()


# ======================================================================
# Kernel integration
# ======================================================================


class TestKernelIntegration:
    @pytest.mark.asyncio
    async def test_kernel_registers_system_monitor(self, tmp_path):
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
        assert kernel.registry.count == 12
        assert kernel.system_monitor is not None
        from atlas_core.monitor import SystemMonitor
        assert isinstance(kernel.system_monitor, SystemMonitor)

    @pytest.mark.asyncio
    async def test_kernel_before_init_raises(self):
        from atlas_core.kernel import AtlasKernel
        k = AtlasKernel()
        k.initialize()
        with pytest.raises(RuntimeError):
            _ = k.system_monitor


# ======================================================================
# IService compliance
# ======================================================================


class TestIServiceCompliance:
    def test_is_service(self, system_monitor: SystemMonitor) -> None:
        from atlas_core.interfaces import IService
        assert isinstance(system_monitor, IService)

    def test_has_name(self, system_monitor: SystemMonitor) -> None:
        assert isinstance(system_monitor.name, str)
        assert len(system_monitor.name) > 0

    def test_has_health_check(self, system_monitor: SystemMonitor) -> None:
        assert hasattr(system_monitor, "health_check")

    def test_has_start(self, system_monitor: SystemMonitor) -> None:
        assert hasattr(system_monitor, "start")

    def test_has_stop(self, system_monitor: SystemMonitor) -> None:
        assert hasattr(system_monitor, "stop")

    def test_has_initialize(self, system_monitor: SystemMonitor) -> None:
        assert hasattr(system_monitor, "initialize")


# ======================================================================
# EventCategory
# ======================================================================


class TestEventCategory:
    def test_monitor_category_exists(self) -> None:
        assert hasattr(EventCategory, "MONITOR")
        assert EventCategory.MONITOR.value == "monitor"
