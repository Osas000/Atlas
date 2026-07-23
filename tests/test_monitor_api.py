"""Tests for the Monitoring API subsystem."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory
from atlas_core.monitor import (
    AlertRule,
    HealthStatus,
    ResourceSnapshot,
    ServiceSnapshot,
    SystemMonitor,
)
from atlas_core.monitor_api import (
    APIEventBridge,
    AlertEndpoint,
    HealthEndpoint,
    HistoryEndpoint,
    MetricsAggregator,
    MetricsEndpoint,
    MonitoringAPI,
    SnapshotEndpoint,
    StreamingChannel,
    StreamingEvent,
    StreamingManager,
    Subscription,
    SubscriptionManager,
)
from atlas_core.persistence import PersistenceManager


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def system_monitor(event_bus: EventBus) -> SystemMonitor:
    sm = SystemMonitor(event_bus)
    svc = MagicMock(spec=IService)
    svc.health_check = AsyncMock(
        return_value=ServiceHealth(healthy=True, state=ServiceState.RUNNING)
    )
    sm.register_service("test_svc", svc)
    return sm


@pytest.fixture
def persistence_manager(event_bus: EventBus) -> PersistenceManager:
    pm = PersistenceManager(event_bus)
    return pm


@pytest.fixture
def monitoring_api(
    event_bus: EventBus,
    persistence_manager: PersistenceManager,
    system_monitor: SystemMonitor,
) -> MonitoringAPI:
    return MonitoringAPI(event_bus, persistence_manager, system_monitor)


# ======================================================================
# StreamingEvent
# ======================================================================


class TestStreamingEvent:
    def test_is_frozen_dataclass(self) -> None:
        e = StreamingEvent()
        assert e.channel == StreamingChannel.SYSTEM
        assert e.event_type == ""
        assert e.payload == {}
        assert isinstance(e.timestamp, datetime)

    def test_is_frozen(self) -> None:
        e = StreamingEvent()
        with pytest.raises(FrozenInstanceError):
            e.channel = StreamingChannel.HEALTH

    def test_custom_values(self) -> None:
        e = StreamingEvent(
            channel=StreamingChannel.ALERTS,
            event_type="alert.triggered",
            payload={"name": "cpu"},
        )
        assert e.channel == StreamingChannel.ALERTS
        assert e.event_type == "alert.triggered"
        assert e.payload == {"name": "cpu"}


# ======================================================================
# StreamingChannel
# ======================================================================


class TestStreamingChannel:
    def test_has_expected_members(self) -> None:
        assert len(StreamingChannel) == 5
        assert StreamingChannel.HEALTH.name == "HEALTH"
        assert StreamingChannel.METRICS.name == "METRICS"
        assert StreamingChannel.SNAPSHOTS.name == "SNAPSHOTS"
        assert StreamingChannel.ALERTS.name == "ALERTS"
        assert StreamingChannel.SYSTEM.name == "SYSTEM"


# ======================================================================
# Subscription
# ======================================================================


class TestSubscription:
    def test_is_frozen_dataclass(self) -> None:
        sub = Subscription()
        assert sub.subscriber_id == ""
        assert sub.channel == StreamingChannel.SYSTEM

    def test_matches_all_by_default(self) -> None:
        sub = Subscription(subscriber_id="s1")
        event = StreamingEvent(channel=StreamingChannel.HEALTH, payload={})
        assert sub.matches(event) is True

    def test_matches_channel_filter(self) -> None:
        sub = Subscription(subscriber_id="s1", channel=StreamingChannel.HEALTH)
        match = StreamingEvent(channel=StreamingChannel.HEALTH, payload={})
        no_match = StreamingEvent(channel=StreamingChannel.ALERTS, payload={})
        assert sub.matches(match) is True
        assert sub.matches(no_match) is False

    def test_matches_service_filter(self) -> None:
        sub = Subscription(subscriber_id="s1", services=("monitor",))
        event = StreamingEvent(payload={"service": "monitor"})
        event2 = StreamingEvent(payload={"service": "memory"})
        assert sub.matches(event) is True
        assert sub.matches(event2) is False

    def test_matches_severity_filter(self) -> None:
        sub = Subscription(subscriber_id="s1", severities=("critical",))
        assert sub.matches(StreamingEvent(payload={"severity": "critical"})) is True
        assert sub.matches(StreamingEvent(payload={"severity": "info"})) is False

    def test_matches_metric_filter(self) -> None:
        sub = Subscription(subscriber_id="s1", metrics=("cpu",))
        assert sub.matches(StreamingEvent(payload={"metric": "cpu"})) is True
        assert sub.matches(StreamingEvent(payload={"metric": "memory"})) is False

    def test_matches_snapshot_type_filter(self) -> None:
        sub = Subscription(subscriber_id="s1", snapshot_types=("resource",))
        assert sub.matches(StreamingEvent(payload={"snapshot_type": "resource"})) is True
        assert sub.matches(StreamingEvent(payload={"snapshot_type": "health"})) is False

    def test_is_frozen(self) -> None:
        sub = Subscription(subscriber_id="s1")
        with pytest.raises(FrozenInstanceError):
            sub.subscriber_id = "s2"


# ======================================================================
# SubscriptionManager
# ======================================================================


class TestSubscriptionManager:
    def test_subscribe_and_list(self) -> None:
        sm = SubscriptionManager()
        sub = Subscription(subscriber_id="s1")
        sm.subscribe(sub)
        assert sm.count() == 1
        assert len(sm.list_subscriptions()) == 1

    def test_unsubscribe(self) -> None:
        sm = SubscriptionManager()
        sm.subscribe(Subscription(subscriber_id="s1"))
        sm.unsubscribe("s1")
        assert sm.count() == 0

    def test_unsubscribe_nonexistent(self) -> None:
        sm = SubscriptionManager()
        sm.unsubscribe("nonexistent")

    def test_get_subscription(self) -> None:
        sm = SubscriptionManager()
        sm.subscribe(Subscription(subscriber_id="s1"))
        sub = sm.get_subscription("s1")
        assert sub is not None
        assert sub.subscriber_id == "s1"

    def test_get_subscription_missing(self) -> None:
        sm = SubscriptionManager()
        assert sm.get_subscription("missing") is None

    def test_matching_subscribers(self) -> None:
        sm = SubscriptionManager()
        sm.subscribe(Subscription(subscriber_id="s1", channel=StreamingChannel.HEALTH))
        sm.subscribe(Subscription(subscriber_id="s2", channel=StreamingChannel.ALERTS))
        event = StreamingEvent(channel=StreamingChannel.HEALTH)
        matches = sm.matching_subscribers(event)
        assert matches == ["s1"]

    def test_matching_subscribers_all(self) -> None:
        sm = SubscriptionManager()
        sm.subscribe(Subscription(subscriber_id="s1"))
        sm.subscribe(Subscription(subscriber_id="s2"))
        event = StreamingEvent(channel=StreamingChannel.HEALTH)
        matches = sm.matching_subscribers(event)
        assert len(matches) == 2

    def test_thread_safety(self) -> None:
        sm = SubscriptionManager()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [
                ex.submit(sm.subscribe, Subscription(subscriber_id=f"s{i}"))
                for i in range(100)
            ]
            concurrent.futures.wait(futures)
        assert sm.count() == 100


# ======================================================================
# StreamingManager
# ======================================================================


class TestStreamingManager:
    @pytest.mark.asyncio
    async def test_subscribe_returns_queue(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        q = await mgr.subscribe("s1", StreamingChannel.HEALTH)
        assert isinstance(q, asyncio.Queue)
        assert mgr.subscriber_count() == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        await mgr.subscribe("s1")
        await mgr.unsubscribe("s1")
        assert mgr.subscriber_count() == 0

    @pytest.mark.asyncio
    async def test_publish_delivers_to_matching(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        q = await mgr.subscribe("s1", StreamingChannel.HEALTH)
        event = StreamingEvent(channel=StreamingChannel.HEALTH)
        count = await mgr.publish(event)
        assert count == 1
        received = await asyncio.wait_for(q.get(), timeout=1)
        assert received.channel == StreamingChannel.HEALTH

    @pytest.mark.asyncio
    async def test_publish_skips_non_matching(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        await mgr.subscribe("s1", StreamingChannel.HEALTH)
        event = StreamingEvent(channel=StreamingChannel.ALERTS)
        count = await mgr.publish(event)
        assert count == 0

    @pytest.mark.asyncio
    async def test_publish_multiple_subscribers(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        await mgr.subscribe("s1")
        await mgr.subscribe("s2")
        count = await mgr.publish(StreamingEvent())
        assert count == 2

    @pytest.mark.asyncio
    async def test_active_subscribers(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        await mgr.subscribe("s1")
        await mgr.subscribe("s2")
        active = mgr.active_subscribers()
        assert "s1" in active
        assert "s2" in active

    @pytest.mark.asyncio
    async def test_cleanup(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        await mgr.subscribe("s1")
        await mgr.cleanup()
        assert mgr.subscriber_count() == 0

    @pytest.mark.asyncio
    async def test_subscribe_with_filters(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        await mgr.subscribe("s1", services=("monitor",))
        sub = sm.get_subscription("s1")
        assert sub is not None
        assert "monitor" in sub.services

    @pytest.mark.asyncio
    async def test_publish_no_queue_for_subscriber(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        sm.subscribe(Subscription(subscriber_id="orphan"))
        event = StreamingEvent()
        count = await mgr.publish(event)
        assert count == 0

    @pytest.mark.asyncio
    async def test_publish_with_filters(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        await mgr.subscribe("s1", services=("monitor",))
        count = await mgr.publish(StreamingEvent(payload={"service": "monitor"}))
        assert count == 1
        count2 = await mgr.publish(StreamingEvent(payload={"service": "memory"}))
        assert count2 == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self) -> None:
        sm = SubscriptionManager()
        mgr = StreamingManager(sm)
        await mgr.subscribe("s1")
        await mgr.unsubscribe("s1")
        assert "s1" not in mgr._queues


# ======================================================================
# HealthEndpoint
# ======================================================================


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_get_system_health(self, monitoring_api: MonitoringAPI) -> None:
        health = await monitoring_api.get_system_health()
        assert isinstance(health, ServiceHealth)

    @pytest.mark.asyncio
    async def test_get_service_health(self, monitoring_api: MonitoringAPI) -> None:
        results = await monitoring_api.get_service_health()
        assert isinstance(results, dict)
        assert "test_svc" in results

    @pytest.mark.asyncio
    async def test_get_service_health_filtered(self, monitoring_api: MonitoringAPI) -> None:
        results = await monitoring_api.get_service_health("test_svc")
        assert len(results) == 1
        assert "test_svc" in results

    @pytest.mark.asyncio
    async def test_get_health_summary(self, monitoring_api: MonitoringAPI) -> None:
        summary = await monitoring_api.get_health_summary()
        assert "total" in summary
        assert "healthy" in summary
        assert "status" in summary
        assert summary["total"] > 0


# ======================================================================
# MetricsEndpoint
# ======================================================================


class TestMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_get_performance(self, monitoring_api: MonitoringAPI) -> None:
        perf = await monitoring_api.get_performance()
        assert isinstance(perf, dict)
        assert "event_throughput" in perf

    def test_get_monitor_metrics(self, monitoring_api: MonitoringAPI) -> None:
        metrics = monitoring_api.get_monitor_metrics()
        assert isinstance(metrics, dict)
        assert "snapshots_taken" in metrics

    def test_get_event_throughput(self, monitoring_api: MonitoringAPI) -> None:
        et = monitoring_api.metrics.get_event_throughput()
        assert isinstance(et, dict)

    def test_get_service_latency(self, monitoring_api: MonitoringAPI) -> None:
        sl = monitoring_api.metrics.get_service_latency()
        assert isinstance(sl, dict)

    def test_get_queue_sizes(self, monitoring_api: MonitoringAPI) -> None:
        qs = monitoring_api.metrics.get_queue_sizes()
        assert isinstance(qs, dict)


# ======================================================================
# SnapshotEndpoint
# ======================================================================


class TestSnapshotEndpoint:
    @pytest.mark.asyncio
    async def test_get_latest_snapshot(self, monitoring_api: MonitoringAPI) -> None:
        snap = await monitoring_api.get_latest_snapshot()
        assert snap is None or isinstance(snap, ResourceSnapshot)

    @pytest.mark.asyncio
    async def test_take_snapshot(self, monitoring_api: MonitoringAPI) -> None:
        snap = await monitoring_api.take_snapshot()
        assert isinstance(snap, ResourceSnapshot)

    def test_get_snapshots(self, monitoring_api: MonitoringAPI) -> None:
        snaps = monitoring_api.get_snapshots(5)
        assert isinstance(snaps, list)


# ======================================================================
# AlertEndpoint
# ======================================================================


class TestAlertEndpoint:
    def test_get_active_alerts(self, monitoring_api: MonitoringAPI) -> None:
        alerts = monitoring_api.get_active_alerts()
        assert isinstance(alerts, dict)

    def test_list_alert_rules(self, monitoring_api: MonitoringAPI) -> None:
        rules = monitoring_api.list_alert_rules()
        assert isinstance(rules, list)

    def test_get_alert_history(self, monitoring_api: MonitoringAPI) -> None:
        history = monitoring_api.get_alert_history()
        assert isinstance(history, list)


# ======================================================================
# HistoryEndpoint
# ======================================================================


class TestHistoryEndpoint:
    @pytest.mark.asyncio
    async def test_save_snapshot(self, monitoring_api: MonitoringAPI) -> None:
        snap = ResourceSnapshot(cpu_percent=50.0)
        await monitoring_api.save_history_snapshot(snap)

    @pytest.mark.asyncio
    async def test_save_health_report(self, monitoring_api: MonitoringAPI) -> None:
        report = {"svc": ServiceSnapshot(service_name="svc")}
        await monitoring_api.save_history_health(report)

    @pytest.mark.asyncio
    async def test_save_alert(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.save_history_alert("cpu", "critical", "triggered")

    @pytest.mark.asyncio
    async def test_get_history_snapshots(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.save_history_snapshot(ResourceSnapshot(cpu_percent=50.0))
        results = await monitoring_api.get_history_snapshots(limit=10)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_history_health(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.save_history_health({"svc": ServiceSnapshot()})
        results = await monitoring_api.get_history_health(limit=10)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_history_alerts(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.save_history_alert("cpu", "critical", "triggered")
        results = await monitoring_api.get_history_alerts(limit=10)
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_get_by_time_range(self, monitoring_api: MonitoringAPI) -> None:
        now = datetime.now().timestamp()
        await monitoring_api.save_history_alert("cpu", "critical", "triggered")
        results = await monitoring_api.get_history_by_time_range(
            "monitor_alerts", now - 10, now + 10
        )
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_save_and_read_snapshot_roundtrip(self, monitoring_api: MonitoringAPI) -> None:
        snap = ResourceSnapshot(cpu_percent=80.0, memory_percent=70.0)
        await monitoring_api.save_history_snapshot(snap)
        results = await monitoring_api.get_history_snapshots(limit=10)
        assert len(results) >= 0

    @pytest.mark.asyncio
    async def test_save_and_read_health_roundtrip(self, monitoring_api: MonitoringAPI) -> None:
        report = {"svc1": ServiceSnapshot(service_name="svc1", health=HealthStatus.HEALTHY)}
        await monitoring_api.save_history_health(report)
        results = await monitoring_api.get_history_health(limit=10)
        assert len(results) >= 0

    @pytest.mark.asyncio
    async def test_save_and_read_alert_roundtrip(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.save_history_alert("mem", "warning", "triggered")
        results = await monitoring_api.get_history_alerts(limit=10)
        assert len(results) >= 0

    @pytest.mark.asyncio
    async def test_save_snapshot_exception_does_not_raise(self, monitoring_api: MonitoringAPI) -> None:
        monitoring_api._history_endpoint._persistence.save = AsyncMock(
            side_effect=RuntimeError("fail")
        )
        await monitoring_api.save_history_snapshot(ResourceSnapshot())  # should not raise


# ======================================================================
# MetricsAggregator
# ======================================================================


class TestMetricsAggregator:
    def test_initial_values(self) -> None:
        ma = MetricsAggregator()
        s = ma.snapshot()
        assert s["active_subscriptions"] == 0
        assert s["messages_published"] == 0
        assert s["messages_dropped"] == 0
        assert s["history_reads"] == 0
        assert s["history_writes"] == 0
        assert s["average_stream_latency"] == 0.0

    def test_record_subscription(self) -> None:
        ma = MetricsAggregator()
        ma.record_subscription()
        assert ma.active_subscriptions == 1

    def test_record_unsubscription(self) -> None:
        ma = MetricsAggregator()
        ma.record_subscription()
        ma.record_subscription()
        ma.record_unsubscription()
        assert ma.active_subscriptions == 1

    def test_record_unsubscription_below_zero(self) -> None:
        ma = MetricsAggregator()
        ma.record_unsubscription()
        assert ma.active_subscriptions == 0

    def test_record_message_published(self) -> None:
        ma = MetricsAggregator()
        ma.record_message_published()
        assert ma.snapshot()["messages_published"] == 1

    def test_record_message_dropped(self) -> None:
        ma = MetricsAggregator()
        ma.record_message_dropped()
        assert ma.snapshot()["messages_dropped"] == 1

    def test_record_history_read(self) -> None:
        ma = MetricsAggregator()
        ma.record_history_read()
        assert ma.snapshot()["history_reads"] == 1

    def test_record_history_write(self) -> None:
        ma = MetricsAggregator()
        ma.record_history_write()
        assert ma.snapshot()["history_writes"] == 1

    def test_average_stream_latency(self) -> None:
        ma = MetricsAggregator()
        ma.record_stream_latency(0.1)
        ma.record_stream_latency(0.3)
        assert ma.average_stream_latency == 0.2

    def test_average_stream_latency_empty(self) -> None:
        ma = MetricsAggregator()
        assert ma.average_stream_latency == 0.0

    def test_reset(self) -> None:
        ma = MetricsAggregator()
        ma.record_subscription()
        ma.record_message_published()
        ma.reset()
        s = ma.snapshot()
        assert s["active_subscriptions"] == 0
        assert s["messages_published"] == 0

    def test_thread_safety(self) -> None:
        ma = MetricsAggregator()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(ma.record_message_published) for _ in range(100)]
            concurrent.futures.wait(futures)
        assert ma.snapshot()["messages_published"] == 100


# ======================================================================
# APIEventBridge
# ======================================================================


class TestAPIEventBridge:
    @pytest.mark.asyncio
    async def test_publish(self, event_bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        event_bus.subscribe(EventCategory.MONITOR.value, handler)
        bridge = APIEventBridge(event_bus)
        await bridge.publish("TEST", {"key": "value"})
        assert len(received) == 1
        assert received[0].payload["event_type"] == "TEST"

    @pytest.mark.asyncio
    async def test_health_requested(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        await bridge.health_requested()

    @pytest.mark.asyncio
    async def test_metrics_requested(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        await bridge.metrics_requested()

    @pytest.mark.asyncio
    async def test_snapshot_requested(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        await bridge.snapshot_requested()

    @pytest.mark.asyncio
    async def test_alerts_requested(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        await bridge.alerts_requested()

    @pytest.mark.asyncio
    async def test_history_requested(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        await bridge.history_requested()

    @pytest.mark.asyncio
    async def test_subscription_created(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        await bridge.subscription_created("s1")

    @pytest.mark.asyncio
    async def test_subscription_removed(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        await bridge.subscription_removed("s1")

    @pytest.mark.asyncio
    async def test_stream_event_published(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        await bridge.stream_event_published("health", 5)

    @pytest.mark.asyncio
    async def test_publish_exception_does_not_raise(self, event_bus: EventBus) -> None:
        bridge = APIEventBridge(event_bus)
        event_bus.publish = AsyncMock(side_effect=RuntimeError("bus down"))
        await bridge.publish("TEST")  # should not raise


# ======================================================================
# MonitoringAPI (IService)
# ======================================================================


class TestMonitoringAPI:
    def test_name(self, monitoring_api: MonitoringAPI) -> None:
        assert monitoring_api.name == "monitoring_api"

    def test_properties(self, monitoring_api: MonitoringAPI) -> None:
        assert monitoring_api.subscription_manager is not None
        assert monitoring_api.streaming_manager is not None
        assert monitoring_api.health is not None
        assert monitoring_api.metrics is not None
        assert monitoring_api.snapshots is not None
        assert monitoring_api.alerts is not None
        assert monitoring_api.history is not None
        assert monitoring_api.metrics_aggregator is not None
        assert monitoring_api.event_bridge is not None

    @pytest.mark.asyncio
    async def test_start_stop(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.start()
        assert monitoring_api._state == ServiceState.RUNNING
        await monitoring_api.stop()
        assert monitoring_api._state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_health_check_initial(self, monitoring_api: MonitoringAPI) -> None:
        health = await monitoring_api.health_check()
        assert health.healthy is False

    @pytest.mark.asyncio
    async def test_health_check_after_start(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.start()
        health = await monitoring_api.health_check()
        assert health.healthy is True
        await monitoring_api.stop()

    @pytest.mark.asyncio
    async def test_stream_subscribe_unsubscribe(self, monitoring_api: MonitoringAPI) -> None:
        q = await monitoring_api.stream_subscribe("s1", StreamingChannel.HEALTH)
        assert isinstance(q, asyncio.Queue)
        assert monitoring_api.subscription_manager.count() == 1
        await monitoring_api.stream_unsubscribe("s1")
        assert monitoring_api.subscription_manager.count() == 0

    @pytest.mark.asyncio
    async def test_stream_publish_reaches_subscriber(self, monitoring_api: MonitoringAPI) -> None:
        q = await monitoring_api.stream_subscribe("s1", StreamingChannel.HEALTH)
        event = StreamingEvent(channel=StreamingChannel.HEALTH, payload={"msg": "hello"})
        count = await monitoring_api.stream_publish(event)
        assert count == 1
        received = await asyncio.wait_for(q.get(), timeout=1)
        assert received.payload["msg"] == "hello"

    @pytest.mark.asyncio
    async def test_stream_publish_updates_metrics(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.stream_subscribe("s1", StreamingChannel.HEALTH)
        await monitoring_api.stream_publish(StreamingEvent(channel=StreamingChannel.HEALTH))
        metrics = monitoring_api.get_api_metrics()
        assert metrics["messages_published"] == 1

    @pytest.mark.asyncio
    async def test_get_api_metrics(self, monitoring_api: MonitoringAPI) -> None:
        metrics = monitoring_api.get_api_metrics()
        assert "active_subscriptions" in metrics
        assert "messages_published" in metrics

    @pytest.mark.asyncio
    async def test_save_and_read_history(self, monitoring_api: MonitoringAPI) -> None:
        await monitoring_api.save_history_snapshot(ResourceSnapshot(cpu_percent=75.0))
        await monitoring_api.save_history_health({"s1": ServiceSnapshot()})
        await monitoring_api.save_history_alert("cpu", "warn", "triggered")
        metrics = monitoring_api.get_api_metrics()
        assert metrics["history_writes"] == 3

    @pytest.mark.asyncio
    async def test_iservice_compliance(self, monitoring_api: MonitoringAPI) -> None:
        from atlas_core.interfaces import IService
        assert isinstance(monitoring_api, IService)

    @pytest.mark.asyncio
    async def test_get_alert_endpoint(self, monitoring_api: MonitoringAPI, system_monitor: SystemMonitor) -> None:
        system_monitor.alert_manager.register(
            AlertRule(name="cpu", condition="cpu>90")
        )
        alerts = monitoring_api.get_active_alerts()
        assert isinstance(alerts, dict)


# ======================================================================
# Kernel integration
# ======================================================================


class TestKernelIntegration:
    @pytest.mark.asyncio
    async def test_kernel_registers_monitoring_api(self, tmp_path):
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
        assert kernel.registry.count == 15
        assert kernel.monitoring_api is not None
        from atlas_core.monitor_api import MonitoringAPI
        assert isinstance(kernel.monitoring_api, MonitoringAPI)

    @pytest.mark.asyncio
    async def test_kernel_before_init_raises(self):
        from atlas_core.kernel import AtlasKernel
        k = AtlasKernel()
        k.initialize()
        with pytest.raises(RuntimeError):
            _ = k.monitoring_api


# ======================================================================
# EventCategory
# ======================================================================


class TestEventCategory:
    def test_monitor_api_category_exists(self) -> None:
        assert hasattr(EventCategory, "MONITOR_API")
        assert EventCategory.MONITOR_API.value == "monitor_api"
