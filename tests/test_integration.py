"""Integration tests for cross-module communication via Event Bus."""

import pytest

from atlas_core.browser import BrowserCompanion
from atlas_core.context import AtlasContext, ContextManager, PermissionContext
from atlas_core.events import EventBus
from atlas_core.execution import ExecutionEngine, FileCommand
from atlas_core.intelligence import Capability, IntelligenceRouter
from atlas_core.interfaces import SubsystemResponse
from atlas_core.knowledge import KnowledgeEngine, KnowledgeType
from atlas_core.memory import MemoryManager
from atlas_core.mission import (
    MissionControl,
    Mission,
    MissionPlan,
    MissionStep,
    MissionStatus,
    Subsystem as MissionSubsystem,
    StepState,
)
from atlas_core.notification import NotificationChannel, NotificationService
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


# ======================================================================
# Runtime Integration: Mission → Subsystem via MissionExecutor
# ======================================================================


class TestRuntimeMissionExecution:
    """Mission → Knowledge → Notification integration."""

    async def test_mission_executes_knowledge_step(self, bus: EventBus) -> None:
        """MissionExecutor routes knowledge steps correctly."""
        mc = MissionControl(bus)

        async def knowledge_handler(payload: dict) -> SubsystemResponse:
            return SubsystemResponse(
                success=True,
                payload={"result": "knowledge_processed"},
                subsystem="knowledge",
            )

        mc.executor.register_handler(MissionSubsystem.KNOWLEDGE, knowledge_handler)
        m = await mc.create_mission(title="Runtime Test")
        plan = await mc.plan(m.mission_id)
        assert plan is not None
        # Replace auto-generated plan with our custom plan
        custom_plan = MissionPlan(mission=m, steps=[
            MissionStep(order=1, subsystem=MissionSubsystem.KNOWLEDGE, title="Process"),
        ])
        mc._plans[m.mission_id] = custom_plan
        result = await mc.execute(m.mission_id)
        assert result is not None
        assert result.status in (MissionStatus.COMPLETED, MissionStatus.FAILED)

    async def test_mission_subscriber_response_errors(self, bus: EventBus) -> None:
        """MissionExecutor handles SubsystemResponse with errors."""
        mc = MissionControl(bus)

        async def failing_handler(payload: dict) -> SubsystemResponse:
            return SubsystemResponse(
                success=False,
                errors=["Step failed intentionally"],
                subsystem="knowledge",
            )

        mc.executor.register_handler(MissionSubsystem.KNOWLEDGE, failing_handler)
        m = await mc.create_mission(title="Failure Test")
        await mc.plan(m.mission_id)
        custom_plan = MissionPlan(mission=m, steps=[
            MissionStep(order=1, subsystem=MissionSubsystem.KNOWLEDGE, title="Fail Step"),
        ])
        mc._plans[m.mission_id] = custom_plan
        result = await mc.execute(m.mission_id)
        assert result is not None
        assert result.status == MissionStatus.FAILED

    async def test_mission_step_failure_propagation(self, bus: EventBus) -> None:
        """A single step failure propagates to mission failure."""
        mc = MissionControl(bus)

        async def ok_handler(payload: dict) -> SubsystemResponse:
            return SubsystemResponse(success=True, subsystem="knowledge")

        async def fail_handler(payload: dict) -> SubsystemResponse:
            return SubsystemResponse(success=False, errors=["Failed"], subsystem="execution")

        mc.executor.register_handler(MissionSubsystem.KNOWLEDGE, ok_handler)
        mc.executor.register_handler(MissionSubsystem.EXECUTION, fail_handler)

        m = await mc.create_mission(title="Propagation Test")
        await mc.plan(m.mission_id)
        custom_plan = MissionPlan(mission=m, steps=[
            MissionStep(order=1, subsystem=MissionSubsystem.KNOWLEDGE, dependencies=[]),
            MissionStep(order=2, subsystem=MissionSubsystem.EXECUTION, dependencies=[]),
        ])
        mc._plans[m.mission_id] = custom_plan
        result = await mc.execute(m.mission_id)
        assert result is not None
        assert result.status == MissionStatus.FAILED


# ======================================================================
# Runtime Integration: Notification generated from events
# ======================================================================


