"""Tests for the Knowledge Engine."""

import json

import pytest

from atlas_core.events import EventBus
from atlas_core.knowledge import (
    Citation,
    CitationManager,
    ImportExportManager,
    KnowledgeCollection,
    KnowledgeEngine,
    KnowledgeImportance,
    KnowledgeIndexer,
    KnowledgeMetrics,
    KnowledgeRecord,
    KnowledgeSearch,
    KnowledgeStatus,
    KnowledgeStore,
    KnowledgeType,
    Relationship,
    RelationshipManager,
    RelationshipType,
    SearchResult,
    VersionEntry,
    VersionManager,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def engine(bus: EventBus) -> KnowledgeEngine:
    return KnowledgeEngine(bus)


@pytest.fixture
def store() -> KnowledgeStore:
    return KnowledgeStore()


@pytest.fixture
def indexer() -> KnowledgeIndexer:
    return KnowledgeIndexer()


@pytest.fixture
def search(store: KnowledgeStore, indexer: KnowledgeIndexer) -> KnowledgeSearch:
    return KnowledgeSearch(store, indexer)


@pytest.fixture
def citation_mgr() -> CitationManager:
    return CitationManager()


@pytest.fixture
def version_mgr() -> VersionManager:
    return VersionManager()


@pytest.fixture
def relationship_mgr() -> RelationshipManager:
    return RelationshipManager()


@pytest.fixture
def import_export(store: KnowledgeStore) -> ImportExportManager:
    return ImportExportManager(store)


# ======================================================================
# Enums
# ======================================================================


class TestKnowledgeType:
    def test_values(self) -> None:
        assert KnowledgeType.FACT.value == "fact"
        assert KnowledgeType.DOCUMENT.value == "document"
        assert KnowledgeType.REFERENCE.value == "reference"
        assert KnowledgeType.CONCEPT.value == "concept"
        assert KnowledgeType.TERM.value == "term"
        assert KnowledgeType.DEFINITION.value == "definition"
        assert KnowledgeType.CODE_SNIPPET.value == "code_snippet"
        assert KnowledgeType.NOTE.value == "note"


class TestKnowledgeStatus:
    def test_values(self) -> None:
        assert KnowledgeStatus.DRAFT != KnowledgeStatus.PUBLISHED
        assert KnowledgeStatus.ARCHIVED != KnowledgeStatus.DEPRECATED


class TestKnowledgeImportance:
    def test_ordering(self) -> None:
        assert KnowledgeImportance.LOW.value < KnowledgeImportance.CRITICAL.value


class TestRelationshipType:
    def test_values(self) -> None:
        assert RelationshipType.RELATES_TO.value == "relates_to"
        assert RelationshipType.DEPENDS_ON.value == "depends_on"
        assert RelationshipType.REFERENCES.value == "references"
        assert RelationshipType.EXTENDS.value == "extends"
        assert RelationshipType.CONTRADICTS.value == "contradicts"
        assert RelationshipType.DERIVED_FROM.value == "derived_from"


# ======================================================================
# Data classes
# ======================================================================


class TestKnowledgeRecord:
    def test_defaults(self) -> None:
        r = KnowledgeRecord()
        assert r.record_id is not None
        assert r.type == KnowledgeType.NOTE
        assert r.status == KnowledgeStatus.DRAFT
        assert r.importance == KnowledgeImportance.MEDIUM
        assert r.version == 1
        assert r.tags == []
        assert r.metadata == {}


class TestKnowledgeCollection:
    def test_defaults(self) -> None:
        c = KnowledgeCollection()
        assert c.collection_id is not None
        assert c.name == ""
        assert c.record_count == 0


class TestCitation:
    def test_defaults(self) -> None:
        c = Citation()
        assert c.citation_id is not None
        assert c.record_id == ""


class TestRelationship:
    def test_defaults(self) -> None:
        r = Relationship()
        assert r.relationship_id is not None
        assert r.relationship_type == RelationshipType.RELATES_TO
        assert r.weight == 1.0


class TestVersionEntry:
    def test_defaults(self) -> None:
        v = VersionEntry()
        assert v.version == 1
        assert v.snapshot == {}


class TestSearchResult:
    def test_defaults(self) -> None:
        s = SearchResult()
        assert s.score == 0.0
        assert s.record is None


class TestKnowledgeMetrics:
    def test_defaults(self) -> None:
        m = KnowledgeMetrics()
        assert m.total_records == 0
        assert m.searches_performed == 0

    def test_type_counts(self) -> None:
        m = KnowledgeMetrics()
        records = [
            KnowledgeRecord(type=KnowledgeType.FACT),
            KnowledgeRecord(type=KnowledgeType.FACT),
            KnowledgeRecord(type=KnowledgeType.NOTE),
        ]
        counts = m.type_counts(records)
        assert counts["fact"] == 2
        assert counts["note"] == 1

    def test_status_counts(self) -> None:
        m = KnowledgeMetrics()
        records = [
            KnowledgeRecord(status=KnowledgeStatus.DRAFT),
            KnowledgeRecord(status=KnowledgeStatus.PUBLISHED),
            KnowledgeRecord(status=KnowledgeStatus.DRAFT),
        ]
        counts = m.status_counts(records)
        assert counts["draft"] == 2
        assert counts["published"] == 1


# ======================================================================
# KnowledgeStore
# ======================================================================


class TestKnowledgeStore:
    def test_add_and_get_record(self, store: KnowledgeStore) -> None:
        r = KnowledgeRecord(title="Test Record")
        store.add_record(r)
        assert store.get_record(r.record_id) is r

    def test_get_record_nonexistent(self, store: KnowledgeStore) -> None:
        assert store.get_record("nope") is None

    def test_update_record(self, store: KnowledgeStore) -> None:
        r = KnowledgeRecord(title="Original")
        store.add_record(r)
        updated = store.update_record(r.record_id, title="Updated", content="New content")
        assert updated is not None
        assert updated.title == "Updated"
        assert updated.content == "New content"

    def test_update_record_nonexistent(self, store: KnowledgeStore) -> None:
        assert store.update_record("nope", title="New") is None

    def test_update_record_preserves_id_and_created(self, store: KnowledgeStore) -> None:
        r = KnowledgeRecord(title="Original")
        store.add_record(r)
        store.update_record(r.record_id, title="New Title")
        updated = store.get_record(r.record_id)
        assert updated is not None
        assert updated.title == "New Title"
        assert updated.record_id == r.record_id

    def test_delete_record(self, store: KnowledgeStore) -> None:
        r = KnowledgeRecord()
        store.add_record(r)
        assert store.delete_record(r.record_id) is True
        assert store.get_record(r.record_id) is None

    def test_delete_record_nonexistent(self, store: KnowledgeStore) -> None:
        assert store.delete_record("nope") is False

    def test_list_records(self, store: KnowledgeStore) -> None:
        store.add_record(KnowledgeRecord(type=KnowledgeType.FACT))
        store.add_record(KnowledgeRecord(type=KnowledgeType.NOTE))
        store.add_record(KnowledgeRecord(type=KnowledgeType.FACT))
        assert len(store.list_records()) == 3
        assert len(store.list_records(type_filter=KnowledgeType.FACT)) == 2
        assert len(store.list_records(type_filter=KnowledgeType.NOTE)) == 1

    def test_list_records_by_collection(self, store: KnowledgeStore) -> None:
        store.add_record(KnowledgeRecord(collection_id="c1"))
        store.add_record(KnowledgeRecord(collection_id="c2"))
        assert len(store.list_records(collection_id="c1")) == 1

    def test_list_records_by_status(self, store: KnowledgeStore) -> None:
        store.add_record(KnowledgeRecord(status=KnowledgeStatus.DRAFT))
        store.add_record(KnowledgeRecord(status=KnowledgeStatus.PUBLISHED))
        assert len(store.list_records(status_filter=KnowledgeStatus.PUBLISHED)) == 1

    def test_list_records_by_tag(self, store: KnowledgeStore) -> None:
        store.add_record(KnowledgeRecord(tags=["python", "async"]))
        store.add_record(KnowledgeRecord(tags=["javascript"]))
        assert len(store.list_records(tag_filter="python")) == 1

    def test_list_records_limit(self, store: KnowledgeStore) -> None:
        for _ in range(10):
            store.add_record(KnowledgeRecord())
        assert len(store.list_records(limit=3)) == 3

    def test_record_count(self, store: KnowledgeStore) -> None:
        assert store.record_count == 0
        store.add_record(KnowledgeRecord())
        assert store.record_count == 1

    def test_all_records(self, store: KnowledgeStore) -> None:
        store.add_record(KnowledgeRecord())
        store.add_record(KnowledgeRecord())
        assert len(store.all_records) == 2

    def test_collection_operations(self, store: KnowledgeStore) -> None:
        c = KnowledgeCollection(name="Test Collection")
        store.add_collection(c)
        assert store.get_collection(c.collection_id) is c
        assert len(store.list_collections()) == 1
        assert store.collection_count == 1

        store.update_collection(c.collection_id, name="Updated")
        assert store.get_collection(c.collection_id).name == "Updated"
        assert store.delete_collection(c.collection_id) is True
        assert store.collection_count == 0

    def test_collection_nonexistent(self, store: KnowledgeStore) -> None:
        assert store.get_collection("nope") is None
        assert store.update_collection("nope", name="X") is None
        assert store.delete_collection("nope") is False

    def test_clear(self, store: KnowledgeStore) -> None:
        store.add_record(KnowledgeRecord())
        store.add_collection(KnowledgeCollection())
        store.clear()
        assert store.record_count == 0
        assert store.collection_count == 0

    def test_update_collection_updates_record_count(self, store: KnowledgeStore) -> None:
        c = KnowledgeCollection(name="Coll")
        store.add_collection(c)
        store.add_record(KnowledgeRecord(collection_id=c.collection_id))
        store.add_record(KnowledgeRecord(collection_id=c.collection_id))
        store.update_collection(c.collection_id)
        assert store.get_collection(c.collection_id).record_count == 2


# ======================================================================
# KnowledgeIndexer
# ======================================================================


class TestKnowledgeIndexer:
    def test_index_and_search(self, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="Python Async", content="Asynchronous programming with asyncio", tags=["python"])
        indexer.index_record(r)
        assert "async" in indexer._word_index
        assert r.record_id in indexer._word_index["async"]

    def test_tag_index(self, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(tags=["python", "async"])
        indexer.index_record(r)
        assert r.record_id in indexer._tag_index["python"]
        assert r.record_id in indexer._tag_index["async"]

    def test_type_index(self, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(type=KnowledgeType.FACT)
        indexer.index_record(r)
        assert r.record_id in indexer._type_index[KnowledgeType.FACT]

    def test_remove_record(self, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="Hello World")
        indexer.index_record(r)
        assert r.record_id in indexer._word_index["hello"]
        indexer.remove_record(r.record_id)
        assert r.record_id not in indexer._word_index.get("hello", set())

    def test_reindex(self, indexer: KnowledgeIndexer) -> None:
        r1 = KnowledgeRecord(title="Alpha")
        r2 = KnowledgeRecord(title="Beta")
        indexer.index_record(r1)
        indexer.reindex([r2])
        assert indexer.word_count == 1
        assert "alpha" not in indexer._word_index

    def test_word_count(self, indexer: KnowledgeIndexer) -> None:
        assert indexer.word_count == 0
        r = KnowledgeRecord(title="Hello World Python")
        indexer.index_record(r)
        assert indexer.word_count == 3

    def test_tag_count(self, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(tags=["python", "async", "tutorial"])
        indexer.index_record(r)
        assert indexer.tag_count == 3

    def test_index_skips_short_words(self, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="a an at x y z")
        indexer.index_record(r)
        assert indexer.word_count == 0


# ======================================================================
# KnowledgeSearch
# ======================================================================


class TestKnowledgeSearch:
    def test_search_basic(self, search: KnowledgeSearch, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="Python Tutorial", content="Learn Python programming", tags=["python"])
        store.add_record(r)
        indexer.index_record(r)
        results = search.search("python")
        assert len(results) == 1
        assert results[0].record is r
        assert results[0].score > 0

    def test_search_no_match(self, search: KnowledgeSearch) -> None:
        results = search.search("nonexistent")
        assert results == []

    def test_search_empty_query(self, search: KnowledgeSearch) -> None:
        results = search.search("")
        assert results == []

    def test_search_short_query(self, search: KnowledgeSearch) -> None:
        results = search.search("a")
        assert results == []
        results = search.search("ab")
        assert results == []

    def test_search_scoring(self, search: KnowledgeSearch, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        r1 = KnowledgeRecord(title="Python Guide", content="A guide to Python")
        r2 = KnowledgeRecord(title="JS Guide", content="A guide to JavaScript")
        store.add_record(r1)
        store.add_record(r2)
        indexer.index_record(r1)
        indexer.index_record(r2)
        results = search.search("guide")
        assert len(results) == 2

    def test_search_with_filters(self, search: KnowledgeSearch, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="Python", collection_id="c1", status=KnowledgeStatus.PUBLISHED)
        store.add_record(r)
        indexer.index_record(r)
        assert len(search.search("python", collection_id="c1")) == 1
        assert len(search.search("python", collection_id="c2")) == 0
        assert len(search.search("python", status_filter=KnowledgeStatus.PUBLISHED)) == 1
        assert len(search.search("python", status_filter=KnowledgeStatus.DRAFT)) == 0

    def test_search_with_tags(self, search: KnowledgeSearch, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="Python", tags=["python", "tutorial"])
        store.add_record(r)
        indexer.index_record(r)
        results = search.search("python", tags=["python"])
        assert len(results) == 1

    def test_search_with_tags_no_match(self, search: KnowledgeSearch, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="Python", tags=["python"])
        store.add_record(r)
        indexer.index_record(r)
        results = search.search("python", tags=["javascript"])
        assert len(results) == 0

    def test_search_limit(self, search: KnowledgeSearch, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        for i in range(10):
            r = KnowledgeRecord(title=f"Record {i}", content="common content")
            store.add_record(r)
            indexer.index_record(r)
        results = search.search("common", limit=3)
        assert len(results) == 3

    def test_match_field_identification(self, search: KnowledgeSearch, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="UniqueTitle", content="Some content here")
        store.add_record(r)
        indexer.index_record(r)
        results = search.search("UniqueTitle")
        assert results[0].matched_field == "title"

    def test_search_snippet_in_content(self, search: KnowledgeSearch, store: KnowledgeStore, indexer: KnowledgeIndexer) -> None:
        r = KnowledgeRecord(title="Doc", content="This is a long document about Python programming language")
        store.add_record(r)
        indexer.index_record(r)
        results = search.search("Python")
        assert results[0].matched_field == "content"
        assert "Python" in results[0].matched_text


# ======================================================================
# CitationManager
# ======================================================================


class TestCitationManager:
    def test_add_and_get_citation(self, citation_mgr: CitationManager) -> None:
        c = Citation(record_id="r1", source_title="Source")
        citation_mgr.add_citation(c)
        assert citation_mgr.get_citation(c.citation_id) is c

    def test_list_citations(self, citation_mgr: CitationManager) -> None:
        c1 = Citation(record_id="r1")
        c2 = Citation(record_id="r1")
        citation_mgr.add_citation(c1)
        citation_mgr.add_citation(c2)
        assert len(citation_mgr.list_citations("r1")) == 2

    def test_list_citations_empty(self, citation_mgr: CitationManager) -> None:
        assert citation_mgr.list_citations("nonexistent") == []

    def test_remove_citation(self, citation_mgr: CitationManager) -> None:
        c = Citation(record_id="r1")
        citation_mgr.add_citation(c)
        assert citation_mgr.remove_citation(c.citation_id) is True
        assert citation_mgr.get_citation(c.citation_id) is None

    def test_remove_citation_nonexistent(self, citation_mgr: CitationManager) -> None:
        assert citation_mgr.remove_citation("nope") is False

    def test_remove_updates_record_index(self, citation_mgr: CitationManager) -> None:
        c = Citation(record_id="r1")
        citation_mgr.add_citation(c)
        citation_mgr.remove_citation(c.citation_id)
        assert citation_mgr.list_citations("r1") == []

    def test_count_citations(self, citation_mgr: CitationManager) -> None:
        assert citation_mgr.count_citations("r1") == 0
        citation_mgr.add_citation(Citation(record_id="r1"))
        assert citation_mgr.count_citations("r1") == 1

    def test_total_citations(self, citation_mgr: CitationManager) -> None:
        assert citation_mgr.total_citations == 0
        citation_mgr.add_citation(Citation(record_id="r1"))
        citation_mgr.add_citation(Citation(record_id="r2"))
        assert citation_mgr.total_citations == 2

    def test_clear(self, citation_mgr: CitationManager) -> None:
        citation_mgr.add_citation(Citation(record_id="r1"))
        citation_mgr.clear()
        assert citation_mgr.total_citations == 0


# ======================================================================
# VersionManager
# ======================================================================


class TestVersionManager:
    def test_create_version(self, version_mgr: VersionManager) -> None:
        r = KnowledgeRecord(title="Test", content="Content")
        entry = version_mgr.create_version(r, "Initial")
        assert entry.version == 1
        assert entry.record_id == r.record_id
        assert entry.snapshot["title"] == "Test"

    def test_get_history(self, version_mgr: VersionManager) -> None:
        r = KnowledgeRecord(title="Test")
        version_mgr.create_version(r, "v1")
        r.title = "Updated"
        version_mgr.create_version(r, "v2")
        history = version_mgr.get_history(r.record_id)
        assert len(history) == 2
        assert history[0].snapshot["title"] == "Test"
        assert history[1].snapshot["title"] == "Updated"

    def test_get_history_empty(self, version_mgr: VersionManager) -> None:
        assert version_mgr.get_history("nope") == []

    def test_get_version(self, version_mgr: VersionManager) -> None:
        r = KnowledgeRecord(title="Test")
        version_mgr.create_version(r, "v1")
        entry = version_mgr.get_version(r.record_id, 1)
        assert entry is not None
        assert entry.version == 1

    def test_get_version_nonexistent(self, version_mgr: VersionManager) -> None:
        assert version_mgr.get_version("nope", 1) is None

    def test_restore(self, version_mgr: VersionManager) -> None:
        r = KnowledgeRecord(title="Original")
        version_mgr.create_version(r, "v1")
        r.title = "Changed"
        version_mgr.create_version(r, "v2")
        snapshot = version_mgr.restore(r.record_id, 1)
        assert snapshot is not None
        assert snapshot["title"] == "Original"

    def test_restore_nonexistent(self, version_mgr: VersionManager) -> None:
        assert version_mgr.restore("nope", 1) is None

    def test_total_versions(self, version_mgr: VersionManager) -> None:
        assert version_mgr.total_versions == 0
        r = KnowledgeRecord(title="T")
        version_mgr.create_version(r, "v1")
        assert version_mgr.total_versions == 1

    def test_clear(self, version_mgr: VersionManager) -> None:
        r = KnowledgeRecord(title="T")
        version_mgr.create_version(r, "v1")
        version_mgr.clear()
        assert version_mgr.total_versions == 0


# ======================================================================
# RelationshipManager
# ======================================================================


class TestRelationshipManager:
    def test_add_and_get_relationship(self, relationship_mgr: RelationshipManager) -> None:
        rel = Relationship(source_record_id="r1", target_record_id="r2")
        relationship_mgr.add_relationship(rel)
        relationships = relationship_mgr.get_relationships("r1")
        assert len(relationships) == 1

    def test_get_incoming_outgoing(self, relationship_mgr: RelationshipManager) -> None:
        rel = Relationship(source_record_id="r1", target_record_id="r2")
        relationship_mgr.add_relationship(rel)
        assert len(relationship_mgr.get_outgoing("r1")) == 1
        assert len(relationship_mgr.get_incoming("r2")) == 1
        assert len(relationship_mgr.get_outgoing("r2")) == 0
        assert len(relationship_mgr.get_incoming("r1")) == 0

    def test_remove_relationship(self, relationship_mgr: RelationshipManager) -> None:
        rel = Relationship(source_record_id="r1", target_record_id="r2")
        relationship_mgr.add_relationship(rel)
        assert relationship_mgr.remove_relationship(rel.relationship_id) is True
        assert len(relationship_mgr.get_relationships("r1")) == 0

    def test_remove_relationship_nonexistent(self, relationship_mgr: RelationshipManager) -> None:
        assert relationship_mgr.remove_relationship("nope") is False

    def test_query_relationships(self, relationship_mgr: RelationshipManager) -> None:
        r1 = Relationship(source_record_id="r1", target_record_id="r2", relationship_type=RelationshipType.DEPENDS_ON)
        r2 = Relationship(source_record_id="r1", target_record_id="r3", relationship_type=RelationshipType.RELATES_TO)
        relationship_mgr.add_relationship(r1)
        relationship_mgr.add_relationship(r2)

        results = relationship_mgr.query_relationships(source_id="r1")
        assert len(results) == 2

        results = relationship_mgr.query_relationships(rel_type=RelationshipType.DEPENDS_ON)
        assert len(results) == 1
        assert results[0].target_record_id == "r2"

        results = relationship_mgr.query_relationships(source_id="r1", rel_type=RelationshipType.RELATES_TO)
        assert len(results) == 1

    def test_query_relationships_no_match(self, relationship_mgr: RelationshipManager) -> None:
        results = relationship_mgr.query_relationships(source_id="r1")
        assert results == []

    def test_total_relationships(self, relationship_mgr: RelationshipManager) -> None:
        assert relationship_mgr.total_relationships == 0
        relationship_mgr.add_relationship(Relationship(source_record_id="r1", target_record_id="r2"))
        assert relationship_mgr.total_relationships == 1

    def test_clear(self, relationship_mgr: RelationshipManager) -> None:
        relationship_mgr.add_relationship(Relationship(source_record_id="r1", target_record_id="r2"))
        relationship_mgr.clear()
        assert relationship_mgr.total_relationships == 0


# ======================================================================
# ImportExportManager
# ======================================================================


class TestImportExportManager:
    def test_export_collection(self, import_export: ImportExportManager, store: KnowledgeStore) -> None:
        c = KnowledgeCollection(name="TestColl")
        store.add_collection(c)
        store.add_record(KnowledgeRecord(collection_id=c.collection_id, title="Record 1"))
        store.add_record(KnowledgeRecord(collection_id=c.collection_id, title="Record 2"))
        exported = import_export.export_collection(c.collection_id)
        assert exported is not None
        assert exported["collection"]["name"] == "TestColl"
        assert len(exported["records"]) == 2

    def test_export_collection_nonexistent(self, import_export: ImportExportManager) -> None:
        assert import_export.export_collection("nope") is None

    def test_export_all(self, import_export: ImportExportManager, store: KnowledgeStore) -> None:
        c1 = KnowledgeCollection(name="C1")
        c2 = KnowledgeCollection(name="C2")
        store.add_collection(c1)
        store.add_collection(c2)
        store.add_record(KnowledgeRecord(collection_id=c1.collection_id))
        store.add_record(KnowledgeRecord(collection_id=c2.collection_id))
        exported = import_export.export_all()
        assert len(exported) == 2

    def test_import_records(self, import_export: ImportExportManager, store: KnowledgeStore) -> None:
        data = [
            {"title": "Record 1", "type": "fact", "content": "Content 1"},
            {"title": "Record 2", "type": "note", "content": "Content 2"},
        ]
        count = import_export.import_records(data, "coll1")
        assert count == 2
        assert store.record_count == 2

    def test_import_records_with_invalid_data(self, import_export: ImportExportManager, store: KnowledgeStore) -> None:
        data = [{"title": "Valid"}, {"type": "note"}, {}]
        count = import_export.import_records(data, "coll1")
        assert count >= 2

    def test_to_json(self, import_export: ImportExportManager, store: KnowledgeStore) -> None:
        c = KnowledgeCollection(name="JSONTest")
        store.add_collection(c)
        store.add_record(KnowledgeRecord(collection_id=c.collection_id, title="JSON Record"))
        json_str = import_export.to_json(c.collection_id)
        data = json.loads(json_str)
        assert data["collection"]["name"] == "JSONTest"
        assert len(data["records"]) == 1

    def test_from_json(self, import_export: ImportExportManager, store: KnowledgeStore) -> None:
        data = [{"title": "Imported 1", "type": "fact"}, {"title": "Imported 2", "type": "note"}]
        json_str = json.dumps(data)
        count = import_export.from_json(json_str, "coll1")
        assert count == 2
        assert store.record_count == 2


# ======================================================================
# KnowledgeEngine (IService)
# ======================================================================


class TestKnowledgeEngine:
    async def test_initialize(self, engine: KnowledgeEngine) -> None:
        assert engine.name == "knowledge_engine"
        await engine.initialize()

    async def test_start_stop(self, engine: KnowledgeEngine) -> None:
        await engine.start()
        assert engine._running
        await engine.stop()
        assert not engine._running

    async def test_health_check(self, engine: KnowledgeEngine) -> None:
        health = await engine.health_check()
        assert health.healthy
        assert health.metadata["total_records"] == 0

    async def test_create_record(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(
            title="Test Record",
            content="Test content",
            record_type=KnowledgeType.FACT,
            tags=["python", "test"],
        )
        assert r.title == "Test Record"
        assert r.type == KnowledgeType.FACT
        assert r.tags == ["python", "test"]
        assert r.version == 1
        assert engine.metrics.records_created == 1
        assert engine.metrics.total_records == 1

    async def test_get_record(self, engine: KnowledgeEngine) -> None:
        created = await engine.create_record(title="Get Me")
        fetched = await engine.get_record(created.record_id)
        assert fetched is created

    async def test_get_record_nonexistent(self, engine: KnowledgeEngine) -> None:
        assert await engine.get_record("nope") is None

    async def test_update_record(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="Original", content="Old content")
        updated = await engine.update_record(r.record_id, title="Updated", content="New content", change_description="Updated title")
        assert updated is not None
        assert updated.title == "Updated"
        assert updated.version == 2
        assert engine.metrics.records_updated == 1

    async def test_update_record_nonexistent(self, engine: KnowledgeEngine) -> None:
        assert await engine.update_record("nope", title="X") is None

    async def test_delete_record(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="To Delete")
        assert await engine.delete_record(r.record_id) is True
        assert await engine.get_record(r.record_id) is None
        assert engine.metrics.records_deleted == 1

    async def test_delete_record_nonexistent(self, engine: KnowledgeEngine) -> None:
        assert await engine.delete_record("nope") is False

    async def test_create_collection(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("My Collection", "A test collection", ["test"])
        assert c.name == "My Collection"
        assert c.description == "A test collection"
        assert c.tags == ["test"]
        assert engine.metrics.total_collections == 1

    async def test_get_collection(self, engine: KnowledgeEngine) -> None:
        created = await engine.create_collection("Test")
        fetched = await engine.get_collection(created.collection_id)
        assert fetched is created

    async def test_list_collections(self, engine: KnowledgeEngine) -> None:
        await engine.create_collection("C1")
        await engine.create_collection("C2")
        collections = await engine.list_collections()
        assert len(collections) == 2

    async def test_delete_collection(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("To Delete")
        assert await engine.delete_collection(c.collection_id) is True
        assert engine.metrics.total_collections == 0

    async def test_list_records(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("Test")
        await engine.create_record(collection_id=c.collection_id, title="R1")
        await engine.create_record(collection_id=c.collection_id, title="R2")
        records = await engine.list_records(collection_id=c.collection_id)
        assert len(records) == 2

    async def test_search(self, engine: KnowledgeEngine) -> None:
        await engine.create_record(title="Python Tutorial", content="Learn Python")
        results = await engine.search("python")
        assert len(results) >= 1
        assert engine.metrics.searches_performed == 1

    async def test_search_no_results(self, engine: KnowledgeEngine) -> None:
        results = await engine.search("nonexistent")
        assert results == []

    async def test_add_citation(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="Cited")
        citation = await engine.add_citation(r.record_id, source_title="Source Doc", source_url="https://example.com")
        assert citation is not None
        assert citation.source_title == "Source Doc"
        assert engine.metrics.total_citations == 1

    async def test_add_citation_nonexistent_record(self, engine: KnowledgeEngine) -> None:
        citation = await engine.add_citation("nope", source_title="Source")
        assert citation is None

    async def test_list_citations(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="With Citations")
        await engine.add_citation(r.record_id, source_title="S1")
        await engine.add_citation(r.record_id, source_title="S2")
        citations = await engine.list_citations(r.record_id)
        assert len(citations) == 2

    async def test_remove_citation(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="With Citation")
        c = await engine.add_citation(r.record_id, source_title="S1")
        assert await engine.remove_citation(c.citation_id) is True
        assert engine.metrics.total_citations == 0

    async def test_remove_citation_nonexistent(self, engine: KnowledgeEngine) -> None:
        assert await engine.remove_citation("nope") is False

    async def test_version_history(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="V1")
        await engine.update_record(r.record_id, title="V2", change_description="Updated")
        history = await engine.get_version_history(r.record_id)
        assert len(history) == 2
        assert history[0].version == 1
        assert history[1].version == 1  # pre-update snapshot has same version

    async def test_restore_version_rolls_back(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="Original", content="Original content")
        await engine.update_record(r.record_id, title="Changed", content="New content")
        restored = await engine.restore_version(r.record_id, 1)
        assert restored is not None
        assert restored.title == "Original"
        assert restored.content == "Original content"

    async def test_get_version(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="Original")
        entry = await engine.get_version(r.record_id, 1)
        assert entry is not None
        assert entry.snapshot["title"] == "Original"

    async def test_get_version_nonexistent(self, engine: KnowledgeEngine) -> None:
        assert await engine.get_version("nope", 1) is None

    async def test_restore_version(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(title="Original")
        await engine.update_record(r.record_id, title="Changed", content="New content")
        restored = await engine.restore_version(r.record_id, 1)
        assert restored is not None
        assert restored.title == "Original"

    async def test_restore_version_nonexistent(self, engine: KnowledgeEngine) -> None:
        assert await engine.restore_version("nope", 1) is None

    async def test_add_relationship(self, engine: KnowledgeEngine) -> None:
        r1 = await engine.create_record(title="Source")
        r2 = await engine.create_record(title="Target")
        rel = await engine.add_relationship(r1.record_id, r2.record_id, RelationshipType.DEPENDS_ON)
        assert rel is not None
        assert rel.relationship_type == RelationshipType.DEPENDS_ON
        assert engine.metrics.total_relationships == 1

    async def test_add_relationship_nonexistent_source(self, engine: KnowledgeEngine) -> None:
        r2 = await engine.create_record(title="Target")
        rel = await engine.add_relationship("nope", r2.record_id)
        assert rel is None

    async def test_add_relationship_nonexistent_target(self, engine: KnowledgeEngine) -> None:
        r1 = await engine.create_record(title="Source")
        rel = await engine.add_relationship(r1.record_id, "nope")
        assert rel is None

    async def test_get_relationships(self, engine: KnowledgeEngine) -> None:
        r1 = await engine.create_record(title="Source")
        r2 = await engine.create_record(title="Target")
        await engine.add_relationship(r1.record_id, r2.record_id)
        rels = await engine.get_relationships(r1.record_id)
        assert len(rels) == 1

    async def test_remove_relationship(self, engine: KnowledgeEngine) -> None:
        r1 = await engine.create_record(title="Source")
        r2 = await engine.create_record(title="Target")
        rel = await engine.add_relationship(r1.record_id, r2.record_id)
        assert await engine.remove_relationship(rel.relationship_id) is True
        assert engine.metrics.total_relationships == 0

    async def test_query_relationships(self, engine: KnowledgeEngine) -> None:
        r1 = await engine.create_record(title="A")
        r2 = await engine.create_record(title="B")
        r3 = await engine.create_record(title="C")
        await engine.add_relationship(r1.record_id, r2.record_id, RelationshipType.DEPENDS_ON)
        await engine.add_relationship(r1.record_id, r3.record_id, RelationshipType.RELATES_TO)
        results = await engine.query_relationships(source_id=r1.record_id)
        assert len(results) == 2

    async def test_export_collection(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("Export Test")
        await engine.create_record(collection_id=c.collection_id, title="Exported Record")
        exported = await engine.export_collection(c.collection_id)
        assert exported is not None
        assert len(exported["records"]) == 1

    async def test_export_all(self, engine: KnowledgeEngine) -> None:
        await engine.create_collection("C1")
        await engine.create_collection("C2")
        exported = await engine.export_all()
        assert len(exported) == 2

    async def test_import_records(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("Import Target")
        data = [{"title": "Imported 1", "type": "fact"}, {"title": "Imported 2", "type": "note"}]
        count = await engine.import_records(data, c.collection_id)
        assert count == 2
        assert engine.metrics.imports_performed == 1

    async def test_to_json(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("JSON Collection")
        await engine.create_record(collection_id=c.collection_id, title="JSON Record")
        json_str = await engine.to_json(c.collection_id)
        data = json.loads(json_str)
        assert data["collection"]["name"] == "JSON Collection"

    async def test_from_json(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("Import Collection")
        data = [{"title": "Imported", "type": "fact"}]
        json_str = json.dumps(data)
        count = await engine.from_json(json_str, c.collection_id)
        assert count == 1
        assert engine.metrics.imports_performed == 1

    async def test_set_context(self, engine: KnowledgeEngine) -> None:
        engine.set_context(None)  # should not raise

    async def test_metrics_property(self, engine: KnowledgeEngine) -> None:
        assert engine.metrics is engine._metrics

    async def test_store_property(self, engine: KnowledgeEngine) -> None:
        assert engine.store is engine._store

    async def test_indexer_property(self, engine: KnowledgeEngine) -> None:
        assert engine.indexer is engine._indexer

    async def test_search_engine_property(self, engine: KnowledgeEngine) -> None:
        assert engine.search_engine is engine._search

    async def test_citation_manager_property(self, engine: KnowledgeEngine) -> None:
        assert engine.citation_manager is engine._citation_manager

    async def test_version_manager_property(self, engine: KnowledgeEngine) -> None:
        assert engine.version_manager is engine._version_manager

    async def test_relationship_manager_property(self, engine: KnowledgeEngine) -> None:
        assert engine.relationship_manager is engine._relationship_manager

    async def test_import_export_property(self, engine: KnowledgeEngine) -> None:
        assert engine.import_export is engine._import_export

    async def test_health_after_operations(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("Health")
        await engine.create_record(collection_id=c.collection_id, title="R1")
        await engine.create_record(collection_id=c.collection_id, title="R2")
        await engine.search("test")
        health = await engine.health_check()
        assert health.metadata["total_records"] == 2
        assert health.metadata["total_collections"] == 1
        assert health.metadata["searches_performed"] == 1

    async def test_create_record_updates_collection_count(self, engine: KnowledgeEngine) -> None:
        c = await engine.create_collection("Count")
        await engine.create_record(collection_id=c.collection_id, title="R1")
        fetched = await engine.get_collection(c.collection_id)
        assert fetched is not None
        assert fetched.record_count >= 1

    async def test_publishes_events(self, bus: EventBus) -> None:
        engine = KnowledgeEngine(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("application", handler)
        r = await engine.create_record(title="Event Test")
        await engine.update_record(r.record_id, title="Updated")
        await engine.add_citation(r.record_id, source_title="Source")
        assert len(received) >= 3

    async def test_create_record_with_all_fields(self, engine: KnowledgeEngine) -> None:
        r = await engine.create_record(
            collection_id="col1",
            title="Full Record",
            content="Full content",
            record_type=KnowledgeType.DOCUMENT,
            status=KnowledgeStatus.PUBLISHED,
            importance=KnowledgeImportance.HIGH,
            summary="A summary",
            tags=["a", "b"],
            source="test",
            metadata={"key": "value"},
        )
        assert r.collection_id == "col1"
        assert r.type == KnowledgeType.DOCUMENT
        assert r.status == KnowledgeStatus.PUBLISHED
        assert r.importance == KnowledgeImportance.HIGH
        assert r.summary == "A summary"
        assert r.source == "test"
        assert r.metadata == {"key": "value"}
