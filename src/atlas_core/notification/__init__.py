"""Notification Service — delivers notifications across multiple channels.

Subscribes to Event Bus events.
Other modules do NOT call it directly.
No external integrations yet — only interfaces and stubs.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from atlas_core.context import AtlasContext
from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventHandler, EventPriority


# ======================================================================
# Enums
# ======================================================================


class NotificationPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class NotificationChannel(Enum):
    INTERNAL = "internal"
    LOG = "log"
    CONSOLE = "console"
    EVENTBUS = "eventbus"
    EMAIL = "email"
    PUSH = "push"
    WEBHOOK = "webhook"


class NotificationStatus(Enum):
    PENDING = auto()
    SENT = auto()
    DELIVERED = auto()
    FAILED = auto()
    READ = auto()


# ======================================================================
# Core data classes
# ======================================================================


@dataclass
class Notification:
    """A single notification message."""

    notification_id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    message: str = ""
    priority: NotificationPriority = NotificationPriority.NORMAL
    channel: NotificationChannel = NotificationChannel.INTERNAL
    status: NotificationStatus = NotificationStatus.PENDING
    source: str = ""
    category: str = ""
    target_user: str = ""
    related_entity_id: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    delivered_at: datetime | None = None


@dataclass
class NotificationRule:
    """A rule that triggers notifications when certain events occur."""

    rule_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    event_source: str = ""
    event_action: str = ""
    channel: NotificationChannel = NotificationChannel.INTERNAL
    priority: NotificationPriority = NotificationPriority.NORMAL
    template: str = ""
    enabled: bool = True


@dataclass
class NotificationSubscription:
    """A subscription to receive notifications matching certain criteria."""

    subscription_id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    channels: list[NotificationChannel] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    min_priority: NotificationPriority = NotificationPriority.NORMAL
    enabled: bool = True


@dataclass
class NotificationMetrics:
    """Usage and performance metrics for the Notification Service."""

    total_sent: int = 0
    total_delivered: int = 0
    total_failed: int = 0
    total_rules: int = 0
    total_subscriptions: int = 0
    errors: int = 0


# ======================================================================
# Notification Dispatchers
# ======================================================================


class NotificationDispatcher:
    """Dispatches notifications to the appropriate channel handler."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    async def dispatch(self, notification: Notification) -> NotificationStatus:
        """Dispatch a notification to its configured channel.

        Returns the delivery status.
        """
        channel = notification.channel
        self._logger.debug(
            "Dispatching notification %s via %s", notification.notification_id, channel.value
        )

        if channel == NotificationChannel.INTERNAL:
            return await self._dispatch_internal(notification)
        elif channel == NotificationChannel.LOG:
            return await self._dispatch_log(notification)
        elif channel == NotificationChannel.CONSOLE:
            return await self._dispatch_console(notification)
        elif channel == NotificationChannel.EVENTBUS:
            return await self._dispatch_eventbus(notification)
        elif channel == NotificationChannel.EMAIL:
            return self._stub("email")
        elif channel == NotificationChannel.PUSH:
            return self._stub("push")
        elif channel == NotificationChannel.WEBHOOK:
            return self._stub("webhook")
        else:
            self._logger.warning("Unknown notification channel: %s", channel)
            return NotificationStatus.FAILED

    async def _dispatch_internal(self, notification: Notification) -> NotificationStatus:
        """Internal in-memory delivery."""
        notification.status = NotificationStatus.DELIVERED
        notification.delivered_at = datetime.now()
        return NotificationStatus.DELIVERED

    async def _dispatch_log(self, notification: Notification) -> NotificationStatus:
        """Log the notification."""
        self._logger.info(
            "[%s] %s: %s", notification.priority.name, notification.title, notification.message
        )
        notification.status = NotificationStatus.SENT
        return NotificationStatus.SENT

    async def _dispatch_console(self, notification: Notification) -> NotificationStatus:
        """Output to console (stdout)."""
        print(f"[{notification.priority.name}] {notification.title}: {notification.message}")
        notification.status = NotificationStatus.SENT
        return NotificationStatus.SENT

    async def _dispatch_eventbus(self, notification: Notification) -> NotificationStatus:
        """Deliver via Event Bus. Actual publishing is handled by the caller."""
        notification.status = NotificationStatus.SENT
        return NotificationStatus.SENT

    def _stub(self, channel: str) -> NotificationStatus:
        self._logger.info("Stub dispatch for channel: %s", channel)
        return NotificationStatus.FAILED


# ======================================================================
# Notification Manager
# ======================================================================


