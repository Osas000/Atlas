"""Persistence Layer — the only subsystem responsible for durable storage.

Every subsystem requiring persistence must use this layer.
No subsystem communicates directly with SQLite or any database.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid as uuid_module
from abc import ABC, abstractmethod
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Iterator, Optional
from uuid import UUID

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Serializer
# ======================================================================


class Serializer:
    def serialize(self, obj: Any) -> str:
        return json.dumps(obj, default=self._default_serializer, ensure_ascii=False)

    def deserialize(self, data: str) -> Any:
        return json.loads(data)

    def _default_serializer(self, obj: Any) -> Any:
        if is_dataclass(obj):
            return {k: self._value(v) for k, v in obj.__dict__.items()}
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, set):
            return list(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def _value(self, v: Any) -> Any:
        if is_dataclass(v):
            return {k: self._value(field_val) for k, field_val in v.__dict__.items()}
        if isinstance(v, Enum):
            return v.value
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, UUID):
            return str(v)
        if isinstance(v, set):
            return list(v)
        if isinstance(v, bytes):
            return v.decode("utf-8", errors="replace")
        if isinstance(v, dict):
            return {kk: self._value(vv) for kk, vv in v.items()}
        if isinstance(v, (list, tuple)):
            return [self._value(item) for item in v]
        return v


# ======================================================================
# StorageProvider (ABC)
# ======================================================================


class StorageProvider(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def disconnect(self) -> None: ...

    @abstractmethod
    async def save(self, collection: str, key: str, value: Any) -> None: ...

    @abstractmethod
    async def load(self, collection: str, key: str) -> Optional[Any]: ...

    @abstractmethod
    async def delete(self, collection: str, key: str) -> bool: ...

    @abstractmethod
    async def exists(self, collection: str, key: str) -> bool: ...

    @abstractmethod
    async def list_keys(self, collection: str) -> list[str]: ...

    @abstractmethod
    async def count(self, collection: str) -> int: ...

    @contextmanager
    @abstractmethod
    def transaction(self) -> Iterator[None]: ...

    @abstractmethod
    async def health_check(self) -> bool: ...


# ======================================================================
# SQLiteProvider
# ======================================================================


class SQLiteProvider(StorageProvider):
    def __init__(self, db_path: str = "atlas.db", serializer: Serializer | None = None) -> None:
        self._db_path = db_path
        self._serializer = serializer or Serializer()
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._logger = logging.getLogger(__name__)

    async def connect(self) -> None:
        if self._connection is not None:
            return
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._connection = sqlite3.connect(self._db_path, check_same_thread=False, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._create_tables()
        self._logger.info("Connected to SQLite at %s", self._db_path)

    async def disconnect(self) -> None:
        if self._connection:
            self._connection.close()
            self._connection = None
            self._logger.info("Disconnected from SQLite")

    def _create_tables(self) -> None:
        with self._lock:
            cur = self._connection.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS atlas_storage (
                    collection TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (collection, key)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS atlas_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS atlas_snapshots (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS atlas_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_storage_collection ON atlas_storage(collection)
            """)

    async def save(self, collection: str, key: str, value: Any) -> None:
        serialized = self._serializer.serialize(value)
        now = datetime.now().isoformat()
        with self._lock:
            self._connection.execute(
                """INSERT INTO atlas_storage (collection, key, value, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(collection, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (collection, key, serialized, now, now),
            )

    async def load(self, collection: str, key: str) -> Optional[Any]:
        with self._lock:
            cur = self._connection.execute(
                "SELECT value FROM atlas_storage WHERE collection=? AND key=?",
                (collection, key),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return self._serializer.deserialize(row["value"])

    async def delete(self, collection: str, key: str) -> bool:
        with self._lock:
            cur = self._connection.execute(
                "DELETE FROM atlas_storage WHERE collection=? AND key=?",
                (collection, key),
            )
            return cur.rowcount > 0

    async def exists(self, collection: str, key: str) -> bool:
        with self._lock:
            cur = self._connection.execute(
                "SELECT 1 FROM atlas_storage WHERE collection=? AND key=?",
                (collection, key),
            )
            return cur.fetchone() is not None

    async def list_keys(self, collection: str) -> list[str]:
        with self._lock:
            cur = self._connection.execute(
                "SELECT key FROM atlas_storage WHERE collection=? ORDER BY key",
                (collection,),
            )
            return [row["key"] for row in cur.fetchall()]

    async def count(self, collection: str) -> int:
        with self._lock:
            cur = self._connection.execute(
                "SELECT COUNT(*) as cnt FROM atlas_storage WHERE collection=?",
                (collection,),
            )
            row = cur.fetchone()
            return row["cnt"] if row else 0

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._connection is None:
            raise RuntimeError("Database not connected")
        with self._lock:
            self._connection.execute("BEGIN")
            try:
                yield
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise

    async def health_check(self) -> bool:
        if self._connection is None:
            return False
        try:
            with self._lock:
                self._connection.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def execute_raw(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._connection.execute(sql, params)
            return list(cur.fetchall())

    def execute_write(self, sql: str, params: tuple = ()) -> None:
        with self._lock:
            self._connection.execute(sql, params)


# ======================================================================
# Repository
# ======================================================================


class Repository:
    def __init__(self, storage: StorageProvider, collection: str) -> None:
        self._storage = storage
        self._collection = collection

    @property
    def collection(self) -> str:
        return self._collection

    async def create(self, key: str, value: Any) -> None:
        await self._storage.save(self._collection, key, value)

    async def read(self, key: str) -> Optional[Any]:
        return await self._storage.load(self._collection, key)

    async def update(self, key: str, value: Any) -> None:
        await self._storage.save(self._collection, key, value)

    async def delete(self, key: str) -> bool:
        return await self._storage.delete(self._collection, key)

    async def find(self, **filters: Any) -> list[tuple[str, Any]]:
        keys = await self._storage.list_keys(self._collection)
        result: list[tuple[str, Any]] = []
        for k in keys:
            val = await self._storage.load(self._collection, k)
            if val is not None and all(val.get(fkey) == fvalue for fkey, fvalue in filters.items()):
                result.append((k, val))
        return result

    async def count(self) -> int:
        return await self._storage.count(self._collection)

    async def exists(self, key: str) -> bool:
        return await self._storage.exists(self._collection, key)

    async def list_keys(self) -> list[str]:
        return await self._storage.list_keys(self._collection)


# ======================================================================
# PersistenceMetrics
# ======================================================================


@dataclass
class PersistenceMetrics:
    reads: int = 0
    writes: int = 0
    updates: int = 0
    deletes: int = 0
    transactions: int = 0
    rollback_count: int = 0
    snapshot_count: int = 0
    errors: int = 0
    latency: float = 0.0

    def record_read(self, duration: float = 0.0) -> None:
        self.reads += 1
        self.latency += duration

    def record_write(self, duration: float = 0.0) -> None:
        self.writes += 1
        self.latency += duration

    def record_update(self, duration: float = 0.0) -> None:
        self.updates += 1
        self.latency += duration

    def record_delete(self, duration: float = 0.0) -> None:
        self.deletes += 1
        self.latency += duration

    def record_transaction(self) -> None:
        self.transactions += 1

    def record_rollback(self) -> None:
        self.rollback_count += 1

    def record_snapshot(self) -> None:
        self.snapshot_count += 1

    def record_error(self) -> None:
        self.errors += 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "reads": self.reads,
            "writes": self.writes,
            "updates": self.updates,
            "deletes": self.deletes,
            "transactions": self.transactions,
            "rollback_count": self.rollback_count,
            "snapshot_count": self.snapshot_count,
            "errors": self.errors,
            "latency": self.latency,
        }

    def reset(self) -> None:
        self.reads = 0
        self.writes = 0
        self.updates = 0
        self.deletes = 0
        self.transactions = 0
        self.rollback_count = 0
        self.snapshot_count = 0
        self.errors = 0
        self.latency = 0.0


# ======================================================================
# PersistenceEventBridge
# ======================================================================


class PersistenceEventBridge:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(self, action: str, payload: dict[str, Any] | None = None) -> None:
        event = Event(
            source="persistence",
            category=EventCategory.PERSISTENCE,
            priority=EventPriority.NORMAL,
            payload={
                "action": action,
                "timestamp": datetime.now().isoformat(),
                **(payload or {}),
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish persistence event")

    async def database_connected(self) -> None:
        await self.publish("database_connected")

    async def database_disconnected(self) -> None:
        await self.publish("database_disconnected")

    async def data_saved(self, collection: str, key: str) -> None:
        await self.publish("data_saved", {"collection": collection, "key": key})

    async def data_loaded(self, collection: str, key: str) -> None:
        await self.publish("data_loaded", {"collection": collection, "key": key})

    async def data_deleted(self, collection: str, key: str) -> None:
        await self.publish("data_deleted", {"collection": collection, "key": key})

    async def transaction_started(self) -> None:
        await self.publish("transaction_started")

    async def transaction_committed(self) -> None:
        await self.publish("transaction_committed")

    async def transaction_rolled_back(self) -> None:
        await self.publish("transaction_rolled_back")

    async def snapshot_created(self, snapshot_id: str, name: str) -> None:
        await self.publish("snapshot_created", {"snapshot_id": snapshot_id, "name": name})

    async def snapshot_restored(self, snapshot_id: str) -> None:
        await self.publish("snapshot_restored", {"snapshot_id": snapshot_id})


# ======================================================================
# MigrationManager
# ======================================================================


@dataclass
class Migration:
    version: int
    name: str
    up: Callable[[SQLiteProvider], None]
    down: Callable[[SQLiteProvider], None]


class MigrationManager:
    def __init__(self, storage: SQLiteProvider) -> None:
        self._storage = storage
        self._migrations: dict[int, Migration] = {}
        self._logger = logging.getLogger(__name__)

    def register(self, version: int, name: str, up: Callable[[SQLiteProvider], None], down: Callable[[SQLiteProvider], None]) -> None:
        if version in self._migrations:
            raise ValueError(f"Migration version {version} already registered")
        self._migrations[version] = Migration(version=version, name=name, up=up, down=down)
        self._logger.debug("Registered migration v%d: %s", version, name)

    def current_version(self) -> int:
        rows = self._storage.execute_raw("SELECT MAX(version) as v FROM atlas_migrations")
        return rows[0]["v"] if rows and rows[0]["v"] else 0

    def pending_versions(self) -> list[int]:
        current = self.current_version()
        return sorted(v for v in self._migrations if v > current)

    async def upgrade(self, target_version: int | None = None) -> None:
        current = self.current_version()
        max_registered = max(self._migrations.keys()) if self._migrations else 0
        target = target_version if target_version is not None else max_registered
        for v in range(current + 1, target + 1):
            if v not in self._migrations:
                raise ValueError(f"No migration registered for version {v}")
        pending = sorted(v for v in self._migrations if v > current and v <= target)
        for version in pending:
            migration = self._migrations[version]
            try:
                self._storage.execute_write("BEGIN")
                migration.up(self._storage)
                now = datetime.now().isoformat()
                self._storage.execute_write(
                    "INSERT INTO atlas_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (version, migration.name, now),
                )
                self._storage.execute_write("COMMIT")
                self._logger.info("Applied migration v%d: %s", version, migration.name)
            except Exception:
                self._storage.execute_write("ROLLBACK")
                self._logger.exception("Failed to apply migration v%d", version)
                raise

    async def downgrade(self, target_version: int) -> None:
        current = self.current_version()
        for v in range(target_version + 1, current + 1):
            if v not in self._migrations:
                raise ValueError(f"No migration registered for version {v}")
        versions = sorted((v for v in self._migrations if v > target_version and v <= current), reverse=True)
        for version in versions:
            migration = self._migrations[version]
            try:
                self._storage.execute_write("BEGIN")
                migration.down(self._storage)
                self._storage.execute_write(
                    "DELETE FROM atlas_migrations WHERE version=?",
                    (version,),
                )
                self._storage.execute_write("COMMIT")
                self._logger.info("Reverted migration v%d: %s", version, migration.name)
            except Exception:
                self._storage.execute_write("ROLLBACK")
                self._logger.exception("Failed to revert migration v%d", version)
                raise

    @property
    def count(self) -> int:
        return len(self._migrations)

    def list_migrations(self) -> list[Migration]:
        return sorted(self._migrations.values(), key=lambda m: m.version)


# ======================================================================
# SnapshotManager
# ======================================================================


@dataclass
class SnapshotEntry:
    snapshot_id: str
    name: str
    data: dict[str, Any]
    created_at: datetime


class SnapshotManager:
    def __init__(self, storage: StorageProvider, serializer: Serializer) -> None:
        self._storage = storage
        self._serializer = serializer
        self._logger = logging.getLogger(__name__)

    async def create(self, name: str, data: dict[str, Any]) -> str:
        snapshot_id = str(uuid_module.uuid4())
        now = datetime.now()
        with self._storage.transaction():
            for collection in data:
                for key, value in data[collection].items():
                    await self._storage.save(collection, key, value)
            serialized = self._serializer.serialize(data)
            await self._storage.save("atlas_snapshots_internal", snapshot_id, {
                "name": name,
                "data": serialized,
                "created_at": now.isoformat(),
            })
        self._logger.info("Created snapshot %s: %s", snapshot_id, name)
        return snapshot_id

    async def restore(self, snapshot_id: str) -> dict[str, Any] | None:
        entry = await self._storage.load("atlas_snapshots_internal", snapshot_id)
        if entry is None:
            return None
        data = self._serializer.deserialize(entry["data"])
        with self._storage.transaction():
            for collection, items in data.items():
                for key, value in items.items():
                    await self._storage.save(collection, key, value)
        self._logger.info("Restored snapshot %s", snapshot_id)
        return data

    async def list_snapshots(self) -> list[dict[str, Any]]:
        keys = await self._storage.list_keys("atlas_snapshots_internal")
        result: list[dict[str, Any]] = []
        for key in keys:
            entry = await self._storage.load("atlas_snapshots_internal", key)
            if entry:
                result.append({
                    "snapshot_id": key,
                    "name": entry["name"],
                    "created_at": entry["created_at"],
                })
        return sorted(result, key=lambda x: x["created_at"], reverse=True)

    async def delete(self, snapshot_id: str) -> bool:
        result = await self._storage.delete("atlas_snapshots_internal", snapshot_id)
        if result:
            self._logger.info("Deleted snapshot %s", snapshot_id)
        return result

    async def count(self) -> int:
        return await self._storage.count("atlas_snapshots_internal")


# ======================================================================
# PersistenceManager (IService)
# ======================================================================


class PersistenceManager(IService):
    def __init__(self, event_bus: EventBus, db_path: str = "atlas.db") -> None:
        self._event_bus = event_bus
        self._db_path = db_path
        self._serializer = Serializer()
        self._storage = SQLiteProvider(db_path, self._serializer)
        self._repositories: dict[str, Repository] = {}
        self._migration_manager = MigrationManager(self._storage)
        self._snapshot_manager = SnapshotManager(self._storage, self._serializer)
        self._event_bridge = PersistenceEventBridge(event_bus)
        self._metrics = PersistenceMetrics()
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return "persistence_manager"

    @property
    def storage(self) -> SQLiteProvider:
        return self._storage

    @property
    def serializer(self) -> Serializer:
        return self._serializer

    @property
    def metrics(self) -> PersistenceMetrics:
        return self._metrics

    @property
    def event_bridge(self) -> PersistenceEventBridge:
        return self._event_bridge

    @property
    def migration_manager(self) -> MigrationManager:
        return self._migration_manager

    @property
    def snapshot_manager(self) -> SnapshotManager:
        return self._snapshot_manager

    async def initialize(self) -> None:
        await super().initialize()
        self._state = ServiceState.INITIALIZED
        self._logger.info("Persistence Manager initialized")

    async def start(self) -> None:
        await super().start()
        try:
            await self._storage.connect()
            await self._event_bridge.database_connected()
        except Exception:
            self._logger.exception("Failed to connect to database")
            raise
        self._state = ServiceState.RUNNING
        self._logger.info("Persistence Manager started")

    async def stop(self) -> None:
        await super().stop()
        await self._storage.disconnect()
        await self._event_bridge.database_disconnected()
        self._state = ServiceState.STOPPED
        self._logger.info("Persistence Manager stopped")

    async def health_check(self) -> ServiceHealth:
        db_healthy = await self._storage.health_check()
        return ServiceHealth(
            healthy=db_healthy and self._state == ServiceState.RUNNING,
            state=self._state,
            message=f"PersistenceManager db={'connected' if db_healthy else 'disconnected'}",
            metadata={
                "db_connected": db_healthy,
                "db_path": self._db_path,
                "repositories": list(self._repositories.keys()),
                "metrics": self._metrics.snapshot(),
            },
        )

    def register_repository(self, name: str, repository: Repository) -> None:
        if name in self._repositories:
            raise ValueError(f"Repository already registered: {name}")
        self._repositories[name] = repository
        self._logger.debug("Registered repository: %s", name)

    def repository(self, name: str) -> Optional[Repository]:
        return self._repositories.get(name)

    def create_repository(self, name: str, collection: str | None = None) -> Repository:
        if name in self._repositories:
            raise ValueError(f"Repository already registered: {name}")
        repo = Repository(self._storage, collection or name)
        self._repositories[name] = repo
        return repo

    async def save(self, collection: str, key: str, value: Any) -> None:
        start = time.time()
        try:
            await self._storage.save(collection, key, value)
            self._metrics.record_write(time.time() - start)
            await self._event_bridge.data_saved(collection, key)
        except Exception:
            self._metrics.record_error()
            raise

    async def load(self, collection: str, key: str) -> Optional[Any]:
        start = time.time()
        try:
            result = await self._storage.load(collection, key)
            self._metrics.record_read(time.time() - start)
            if result is not None:
                await self._event_bridge.data_loaded(collection, key)
            return result
        except Exception:
            self._metrics.record_error()
            raise

    async def delete(self, collection: str, key: str) -> bool:
        start = time.time()
        try:
            result = await self._storage.delete(collection, key)
            self._metrics.record_delete(time.time() - start)
            if result:
                await self._event_bridge.data_deleted(collection, key)
            return result
        except Exception:
            self._metrics.record_error()
            raise

    async def backup(self, path: str) -> None:
        """Create a copy of the current database."""
        if hasattr(self._storage, "_connection") and self._storage._connection:
            self._storage.execute_write("VACUUM")
            import shutil
            shutil.copy2(self._db_path, path)
            self._logger.info("Backed up database to %s", path)

    async def restore_backup(self, path: str) -> None:
        """Restore from a backup file."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Backup file not found: {path}")
        old_path = self._db_path + ".backup"
        if os.path.exists(old_path):
            os.remove(old_path)
        if os.path.exists(self._db_path):
            os.rename(self._db_path, old_path)
        import shutil
        shutil.copy2(path, self._db_path)
        await self._storage.connect()
        self._logger.info("Restored database from %s", path)

    async def execute_transaction(self, operations: list[Callable[[], Any]]) -> None:
        self._metrics.record_transaction()
        await self._event_bridge.transaction_started()
        with self._storage.transaction():
            try:
                for op in operations:
                    op()
                await self._event_bridge.transaction_committed()
            except Exception:
                self._metrics.record_rollback()
                await self._event_bridge.transaction_rolled_back()
                raise
