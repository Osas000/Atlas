"""Integration tests for cross-module communication via Event Bus."""

import pytest

from atlas_core.browser import BrowserCompanion
from atlas_core.context import AtlasContext, ContextManager, PermissionContext
from atlas_core.events import EventBus
from atlas_core.execution import ExecutionEngine, FileCommand
from atlas_core.intelligence import Capability, IntelligenceRouter
from atlas_core.knowledge import KnowledgeEngine, KnowledgeType
from atlas_core.memory import MemoryManager
from atlas_core.operations import OperationsCore


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=200)


@pytest.fixture
def context_manager(bus: EventBus) -> ContextManager:
    return ContextManager(bus)


@pytest.fixture
def memory_manager(bus: EventBus) -> MemoryManager:
    return MemoryManager(bus)


@pytest.fixture
def operations_core(bus: EventBus) -> OperationsCore:
    return OperationsCore(bus)


@pytest.fixture
def execution_engine(bus: EventBus) -> ExecutionEngine:
    return ExecutionEngine(bus)


@pytest.fixture
def intelligence_router(bus: EventBus) -> IntelligenceRouter:
    return IntelligenceRouter(bus)


@pytest.fixture
def browser_companion(bus: EventBus) -> BrowserCompanion:
    return BrowserCompanion(bus)


@pytest.fixture
def knowledge_engine(bus: EventBus) -> KnowledgeEngine:
    return KnowledgeEngine(bus)


# ======================================================================
# Integration: Context → Event Bus → All listeners
# ======================================================================


class TestContextIntegration:
    async def test_context_update_fires_event_received_by_all(self, bus: EventBus) -> None:
        """Context update events reach subscribers across categories."""
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("context", handler)
        manager = ContextManager(bus)
        await manager.update_user(display_name="Integration")
        assert len(received) >= 1

    async def test_execution_uses_context_permissions(self, bus: EventBus, context_manager: ContextManager) -> None:
        """Execution Engine grants commands when context has permissions."""
        engine = ExecutionEngine(bus)
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        await context_manager.replace_context(ctx)
        engine.set_context(ctx)
        await engine.start()
        job = await engine.execute(FileCommand("read", "/tmp/test"))
        assert job.status.name == "SUCCESS"
        await engine.stop()

    async def test_execution_denies_without_permissions(self, bus: EventBus, context_manager: ContextManager) -> None:
        """Execution Engine denies commands when context lacks permissions."""
        engine = ExecutionEngine(bus)
        ctx = AtlasContext(permissions=PermissionContext(permissions={}))
        await context_manager.replace_context(ctx)
        engine.set_context(ctx)
        job = await engine.execute(FileCommand("read", "/tmp/test"))
        assert job.status.name == "FAILED"
        assert "Permission denied" in job.error


# ======================================================================
# Integration: Browser Companion → Event Bus → External subscribers
# ======================================================================


class TestBrowserIntegration:
    async def test_browser_events_reachable_via_bus(self, bus: EventBus) -> None:
        """Browser Companion events are published to the Event Bus."""
        companion = BrowserCompanion(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("browser", handler)
        await companion.connect_browser("chrome")
        await companion.update_page(url="https://example.com")
        assert len(received) >= 2

    async def test_browser_permission_from_context(self, bus: EventBus, context_manager: ContextManager) -> None:
        """Browser Companion checks permissions from AtlasContext."""
        companion = BrowserCompanion(bus)
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True}))
        await context_manager.replace_context(ctx)
        companion.set_context(ctx)
        result = await companion.execute_action("navigate", url="https://example.com")
        assert result["success"] is True

    async def test_browser_permission_denied(self, bus: EventBus, context_manager: ContextManager) -> None:
        """Browser Companion denies actions without permission."""
        companion = BrowserCompanion(bus)
        ctx = AtlasContext(permissions=PermissionContext(permissions={}))
        await context_manager.replace_context(ctx)
        companion.set_context(ctx)
        result = await companion.execute_action("navigate", url="https://example.com")
        assert result["success"] is False


# ======================================================================
# Integration: Knowledge Engine → Event Bus → External subscribers
# ======================================================================


