"""System Monitor — purely observational observability subsystem.

Measures, monitors, and reports system health.
Never executes, never reasons, never modifies subsystem state.
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Optional

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


# ======================================================================
# Enums
# ======================================================================


class HealthStatus(Enum):
    UNKNOWN = auto()
    HEALTHY = auto()
    WARNING = auto()
    DEGRADED = auto()
    UNHEALTHY = auto()
    OFFLINE = auto()


# ======================================================================
# Snapshots
# ======================================================================


@dataclass(frozen=True)
class ResourceSnapshot:
    timestamp: datetime = field(default_factory=datetime.now)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used: int = 0
    memory_available: int = 0
    disk_percent: float = 0.0
    disk_used: int = 0
    disk_free: int = 0
    process_count: int = 0
    thread_count: int = 0
    uptime: float = 0.0


@dataclass(frozen=True)
class ServiceSnapshot:
    service_name: str = ""
    state: ServiceState = ServiceState.CREATED
    health: HealthStatus = HealthStatus.UNKNOWN
    uptime: float = 0.0
    last_error: str = ""
    restart_count: int = 0


# ======================================================================
# AlertRule
# ======================================================================


@dataclass(frozen=True)
class AlertRule:
    name: str = ""
    condition: str = ""
    severity: str = "info"
    enabled: bool = True


# ======================================================================
# ResourceMonitor
# ======================================================================


class ResourceMonitor:
    def __init__(self) -> None:
        self._start_time = time.time()
        self._logger = logging.getLogger(__name__)

    def snapshot(self) -> ResourceSnapshot:
        cpu = self._get_cpu()
        mem = self._get_memory()
        disk = self._get_disk()
        proc = self._get_processes()
        threads = self._get_threads()
        return ResourceSnapshot(
            cpu_percent=cpu,
            memory_percent=mem.percent,
            memory_used=mem.used,
            memory_available=mem.available,
            disk_percent=disk.percent,
            disk_used=disk.used,
            disk_free=disk.free,
            process_count=proc,
            thread_count=threads,
            uptime=time.time() - self._start_time,
        )

    def _get_cpu(self) -> float:
        if _HAS_PSUTIL:
            return psutil.cpu_percent(interval=0)
        return 0.0

    def _get_memory(self) -> Any:
        if _HAS_PSUTIL:
            return psutil.virtual_memory()

        class _Mem:
            def __init__(self) -> None:
                self.percent = 0.0
                self.used = 0
                self.available = 0

        return _Mem()

    def _get_disk(self) -> Any:
        if _HAS_PSUTIL:
            return psutil.disk_usage(os.path.abspath(os.sep))

        class _Disk:
            def __init__(self) -> None:
                self.percent = 0.0
                self.used = 0
                self.free = 0

        return _Disk()

    def _get_processes(self) -> int:
        if _HAS_PSUTIL:
            return len(psutil.pids())
        return 0

    def _get_threads(self) -> int:
        if _HAS_PSUTIL:
            return threading.active_count()
        return threading.active_count()


# ======================================================================
# HealthChecker
# ======================================================================


class HealthChecker:
    def __init__(self, services: dict[str, IService]) -> None:
        self._services = services
        self._logger = logging.getLogger(__name__)
        self._start_times: dict[str, float] = {}
        self._last_errors: dict[str, str] = {}
        self._restart_counts: dict[str, int] = {}

    def register_service_start_time(self, name: str) -> None:
        self._start_times[name] = time.time()

    def record_error(self, name: str, error: str) -> None:
        self._last_errors[name] = error
        self._restart_counts[name] = self._restart_counts.get(name, 0) + 1

    async def check(self, name: str, service: IService) -> ServiceSnapshot:
        try:
            health = await service.health_check()
            uptime = time.time() - self._start_times.get(name, time.time())
            status = self._map_health(health)
            return ServiceSnapshot(
                service_name=name,
                state=health.state,
                health=status,
                uptime=uptime,
                last_error=self._last_errors.get(name, ""),
                restart_count=self._restart_counts.get(name, 0),
            )
        except Exception as exc:
            self.record_error(name, str(exc))
            return ServiceSnapshot(
                service_name=name,
                state=ServiceState.FAILED,
                health=HealthStatus.UNHEALTHY,
                uptime=0.0,
                last_error=str(exc),
                restart_count=self._restart_counts.get(name, 0),
            )

    async def check_all(self) -> dict[str, ServiceSnapshot]:
        results: dict[str, ServiceSnapshot] = {}
        for name, service in self._services.items():
            results[name] = await self.check(name, service)
        return results

    @staticmethod
    def _map_health(health: ServiceHealth) -> HealthStatus:
        if not health.healthy:
            return HealthStatus.UNHEALTHY
        if health.state == ServiceState.RUNNING:
            return HealthStatus.HEALTHY
        if health.state in (ServiceState.STARTING, ServiceState.INITIALIZED):
            return HealthStatus.WARNING
        if health.state in (ServiceState.STOPPED, ServiceState.DISPOSED):
            return HealthStatus.OFFLINE
        return HealthStatus.UNKNOWN


# ======================================================================
# PerformanceMonitor
# ======================================================================


class PerformanceMonitor:
    def __init__(self) -> None:
        self._event_counts: dict[str, int] = {}
        self._event_times: dict[str, list[float]] = {}
        self._service_latencies: dict[str, list[float]] = {}
        self._execution_timings: dict[str, list[float]] = {}
        self._queue_sizes: dict[str, int] = {}
        self._lock = threading.RLock()

    def record_event(self, category: str, duration: float) -> None:
        with self._lock:
            self._event_counts[category] = self._event_counts.get(category, 0) + 1
            if category not in self._event_times:
                self._event_times[category] = []
            self._event_times[category].append(duration)

    def record_service_latency(self, service: str, duration: float) -> None:
        with self._lock:
            if service not in self._service_latencies:
                self._service_latencies[service] = []
            self._service_latencies[service].append(duration)

    def record_execution(self, name: str, duration: float) -> None:
        with self._lock:
            if name not in self._execution_timings:
                self._execution_timings[name] = []
            self._execution_timings[name].append(duration)

    def set_queue_size(self, queue: str, size: int) -> None:
        with self._lock:
            self._queue_sizes[queue] = size

    @property
    def event_throughput(self) -> dict[str, float]:
        with self._lock:
            return {k: float(v) for k, v in self._event_counts.items()}

    @property
    def average_response_time(self) -> float:
        with self._lock:
            all_times = [t for times in self._event_times.values() for t in times]
            if not all_times:
                return 0.0
            return sum(all_times) / len(all_times)

    @property
    def service_latency(self) -> dict[str, float]:
        with self._lock:
            result: dict[str, float] = {}
            for svc, times in self._service_latencies.items():
                if times:
                    result[svc] = sum(times) / len(times)
            return result

    @property
    def queue_sizes(self) -> dict[str, int]:
        with self._lock:
            return dict(self._queue_sizes)

    @property
    def execution_timings(self) -> dict[str, float]:
        with self._lock:
            result: dict[str, float] = {}
            for name, times in self._execution_timings.items():
                if times:
                    result[name] = sum(times) / len(times)
            return result

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "event_throughput": {k: float(v) for k, v in self._event_counts.items()},
                "average_response_time": self.average_response_time,
                "service_latency": dict(self._service_latencies),
                "queue_sizes": dict(self._queue_sizes),
                "execution_timings": dict(self._execution_timings),
            }


# ======================================================================
# AlertManager
# ======================================================================


class AlertManager:
    def __init__(self) -> None:
        self._rules: dict[str, AlertRule] = {}
        self._active_alerts: dict[str, str] = {}
        self._lock = threading.RLock()

    def register(self, rule: AlertRule) -> None:
        with self._lock:
            self._rules[rule.name] = rule

    def remove(self, name: str) -> None:
        with self._lock:
            self._rules.pop(name, None)
            self._active_alerts.pop(name, None)

    def enable(self, name: str) -> None:
        with self._lock:
            if name in self._rules:
                self._rules[name] = AlertRule(
                    name=self._rules[name].name,
                    condition=self._rules[name].condition,
                    severity=self._rules[name].severity,
                    enabled=True,
                )

    def disable(self, name: str) -> None:
        with self._lock:
            if name in self._rules:
                self._rules[name] = AlertRule(
                    name=self._rules[name].name,
                    condition=self._rules[name].condition,
                    severity=self._rules[name].severity,
                    enabled=False,
                )

    def evaluate(self, context: dict[str, Any]) -> list[tuple[str, str, str]]:
        triggered: list[tuple[str, str, str]] = []
        with self._lock:
            for name, rule in self._rules.items():
                if not rule.enabled:
                    continue
                if self._evaluate_condition(rule.condition, context):
                    was_active = name in self._active_alerts
                    self._active_alerts[name] = rule.severity
                    if not was_active:
                        triggered.append((name, rule.severity, "triggered"))
                else:
                    was_active = name in self._active_alerts
                    self._active_alerts.pop(name, None)
                    if was_active:
                        triggered.append((name, rule.severity, "resolved"))
        return triggered

    def list_rules(self) -> list[AlertRule]:
        with self._lock:
            return sorted(self._rules.values(), key=lambda r: r.name)

    def active_alerts(self) -> dict[str, str]:
        with self._lock:
            return dict(self._active_alerts)

    @staticmethod
    def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
        if not condition:
            return False
        import re
        m = re.match(r"^(\w+)\s*(>=|<=|!=|==|>|<)\s*([\d.]+)$", condition)
        if not m:
            return False
        key, op, rhs_str = m.groups()
        try:
            rhs = float(rhs_str)
        except ValueError:
            return False
        value = context.get(key)
        if value is None:
            return False
        try:
            lhs = float(value)
        except (ValueError, TypeError):
            return False
        if op == ">":
            return lhs > rhs
        if op == ">=":
            return lhs >= rhs
        if op == "<":
            return lhs < rhs
        if op == "<=":
            return lhs <= rhs
        if op == "==":
            return lhs == rhs
        if op == "!=":
            return lhs != rhs
        return False


# ======================================================================
# MonitorHistory
# ======================================================================


class MonitorHistory:
    def __init__(self, max_size: int = 1000) -> None:
        self._max_size = max_size
        self._snapshots: deque[ResourceSnapshot] = deque(maxlen=max_size)
        self._alerts: deque[tuple[str, str, str, float]] = deque(maxlen=max_size)
        self._health_reports: deque[dict[str, ServiceSnapshot]] = deque(maxlen=max_size)

    def record_snapshot(self, snapshot: ResourceSnapshot) -> None:
        self._snapshots.append(snapshot)

    def record_alert(self, name: str, severity: str, status: str) -> None:
        self._alerts.append((name, severity, status, time.time()))

    def record_health_report(self, report: dict[str, ServiceSnapshot]) -> None:
        self._health_reports.append(report)

    @property
    def snapshots(self) -> list[ResourceSnapshot]:
        return list(self._snapshots)

    @property
    def alerts(self) -> list[tuple[str, str, str, float]]:
        return list(self._alerts)

    @property
    def health_reports(self) -> list[dict[str, ServiceSnapshot]]:
        return list(self._health_reports)

    @property
    def latest_snapshot(self) -> Optional[ResourceSnapshot]:
        if self._snapshots:
            return self._snapshots[-1]
        return None

    @property
    def latest_health(self) -> Optional[dict[str, ServiceSnapshot]]:
        if self._health_reports:
            return self._health_reports[-1]
        return None

    def clear(self) -> None:
        self._snapshots.clear()
        self._alerts.clear()
        self._health_reports.clear()


# ======================================================================
# MonitorMetrics
# ======================================================================


@dataclass
class MonitorMetrics:
    snapshots_taken: int = 0
    health_checks: int = 0
    alerts_generated: int = 0
    warnings: int = 0
    failures: int = 0
    average_health_latency: float = 0.0
    average_snapshot_latency: float = 0.0

    _total_health_time: float = 0.0
    _total_snapshot_time: float = 0.0

    def record_snapshot(self, duration: float) -> None:
        self.snapshots_taken += 1
        self._total_snapshot_time += duration
        self.average_snapshot_latency = self._total_snapshot_time / self.snapshots_taken

    def record_health_check(self, duration: float) -> None:
        self.health_checks += 1
        self._total_health_time += duration
        self.average_health_latency = self._total_health_time / self.health_checks

    def record_alert(self) -> None:
        self.alerts_generated += 1

    def record_warning(self) -> None:
        self.warnings += 1

    def record_failure(self) -> None:
        self.failures += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "snapshots_taken": self.snapshots_taken,
            "health_checks": self.health_checks,
            "alerts_generated": self.alerts_generated,
            "warnings": self.warnings,
            "failures": self.failures,
            "average_health_latency": self.average_health_latency,
            "average_snapshot_latency": self.average_snapshot_latency,
        }


# ======================================================================
# MonitorEventBridge
# ======================================================================


class MonitorEventBridge:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = Event(
            source="system_monitor",
            category=EventCategory.MONITOR,
            priority=EventPriority.NORMAL,
            payload={
                "event_type": event_type,
                **(payload or {}),
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish monitor event: %s", event_type)

    async def health_check_completed(self, results: dict[str, ServiceSnapshot]) -> None:
        await self.publish("HEALTH_CHECK_COMPLETED", {
            "services": {k: v.service_name for k, v in results.items()},
        })

    async def resource_snapshot(self, snapshot: ResourceSnapshot) -> None:
        await self.publish("RESOURCE_SNAPSHOT", {
            "cpu_percent": snapshot.cpu_percent,
            "memory_percent": snapshot.memory_percent,
            "disk_percent": snapshot.disk_percent,
        })

    async def service_degraded(self, service: str, health: HealthStatus) -> None:
        await self.publish("SERVICE_DEGRADED", {
            "service": service,
            "health": health.name,
        })

    async def service_recovered(self, service: str) -> None:
        await self.publish("SERVICE_RECOVERED", {
            "service": service,
        })

    async def alert_triggered(self, name: str, severity: str) -> None:
        await self.publish("ALERT_TRIGGERED", {
            "name": name,
            "severity": severity,
        })

    async def alert_resolved(self, name: str, severity: str) -> None:
        await self.publish("ALERT_RESOLVED", {
            "name": name,
            "severity": severity,
        })

    async def transaction_started(self) -> None:
        await self.publish("TRANSACTION_STARTED")

    async def transaction_committed(self) -> None:
        await self.publish("TRANSACTION_COMMITTED")

    async def transaction_rolled_back(self) -> None:
        await self.publish("TRANSACTION_ROLLED_BACK")


# ======================================================================
# SystemMonitor (IService)
# ======================================================================


class SystemMonitor(IService):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)
        self._services: dict[str, IService] = {}
        self._resource_monitor = ResourceMonitor()
        self._health_checker = HealthChecker(self._services)
        self._performance_monitor = PerformanceMonitor()
        self._alert_manager = AlertManager()
        self._history = MonitorHistory()
        self._metrics = MonitorMetrics()
        self._event_bridge = MonitorEventBridge(event_bus)
        self._loop_task: Optional[asyncio.Task] = None
        self._running = False
        self._monitor_interval: float = 10.0
        self._last_health: dict[str, ServiceSnapshot] = {}

    @property
    def name(self) -> str:
        return "system_monitor"

    @property
    def resource_monitor(self) -> ResourceMonitor:
        return self._resource_monitor

    @property
    def health_checker(self) -> HealthChecker:
        return self._health_checker

    @property
    def performance_monitor(self) -> PerformanceMonitor:
        return self._performance_monitor

    @property
    def alert_manager(self) -> AlertManager:
        return self._alert_manager

    @property
    def history(self) -> MonitorHistory:
        return self._history

    @property
    def metrics(self) -> MonitorMetrics:
        return self._metrics

    @property
    def event_bridge(self) -> MonitorEventBridge:
        return self._event_bridge

    def register_service(self, name: str, service: IService) -> None:
        self._services[name] = service
        self._health_checker.register_service_start_time(name)

    def set_monitor_interval(self, interval: float) -> None:
        self._monitor_interval = interval

    async def start(self) -> None:
        await super().start()
        self._state = ServiceState.RUNNING
        self._running = True
        self._loop_task = asyncio.create_task(self._monitoring_loop())
        self._logger.info("System Monitor started (interval=%ss)", self._monitor_interval)

    async def stop(self) -> None:
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        self._state = ServiceState.STOPPED
        await super().stop()
        self._logger.info("System Monitor stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=self._state == ServiceState.RUNNING,
            state=self._state,
            message=f"System Monitor: {self._metrics.snapshots_taken} snapshots, {self._metrics.health_checks} checks",
            metadata=self._metrics.snapshot(),
        )

    async def snapshot(self) -> ResourceSnapshot:
        start = time.time()
        snap = self._resource_monitor.snapshot()
        self._history.record_snapshot(snap)
        self._metrics.record_snapshot(time.time() - start)
        await self._event_bridge.resource_snapshot(snap)
        return snap

    async def health(self) -> dict[str, ServiceSnapshot]:
        start = time.time()
        results = await self._health_checker.check_all()
        self._history.record_health_report(results)
        self._metrics.record_health_check(time.time() - start)
        await self._detect_state_changes(results)
        await self._event_bridge.health_check_completed(results)
        self._last_health = results
        return results

    async def performance(self) -> dict[str, Any]:
        return self._performance_monitor.snapshot()

    def register_alert(self, rule: AlertRule) -> None:
        self._alert_manager.register(rule)

    def remove_alert(self, name: str) -> None:
        self._alert_manager.remove(name)

    def start_monitoring(self) -> None:
        if not self._running:
            self._running = True
            self._loop_task = asyncio.create_task(self._monitoring_loop())

    def stop_monitoring(self) -> None:
        self._running = False

    async def _monitoring_loop(self) -> None:
        while self._running:
            try:
                await self.snapshot()
                await self.health()
                await self._evaluate_and_publish_alerts()
                await asyncio.sleep(self._monitor_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                self._logger.exception("Monitoring loop error")
                self._metrics.record_failure()

    async def _evaluate_and_publish_alerts(self) -> None:
        context = self._build_alert_context()
        triggered = self._alert_manager.evaluate(context)
        for name, severity, status in triggered:
            if status == "triggered":
                self._metrics.record_alert()
                await self._event_bridge.alert_triggered(name, severity)
            else:
                await self._event_bridge.alert_resolved(name, severity)
            self._history.record_alert(name, severity, status)

    def _build_alert_context(self) -> dict[str, Any]:
        context: dict[str, Any] = {}
        latest = self._history.latest_snapshot
        if latest:
            context["cpu_percent"] = latest.cpu_percent
            context["memory_percent"] = latest.memory_percent
            context["disk_percent"] = latest.disk_percent
        health = self._history.latest_health
        if health:
            unhealthy = sum(1 for s in health.values() if s.health in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED))
            context["unhealthy_services"] = unhealthy
            context["total_services"] = len(health)
        return context

    async def _detect_state_changes(self, results: dict[str, ServiceSnapshot]) -> None:
        if not self._last_health:
            return
        for name, current in results.items():
            previous = self._last_health.get(name)
            if previous is None:
                continue
            if previous.health in (HealthStatus.HEALTHY, HealthStatus.WARNING) and current.health in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED):
                await self._event_bridge.service_degraded(name, current.health)
            elif current.health == HealthStatus.HEALTHY and previous.health in (HealthStatus.UNHEALTHY, HealthStatus.DEGRADED, HealthStatus.OFFLINE):
                await self._event_bridge.service_recovered(name)
