"""Event Bus — the communication backbone of Atlas.

Every subsystem communicates through the Event Bus.
No subsystem talks directly to another subsystem.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from atlas_core.interfaces.events import Event, EventCategory, EventHandler, EventPriority


@dataclass
class Subscription:
    handler: EventHandler
    event_type: str
    event_filter: Callable[[Event], bool] | None = None


class EventHistory:
    def __init__(self, max_size: int = 1000) -> None:
        self._events: deque[Event] = deque(maxlen=max_size)

    def record(self, event: Event) -> None:
        self._events.append(event)

    def query(
        self,
        category: EventCategory | None = None,
        source: str | None = None,
        priority: EventPriority | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[Event]:
        result: list[Event] = []
        for event in self._events:
            if category is not None and event.category != category:
                continue
            if source is not None and event.source != source:
                continue
            if priority is not None and event.priority != priority:
                continue
            if since is not None and event.timestamp < since:
                continue
            if until is not None and event.timestamp > until:
                continue
            result.append(event)
            if len(result) >= limit:
                break
        return result

    def clear(self) -> None:
        self._events.clear()

    @property
    def size(self) -> int:
        return len(self._events)


class EventBus:
    def __init__(self, max_history: int = 1000) -> None:
        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)
        self._wildcard_subs: list[Subscription] = []
        self._history = EventHistory(max_size=max_history)
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        event_filter: Callable[[Event], bool] | None = None,
    ) -> Subscription:
        sub = Subscription(handler=handler, event_type=event_type, event_filter=event_filter)
        if event_type == "*":
            self._wildcard_subs.append(sub)
        else:
            self._subscriptions[event_type].append(sub)
        self._logger.debug("Subscribed %s to '%s'", handler, event_type)
        return sub

    def unsubscribe(self, subscription: Subscription) -> None:
        if subscription.event_type == "*":
            self._wildcard_subs[:] = [s for s in self._wildcard_subs if s is not subscription]
        else:
            subs = self._subscriptions.get(subscription.event_type)
            if subs:
                self._subscriptions[subscription.event_type] = [s for s in subs if s is not subscription]
        self._logger.debug("Unsubscribed %s from '%s'", subscription.handler, subscription.event_type)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    async def publish(self, event: Event) -> None:
        self._history.record(event)

        candidates: list[Subscription] = list(self._subscriptions.get(event.category.value, []))
        candidates.extend(self._subscriptions.get(event.source, []))
        candidates.extend(self._wildcard_subs)

        for sub in candidates:
            if sub.event_filter is not None and not sub.event_filter(event):
                continue
            try:
                await sub.handler(event)
            except Exception:
                self._logger.exception("Handler error for event %s", event.event_id)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def history(self) -> EventHistory:
        return self._history