class TestKnowledgeIntegration:
    async def test_knowledge_events_via_bus(self, bus: EventBus) -> None:
        """Knowledge Engine events are published to the Event Bus."""
        engine = KnowledgeEngine(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("knowledge", handler)
        await engine.create_record(title="Integration Test", content="Test content")
        assert len(received) >= 1

    async def test_record_searchable_after_create(self, bus: EventBus) -> None:
        """Records created via Knowledge Engine are immediately searchable."""
        engine = KnowledgeEngine(bus)
        await engine.create_record(title="SearchTerm", content="Content about Python")
        results = await engine.search("SearchTerm")
        assert len(results) == 1
        assert results[0].record.title == "SearchTerm"

    async def test_knowledge_versioning(self, bus: EventBus) -> None:
        """Updating a record creates a new version and preserves history."""
        engine = KnowledgeEngine(bus)
        r = await engine.create_record(title="V1", content="Version 1")
        await engine.update_record(r.record_id, title="V2", content="Version 2")
        history = await engine.get_version_history(r.record_id)
        assert len(history) == 2
        updated = await engine.get_record(r.record_id)
        assert updated.version == 2


# ======================================================================
# Integration: Memory Engine → Event Bus → External subscribers
# ======================================================================


class TestMemoryIntegration:
    async def test_memory_events_via_bus(self, bus: EventBus) -> None:
        """Memory Engine events are published to the Event Bus."""
        engine = MemoryManager(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("memory", handler)
        from atlas_core.memory import MemoryCategory, MemoryImportance, MemoryRecord
        record = MemoryRecord(
            title="Integration Memory",
            content={"text": "Test"},
            category=MemoryCategory.TECHNICAL,
            importance=MemoryImportance.MEDIUM,
        )
        await engine.working.create(record)
        assert len(received) >= 1

    async def test_memory_search_across_layers(self, bus: EventBus) -> None:
        """Memory search works across all layers simultaneously."""
        engine = MemoryManager(bus)
        from atlas_core.memory import MemoryCategory, MemoryImportance, MemoryRecord
        record = MemoryRecord(
            title="CrossLayer",
            content={"text": "Searchable content"},
            category=MemoryCategory.TECHNICAL,
            importance=MemoryImportance.MEDIUM,
        )
        await engine.working.create(record)
        results = await engine.search_all("CrossLayer")
        assert len(results) >= 1


# ======================================================================
# Integration: Multi-service lifecycle
# ======================================================================


class TestMultiServiceLifecycle:
    async def test_multiple_services_start_stop(self, bus: EventBus) -> None:
        """Multiple IServices can be started and stopped independently."""
        engine = ExecutionEngine(bus)
        router = IntelligenceRouter(bus)
        knowledge = KnowledgeEngine(bus)

        await engine.start()
        await router.start()
        await knowledge.start()

        assert engine._running
        assert router._running
        assert knowledge._running

        health_e = await engine.health_check()
        health_r = await router.health_check()
        health_k = await knowledge.health_check()

        assert health_e.healthy
        assert health_r.healthy
        assert health_k.healthy

        await engine.stop()
        await router.stop()
        await knowledge.stop()

    async def test_events_flow_across_services(self, bus: EventBus) -> None:
        """Events from one service are visible to all subscribers."""
        engine = ExecutionEngine(bus)
        knowledge = KnowledgeEngine(bus)

        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("execution", handler)
        bus.subscribe("knowledge", handler)

        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        engine.set_context(ctx)
        await engine.start()
        await engine.execute(FileCommand("read", "/tmp/f"))

        await knowledge.create_record(title="Cross-Service Event Test")

        assert len(received) >= 2
        await engine.stop()


# ======================================================================
# Integration: Add/remove relationships between knowledge records
# ======================================================================


class TestKnowledgeRelationshipIntegration:
    async def test_knowledge_relationship(self, bus: EventBus) -> None:
        """Knowledge records can be related to each other."""
        from atlas_core.knowledge import RelationshipType
        engine = KnowledgeEngine(bus)
        r1 = await engine.create_record(title="Python")
        r2 = await engine.create_record(title="Async")
        rel = await engine.add_relationship(r1.record_id, r2.record_id, RelationshipType.RELATES_TO)
        assert rel is not None
        rels = await engine.get_relationships(r1.record_id)
        assert len(rels) == 1