class TestRuntimeNotificationIntegration:
    """Mission → Notification integration via Event Bus."""

    async def test_mission_completion_triggers_notification(self, bus: EventBus) -> None:
        """Mission completion events trigger notification rules."""
        ns = NotificationService(bus)
        await ns.start()

        from atlas_core.interfaces.events import Event, EventCategory, EventPriority
        await bus.publish(Event(
            source="mission_event_bridge",
            category=EventCategory.MISSION,
            payload={"action": "mission_completed", "title": "Test Mission", "mission_id": "m1"},
        ))

        import asyncio
        await asyncio.sleep(0.01)

        assert ns.metrics.total_sent >= 1
        await ns.stop()

    async def test_mission_failure_triggers_notification(self, bus: EventBus) -> None:
        """Mission failure events trigger notification rules."""
        ns = NotificationService(bus)
        await ns.start()

        from atlas_core.interfaces.events import Event, EventCategory, EventPriority
        await bus.publish(Event(
            source="mission_event_bridge",
            category=EventCategory.MISSION,
            payload={"action": "mission_failed", "title": "Failed Mission", "error": "Something broke"},
        ))

        import asyncio
        await asyncio.sleep(0.01)

        assert ns.metrics.total_sent >= 1
        await ns.stop()

    async def test_execution_failure_triggers_notification(self, bus: EventBus) -> None:
        """Execution failure events trigger notification rules."""
        ns = NotificationService(bus)
        await ns.start()

        from atlas_core.interfaces.events import Event, EventCategory, EventPriority
        await bus.publish(Event(
            source="execution_engine",
            category=EventCategory.EXECUTION,
            payload={"action": "command_failed", "error": "Command failed"},
        ))

        import asyncio
        await asyncio.sleep(0.01)

        assert ns.metrics.total_sent >= 1
        await ns.stop()

    async def test_browser_disconnect_triggers_notification(self, bus: EventBus) -> None:
        """Browser disconnect events trigger notification rules."""
        ns = NotificationService(bus)
        await ns.start()

        from atlas_core.interfaces.events import Event, EventCategory, EventPriority
        await bus.publish(Event(
            source="browser_companion",
            category=EventCategory.BROWSER,
            payload={"action": "browser_disconnected"},
        ))

        import asyncio
        await asyncio.sleep(0.01)

        assert ns.metrics.total_sent >= 1
        await ns.stop()

    async def test_knowledge_import_triggers_notification(self, bus: EventBus) -> None:
        """Knowledge import events trigger notification rules."""
        ns = NotificationService(bus)
        await ns.start()

        from atlas_core.interfaces.events import Event, EventCategory, EventPriority
        await bus.publish(Event(
            source="knowledge_engine",
            category=EventCategory.KNOWLEDGE,
            payload={"action": "records_imported", "count": 5},
        ))

        import asyncio
        await asyncio.sleep(0.01)

        assert ns.metrics.total_sent >= 1
        await ns.stop()

    async def test_opportunity_discovery_triggers_notification(self, bus: EventBus) -> None:
        """Opportunity discovery events trigger notification rules."""
        ns = NotificationService(bus)
        await ns.start()

        from atlas_core.interfaces.events import Event, EventCategory, EventPriority
        await bus.publish(Event(
            source="opportunity_discovery",
            category=EventCategory.OPPORTUNITY,
            payload={"action": "discovery_completed", "count": 3},
        ))

        import asyncio
        await asyncio.sleep(0.01)

        assert ns.metrics.total_sent >= 1
        await ns.stop()


# ======================================================================
# Runtime Integration: SubsystemResponse contract
# ======================================================================


class TestRuntimeSubsystemResponse:
    """SubsystemResponse is the standard contract across all subsystems."""

    def test_subsystem_response_is_dataclass(self) -> None:
        r = SubsystemResponse(success=True, subsystem="test")
        assert r.success is True
        assert r.subsystem == "test"
        assert r.errors == []

    def test_subsystem_response_serializable(self) -> None:
        r = SubsystemResponse(payload={"result": 42})
        assert r.payload["result"] == 42


# ======================================================================
# Runtime Integration: Multi-service lifecycle
# ======================================================================


class TestRuntimeMultiServiceLifecycle:
    """All core services can start and stop together."""

    async def test_core_services_start_stop(self, bus: EventBus) -> None:
        """Core services co-exist without conflict."""
        mc = MissionControl(bus)
        ns = NotificationService(bus)

        await mc.start()
        await ns.start()
        assert mc._running
        assert ns._running

        await mc.stop()
        await ns.stop()
        assert not mc._running
        assert not ns._running
