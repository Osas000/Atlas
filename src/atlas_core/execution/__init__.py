"""Execution Engine — executes approved commands from Operations Core.

Every executable action is represented by a Command object.  The Engine
never decides WHAT to do — it only executes approved commands.
No subsystem may execute OS actions directly; all execution passes here.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import uuid4

from atlas_core.context import AtlasContext
from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Enums
# ======================================================================


class CommandCategory(Enum):
    FILE = "file"
    PROCESS = "process"
    TOOL = "tool"
    SCRIPT = "script"
    SYSTEM = "system"
    WORKFLOW = "workflow"


class ExecutionStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    ROLLING_BACK = auto()
    ROLLED_BACK = auto()
    CANCELLED = auto()


# ======================================================================
# Command — abstract base for all executable actions
# ======================================================================


class Command(ABC):
    """Abstract base for every executable action in Atlas.

    Subclasses implement execute() and optionally rollback() and validate().
    """

    def __init__(self) -> None:
        self._command_id = str(uuid4())

    @property
    def command_id(self) -> str:
        return self._command_id

    @property
    @abstractmethod
    def category(self) -> CommandCategory:
        ...

    @property
    def required_permissions(self) -> list[str]:
        return []

    @abstractmethod
    async def execute(self, context: AtlasContext | None = None) -> CommandResult:
        ...

    async def rollback(self, context: AtlasContext | None = None) -> None:
        """Undo the effects of this command.  Override in subclasses."""
        pass

    async def validate(self) -> list[str]:
        """Return a list of validation errors (empty = valid)."""
        return []


# ======================================================================
# Command result
# ======================================================================


@dataclass
class CommandResult:
    success: bool = True
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""


# ======================================================================
# Concrete command stubs (one per category)
# ======================================================================


class FileCommand(Command):
    """Command for file operations (read, write, copy, delete)."""

    def __init__(self, operation: str, path: str, content: str = "") -> None:
        super().__init__()
        self.operation = operation
        self.path = path
        self.content = content
        self._executed = False

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.FILE

    @property
    def required_permissions(self) -> list[str]:
        return [f"file.{self.operation}"]

    async def execute(self, context: AtlasContext | None = None) -> CommandResult:
        self._executed = True
        # In production this would perform real file I/O
        return CommandResult(
            success=True,
            message=f"File {self.operation} on {self.path} completed",
            data={"operation": self.operation, "path": self.path},
        )

    async def rollback(self, context: AtlasContext | None = None) -> None:
        if self._executed and self.operation in ("write", "delete"):
            # In production this would undo the file operation
            pass

    async def validate(self) -> list[str]:
        errors = []
        if not self.path:
            errors.append("File path is required")
        return errors


class ProcessCommand(Command):
    """Command for process management (start, stop, restart, status)."""

    def __init__(self, action: str, process_name: str) -> None:
        super().__init__()
        self.action = action
        self.process_name = process_name
        self._executed = False

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.PROCESS

    @property
    def required_permissions(self) -> list[str]:
        return [f"process.{self.action}"]

    async def execute(self, context: AtlasContext | None = None) -> CommandResult:
        self._executed = True
        return CommandResult(
            success=True,
            message=f"Process {self.action} for {self.process_name} completed",
            data={"action": self.action, "process": self.process_name},
        )

    async def rollback(self, context: AtlasContext | None = None) -> None:
        if self._executed and self.action in ("start", "restart"):
            pass  # In production: stop the process

    async def validate(self) -> list[str]:
        errors = []
        if not self.process_name:
            errors.append("Process name is required")
        return errors


class ToolCommand(Command):
    """Command for external tool invocation."""

    def __init__(self, tool: str, args: list[str] | None = None) -> None:
        super().__init__()
        self.tool = tool
        self.args = args or []

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.TOOL

    @property
    def required_permissions(self) -> list[str]:
        return [f"tool.{self.tool}"]

    async def execute(self, context: AtlasContext | None = None) -> CommandResult:
        return CommandResult(
            success=True,
            message=f"Tool {self.tool} executed",
            data={"tool": self.tool, "args": self.args},
        )

    async def validate(self) -> list[str]:
        errors = []
        if not self.tool:
            errors.append("Tool name is required")
        return errors


class ScriptCommand(Command):
    """Command for running scripts."""

    def __init__(self, script_path: str, interpreter: str = "") -> None:
        super().__init__()
        self.script_path = script_path
        self.interpreter = interpreter
        self._executed = False

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SCRIPT

    @property
    def required_permissions(self) -> list[str]:
        return ["script.execute"]

    async def execute(self, context: AtlasContext | None = None) -> CommandResult:
        self._executed = True
        return CommandResult(
            success=True,
            message=f"Script {self.script_path} executed",
            data={"script": self.script_path, "interpreter": self.interpreter},
        )

    async def rollback(self, context: AtlasContext | None = None) -> None:
        pass  # Script rollback depends on what the script did

    async def validate(self) -> list[str]:
        errors = []
        if not self.script_path:
            errors.append("Script path is required")
        return errors


class SystemCommand(Command):
    """Command for system-level operations."""

    def __init__(self, operation: str, params: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.operation = operation
        self.params = params or {}

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.SYSTEM

    @property
    def required_permissions(self) -> list[str]:
        return [f"system.{self.operation}"]

    async def execute(self, context: AtlasContext | None = None) -> CommandResult:
        return CommandResult(
            success=True,
            message=f"System {self.operation} completed",
            data={"operation": self.operation, "params": self.params},
        )

    async def validate(self) -> list[str]:
        errors = []
        if not self.operation:
            errors.append("System operation is required")
        return errors


class WorkflowCommand(Command):
    """Command for triggering or managing workflows."""

    def __init__(self, workflow_name: str, payload: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.workflow_name = workflow_name
        self.payload = payload or {}

    @property
    def category(self) -> CommandCategory:
        return CommandCategory.WORKFLOW

    @property
    def required_permissions(self) -> list[str]:
        return ["workflow.execute"]

    async def execute(self, context: AtlasContext | None = None) -> CommandResult:
        return CommandResult(
            success=True,
            message=f"Workflow {self.workflow_name} triggered",
            data={"workflow": self.workflow_name, "payload": self.payload},
        )

    async def validate(self) -> list[str]:
        errors = []
        if not self.workflow_name:
            errors.append("Workflow name is required")
        return errors


# ======================================================================
# Execution context for a single job
# ======================================================================


@dataclass
class ExecutionJob:
    job_id: str = field(default_factory=lambda: str(uuid4()))
    command: Command | None = None
    status: ExecutionStatus = ExecutionStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: CommandResult | None = None
    error: str = ""
    retry_count: int = 0
    max_retries: int = 3
    context: AtlasContext | None = None


# ======================================================================
# PermissionGuard
# ======================================================================


class PermissionGuard:
    """Checks whether commands have the required permissions."""

    def __init__(self, context: AtlasContext | None = None) -> None:
        self._context = context

    def set_context(self, context: AtlasContext) -> None:
        self._context = context

    def check(self, command: Command) -> list[str]:
        """Check if the command's required permissions are granted.

        Returns a list of denied permission strings (empty = all granted).
        """
        required = command.required_permissions
        if not required:
            return []

        if self._context is None:
            return list(required)  # no context = no permissions

        denied: list[str] = []
        for perm in required:
            granted = self._context.permissions.permissions.get(perm, False)
            if not granted:
                denied.append(perm)
        return denied

    async def authorize(self, command: Command) -> bool:
        """Returns True if the command is authorized to execute."""
        return len(self.check(command)) == 0


# ======================================================================
# RollbackManager
# ======================================================================


class RollbackManager:
    """Manages rollback of previously executed commands."""

    def __init__(self) -> None:
        self._history: list[ExecutionJob] = []

    def record(self, job: ExecutionJob) -> None:
        self._history.append(job)

    async def rollback(self, job: ExecutionJob, context: AtlasContext | None = None) -> CommandResult:
        """Attempt to rollback a single executed job."""
        if job.command is None:
            return CommandResult(success=False, error="No command to rollback")

        try:
            await job.command.rollback(context)
            return CommandResult(success=True, message=f"Rolled back {job.job_id}")
        except Exception as exc:
            return CommandResult(success=False, error=str(exc))

    async def rollback_all(self, context: AtlasContext | None = None) -> list[CommandResult]:
        """Rollback all recorded jobs in reverse order."""
        results: list[CommandResult] = []
        for job in reversed(self._history):
            result = await self.rollback(job, context)
            results.append(result)
        return results

    def can_rollback(self, job: ExecutionJob) -> bool:
        return job.status == ExecutionStatus.SUCCESS and job.command is not None


# ======================================================================
# CommandRegistry
# ======================================================================


class CommandRegistry:
    """Registry for command types organised by category."""

    def __init__(self) -> None:
        self._categories: dict[CommandCategory, list[type[Command]]] = defaultdict(list)
        self._defaults: dict[CommandCategory, type[Command]] = {}

    def register(self, command_type: type[Command]) -> None:
        inst = command_type.__new__(command_type)
        cat = inst.category
        self._categories[cat].append(command_type)
        if cat not in self._defaults:
            self._defaults[cat] = command_type

    def get_types(self, category: CommandCategory) -> list[type[Command]]:
        return list(self._categories.get(category, []))

    def create(self, category: CommandCategory, **kwargs: Any) -> Command | None:
        cls = self._defaults.get(category)
        if cls is None:
            return None
        return cls(**kwargs)

    @property
    def categories(self) -> dict[CommandCategory, list[type[Command]]]:
        return dict(self._categories)

    @property
    def count(self) -> int:
        return sum(len(v) for v in self._categories.values())

    def _register_defaults(self) -> None:
        self.register(FileCommand)
        self.register(ProcessCommand)
        self.register(ToolCommand)
        self.register(ScriptCommand)
        self.register(SystemCommand)
        self.register(WorkflowCommand)


# ======================================================================
# ExecutionHistory
# ======================================================================


class ExecutionHistory:
    """Records and queries executed commands."""

    def __init__(self, max_size: int = 1000) -> None:
        self._jobs: list[ExecutionJob] = []
        self._max_size = max_size

    def record(self, job: ExecutionJob) -> None:
        self._jobs.append(job)
        if len(self._jobs) > self._max_size:
            self._jobs.pop(0)

    def get(self, job_id: str) -> ExecutionJob | None:
        for j in self._jobs:
            if j.job_id == job_id:
                return j
        return None

    def query(
        self,
        category: CommandCategory | None = None,
        status: ExecutionStatus | None = None,
        limit: int = 50,
    ) -> list[ExecutionJob]:
        result: list[ExecutionJob] = []
        for j in self._jobs:
            if category is not None and j.command is not None and j.command.category != category:
                continue
            if status is not None and j.status != status:
                continue
            result.append(j)
            if len(result) >= limit:
                break
        return result

    @property
    def all(self) -> list[ExecutionJob]:
        return list(self._jobs)

    @property
    def size(self) -> int:
        return len(self._jobs)

    def clear(self) -> None:
        self._jobs.clear()


# ======================================================================
# ExecutionMetrics
# ======================================================================


@dataclass
class CommandMetrics:
    total: int = 0
    success: int = 0
    failed: int = 0
    rolled_back: int = 0
    total_timing_ms: float = 0.0


class ExecutionMetrics:
    """Tracks execution metrics per command category and overall."""

    def __init__(self) -> None:
        self._category_metrics: dict[str, CommandMetrics] = defaultdict(CommandMetrics)
        self._overall = CommandMetrics()

    def record(
        self,
        category: CommandCategory,
        success: bool,
        timing_ms: float,
        rolled_back: bool = False,
    ) -> None:
        cm = self._category_metrics[category.value]
        cm.total += 1
        cm.total_timing_ms += timing_ms
        if success:
            cm.success += 1
        else:
            cm.failed += 1
        if rolled_back:
            cm.rolled_back += 1

        self._overall.total += 1
        self._overall.total_timing_ms += timing_ms
        if success:
            self._overall.success += 1
        else:
            self._overall.failed += 1
        if rolled_back:
            self._overall.rolled_back += 1

    def category_stats(self, category: CommandCategory) -> CommandMetrics:
        return self._category_metrics.get(category.value, CommandMetrics())

    @property
    def overall(self) -> CommandMetrics:
        return self._overall

    @property
    def all_categories(self) -> dict[str, CommandMetrics]:
        return dict(self._category_metrics)

    def avg_timing_ms(self, category: CommandCategory | None = None) -> float:
        if category is not None:
            cm = self._category_metrics.get(category.value)
            if cm is None or cm.total == 0:
                return 0.0
            return cm.total_timing_ms / cm.total
        if self._overall.total == 0:
            return 0.0
        return self._overall.total_timing_ms / self._overall.total


# ======================================================================
# CommandExecutor
# ======================================================================


class CommandExecutor:
    """Executes a single command with validation, retry, and rollback."""

    def __init__(
        self,
        permission_guard: PermissionGuard,
        rollback_manager: RollbackManager,
        metrics: ExecutionMetrics,
    ) -> None:
        self._permission_guard = permission_guard
        self._rollback_manager = rollback_manager
        self._metrics = metrics
        self._logger = logging.getLogger(__name__)

    async def execute(
        self,
        command: Command,
        context: AtlasContext | None = None,
        max_retries: int = 3,
    ) -> ExecutionJob:
        """Validate, authorize, and execute a command with retry support."""
        job = ExecutionJob(command=command, max_retries=max_retries, context=context)

        # 1. Validate
        validation_errors = await command.validate()
        if validation_errors:
            job.status = ExecutionStatus.FAILED
            job.error = "; ".join(validation_errors)
            self._metrics.record(command.category, success=False, timing_ms=0)
            self._rollback_manager.record(job)
            return job

        # 2. Permission check
        if not await self._permission_guard.authorize(command):
            job.status = ExecutionStatus.FAILED
            job.error = f"Permission denied: {command.required_permissions}"
            self._metrics.record(command.category, success=False, timing_ms=0)
            self._rollback_manager.record(job)
            return job

        # 3. Execute with retry
        start = time.monotonic()
        job.status = ExecutionStatus.RUNNING
        job.started_at = datetime.now()

        last_error: str = ""
        for attempt in range(max_retries + 1):
            try:
                result = await command.execute(context)
                elapsed = (time.monotonic() - start) * 1000
                job.result = result
                job.completed_at = datetime.now()

                if result.success:
                    job.status = ExecutionStatus.SUCCESS
                    self._metrics.record(command.category, success=True, timing_ms=elapsed)
                else:
                    job.status = ExecutionStatus.FAILED
                    job.error = result.error or result.message
                    self._metrics.record(command.category, success=False, timing_ms=elapsed)
                self._rollback_manager.record(job)
                return job

            except Exception as exc:
                last_error = str(exc)
                job.retry_count = attempt + 1
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))  # backoff
                continue

        # All retries exhausted
        elapsed = (time.monotonic() - start) * 1000
        job.status = ExecutionStatus.FAILED
        job.error = last_error
        job.completed_at = datetime.now()
        self._metrics.record(command.category, success=False, timing_ms=elapsed)
        self._rollback_manager.record(job)
        return job


# ======================================================================
# JobQueue
# ======================================================================


class JobQueue:
    """Async queue of pending execution jobs."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ExecutionJob] = asyncio.Queue()

    async def put(self, job: ExecutionJob) -> None:
        await self._queue.put(job)

    async def get(self) -> ExecutionJob:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    @property
    def size(self) -> int:
        return self._queue.qsize()

    async def join(self) -> None:
        await self._queue.join()


