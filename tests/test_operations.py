"""Tests for the Operations Core, Workflow Coordinator, and Task Scheduler."""

import asyncio
from datetime import datetime, timedelta

import pytest

from atlas_core.events import EventBus
from atlas_core.interfaces import ServiceState
from atlas_core.interfaces.events import EventCategory, EventPriority
from atlas_core.operations import (
    OperationsCore,
    TaskScheduler,
    WorkflowCoordinator,
    WorkflowState,
)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus(max_history=50)


@pytest.fixture
def coordinator(event_bus: EventBus) -> WorkflowCoordinator:
    return WorkflowCoordinator(event_bus)


@pytest.fixture
def scheduler(event_bus: EventBus) -> TaskScheduler:
    return TaskScheduler(event_bus)


@pytest.fixture
def operations_core(event_bus: EventBus) -> OperationsCore:
    return OperationsCore(event_bus)


# ======================================================================
# Workflow Coordinator
# ======================================================================

class TestWorkflowCoordinator:
    async def test_create_workflow(self, coordinator: WorkflowCoordinator) -> None:
        wf = await coordinator.create_workflow("test_job", {"task": "abc"})
        assert wf.name == "test_job"
        assert wf.state == WorkflowState.CREATED
        assert wf.payload == {"task": "abc"}

    async def test_create_workflow_publishes_event(self, event_bus: EventBus) -> None:
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        event_bus.subscribe("workflow", handler)
        coordinator = WorkflowCoordinator(event_bus)
        await coordinator.create_workflow("test")
        assert len(received) == 1
        assert received[0].payload["action"] == "created"

    async def test_transition(self, coordinator: WorkflowCoordinator) -> None:
        wf = await coordinator.create_workflow("test")
        await coordinator.transition(wf.workflow_id, WorkflowState.RUNNING)
        assert coordinator.get_workflow(wf.workflow_id).state == WorkflowState.RUNNING

    async def test_transition_unknown_raises(self, coordinator: WorkflowCoordinator) -> None:
        with pytest.raises(ValueError, match="Unknown workflow"):
            await coordinator.transition("nonexistent", WorkflowState.RUNNING)

    async def test_transition_publishes_event(self, event_bus: EventBus) -> None:
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        event_bus.subscribe("workflow", handler)
        coordinator = WorkflowCoordinator(event_bus)
        wf = await coordinator.create_workflow("test")
        await coordinator.transition(wf.workflow_id, WorkflowState.RUNNING)
        transitions = [e for e in received if e.payload.get("action") == "transition"]
        assert len(transitions) == 1

    async def test_active_workflows(self, coordinator: WorkflowCoordinator) -> None:
        wf1 = await coordinator.create_workflow("active1")
        wf2 = await coordinator.create_workflow("active2")
        await coordinator.transition(wf2.workflow_id, WorkflowState.COMPLETED)
        active = coordinator.active_workflows
        assert len(active) == 1
        assert active[0].workflow_id == wf1.workflow_id

    async def test_handle_error_retry(self, coordinator: WorkflowCoordinator) -> None:
        wf = await coordinator.create_workflow("test")
        wf.max_retries = 3
        await coordinator.handle_error(wf.workflow_id)
        assert coordinator.get_workflow(wf.workflow_id).state == WorkflowState.RETRY
        assert coordinator.get_workflow(wf.workflow_id).error_count == 1

    async def test_handle_error_escalation(self, coordinator: WorkflowCoordinator) -> None:
        wf = await coordinator.create_workflow("test")
        wf.max_retries = 1
        await coordinator.handle_error(wf.workflow_id)
        await coordinator.handle_error(wf.workflow_id)
        assert coordinator.get_workflow(wf.workflow_id).state == WorkflowState.ESCALATION

    async def test_get_workflow_unknown(self, coordinator: WorkflowCoordinator) -> None:
        assert coordinator.get_workflow("ghost") is None

    async def test_all_workflows(self, coordinator: WorkflowCoordinator) -> None:
        await coordinator.create_workflow("a")
        await coordinator.create_workflow("b")
        assert len(coordinator.all_workflows) == 2


