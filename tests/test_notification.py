"""Tests for the Notification Service."""

import pytest

from atlas_core.events import EventBus
from atlas_core.interfaces import SubsystemResponse
from atlas_core.notification import (
    Notification,
    NotificationChannel,
    NotificationDispatcher,
    NotificationHistory,
    NotificationManager,
    NotificationMetrics,
    NotificationPriority,
    NotificationRule,
    NotificationService,
    NotificationStatus,
    NotificationSubscription,
    NotificationTemplate,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=200)


@pytest.fixture
def service(bus: EventBus) -> NotificationService:
    return NotificationService(bus)


@pytest.fixture
def dispatcher() -> NotificationDispatcher:
    return NotificationDispatcher()


@pytest.fixture
def manager() -> NotificationManager:
    return NotificationManager()


@pytest.fixture
def history() -> NotificationHistory:
    return NotificationHistory()


# ======================================================================
# Enums
# ======================================================================


class TestEnums:
    def test_notification_priority(self) -> None:
        assert NotificationPriority.LOW.value == 0
        assert NotificationPriority.NORMAL.value == 1
        assert NotificationPriority.HIGH.value == 2
        assert NotificationPriority.CRITICAL.value == 3

    def test_notification_channel(self) -> None:
        assert NotificationChannel.INTERNAL.value == "internal"
        assert NotificationChannel.EMAIL.value == "email"
        assert NotificationChannel.CONSOLE.value == "console"

    def test_notification_status(self) -> None:
        assert NotificationStatus.PENDING.name == "PENDING"
        assert NotificationStatus.DELIVERED.name == "DELIVERED"


# ======================================================================
# Notification
# ======================================================================


class TestNotification:
    def test_notification_creation(self) -> None:
        n = Notification(title="Test", message="Hello")
        assert n.title == "Test"
        assert n.message == "Hello"
        assert n.priority == NotificationPriority.NORMAL
        assert n.status == NotificationStatus.PENDING
        assert n.channel == NotificationChannel.INTERNAL

    def test_notification_defaults(self) -> None:
        n = Notification()
        assert n.title == ""
        assert n.tags == []


# ======================================================================
# NotificationDispatcher
# ======================================================================


class TestNotificationDispatcher:
    async def test_dispatch_internal(self, dispatcher: NotificationDispatcher) -> None:
        n = Notification(channel=NotificationChannel.INTERNAL)
        status = await dispatcher.dispatch(n)
        assert status == NotificationStatus.DELIVERED
        assert n.status == NotificationStatus.DELIVERED

    async def test_dispatch_log(self, dispatcher: NotificationDispatcher) -> None:
        n = Notification(channel=NotificationChannel.LOG)
        status = await dispatcher.dispatch(n)
        assert status == NotificationStatus.SENT

    async def test_dispatch_console(self, dispatcher: NotificationDispatcher) -> None:
        n = Notification(channel=NotificationChannel.CONSOLE)
        status = await dispatcher.dispatch(n)
        assert status == NotificationStatus.SENT

    async def test_dispatch_eventbus(self, dispatcher: NotificationDispatcher) -> None:
        n = Notification(channel=NotificationChannel.EVENTBUS)
        status = await dispatcher.dispatch(n)
        assert status == NotificationStatus.SENT

    async def test_dispatch_email_stub(self, dispatcher: NotificationDispatcher) -> None:
        n = Notification(channel=NotificationChannel.EMAIL)
        status = await dispatcher.dispatch(n)
        assert status == NotificationStatus.FAILED

    async def test_dispatch_push_stub(self, dispatcher: NotificationDispatcher) -> None:
        n = Notification(channel=NotificationChannel.PUSH)
        status = await dispatcher.dispatch(n)
        assert status == NotificationStatus.FAILED

    async def test_dispatch_webhook_stub(self, dispatcher: NotificationDispatcher) -> None:
        n = Notification(channel=NotificationChannel.WEBHOOK)
        status = await dispatcher.dispatch(n)
        assert status == NotificationStatus.FAILED


# ======================================================================
# NotificationManager
# ======================================================================


