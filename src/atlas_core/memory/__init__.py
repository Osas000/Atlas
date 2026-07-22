"""Memory Engine — Atlas's long-term intelligence.

Captures, organises, retrieves, and improves knowledge across five layers:
Working → Session → Project → Long-Term → Archive.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Enums
# ======================================================================


class MemoryCategory(Enum):
    PROFESSIONAL = "professional"
    LEARNING = "learning"
    CLIENT = "client"
    PLATFORM = "platform"
    FINANCIAL = "financial"
    CAREER = "career"
    PROJECT = "project"
    TECHNICAL = "technical"
    PREFERENCES = "preferences"
    OPERATIONAL = "operational"


class MemoryImportance(Enum):
    VERY_HIGH = 5
    HIGH = 4
    MEDIUM = 3
    LOW = 2
    VERY_LOW = 1


# ======================================================================
# Memory Record
# ======================================================================


class MemoryRecord(BaseModel):
    memory_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    category: MemoryCategory = MemoryCategory.PROFESSIONAL
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    source: str = ""
    confidence: float = 1.0
    importance: MemoryImportance = MemoryImportance.MEDIUM
    related_projects: list[str] = Field(default_factory=list)
    related_clients: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    version: int = 1
    content: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ======================================================================
# MemoryStore — persistence abstraction
# ======================================================================


class MemoryStore(ABC):
    """Storage-agnostic interface for memory persistence.

    Implementations may use dicts, SQLite, Postgres, files, etc.
    """

    @abstractmethod
    async def create(self, record: MemoryRecord) -> MemoryRecord:
        ...

    @abstractmethod
    async def get(self, memory_id: str) -> MemoryRecord | None:
        ...

    @abstractmethod
    async def update(self, record: MemoryRecord) -> MemoryRecord:
        ...

    @abstractmethod
    async def delete(self, memory_id: str) -> None:
        ...

    @abstractmethod
    async def search(
        self,
        query: str | None = None,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        importance: MemoryImportance | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        ...

    @abstractmethod
    async def list(
        self,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        ...

    @abstractmethod
    async def count(self) -> int:
        ...


# ======================================================================
# InMemoryStore — default dict-backed implementation
# ======================================================================


class InMemoryStore(MemoryStore):
    """Default in-memory implementation of MemoryStore."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}

    async def create(self, record: MemoryRecord) -> MemoryRecord:
        self._records[record.memory_id] = record.model_copy()
        return record

    async def get(self, memory_id: str) -> MemoryRecord | None:
        record = self._records.get(memory_id)
        return record.model_copy() if record else None

    async def update(self, record: MemoryRecord) -> MemoryRecord:
        self._records[record.memory_id] = record.model_copy()
        return record

    async def delete(self, memory_id: str) -> None:
        self._records.pop(memory_id, None)

    async def search(
        self,
        query: str | None = None,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        importance: MemoryImportance | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        q = query.lower() if query else None
        tag_set = set(tags) if tags else None

        matched = []
        for record in self._records.values():
            if category is not None and record.category != category:
                continue
            if importance is not None and record.importance != importance:
                continue
            if since is not None and record.created_at < since:
                continue
            if until is not None and record.created_at > until:
                continue
            if tag_set and not tag_set.intersection(record.tags):
                continue
            if q:
                haystack = f"{record.title} {' '.join(record.search_keywords)} {' '.join(record.tags)}".lower()
                if q not in haystack:
                    continue
            matched.append(record.model_copy())

        matched.sort(key=lambda r: (r.importance.value, r.created_at), reverse=True)
        return matched[offset: offset + limit]

    async def list(
        self,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        return await self.search(category=category, tags=tags, limit=limit, offset=offset)

    async def count(self) -> int:
        return len(self._records)


# ======================================================================
# Memory Layer — wraps a store + event bus for a single memory tier
# ======================================================================


def _publish_memory_event(
    event_bus: EventBus,
    action: str,
    record: MemoryRecord,
    source: str = "memory_engine",
) -> None:
    """Fire-and-forget an event about a memory mutation."""
    try:
        asyncio.create_task(event_bus.publish(Event(
            source=source,
            category=EventCategory.PROJECT,
            priority=EventPriority.NORMAL,
            payload={
                "action": action,
                "memory_id": record.memory_id,
                "title": record.title,
                "category": record.category.value,
            },
        )))
    except Exception:
        pass


class MemoryLayer:
    """Base wrapper providing CRUD + search over a MemoryStore with event publishing."""

    def __init__(self, store: MemoryStore, event_bus: EventBus, layer_name: str) -> None:
        self._store = store
        self._event_bus = event_bus
        self._layer_name = layer_name
        self._logger = logging.getLogger(__name__)

    async def create(self, record: MemoryRecord) -> MemoryRecord:
        result = await self._store.create(record)
        _publish_memory_event(self._event_bus, "created", result, self._layer_name)
        self._logger.debug("Created memory %s in %s", result.memory_id, self._layer_name)
        return result

    async def get(self, memory_id: str) -> MemoryRecord | None:
        return await self._store.get(memory_id)

    async def update(self, record: MemoryRecord) -> MemoryRecord:
        existing = await self._store.get(record.memory_id)
        if existing is None:
            raise ValueError(f"Memory not found: {record.memory_id}")
        updated = record.model_copy(update={"version": existing.version + 1, "updated_at": datetime.now()})
        result = await self._store.update(updated)
        _publish_memory_event(self._event_bus, "updated", result, self._layer_name)
        return result

    async def delete(self, memory_id: str) -> None:
        record = await self._store.get(memory_id)
        if record is None:
            return
        await self._store.delete(memory_id)
        _publish_memory_event(self._event_bus, "deleted", record, self._layer_name)

    async def search(
        self,
        query: str | None = None,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        importance: MemoryImportance | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        return await self._store.search(
            query=query, category=category, tags=tags,
            importance=importance, since=since, until=until,
            limit=limit, offset=offset,
        )

    async def list(
        self,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        return await self._store.list(category=category, tags=tags, limit=limit, offset=offset)

    async def count(self) -> int:
        return await self._store.count()

    async def clear(self) -> None:
        """Remove all records (layer-specific behaviour)."""
        all_records = await self._store.list(limit=10000)
        for r in all_records:
            await self._store.delete(r.memory_id)
        self._logger.info("Cleared %s", self._layer_name)

    @property
    def name(self) -> str:
        return self._layer_name


# ======================================================================
# Concrete Memory Layers
# ======================================================================


class WorkingMemory(MemoryLayer):
    """Temporary, fast, auto-cleared after task completion."""

    def __init__(self, store: MemoryStore, event_bus: EventBus) -> None:
        super().__init__(store, event_bus, "working_memory")


class SessionMemory(MemoryLayer):
    """Current session scope — auto-cleared when session ends."""

    def __init__(self, store: MemoryStore, event_bus: EventBus) -> None:
        super().__init__(store, event_bus, "session_memory")


class ProjectMemory(MemoryLayer):
    """Project-scoped memory — persists until archived."""

    def __init__(self, store: MemoryStore, event_bus: EventBus) -> None:
        super().__init__(store, event_bus, "project_memory")


class LongTermMemory(MemoryLayer):
    """Permanent professional knowledge — never auto-deleted."""

    def __init__(self, store: MemoryStore, event_bus: EventBus) -> None:
        super().__init__(store, event_bus, "long_term_memory")


class ArchiveMemory(MemoryLayer):
    """Historical storage — read-heavy, user-approved deletion only."""

    def __init__(self, store: MemoryStore, event_bus: EventBus) -> None:
        super().__init__(store, event_bus, "archive_memory")


# ======================================================================
# MemoryManager — IService orchestrator
# ======================================================================


class MemoryManager(IService):
    """Orchestrates all five memory layers with Event Bus integration.

    Provides a unified entry point for storing and retrieving memories
    across the entire memory hierarchy.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        self._working = WorkingMemory(InMemoryStore(), event_bus)
        self._session = SessionMemory(InMemoryStore(), event_bus)
        self._project = ProjectMemory(InMemoryStore(), event_bus)
        self._long_term = LongTermMemory(InMemoryStore(), event_bus)
        self._archive = ArchiveMemory(InMemoryStore(), event_bus)

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "memory_engine"

    async def initialize(self) -> None:
        self._logger.info("Memory Engine initializing")

    async def start(self) -> None:
        self._logger.info("Memory Engine started")

    async def stop(self) -> None:
        self._logger.info("Memory Engine stopped")

    async def health_check(self) -> ServiceHealth:
        total = sum(
            await asyncio.gather(
                self._working.count(),
                self._session.count(),
                self._project.count(),
                self._long_term.count(),
                self._archive.count(),
            )
        )
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={"total_memories": total},
        )

    # ------------------------------------------------------------------
    # Layer accessors
    # ------------------------------------------------------------------

    @property
    def working(self) -> WorkingMemory:
        return self._working

    @property
    def session(self) -> SessionMemory:
        return self._session

    @property
    def project(self) -> ProjectMemory:
        return self._project

    @property
    def long_term(self) -> LongTermMemory:
        return self._long_term

    @property
    def archive(self) -> ArchiveMemory:
        return self._archive

    # ------------------------------------------------------------------
    # Unified search across layers (retrieval strategy order)
    # ------------------------------------------------------------------

    async def search_all(
        self,
        query: str | None = None,
        category: MemoryCategory | None = None,
        tags: list[str] | None = None,
        importance: MemoryImportance | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        """Search every layer in retrieval order: Working → Session → Project → LTM → Archive."""
        results: list[MemoryRecord] = []
        for layer in (self._working, self._session, self._project, self._long_term, self._archive):
            batch = await layer.search(
                query=query, category=category, tags=tags,
                importance=importance, since=since, until=until,
                limit=limit - len(results), offset=0,
            )
            results.extend(batch)
            if len(results) >= limit:
                break
        return results[:limit]

    async def promote(self, memory_id: str, target_layer: str = "long_term") -> MemoryRecord | None:
        """Move a memory from its current layer to a higher layer."""
        target = getattr(self, target_layer, None)
        if target is None:
            return None
        for source in (self._working, self._session, self._project, self._long_term, self._archive):
            record = await source.get(memory_id)
            if record is not None:
                if source is target:
                    return record
                await source.delete(memory_id)
                return await target.create(record)
        return None
