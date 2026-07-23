"""Monitoring API — backend monitoring interface layer.

Exposes monitoring information to future clients.
Read-only. No business logic. No GUI. No web frontend.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Optional

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority
from atlas_core.monitor import (
    AlertRule,
    HealthStatus,
    ResourceSnapshot,
    ServiceSnapshot,
    SystemMonitor,
)
from atlas_core.persistence import PersistenceManager


# ======================================================================
# Enums
# ======================================================================


class StreamingChannel(Enum):
    HEALTH = auto()
    METRICS = auto()
    SNAPSHOTS = auto()
    ALERTS = auto()
    SYSTEM = auto()


# ======================================================================
# StreamingEvent
# ======================================================================


@dataclass(frozen=True)
class StreamingEvent:
    channel: StreamingChannel = StreamingChannel.SYSTEM
    event_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


# ======================================================================
# Subscription
# ======================================================================


@dataclass(frozen=True)
class Subscription:
    subscriber_id: str = ""
    channel: StreamingChannel = StreamingChannel.SYSTEM
    categories: tuple[EventCategory, ...] = ()
    services: tuple[str, ...] = ()
    severities: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    snapshot_types: tuple[str, ...] = ()

    def matches(self, event: StreamingEvent) -> bool:
        if self.channel != StreamingChannel.SYSTEM and event.channel != self.channel:
            return False
        payload = event.payload
        if self.services and payload.get("service") not in self.services:
            return False
        if self.severities and payload.get("severity") not in self.severities:
            return False
        if self.metrics and payload.get("metric") not in self.metrics:
            return False
        if self.snapshot_types and payload.get("snapshot_type") not in self.snapshot_types:
            return False
        return True


# ======================================================================
# SubscriptionManager
# ======================================================================


class SubscriptionManager:
    def __init__(self) -> None:
        self._subscribers: dict[str, Subscription] = {}
        self._lock = threading.RLock()

    def subscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscribers[subscription.subscriber_id] = subscription

    def unsubscribe(self, subscriber_id: str) -> None:
        with self._lock:
            self._subscribers.pop(subscriber_id, None)

    def get_subscription(self, subscriber_id: str) -> Optional[Subscription]:
        with self._lock:
            return self._subscribers.get(subscriber_id)

    def list_subscriptions(self) -> list[Subscription]:
        with self._lock:
            return list(self._subscribers.values())

    def count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def matching_subscribers(self, event: StreamingEvent) -> list[str]:
        with self._lock:
            return [
                sid for sid, sub in self._subscribers.items()
                if sub.matches(event)
            ]


# ======================================================================
# StreamingManager
# ======================================================================


class StreamingManager:
    def __init__(self, subscription_manager: SubscriptionManager) -> None:
        self._subscription_manager = subscription_manager
        self._queues: dict[str, asyncio.Queue[StreamingEvent]] = {}
        self._lock = threading.RLock()
        self._logger = logging.getLogger(__name__)

    async def subscribe(
        self,
        subscriber_id: str,
        channel: StreamingChannel = StreamingChannel.SYSTEM,
        **filters: Any,
    ) -> asyncio.Queue[StreamingEvent]:
        sub = Subscription(
            subscriber_id=subscriber_id,
            channel=channel,
            categories=filters.get("categories", ()),
            services=filters.get("services", ()),
            severities=filters.get("severities", ()),
            metrics=filters.get("metrics", ()),
            snapshot_types=filters.get("snapshot_types", ()),
        )
        self._subscription_manager.subscribe(sub)
        queue: asyncio.Queue[StreamingEvent] = asyncio.Queue()
        with self._lock:
            self._queues[subscriber_id] = queue
        return queue

    async def unsubscribe(self, subscriber_id: str) -> None:
        self._subscription_manager.unsubscribe(subscriber_id)
        with self._lock:
            self._queues.pop(subscriber_id, None)

    async def publish(self, event: StreamingEvent) -> int:
        subscriber_ids = self._subscription_manager.matching_subscribers(event)
        delivered = 0
        with self._lock:
            for sid in subscriber_ids:
                queue = self._queues.get(sid)
                if queue is None:
                    continue
                try:
                    queue.put_nowait(event)
                    delivered += 1
                except asyncio.QueueFull:
                    self._logger.warning("Queue full for subscriber %s, dropping event", sid)
        return delivered

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._queues)

    def active_subscribers(self) -> list[str]:
        with self._lock:
            return list(self._queues.keys())

    async def cleanup(self) -> None:
        with self._lock:
            self._queues.clear()


# ======================================================================
# HealthEndpoint
# ======================================================================


class HealthEndpoint:
    def __init__(self, system_monitor: SystemMonitor) -> None:
        self._monitor = system_monitor

    async def get_system_health(self) -> ServiceHealth:
        return await self._monitor.health_check()

    async def get_service_health(self, service_name: str | None = None) -> dict[str, ServiceSnapshot]:
        results = await self._monitor.health()
        if service_name:
            return {k: v for k, v in results.items() if k == service_name}
        return results

    async def get_health_summary(self) -> dict[str, Any]:
        health = await self._monitor.health()
        total = len(health)
        healthy = sum(1 for s in health.values() if s.health == HealthStatus.HEALTHY)
        warning = sum(1 for s in health.values() if s.health == HealthStatus.WARNING)
        degraded = sum(1 for s in health.values() if s.health == HealthStatus.DEGRADED)
        unhealthy = sum(1 for s in health.values() if s.health in (HealthStatus.UNHEALTHY, HealthStatus.OFFLINE))
        return {
            "total": total,
            "healthy": healthy,
            "warning": warning,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "status": "healthy" if unhealthy == 0 else "degraded" if healthy > 0 else "unhealthy",
        }


# ======================================================================
# MetricsEndpoint
# ======================================================================


class MetricsEndpoint:
    def __init__(self, system_monitor: SystemMonitor) -> None:
        self._monitor = system_monitor

    async def get_performance_metrics(self) -> dict[str, Any]:
        return await self._monitor.performance()

    def get_monitor_metrics(self) -> dict[str, Any]:
        return self._monitor.metrics.snapshot()

    def get_event_throughput(self) -> dict[str, float]:
        return self._monitor.performance_monitor.event_throughput

    def get_service_latency(self) -> dict[str, float]:
        return self._monitor.performance_monitor.service_latency

    def get_queue_sizes(self) -> dict[str, int]:
        return self._monitor.performance_monitor.queue_sizes


# ======================================================================
# SnapshotEndpoint
# ======================================================================


class SnapshotEndpoint:
    def __init__(self, system_monitor: SystemMonitor) -> None:
        self._monitor = system_monitor

    async def get_latest_snapshot(self) -> Optional[ResourceSnapshot]:
        return self._monitor.history.latest_snapshot

    def get_snapshots(self, count: int = 10) -> list[ResourceSnapshot]:
        return self._monitor.history.snapshots[-count:]

    async def take_snapshot(self) -> ResourceSnapshot:
        return await self._monitor.snapshot()


# ======================================================================
# AlertEndpoint
# ======================================================================


class AlertEndpoint:
    def __init__(self, system_monitor: SystemMonitor) -> None:
        self._monitor = system_monitor

    def get_active_alerts(self) -> dict[str, str]:
        return self._monitor.alert_manager.active_alerts()

    def list_rules(self) -> list[AlertRule]:
        return self._monitor.alert_manager.list_rules()

    def get_alert_history(self) -> list[tuple[str, str, str, float]]:
        return list(self._monitor.history.alerts)


# ======================================================================
# HistoryEndpoint
# ======================================================================


class HistoryEndpoint:
    def __init__(
        self,
        persistence_manager: PersistenceManager,
        system_monitor: SystemMonitor,
    ) -> None:
        self._persistence = persistence_manager
        self._monitor = system_monitor
        self._logger = logging.getLogger(__name__)

    async def save_snapshot(self, snapshot: ResourceSnapshot) -> None:
        try:
            await self._persistence.save(
                "monitor_snapshots",
                str(snapshot.timestamp.timestamp()),
                {
                    "cpu_percent": snapshot.cpu_percent,
                    "memory_percent": snapshot.memory_percent,
                    "memory_used": snapshot.memory_used,
                    "memory_available": snapshot.memory_available,
                    "disk_percent": snapshot.disk_percent,
                    "disk_used": snapshot.disk_used,
                    "disk_free": snapshot.disk_free,
                    "process_count": snapshot.process_count,
                    "thread_count": snapshot.thread_count,
                    "uptime": snapshot.uptime,
                    "timestamp": snapshot.timestamp.isoformat(),
                },
            )
        except Exception:
            self._logger.exception("Failed to save snapshot")

    async def save_health_report(self, report: dict[str, ServiceSnapshot]) -> None:
        try:
            await self._persistence.save(
                "monitor_health",
                str(datetime.now().timestamp()),
                {
                    name: {
                        "service_name": s.service_name,
                        "state": s.state.name,
                        "health": s.health.name,
                        "uptime": s.uptime,
                        "last_error": s.last_error,
                        "restart_count": s.restart_count,
                    }
                    for name, s in report.items()
                },
            )
        except Exception:
            self._logger.exception("Failed to save health report")

    async def save_alert(self, name: str, severity: str, status: str) -> None:
        try:
            await self._persistence.save(
                "monitor_alerts",
                f"{name}_{datetime.now().timestamp()}",
                {
                    "name": name,
                    "severity": severity,
                    "status": status,
                    "timestamp": datetime.now().isoformat(),
                },
            )
        except Exception:
            self._logger.exception("Failed to save alert")

    async def get_snapshots(self, limit: int = 50) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            keys = await self._persistence.list_keys("monitor_snapshots")
            for key in sorted(keys, reverse=True)[:limit]:
                val = await self._persistence.load("monitor_snapshots", key)
                if val is not None:
                    results.append(val if isinstance(val, dict) else {})
        except Exception:
            self._logger.exception("Failed to load snapshots from persistence")
        return results

    async def get_health_reports(self, limit: int = 50) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            keys = await self._persistence.list_keys("monitor_health")
            for key in sorted(keys, reverse=True)[:limit]:
                val = await self._persistence.load("monitor_health", key)
                if val is not None:
                    results.append(val if isinstance(val, dict) else {})
        except Exception:
            self._logger.exception("Failed to load health reports from persistence")
        return results

    async def get_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            keys = await self._persistence.list_keys("monitor_alerts")
            for key in sorted(keys, reverse=True)[:limit]:
                val = await self._persistence.load("monitor_alerts", key)
                if val is not None:
                    results.append(val if isinstance(val, dict) else {})
        except Exception:
            self._logger.exception("Failed to load alerts from persistence")
        return results

    async def get_by_time_range(
        self,
        collection: str,
        start: float,
        end: float,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            keys = await self._persistence.list_keys(collection)
            for key in keys:
                try:
                    ts = float(key.split("_")[-1] if "_" in key else key)
                except ValueError:
                    ts = 0.0
                if start <= ts <= end:
                    val = await self._persistence.load(collection, key)
                    if val is not None:
                        results.append(val if isinstance(val, dict) else {})
        except Exception:
            self._logger.exception("Failed to query by time range")
        return results


# ======================================================================
# MetricsAggregator
# ======================================================================


class MetricsAggregator:
    def __init__(self) -> None:
        self._subscriptions: int = 0
        self._messages_published: int = 0
        self._messages_dropped: int = 0
        self._history_reads: int = 0
        self._history_writes: int = 0
        self._stream_latencies: list[float] = []
        self._lock = threading.RLock()

    def record_subscription(self) -> None:
        with self._lock:
            self._subscriptions += 1

    def record_unsubscription(self) -> None:
        with self._lock:
            if self._subscriptions > 0:
                self._subscriptions -= 1

    def record_message_published(self) -> None:
        with self._lock:
            self._messages_published += 1

    def record_message_dropped(self) -> None:
        with self._lock:
            self._messages_dropped += 1

    def record_history_read(self) -> None:
        with self._lock:
            self._history_reads += 1

    def record_history_write(self) -> None:
        with self._lock:
            self._history_writes += 1

    def record_stream_latency(self, latency: float) -> None:
        with self._lock:
            self._stream_latencies.append(latency)

    @property
    def average_stream_latency(self) -> float:
        with self._lock:
            if not self._stream_latencies:
                return 0.0
            return sum(self._stream_latencies) / len(self._stream_latencies)

    @property
    def active_subscriptions(self) -> int:
        with self._lock:
            return self._subscriptions

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active_subscriptions": self._subscriptions,
                "messages_published": self._messages_published,
                "messages_dropped": self._messages_dropped,
                "history_reads": self._history_reads,
                "history_writes": self._history_writes,
                "average_stream_latency": self.average_stream_latency,
            }

    def reset(self) -> None:
        with self._lock:
            self._subscriptions = 0
            self._messages_published = 0
            self._messages_dropped = 0
            self._history_reads = 0
            self._history_writes = 0
            self._stream_latencies.clear()


# ======================================================================
# APIEventBridge
# ======================================================================


class APIEventBridge:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = Event(
            source="monitoring_api",
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
            self._logger.exception("Failed to publish API event: %s", event_type)

    async def health_requested(self) -> None:
        await self.publish("HEALTH_REQUESTED")

    async def metrics_requested(self) -> None:
        await self.publish("METRICS_REQUESTED")

    async def snapshot_requested(self) -> None:
        await self.publish("SNAPSHOT_REQUESTED")

    async def alerts_requested(self) -> None:
        await self.publish("ALERTS_REQUESTED")

    async def history_requested(self) -> None:
        await self.publish("HISTORY_REQUESTED")

    async def subscription_created(self, subscriber_id: str) -> None:
        await self.publish("SUBSCRIPTION_CREATED", {"subscriber_id": subscriber_id})

    async def subscription_removed(self, subscriber_id: str) -> None:
        await self.publish("SUBSCRIPTION_REMOVED", {"subscriber_id": subscriber_id})

    async def stream_event_published(self, channel: str, count: int) -> None:
        await self.publish("STREAM_EVENT_PUBLISHED", {"channel": channel, "count": count})


# ======================================================================
# MonitoringAPI (IService)
# ======================================================================


class MonitoringAPI(IService):
    def __init__(
        self,
        event_bus: EventBus,
        persistence_manager: PersistenceManager,
        system_monitor: SystemMonitor,
    ) -> None:
        self._event_bus = event_bus
        self._persistence = persistence_manager
        self._monitor = system_monitor
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)

        self._subscription_manager = SubscriptionManager()
        self._streaming_manager = StreamingManager(self._subscription_manager)
        self._health_endpoint = HealthEndpoint(system_monitor)
        self._metrics_endpoint = MetricsEndpoint(system_monitor)
        self._snapshot_endpoint = SnapshotEndpoint(system_monitor)
        self._alert_endpoint = AlertEndpoint(system_monitor)
        self._history_endpoint = HistoryEndpoint(persistence_manager, system_monitor)
        self._metrics_aggregator = MetricsAggregator()
        self._event_bridge = APIEventBridge(event_bus)

    @property
    def name(self) -> str:
        return "monitoring_api"

    @property
    def subscription_manager(self) -> SubscriptionManager:
        return self._subscription_manager

    @property
    def streaming_manager(self) -> StreamingManager:
        return self._streaming_manager

    @property
    def health(self) -> HealthEndpoint:
        return self._health_endpoint

    @property
    def metrics(self) -> MetricsEndpoint:
        return self._metrics_endpoint

    @property
    def snapshots(self) -> SnapshotEndpoint:
        return self._snapshot_endpoint

    @property
    def alerts(self) -> AlertEndpoint:
        return self._alert_endpoint

    @property
    def history(self) -> HistoryEndpoint:
        return self._history_endpoint

    @property
    def metrics_aggregator(self) -> MetricsAggregator:
        return self._metrics_aggregator

    @property
    def event_bridge(self) -> APIEventBridge:
        return self._event_bridge

    async def start(self) -> None:
        await super().start()
        self._state = ServiceState.RUNNING
        self._logger.info("Monitoring API started")

    async def stop(self) -> None:
        await self._streaming_manager.cleanup()
        self._state = ServiceState.STOPPED
        await super().stop()
        self._logger.info("Monitoring API stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=self._state == ServiceState.RUNNING,
            state=self._state,
            message=f"Monitoring API: {self._subscription_manager.count()} subscriptions",
            metadata=self._metrics_aggregator.snapshot(),
        )

    async def get_system_health(self) -> ServiceHealth:
        await self._event_bridge.health_requested()
        return await self._health_endpoint.get_system_health()

    async def get_service_health(self, service_name: str | None = None) -> dict[str, ServiceSnapshot]:
        await self._event_bridge.health_requested()
        return await self._health_endpoint.get_service_health(service_name)

    async def get_health_summary(self) -> dict[str, Any]:
        await self._event_bridge.health_requested()
        return await self._health_endpoint.get_health_summary()

    async def get_performance(self) -> dict[str, Any]:
        await self._event_bridge.metrics_requested()
        return await self._metrics_endpoint.get_performance_metrics()

    def get_monitor_metrics(self) -> dict[str, Any]:
        return self._metrics_endpoint.get_monitor_metrics()

    async def get_latest_snapshot(self) -> Optional[ResourceSnapshot]:
        await self._event_bridge.snapshot_requested()
        return await self._snapshot_endpoint.get_latest_snapshot()

    def get_snapshots(self, count: int = 10) -> list[ResourceSnapshot]:
        return self._snapshot_endpoint.get_snapshots(count)

    async def take_snapshot(self) -> ResourceSnapshot:
        await self._event_bridge.snapshot_requested()
        return await self._snapshot_endpoint.take_snapshot()

    def get_active_alerts(self) -> dict[str, str]:
        return self._alert_endpoint.get_active_alerts()

    def list_alert_rules(self) -> list[AlertRule]:
        return self._alert_endpoint.list_rules()

    def get_alert_history(self) -> list[tuple[str, str, str, float]]:
        return self._alert_endpoint.get_alert_history()

    async def stream_subscribe(
        self,
        subscriber_id: str,
        channel: StreamingChannel = StreamingChannel.SYSTEM,
        **filters: Any,
    ) -> asyncio.Queue[StreamingEvent]:
        self._metrics_aggregator.record_subscription()
        await self._event_bridge.subscription_created(subscriber_id)
        return await self._streaming_manager.subscribe(subscriber_id, channel, **filters)

    async def stream_unsubscribe(self, subscriber_id: str) -> None:
        self._metrics_aggregator.record_unsubscription()
        await self._event_bridge.subscription_removed(subscriber_id)
        await self._streaming_manager.unsubscribe(subscriber_id)

    async def stream_publish(self, event: StreamingEvent) -> int:
        start = time.time()
        count = await self._streaming_manager.publish(event)
        latency = time.time() - start
        if count > 0:
            self._metrics_aggregator.record_message_published()
            self._metrics_aggregator.record_stream_latency(latency)
        return count

    async def save_history_snapshot(self, snapshot: ResourceSnapshot) -> None:
        self._metrics_aggregator.record_history_write()
        await self._history_endpoint.save_snapshot(snapshot)

    async def save_history_health(self, report: dict[str, ServiceSnapshot]) -> None:
        self._metrics_aggregator.record_history_write()
        await self._history_endpoint.save_health_report(report)

    async def save_history_alert(self, name: str, severity: str, status: str) -> None:
        self._metrics_aggregator.record_history_write()
        await self._history_endpoint.save_alert(name, severity, status)

    async def get_history_snapshots(self, limit: int = 50) -> list[dict[str, Any]]:
        self._metrics_aggregator.record_history_read()
        return await self._history_endpoint.get_snapshots(limit)

    async def get_history_health(self, limit: int = 50) -> list[dict[str, Any]]:
        self._metrics_aggregator.record_history_read()
        return await self._history_endpoint.get_health_reports(limit)

    async def get_history_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        self._metrics_aggregator.record_history_read()
        return await self._history_endpoint.get_alerts(limit)

    async def get_history_by_time_range(
        self,
        collection: str,
        start: float,
        end: float,
    ) -> list[dict[str, Any]]:
        self._metrics_aggregator.record_history_read()
        return await self._history_endpoint.get_by_time_range(collection, start, end)

    def get_api_metrics(self) -> dict[str, Any]:
        return self._metrics_aggregator.snapshot()
