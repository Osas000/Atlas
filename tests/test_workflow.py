"""Comprehensive tests for the Workflow Engine."""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from atlas_core.interfaces import SubsystemResponse
from atlas_core.interfaces.events import EventCategory
from atlas_core.workflow import (
    HistoryEntry,
    Priority,
    QueueItem,
    ValidationResult,
    Workflow,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowEventBridge,
    WorkflowExecutor,
    WorkflowHistory,
    WorkflowMetrics,
    WorkflowScheduler,
    WorkflowState,
    WorkflowStep,
    WorkflowValidator,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def sample_step() -> WorkflowStep:
    return WorkflowStep(
        step_id="s1",
        name="Step One",
        action="process",
    )


@pytest.fixture
def sample_workflow(sample_step: WorkflowStep) -> Workflow:
    return Workflow(
        workflow_id="wf1",
        name="Test Workflow",
        description="A test workflow",
        steps=(sample_step,),
        metadata={"author": "tester"},
    )


@pytest.fixture
def multi_step_workflow() -> Workflow:
    return Workflow(
        workflow_id="wf_multi",
        name="Multi Step",
        steps=(
            WorkflowStep(step_id="s1", name="First", action="init"),
            WorkflowStep(step_id="s2", name="Second", action="process", dependencies=("s1",)),
            WorkflowStep(step_id="s3", name="Third", action="finalize", dependencies=("s2",)),
        ),
    )


@pytest.fixture
def definitions() -> WorkflowDefinition:
    return WorkflowDefinition()


@pytest.fixture
def validator() -> WorkflowValidator:
    return WorkflowValidator()


@pytest.fixture
def scheduler() -> WorkflowScheduler:
    return WorkflowScheduler()


@pytest.fixture
def executor() -> WorkflowExecutor:
    return WorkflowExecutor()


@pytest.fixture
def history() -> WorkflowHistory:
    return WorkflowHistory()


@pytest.fixture
def metrics() -> WorkflowMetrics:
    return WorkflowMetrics()


@pytest.fixture
def engine() -> WorkflowEngine:
    from atlas_core.events import EventBus
    return WorkflowEngine(EventBus())


# ======================================================================
# WorkflowState
# ======================================================================


class TestWorkflowState:
    def test_enum_values(self) -> None:
        assert len(WorkflowState) == 9
        assert WorkflowState.CREATED.name == "CREATED"
        assert WorkflowState.VALIDATING.name == "VALIDATING"
        assert WorkflowState.READY.name == "READY"
        assert WorkflowState.RUNNING.name == "RUNNING"
        assert WorkflowState.WAITING.name == "WAITING"
        assert WorkflowState.PAUSED.name == "PAUSED"
        assert WorkflowState.FAILED.name == "FAILED"
        assert WorkflowState.COMPLETED.name == "COMPLETED"
        assert WorkflowState.CANCELLED.name == "CANCELLED"


# ======================================================================
# WorkflowStep
# ======================================================================


class TestWorkflowStep:
    def test_frozen(self) -> None:
        s = WorkflowStep(step_id="s1", name="S1", action="act")
        with pytest.raises(AttributeError):
            s.name = "S2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        s = WorkflowStep(step_id="s1", name="S1", action="act")
        assert s.dependencies == ()
        assert s.connector == ""
        assert s.timeout == 60.0
        assert s.retry_count == 0
        assert s.payload == {}
        assert s.metadata == {}

    def test_full(self) -> None:
        s = WorkflowStep(
            step_id="s1", name="S1", action="act",
            dependencies=("s0",), connector="gh",
            timeout=30.0, retry_count=3,
            payload={"key": "val"}, metadata={"env": "test"},
        )
        assert s.step_id == "s1"
        assert "s0" in s.dependencies
        assert s.connector == "gh"
        assert s.timeout == 30.0
        assert s.retry_count == 3


# ======================================================================
# Workflow
# ======================================================================


class TestWorkflow:
    def test_frozen(self) -> None:
        w = Workflow(workflow_id="w1", name="W1")
        with pytest.raises(AttributeError):
            w.name = "W2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        w = Workflow(workflow_id="w1", name="W1")
        assert w.description == ""
        assert w.steps == ()
        assert w.state == WorkflowState.CREATED
        assert w.metadata == {}

    def test_full(self, sample_step: WorkflowStep) -> None:
        w = Workflow(
            workflow_id="w1", name="W1",
            description="desc", steps=(sample_step,),
            state=WorkflowState.READY, metadata={"key": "val"},
        )
        assert w.workflow_id == "w1"
        assert w.name == "W1"
        assert w.description == "desc"
        assert len(w.steps) == 1
        assert w.state == WorkflowState.READY


# ======================================================================
# WorkflowDefinition
# ======================================================================


class TestWorkflowDefinition:
    async def test_register(self, definitions: WorkflowDefinition, sample_workflow: Workflow) -> None:
        await definitions.register(sample_workflow)
        assert definitions.get("wf1") is sample_workflow

    async def test_register_duplicate_raises(self, definitions: WorkflowDefinition, sample_workflow: Workflow) -> None:
        await definitions.register(sample_workflow)
        with pytest.raises(ValueError, match="already registered"):
            await definitions.register(sample_workflow)

    async def test_unregister(self, definitions: WorkflowDefinition, sample_workflow: Workflow) -> None:
        await definitions.register(sample_workflow)
        result = await definitions.unregister("wf1")
        assert result is sample_workflow
        assert definitions.get("wf1") is None

    async def test_unregister_missing(self, definitions: WorkflowDefinition) -> None:
        result = await definitions.unregister("nonexistent")
        assert result is None

    async def test_list(self, definitions: WorkflowDefinition, sample_workflow: Workflow) -> None:
        assert definitions.list() == []
        await definitions.register(sample_workflow)
        assert len(definitions.list()) == 1

    async def test_clone(self, definitions: WorkflowDefinition, sample_workflow: Workflow) -> None:
        await definitions.register(sample_workflow)
        cloned = definitions.clone("wf1", "wf_clone")
        assert cloned is not None
        assert cloned.workflow_id == "wf_clone"
        assert cloned.name == sample_workflow.name
        assert cloned.state == WorkflowState.CREATED
        assert cloned.metadata.get("cloned_from") == "wf1"

    async def test_clone_nonexistent(self, definitions: WorkflowDefinition) -> None:
        cloned = definitions.clone("missing")
        assert cloned is None

    async def test_clone_generates_id(self, definitions: WorkflowDefinition, sample_workflow: Workflow) -> None:
        await definitions.register(sample_workflow)
        cloned = definitions.clone("wf1")
        assert cloned is not None
        assert cloned.workflow_id.startswith("wf1_clone_")


# ======================================================================
# WorkflowValidator
# ======================================================================


class TestWorkflowValidator:
    def test_valid_workflow(self, validator: WorkflowValidator, sample_workflow: Workflow) -> None:
        result = validator.validate(sample_workflow)
        assert result.valid is True
        assert result.errors == []

    def test_missing_id(self, validator: WorkflowValidator) -> None:
        w = Workflow(workflow_id="", name="Test")
        result = validator.validate(w)
        assert result.valid is False
        assert "Workflow ID is required" in result.errors

    def test_missing_name(self, validator: WorkflowValidator) -> None:
        w = Workflow(workflow_id="w1", name="")
        result = validator.validate(w)
        assert result.valid is False
        assert "Workflow name is required" in result.errors

    def test_no_steps(self, validator: WorkflowValidator) -> None:
        w = Workflow(workflow_id="w1", name="Test")
        result = validator.validate(w)
        assert result.valid is False
        assert "at least one step" in result.errors[0]

    def test_duplicate_step_ids(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(
                WorkflowStep(step_id="s1", name="A", action="act"),
                WorkflowStep(step_id="s1", name="B", action="act"),
            ),
        )
        result = validator.validate(w)
        assert result.valid is False
        assert "Duplicate step ID" in result.errors[0]

    def test_missing_step_name(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(WorkflowStep(step_id="s1", name="", action="act"),),
        )
        result = validator.validate(w)
        assert "name is required" in result.errors[0]

    def test_missing_step_action(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(WorkflowStep(step_id="s1", name="S1", action=""),),
        )
        result = validator.validate(w)
        assert "action is required" in result.errors[0]

    def test_negative_timeout(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(WorkflowStep(step_id="s1", name="S1", action="act", timeout=-1),),
        )
        result = validator.validate(w)
        assert "timeout must be positive" in result.errors[0]

    def test_negative_retry(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(WorkflowStep(step_id="s1", name="S1", action="act", retry_count=-1),),
        )
        result = validator.validate(w)
        assert "retry_count must be non-negative" in result.errors[0]

    def test_missing_dependency(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(WorkflowStep(step_id="s1", name="S1", action="act", dependencies=("missing",)),),
        )
        result = validator.validate(w)
        assert "missing dependency" in result.errors[0]

    def test_circular_dependency(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(
                WorkflowStep(step_id="s1", name="A", action="act", dependencies=("s2",)),
                WorkflowStep(step_id="s2", name="B", action="act", dependencies=("s1",)),
            ),
        )
        result = validator.validate(w)
        assert result.valid is False
        assert "circular dependency" in result.errors[0]

    def test_self_reference_dependency(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(WorkflowStep(step_id="s1", name="A", action="act", dependencies=("s1",)),),
        )
        result = validator.validate(w)
        assert result.valid is False

    def test_valid_transition(self, validator: WorkflowValidator) -> None:
        result = validator.validate_transition(WorkflowState.CREATED, WorkflowState.VALIDATING)
        assert result.valid is True

    def test_invalid_transition(self, validator: WorkflowValidator) -> None:
        result = validator.validate_transition(WorkflowState.CREATED, WorkflowState.COMPLETED)
        assert result.valid is False
        assert "Cannot transition" in result.errors[0]

    def test_all_transitions(self, validator: WorkflowValidator) -> None:
        assert validator.validate_transition(WorkflowState.CREATED, WorkflowState.VALIDATING).valid
        assert validator.validate_transition(WorkflowState.VALIDATING, WorkflowState.READY).valid
        assert validator.validate_transition(WorkflowState.VALIDATING, WorkflowState.FAILED).valid
        assert validator.validate_transition(WorkflowState.READY, WorkflowState.RUNNING).valid
        assert validator.validate_transition(WorkflowState.READY, WorkflowState.CANCELLED).valid
        assert validator.validate_transition(WorkflowState.RUNNING, WorkflowState.PAUSED).valid
        assert validator.validate_transition(WorkflowState.RUNNING, WorkflowState.COMPLETED).valid
        assert validator.validate_transition(WorkflowState.RUNNING, WorkflowState.FAILED).valid
        assert validator.validate_transition(WorkflowState.RUNNING, WorkflowState.WAITING).valid
        assert validator.validate_transition(WorkflowState.WAITING, WorkflowState.RUNNING).valid
        assert validator.validate_transition(WorkflowState.WAITING, WorkflowState.CANCELLED).valid
        assert validator.validate_transition(WorkflowState.PAUSED, WorkflowState.RUNNING).valid
        assert validator.validate_transition(WorkflowState.PAUSED, WorkflowState.CANCELLED).valid

    def test_terminal_state_transitions(self, validator: WorkflowValidator) -> None:
        for terminal in (WorkflowState.FAILED, WorkflowState.COMPLETED, WorkflowState.CANCELLED):
            result = validator.validate_transition(terminal, WorkflowState.READY)
            assert result.valid is False


# ======================================================================
# WorkflowScheduler
# ======================================================================


class TestWorkflowScheduler:
    async def test_enqueue_dequeue(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.enqueue("wf1")
        result = await scheduler.dequeue()
        assert result == "wf1"

    async def test_dequeue_empty(self, scheduler: WorkflowScheduler) -> None:
        result = await scheduler.dequeue()
        assert result is None

    async def test_priority_ordering(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.enqueue("low", Priority.LOW)
        await scheduler.enqueue("critical", Priority.CRITICAL)
        await scheduler.enqueue("normal", Priority.NORMAL)
        assert await scheduler.dequeue() == "critical"
        assert await scheduler.dequeue() == "normal"
        assert await scheduler.dequeue() == "low"

    async def test_pause(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.enqueue("wf1")
        assert await scheduler.is_paused("wf1") is False
        await scheduler.pause("wf1")
        assert await scheduler.is_paused("wf1") is True

    async def test_pause_cancelled_returns_false(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.cancel("wf1")
        result = await scheduler.pause("wf1")
        assert result is False

    async def test_resume(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.pause("wf1")
        assert await scheduler.is_paused("wf1") is True
        result = await scheduler.resume("wf1")
        assert result is True
        assert await scheduler.is_paused("wf1") is False

    async def test_resume_cancelled_returns_false(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.cancel("wf1")
        result = await scheduler.resume("wf1")
        assert result is False

    async def test_cancel(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.enqueue("wf1")
        result = await scheduler.cancel("wf1")
        assert result is True
        assert await scheduler.is_cancelled("wf1") is True
        result = await scheduler.dequeue()
        assert result is None  # cancelled item removed from queue

    async def test_cancel_paused(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.pause("wf1")
        await scheduler.cancel("wf1")
        assert await scheduler.is_cancelled("wf1") is True
        assert await scheduler.is_paused("wf1") is False

    async def test_queue_size(self, scheduler: WorkflowScheduler) -> None:
        assert scheduler.queue_size == 0
        await scheduler.enqueue("wf1")
        await scheduler.enqueue("wf2")
        assert scheduler.queue_size == 2

    async def test_list_paused(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.pause("wf1")
        await scheduler.pause("wf2")
        assert "wf1" in scheduler.list_paused()
        assert "wf2" in scheduler.list_paused()

    async def test_list_cancelled(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.cancel("wf1")
        assert "wf1" in scheduler.list_cancelled()


# ======================================================================
# WorkflowExecutor
# ======================================================================


class TestWorkflowExecutor:
    async def test_execute_step_basic(self, executor: WorkflowExecutor, sample_step: WorkflowStep) -> None:
        response = await executor.execute_step("wf1", sample_step)
        assert response.success is True
        assert response.status == "completed"
        assert response.payload["step_id"] == "s1"

    async def test_execute_step_with_connector(self, sample_step: WorkflowStep) -> None:
        class FakeConnectorManager:
            async def execute(self, connector_id: str, operation: str, **kwargs: Any) -> dict[str, Any]:
                return {"connector_result": "ok"}
        executor = WorkflowExecutor(connector_manager=FakeConnectorManager())
        step = WorkflowStep(step_id="s1", name="S1", action="read", connector="fs")
        response = await executor.execute_step("wf1", step)
        assert response.success is True
        assert response.payload["result"]["connector_result"] == "ok"

    async def test_execute_step_notification(self) -> None:
        sent: list = []
        class FakeNotificationService:
            async def send(self, message: str, channel: str) -> None:
                sent.append((message, channel))
        executor = WorkflowExecutor(notification_service=FakeNotificationService())
        step = WorkflowStep(step_id="s1", name="S1", action="notify", payload={"message": "hello", "channel": "email"})
        response = await executor.execute_step("wf1", step)
        assert response.success is True
        assert len(sent) == 1
        assert sent[0] == ("hello", "email")

    async def test_execute_step_with_retry_success(self) -> None:
        attempts: list = []
        class FailThenSucceedConnector:
            async def execute(self, connector_id: str, operation: str, **kwargs: Any) -> dict[str, Any]:
                attempts.append(1)
                if len(attempts) < 2:
                    raise RuntimeError("first attempt fails")
                return {"result": "ok"}
        executor = WorkflowExecutor(connector_manager=FailThenSucceedConnector())
        step = WorkflowStep(step_id="s1", name="S1", action="read", connector="fs", retry_count=3)
        response = await executor.execute_step("wf1", step)
        assert response.success is True
        assert len(attempts) == 2

    async def test_execute_step_retry_exhausted(self) -> None:
        class AlwaysFailsConnector:
            async def execute(self, connector_id: str, operation: str, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("always fails")
        executor = WorkflowExecutor(connector_manager=AlwaysFailsConnector())
        step = WorkflowStep(step_id="s1", name="S1", action="read", connector="fs", retry_count=2)
        response = await executor.execute_step("wf1", step)
        assert response.success is False
        assert "failed after" in response.errors[0]

    async def test_execute_step_no_retry_on_failure(self) -> None:
        class FailingConnector:
            async def execute(self, connector_id: str, operation: str, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("fail")
        executor = WorkflowExecutor(connector_manager=FailingConnector())
        step = WorkflowStep(step_id="s1", name="S1", action="read", connector="fs", retry_count=0)
        response = await executor.execute_step("wf1", step)
        assert response.success is False

    async def test_execute_step_with_mission(self) -> None:
        class FakeMissionControl:
            async def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
                return {"mission_executed": True}
        executor = WorkflowExecutor(mission_control=FakeMissionControl())
        step = WorkflowStep(step_id="s1", name="S1", action="mission", payload={"id": 1})
        response = await executor.execute_step("wf1", step)
        assert response.success is True


# ======================================================================
# WorkflowHistory
# ======================================================================


class TestWorkflowHistory:
    async def test_record_and_get(self, history: WorkflowHistory) -> None:
        entry = HistoryEntry(workflow_id="wf1", event="started")
        await history.record(entry)
        entries = await history.get_history("wf1")
        assert len(entries) == 1
        assert entries[0].event == "started"

    async def test_get_all(self, history: WorkflowHistory) -> None:
        await history.record(HistoryEntry(workflow_id="wf1", event="a"))
        await history.record(HistoryEntry(workflow_id="wf2", event="b"))
        entries = await history.get_history()
        assert len(entries) == 2

    async def test_get_limit(self, history: WorkflowHistory) -> None:
        for i in range(10):
            await history.record(HistoryEntry(workflow_id="wf1", event=f"e{i}"))
        entries = await history.get_history("wf1", limit=3)
        assert len(entries) == 3

    async def test_clear_all(self, history: WorkflowHistory) -> None:
        await history.record(HistoryEntry(workflow_id="wf1", event="a"))
        await history.clear()
        assert history.size == 0

    async def test_clear_specific(self, history: WorkflowHistory) -> None:
        await history.record(HistoryEntry(workflow_id="wf1", event="a"))
        await history.record(HistoryEntry(workflow_id="wf2", event="b"))
        await history.clear("wf1")
        entries = await history.get_history()
        assert len(entries) == 1
        assert entries[0].workflow_id == "wf2"

    async def test_max_size(self, history: WorkflowHistory) -> None:
        assert history.max_size == 1000

    async def test_ring_buffer_enforced(self) -> None:
        h = WorkflowHistory(max_size=3)
        for i in range(5):
            await h.record(HistoryEntry(workflow_id="wf1", event=f"e{i}"))
        assert h.size == 3

    async def test_size(self, history: WorkflowHistory) -> None:
        assert history.size == 0
        await history.record(HistoryEntry(workflow_id="wf1", event="e"))
        assert history.size == 1


# ======================================================================
# WorkflowMetrics
# ======================================================================


class TestWorkflowMetrics:
    async def test_initial(self, metrics: WorkflowMetrics) -> None:
        assert metrics.created == 0
        assert metrics.completed == 0
        assert metrics.failed == 0
        assert metrics.cancelled == 0
        assert metrics.average_runtime == 0.0
        assert metrics.active == 0
        assert metrics.step_count == 0
        assert metrics.retry_count == 0

    async def test_record_created(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_created()
        assert metrics.created == 1

    async def test_record_completed(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_completed(10.0)
        assert metrics.completed == 1
        assert metrics.average_runtime == 10.0

    async def test_record_failed(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_failed()
        assert metrics.failed == 1

    async def test_record_cancelled(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_cancelled()
        assert metrics.cancelled == 1

    async def test_active(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_created()
        assert metrics.active == 1
        await metrics.record_completed()
        assert metrics.active == 0

    async def test_record_step(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_step()
        assert metrics.step_count == 1

    async def test_record_retry(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_retry()
        assert metrics.retry_count == 1

    async def test_average_runtime_multiple(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_completed(2.0)
        await metrics.record_completed(4.0)
        assert metrics.average_runtime == 3.0

    async def test_snapshot(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_created()
        await metrics.record_step()
        snap = metrics.snapshot()
        assert snap["created"] == 1
        assert snap["step_count"] == 1
        assert snap["active"] == 1


# ======================================================================
# WorkflowEventBridge
# ======================================================================


class TestWorkflowEventBridge:
    @pytest.fixture
    def event_bus(self) -> Any:
        from atlas_core.events import EventBus
        return EventBus()

    @pytest.fixture
    def bridge(self, event_bus: Any) -> WorkflowEventBridge:
        return WorkflowEventBridge(event_bus)

    async def receive(self, event_bus: Any) -> list:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("workflow", handler)
        return received

    async def test_workflow_created(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.workflow_created("wf1")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "WORKFLOW_CREATED"

    async def test_workflow_started(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.workflow_started("wf1")
        assert len(received) == 1

    async def test_workflow_paused(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.workflow_paused("wf1")
        assert len(received) == 1

    async def test_workflow_resumed(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.workflow_resumed("wf1")
        assert len(received) == 1

    async def test_workflow_completed(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.workflow_completed("wf1")
        assert len(received) == 1

    async def test_workflow_failed(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.workflow_failed("wf1", "error")
        assert len(received) == 1

    async def test_workflow_cancelled(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.workflow_cancelled("wf1")
        assert len(received) == 1

    async def test_step_started(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.step_started("wf1", "s1")
        assert len(received) == 1

    async def test_step_completed(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.step_completed("wf1", "s1")
        assert len(received) == 1

    async def test_step_failed(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.step_failed("wf1", "s1", "err")
        assert len(received) == 1

    async def test_publish_creates_event(self, bridge: WorkflowEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.publish("TEST", "wf1", key="val")
        assert len(received) == 1
        assert received[0].category == EventCategory.WORKFLOW
        assert received[0].source == "workflow_engine"
        assert received[0].payload["key"] == "val"

    async def test_publish_no_failure(self) -> None:
        class FakeBus:
            async def publish(self, event: Any) -> None:
                raise RuntimeError("bus down")
        bridge = WorkflowEventBridge(FakeBus())
        await bridge.publish("TEST", "wf1")


# ======================================================================
# WorkflowEngine (IService)
# ======================================================================


class TestWorkflowEngine:
    async def test_name(self, engine: WorkflowEngine) -> None:
        assert engine.name == "workflow_engine"

    async def test_iservice_lifecycle(self, engine: WorkflowEngine) -> None:
        await engine.initialize()
        await engine.start()
        await engine.stop()

    async def test_create_workflow(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        wf = await engine.create_workflow(sample_workflow)
        assert wf.state == WorkflowState.READY
        assert wf.workflow_id == "wf1"

    async def test_create_workflow_duplicate_raises(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        with pytest.raises(ValueError, match="already exists"):
            await engine.create_workflow(sample_workflow)

    async def test_create_workflow_invalid_raises(self, engine: WorkflowEngine) -> None:
        w = Workflow(workflow_id="", name="")
        with pytest.raises(ValueError, match="Invalid workflow"):
            await engine.create_workflow(w)

    async def test_register_definition(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.register_definition(sample_workflow)
        assert engine.definitions.get("wf1") is sample_workflow

    async def test_register_definition_invalid_raises(self, engine: WorkflowEngine) -> None:
        w = Workflow(workflow_id="", name="")
        with pytest.raises(ValueError, match="Invalid definition"):
            await engine.register_definition(w)

    async def test_execute(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        await engine.execute("wf1")
        # Workflow should be enqueued — worker processes it if started

    async def test_execute_nonexistent_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(ValueError, match="Workflow not found"):
            await engine.execute("missing")

    async def test_pause(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        await engine.execute("wf1")
        result = await engine.pause("wf1")
        assert result is True

    async def test_pause_not_found_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(ValueError, match="Workflow not found"):
            await engine.pause("missing")

    async def test_pause_not_running(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        result = await engine.pause("wf1")
        assert result is False

    async def test_resume(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        await engine.execute("wf1")
        await engine.pause("wf1")
        result = await engine.resume("wf1")
        assert result is True

    async def test_resume_not_found_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(ValueError, match="Workflow not found"):
            await engine.resume("missing")

    async def test_resume_not_paused(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        result = await engine.resume("wf1")
        assert result is False

    async def test_cancel(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        await engine.execute("wf1")
        result = await engine.cancel("wf1")
        assert result is True

    async def test_cancel_not_found_raises(self, engine: WorkflowEngine) -> None:
        with pytest.raises(ValueError, match="Workflow not found"):
            await engine.cancel("missing")

    async def test_cancel_terminal_state(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        w = Workflow(workflow_id="w", name="W", state=WorkflowState.COMPLETED)
        engine._workflows["w"] = w
        result = await engine.cancel("w")
        assert result is False

    async def test_validate(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        result = engine.validate(sample_workflow)
        assert result.valid is True

    async def test_history_empty(self, engine: WorkflowEngine) -> None:
        entries = await engine.history()
        assert entries == []

    async def test_history_after_create(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        entries = await engine.history("wf1")
        assert len(entries) == 1
        assert entries[0].event == "created"

    async def test_metrics(self, engine: WorkflowEngine) -> None:
        m = engine.metrics()
        assert m["created"] == 0
        assert m["completed"] == 0

    async def test_metrics_after_create(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.create_workflow(sample_workflow)
        m = engine.metrics()
        assert m["created"] == 1

    async def test_health_check(self, engine: WorkflowEngine) -> None:
        health = await engine.health_check()
        assert health.healthy is True
        assert "Workflow Engine" in health.message
        assert health.metadata["workflows"] == 0

    async def test_full_execution_flow(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        await engine.initialize()
        await engine.start()
        await engine.create_workflow(sample_workflow)
        await engine.execute("wf1")
        await asyncio.sleep(0.3)
        await engine.stop()
        entries = await engine.history("wf1")
        events = [e.event for e in entries]
        assert "completed" in events

    async def test_full_execution_multi_step(self, engine: WorkflowEngine, multi_step_workflow: Workflow) -> None:
        await engine.initialize()
        await engine.start()
        await engine.create_workflow(multi_step_workflow)
        await engine.execute("wf_multi")
        await asyncio.sleep(0.3)
        await engine.stop()
        entries = await engine.history("wf_multi")
        events = [e.event for e in entries]
        assert "completed" in events

    async def test_workflow_fails_on_step_error(self, engine: WorkflowEngine) -> None:
        step = WorkflowStep(step_id="s1", name="Fail", action="crash")
        w = Workflow(workflow_id="wf_fail", name="FailWF", steps=(step,))
        await engine.initialize()
        await engine.start()
        await engine.create_workflow(w)
        await engine.execute("wf_fail")

        class FailingExecutor:
            async def execute_step(self, workflow_id: str, step: WorkflowStep) -> SubsystemResponse:
                return SubsystemResponse(
                    success=False, status="failed",
                    errors=["step failed"],
                    subsystem="test",
                )

        engine._executor = FailingExecutor()
        await asyncio.sleep(0.3)
        await engine.stop()
        entries = await engine.history("wf_fail")
        events = [e.event for e in entries]
        assert "failed" in events

    async def test_workflow_cancelled_during_execution(self, engine: WorkflowEngine, sample_workflow: Workflow) -> None:
        step = WorkflowStep(step_id="s1", name="Slow", action="delay")
        w = Workflow(workflow_id="wf_cancel", name="CancelWF", steps=(step,))
        await engine.initialize()
        await engine.start()
        await engine.create_workflow(w)
        await engine.execute("wf_cancel")
        await engine.cancel("wf_cancel")
        await asyncio.sleep(0.1)
        await engine.stop()
        wf = engine._workflows.get("wf_cancel")
        assert wf is not None
        assert wf.state == WorkflowState.CANCELLED

    async def test_definitions_property(self, engine: WorkflowEngine) -> None:
        assert engine.definitions is not None


# ======================================================================
# Kernel Integration
# ======================================================================


class TestKernelIntegration:
    @pytest.fixture
    def kernel(self, tmp_path: Path):
        from atlas_core.kernel import AtlasKernel
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "default.yaml").write_text(
            "app_name: TestKernel\n"
            "version: 9.9.9\n"
            "log_level: DEBUG\n"
            "log_dir: '" + str(tmp_path / "logs").replace("\\", "\\\\") + "'\n"
        )
        return AtlasKernel(config_dir)

    async def test_kernel_boot_registers_workflow_engine(self, kernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.registry.count == 15
        assert kernel.workflow_engine is not None
        from atlas_core.workflow import WorkflowEngine
        assert isinstance(kernel.workflow_engine, WorkflowEngine)

    async def test_kernel_before_init_raises(self):
        from atlas_core.kernel import AtlasKernel
        k = AtlasKernel()
        with pytest.raises(RuntimeError):
            _ = k.workflow_engine

    async def test_workflow_engine_property(self, kernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.workflow_engine is not None
        assert isinstance(kernel.workflow_engine, WorkflowEngine)


# ======================================================================
# Thread Safety & Concurrency
# ======================================================================


class TestThreadSafety:
    async def test_scheduler_concurrent_enqueue(self, scheduler: WorkflowScheduler) -> None:
        async def enqueue_many() -> None:
            for i in range(50):
                await scheduler.enqueue(f"wf_{i}")
        async def dequeue_many() -> None:
            for _ in range(50):
                await scheduler.dequeue()
        await asyncio.gather(enqueue_many(), dequeue_many())

    async def test_metrics_concurrent(self, metrics: WorkflowMetrics) -> None:
        async def record() -> None:
            for _ in range(100):
                await metrics.record_created()
                await metrics.record_completed(1.0)
        async def read() -> None:
            for _ in range(100):
                _ = metrics.created
                _ = metrics.average_runtime
                _ = metrics.snapshot()
        await asyncio.gather(record(), read())
        assert metrics.created == 100
        assert metrics.completed == 100

    async def test_history_concurrent(self, history: WorkflowHistory) -> None:
        async def write() -> None:
            for i in range(50):
                await history.record(HistoryEntry(workflow_id="wf1", event=f"e{i}"))
        async def read() -> None:
            for _ in range(50):
                await history.get_history("wf1")
        await asyncio.gather(write(), read())

    async def test_definitions_concurrent(self, definitions: WorkflowDefinition) -> None:
        w = Workflow(workflow_id="w", name="W", steps=(WorkflowStep(step_id="s1", name="S", action="act"),))
        await definitions.register(w)
        async def access() -> None:
            for _ in range(50):
                _ = definitions.get("w")
                _ = definitions.list()
                definitions.clone("w")
        async def modify() -> None:
            for _ in range(10):
                await definitions.unregister("w")
                w2 = Workflow(workflow_id="w", name="W2", steps=(WorkflowStep(step_id="s1", name="S", action="act"),))
                await definitions.register(w2)
        await asyncio.gather(access(), modify())


# ======================================================================
# Edge Cases & Failure Paths
# ======================================================================


class TestEdgeCases:
    def test_validation_result_defaults(self) -> None:
        r = ValidationResult()
        assert r.valid is True
        assert r.errors == []
        assert r.warnings == []

    def test_queue_item_defaults(self) -> None:
        item = QueueItem(workflow_id="wf1")
        assert item.priority == Priority.NORMAL
        assert item.workflow_id == "wf1"

    def test_history_entry_defaults(self) -> None:
        e = HistoryEntry(workflow_id="wf1", event="test")
        assert e.step_id == ""
        assert e.message == ""

    async def test_executor_no_services(self, executor: WorkflowExecutor) -> None:
        step = WorkflowStep(step_id="s1", name="S", action="anything", connector="missing")
        response = await executor.execute_step("wf1", step)
        assert response.success is True

    async def test_workflow_with_no_steps(self, engine: WorkflowEngine) -> None:
        w = Workflow(workflow_id="empty", name="Empty", steps=())
        with pytest.raises(ValueError):
            await engine.create_workflow(w)

    async def test_engine_stop_without_start(self, engine: WorkflowEngine) -> None:
        await engine.stop()

    async def test_engine_double_start(self, engine: WorkflowEngine) -> None:
        await engine.start()
        await engine.start()

    async def test_engine_double_stop(self, engine: WorkflowEngine) -> None:
        await engine.start()
        await engine.stop()
        await engine.stop()

    async def test_scheduler_priority_same_level(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.enqueue("a", Priority.NORMAL)
        await scheduler.enqueue("b", Priority.NORMAL)
        r1 = await scheduler.dequeue()
        r2 = await scheduler.dequeue()
        assert r1 == "a"
        assert r2 == "b"

    async def test_cancel_already_cancelled(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.cancel("wf1")
        result = await scheduler.cancel("wf1")
        assert result is True

    async def test_pause_not_enqueued(self, scheduler: WorkflowScheduler) -> None:
        result = await scheduler.pause("wf1")
        assert result is True
        assert await scheduler.is_paused("wf1") is True

    async def test_workflow_history_filters_by_id(self, history: WorkflowHistory) -> None:
        await history.record(HistoryEntry(workflow_id="a", event="e1"))
        await history.record(HistoryEntry(workflow_id="b", event="e2"))
        entries = await history.get_history("a")
        assert all(e.workflow_id == "a" for e in entries)

    async def test_metrics_active_calculation(self, metrics: WorkflowMetrics) -> None:
        await metrics.record_created()
        await metrics.record_created()
        await metrics.record_created()
        assert metrics.active == 3
        await metrics.record_completed()
        assert metrics.active == 2
        await metrics.record_failed()
        assert metrics.active == 1
        await metrics.record_cancelled()
        assert metrics.active == 0

    async def test_step_empty_id(self, validator: WorkflowValidator) -> None:
        w = Workflow(
            workflow_id="w1", name="Test",
            steps=(WorkflowStep(step_id="", name="S", action="act"),),
        )
        result = validator.validate(w)
        assert not result.valid
        assert "Step ID is required" in result.errors

    async def test_scheduler_dequeue_with_cancelled(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.enqueue("wf1")
        await scheduler.enqueue("wf2")
        # Manually cancel wf1 without removing from queue
        scheduler._cancelled.add("wf1")
        result = await scheduler.dequeue()
        assert result == "wf2"

    async def test_scheduler_dequeue_multiple_cancelled(self, scheduler: WorkflowScheduler) -> None:
        await scheduler.enqueue("a")
        await scheduler.enqueue("b")
        await scheduler.enqueue("c")
        scheduler._cancelled.add("a")
        scheduler._cancelled.add("b")
        result = await scheduler.dequeue()
        assert result == "c"

    async def test_workflow_with_retry_on_step(self, engine: WorkflowEngine) -> None:
        step = WorkflowStep(step_id="s1", name="Retry", action="process", retry_count=2)
        w = Workflow(workflow_id="wf_retry", name="RetryWF", steps=(step,))

        class RetryThenFailExecutor:
            def __init__(self):
                self._attempts: dict[str, int] = {}

            async def execute_step(self, workflow_id: str, step: WorkflowStep) -> SubsystemResponse:
                key = f"{workflow_id}:{step.step_id}"
                self._attempts[key] = self._attempts.get(key, 0) + 1
                return SubsystemResponse(
                    success=False, status="failed",
                    errors=[f"attempt {self._attempts[key]}"],
                    subsystem="test",
                )

        await engine.initialize()
        await engine.start()
        await engine.create_workflow(w)
        engine._executor = RetryThenFailExecutor()
        await engine.execute("wf_retry")
        await asyncio.sleep(0.5)
        await engine.stop()
        entries = await engine.history("wf_retry")
        events = [e.event for e in entries]
        assert "failed" in events

    async def test_workflow_step_dependency_blocks(self, engine: WorkflowEngine) -> None:
        w = Workflow(
            workflow_id="wf_dep",
            name="DepWF",
            steps=(
                WorkflowStep(step_id="s1", name="First", action="a"),
                WorkflowStep(step_id="s2", name="Second", action="b", dependencies=("s1",)),
            ),
        )
        await engine.initialize()
        await engine.start()
        await engine.create_workflow(w)
        await engine.execute("wf_dep")
        await asyncio.sleep(0.3)
        await engine.stop()
        entries = await engine.history("wf_dep")
        events = [e.event for e in entries]
        assert "completed" in events

    async def test_workflow_interrupted_not_all_completed(self, engine: WorkflowEngine) -> None:
        steps = tuple(
            WorkflowStep(step_id=f"s{i}", name=f"S{i}", action="act")
            for i in range(3)
        )
        w = Workflow(workflow_id="wf_interrupted", name="Interrupted", steps=steps)

        class PartialExecutor:
            async def execute_step(self, workflow_id: str, step: WorkflowStep) -> SubsystemResponse:
                if step.step_id == "s2":
                    return SubsystemResponse(success=False, status="failed", errors=["step s2 failed"])
                return SubsystemResponse(success=True, status="completed", payload={"step_id": step.step_id})

        await engine.initialize()
        await engine.start()
        await engine.create_workflow(w)
        engine._executor = PartialExecutor()
        await engine.execute("wf_interrupted")
        await asyncio.sleep(0.5)
        await engine.stop()
        entries = await engine.history("wf_interrupted")
        events = [e.event for e in entries]
        assert "failed" in events
        assert "step_completed" in events
        assert "step_failed" in events


# ======================================================================
# EventCategory
# ======================================================================


class TestEventCategory:
    def test_workflow_category_exists(self) -> None:
        assert EventCategory.WORKFLOW.value == "workflow"