class NotificationManager:
    """Manages notification rules, subscriptions, and lifecycle."""

    def __init__(self) -> None:
        self._rules: dict[str, NotificationRule] = {}
        self._subscriptions: dict[str, NotificationSubscription] = {}
        self._logger = logging.getLogger(__name__)
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        rules = [
            NotificationRule(
                name="Mission Completed",
                event_source="mission_event_bridge",
                event_action="mission_completed",
                channel=NotificationChannel.INTERNAL,
                priority=NotificationPriority.NORMAL,
                template="Mission '{title}' completed successfully",
            ),
            NotificationRule(
                name="Mission Failed",
                event_source="mission_event_bridge",
                event_action="mission_failed",
                channel=NotificationChannel.INTERNAL,
                priority=NotificationPriority.HIGH,
                template="Mission '{title}' failed: {error}",
            ),
            NotificationRule(
                name="Execution Failed",
                event_source="execution_engine",
                event_action="command_failed",
                channel=NotificationChannel.INTERNAL,
                priority=NotificationPriority.HIGH,
                template="Execution command failed: {error}",
            ),
            NotificationRule(
                name="Browser Disconnected",
                event_source="browser_companion",
                event_action="browser_disconnected",
                channel=NotificationChannel.INTERNAL,
                priority=NotificationPriority.HIGH,
                template="Browser disconnected",
            ),
            NotificationRule(
                name="Knowledge Imported",
                event_source="knowledge_engine",
                event_action="records_imported",
                channel=NotificationChannel.INTERNAL,
                priority=NotificationPriority.LOW,
                template="Imported {count} knowledge records",
            ),
            NotificationRule(
                name="Memory Promoted",
                event_source="memory_manager",
                event_action="memory_promoted",
                channel=NotificationChannel.INTERNAL,
                priority=NotificationPriority.LOW,
                template="Memory promoted to layer {layer}",
            ),
            NotificationRule(
                name="Opportunity Discovered",
                event_source="opportunity_discovery",
                event_action="discovery_completed",
                channel=NotificationChannel.INTERNAL,
                priority=NotificationPriority.NORMAL,
                template="Discovered {count} new opportunities",
            ),
            NotificationRule(
                name="Intelligence Provider Unhealthy",
                event_source="intelligence_router",
                event_action="provider_unhealthy",
                channel=NotificationChannel.INTERNAL,
                priority=NotificationPriority.CRITICAL,
                template="AI provider {provider} is unhealthy",
            ),
        ]
        for rule in rules:
            self.add_rule(rule)

    def add_rule(self, rule: NotificationRule) -> None:
        self._rules[rule.rule_id] = rule
        self._logger.debug("Added notification rule: %s", rule.name)

    def get_rule(self, rule_id: str) -> NotificationRule | None:
        return self._rules.get(rule_id)

    def list_rules(self, enabled_only: bool = False) -> list[NotificationRule]:
        if enabled_only:
            return [r for r in self._rules.values() if r.enabled]
        return list(self._rules.values())

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False

    def add_subscription(self, subscription: NotificationSubscription) -> None:
        self._subscriptions[subscription.subscription_id] = subscription
        self._logger.debug("Added notification subscription for user: %s", subscription.user_id)

    def get_subscription(self, subscription_id: str) -> NotificationSubscription | None:
        return self._subscriptions.get(subscription_id)

    def list_subscriptions(self) -> list[NotificationSubscription]:
        return list(self._subscriptions.values())

    def remove_subscription(self, subscription_id: str) -> bool:
        if subscription_id in self._subscriptions:
            del self._subscriptions[subscription_id]
            return True
        return False

    def find_matching_rules(self, source: str, action: str) -> list[NotificationRule]:
        matching: list[NotificationRule] = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if rule.event_source == source and rule.event_action == action:
                matching.append(rule)
        return matching

    def clear(self) -> None:
        self._rules.clear()
        self._subscriptions.clear()

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)


# ======================================================================
# NotificationHistory
# ======================================================================


class NotificationHistory:
    """Ring buffer of sent notifications."""

    def __init__(self, max_size: int = 200) -> None:
        self._notifications: deque[Notification] = deque(maxlen=max_size)

    def record(self, notification: Notification) -> None:
        self._notifications.append(notification)

    def query(
        self,
        channel: NotificationChannel | None = None,
        status: NotificationStatus | None = None,
        priority: NotificationPriority | None = None,
        limit: int = 20,
    ) -> list[Notification]:
        results: list[Notification] = []
        for n in reversed(self._notifications):
            if channel is not None and n.channel != channel:
                continue
            if status is not None and n.status != status:
                continue
            if priority is not None and n.priority != priority:
                continue
            results.append(n)
            if len(results) >= limit:
                break
        return results

    @property
    def total_count(self) -> int:
        return len(self._notifications)

    def clear(self) -> None:
        self._notifications.clear()


# ======================================================================
# NotificationTemplate
# ======================================================================


class NotificationTemplate:
    """Simple string template for notification messages."""

    @staticmethod
    def render(template: str, **kwargs: Any) -> str:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template


# ======================================================================
# NotificationService — IService
# ======================================================================