# ======================================================================
# Task Scheduler
# ======================================================================

class TestTaskScheduler:
    async def test_schedule_once(self, scheduler: TaskScheduler) -> None:
        triggered = False

        async def callback() -> None:
            nonlocal triggered
            triggered = True

        await scheduler.schedule_once("oneshot", callback, delay_seconds=0.02)
        await scheduler.start()
        for _ in range(10):
            if triggered:
                break
            await asyncio.sleep(0.03)
        await scheduler.stop()
        assert triggered is True

    async def test_schedule_interval(self, scheduler: TaskScheduler) -> None:
        count = 0

        async def callback() -> None:
            nonlocal count
            count += 1

        await scheduler.schedule_interval("periodic", callback, interval_seconds=0.05)
        await scheduler.start()
        await asyncio.sleep(0.18)
        await scheduler.stop()
        assert count >= 2  # should fire at least twice

    async def test_cancel_task(self, scheduler: TaskScheduler) -> None:
        count = 0

        async def callback() -> None:
            nonlocal count
            count += 1

        task_id = await scheduler.schedule_interval("cancellable", callback, interval_seconds=0.03)
        await scheduler.start()
        await asyncio.sleep(0.08)
        await scheduler.cancel_task(task_id)
        await asyncio.sleep(0.08)
        await scheduler.stop()
        assert count < 5

    async def test_callback_exception_handled(self, scheduler: TaskScheduler) -> None:
        async def broken() -> None:
            raise RuntimeError("boom")

        task_id = await scheduler.schedule_once("broken", broken, delay_seconds=0.02)
        await scheduler.start()
        for _ in range(10):
            if task_id not in scheduler.tasks:
                break
            await asyncio.sleep(0.03)
        await scheduler.stop()
        assert task_id not in scheduler.tasks

    async def test_start_stop_idempotent(self, scheduler: TaskScheduler) -> None:
        await scheduler.start()
        await scheduler.start()  # second start should be no-op
        assert scheduler._running is True
        await scheduler.stop()
        assert scheduler._running is False

    async def test_tasks_property(self, scheduler: TaskScheduler) -> None:
        async def cb() -> None:
            pass

        await scheduler.schedule_once("t1", cb, delay_seconds=10)
        await scheduler.schedule_interval("t2", cb, interval_seconds=10)
        assert len(scheduler.tasks) == 2


# ======================================================================
# Operations Core
# ======================================================================

class TestOperationsCore:
    async def test_initialise(self, operations_core: OperationsCore) -> None:
        await operations_core.initialize()
        assert operations_core.name == "operations_core"

    async def test_start_stop(self, operations_core: OperationsCore) -> None:
        await operations_core.initialize()
        await operations_core.start()
        await operations_core.stop()

    async def test_health_check_before_start(self, operations_core: OperationsCore) -> None:
        await operations_core.initialize()
        health = await operations_core.health_check()
        assert health.healthy is True

    async def test_health_check_after_start(self, operations_core: OperationsCore) -> None:
        await operations_core.initialize()
        await operations_core.start()
        health = await operations_core.health_check()
        assert health.healthy is True
        assert "scheduled_tasks" in health.metadata
        await operations_core.stop()

    async def test_workflow_coordinator_accessible(self, operations_core: OperationsCore) -> None:
        assert operations_core.workflow_coordinator is not None
        assert operations_core.scheduler is not None

    async def test_end_to_end_workflow(self, operations_core: OperationsCore) -> None:
        wf = await operations_core.workflow_coordinator.create_workflow("e2e", {"x": 1})
        assert wf.state == WorkflowState.CREATED
        await operations_core.workflow_coordinator.transition(wf.workflow_id, WorkflowState.RUNNING)
        assert operations_core.workflow_coordinator.get_workflow(wf.workflow_id).state == WorkflowState.RUNNING