# ======================================================================
# WorkerPool
# ======================================================================


class WorkerPool:
    """Pool of async workers that process jobs from the JobQueue."""

    def __init__(
        self,
        command_executor: CommandExecutor,
        job_queue: JobQueue,
        history: ExecutionHistory,
        num_workers: int = 4,
    ) -> None:
        self._executor = command_executor
        self._queue = job_queue
        self._history = history
        self._num_workers = num_workers
        self._workers: list[asyncio.Task[None]] = []
        self._running = False
        self._logger = logging.getLogger(__name__)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self._num_workers)
        ]
        self._logger.info("Worker pool started (%d workers)", self._num_workers)

    async def stop(self) -> None:
        self._running = False
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._logger.info("Worker pool stopped")

    async def _worker(self, worker_id: int) -> None:
        self._logger.debug("Worker %d started", worker_id)
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                if job.command is not None:
                    executed = await self._executor.execute(
                        job.command, job.context, job.max_retries
                    )
                    self._history.record(executed)
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                self._logger.exception("Worker %d error", worker_id)
        self._logger.debug("Worker %d stopped", worker_id)


# ======================================================================
# ExecutionEngine — IService
# ======================================================================


class ExecutionEngine(IService):
    """Central execution engine for Atlas.

    Every executable action must be a Command object.
    No subsystem may execute OS actions directly.
    All execution passes through this engine.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        self._registry = CommandRegistry()
        self._registry._register_defaults()

        self._history = ExecutionHistory()
        self._metrics = ExecutionMetrics()
        self._permission_guard = PermissionGuard()
        self._rollback_manager = RollbackManager()
        self._executor = CommandExecutor(
            self._permission_guard, self._rollback_manager, self._metrics
        )
        self._job_queue = JobQueue()
        self._worker_pool = WorkerPool(
            self._executor, self._job_queue, self._history, num_workers=4
        )

        self._running = False

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "execution_engine"

    async def initialize(self) -> None:
        self._logger.info("Execution Engine initializing")

    async def start(self) -> None:
        self._running = True
        await self._worker_pool.start()
        self._logger.info("Execution Engine started")

    async def stop(self) -> None:
        self._running = False
        await self._worker_pool.stop()
        self._logger.info("Execution Engine stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "commands_executed": self._metrics.overall.total,
                "queue_size": self._job_queue.size,
                "history_size": self._history.size,
                "registered_types": self._registry.count,
            },
        )

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def set_context(self, context: AtlasContext) -> None:
        self._permission_guard.set_context(context)

    # ------------------------------------------------------------------
    # Synchronous execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        command: Command,
        max_retries: int = 3,
    ) -> ExecutionJob:
        """Execute a command synchronously and return the result."""
        job = await self._executor.execute(command, max_retries=max_retries)
        self._history.record(job)
        await self._publish_event(job)
        return job

    # ------------------------------------------------------------------
    # Asynchronous execution (via queue)
    # ------------------------------------------------------------------

    async def submit(
        self,
        command: Command,
        max_retries: int = 3,
    ) -> str:
        """Submit a command for async execution. Returns the job ID."""
        context = self._permission_guard._context
        job = ExecutionJob(
            command=command,
            max_retries=max_retries,
            context=context,
        )
        await self._job_queue.put(job)
        self._logger.debug("Submitted job %s: %s", job.job_id, command.category.value)
        return job.job_id

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    async def rollback(self, job_id: str) -> CommandResult | None:
        """Rollback a specific job by ID."""
        job = self._history.get(job_id)
        if job is None:
            return None
        if not self._rollback_manager.can_rollback(job):
            return CommandResult(success=False, error="Job cannot be rolled back")
        job.status = ExecutionStatus.ROLLING_BACK
        result = await self._rollback_manager.rollback(job)
        job.status = ExecutionStatus.ROLLED_BACK if result.success else ExecutionStatus.FAILED
        await self._publish_event(job)
        return result

    async def rollback_all(self) -> list[CommandResult]:
        """Rollback all previously executed jobs in reverse order."""
        results = await self._rollback_manager.rollback_all()
        for job in self._history.all:
            job.status = ExecutionStatus.ROLLED_BACK
        return results

    # ------------------------------------------------------------------
    # Sub-component accessors
    # ------------------------------------------------------------------

    @property
    def registry(self) -> CommandRegistry:
        return self._registry

    @property
    def history(self) -> ExecutionHistory:
        return self._history

    @property
    def metrics(self) -> ExecutionMetrics:
        return self._metrics

    @property
    def permission_guard(self) -> PermissionGuard:
        return self._permission_guard

    @property
    def rollback_manager(self) -> RollbackManager:
        return self._rollback_manager

    @property
    def executor(self) -> CommandExecutor:
        return self._executor

    @property
    def job_queue(self) -> JobQueue:
        return self._job_queue

    @property
    def worker_pool(self) -> WorkerPool:
        return self._worker_pool

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def _publish_event(self, job: ExecutionJob) -> None:
        try:
            category = job.command.category.value if job.command else "unknown"
            await self._event_bus.publish(Event(
                source="execution_engine",
                category=EventCategory.WORKFLOW,
                priority=EventPriority.NORMAL,
                payload={
                    "action": "command_executed",
                    "job_id": job.job_id,
                    "command_category": category,
                    "status": job.status.name,
                    "error": job.error,
                    "retry_count": job.retry_count,
                },
            ))
        except Exception:
            self._logger.exception("Failed to publish execution event")