class NotificationService(IService):
    """Central notification service for Atlas.

    Subscribes to Event Bus events.
    Other modules do NOT call it directly.
    No external integrations yet — only interfaces and stubs.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        self._dispatcher = NotificationDispatcher()
        self._manager = NotificationManager()
        self._history = NotificationHistory()
        self._metrics = NotificationMetrics()
        self._template_engine = NotificationTemplate()

        self._running = False
        self._context: AtlasContext | None = None
        self._subscription_handles: list[Any] = []

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "notification_service"

    async def initialize(self) -> None:
        await super().initialize()
        self._logger.info("Notification Service initializing")

    async def start(self) -> None:
        await super().start()
        self._running = True
        self._subscribe_to_events()
        self._logger.info("Notification Service started")

    async def stop(self) -> None:
        await super().stop()
        self._running = False
        self._unsubscribe_from_events()
        self._logger.info("Notification Service stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "total_sent": self._metrics.total_sent,
                "total_delivered": self._metrics.total_delivered,
                "total_failed": self._metrics.total_failed,
                "total_rules": self._metrics.total_rules,
                "history_count": self._history.total_count,
            },
        )

    # ------------------------------------------------------------------
    # Context integration
    # ------------------------------------------------------------------

    def set_context(self, context: AtlasContext) -> None:
        self._context = context

    # ------------------------------------------------------------------
    # Event subscription
    # ------------------------------------------------------------------

    def _subscribe_to_events(self) -> None:
        """Subscribe to Event Bus events that trigger notifications."""
        # Subscribe to all relevant event categories
        for category in (
            EventCategory.MISSION,
            EventCategory.EXECUTION,
            EventCategory.BROWSER,
            EventCategory.KNOWLEDGE,
            EventCategory.MEMORY,
            EventCategory.OPPORTUNITY,
            EventCategory.INTELLIGENCE,
        ):
            handle = self._event_bus.subscribe(category.value, self._handle_event)
            self._subscription_handles.append(handle)

    def _unsubscribe_from_events(self) -> None:
        for handle in self._subscription_handles:
            self._event_bus.unsubscribe(handle)
        self._subscription_handles.clear()

    async def _handle_event(self, event: Event) -> None:
        """Handle an incoming Event Bus event and generate notifications."""
        if not self._running:
            return

        source = event.source
        action = event.payload.get("action", "")

        matching_rules = self._manager.find_matching_rules(source, action)
        if not matching_rules:
            return

        for rule in matching_rules:
            await self._generate_from_rule(rule, event)

    async def _generate_from_rule(self, rule: NotificationRule, event: Event) -> None:
        """Generate a notification from a matching rule and event."""
        try:
            template_data: dict[str, Any] = {}
            template_data.update(event.payload)
            template_data["title"] = event.payload.get("title", "Notification")

            message = self._template_engine.render(rule.template, **template_data)

            notification = Notification(
                title=rule.name,
                message=message,
                priority=rule.priority,
                channel=rule.channel,
                source=event.source,
                category=event.category.value,
                related_entity_id=event.payload.get("mission_id", ""),
                metadata={"rule_id": rule.rule_id, "event_id": str(event.event_id)},
            )

            await self.send(notification)
        except Exception:
            self._logger.exception("Failed to generate notification from rule: %s", rule.name)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def send(self, notification: Notification) -> NotificationStatus:
        """Send a notification through its configured channel."""
        status = await self._dispatcher.dispatch(notification)
        notification.status = status
        self._history.record(notification)

        self._metrics.total_sent += 1
        if status == NotificationStatus.DELIVERED:
            self._metrics.total_delivered += 1
        elif status == NotificationStatus.FAILED:
            self._metrics.total_failed += 1

        if notification.channel == NotificationChannel.EVENTBUS:
            try:
                await self._event_bus.publish(Event(
                    source="notification_service",
                    category=EventCategory.NOTIFICATION,
                    priority=EventPriority.NORMAL,
                    payload={
                        "action": "notification_sent",
                        "notification_id": notification.notification_id,
                        "title": notification.title,
                        "channel": notification.channel.value,
                        "status": status.name,
                    },
                ))
            except Exception:
                self._logger.exception("Failed to publish notification event")

        self._logger.debug("Notification %s sent via %s: %s", notification.notification_id, notification.channel.value, status.name)
        return status

    async def send_notification(
        self,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        channel: NotificationChannel = NotificationChannel.INTERNAL,
        source: str = "",
        category: str = "",
    ) -> Notification:
        """Convenience method to create and send a notification."""
        notification = Notification(
            title=title,
            message=message,
            priority=priority,
            channel=channel,
            source=source,
            category=category,
        )
        await self.send(notification)
        return notification

    # ------------------------------------------------------------------
    # Rules management
    # ------------------------------------------------------------------

    @property
    def manager(self) -> NotificationManager:
        return self._manager

    @property
    def dispatcher(self) -> NotificationDispatcher:
        return self._dispatcher

    @property
    def history(self) -> NotificationHistory:
        return self._history

    @property
    def metrics(self) -> NotificationMetrics:
        return self._metrics