class TestNotificationManager:
    def test_default_rules_registered(self, manager: NotificationManager) -> None:
        assert manager.rule_count >= 8

    def test_add_rule(self, manager: NotificationManager) -> None:
        rule = NotificationRule(name="Custom Rule", event_source="test")
        manager.add_rule(rule)
        assert manager.rule_count >= 9
        assert manager.get_rule(rule.rule_id) is rule

    def test_get_missing_rule(self, manager: NotificationManager) -> None:
        assert manager.get_rule("missing") is None

    def test_remove_rule(self, manager: NotificationManager) -> None:
        rule = NotificationRule(name="Remove Me")
        manager.add_rule(rule)
        assert manager.remove_rule(rule.rule_id) is True
        assert manager.get_rule(rule.rule_id) is None

    def test_remove_missing_rule(self, manager: NotificationManager) -> None:
        assert manager.remove_rule("missing") is False

    def test_list_rules(self, manager: NotificationManager) -> None:
        all_rules = manager.list_rules()
        assert len(all_rules) >= 8
        enabled = manager.list_rules(enabled_only=True)
        assert len(enabled) <= len(all_rules)

    def test_add_subscription(self, manager: NotificationManager) -> None:
        sub = NotificationSubscription(user_id="user1")
        manager.add_subscription(sub)
        assert manager.subscription_count == 1
        assert manager.get_subscription(sub.subscription_id) is sub

    def test_remove_subscription(self, manager: NotificationManager) -> None:
        sub = NotificationSubscription(user_id="user1")
        manager.add_subscription(sub)
        assert manager.remove_subscription(sub.subscription_id) is True
        assert manager.remove_subscription("missing") is False

    def test_list_subscriptions(self, manager: NotificationManager) -> None:
        manager.add_subscription(NotificationSubscription(user_id="u1"))
        manager.add_subscription(NotificationSubscription(user_id="u2"))
        assert len(manager.list_subscriptions()) == 2

    def test_find_matching_rules(self, manager: NotificationManager) -> None:
        results = manager.find_matching_rules("mission_event_bridge", "mission_completed")
        assert len(results) >= 1
        assert results[0].name == "Mission Completed"

    def test_find_matching_rules_no_match(self, manager: NotificationManager) -> None:
        assert manager.find_matching_rules("unknown", "unknown") == []

    def test_clear(self, manager: NotificationManager) -> None:
        manager.clear()
        assert manager.rule_count == 0
        assert manager.subscription_count == 0


# ======================================================================
# NotificationHistory
# ======================================================================


class TestNotificationHistory:
    def test_record_and_query(self, history: NotificationHistory) -> None:
        n = Notification(title="Test")
        history.record(n)
        results = history.query()
        assert len(results) == 1

    def test_query_by_channel(self, history: NotificationHistory) -> None:
        history.record(Notification(channel=NotificationChannel.INTERNAL))
        history.record(Notification(channel=NotificationChannel.LOG))
        results = history.query(channel=NotificationChannel.INTERNAL)
        assert len(results) == 1

    def test_query_by_status(self, history: NotificationHistory) -> None:
        n = Notification(status=NotificationStatus.DELIVERED)
        history.record(n)
        results = history.query(status=NotificationStatus.DELIVERED)
        assert len(results) == 1

    def test_query_by_priority(self, history: NotificationHistory) -> None:
        history.record(Notification(priority=NotificationPriority.HIGH))
        results = history.query(priority=NotificationPriority.HIGH)
        assert len(results) == 1

    def test_ring_buffer(self) -> None:
        h = NotificationHistory(max_size=2)
        h.record(Notification(title="A"))
        h.record(Notification(title="B"))
        h.record(Notification(title="C"))
        assert h.total_count == 2

    def test_clear(self, history: NotificationHistory) -> None:
        history.record(Notification())
        history.clear()
        assert history.total_count == 0


# ======================================================================
# NotificationTemplate
# ======================================================================


class TestNotificationTemplate:
    def test_render(self) -> None:
        result = NotificationTemplate.render("Hello {name}", name="World")
        assert result == "Hello World"

    def test_render_missing_key(self) -> None:
        result = NotificationTemplate.render("Hello {name}")
        assert result == "Hello {name}"


# ======================================================================
# NotificationService — IService Lifecycle
# ======================================================================


