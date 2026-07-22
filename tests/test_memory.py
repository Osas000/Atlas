"""Tests for the Memory Engine."""

from datetime import datetime, timedelta

import pytest

from atlas_core.events import EventBus
from atlas_core.memory import (
    ArchiveMemory,
    InMemoryStore,
    LongTermMemory,
    MemoryCategory,
    MemoryImportance,
    MemoryManager,
    MemoryRecord,
    MemoryStore,
    ProjectMemory,
    SessionMemory,
    WorkingMemory,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def sample_record() -> MemoryRecord:
    return MemoryRecord(
        title="Test Memory",
        category=MemoryCategory.PROJECT,
        tags=["test", "memory"],
        source="test_suite",
        search_keywords=["test", "sample"],
        content={"key": "value"},
    )


@pytest.fixture
def manager(bus: EventBus) -> MemoryManager:
    return MemoryManager(bus)


# ======================================================================
# MemoryCategory
# ======================================================================


class TestMemoryCategory:
    def test_values(self) -> None:
        assert MemoryCategory.PROFESSIONAL.value == "professional"
        assert MemoryCategory.LEARNING.value == "learning"
        assert MemoryCategory.CLIENT.value == "client"
        assert MemoryCategory.PLATFORM.value == "platform"
        assert MemoryCategory.FINANCIAL.value == "financial"
        assert MemoryCategory.CAREER.value == "career"
        assert MemoryCategory.PROJECT.value == "project"
        assert MemoryCategory.TECHNICAL.value == "technical"
        assert MemoryCategory.PREFERENCES.value == "preferences"
        assert MemoryCategory.OPERATIONAL.value == "operational"


# ======================================================================
# MemoryImportance
# ======================================================================


class TestMemoryImportance:
    def test_values(self) -> None:
        assert MemoryImportance.VERY_HIGH.value == 5
        assert MemoryImportance.HIGH.value == 4
        assert MemoryImportance.MEDIUM.value == 3
        assert MemoryImportance.LOW.value == 2
        assert MemoryImportance.VERY_LOW.value == 1


# ======================================================================
# MemoryRecord
# ======================================================================


class TestMemoryRecord:
    def test_defaults(self) -> None:
        r = MemoryRecord(title="Foo")
        assert r.title == "Foo"
        assert r.category == MemoryCategory.PROFESSIONAL
        assert r.importance == MemoryImportance.MEDIUM
        assert r.confidence == 1.0
        assert r.version == 1
        assert r.tags == []
        assert isinstance(r.memory_id, str)

    def test_custom_values(self) -> None:
        r = MemoryRecord(
            title="Bar",
            category=MemoryCategory.CLIENT,
            tags=["client"],
            importance=MemoryImportance.HIGH,
        )
        assert r.title == "Bar"
        assert r.category == MemoryCategory.CLIENT
        assert r.tags == ["client"]
        assert r.importance == MemoryImportance.HIGH


# ======================================================================
# InMemoryStore
# ======================================================================


class TestInMemoryStore:
    async def test_create_and_get(self, store: InMemoryStore, sample_record: MemoryRecord) -> None:
        created = await store.create(sample_record)
        assert created.memory_id == sample_record.memory_id
        fetched = await store.get(sample_record.memory_id)
        assert fetched is not None
        assert fetched.title == "Test Memory"

    async def test_get_missing(self, store: InMemoryStore) -> None:
        assert await store.get("nonexistent") is None

    async def test_update(self, store: InMemoryStore, sample_record: MemoryRecord) -> None:
        await store.create(sample_record)
        updated = sample_record.model_copy(update={"title": "Updated"})
        result = await store.update(updated)
        assert result.title == "Updated"
        fetched = await store.get(sample_record.memory_id)
        assert fetched is not None
        assert fetched.title == "Updated"

    async def test_delete(self, store: InMemoryStore, sample_record: MemoryRecord) -> None:
        await store.create(sample_record)
        await store.delete(sample_record.memory_id)
        assert await store.get(sample_record.memory_id) is None

    async def test_delete_missing(self, store: InMemoryStore) -> None:
        await store.delete("nonexistent")  # should not raise

    async def test_count(self, store: InMemoryStore, sample_record: MemoryRecord) -> None:
        assert await store.count() == 0
        await store.create(sample_record)
        assert await store.count() == 1

    async def test_search_by_query(self, store: InMemoryStore) -> None:
        a = MemoryRecord(title="Python Project", search_keywords=["python", "coding"])
        b = MemoryRecord(title="Design Review", search_keywords=["design", "ui"])
        await store.create(a)
        await store.create(b)
        results = await store.search(query="python")
        assert len(results) == 1
        assert results[0].title == "Python Project"

    async def test_search_by_category(self, store: InMemoryStore) -> None:
        a = MemoryRecord(title="A", category=MemoryCategory.PROJECT)
        b = MemoryRecord(title="B", category=MemoryCategory.CLIENT)
        await store.create(a)
        await store.create(b)
        results = await store.search(category=MemoryCategory.PROJECT)
        assert len(results) == 1
        assert results[0].title == "A"

    async def test_search_by_tags(self, store: InMemoryStore) -> None:
        a = MemoryRecord(title="A", tags=["foo", "bar"])
        b = MemoryRecord(title="B", tags=["baz"])
        await store.create(a)
        await store.create(b)
        results = await store.search(tags=["foo"])
        assert len(results) == 1
        assert results[0].title == "A"

    async def test_search_by_importance(self, store: InMemoryStore) -> None:
        a = MemoryRecord(title="A", importance=MemoryImportance.HIGH)
        b = MemoryRecord(title="B", importance=MemoryImportance.LOW)
        await store.create(a)
        await store.create(b)
        results = await store.search(importance=MemoryImportance.HIGH)
        assert len(results) == 1

    async def test_search_by_time_range(self, store: InMemoryStore) -> None:
        now = datetime.now()
        old = MemoryRecord(title="Old", created_at=now - timedelta(hours=5))
        recent = MemoryRecord(title="Recent", created_at=now)
        await store.create(old)
        await store.create(recent)
        since = now - timedelta(hours=2)
        results = await store.search(since=since)
        assert len(results) == 1
        assert results[0].title == "Recent"

    async def test_search_until(self, store: InMemoryStore) -> None:
        now = datetime.now()
        old = MemoryRecord(title="Old", created_at=now - timedelta(hours=5))
        recent = MemoryRecord(title="Recent", created_at=now)
        await store.create(old)
        await store.create(recent)
        until = now - timedelta(hours=1)
        results = await store.search(until=until)
        assert len(results) == 1
        assert results[0].title == "Old"

    async def test_search_limit_offset(self, store: InMemoryStore) -> None:
        for i in range(10):
            await store.create(MemoryRecord(title=f"Item {i}", tags=["test"]))
        results = await store.search(tags=["test"], limit=3, offset=2)
        assert len(results) == 3

    async def test_list(self, store: InMemoryStore) -> None:
        a = MemoryRecord(title="A", category=MemoryCategory.PROJECT)
        b = MemoryRecord(title="B", category=MemoryCategory.CLIENT)
        await store.create(a)
        await store.create(b)
        results = await store.list(category=MemoryCategory.PROJECT)
        assert len(results) == 1
        assert results[0].title == "A"

    async def test_list_all(self, store: InMemoryStore) -> None:
        for i in range(5):
            await store.create(MemoryRecord(title=f"Item {i}"))
        results = await store.list()
        assert len(results) == 5


# ======================================================================
# MemoryLayer (via WorkingMemory)
# ======================================================================


class TestMemoryLayer:
    async def test_create(self, bus: EventBus, sample_record: MemoryRecord) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        result = await wm.create(sample_record)
        assert result.memory_id == sample_record.memory_id

    async def test_get_missing(self, bus: EventBus) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        assert await wm.get("nonexistent") is None

    async def test_update_existing(self, bus: EventBus, sample_record: MemoryRecord) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        await wm.create(sample_record)
        updated = sample_record.model_copy(update={"title": "Updated"})
        result = await wm.update(updated)
        assert result.title == "Updated"
        assert result.version == 2

    async def test_update_missing_raises(self, bus: EventBus, sample_record: MemoryRecord) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        with pytest.raises(ValueError, match="Memory not found"):
            await wm.update(sample_record)

    async def test_delete(self, bus: EventBus, sample_record: MemoryRecord) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        await wm.create(sample_record)
        await wm.delete(sample_record.memory_id)
        assert await wm.get(sample_record.memory_id) is None

    async def test_delete_missing(self, bus: EventBus) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        await wm.delete("nonexistent")  # should not raise

    async def test_search(self, bus: EventBus) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        await wm.create(MemoryRecord(title="Alpha", tags=["a"]))
        await wm.create(MemoryRecord(title="Beta", tags=["b"]))
        results = await wm.search(tags=["a"])
        assert len(results) == 1
        assert results[0].title == "Alpha"

    async def test_list(self, bus: EventBus) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        await wm.create(MemoryRecord(title="X", category=MemoryCategory.PROJECT))
        await wm.create(MemoryRecord(title="Y", category=MemoryCategory.CLIENT))
        results = await wm.list(category=MemoryCategory.PROJECT)
        assert len(results) == 1

    async def test_clear(self, bus: EventBus) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        await wm.create(MemoryRecord(title="A"))
        await wm.create(MemoryRecord(title="B"))
        assert await wm.count() == 2
        await wm.clear()
        assert await wm.count() == 0

    async def test_count(self, bus: EventBus) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        assert await wm.count() == 0
        await wm.create(MemoryRecord(title="A"))
        assert await wm.count() == 1


# ======================================================================
# Concrete Memory Layers
# ======================================================================


class TestWorkingMemory:
    async def test_layer_name(self, bus: EventBus) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        assert wm.name == "working_memory"

    async def test_create_and_read(self, bus: EventBus) -> None:
        wm = WorkingMemory(InMemoryStore(), bus)
        r = MemoryRecord(title="Task Data", content={"task": "write docs"})
        await wm.create(r)
        fetched = await wm.get(r.memory_id)
        assert fetched is not None
        assert fetched.content["task"] == "write docs"


class TestSessionMemory:
    async def test_layer_name(self, bus: EventBus) -> None:
        sm = SessionMemory(InMemoryStore(), bus)
        assert sm.name == "session_memory"

    async def test_create_and_search(self, bus: EventBus) -> None:
        sm = SessionMemory(InMemoryStore(), bus)
        r = MemoryRecord(title="Session Question", tags=["qa"])
        await sm.create(r)
        results = await sm.search(query="Question")
        assert len(results) == 1


class TestProjectMemory:
    async def test_layer_name(self, bus: EventBus) -> None:
        pm = ProjectMemory(InMemoryStore(), bus)
        assert pm.name == "project_memory"

    async def test_scoped_crud(self, bus: EventBus) -> None:
        pm = ProjectMemory(InMemoryStore(), bus)
        r = MemoryRecord(title="Project Requirement", category=MemoryCategory.PROJECT)
        await pm.create(r)
        fetched = await pm.get(r.memory_id)
        assert fetched is not None
        assert fetched.category == MemoryCategory.PROJECT


class TestLongTermMemory:
    async def test_layer_name(self, bus: EventBus) -> None:
        ltm = LongTermMemory(InMemoryStore(), bus)
        assert ltm.name == "long_term_memory"

    async def test_permanent_storage(self, bus: EventBus) -> None:
        ltm = LongTermMemory(InMemoryStore(), bus)
        r = MemoryRecord(title="Skill: Python", importance=MemoryImportance.HIGH)
        await ltm.create(r)
        assert await ltm.count() == 1


class TestArchiveMemory:
    async def test_layer_name(self, bus: EventBus) -> None:
        am = ArchiveMemory(InMemoryStore(), bus)
        assert am.name == "archive_memory"

    async def test_read_only_pattern(self, bus: EventBus) -> None:
        am = ArchiveMemory(InMemoryStore(), bus)
        r = MemoryRecord(title="Old Project", category=MemoryCategory.PROJECT)
        await am.create(r)
        fetched = await am.get(r.memory_id)
        assert fetched is not None
        assert fetched.title == "Old Project"


# ======================================================================
# MemoryManager
# ======================================================================


class TestMemoryManager:
    async def test_initialise(self, manager: MemoryManager) -> None:
        assert manager.name == "memory_manager"
        await manager.initialize()

    async def test_start_stop(self, manager: MemoryManager) -> None:
        await manager.start()
        await manager.stop()

    async def test_health_check(self, manager: MemoryManager) -> None:
        health = await manager.health_check()
        assert health.healthy is True
        assert health.metadata["total_memories"] == 0

    async def test_layer_accessors(self, manager: MemoryManager) -> None:
        assert isinstance(manager.working, WorkingMemory)
        assert isinstance(manager.session, SessionMemory)
        assert isinstance(manager.project, ProjectMemory)
        assert isinstance(manager.long_term, LongTermMemory)
        assert isinstance(manager.archive, ArchiveMemory)

    async def test_write_to_working(self, manager: MemoryManager) -> None:
        r = MemoryRecord(title="Current Task")
        created = await manager.working.create(r)
        fetched = await manager.working.get(created.memory_id)
        assert fetched is not None

    async def test_write_to_long_term(self, manager: MemoryManager) -> None:
        r = MemoryRecord(title="Permanent Skill", importance=MemoryImportance.VERY_HIGH)
        await manager.long_term.create(r)
        assert await manager.long_term.count() == 1

    async def test_search_all(self, manager: MemoryManager) -> None:
        await manager.working.create(MemoryRecord(title="Working Item", tags=["find_me"]))
        await manager.long_term.create(MemoryRecord(title="LTM Item", tags=["find_me"]))
        results = await manager.search_all(tags=["find_me"])
        assert len(results) == 2

    async def test_search_all_respects_limit(self, manager: MemoryManager) -> None:
        for _ in range(5):
            await manager.working.create(MemoryRecord(title="Item", tags=["limited"]))
        results = await manager.search_all(tags=["limited"], limit=3)
        assert len(results) == 3

    async def test_search_all_returns_from_all_layers(self, manager: MemoryManager) -> None:
        layers = [manager.working, manager.session, manager.project, manager.long_term, manager.archive]
        for i, layer in enumerate(layers):
            await layer.create(MemoryRecord(title=f"Item {i}", tags=["multi_layer"]))
        results = await manager.search_all(tags=["multi_layer"])
        assert len(results) == 5

    async def test_promote_to_long_term(self, manager: MemoryManager) -> None:
        r = MemoryRecord(title="Promotable", tags=["promote"])
        created = await manager.working.create(r)
        promoted = await manager.promote(created.memory_id, "long_term")
        assert promoted is not None
        assert promoted.title == "Promotable"
        assert await manager.working.get(created.memory_id) is None
        assert await manager.long_term.get(created.memory_id) is not None

    async def test_promote_same_layer(self, manager: MemoryManager) -> None:
        r = MemoryRecord(title="Stay")
        created = await manager.long_term.create(r)
        result = await manager.promote(created.memory_id, "long_term")
        assert result is not None
        assert result.title == "Stay"

    async def test_promote_nonexistent(self, manager: MemoryManager) -> None:
        result = await manager.promote("nonexistent", "long_term")
        assert result is None

    async def test_health_check_counts_memories(self, manager: MemoryManager) -> None:
        await manager.working.create(MemoryRecord(title="W1"))
        await manager.session.create(MemoryRecord(title="S1"))
        await manager.project.create(MemoryRecord(title="P1"))
        health = await manager.health_check()
        assert health.metadata["total_memories"] == 3

    async def test_promote_unknown_layer(self, manager: MemoryManager) -> None:
        r = MemoryRecord(title="Orphan")
        created = await manager.working.create(r)
        result = await manager.promote(created.memory_id, "nonexistent")
        assert result is None
        # record should still be in working
        assert await manager.working.get(created.memory_id) is not None

    async def test_promote_to_archive(self, manager: MemoryManager) -> None:
        r = MemoryRecord(title="Archive Me")
        created = await manager.working.create(r)
        result = await manager.promote(created.memory_id, "archive")
        assert result is not None
        assert result.title == "Archive Me"
        assert await manager.archive.get(created.memory_id) is not None
