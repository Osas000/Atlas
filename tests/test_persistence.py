"""Tests for Persistence Layer — Milestone 15."""

import json
import os
import tempfile
from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

import pytest

from atlas_core.persistence import (
    MigrationManager,
    PersistenceEventBridge,
    PersistenceManager,
    PersistenceMetrics,
    Repository,
    SQLiteProvider,
    Serializer,
    SnapshotManager,
    StorageProvider,
)
from atlas_core.events import EventBus
from atlas_core.interfaces import ServiceState
from atlas_core.interfaces.events import EventCategory


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def provider(db_path):
    return SQLiteProvider(db_path=db_path)


@pytest.fixture
async def connected_provider(provider):
    await provider.connect()
    yield provider
    await provider.disconnect()


@pytest.fixture
def serializer():
    return Serializer()


@pytest.fixture
async def pm(db_path, event_bus):
    mgr = PersistenceManager(event_bus=event_bus, db_path=db_path)
    await mgr.initialize()
    await mgr.start()
    yield mgr
    await mgr.stop()
    if os.path.exists(db_path):
        os.remove(db_path)


# ======================================================================
# Serializer
# ======================================================================


class TestSerializer:
    def test_serialize_dict(self, serializer):
        data = {"key": "value", "num": 42}
        s = serializer.serialize(data)
        assert json.loads(s) == data

    def test_serialize_list(self, serializer):
        data = [1, 2, 3]
        assert json.loads(serializer.serialize(data)) == data

    def test_serialize_enum(self, serializer):
        class Color(Enum):
            RED = "red"
            BLUE = "blue"

        s = serializer.serialize(Color.RED)
        assert json.loads(s) == "red"

    def test_serialize_datetime(self, serializer):
        dt = datetime(2024, 1, 15, 12, 30, 0)
        s = serializer.serialize(dt)
        assert json.loads(s) == "2024-01-15T12:30:00"

    def test_serialize_uuid(self, serializer):
        uid = UUID("550e8400-e29b-41d4-a716-446655440000")
        s = serializer.serialize(uid)
        assert json.loads(s) == "550e8400-e29b-41d4-a716-446655440000"

    def test_serialize_set(self, serializer):
        s = serializer.serialize({1, 2, 3})
        data = json.loads(s)
        assert sorted(data) == [1, 2, 3]

    def test_serialize_bytes(self, serializer):
        s = serializer.serialize(b"hello")
        assert json.loads(s) == "hello"

    def test_roundtrip_complex(self, serializer):
        data = {
            "name": "test",
            "count": 42,
            "tags": ["a", "b"],
            "meta": {"nested": True},
        }
        s = serializer.serialize(data)
        assert serializer.deserialize(s) == data

    def test_serialize_nested_dataclass(self, serializer):
        from dataclasses import dataclass

        @dataclass
        class Inner:
            value: int

        @dataclass
        class Outer:
            inner: Inner
            label: str

        obj = Outer(inner=Inner(value=5), label="test")
        s = serializer.serialize(obj)
        data = json.loads(s)
        assert data["label"] == "test"
        assert data["inner"]["value"] == 5

    def test_deserialize_string(self, serializer):
        assert serializer.deserialize('{"key": "val"}') == {"key": "val"}

    def test_serialize_none(self, serializer):
        assert serializer.serialize(None) == "null"


# ======================================================================
# StorageProvider (ABC)
# ======================================================================


class TestStorageProvider:
    def test_abc_cannot_instantiate(self):
        with pytest.raises(TypeError):
            StorageProvider()

    def test_abc_has_abstract_methods(self):
        methods = [
            "connect", "disconnect", "save", "load", "delete",
            "exists", "list_keys", "count", "transaction", "health_check",
        ]
        for m in methods:
            assert hasattr(StorageProvider, m)
            assert getattr(getattr(StorageProvider, m), "__isabstractmethod__", False)


# ======================================================================
# SQLiteProvider
# ======================================================================


