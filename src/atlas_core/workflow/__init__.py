"""Workflow Engine — coordinates multi-step business workflows.

The Workflow Engine orchestrates steps across Missions, Agents,
Connectors, Notifications, Persistence, and Monitoring.

It does NOT execute OS commands, communicate with AI providers, or
contain business logic.  It only orchestrates existing services.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional

from atlas_core.interfaces import IService, ServiceHealth, ServiceState, SubsystemResponse


# ======================================================================
# WorkflowState
# ======================================================================


class WorkflowState(Enum):
    CREATED = auto()
    VALIDATING = auto()
    READY = auto()
    RUNNING = auto()
    WAITING = auto()
    PAUSED = auto()
    FAILED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


# ======================================================================
# WorkflowStep
# ======================================================================


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    name: str
    action: str
    dependencies: tuple[str, ...] = ()
    connector: str = ""
    timeout: float = 60.0
    retry_count: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# Workflow
# ======================================================================


@dataclass(frozen=True)
class Workflow:
    workflow_id: str
    name: str
    description: str = ""
    steps: tuple[WorkflowStep, ...] = ()
    state: WorkflowState = WorkflowState.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# WorkflowDefinition
# ======================================================================


class WorkflowDefinition:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._definitions: dict[str, Workflow] = {}

    async def register(self, workflow: Workflow) -> None:
        async with self._lock:
            if workflow.workflow_id in self._definitions:
                raise ValueError(f"Workflow already registered: {workflow.workflow_id}")
            self._definitions[workflow.workflow_id] = workflow

    async def unregister(self, workflow_id: str) -> Optional[Workflow]:
        async with self._lock:
            return self._definitions.pop(workflow_id, None)

    def get(self, workflow_id: str) -> Optional[Workflow]:
        return self._definitions.get(workflow_id)

    def list(self) -> list[Workflow]:
        return list(self._definitions.values())

    def clone(self, workflow_id: str, new_id: str | None = None) -> Optional[Workflow]:
        original = self._definitions.get(workflow_id)
        if original is None:
            return None
        new_id = new_id or f"{original.workflow_id}_clone_{uuid.uuid4().hex[:8]}"
        return Workflow(
            workflow_id=new_id,
            name=original.name,
            description=original.description,
            steps=original.steps,
            state=WorkflowState.CREATED,
            metadata={**original.metadata, "cloned_from": workflow_id},
        )


# ======================================================================
# WorkflowValidator
# ======================================================================


@dataclass
class ValidationResult:
    valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class WorkflowValidator:
    VALID_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
        WorkflowState.CREATED: {WorkflowState.VALIDATING},
        WorkflowState.VALIDATING: {WorkflowState.READY, WorkflowState.FAILED},
        WorkflowState.READY: {WorkflowState.RUNNING, WorkflowState.CANCELLED},
        WorkflowState.RUNNING: {WorkflowState.PAUSED, WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.WAITING},
        WorkflowState.WAITING: {WorkflowState.RUNNING, WorkflowState.CANCELLED},
        WorkflowState.PAUSED: {WorkflowState.RUNNING, WorkflowState.CANCELLED},
        WorkflowState.FAILED: set(),
        WorkflowState.COMPLETED: set(),
        WorkflowState.CANCELLED: set(),
    }

    def validate(self, workflow: Workflow) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        step_ids: set[str] = set()

        if not workflow.workflow_id:
            errors.append("Workflow ID is required")
        if not workflow.name:
            errors.append("Workflow name is required")
        if not workflow.steps:
            errors.append("Workflow must have at least one step")

        for step in workflow.steps:
            if not step.step_id:
                errors.append("Step ID is required")
                continue

            if step.step_id in step_ids:
                errors.append(f"Duplicate step ID: {step.step_id}")
            step_ids.add(step.step_id)

            if not step.name:
                errors.append(f"Step {step.step_id}: name is required")
            if not step.action:
                errors.append(f"Step {step.step_id}: action is required")
            if step.timeout <= 0:
                errors.append(f"Step {step.step_id}: timeout must be positive")
            if step.retry_count < 0:
                errors.append(f"Step {step.step_id}: retry_count must be non-negative")

            for dep in step.dependencies:
                if dep not in step_ids and dep not in {s.step_id for s in workflow.steps}:
                    errors.append(f"Step {step.step_id}: missing dependency '{dep}'")

        for step in workflow.steps:
            visited: set[str] = set()
            if self._has_cycle(step.step_id, workflow.steps, set(), visited):
                errors.append(f"Step {step.step_id}: circular dependency detected")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    def validate_transition(self, current: WorkflowState, target: WorkflowState) -> ValidationResult:
        allowed = self.VALID_TRANSITIONS.get(current, set())
        if target in allowed:
            return ValidationResult()
        return ValidationResult(
            valid=False,
            errors=[f"Cannot transition from {current.name} to {target.name}"],
        )

    @staticmethod
    def _has_cycle(
        node: str,
        steps: tuple[WorkflowStep, ...],
        visited: set[str],
        rec_stack: set[str],
    ) -> bool:
        step_map = {s.step_id: s for s in steps}
        if node not in step_map:
            return False
        visited.add(node)
        rec_stack.add(node)
        for dep in step_map[node].dependencies:
            if dep not in step_map:
                continue
            if dep not in visited:
                if WorkflowValidator._has_cycle(dep, steps, visited, rec_stack):
                    return True
            elif dep in rec_stack:
                return True
        rec_stack.discard(node)
        return False


# ======================================================================
# WorkflowScheduler
# ======================================================================


class Priority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


@dataclass
class QueueItem:
    workflow_id: str
    priority: Priority = Priority.NORMAL
    created_at: datetime = field(default_factory=datetime.now)


class WorkflowScheduler:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._queue: list[QueueItem] = []
        self._paused: set[str] = set()
        self._cancelled: set[str] = set()

    async def enqueue(self, workflow_id: str, priority: Priority = Priority.NORMAL) -> None:
        async with self._lock:
            self._queue.append(QueueItem(workflow_id=workflow_id, priority=priority))
            self._queue.sort(key=lambda x: (x.priority.value, x.created_at))

    async def dequeue(self) -> Optional[str]:
        async with self._lock:
            while self._queue:
                item = self._queue.pop(0)
                if item.workflow_id in self._cancelled:
                    self._cancelled.discard(item.workflow_id)
                    continue
                return item.workflow_id
            return None

    async def pause(self, workflow_id: str) -> bool:
        async with self._lock:
            if workflow_id in self._cancelled:
                return False
            self._paused.add(workflow_id)
            return True

    async def resume(self, workflow_id: str) -> bool:
        async with self._lock:
            if workflow_id in self._cancelled:
                return False
            self._paused.discard(workflow_id)
            return workflow_id not in self._paused

    async def cancel(self, workflow_id: str) -> bool:
        async with self._lock:
            self._cancelled.add(workflow_id)
            self._paused.discard(workflow_id)
            self._queue[:] = [item for item in self._queue if item.workflow_id != workflow_id]
            return True

    async def is_paused(self, workflow_id: str) -> bool:
        async with self._lock:
            return workflow_id in self._paused

    async def is_cancelled(self, workflow_id: str) -> bool:
        async with self._lock:
            return workflow_id in self._cancelled

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def list_paused(self) -> list[str]:
        return list(self._paused)

    def list_cancelled(self) -> list[str]:
        return list(self._cancelled)


# ======================================================================
# WorkflowExecutor
# ======================================================================


class WorkflowExecutor:
    def __init__(
        self,
        connector_manager: Any | None = None,
        mission_control: Any | None = None,
        notification_service: Any | None = None,
    ) -> None:
        self._connector_manager = connector_manager
        self._mission_control = mission_control
        self._notification_service = notification_service
        self._logger = logging.getLogger(__name__)

    async def execute_step(
        self,
        workflow_id: str,
        step: WorkflowStep,
    ) -> SubsystemResponse:
        start = time.monotonic()
        attempt = 0
        max_retries = step.retry_count

        while attempt <= max_retries:
            try:
                if step.connector and self._connector_manager:
                    result = await self._connector_manager.execute(
                        step.connector, step.action, **step.payload,
                    )
                elif self._notification_service and step.action == "notify":
                    result = {}
                    await self._notification_service.send(
                        message=step.payload.get("message", ""),
                        channel=step.payload.get("channel", "default"),
                    )
                elif self._mission_control and step.action == "mission":
                    result = await self._mission_control.execute(step.payload)
                else:
                    result = {"executed": True, "step_id": step.step_id}

                duration = time.monotonic() - start
                return SubsystemResponse(
                    success=True,
                    status="completed",
                    payload={"step_id": step.step_id, "result": result},
                    subsystem="workflow_executor",
                    duration=duration,
                )
            except Exception as e:
                attempt += 1
                if attempt > max_retries:
                    duration = time.monotonic() - start
                    return SubsystemResponse(
                        success=False,
                        status="failed",
                        errors=[f"Step {step.step_id} failed after {attempt} attempts: {e}"],
                        subsystem="workflow_executor",
                        duration=duration,
                    )
                await asyncio.sleep(min(0.5 * attempt, 5.0))

        return SubsystemResponse(
            success=False,
            status="failed",
            errors=[f"Step {step.step_id} failed: unknown error"],
            subsystem="workflow_executor",
        )


# ======================================================================
# WorkflowHistory
# ======================================================================


@dataclass
class HistoryEntry:
    workflow_id: str
    event: str
    step_id: str = ""
    message: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


class WorkflowHistory:
    def __init__(self, max_size: int = 1000) -> None:
        self._lock = asyncio.Lock()
        self._entries: deque[HistoryEntry] = deque(maxlen=max_size)

    async def record(self, entry: HistoryEntry) -> None:
        async with self._lock:
            self._entries.append(entry)

    async def get_history(
        self,
        workflow_id: str | None = None,
        limit: int = 100,
    ) -> list[HistoryEntry]:
        async with self._lock:
            matches = [
                e for e in self._entries
                if workflow_id is None or e.workflow_id == workflow_id
            ]
            return matches[-limit:]

    async def clear(self, workflow_id: str | None = None) -> None:
        async with self._lock:
            if workflow_id is None:
                self._entries.clear()
            else:
                self._entries = deque(
                    [e for e in self._entries if e.workflow_id != workflow_id],
                    maxlen=self._entries.maxlen,
                )

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def max_size(self) -> int:
        return self._entries.maxlen  # type: ignore[arg-type]


# ======================================================================
# WorkflowMetrics
# ======================================================================


class WorkflowMetrics:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._created = 0
        self._completed = 0
        self._failed = 0
        self._cancelled = 0
        self._total_runtime = 0.0
        self._step_count = 0
        self._retry_count = 0

    async def record_created(self) -> None:
        async with self._lock:
            self._created += 1

    async def record_completed(self, runtime: float = 0.0) -> None:
        async with self._lock:
            self._completed += 1
            self._total_runtime += runtime

    async def record_failed(self) -> None:
        async with self._lock:
            self._failed += 1

    async def record_cancelled(self) -> None:
        async with self._lock:
            self._cancelled += 1

    async def record_step(self) -> None:
        async with self._lock:
            self._step_count += 1

    async def record_retry(self) -> None:
        async with self._lock:
            self._retry_count += 1

    @property
    def created(self) -> int:
        return self._created

    @property
    def completed(self) -> int:
        return self._completed

    @property
    def failed(self) -> int:
        return self._failed

    @property
    def cancelled(self) -> int:
        return self._cancelled

    @property
    def average_runtime(self) -> float:
        if self._completed == 0:
            return 0.0
        return self._total_runtime / self._completed

    @property
    def active(self) -> int:
        return self._created - self._completed - self._failed - self._cancelled

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def retry_count(self) -> int:
        return self._retry_count

    def snapshot(self) -> dict[str, Any]:
        return {
            "created": self._created,
            "completed": self._completed,
            "failed": self._failed,
            "cancelled": self._cancelled,
            "active": self.active,
            "average_runtime": self.average_runtime,
            "step_count": self._step_count,
            "retry_count": self._retry_count,
        }


# ======================================================================
# WorkflowEventBridge
# ======================================================================


class WorkflowEventBridge:
    def __init__(self, event_bus: Any) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(self, event_type: str, workflow_id: str, **extra: Any) -> None:
        try:
            from atlas_core.interfaces.events import Event, EventCategory
            event = Event(
                source="workflow_engine",
                category=EventCategory.WORKFLOW,
                payload={"event_type": event_type, "workflow_id": workflow_id, **extra},
            )
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish workflow event")

    async def workflow_created(self, workflow_id: str) -> None:
        await self.publish("WORKFLOW_CREATED", workflow_id)

    async def workflow_started(self, workflow_id: str) -> None:
        await self.publish("WORKFLOW_STARTED", workflow_id)

    async def workflow_paused(self, workflow_id: str) -> None:
        await self.publish("WORKFLOW_PAUSED", workflow_id)

    async def workflow_resumed(self, workflow_id: str) -> None:
        await self.publish("WORKFLOW_RESUMED", workflow_id)

    async def workflow_completed(self, workflow_id: str) -> None:
        await self.publish("WORKFLOW_COMPLETED", workflow_id, status="completed")

    async def workflow_failed(self, workflow_id: str, error: str = "") -> None:
        await self.publish("WORKFLOW_FAILED", workflow_id, error=error)

    async def workflow_cancelled(self, workflow_id: str) -> None:
        await self.publish("WORKFLOW_CANCELLED", workflow_id)

    async def step_started(self, workflow_id: str, step_id: str) -> None:
        await self.publish("STEP_STARTED", workflow_id, step_id=step_id)

    async def step_completed(self, workflow_id: str, step_id: str) -> None:
        await self.publish("STEP_COMPLETED", workflow_id, step_id=step_id)

    async def step_failed(self, workflow_id: str, step_id: str, error: str = "") -> None:
        await self.publish("STEP_FAILED", workflow_id, step_id=step_id, error=error)


# ======================================================================
# WorkflowEngine (IService)
# ======================================================================


class WorkflowEngine(IService):
    def __init__(
        self,
        event_bus: Any,
        connector_manager: Any | None = None,
        mission_control: Any | None = None,
        notification_service: Any | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)
        self._connector_manager = connector_manager
        self._mission_control = mission_control
        self._notification_service = notification_service

        self._definitions = WorkflowDefinition()
        self._validator = WorkflowValidator()
        self._scheduler = WorkflowScheduler()
        self._executor = WorkflowExecutor(
            connector_manager=connector_manager,
            mission_control=mission_control,
            notification_service=notification_service,
        )
        self._history = WorkflowHistory()
        self._metrics = WorkflowMetrics()
        self._event_bridge = WorkflowEventBridge(event_bus)

        self._workflows: dict[str, Workflow] = {}
        self._workflows_lock = asyncio.Lock()
        self._running = False
        self._worker_task: asyncio.Task[None] | None = None

    @property
    def name(self) -> str:
        return "workflow_engine"

    async def initialize(self) -> None:
        self._state = ServiceState.INITIALIZED
        self._logger.info("Workflow Engine initialized")

    async def start(self) -> None:
        self._state = ServiceState.RUNNING
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._logger.info("Workflow Engine started")

    async def stop(self) -> None:
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._state = ServiceState.STOPPED
        self._logger.info("Workflow Engine stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=self._state,
            message=f"Workflow Engine: {len(self._workflows)} workflow(s)",
            metadata={
                "workflows": len(self._workflows),
                "active": self._metrics.active,
                "queue_size": self._scheduler.queue_size,
                **self._metrics.snapshot(),
            },
        )

    @property
    def definitions(self) -> WorkflowDefinition:
        return self._definitions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_workflow(self, workflow: Workflow) -> Workflow:
        validation = self._validator.validate(workflow)
        if not validation.valid:
            raise ValueError(f"Invalid workflow: {'; '.join(validation.errors)}")

        async with self._workflows_lock:
            if workflow.workflow_id in self._workflows:
                raise ValueError(f"Workflow already exists: {workflow.workflow_id}")

            new_workflow = Workflow(
                workflow_id=workflow.workflow_id,
                name=workflow.name,
                description=workflow.description,
                steps=workflow.steps,
                state=WorkflowState.READY,
                metadata=workflow.metadata,
            )
            self._workflows[workflow.workflow_id] = new_workflow

        await self._metrics.record_created()
        await self._event_bridge.workflow_created(workflow.workflow_id)
        await self._history.record(HistoryEntry(
            workflow_id=workflow.workflow_id,
            event="created",
        ))
        return new_workflow

    async def register_definition(self, workflow: Workflow) -> None:
        validation = self._validator.validate(workflow)
        if not validation.valid:
            raise ValueError(f"Invalid definition: {'; '.join(validation.errors)}")
        await self._definitions.register(workflow)

    async def execute(self, workflow_id: str, priority: Priority = Priority.NORMAL) -> None:
        async with self._workflows_lock:
            workflow = self._workflows.get(workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow not found: {workflow_id}")

            updated = Workflow(
                workflow_id=workflow.workflow_id,
                name=workflow.name,
                description=workflow.description,
                steps=workflow.steps,
                state=WorkflowState.RUNNING,
                metadata=workflow.metadata,
            )
            self._workflows[workflow_id] = updated

        await self._event_bridge.workflow_started(workflow_id)
        await self._scheduler.enqueue(workflow_id, priority)

    async def pause(self, workflow_id: str) -> bool:
        async with self._workflows_lock:
            workflow = self._workflows.get(workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow not found: {workflow_id}")
            if workflow.state not in (WorkflowState.RUNNING,):
                return False
            self._workflows[workflow_id] = Workflow(
                workflow_id=workflow.workflow_id,
                name=workflow.name,
                description=workflow.description,
                steps=workflow.steps,
                state=WorkflowState.PAUSED,
                metadata=workflow.metadata,
            )

        result = await self._scheduler.pause(workflow_id)
        if result:
            await self._event_bridge.workflow_paused(workflow_id)
            await self._history.record(HistoryEntry(
                workflow_id=workflow_id, event="paused",
            ))
        return result

    async def resume(self, workflow_id: str) -> bool:
        async with self._workflows_lock:
            workflow = self._workflows.get(workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow not found: {workflow_id}")
            if workflow.state not in (WorkflowState.PAUSED,):
                return False
            self._workflows[workflow_id] = Workflow(
                workflow_id=workflow.workflow_id,
                name=workflow.name,
                description=workflow.description,
                steps=workflow.steps,
                state=WorkflowState.RUNNING,
                metadata=workflow.metadata,
            )

        result = await self._scheduler.resume(workflow_id)
        if result:
            await self._event_bridge.workflow_resumed(workflow_id)
            await self._history.record(HistoryEntry(
                workflow_id=workflow_id, event="resumed",
            ))
        return result

    async def cancel(self, workflow_id: str) -> bool:
        async with self._workflows_lock:
            workflow = self._workflows.get(workflow_id)
            if workflow is None:
                raise ValueError(f"Workflow not found: {workflow_id}")
            if workflow.state in (WorkflowState.COMPLETED, WorkflowState.CANCELLED, WorkflowState.FAILED):
                return False
            self._workflows[workflow_id] = Workflow(
                workflow_id=workflow.workflow_id,
                name=workflow.name,
                description=workflow.description,
                steps=workflow.steps,
                state=WorkflowState.CANCELLED,
                metadata=workflow.metadata,
            )

        result = await self._scheduler.cancel(workflow_id)
        if result:
            await self._metrics.record_cancelled()
            await self._event_bridge.workflow_cancelled(workflow_id)
            await self._history.record(HistoryEntry(
                workflow_id=workflow_id, event="cancelled",
            ))
        return result

    def validate(self, workflow: Workflow) -> ValidationResult:
        return self._validator.validate(workflow)

    async def history(
        self,
        workflow_id: str | None = None,
        limit: int = 100,
    ) -> list[HistoryEntry]:
        return await self._history.get_history(workflow_id, limit)

    def metrics(self) -> dict[str, Any]:
        return self._metrics.snapshot()

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    async def _worker_loop(self) -> None:
        while self._running:
            try:
                workflow_id = await self._scheduler.dequeue()
                if workflow_id is None:
                    await asyncio.sleep(0.1)
                    continue

                async with self._workflows_lock:
                    workflow = self._workflows.get(workflow_id)
                    if workflow is None:
                        continue
                    if workflow.state != WorkflowState.RUNNING:
                        continue

                await self._process_workflow(workflow)

            except asyncio.CancelledError:
                break
            except Exception:
                self._logger.exception("Worker error")

    async def _process_workflow(self, workflow: Workflow) -> None:
        completed_steps: set[str] = set()
        start_time = time.monotonic()

        for step in workflow.steps:
            if await self._scheduler.is_cancelled(workflow.workflow_id):
                return
            if await self._scheduler.is_paused(workflow.workflow_id):
                while await self._scheduler.is_paused(workflow.workflow_id):
                    if await self._scheduler.is_cancelled(workflow.workflow_id):
                        return
                    await asyncio.sleep(0.5)

            if any(dep not in completed_steps for dep in step.dependencies):
                continue
            await self._metrics.record_step()
            await self._event_bridge.step_started(workflow.workflow_id, step.step_id)
            await self._history.record(HistoryEntry(
                workflow_id=workflow.workflow_id,
                event="step_started",
                step_id=step.step_id,
            ))

            response = await self._executor.execute_step(workflow.workflow_id, step)

            if response.success:
                completed_steps.add(step.step_id)
                await self._event_bridge.step_completed(workflow.workflow_id, step.step_id)
                await self._history.record(HistoryEntry(
                    workflow_id=workflow.workflow_id,
                    event="step_completed",
                    step_id=step.step_id,
                ))
            else:
                if step.retry_count > 0:
                    await self._metrics.record_retry()
                if not response.success and response.errors:
                    await self._metrics.record_failed()
                    await self._event_bridge.step_failed(
                        workflow.workflow_id, step.step_id,
                        error=response.errors[0],
                    )
                    await self._history.record(HistoryEntry(
                        workflow_id=workflow.workflow_id,
                        event="step_failed",
                        step_id=step.step_id,
                        message=response.errors[0],
                    ))
                    await self._finalize_workflow(workflow.workflow_id, WorkflowState.FAILED)
                    return

        runtime = time.monotonic() - start_time
        all_steps_completed = len(completed_steps) == len(workflow.steps)
        if all_steps_completed:
            await self._finalize_workflow(workflow.workflow_id, WorkflowState.COMPLETED, runtime)
        else:
            await self._finalize_workflow(workflow.workflow_id, WorkflowState.FAILED)

    async def _finalize_workflow(
        self,
        workflow_id: str,
        state: WorkflowState,
        runtime: float = 0.0,
    ) -> None:
        async with self._workflows_lock:
            workflow = self._workflows.get(workflow_id)
            if workflow is None:
                return
            self._workflows[workflow_id] = Workflow(
                workflow_id=workflow.workflow_id,
                name=workflow.name,
                description=workflow.description,
                steps=workflow.steps,
                state=state,
                metadata=workflow.metadata,
            )

        if state == WorkflowState.COMPLETED:
            await self._metrics.record_completed(runtime)
            await self._event_bridge.workflow_completed(workflow_id)
            await self._history.record(HistoryEntry(
                workflow_id=workflow_id, event="completed",
            ))
        elif state == WorkflowState.FAILED:
            await self._metrics.record_failed()
            await self._event_bridge.workflow_failed(workflow_id)
            await self._history.record(HistoryEntry(
                workflow_id=workflow_id, event="failed",
            ))
