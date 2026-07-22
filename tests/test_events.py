"""Tests for the Event Bus and Event History."""

from datetime import datetime, timedelta

import pytest

from atlas_core.events import EventBus, EventHistory
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def sample_event() -> Event:
    return Event(
        source="test_source",
        category=EventCategory.SYSTEM,
        priority=EventPriority.HIGH,
        payload={"key": "value"},
    )


# ------------------------------------------------------------------
# Event Bus — publish / subscribe
# ------------------------------------------------------------------

class TestEventBus:
    async def test_publish_delivers_to_subscriber(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("system", handler)
        event = Event(source="test", category=EventCategory.SYSTEM)
        await bus.publish(event)
        assert len(received) == 1
        assert received[0].event_id == event.event_id

    async def test_publish_no_subscribers(self, bus: EventBus) -> None:
        event = Event(source="test", category=EventCategory.SYSTEM)
        await bus.publish(event)  # should not raise

    async def test_multiple_subscribers(self, bus: EventBus) -> None:
        received: list[str] = []

        async def h1(event: Event) -> None:
            received.append("h1")

        async def h2(event: Event) -> None:
            received.append("h2")

        bus.subscribe("system", h1)
        bus.subscribe("system", h2)
        await bus.publish(Event(source="test", category=EventCategory.SYSTEM))
        assert sorted(received) == ["h1", "h2"]

    async def test_unsubscribe_stops_delivery(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        sub = bus.subscribe("system", handler)
        await bus.publish(Event(source="test", category=EventCategory.SYSTEM))
        assert len(received) == 1

        bus.unsubscribe(sub)
        await bus.publish(Event(source="test2", category=EventCategory.SYSTEM))
        assert len(received) == 1  # no new delivery

    async def test_wildcard_subscriber_receives_all(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("*", handler)
        await bus.publish(Event(source="a", category=EventCategory.SYSTEM))
        await bus.publish(Event(source="b", category=EventCategory.HEALTH))
        assert len(received) == 2

    async def test_event_filter(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("system", handler, event_filter=lambda e: e.source == "important")
        await bus.publish(Event(source="ignore", category=EventCategory.SYSTEM))
        await bus.publish(Event(source="important", category=EventCategory.SYSTEM))
        assert len(received) == 1
        assert received[0].source == "important"

    async def test_subscribe_by_source_name(self, bus: EventBus) -> None:
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe("my_component", handler)
        await bus.publish(Event(source="my_component", category=EventCategory.SYSTEM))
        await bus.publish(Event(source="other", category=EventCategory.SYSTEM))
        assert len(received) == 1

    async def test_handler_exception_does_not_crash(self, bus: EventBus) -> None:
        async def broken(event: Event) -> None:
            raise RuntimeError("boom")

        async def good(event: Event) -> None:
            good.called = True  # type: ignore[attr-defined]

        good.called = False  # type: ignore[attr-defined]
        bus.subscribe("system", broken)
        bus.subscribe("system", good)
        await bus.publish(Event(source="test", category=EventCategory.SYSTEM))
        assert good.called is True

    async def test_publish_records_history(self, bus: EventBus) -> None:
        event = Event(source="test", category=EventCategory.SYSTEM)
        await bus.publish(event)
        assert bus.history.size == 1
        assert bus.history.query()[0].event_id == event.event_id


# ------------------------------------------------------------------
# Event History
# ------------------------------------------------------------------

class TestEventHistory:
    def test_record_and_query(self) -> None:
        h = EventHistory(max_size=100)
        e1 = Event(source="a", category=EventCategory.SYSTEM)
        e2 = Event(source="b", category=EventCategory.HEALTH)
        h.record(e1)
        h.record(e2)
        assert h.size == 2
        assert len(h.query()) == 2

    def test_query_by_category(self) -> None:
        h = EventHistory()
        h.record(Event(source="a", category=EventCategory.SYSTEM))
        h.record(Event(source="b", category=EventCategory.HEALTH))
        h.record(Event(source="c", category=EventCategory.SYSTEM))
        results = h.query(category=EventCategory.SYSTEM)
        assert len(results) == 2

    def test_query_by_source(self) -> None:
        h = EventHistory()
        h.record(Event(source="alpha", category=EventCategory.SYSTEM))
        h.record(Event(source="beta", category=EventCategory.SYSTEM))
        results = h.query(source="alpha")
        assert len(results) == 1

    def test_query_by_priority(self) -> None:
        h = EventHistory()
        h.record(Event(source="a", category=EventCategory.SYSTEM, priority=EventPriority.HIGH))
        h.record(Event(source="b", category=EventCategory.SYSTEM, priority=EventPriority.LOW))
        results = h.query(priority=EventPriority.HIGH)
        assert len(results) == 1

    def test_query_by_time_range(self) -> None:
        h = EventHistory()
        now = datetime.now()
        old = Event(source="a", category=EventCategory.SYSTEM, timestamp=now - timedelta(hours=2))
        new = Event(source="b", category=EventCategory.SYSTEM, timestamp=now)
        h.record(old)
        h.record(new)
        since = now - timedelta(hours=1)
        results = h.query(since=since)
        assert len(results) == 1
        assert results[0].source == "b"

    def test_query_limit(self) -> None:
        h = EventHistory()
        for i in range(10):
            h.record(Event(source=f"s{i}", category=EventCategory.SYSTEM))
        assert len(h.query(limit=3)) == 3

    def test_clear(self) -> None:
        h = EventHistory()
        h.record(Event(source="a", category=EventCategory.SYSTEM))
        h.clear()
        assert h.size == 0

    def test_max_size_enforced(self) -> None:
        h = EventHistory(max_size=3)
        for i in range(10):
            h.record(Event(source=f"s{i}", category=EventCategory.SYSTEM))
        assert h.size == 3
        # newest events are kept (deque behavior)
        assert h.query()[0].source == "s7"

    def test_empty_query(self) -> None:
        h = EventHistory()
        assert h.query() == []