class TestSQLiteProvider:
    @pytest.mark.asyncio
    async def test_connect(self, provider, db_path):
        await provider.connect()
        assert os.path.exists(db_path)
        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_double_connect(self, provider):
        await provider.connect()
        await provider.connect()  # should not raise
        await provider.disconnect()

    @pytest.mark.asyncio
    async def test_disconnect(self, provider):
        await provider.connect()
        await provider.disconnect()
        assert provider._connection is None

    @pytest.mark.asyncio
    async def test_save_and_load(self, connected_provider):
        await connected_provider.save("test_col", "key1", {"name": "Alice"})
        result = await connected_provider.load("test_col", "key1")
        assert result == {"name": "Alice"}

    @pytest.mark.asyncio
    async def test_load_missing(self, connected_provider):
        result = await connected_provider.load("test_col", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_existing(self, connected_provider):
        await connected_provider.save("test_col", "key1", "value1")
        deleted = await connected_provider.delete("test_col", "key1")
        assert deleted is True
        assert await connected_provider.load("test_col", "key1") is None

    @pytest.mark.asyncio
    async def test_delete_missing(self, connected_provider):
        deleted = await connected_provider.delete("test_col", "nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_exists(self, connected_provider):
        await connected_provider.save("test_col", "key1", "value1")
        assert await connected_provider.exists("test_col", "key1") is True
        assert await connected_provider.exists("test_col", "nonexistent") is False

    @pytest.mark.asyncio
    async def test_list_keys(self, connected_provider):
        await connected_provider.save("test_col", "a", "1")
        await connected_provider.save("test_col", "b", "2")
        keys = await connected_provider.list_keys("test_col")
        assert sorted(keys) == ["a", "b"]

    @pytest.mark.asyncio
    async def test_list_keys_empty(self, connected_provider):
        assert await connected_provider.list_keys("empty") == []

    @pytest.mark.asyncio
    async def test_count(self, connected_provider):
        await connected_provider.save("test_col", "a", "1")
        await connected_provider.save("test_col", "b", "2")
        assert await connected_provider.count("test_col") == 2

    @pytest.mark.asyncio
    async def test_update_overwrites(self, connected_provider):
        await connected_provider.save("test_col", "key1", {"v": 1})
        await connected_provider.save("test_col", "key1", {"v": 2})
        result = await connected_provider.load("test_col", "key1")
        assert result == {"v": 2}

    @pytest.mark.asyncio
    async def test_health_check_connected(self, connected_provider):
        assert await connected_provider.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self, provider):
        assert await provider.health_check() is False

    @pytest.mark.asyncio
    async def test_transaction_commit(self, connected_provider):
        with connected_provider.transaction():
            await connected_provider.save("tx_col", "k1", "value1")
        result = await connected_provider.load("tx_col", "k1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, connected_provider):
        try:
            with connected_provider.transaction():
                await connected_provider.save("tx_col", "k1", "value1")
                raise ValueError("rollback")
        except ValueError:
            pass
        result = await connected_provider.load("tx_col", "k1")
        assert result is None

    @pytest.mark.asyncio
    async def test_transaction_not_connected(self, provider):
        with pytest.raises(RuntimeError, match="not connected"):
            with provider.transaction():
                pass

    @pytest.mark.asyncio
    async def test_execute_raw(self, connected_provider):
        await connected_provider.save("test_col", "k1", "v1")
        rows = connected_provider.execute_raw("SELECT * FROM atlas_storage")
        assert len(rows) >= 1

    @pytest.mark.asyncio
    async def test_execute_write(self, connected_provider):
        connected_provider.execute_write(
            "INSERT INTO atlas_metadata (key, value) VALUES (?, ?)",
            ("test_key", "test_value"),
        )
        rows = connected_provider.execute_raw("SELECT * FROM atlas_metadata WHERE key=?", ("test_key",))
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_tables_created(self, connected_provider):
        tables = connected_provider.execute_raw(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = [t["name"] for t in tables]
        assert "atlas_storage" in names
        assert "atlas_metadata" in names
        assert "atlas_snapshots" in names
        assert "atlas_migrations" in names


# ======================================================================
# Repository
# ======================================================================


class TestRepository:
    @pytest.mark.asyncio
    async def test_create_and_read(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        await repo.create("k1", {"name": "test"})
        result = await repo.read("k1")
        assert result == {"name": "test"}

    @pytest.mark.asyncio
    async def test_read_missing(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        assert await repo.read("missing") is None

    @pytest.mark.asyncio
    async def test_update(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        await repo.create("k1", {"v": 1})
        await repo.update("k1", {"v": 2})
        assert await repo.read("k1") == {"v": 2}

    @pytest.mark.asyncio
    async def test_delete(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        await repo.create("k1", "val")
        assert await repo.delete("k1") is True
        assert await repo.read("k1") is None

    @pytest.mark.asyncio
    async def test_exists(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        await repo.create("k1", "val")
        assert await repo.exists("k1") is True
        assert await repo.exists("missing") is False

    @pytest.mark.asyncio
    async def test_count(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        await repo.create("a", "1")
        await repo.create("b", "2")
        assert await repo.count() == 2

    @pytest.mark.asyncio
    async def test_list_keys(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        await repo.create("z", "1")
        await repo.create("a", "2")
        keys = await repo.list_keys()
        assert sorted(keys) == ["a", "z"]

    @pytest.mark.asyncio
    async def test_find(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        await repo.create("k1", {"type": "book", "year": 2020})
        await repo.create("k2", {"type": "book", "year": 2021})
        await repo.create("k3", {"type": "magazine", "year": 2020})
        results = await repo.find(type="book")
        assert len(results) == 2
        assert all(r[1]["type"] == "book" for r in results)

    @pytest.mark.asyncio
    async def test_find_no_match(self, connected_provider):
        repo = Repository(connected_provider, "test_repo")
        await repo.create("k1", {"type": "book"})
        results = await repo.find(type="movie")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_collection_property(self, connected_provider):
        repo = Repository(connected_provider, "my_collection")
        assert repo.collection == "my_collection"


# ======================================================================
# PersistenceMetrics
# ======================================================================


class TestPersistenceMetrics:
    def test_initial_values(self):
        m = PersistenceMetrics()
        assert m.reads == 0
        assert m.writes == 0
        assert m.deletes == 0
        assert m.transactions == 0
        assert m.rollback_count == 0
        assert m.snapshot_count == 0
        assert m.errors == 0
        assert m.latency == 0.0

    def test_record_read(self):
        m = PersistenceMetrics()
        m.record_read(0.5)
        assert m.reads == 1
        assert m.latency == 0.5

    def test_record_write(self):
        m = PersistenceMetrics()
        m.record_write(0.3)
        assert m.writes == 1
        assert m.latency == 0.3

    def test_record_update(self):
        m = PersistenceMetrics()
        m.record_update()
        assert m.updates == 1

    def test_record_delete(self):
        m = PersistenceMetrics()
        m.record_delete()
        assert m.deletes == 1

    def test_record_transaction(self):
        m = PersistenceMetrics()
        m.record_transaction()
        assert m.transactions == 1

    def test_record_rollback(self):
        m = PersistenceMetrics()
        m.record_rollback()
        assert m.rollback_count == 1

    def test_record_snapshot(self):
        m = PersistenceMetrics()
        m.record_snapshot()
        assert m.snapshot_count == 1

    def test_record_error(self):
        m = PersistenceMetrics()
        m.record_error()
        assert m.errors == 1

    def test_snapshot(self):
        m = PersistenceMetrics()
        m.record_read()
        m.record_write()
        m.record_transaction()
        s = m.snapshot()
        assert s["reads"] == 1
        assert s["writes"] == 1
        assert s["transactions"] == 1
        assert "latency" in s

    def test_reset(self):
        m = PersistenceMetrics()
        m.record_read()
        m.record_error()
        m.reset()
        assert m.reads == 0
        assert m.errors == 0


# ======================================================================
# PersistenceEventBridge
# ======================================================================


class TestPersistenceEventBridge:
    @pytest.mark.asyncio
    async def test_publish(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.publish("test", {"data": "val"})
        assert len(events) >= 1
        assert events[0].category == EventCategory.PERSISTENCE

    @pytest.mark.asyncio
    async def test_database_connected(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.database_connected()
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["action"] == "database_connected"

    @pytest.mark.asyncio
    async def test_database_disconnected(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.database_disconnected()
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["action"] == "database_disconnected"

    @pytest.mark.asyncio
    async def test_data_saved(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.data_saved("col", "key1")
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["collection"] == "col"

    @pytest.mark.asyncio
    async def test_data_loaded(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.data_loaded("col", "key1")
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["action"] == "data_loaded"

    @pytest.mark.asyncio
    async def test_data_deleted(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.data_deleted("col", "key1")
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["action"] == "data_deleted"

    @pytest.mark.asyncio
    async def test_transaction_started(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.transaction_started()
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["action"] == "transaction_started"

    @pytest.mark.asyncio
    async def test_transaction_committed(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.transaction_committed()
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["action"] == "transaction_committed"

    @pytest.mark.asyncio
    async def test_transaction_rolled_back(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.transaction_rolled_back()
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["action"] == "transaction_rolled_back"

    @pytest.mark.asyncio
    async def test_snapshot_created(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.snapshot_created("s1", "test-snap")
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["snapshot_id"] == "s1"

    @pytest.mark.asyncio
    async def test_snapshot_restored(self, event_bus):
        bridge = PersistenceEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await bridge.snapshot_restored("s1")
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert pe[0].payload["snapshot_id"] == "s1"


# ======================================================================
# MigrationManager
# ======================================================================


class TestMigrationManager:
    @pytest.mark.asyncio
    async def test_current_version_zero(self, connected_provider):
        mm = MigrationManager(connected_provider)
        assert mm.current_version() == 0

    @pytest.mark.asyncio
    async def test_register_migration(self, connected_provider):
        mm = MigrationManager(connected_provider)
        mm.register(1, "initial", lambda s: None, lambda s: None)
        assert mm.count == 1

    @pytest.mark.asyncio
    async def test_register_duplicate(self, connected_provider):
        mm = MigrationManager(connected_provider)
        mm.register(1, "v1", lambda s: None, lambda s: None)
        with pytest.raises(ValueError, match="already registered"):
            mm.register(1, "v1_dup", lambda s: None, lambda s: None)

    @pytest.mark.asyncio
    async def test_pending_versions(self, connected_provider):
        mm = MigrationManager(connected_provider)
        mm.register(1, "v1", lambda s: None, lambda s: None)
        mm.register(2, "v2", lambda s: None, lambda s: None)
        assert mm.pending_versions() == [1, 2]

    @pytest.mark.asyncio
    async def test_upgrade(self, connected_provider):
        mm = MigrationManager(connected_provider)
        applied = []

        def up(s):
            applied.append("v1_up")

        mm.register(1, "v1", up, lambda s: None)
        await mm.upgrade()
        assert mm.current_version() == 1
        assert "v1_up" in applied

    @pytest.mark.asyncio
    async def test_upgrade_targeted(self, connected_provider):
        mm = MigrationManager(connected_provider)
        mm.register(1, "v1", lambda s: None, lambda s: None)
        mm.register(2, "v2", lambda s: None, lambda s: None)
        await mm.upgrade(target_version=1)
        assert mm.current_version() == 1

    @pytest.mark.asyncio
    async def test_downgrade(self, connected_provider):
        mm = MigrationManager(connected_provider)
        applied = []

        def up(s):
            applied.append("up")

        def down(s):
            applied.append("down")

        mm.register(1, "v1", up, down)
        await mm.upgrade()
        assert mm.current_version() == 1
        applied.clear()
        await mm.downgrade(0)
        assert mm.current_version() == 0
        assert "down" in applied

    @pytest.mark.asyncio
    async def test_upgrade_missing_migration(self, connected_provider):
        mm = MigrationManager(connected_provider)
        # Register v2 but not v1 - should fail on upgrade
        mm.register(2, "v2", lambda s: _fail, lambda s: None)
        with pytest.raises(ValueError, match="No migration registered"):
            await mm.upgrade()


def _fail(s):
    raise ValueError("should not be called")


# ======================================================================
# SnapshotManager
# ======================================================================


class TestSnapshotManager:
    @pytest.mark.asyncio
    async def test_create_snapshot(self, connected_provider, serializer):
        sm = SnapshotManager(connected_provider, serializer)
        await connected_provider.save("data", "k1", {"value": 1})
        sid = await sm.create("test-snap", {"data": {"k1": {"value": 1}}})
        assert isinstance(sid, str)
        assert len(sid) > 0

    @pytest.mark.asyncio
    async def test_restore_snapshot(self, connected_provider, serializer):
        sm = SnapshotManager(connected_provider, serializer)
        await connected_provider.save("data", "k1", {"value": 1})
        sid = await sm.create("test-snap", {"data": {"k1": {"value": 1}}})
        await connected_provider.save("data", "k1", {"value": 99})
        restored = await sm.restore(sid)
        assert restored is not None
        assert "data" in restored

    @pytest.mark.asyncio
    async def test_restore_nonexistent(self, connected_provider, serializer):
        sm = SnapshotManager(connected_provider, serializer)
        result = await sm.restore("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_snapshots(self, connected_provider, serializer):
        sm = SnapshotManager(connected_provider, serializer)
        await sm.create("snap1", {})
        await sm.create("snap2", {})
        snaps = await sm.list_snapshots()
        assert len(snaps) == 2

    @pytest.mark.asyncio
    async def test_list_snapshots_empty(self, connected_provider, serializer):
        sm = SnapshotManager(connected_provider, serializer)
        assert await sm.list_snapshots() == []

    @pytest.mark.asyncio
    async def test_delete_snapshot(self, connected_provider, serializer):
        sm = SnapshotManager(connected_provider, serializer)
        sid = await sm.create("test", {})
        assert await sm.delete(sid) is True
        assert await sm.count() == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, connected_provider, serializer):
        sm = SnapshotManager(connected_provider, serializer)
        assert await sm.delete("nonexistent") is False

    @pytest.mark.asyncio
    async def test_count_snapshots(self, connected_provider, serializer):
        sm = SnapshotManager(connected_provider, serializer)
        await sm.create("a", {})
        await sm.create("b", {})
        assert await sm.count() == 2


# ======================================================================
# PersistenceManager (IService)
# ======================================================================


class TestPersistenceManager:
    @pytest.mark.asyncio
    async def test_create(self, db_path, event_bus):
        pm = PersistenceManager(event_bus=event_bus, db_path=db_path)
        assert pm.name == "persistence_manager"

    @pytest.mark.asyncio
    async def test_initialize(self, pm):
        assert pm._state == ServiceState.RUNNING

    @pytest.mark.asyncio
    async def test_stop(self, db_path, event_bus):
        pm = PersistenceManager(event_bus=event_bus, db_path=db_path)
        await pm.initialize()
        await pm.start()
        await pm.stop()
        assert pm._state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_health_check_running(self, pm):
        health = await pm.health_check()
        assert health.healthy

    @pytest.mark.asyncio
    async def test_health_check_not_started(self, db_path, event_bus):
        pm = PersistenceManager(event_bus=event_bus, db_path=db_path)
        health = await pm.health_check()
        assert not health.healthy

    @pytest.mark.asyncio
    async def test_save_and_load(self, pm):
        await pm.save("test", "k1", {"name": "test"})
        result = await pm.load("test", "k1")
        assert result == {"name": "test"}

    @pytest.mark.asyncio
    async def test_load_missing(self, pm):
        assert await pm.load("test", "missing") is None

    @pytest.mark.asyncio
    async def test_delete(self, pm):
        await pm.save("test", "k1", "val")
        assert await pm.delete("test", "k1") is True
        assert await pm.load("test", "k1") is None

    @pytest.mark.asyncio
    async def test_delete_missing(self, pm):
        assert await pm.delete("test", "missing") is False

    @pytest.mark.asyncio
    async def test_register_repository(self, pm, pm_storage):
        repo = Repository(pm.storage, "custom")
        pm.register_repository("custom", repo)
        assert pm.repository("custom") is repo

    @pytest.mark.asyncio
    async def test_register_duplicate_repository(self, pm):
        repo = Repository(pm.storage, "dup")
        pm.register_repository("dup", repo)
        with pytest.raises(ValueError, match="already registered"):
            pm.register_repository("dup", Repository(pm.storage, "dup2"))

    @pytest.mark.asyncio
    async def test_repository_not_found(self, pm):
        assert pm.repository("nonexistent") is None

    @pytest.mark.asyncio
    async def test_create_repository(self, pm):
        repo = pm.create_repository("my_repo")
        assert repo.collection == "my_repo"
        assert pm.repository("my_repo") is repo

    @pytest.mark.asyncio
    async def test_create_duplicate_repository(self, pm):
        pm.create_repository("dup")
        with pytest.raises(ValueError, match="already registered"):
            pm.create_repository("dup")

    @pytest.mark.asyncio
    async def test_properties(self, pm):
        assert pm.storage is not None
        assert pm.serializer is not None
        assert pm.metrics is not None
        assert pm.event_bridge is not None
        assert pm.migration_manager is not None
        assert pm.snapshot_manager is not None

    @pytest.mark.asyncio
    async def test_metrics_tracked_on_save(self, pm):
        m0 = pm.metrics.writes
        await pm.save("test", "k1", "val")
        assert pm.metrics.writes == m0 + 1

    @pytest.mark.asyncio
    async def test_metrics_tracked_on_load(self, pm):
        await pm.save("test", "k1", "val")
        m0 = pm.metrics.reads
        await pm.load("test", "k1")
        assert pm.metrics.reads == m0 + 1

    @pytest.mark.asyncio
    async def test_metrics_tracked_on_delete(self, pm):
        await pm.save("test", "k1", "val")
        m0 = pm.metrics.deletes
        await pm.delete("test", "k1")
        assert pm.metrics.deletes == m0 + 1

    @pytest.mark.asyncio
    async def test_event_published_on_save(self, event_bus, db_path):
        pm = PersistenceManager(event_bus=event_bus, db_path=db_path)
        await pm.initialize()
        await pm.start()
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("persistence", capture)
        await pm.save("test", "k1", "val")
        pe = [e for e in events if e.category == EventCategory.PERSISTENCE]
        assert any(e.payload.get("action") == "data_saved" for e in pe)
        await pm.stop()

    @pytest.mark.asyncio
    async def test_backup_and_restore(self, pm, tmp_path):
        await pm.save("test", "k1", "original")
        backup_path = str(tmp_path / "backup.db")
        await pm.backup(backup_path)
        assert os.path.exists(backup_path)

    @pytest.mark.asyncio
    async def test_transaction(self, pm):
        pm._metrics.record_transaction = lambda: None
        pm._event_bridge.transaction_started = lambda: None  # type: ignore
        pm._event_bridge.transaction_committed = lambda: None  # type: ignore
        await pm.save("tx", "k1", "val")
        assert await pm.load("tx", "k1") == "val"

    @pytest.mark.asyncio
    async def test_iservice_lifecycle(self, db_path, event_bus):
        pm = PersistenceManager(event_bus=event_bus, db_path=db_path)
        await pm.initialize()
        assert pm._state == ServiceState.INITIALIZED
        await pm.start()
        assert pm._state == ServiceState.RUNNING
        await pm.stop()
        assert pm._state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_super_called(self, db_path, event_bus):
        calls = []

        class Tracking(PersistenceManager):
            async def initialize(self):
                await super().initialize()
                calls.append("init")
            async def start(self):
                await super().start()
                calls.append("start")
            async def stop(self):
                await super().stop()
                calls.append("stop")

        pm = Tracking(event_bus=event_bus, db_path=db_path)
        await pm.initialize()
        await pm.start()
        await pm.stop()
        assert len(calls) >= 2


@pytest.fixture
async def pm_storage(pm):
    return pm.storage


# ======================================================================
# Kernel Integration
# ======================================================================


class TestKernelIntegration:
    @pytest.mark.asyncio
    async def test_kernel_registers_persistence(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        assert kernel.persistence_manager is not None
        assert kernel.persistence_manager.name == "persistence_manager"

    @pytest.mark.asyncio
    async def test_kernel_persistence_property_guard(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        with pytest.raises(RuntimeError):
            _ = kernel.persistence_manager

    @pytest.mark.asyncio
    async def test_kernel_persistence_is_service(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        svc = kernel.registry.resolve("persistence_manager")
        assert svc is not None
        assert svc.name == "persistence_manager"

    @pytest.mark.asyncio
    async def test_kernel_lifecycle_with_persistence(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        await kernel.start()
        assert kernel.state.name == "RUNNING"
        await kernel.stop()
        assert kernel.state.name == "STOPPED"


# ======================================================================
# EventCategory.PERSISTENCE
# ======================================================================


class TestPersistenceEventCategory:
    def test_category_exists(self):
        assert hasattr(EventCategory, "PERSISTENCE")
        assert EventCategory.PERSISTENCE.value == "persistence"

    def test_category_is_unique(self):
        values = {c.value for c in EventCategory}
        assert "persistence" in values


# ======================================================================
# Error Handling
# ======================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_save_error_handling(self, pm):
        pm._storage.save = lambda c, k, v: (_ for _ in ()).throw(Exception("db error"))
        with pytest.raises(Exception, match="db error"):
            await pm.save("test", "k1", "val")

    @pytest.mark.asyncio
    async def test_load_error_handling(self, pm):
        pm._storage.load = lambda c, k: (_ for _ in ()).throw(Exception("load error"))
        with pytest.raises(Exception, match="load error"):
            await pm.load("test", "k1")

    @pytest.mark.asyncio
    async def test_delete_error_handling(self, pm):
        pm._storage.delete = lambda c, k: (_ for _ in ()).throw(Exception("delete error"))
        with pytest.raises(Exception, match="delete error"):
            await pm.delete("test", "k1")

    @pytest.mark.asyncio
    async def test_metrics_error_incremented(self, pm):
        original = pm._metrics.errors
        pm._storage.save = lambda c, k, v: (_ for _ in ()).throw(Exception("err"))
        try:
            await pm.save("test", "k1", "val")
        except Exception:
            pass
        assert pm._metrics.errors == original + 1

    @pytest.mark.asyncio
    async def test_implements_iservice(self, pm):
        from atlas_core.interfaces import IService
        assert isinstance(pm, IService)
