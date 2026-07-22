"""Knowledge Engine — structured knowledge repository for Atlas.

Stores facts, documents, references, and relationships.
Records are immutable — updates create new versions.
No AI reasoning — storage and retrieval only.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from atlas_core.context import AtlasContext
from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Enums
# ======================================================================


class KnowledgeType(Enum):
    FACT = "fact"
    DOCUMENT = "document"
    REFERENCE = "reference"
    CONCEPT = "concept"
    TERM = "term"
    DEFINITION = "definition"
    CODE_SNIPPET = "code_snippet"
    NOTE = "note"


class KnowledgeStatus(Enum):
    DRAFT = auto()
    PUBLISHED = auto()
    ARCHIVED = auto()
    DEPRECATED = auto()


class KnowledgeImportance(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class RelationshipType(Enum):
    RELATES_TO = "relates_to"
    DEPENDS_ON = "depends_on"
    REFERENCES = "references"
    EXTENDS = "extends"
    CONTRADICTS = "contradicts"
    DERIVED_FROM = "derived_from"


# ======================================================================
# Core data classes
# ======================================================================


@dataclass
class KnowledgeRecord:
    """An immutable knowledge record.

    Once created, fields should not be mutated directly.
    Updates create a new version via the KnowledgeStore.
    """

    record_id: str = field(default_factory=lambda: str(uuid4()))
    collection_id: str = ""
    type: KnowledgeType = KnowledgeType.NOTE
    status: KnowledgeStatus = KnowledgeStatus.DRAFT
    importance: KnowledgeImportance = KnowledgeImportance.MEDIUM
    title: str = ""
    content: str = ""
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = ""
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeCollection:
    """A named group of knowledge records."""

    collection_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    record_count: int = 0


@dataclass
class Citation:
    """A citation linking a record to an external source."""

    citation_id: str = field(default_factory=lambda: str(uuid4()))
    record_id: str = ""
    source_title: str = ""
    source_url: str = ""
    source_author: str = ""
    source_date: str = ""
    excerpt: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Relationship:
    """A directed relationship between two knowledge records."""

    relationship_id: str = field(default_factory=lambda: str(uuid4()))
    source_record_id: str = ""
    target_record_id: str = ""
    relationship_type: RelationshipType = RelationshipType.RELATES_TO
    weight: float = 1.0
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class VersionEntry:
    """A single version entry in a record's version history."""

    version: int = 1
    record_id: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)
    change_description: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class SearchResult:
    """A single search result with relevance scoring."""

    record: KnowledgeRecord | None = None
    score: float = 0.0
    matched_field: str = ""
    matched_text: str = ""
    collection_name: str = ""


