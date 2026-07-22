"""Tests for the Execution Engine."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from atlas_core.context import AtlasContext, ContextManager, PermissionContext, UserContext
from atlas_core.events import EventBus
from atlas_core.execution import (
    Command,
    CommandCategory,
    CommandExecutor,
    CommandRegistry,
    CommandResult,
    ExecutionEngine,
    ExecutionHistory,
    ExecutionJob,
    ExecutionMetrics,
    ExecutionStatus,
    FileCommand,
    JobQueue,
    PermissionGuard,
    ProcessCommand,
    RollbackManager,
    ScriptCommand,
    SystemCommand,
    ToolCommand,
    WorkerPool,
    WorkflowCommand,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def context_manager() -> ContextManager:
    return ContextManager(EventBus(max_history=100))


@pytest.fixture
def engine(bus: EventBus) -> ExecutionEngine:
    return ExecutionEngine(bus)


@pytest.fixture
def guard() -> PermissionGuard:
    return PermissionGuard()


@pytest.fixture
def rollback_mgr() -> RollbackManager:
    return RollbackManager()


@pytest.fixture
def metrics() -> ExecutionMetrics:
    return ExecutionMetrics()


@pytest.fixture
def history() -> ExecutionHistory:
    return ExecutionHistory()


@pytest.fixture
def executor(guard: PermissionGuard, rollback_mgr: RollbackManager, metrics: ExecutionMetrics) -> CommandExecutor:
    return CommandExecutor(guard, rollback_mgr, metrics)


@pytest.fixture
def queue() -> JobQueue:
    return JobQueue()


# ======================================================================
# Enums
# ======================================================================


class TestCommandCategory:
    def test_values(self) -> None:
        assert CommandCategory.FILE.value == "file"
        assert CommandCategory.PROCESS.value == "process"
        assert CommandCategory.TOOL.value == "tool"
        assert CommandCategory.SCRIPT.value == "script"
        assert CommandCategory.SYSTEM.value == "system"
        assert CommandCategory.WORKFLOW.value == "workflow"


class TestExecutionStatus:
    def test_values(self) -> None:
        assert ExecutionStatus.PENDING != ExecutionStatus.RUNNING
        assert ExecutionStatus.SUCCESS != ExecutionStatus.FAILED
        assert ExecutionStatus.ROLLING_BACK != ExecutionStatus.ROLLED_BACK


# ======================================================================
# Command ABC
# ======================================================================


class TestCommandABC:
    def test_instantiation_raises(self) -> None:
        with pytest.raises(TypeError):
            Command()

    def test_command_id_is_uuid(self) -> None:
        cmd = FileCommand("read", "/tmp/test")
        assert len(cmd.command_id) == 36
        assert "-" in cmd.command_id


# ======================================================================
# Concrete Commands
# ======================================================================


class TestFileCommand:
    async def test_execute_success(self) -> None:
        cmd = FileCommand("read", "/tmp/test.txt")
        result = await cmd.execute()
        assert result.success
        assert "read" in result.message

    async def test_rollback(self) -> None:
        cmd = FileCommand("write", "/tmp/test.txt", "data")
        await cmd.execute()
        await cmd.rollback()  # should not raise

    async def test_validate_empty_path(self) -> None:
        cmd = FileCommand("read", "")
        errors = await cmd.validate()
        assert "File path is required" in errors

    async def test_validate_valid(self) -> None:
        cmd = FileCommand("read", "/tmp/test.txt")
        errors = await cmd.validate()
        assert errors == []

    def test_category(self) -> None:
        assert FileCommand("read", "/tmp/f").category == CommandCategory.FILE

    def test_permissions(self) -> None:
        cmd = FileCommand("delete", "/tmp/f")
        assert cmd.required_permissions == ["file.delete"]


class TestProcessCommand:
    async def test_execute_success(self) -> None:
        cmd = ProcessCommand("start", "nginx")
        result = await cmd.execute()
        assert result.success

    async def test_rollback(self) -> None:
        cmd = ProcessCommand("start", "nginx")
        await cmd.execute()
        await cmd.rollback()

    async def test_validate_empty_name(self) -> None:
        cmd = ProcessCommand("start", "")
        errors = await cmd.validate()
        assert "Process name is required" in errors

    def test_category(self) -> None:
        assert ProcessCommand("stop", "p").category == CommandCategory.PROCESS

    def test_permissions(self) -> None:
        assert ProcessCommand("restart", "p").required_permissions == ["process.restart"]


class TestToolCommand:
    async def test_execute_success(self) -> None:
        cmd = ToolCommand("git", ["status"])
        result = await cmd.execute()
        assert result.success
        assert result.data["tool"] == "git"

    async def test_validate_empty_tool(self) -> None:
        cmd = ToolCommand("")
        errors = await cmd.validate()
        assert "Tool name is required" in errors

    def test_category(self) -> None:
        assert ToolCommand("curl").category == CommandCategory.TOOL

    def test_permissions(self) -> None:
        assert ToolCommand("docker").required_permissions == ["tool.docker"]

    def test_default_args(self) -> None:
        cmd = ToolCommand("git")
        assert cmd.args == []


class TestScriptCommand:
    async def test_execute_success(self) -> None:
        cmd = ScriptCommand("/tmp/deploy.sh", "bash")
        result = await cmd.execute()
        assert result.success
        assert result.data["script"] == "/tmp/deploy.sh"

    async def test_validate_empty_path(self) -> None:
        cmd = ScriptCommand("")
        errors = await cmd.validate()
        assert "Script path is required" in errors

    def test_category(self) -> None:
        assert ScriptCommand("/tmp/s.sh").category == CommandCategory.SCRIPT

    def test_permissions(self) -> None:
        assert ScriptCommand("/tmp/s.sh").required_permissions == ["script.execute"]


class TestSystemCommand:
    async def test_execute_success(self) -> None:
        cmd = SystemCommand("shutdown", {"delay": 30})
        result = await cmd.execute()
        assert result.success

    async def test_validate_empty_operation(self) -> None:
        cmd = SystemCommand("")
        errors = await cmd.validate()
        assert "System operation is required" in errors

    def test_category(self) -> None:
        assert SystemCommand("reboot").category == CommandCategory.SYSTEM

    def test_permissions(self) -> None:
        assert SystemCommand("reboot").required_permissions == ["system.reboot"]

    def test_default_params(self) -> None:
        cmd = SystemCommand("reboot")
        assert cmd.params == {}


class TestWorkflowCommand:
    async def test_execute_success(self) -> None:
        cmd = WorkflowCommand("deploy", {"env": "prod"})
        result = await cmd.execute()
        assert result.success
        assert result.data["workflow"] == "deploy"

    async def test_validate_empty_name(self) -> None:
        cmd = WorkflowCommand("")
        errors = await cmd.validate()
        assert "Workflow name is required" in errors

    def test_category(self) -> None:
        assert WorkflowCommand("deploy").category == CommandCategory.WORKFLOW

    def test_permissions(self) -> None:
        assert WorkflowCommand("deploy").required_permissions == ["workflow.execute"]

    def test_default_payload(self) -> None:
        cmd = WorkflowCommand("deploy")
        assert cmd.payload == {}


# ======================================================================
# CommandResult
# ======================================================================


class TestCommandResult:
    def test_defaults(self) -> None:
        r = CommandResult()
        assert r.success
        assert r.message == ""
        assert r.data == {}
        assert r.error == ""

    def test_custom(self) -> None:
        r = CommandResult(success=False, error="oops", data={"key": "val"})
        assert not r.success
        assert r.error == "oops"
        assert r.data["key"] == "val"


# ======================================================================
# ExecutionJob
# ======================================================================


class TestExecutionJob:
    def test_defaults(self) -> None:
        job = ExecutionJob()
        assert job.status == ExecutionStatus.PENDING
        assert job.max_retries == 3
        assert job.retry_count == 0
        assert job.job_id is not None

    def test_with_command(self) -> None:
        cmd = FileCommand("read", "/tmp/f")
        job = ExecutionJob(command=cmd)
        assert job.command is cmd


# ======================================================================
# PermissionGuard
# ======================================================================


class TestPermissionGuard:
    def test_check_no_context_denies_all(self, guard: PermissionGuard) -> None:
        cmd = FileCommand("read", "/tmp/f")
        denied = guard.check(cmd)
        assert denied == ["file.read"]

    def test_check_no_permissions_needed(self, guard: PermissionGuard) -> None:
        class NoPermCommand(Command):
            @property
            def category(self) -> CommandCategory:
                return CommandCategory.SYSTEM
            async def execute(self, context=None) -> CommandResult:
                return CommandResult()
        cmd = NoPermCommand()
        denied = guard.check(cmd)
        assert denied == []

    def test_check_granted(self, guard: PermissionGuard) -> None:
        cmd = FileCommand("read", "/tmp/f")
        ctx = AtlasContext(
            permissions=PermissionContext(permissions={"file.read": True}),
        )
        guard.set_context(ctx)
        denied = guard.check(cmd)
        assert denied == []

    def test_check_denied(self, guard: PermissionGuard) -> None:
        cmd = FileCommand("delete", "/tmp/f")
        ctx = AtlasContext(
            permissions=PermissionContext(permissions={"file.read": True}),
        )
        guard.set_context(ctx)
        denied = guard.check(cmd)
        assert denied == ["file.delete"]

    async def test_authorize_true(self, guard: PermissionGuard) -> None:
        cmd = FileCommand("read", "/tmp/f")
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        guard.set_context(ctx)
        assert await guard.authorize(cmd) is True

    async def test_authorize_false(self, guard: PermissionGuard) -> None:
        cmd = FileCommand("delete", "/tmp/f")
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        guard.set_context(ctx)
        assert await guard.authorize(cmd) is False


# ======================================================================
# RollbackManager
# ======================================================================


class TestRollbackManager:
    async def test_rollback_success(self, rollback_mgr: RollbackManager) -> None:
        cmd = FileCommand("write", "/tmp/f", "data")
        await cmd.execute()
        job = ExecutionJob(command=cmd, status=ExecutionStatus.SUCCESS)
        rollback_mgr.record(job)
        result = await rollback_mgr.rollback(job)
        assert result.success

    async def test_rollback_no_command(self, rollback_mgr: RollbackManager) -> None:
        job = ExecutionJob(status=ExecutionStatus.SUCCESS)
        result = await rollback_mgr.rollback(job)
        assert not result.success

    async def test_rollback_all(self, rollback_mgr: RollbackManager) -> None:
        cmd1 = FileCommand("write", "/tmp/f1", "a")
        cmd2 = FileCommand("write", "/tmp/f2", "b")
        await cmd1.execute()
        await cmd2.execute()
        j1 = ExecutionJob(command=cmd1, status=ExecutionStatus.SUCCESS)
        j2 = ExecutionJob(command=cmd2, status=ExecutionStatus.SUCCESS)
        rollback_mgr.record(j1)
        rollback_mgr.record(j2)
        results = await rollback_mgr.rollback_all()
        assert len(results) == 2

    def test_can_rollback_success(self, rollback_mgr: RollbackManager) -> None:
        cmd = FileCommand("read", "/tmp/f")
        job = ExecutionJob(command=cmd, status=ExecutionStatus.SUCCESS)
        assert rollback_mgr.can_rollback(job) is True

    def test_can_rollback_failed(self, rollback_mgr: RollbackManager) -> None:
        cmd = FileCommand("read", "/tmp/f")
        job = ExecutionJob(command=cmd, status=ExecutionStatus.FAILED)
        assert rollback_mgr.can_rollback(job) is False

    def test_can_rollback_no_command(self, rollback_mgr: RollbackManager) -> None:
        job = ExecutionJob(status=ExecutionStatus.SUCCESS)
        assert rollback_mgr.can_rollback(job) is False

    def test_record(self, rollback_mgr: RollbackManager) -> None:
        job = ExecutionJob()
        rollback_mgr.record(job)
        assert len(rollback_mgr._history) == 1


# ======================================================================
# CommandRegistry
# ======================================================================


class TestCommandRegistry:
    def test_register_defaults(self) -> None:
        reg = CommandRegistry()
        reg._register_defaults()
        assert reg.count == 6
        assert CommandCategory.FILE in reg.categories
        assert CommandCategory.WORKFLOW in reg.categories

    def test_get_types(self) -> None:
        reg = CommandRegistry()
        reg._register_defaults()
        types = reg.get_types(CommandCategory.FILE)
        assert FileCommand in types

    def test_create(self) -> None:
        reg = CommandRegistry()
        reg._register_defaults()
        cmd = reg.create(CommandCategory.FILE, operation="read", path="/tmp/f")
        assert cmd is not None
        assert isinstance(cmd, FileCommand)

    def test_create_unknown_category(self) -> None:
        reg = CommandRegistry()
        cmd = reg.create(CommandCategory.SCRIPT)
        assert cmd is None

    def test_register_custom(self) -> None:
        reg = CommandRegistry()
        reg.register(FileCommand)
        assert reg.count == 1

    def test_count(self) -> None:
        reg = CommandRegistry()
        assert reg.count == 0
        reg.register(FileCommand)
        assert reg.count == 1


# ======================================================================
# ExecutionHistory
# ======================================================================


class TestExecutionHistory:
    def test_record_and_get(self, history: ExecutionHistory) -> None:
        job = ExecutionJob()
        history.record(job)
        assert history.get(job.job_id) is job

    def test_get_missing(self, history: ExecutionHistory) -> None:
        assert history.get("nonexistent") is None

    def test_query_by_category(self, history: ExecutionHistory) -> None:
        j1 = ExecutionJob(command=FileCommand("read", "/tmp/f"))
        j2 = ExecutionJob(command=ProcessCommand("start", "nginx"))
        history.record(j1)
        history.record(j2)
        results = history.query(category=CommandCategory.FILE)
        assert len(results) == 1
        assert results[0] is j1

    def test_query_by_status(self, history: ExecutionHistory) -> None:
        j1 = ExecutionJob(status=ExecutionStatus.SUCCESS)
        j2 = ExecutionJob(status=ExecutionStatus.FAILED)
        history.record(j1)
        history.record(j2)
        results = history.query(status=ExecutionStatus.SUCCESS)
        assert len(results) == 1

    def test_query_limit(self, history: ExecutionHistory) -> None:
        for _ in range(10):
            history.record(ExecutionJob())
        results = history.query(limit=3)
        assert len(results) == 3

    def test_all(self, history: ExecutionHistory) -> None:
        history.record(ExecutionJob())
        history.record(ExecutionJob())
        assert len(history.all) == 2

    def test_clear(self, history: ExecutionHistory) -> None:
        history.record(ExecutionJob())
        history.clear()
        assert history.size == 0

    def test_max_size(self) -> None:
        history = ExecutionHistory(max_size=3)
        for _ in range(5):
            history.record(ExecutionJob())
        assert history.size == 3

    def test_size(self, history: ExecutionHistory) -> None:
        assert history.size == 0
        history.record(ExecutionJob())
        assert history.size == 1


# ======================================================================
# ExecutionMetrics
# ======================================================================


class TestExecutionMetrics:
    def test_record_success(self, metrics: ExecutionMetrics) -> None:
        metrics.record(CommandCategory.FILE, success=True, timing_ms=100)
        assert metrics.overall.total == 1
        assert metrics.overall.success == 1

    def test_record_failure(self, metrics: ExecutionMetrics) -> None:
        metrics.record(CommandCategory.FILE, success=False, timing_ms=50)
        assert metrics.overall.total == 1
        assert metrics.overall.failed == 1

    def test_record_rolled_back(self, metrics: ExecutionMetrics) -> None:
        metrics.record(CommandCategory.FILE, success=True, timing_ms=100, rolled_back=True)
        assert metrics.overall.rolled_back == 1

    def test_category_stats(self, metrics: ExecutionMetrics) -> None:
        metrics.record(CommandCategory.FILE, success=True, timing_ms=100)
        metrics.record(CommandCategory.FILE, success=False, timing_ms=50)
        stats = metrics.category_stats(CommandCategory.FILE)
        assert stats.total == 2
        assert stats.success == 1
        assert stats.failed == 1

    def test_category_stats_empty(self, metrics: ExecutionMetrics) -> None:
        stats = metrics.category_stats(CommandCategory.PROCESS)
        assert stats.total == 0

    def test_all_categories(self, metrics: ExecutionMetrics) -> None:
        metrics.record(CommandCategory.FILE, success=True, timing_ms=100)
        metrics.record(CommandCategory.PROCESS, success=True, timing_ms=200)
        cats = metrics.all_categories
        assert "file" in cats
        assert "process" in cats

    def test_avg_timing_ms(self, metrics: ExecutionMetrics) -> None:
        metrics.record(CommandCategory.FILE, success=True, timing_ms=100)
        metrics.record(CommandCategory.FILE, success=True, timing_ms=200)
        assert metrics.avg_timing_ms(CommandCategory.FILE) == 150.0

    def test_avg_timing_ms_overall(self, metrics: ExecutionMetrics) -> None:
        metrics.record(CommandCategory.FILE, success=True, timing_ms=100)
        assert metrics.avg_timing_ms() == 100.0

    def test_avg_timing_ms_empty(self, metrics: ExecutionMetrics) -> None:
        assert metrics.avg_timing_ms() == 0.0
        assert metrics.avg_timing_ms(CommandCategory.FILE) == 0.0

# ======================================================================
# CommandExecutor
# ======================================================================


class TestCommandExecutor:
    async def test_execute_success(self, guard: PermissionGuard, metrics: ExecutionMetrics) -> None:
        cmd = FileCommand("read", "/tmp/f")
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        guard.set_context(ctx)
        executor = CommandExecutor(guard, RollbackManager(), metrics)
        job = await executor.execute(cmd)
        assert job.status == ExecutionStatus.SUCCESS
        assert job.result is not None
        assert job.result.success

    async def test_execute_validation_failure(self, executor: CommandExecutor) -> None:
        cmd = FileCommand("read", "")
        job = await executor.execute(cmd)
        assert job.status == ExecutionStatus.FAILED
        assert "File path is required" in job.error

    async def test_execute_permission_denied(self, executor: CommandExecutor) -> None:
        cmd = FileCommand("read", "/tmp/f")
        job = await executor.execute(cmd)
        assert job.status == ExecutionStatus.FAILED
        assert "Permission denied" in job.error

    async def test_execute_with_permissions(self, guard: PermissionGuard, metrics: ExecutionMetrics) -> None:
        cmd = FileCommand("read", "/tmp/f")
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        guard.set_context(ctx)
        executor = CommandExecutor(guard, RollbackManager(), metrics)
        job = await executor.execute(cmd)
        assert job.status == ExecutionStatus.SUCCESS

    async def test_execute_retry_on_exception(self, guard: PermissionGuard, metrics: ExecutionMetrics) -> None:
        class FlakyCommand(Command):
            def __init__(self) -> None:
                super().__init__()
                self.attempts = 0

            @property
            def category(self) -> CommandCategory:
                return CommandCategory.SYSTEM

            async def execute(self, context=None) -> CommandResult:
                self.attempts += 1
                if self.attempts < 3:
                    raise RuntimeError("transient error")
                return CommandResult(success=True, message="ok")

        ctx = AtlasContext(permissions=PermissionContext(permissions={}))
        guard.set_context(ctx)
        executor = CommandExecutor(guard, RollbackManager(), metrics)
        cmd = FlakyCommand()
        job = await executor.execute(cmd, max_retries=3)
        assert job.status == ExecutionStatus.SUCCESS
        assert cmd.attempts == 3

    async def test_execute_retry_exhausted(self, guard: PermissionGuard, metrics: ExecutionMetrics) -> None:
        class AlwaysFailsCommand(Command):
            @property
            def category(self) -> CommandCategory:
                return CommandCategory.SYSTEM

            async def execute(self, context=None) -> CommandResult:
                raise RuntimeError("always fails")

        ctx = AtlasContext(permissions=PermissionContext(permissions={}))
        guard.set_context(ctx)
        executor = CommandExecutor(guard, RollbackManager(), metrics)
        cmd = AlwaysFailsCommand()
        job = await executor.execute(cmd, max_retries=2)
        assert job.status == ExecutionStatus.FAILED
        assert job.retry_count == 3

    async def test_execute_produces_error_result(self, executor: CommandExecutor) -> None:
        class ErrorCommand(Command):
            @property
            def category(self) -> CommandCategory:
                return CommandCategory.SYSTEM

            async def execute(self, context=None) -> CommandResult:
                return CommandResult(success=False, error="command failed")

        ctx = AtlasContext(permissions=PermissionContext(permissions={}))
        executor._permission_guard.set_context(ctx)
        job = await executor.execute(ErrorCommand())
        assert job.status == ExecutionStatus.FAILED
        assert "command failed" in job.error


# ======================================================================
# JobQueue
# ======================================================================


class TestJobQueue:
    async def test_put_get(self, queue: JobQueue) -> None:
        job = ExecutionJob()
        await queue.put(job)
        retrieved = await queue.get()
        assert retrieved is job

    async def test_size(self, queue: JobQueue) -> None:
        assert queue.size == 0
        await queue.put(ExecutionJob())
        assert queue.size == 1

    async def test_task_done(self, queue: JobQueue) -> None:
        await queue.put(ExecutionJob())
        await queue.get()
        queue.task_done()  # should not raise

    async def test_join(self, queue: JobQueue) -> None:
        await queue.put(ExecutionJob())
        await queue.put(ExecutionJob())
        got1 = await queue.get()
        got2 = await queue.get()
        queue.task_done()
        queue.task_done()
        await queue.join()  # should not raise


# ======================================================================
# WorkerPool
# ======================================================================


class TestWorkerPool:
    async def test_start_stop(self, executor: CommandExecutor, queue: JobQueue, history: ExecutionHistory) -> None:
        pool = WorkerPool(executor, queue, history, num_workers=2)
        await pool.start()
        assert pool._running
        assert len(pool._workers) == 2
        await pool.stop()
        assert not pool._running

    async def test_process_job(self, guard: PermissionGuard, metrics: ExecutionMetrics, history: ExecutionHistory) -> None:
        cmd = FileCommand("read", "/tmp/f")
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        guard.set_context(ctx)
        executor = CommandExecutor(guard, RollbackManager(), metrics)
        queue = JobQueue()
        pool = WorkerPool(executor, queue, history, num_workers=1)
        await pool.start()

        job = ExecutionJob(command=cmd, context=ctx)
        await queue.put(job)
        await asyncio.sleep(0.2)
        await pool.stop()
        assert history.size == 1

    async def test_start_idempotent(self, executor: CommandExecutor, queue: JobQueue, history: ExecutionHistory) -> None:
        pool = WorkerPool(executor, queue, history)
        await pool.start()
        await pool.start()  # second start should be no-op
        assert pool._running
        await pool.stop()


# ======================================================================
# ExecutionEngine (IService)
# ======================================================================


class TestExecutionEngine:
    async def test_initialize(self, engine: ExecutionEngine) -> None:
        assert engine.name == "execution_engine"
        await engine.initialize()

    async def test_start_stop(self, engine: ExecutionEngine) -> None:
        await engine.start()
        assert engine._running
        await engine.stop()
        assert not engine._running

    async def test_health_check(self, engine: ExecutionEngine) -> None:
        health = await engine.health_check()
        assert health.healthy
        assert health.metadata["registered_types"] == 6
        assert health.metadata["commands_executed"] == 0

    async def test_execute_success(self, engine: ExecutionEngine, context_manager: ContextManager) -> None:
        cmd = FileCommand("read", "/tmp/f")
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        await context_manager.replace_context(ctx)
        engine.set_context(ctx)
        await engine.start()
        job = await engine.execute(cmd)
        assert job.status == ExecutionStatus.SUCCESS
        await engine.stop()

    async def test_execute_permission_denied(self, engine: ExecutionEngine) -> None:
        cmd = FileCommand("read", "/tmp/f")
        job = await engine.execute(cmd)
        assert job.status == ExecutionStatus.FAILED
        assert "Permission denied" in job.error

    async def test_submit_async(self, engine: ExecutionEngine, context_manager: ContextManager) -> None:
        cmd = FileCommand("read", "/tmp/f")
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        await context_manager.replace_context(ctx)
        engine.set_context(ctx)
        await engine.start()
        job_id = await engine.submit(cmd)
        assert job_id is not None
        assert len(job_id) == 36
        await asyncio.sleep(0.3)
        await engine.stop()

    async def test_rollback_success(self, engine: ExecutionEngine, context_manager: ContextManager) -> None:
        cmd = FileCommand("read", "/tmp/f")
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        await context_manager.replace_context(ctx)
        engine.set_context(ctx)
        await engine.start()
        job = await engine.execute(cmd)
        result = await engine.rollback(job.job_id)
        assert result is not None
        assert result.success
        await engine.stop()

    async def test_rollback_missing_job(self, engine: ExecutionEngine) -> None:
        result = await engine.rollback("nonexistent")
        assert result is None

    async def test_rollback_failed_job(self, engine: ExecutionEngine) -> None:
        cmd = FileCommand("read", "/tmp/f")
        job = await engine.execute(cmd)  # will fail (no permissions)
        result = await engine.rollback(job.job_id)
        assert result is not None
        assert not result.success

    async def test_rollback_all(self, engine: ExecutionEngine, context_manager: ContextManager) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True, "file.write": True}))
        await context_manager.replace_context(ctx)
        engine.set_context(ctx)
        await engine.start()
        await engine.execute(FileCommand("read", "/tmp/f1"))
        await engine.execute(FileCommand("read", "/tmp/f2"))
        results = await engine.rollback_all()
        assert len(results) >= 2
        await engine.stop()

    async def test_set_context(self, engine: ExecutionEngine) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        engine.set_context(ctx)
        assert engine.permission_guard._context is ctx

    async def test_registry_accessor(self, engine: ExecutionEngine) -> None:
        assert engine.registry.count == 6

    async def test_history_accessor(self, engine: ExecutionEngine) -> None:
        assert engine.history.size == 0

    async def test_metrics_accessor(self, engine: ExecutionEngine) -> None:
        assert engine.metrics.overall.total == 0

    async def test_permission_guard_accessor(self, engine: ExecutionEngine) -> None:
        assert engine.permission_guard is not None

    async def test_rollback_manager_accessor(self, engine: ExecutionEngine) -> None:
        assert engine.rollback_manager is not None

    async def test_executor_accessor(self, engine: ExecutionEngine) -> None:
        assert engine.executor is not None

    async def test_job_queue_accessor(self, engine: ExecutionEngine) -> None:
        assert engine.job_queue is not None

    async def test_worker_pool_accessor(self, engine: ExecutionEngine) -> None:
        assert engine.worker_pool is not None

    async def test_health_after_execution(self, engine: ExecutionEngine, context_manager: ContextManager) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        await context_manager.replace_context(ctx)
        engine.set_context(ctx)
        await engine.start()
        await engine.execute(FileCommand("read", "/tmp/f"))
        health = await engine.health_check()
        assert health.metadata["commands_executed"] == 1
        assert health.metadata["history_size"] == 1
        await engine.stop()

    async def test_publishes_event(self, bus: EventBus) -> None:
        engine = ExecutionEngine(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("workflow", handler)
        ctx = AtlasContext(permissions=PermissionContext(permissions={"file.read": True}))
        engine.set_context(ctx)
        await engine.start()
        await engine.execute(FileCommand("read", "/tmp/f"))
        assert len(received) >= 1
        await engine.stop()
