"""Operations Core — the heartbeat of Atlas.

Owns the event-processing loop, workflow coordination, and background
task scheduling.  All subsystems communicate through this core.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Workflow subsystem
# ======================================================================

class WorkflowState(Enum):
    CREATED = auto()
    QUEUED = auto()
    ASSIGNED = auto()
    RUNNING = auto()
    WAITING = auto()
    REVIEW = auto()
    COMPLETED = auto()
    ARCHIVED = auto()
    RECOVERY = auto()
    RETRY = auto()
    ESCALATION = auto()


_TERMINAL_STATES = {WorkflowState.COMPLETED, WorkflowState.ARCHIVED, WorkflowState.ESCALATION}


@dataclass
class WorkflowDefinition:
    workflow_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    state: WorkflowState = WorkflowState.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    priority: EventPriority = EventPriority.NORMAL
    source: str = "system"
    payload: dict[str, Any] = field(default_factory=dict)
    error_count: int = 0
    max_retries: int = 3


class WorkflowCoordinator:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._logger = logging.getLogger(__name__)

    async def create_workflow(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
        priority: EventPriority = EventPriority.NORMAL,
        source: str = "system",
    ) -> WorkflowDefinition:
        wf = WorkflowDefinition(
            name=name,
            payload=payload or {},
            priority=priority,
            source=source,
        )
        self._workflows[wf.workflow_id] = wf
        try:
            await self._event_bus.publish(Event(
                source="workflow_coordinator",
                category=EventCategory.WORKFLOW,
                priority=priority,
                payload={"workflow_id": wf.workflow_id, "name": name, "action": "created"},
                related_workflow=wf.workflow_id,
            ))
        except Exception:
            self._logger.exception("Failed to publish workflow created event")
        self._logger.info("Workflow created: %s (%s)", name, wf.workflow_id)
        return wf

    async def transition(self, workflow_id: str, new_state: WorkflowState) -> None:
        wf = self._workflows.get(workflow_id)
        if wf is None:
            raise ValueError(f"Unknown workflow: {workflow_id}")
        old = wf.state
        wf.state = new_state
        wf.updated_at = datetime.now()
        try:
            await self._event_bus.publish(Event(
                source="workflow_coordinator",
                category=EventCategory.WORKFLOW,
                payload={
                    "workflow_id": workflow_id,
                    "from_state": old.name,
                    "to_state": new_state.name,
                    "action": "transition",
                },
                related_workflow=workflow_id,
            ))
        except Exception:
            self._logger.exception("Failed to publish workflow transition event")
        self._logger.info("Workflow %s: %s -> %s", workflow_id, old.name, new_state.name)

    async def handle_error(self, workflow_id: str) -> None:
        wf = self._workflows.get(workflow_id)
        if wf is None:
            raise ValueError(f"Unknown workflow: {workflow_id}")
        wf.error_count += 1
        if wf.error_count >= wf.max_retries:
            await self.transition(workflow_id, WorkflowState.ESCALATION)
        else:
            await self.transition(workflow_id, WorkflowState.RETRY)

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        return self._workflows.get(workflow_id)

    @property
    def active_workflows(self) -> list[WorkflowDefinition]:
        return [w for w in self._workflows.values() if w.state not in _TERMINAL_STATES]

    @property
    def all_workflows(self) -> dict[str, WorkflowDefinition]:
        return dict(self._workflows)


# ======================================================================
# Task Scheduler
# ======================================================================

@dataclass
class ScheduledTask:
    task_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    callback: Callable[[], Awaitable[None]] | None = None
    interval: float | None = None
    next_run: datetime = field(default_factory=datetime.now)
    last_run: datetime | None = None
    running: bool = False


class TaskScheduler:
    async def schedule_interval(
        self,
        name: str,
        callback: Callable[[], Awaitable[None]],
        interval_seconds: float,
    ) -> str:
        task = ScheduledTask(
            name=name,
            callback=callback,
            interval=interval_seconds,
            next_run=datetime.now() + timedelta(seconds=interval_seconds),
        )
        self._tasks[task.task_id] = task
        self._logger.debug("Scheduled interval task: %s (every %.1fs)", name, interval_seconds)
        return task.task_id

    async def schedule_once(
        self,
        name: str,
        callback: Callable[[], Awaitable[None]],
        delay_seconds: float,
    ) -> str:
        task = ScheduledTask(
            name=name,
            callback=callback,
            interval=None,
            next_run=datetime.now() + timedelta(seconds=delay_seconds),
        )
        self._tasks[task.task_id] = task
        self._logger.debug("Scheduled one-shot task: %s (delay %.1fs)", name, delay_seconds)
        return task.task_id

    async def cancel_task(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)
        self._logger.debug("Cancelled task: %s", task_id)

    async def _tick(self) -> None:
        now = datetime.now()
        due: list[ScheduledTask] = []
        for task in list(self._tasks.values()):
            if not task.running and task.next_run <= now:
                due.append(task)
        for task in due:
            task.running = True
            asyncio.create_task(self._execute(task))

    async def _execute(self, task: ScheduledTask) -> None:
        try:
            if task.callback is not None:
                await task.callback()
            task.last_run = datetime.now()
            if task.interval is not None:
                task.next_run = task.last_run + timedelta(seconds=task.interval)
                task.running = False
            else:
                self._tasks.pop(task.task_id, None)
        except Exception:
            self._logger.exception("Task '%s' failed", task.name)
            if task.interval is not None:
                task.running = False
                task.next_run = datetime.now() + timedelta(seconds=task.interval or 60)
            else:
                self._tasks.pop(task.task_id, None)

    def __init__(self, event_bus: EventBus, tick_interval: float = 0.05) -> None:
        self._event_bus = event_bus
        self._tasks: dict[str, ScheduledTask] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._running = False
        self._tick_interval = tick_interval
        self._logger = logging.getLogger(__name__)

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self._tick()
                await asyncio.sleep(self._tick_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                self._logger.exception("Scheduler loop error")

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop())
        self._logger.info("Task scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
            self._loop_task = None
        self._logger.info("Task scheduler stopped")

    @property
    def tasks(self) -> dict[str, ScheduledTask]:
        return dict(self._tasks)


# ======================================================================
# Operations Core (wraps everything as an IService)
# ======================================================================

class OperationsCore(IService):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._workflow_coordinator = WorkflowCoordinator(event_bus)
        self._scheduler = TaskScheduler(event_bus)
        self._logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return "operations_core"

    @property
    def workflow_coordinator(self) -> WorkflowCoordinator:
        return self._workflow_coordinator

    @property
    def scheduler(self) -> TaskScheduler:
        return self._scheduler

    async def initialize(self) -> None:
        await super().initialize()
        self._logger.info("Operations Core initializing")

    async def start(self) -> None:
        await super().start()
        await self._scheduler.start()
        self._logger.info("Operations Core started")

    async def stop(self) -> None:
        await super().stop()
        await self._scheduler.stop()
        self._logger.info("Operations Core stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "active_workflows": len(self._workflow_coordinator.active_workflows),
                "scheduled_tasks": len(self._scheduler.tasks),
            },
        )