@dataclass
class KnowledgeMetrics:
    """Usage and content metrics for the Knowledge Engine."""

    total_records: int = 0
    total_collections: int = 0
    total_citations: int = 0
    total_relationships: int = 0
    total_versions: int = 0
    searches_performed: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_deleted: int = 0
    imports_performed: int = 0
    exports_performed: int = 0
    errors: int = 0

    def type_counts(self, records: list[KnowledgeRecord]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for r in records:
            counts[r.type.value] += 1
        return dict(counts)

    def status_counts(self, records: list[KnowledgeRecord]) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for r in records:
            counts[r.status.name.lower()] += 1
        return dict(counts)


# ======================================================================
# KnowledgeStore
# ======================================================================


class KnowledgeStore:
    """In-memory storage for knowledge records and collections."""

    def __init__(self) -> None:
        self._records: dict[str, KnowledgeRecord] = {}
        self._collections: dict[str, KnowledgeCollection] = {}
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------

    def add_record(self, record: KnowledgeRecord) -> KnowledgeRecord:
        self._records[record.record_id] = record
        self._logger.debug("Added record %s (%s)", record.record_id, record.title)
        return record

    def get_record(self, record_id: str) -> KnowledgeRecord | None:
        return self._records.get(record_id)

    def update_record(self, record_id: str, **updates: Any) -> KnowledgeRecord | None:
        existing = self._records.get(record_id)
        if existing is None:
            return None
        for key, value in updates.items():
            if hasattr(existing, key) and key not in ("record_id", "created_at"):
                setattr(existing, key, value)
        existing.updated_at = datetime.now()
        return existing

    def delete_record(self, record_id: str) -> bool:
        if record_id in self._records:
            del self._records[record_id]
            return True
        return False

    def list_records(
        self,
        collection_id: str | None = None,
        type_filter: KnowledgeType | None = None,
        status_filter: KnowledgeStatus | None = None,
        tag_filter: str | None = None,
        limit: int = 100,
    ) -> list[KnowledgeRecord]:
        results: list[KnowledgeRecord] = []
        for r in self._records.values():
            if collection_id is not None and r.collection_id != collection_id:
                continue
            if type_filter is not None and r.type != type_filter:
                continue
            if status_filter is not None and r.status != status_filter:
                continue
            if tag_filter is not None and tag_filter not in r.tags:
                continue
            results.append(r)
            if len(results) >= limit:
                break
        return results

    @property
    def record_count(self) -> int:
        return len(self._records)

    @property
    def all_records(self) -> list[KnowledgeRecord]:
        return list(self._records.values())

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def add_collection(self, collection: KnowledgeCollection) -> KnowledgeCollection:
        self._collections[collection.collection_id] = collection
        self._logger.debug("Added collection %s (%s)", collection.collection_id, collection.name)
        return collection

    def get_collection(self, collection_id: str) -> KnowledgeCollection | None:
        return self._collections.get(collection_id)

    def update_collection(self, collection_id: str, **updates: Any) -> KnowledgeCollection | None:
        existing = self._collections.get(collection_id)
        if existing is None:
            return None
        for key, value in updates.items():
            if hasattr(existing, key) and key not in ("collection_id", "created_at"):
                setattr(existing, key, value)
        existing.updated_at = datetime.now()
        existing.record_count = sum(
            1 for r in self._records.values() if r.collection_id == collection_id
        )
        return existing

    def delete_collection(self, collection_id: str) -> bool:
        if collection_id in self._collections:
            del self._collections[collection_id]
            return True
        return False

    def list_collections(self) -> list[KnowledgeCollection]:
        return list(self._collections.values())

    @property
    def collection_count(self) -> int:
        return len(self._collections)

    def clear(self) -> None:
        self._records.clear()
        self._collections.clear()


# ======================================================================
# KnowledgeIndexer
# ======================================================================


class KnowledgeIndexer:
    """Builds and maintains a searchable index over knowledge records."""

    def __init__(self) -> None:
        self._word_index: dict[str, set[str]] = defaultdict(set)
        self._tag_index: dict[str, set[str]] = defaultdict(set)
        self._type_index: dict[KnowledgeType, set[str]] = defaultdict(set)
        self._logger = logging.getLogger(__name__)

    def index_record(self, record: KnowledgeRecord) -> None:
        self._index_text(record.record_id, record.title)
        self._index_text(record.record_id, record.content)
        self._index_text(record.record_id, record.summary)
        for tag in record.tags:
            self._tag_index[tag.lower()].add(record.record_id)
        self._type_index[record.type].add(record.record_id)

    def _index_text(self, record_id: str, text: str) -> None:
        for word in text.lower().split():
            word = word.strip(".,!?;:\"'()[]{}")
            if len(word) > 2:
                self._word_index[word].add(record_id)

    def remove_record(self, record_id: str) -> None:
        for word_set in self._word_index.values():
            word_set.discard(record_id)
        for tag_set in self._tag_index.values():
            tag_set.discard(record_id)
        for type_set in self._type_index.values():
            type_set.discard(record_id)

    def reindex(self, records: list[KnowledgeRecord]) -> None:
        self._word_index.clear()
        self._tag_index.clear()
        self._type_index.clear()
        for r in records:
            self.index_record(r)

    @property
    def word_count(self) -> int:
        return len(self._word_index)

    @property
    def tag_count(self) -> int:
        return len(self._tag_index)


# ======================================================================
# KnowledgeSearch
# ======================================================================


class KnowledgeSearch:
    """Full-text search across knowledge records with filtering."""

    def __init__(self, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        self._store = store
        self._indexer = indexer
        self._logger = logging.getLogger(__name__)

    def search(
        self,
        query: str,
        collection_id: str | None = None,
        type_filter: KnowledgeType | None = None,
        status_filter: KnowledgeStatus | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Full-text search with optional filters."""
        if not query.strip():
            return []

        query_words = [w.lower().strip(".,!?;:\"'()[]{}") for w in query.split() if len(w) > 2]
        if not query_words:
            return []

        candidate_ids: set[str] | None = None
        for word in query_words:
            matched = self._indexer._word_index.get(word, set())
            if candidate_ids is None:
                candidate_ids = set(matched)
            else:
                candidate_ids &= matched
            if not candidate_ids:
                break

        if not candidate_ids:
            return []

        results: list[SearchResult] = []
        for rid in candidate_ids:
            record = self._store.get_record(rid)
            if record is None:
                continue

            if collection_id is not None and record.collection_id != collection_id:
                continue
            if type_filter is not None and record.type != type_filter:
                continue
            if status_filter is not None and record.status != status_filter:
                continue
            if tags:
                if not any(t in record.tags for t in tags):
                    continue

            score = self._calculate_score(record, query_words)
            matched_field, matched_text = self._find_match(record, query_words)
            results.append(SearchResult(
                record=record,
                score=score,
                matched_field=matched_field,
                matched_text=matched_text,
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _calculate_score(self, record: KnowledgeRecord, query_words: list[str]) -> float:
        score = 0.0
        text = (record.title + " " + record.content + " " + record.summary).lower()
        for word in query_words:
            count = text.count(word)
            if count > 0:
                score += count * 10 if word in record.title.lower() else count
            if word in record.tags:
                score += 20
            if word in record.type.value:
                score += 5
        return score

    def _find_match(self, record: KnowledgeRecord, query_words: list[str]) -> tuple[str, str]:
        for word in query_words:
            if word in record.title.lower():
                return ("title", record.title)
            if word in record.summary.lower():
                return ("summary", record.summary)
            if word in record.content.lower():
                idx = record.content.lower().find(word)
                start = max(0, idx - 40)
                end = min(len(record.content), idx + 60)
                snippet = record.content[start:end]
                return ("content", snippet)
        return ("", "")


# ======================================================================
# CitationManager
# ======================================================================


class CitationManager:
    """Manages citations attached to knowledge records."""

    def __init__(self) -> None:
        self._citations: dict[str, Citation] = {}
        self._record_citations: dict[str, list[str]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)

    def add_citation(self, citation: Citation) -> Citation:
        self._citations[citation.citation_id] = citation
        self._record_citations[citation.record_id].append(citation.citation_id)
        self._logger.debug("Added citation %s to record %s", citation.citation_id, citation.record_id)
        return citation

    def get_citation(self, citation_id: str) -> Citation | None:
        return self._citations.get(citation_id)

    def remove_citation(self, citation_id: str) -> bool:
        citation = self._citations.get(citation_id)
        if citation is None:
            return False
        record_citations = self._record_citations.get(citation.record_id, [])
        if citation_id in record_citations:
            record_citations.remove(citation_id)
        del self._citations[citation_id]
        return True

    def list_citations(self, record_id: str) -> list[Citation]:
        citation_ids = self._record_citations.get(record_id, [])
        return [self._citations[cid] for cid in citation_ids if cid in self._citations]

    def count_citations(self, record_id: str) -> int:
        return len(self._record_citations.get(record_id, []))

    @property
    def total_citations(self) -> int:
        return len(self._citations)

    def clear(self) -> None:
        self._citations.clear()
        self._record_citations.clear()


# ======================================================================
# VersionManager
# ======================================================================


class VersionManager:
    """Manages version history for knowledge records."""

    def __init__(self) -> None:
        self._versions: dict[str, list[VersionEntry]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)

    def create_version(self, record: KnowledgeRecord, change_description: str = "") -> VersionEntry:
        snapshot = {
            "record_id": record.record_id,
            "collection_id": record.collection_id,
            "type": record.type.value,
            "status": record.status.name,
            "title": record.title,
            "content": record.content,
            "summary": record.summary,
            "tags": list(record.tags),
            "source": record.source,
            "version": record.version,
            "metadata": dict(record.metadata),
        }
        entry = VersionEntry(
            version=record.version,
            record_id=record.record_id,
            snapshot=snapshot,
            change_description=change_description,
        )
        self._versions[record.record_id].append(entry)
        return entry

    def get_history(self, record_id: str) -> list[VersionEntry]:
        return list(self._versions.get(record_id, []))

    def get_version(self, record_id: str, version: int) -> VersionEntry | None:
        for entry in self._versions.get(record_id, []):
            if entry.version == version:
                return entry
        return None

    def restore(self, record_id: str, version: int) -> dict[str, Any] | None:
        entry = self.get_version(record_id, version)
        if entry is None:
            return None
        return dict(entry.snapshot)

    @property
    def total_versions(self) -> int:
        return sum(len(v) for v in self._versions.values())

    def clear(self) -> None:
        self._versions.clear()


# ======================================================================
# RelationshipManager
# ======================================================================


class RelationshipManager:
    """Manages relationships between knowledge records."""

    def __init__(self) -> None:
        self._relationships: dict[str, Relationship] = {}
        self._outgoing: dict[str, list[str]] = defaultdict(list)
        self._incoming: dict[str, list[str]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)

    def add_relationship(self, relationship: Relationship) -> Relationship:
        self._relationships[relationship.relationship_id] = relationship
        self._outgoing[relationship.source_record_id].append(relationship.relationship_id)
        self._incoming[relationship.target_record_id].append(relationship.relationship_id)
        self._logger.debug(
            "Added relationship %s: %s → %s",
            relationship.relationship_type.value,
            relationship.source_record_id,
            relationship.target_record_id,
        )
        return relationship

    def remove_relationship(self, relationship_id: str) -> bool:
        rel = self._relationships.get(relationship_id)
        if rel is None:
            return False
        outgoing = self._outgoing.get(rel.source_record_id, [])
        if relationship_id in outgoing:
            outgoing.remove(relationship_id)
        incoming = self._incoming.get(rel.target_record_id, [])
        if relationship_id in incoming:
            incoming.remove(relationship_id)
        del self._relationships[relationship_id]
        return True

    def get_relationships(self, record_id: str) -> list[Relationship]:
        rel_ids = set(self._outgoing.get(record_id, []) + self._incoming.get(record_id, []))
        return [self._relationships[rid] for rid in rel_ids if rid in self._relationships]

    def get_outgoing(self, record_id: str) -> list[Relationship]:
        return [self._relationships[rid] for rid in self._outgoing.get(record_id, []) if rid in self._relationships]

    def get_incoming(self, record_id: str) -> list[Relationship]:
        return [self._relationships[rid] for rid in self._incoming.get(record_id, []) if rid in self._relationships]

    def query_relationships(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        rel_type: RelationshipType | None = None,
    ) -> list[Relationship]:
        results: list[Relationship] = []
        for rel in self._relationships.values():
            if source_id is not None and rel.source_record_id != source_id:
                continue
            if target_id is not None and rel.target_record_id != target_id:
                continue
            if rel_type is not None and rel.relationship_type != rel_type:
                continue
            results.append(rel)
        return results

    @property
    def total_relationships(self) -> int:
        return len(self._relationships)

    def clear(self) -> None:
        self._relationships.clear()
        self._outgoing.clear()
        self._incoming.clear()


# ======================================================================
# ImportExportManager
# ======================================================================


class ImportExportManager:
    """Import and export knowledge records and collections."""

    def __init__(self, store: KnowledgeStore) -> None:
        self._store = store
        self._logger = logging.getLogger(__name__)

    def export_collection(self, collection_id: str) -> dict[str, Any] | None:
        collection = self._store.get_collection(collection_id)
        if collection is None:
            return None
        records = self._store.list_records(collection_id=collection_id)
        return {
            "collection": {
                "name": collection.name,
                "description": collection.description,
                "tags": collection.tags,
            },
            "records": [
                {
                    "title": r.title,
                    "type": r.type.value,
                    "status": r.status.name,
                    "content": r.content,
                    "summary": r.summary,
                    "tags": r.tags,
                    "source": r.source,
                    "metadata": r.metadata,
                }
                for r in records
            ],
        }

    def export_all(self) -> list[dict[str, Any]]:
        collections = self._store.list_collections()
        return [self.export_collection(c.collection_id) for c in collections if self.export_collection(c.collection_id) is not None]

    def import_records(
        self,
        data: list[dict[str, Any]],
        collection_id: str,
    ) -> int:
        count = 0
        for item in data:
            try:
                record = KnowledgeRecord(
                    collection_id=collection_id,
                    type=KnowledgeType(item.get("type", "note")),
                    status=KnowledgeStatus[item.get("status", "DRAFT").upper()],
                    title=item.get("title", ""),
                    content=item.get("content", ""),
                    summary=item.get("summary", ""),
                    tags=item.get("tags", []),
                    source=item.get("source", ""),
                    metadata=item.get("metadata", {}),
                )
                self._store.add_record(record)
                count += 1
            except Exception:
                self._logger.exception("Failed to import record")
        self._logger.info("Imported %d records into collection %s", count, collection_id)
        return count

    def to_json(self, collection_id: str | None = None) -> str:
        data = self.export_collection(collection_id) if collection_id else {"collections": self.export_all()}
        return json.dumps(data, default=str, indent=2)

    def from_json(self, json_str: str, collection_id: str) -> int:
        data = json.loads(json_str)
        records = data if isinstance(data, list) else data.get("records", [])
        return self.import_records(records, collection_id)


# ======================================================================
# KnowledgeEngine — IService
# ======================================================================


class KnowledgeEngine(IService):
    """Central knowledge repository for Atlas.

    Stores facts, documents, references, and relationships.
    Records are immutable — updates create new versions.
    No AI reasoning — storage and retrieval only.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        self._store = KnowledgeStore()
        self._indexer = KnowledgeIndexer()
        self._search = KnowledgeSearch(self._store, self._indexer)
        self._citation_manager = CitationManager()
        self._version_manager = VersionManager()
        self._relationship_manager = RelationshipManager()
        self._import_export = ImportExportManager(self._store)
        self._metrics = KnowledgeMetrics()

        self._running = False

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "knowledge_engine"

    async def initialize(self) -> None:
        await super().initialize()
        self._logger.info("Knowledge Engine initializing")

    async def start(self) -> None:
        await super().start()
        self._running = True
        self._logger.info("Knowledge Engine started")

    async def stop(self) -> None:
        await super().stop()
        self._running = False
        self._logger.info("Knowledge Engine stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "total_records": self._metrics.total_records,
                "total_collections": self._metrics.total_collections,
                "total_citations": self._metrics.total_citations,
                "total_relationships": self._metrics.total_relationships,
                "searches_performed": self._metrics.searches_performed,
                "index_size": self._indexer.word_count,
            },
        )

    # ------------------------------------------------------------------
    # Context integration
    # ------------------------------------------------------------------

    def set_context(self, context: AtlasContext) -> None:
        pass  # Knowledge Engine does not require runtime permissions

    # ------------------------------------------------------------------
    # Record operations
    # ------------------------------------------------------------------

    async def create_record(
        self,
        collection_id: str = "",
        title: str = "",
        content: str = "",
        record_type: KnowledgeType = KnowledgeType.NOTE,
        status: KnowledgeStatus = KnowledgeStatus.DRAFT,
        importance: KnowledgeImportance = KnowledgeImportance.MEDIUM,
        summary: str = "",
        tags: list[str] | None = None,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> KnowledgeRecord:
        record = KnowledgeRecord(
            collection_id=collection_id,
            type=record_type,
            status=status,
            importance=importance,
            title=title,
            content=content,
            summary=summary,
            tags=tags or [],
            source=source,
            metadata=metadata or {},
        )
        self._store.add_record(record)
        self._indexer.index_record(record)
        self._version_manager.create_version(record, "Initial version")
        self._metrics.records_created += 1
        self._metrics.total_records = self._store.record_count
        self._metrics.total_versions = self._version_manager.total_versions

        if collection_id:
            self._store.update_collection(collection_id)

        await self._publish_event("record_created", {
            "record_id": record.record_id,
            "collection_id": collection_id,
            "title": title,
        })
        return record

    async def get_record(self, record_id: str) -> KnowledgeRecord | None:
        return self._store.get_record(record_id)

    async def update_record(
        self,
        record_id: str,
        change_description: str = "",
        **updates: Any,
    ) -> KnowledgeRecord | None:
        existing = self._store.get_record(record_id)
        if existing is None:
            return None

        self._version_manager.create_version(existing, change_description or f"Version {existing.version}")
        old_version = existing.version

        updated = self._store.update_record(record_id, **updates)
        if updated is None:
            return None

        updated.version = old_version + 1
        self._indexer.reindex(self._store.all_records)
        self._metrics.records_updated += 1
        self._metrics.total_versions = self._version_manager.total_versions

        await self._publish_event("record_updated", {
            "record_id": record_id,
            "new_version": updated.version,
            "change_description": change_description,
        })
        return updated

    async def delete_record(self, record_id: str) -> bool:
        result = self._store.delete_record(record_id)
        if result:
            self._indexer.remove_record(record_id)
            self._metrics.records_deleted += 1
            self._metrics.total_records = self._store.record_count
            await self._publish_event("record_deleted", {"record_id": record_id})
        return result

    async def list_records(
        self,
        collection_id: str | None = None,
        type_filter: KnowledgeType | None = None,
        status_filter: KnowledgeStatus | None = None,
        tag_filter: str | None = None,
        limit: int = 100,
    ) -> list[KnowledgeRecord]:
        return self._store.list_records(collection_id, type_filter, status_filter, tag_filter, limit)

    # ------------------------------------------------------------------
    # Collection operations
    # ------------------------------------------------------------------

    async def create_collection(
        self,
        name: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> KnowledgeCollection:
        collection = KnowledgeCollection(
            name=name,
            description=description,
            tags=tags or [],
        )
        self._store.add_collection(collection)
        self._metrics.total_collections = self._store.collection_count
        await self._publish_event("collection_created", {
            "collection_id": collection.collection_id,
            "name": name,
        })
        return collection

    async def get_collection(self, collection_id: str) -> KnowledgeCollection | None:
        return self._store.get_collection(collection_id)

    async def list_collections(self) -> list[KnowledgeCollection]:
        return self._store.list_collections()

    async def delete_collection(self, collection_id: str) -> bool:
        result = self._store.delete_collection(collection_id)
        if result:
            self._metrics.total_collections = self._store.collection_count
            await self._publish_event("collection_deleted", {"collection_id": collection_id})
        return result

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        collection_id: str | None = None,
        type_filter: KnowledgeType | None = None,
        status_filter: KnowledgeStatus | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        self._metrics.searches_performed += 1
        return self._search.search(query, collection_id, type_filter, status_filter, tags, limit)

    # ------------------------------------------------------------------
    # Citations
    # ------------------------------------------------------------------

    async def add_citation(
        self,
        record_id: str,
        source_title: str = "",
        source_url: str = "",
        source_author: str = "",
        source_date: str = "",
        excerpt: str = "",
        notes: str = "",
    ) -> Citation | None:
        if self._store.get_record(record_id) is None:
            return None
        citation = Citation(
            record_id=record_id,
            source_title=source_title,
            source_url=source_url,
            source_author=source_author,
            source_date=source_date,
            excerpt=excerpt,
            notes=notes,
        )
        self._citation_manager.add_citation(citation)
        self._metrics.total_citations = self._citation_manager.total_citations
        await self._publish_event("citation_added", {
            "citation_id": citation.citation_id,
            "record_id": record_id,
        })
        return citation

    async def list_citations(self, record_id: str) -> list[Citation]:
        return self._citation_manager.list_citations(record_id)

    async def remove_citation(self, citation_id: str) -> bool:
        result = self._citation_manager.remove_citation(citation_id)
        if result:
            self._metrics.total_citations = self._citation_manager.total_citations
        return result

    # ------------------------------------------------------------------
    # Version history
    # ------------------------------------------------------------------

    async def get_version_history(self, record_id: str) -> list[VersionEntry]:
        return self._version_manager.get_history(record_id)

    async def get_version(self, record_id: str, version: int) -> VersionEntry | None:
        return self._version_manager.get_version(record_id, version)

    async def restore_version(self, record_id: str, version: int) -> KnowledgeRecord | None:
        snapshot = self._version_manager.restore(record_id, version)
        if snapshot is None:
            return None
        existing = self._store.get_record(record_id)
        if existing is None:
            return None

        self._version_manager.create_version(existing, f"Restored from version {version}")
        restored_record = self._store.update_record(
            record_id,
            title=snapshot.get("title", existing.title),
            content=snapshot.get("content", existing.content),
            summary=snapshot.get("summary", existing.summary),
            tags=list(snapshot.get("tags", existing.tags)),
            status=KnowledgeStatus[snapshot.get("status", "DRAFT")],
        )
        if restored_record:
            restored_record.version = existing.version + 1
            self._indexer.reindex(self._store.all_records)
            self._metrics.records_updated += 1
        return restored_record

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    async def add_relationship(
        self,
        source_record_id: str,
        target_record_id: str,
        rel_type: RelationshipType = RelationshipType.RELATES_TO,
        weight: float = 1.0,
        description: str = "",
    ) -> Relationship | None:
        if self._store.get_record(source_record_id) is None:
            return None
        if self._store.get_record(target_record_id) is None:
            return None
        relationship = Relationship(
            source_record_id=source_record_id,
            target_record_id=target_record_id,
            relationship_type=rel_type,
            weight=weight,
            description=description,
        )
        self._relationship_manager.add_relationship(relationship)
        self._metrics.total_relationships = self._relationship_manager.total_relationships
        await self._publish_event("relationship_added", {
            "relationship_id": relationship.relationship_id,
            "source": source_record_id,
            "target": target_record_id,
            "type": rel_type.value,
        })
        return relationship

    async def get_relationships(self, record_id: str) -> list[Relationship]:
        return self._relationship_manager.get_relationships(record_id)

    async def remove_relationship(self, relationship_id: str) -> bool:
        result = self._relationship_manager.remove_relationship(relationship_id)
        if result:
            self._metrics.total_relationships = self._relationship_manager.total_relationships
        return result

    async def query_relationships(
        self,
        source_id: str | None = None,
        target_id: str | None = None,
        rel_type: RelationshipType | None = None,
    ) -> list[Relationship]:
        return self._relationship_manager.query_relationships(source_id, target_id, rel_type)

    # ------------------------------------------------------------------
    # Import / Export
    # ------------------------------------------------------------------

    async def export_collection(self, collection_id: str) -> dict[str, Any] | None:
        self._metrics.exports_performed += 1
        return self._import_export.export_collection(collection_id)

    async def export_all(self) -> list[dict[str, Any]]:
        self._metrics.exports_performed += 1
        return self._import_export.export_all()

    async def import_records(self, data: list[dict[str, Any]], collection_id: str) -> int:
        count = self._import_export.import_records(data, collection_id)
        if count > 0:
            self._indexer.reindex(self._store.all_records)
            self._metrics.imports_performed += 1
            self._metrics.total_records = self._store.record_count
            await self._publish_event("records_imported", {
                "count": count,
                "collection_id": collection_id,
            })
        return count

    async def to_json(self, collection_id: str | None = None) -> str:
        return self._import_export.to_json(collection_id)

    async def from_json(self, json_str: str, collection_id: str) -> int:
        count = self._import_export.from_json(json_str, collection_id)
        if count > 0:
            self._indexer.reindex(self._store.all_records)
            self._metrics.imports_performed += 1
            self._metrics.total_records = self._store.record_count
        return count

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def metrics(self) -> KnowledgeMetrics:
        return self._metrics

    # ------------------------------------------------------------------
    # Sub-component accessors
    # ------------------------------------------------------------------

    @property
    def store(self) -> KnowledgeStore:
        return self._store

    @property
    def indexer(self) -> KnowledgeIndexer:
        return self._indexer

    @property
    def search_engine(self) -> KnowledgeSearch:
        return self._search

    @property
    def citation_manager(self) -> CitationManager:
        return self._citation_manager

    @property
    def version_manager(self) -> VersionManager:
        return self._version_manager

    @property
    def relationship_manager(self) -> RelationshipManager:
        return self._relationship_manager

    @property
    def import_export(self) -> ImportExportManager:
        return self._import_export

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def _publish_event(self, action: str, payload: dict[str, Any]) -> None:
        try:
            await self._event_bus.publish(Event(
                source="knowledge_engine",
                category=EventCategory.KNOWLEDGE,
                priority=EventPriority.NORMAL,
                payload={"action": action, **payload},
            ))
        except Exception:
            self._logger.exception("Failed to publish knowledge event")