class TestNotificationServiceLifecycle:
    def test_name(self, service: NotificationService) -> None:
        assert service.name == "notification_service"

    async def test_initialize(self, service: NotificationService) -> None:
        await service.initialize()
        assert service._running is False

    async def test_start_stop(self, service: NotificationService) -> None:
        await service.start()
        assert service._running is True
        await service.stop()
        assert service._running is False

    async def test_health_check(self, service: NotificationService) -> None:
        await service.start()
        health = await service.health_check()
        assert health.healthy is True
        assert "total_sent" in health.metadata
        await service.stop()

    async def test_set_context(self, service: NotificationService) -> None:
        from atlas_core.context import AtlasContext
        ctx = AtlasContext()
        service.set_context(ctx)
        assert service._context is ctx


# ======================================================================
# NotificationService — Send
# ======================================================================


class TestNotificationServiceSend:
    async def test_send_notification(self, service: NotificationService) -> None:
        n = Notification(title="Test", message="Hello")
        status = await service.send(n)
        assert status in (NotificationStatus.DELIVERED, NotificationStatus.SENT)
        assert service.metrics.total_sent == 1

    async def test_send_convenience(self, service: NotificationService) -> None:
        n = await service.send_notification(title="Test", message="Hello")
        assert n.title == "Test"
        assert n.message == "Hello"
        assert service.metrics.total_sent == 1

    async def test_send_with_channel(self, service: NotificationService) -> None:
        n = Notification(title="Log Test", channel=NotificationChannel.LOG)
        status = await service.send(n)
        assert status == NotificationStatus.SENT

    async def test_send_tracks_metrics(self, service: NotificationService) -> None:
        await service.send(Notification(channel=NotificationChannel.INTERNAL))
        await service.send(Notification(channel=NotificationChannel.INTERNAL))
        assert service.metrics.total_sent == 2
        assert service.metrics.total_delivered == 2


# ======================================================================
# NotificationService — Event-driven notifications
# ======================================================================


class TestNotificationServiceEvents:
    async def test_subscribes_on_start(self, bus: EventBus) -> None:
        service = NotificationService(bus)
        await service.start()
        assert len(service._subscription_handles) >= 7
        await service.stop()
        assert len(service._subscription_handles) == 0

    async def test_handles_matching_event(self, bus: EventBus) -> None:
        service = NotificationService(bus)
        await service.start()

        from atlas_core.interfaces.events import Event, EventCategory, EventPriority
        await bus.publish(Event(
            source="mission_event_bridge",
            category=EventCategory.MISSION,
            payload={"action": "mission_completed", "title": "Test Mission"},
        ))

        # Give the handler time to process
        import asyncio
        await asyncio.sleep(0.01)

        assert service.metrics.total_sent >= 1
        await service.stop()

    async def test_ignores_non_matching_event(self, bus: EventBus) -> None:
        service = NotificationService(bus)
        await service.start()

        from atlas_core.interfaces.events import Event, EventCategory, EventPriority
        await bus.publish(Event(
            source="unknown_source",
            category=EventCategory.SYSTEM,
            payload={"action": "unknown_action"},
        ))

        import asyncio
        await asyncio.sleep(0.01)

        assert service.metrics.total_sent == 0
        await service.stop()


# ======================================================================
# SubsystemResponse
# ======================================================================


class TestSubsystemResponse:
    def test_defaults(self) -> None:
        r = SubsystemResponse()
        assert r.success is True
        assert r.status == "completed"
        assert r.errors == []
        assert r.warnings == []
        assert r.duration == 0.0
        assert r.subsystem == ""

    def test_error_response(self) -> None:
        r = SubsystemResponse(success=False, errors=["Something failed"])
        assert r.success is False
        assert len(r.errors) == 1

    def test_with_payload(self) -> None:
        r = SubsystemResponse(payload={"key": "value"})
        assert r.payload["key"] == "value"


# ======================================================================
# NotificationService — Metrics
# ======================================================================


class TestNotificationMetrics:
    def test_defaults(self) -> None:
        m = NotificationMetrics()
        assert m.total_sent == 0
        assert m.errors == 0


# ======================================================================
# Kernel integration
# ======================================================================


class TestKernelIntegration:
    async def test_kernel_creates_notification_service(self) -> None:
        from atlas_core.kernel import AtlasKernel
        kernel = AtlasKernel()
        kernel.initialize()
        kernel.boot()
        ns = kernel.notification_service
        assert ns.name == "notification_service"
        assert ns is kernel._notification_service
