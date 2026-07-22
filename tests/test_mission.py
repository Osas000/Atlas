"""Tests for Mission Control."""

import pytest

from atlas_core.context import AtlasContext
from atlas_core.events import EventBus
from atlas_core.interfaces import SubsystemResponse
from atlas_core.mission import (
    HistoryEntry,
    Mission,
    MissionControl,
    MissionContextBridge,
    MissionEventBridge,
    MissionExecutor,
    MissionHistory,
    MissionMetrics,
    MissionPlan,
    MissionPlanner,
    MissionScheduler,
    MissionStateMachine,
    MissionStep,
    MissionTemplate,
    MissionTemplates,
    ScheduledMission,
    StepState,
    Subsystem,
    MissionStatus,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=200)


@pytest.fixture
def ctrl(bus: EventBus) -> MissionControl:
    return MissionControl(bus)


@pytest.fixture
def state_machine() -> MissionStateMachine:
    return MissionStateMachine()


@pytest.fixture
def planner() -> MissionPlanner:
    return MissionPlanner()


@pytest.fixture
def scheduler() -> MissionScheduler:
    return MissionScheduler()


@pytest.fixture
def executor(bus: EventBus) -> MissionExecutor:
    return MissionExecutor(bus)


@pytest.fixture
def history() -> MissionHistory:
    return MissionHistory()


@pytest.fixture
def templates() -> MissionTemplates:
    return MissionTemplates()


@pytest.fixture
def context_bridge(bus: EventBus) -> MissionContextBridge:
    return MissionContextBridge(bus)


@pytest.fixture
def event_bridge(bus: EventBus) -> MissionEventBridge:
    return MissionEventBridge(bus)


# ======================================================================
# Enums
# ======================================================================


class TestEnums:
    def test_subsystem_values(self) -> None:
        assert Subsystem.MEMORY.value == "memory"
        assert Subsystem.KNOWLEDGE.value == "knowledge"
        assert Subsystem.INTELLIGENCE.value == "intelligence"
        assert Subsystem.EXECUTION.value == "execution"
        assert Subsystem.BROWSER.value == "browser"
        assert Subsystem.OPPORTUNITY.value == "opportunity"
        assert Subsystem.NOTIFICATION.value == "notification"
        assert len(Subsystem) == 7

    def test_mission_status_values(self) -> None:
        assert MissionStatus.CREATED.name == "CREATED"
        assert MissionStatus.PLANNING.name == "PLANNING"
        assert MissionStatus.COMPLETED.name == "COMPLETED"
        assert MissionStatus.FAILED.name == "FAILED"
        assert MissionStatus.CANCELLED.name == "CANCELLED"
        assert MissionStatus.PAUSED.name == "PAUSED"
        assert MissionStatus.BLOCKED.name == "BLOCKED"
        assert MissionStatus.WAITING.name == "WAITING"
        assert MissionStatus.RUNNING.name == "RUNNING"
        assert len(MissionStatus) == 9

    def test_step_state_values(self) -> None:
        assert StepState.PENDING.name == "PENDING"
        assert StepState.RUNNING.name == "RUNNING"
        assert StepState.COMPLETED.name == "COMPLETED"
        assert StepState.FAILED.name == "FAILED"
        assert StepState.SKIPPED.name == "SKIPPED"


# ======================================================================
# Mission (immutable)
# ======================================================================


class TestMission:
    def test_mission_creation(self) -> None:
        m = Mission(title="Test Mission", mission_id="test-1")
        assert m.title == "Test Mission"
        assert m.mission_id == "test-1"
        assert m.status == MissionStatus.CREATED
        assert m.priority == 0
        assert m.tags == []

    def test_mission_immutable(self) -> None:
        m = Mission(title="Original")
        with pytest.raises((TypeError, AttributeError)):
            m.title = "Modified"  # type: ignore[misc]

    def test_mission_default_values(self) -> None:
        m = Mission()
        assert m.title == ""
        assert m.description == ""
        assert m.objective == ""
        assert m.status == MissionStatus.CREATED

    def test_mission_with_tags(self) -> None:
        m = Mission(title="Research", tags=["research", "urgent"])
        assert "research" in m.tags


# ======================================================================
# MissionStep (immutable)
# ======================================================================


class TestMissionStep:
    def test_step_creation(self) -> None:
        s = MissionStep(title="Test Step", order=1, subsystem=Subsystem.KNOWLEDGE)
        assert s.title == "Test Step"
        assert s.order == 1
        assert s.subsystem == Subsystem.KNOWLEDGE
        assert s.state == StepState.PENDING
        assert s.max_retries == 3

    def test_step_immutable(self) -> None:
        s = MissionStep(title="Step")
        with pytest.raises((TypeError, AttributeError)):
            s.title = "Modified"  # type: ignore[misc]

    def test_step_with_dependencies(self) -> None:
        s = MissionStep(order=2, dependencies=["step-1"])
        assert "step-1" in s.dependencies

    def test_step_default_subsystem(self) -> None:
        s = MissionStep()
        assert s.subsystem == Subsystem.KNOWLEDGE


# ======================================================================
# MissionPlan
# ======================================================================


class TestMissionPlan:
    def test_plan_creation(self) -> None:
        m = Mission(title="Test")
        steps = [MissionStep(order=1)]
        plan = MissionPlan(mission=m, steps=steps)
        assert plan.mission.title == "Test"
        assert len(plan.steps) == 1

    def test_plan_empty_steps(self) -> None:
        m = Mission()
        plan = MissionPlan(mission=m)
        assert plan.steps == []


# ======================================================================
# MissionStateMachine
# ======================================================================


class TestMissionStateMachine:
    def test_legal_created_to_planning(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.CREATED, MissionStatus.PLANNING)
        assert result == MissionStatus.PLANNING

    def test_legal_created_to_cancelled(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.CREATED, MissionStatus.CANCELLED)
        assert result == MissionStatus.CANCELLED

    def test_legal_planning_to_running(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.PLANNING, MissionStatus.RUNNING)
        assert result == MissionStatus.RUNNING

    def test_legal_running_to_completed(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.RUNNING, MissionStatus.COMPLETED)
        assert result == MissionStatus.COMPLETED

    def test_legal_running_to_failed(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.RUNNING, MissionStatus.FAILED)
        assert result == MissionStatus.FAILED

    def test_legal_running_to_paused(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.RUNNING, MissionStatus.PAUSED)
        assert result == MissionStatus.PAUSED

    def test_legal_running_to_blocked(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.RUNNING, MissionStatus.BLOCKED)
        assert result == MissionStatus.BLOCKED

    def test_legal_running_to_waiting(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.RUNNING, MissionStatus.WAITING)
        assert result == MissionStatus.WAITING

    def test_legal_paused_to_running(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.PAUSED, MissionStatus.RUNNING)
        assert result == MissionStatus.RUNNING

    def test_legal_blocked_to_waiting(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.BLOCKED, MissionStatus.WAITING)
        assert result == MissionStatus.WAITING

    def test_legal_failed_to_created(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.FAILED, MissionStatus.CREATED)
        assert result == MissionStatus.CREATED

    def test_legal_cancelled_to_created(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.CANCELLED, MissionStatus.CREATED)
        assert result == MissionStatus.CREATED

    def test_legal_same_status(self, state_machine: MissionStateMachine) -> None:
        result = state_machine.transition(MissionStatus.RUNNING, MissionStatus.RUNNING)
        assert result == MissionStatus.RUNNING

    # --- Illegal transitions ---

    def test_illegal_created_to_completed(self, state_machine: MissionStateMachine) -> None:
        with pytest.raises(ValueError, match="Illegal mission status transition"):
            state_machine.transition(MissionStatus.CREATED, MissionStatus.COMPLETED)

    def test_illegal_planning_to_completed(self, state_machine: MissionStateMachine) -> None:
        with pytest.raises(ValueError):
            state_machine.transition(MissionStatus.PLANNING, MissionStatus.COMPLETED)

    def test_illegal_completed_to_running(self, state_machine: MissionStateMachine) -> None:
        with pytest.raises(ValueError):
            state_machine.transition(MissionStatus.COMPLETED, MissionStatus.RUNNING)

    def test_illegal_cancelled_to_running(self, state_machine: MissionStateMachine) -> None:
        with pytest.raises(ValueError):
            state_machine.transition(MissionStatus.CANCELLED, MissionStatus.RUNNING)

    def test_illegal_paused_to_completed(self, state_machine: MissionStateMachine) -> None:
        with pytest.raises(ValueError):
            state_machine.transition(MissionStatus.PAUSED, MissionStatus.COMPLETED)

    def test_is_legal_true(self, state_machine: MissionStateMachine) -> None:
        assert state_machine.is_legal(MissionStatus.CREATED, MissionStatus.PLANNING) is True

    def test_is_legal_false(self, state_machine: MissionStateMachine) -> None:
        assert state_machine.is_legal(MissionStatus.CREATED, MissionStatus.COMPLETED) is False


# ======================================================================
# MissionPlanner
# ======================================================================


class TestMissionPlanner:
    def test_plan_research_by_tag(self, planner: MissionPlanner) -> None:
        m = Mission(title="Anything", tags=["research"])
        plan = planner.plan(m)
        assert len(plan.steps) >= 4
        assert plan.steps[0].subsystem == Subsystem.KNOWLEDGE

    def test_plan_analyze_by_title(self, planner: MissionPlanner) -> None:
        m = Mission(title="Analyze Repository Structure")
        plan = planner.plan(m)
        assert len(plan.steps) >= 3
        subsystems = [s.subsystem for s in plan.steps]
        assert Subsystem.EXECUTION in subsystems

    def test_plan_write_by_tag(self, planner: MissionPlanner) -> None:
        m = Mission(title="Anything", tags=["write"])
        plan = planner.plan(m)
        assert len(plan.steps) >= 3

    def test_plan_review_by_title(self, planner: MissionPlanner) -> None:
        m = Mission(title="Review Code Quality")
        plan = planner.plan(m)
        assert len(plan.steps) >= 3

    def test_plan_opportunities_by_tag(self, planner: MissionPlanner) -> None:
        m = Mission(title="Anything", tags=["opportunities"])
        plan = planner.plan(m)
        assert len(plan.steps) >= 4
        assert plan.steps[0].subsystem == Subsystem.OPPORTUNITY

    def test_plan_daily_by_title(self, planner: MissionPlanner) -> None:
        m = Mission(title="Daily Review and Briefing")
        plan = planner.plan(m)
        assert len(plan.steps) >= 5

    def test_plan_build_by_tag(self, planner: MissionPlanner) -> None:
        m = Mission(title="Anything", tags=["build"])
        plan = planner.plan(m)
        assert len(plan.steps) >= 5
        assert Subsystem.EXECUTION in [s.subsystem for s in plan.steps]

    def test_plan_generic(self, planner: MissionPlanner) -> None:
        m = Mission(title="Some random task")
        plan = planner.plan(m)
        assert len(plan.steps) == 4
        assert plan.steps[0].subsystem == Subsystem.KNOWLEDGE
        assert plan.steps[1].subsystem == Subsystem.INTELLIGENCE
        assert plan.steps[2].subsystem == Subsystem.KNOWLEDGE
        assert plan.steps[3].subsystem == Subsystem.NOTIFICATION

    def test_plan_objective_match(self, planner: MissionPlanner) -> None:
        m = Mission(title="Task", objective="research the impact of AI")
        plan = planner.plan(m)
        assert len(plan.steps) >= 4


# ======================================================================
# MissionScheduler
# ======================================================================


class TestMissionScheduler:
    def test_enqueue_dequeue(self, scheduler: MissionScheduler) -> None:
        scheduler.enqueue("m1", priority=1)
        scheduler.enqueue("m2", priority=2)
        result = scheduler.dequeue()
        assert result is not None
        assert result.mission_id == "m2"  # higher priority first

    def test_dequeue_empty(self, scheduler: MissionScheduler) -> None:
        assert scheduler.dequeue() is None

    def test_peek(self, scheduler: MissionScheduler) -> None:
        scheduler.enqueue("m1", priority=1)
        scheduler.enqueue("m2", priority=2)
        peeked = scheduler.peek()
        assert peeked is not None
        assert peeked.mission_id == "m2"
        # Peek should not remove
        assert scheduler.queued_count == 2

    def test_peek_empty(self, scheduler: MissionScheduler) -> None:
        assert scheduler.peek() is None

    def test_pause_and_resume(self, scheduler: MissionScheduler) -> None:
        scheduler.enqueue("m1", priority=1)
        assert scheduler.pause("m1") is True
        assert scheduler.dequeue() is None  # paused, so not returned
        assert scheduler.resume("m1") is True
        result = scheduler.dequeue()
        assert result is not None
        assert result.mission_id == "m1"

    def test_pause_missing(self, scheduler: MissionScheduler) -> None:
        assert scheduler.pause("missing") is False

    def test_resume_missing(self, scheduler: MissionScheduler) -> None:
        assert scheduler.resume("missing") is False

    def test_cancel(self, scheduler: MissionScheduler) -> None:
        scheduler.enqueue("m1")
        assert scheduler.cancel("m1") is True
        assert scheduler.dequeue() is None

    def test_cancel_missing(self, scheduler: MissionScheduler) -> None:
        assert scheduler.cancel("missing") is False

    def test_priority_sorting(self, scheduler: MissionScheduler) -> None:
        scheduler.enqueue("low", priority=0)
        scheduler.enqueue("high", priority=10)
        scheduler.enqueue("mid", priority=5)
        assert scheduler.dequeue().mission_id == "high"
        assert scheduler.dequeue().mission_id == "mid"
        assert scheduler.dequeue().mission_id == "low"

    def test_queued_count(self, scheduler: MissionScheduler) -> None:
        assert scheduler.queued_count == 0
        scheduler.enqueue("m1")
        assert scheduler.queued_count == 1

    def test_pending_count(self, scheduler: MissionScheduler) -> None:
        scheduler.enqueue("m1")
        scheduler.enqueue("m2")
        scheduler.pause("m1")
        assert scheduler.pending_count == 1
        assert scheduler.paused_count == 1

    def test_list_queued(self, scheduler: MissionScheduler) -> None:
        scheduler.enqueue("m1")
        scheduler.enqueue("m2")
        assert len(scheduler.list_queued()) == 2

    def test_clear(self, scheduler: MissionScheduler) -> None:
        scheduler.enqueue("m1")
        scheduler.clear()
        assert scheduler.queued_count == 0


# ======================================================================
# MissionExecutor
# ======================================================================


class TestMissionExecutor:
    async def test_execute_step(self, executor: MissionExecutor) -> None:
        step = MissionStep(title="Test", order=1, subsystem=Subsystem.KNOWLEDGE)
        result = await executor.execute_step(step)
        assert result.state == StepState.COMPLETED
        assert result.result["subsystem"] == "knowledge"

    async def test_execute_plan(self, executor: MissionExecutor) -> None:
        m = Mission(title="Test")
        steps = [
            MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, step_id="s1"),
            MissionStep(order=2, subsystem=Subsystem.KNOWLEDGE, dependencies=["s1"]),
        ]
        plan = MissionPlan(mission=m, steps=steps)
        result = await executor.execute_plan(plan)
        assert len(result.steps) == 2
        assert all(s.state == StepState.COMPLETED for s in result.steps)

    async def test_execute_plan_with_registered_handler(self, executor: MissionExecutor) -> None:
        """Test that a registered handler's SubsystemResponse is used."""
        async def handler(payload: dict) -> SubsystemResponse:
            return SubsystemResponse(success=True, payload={"processed": True, "key": "value"})
        executor.register_handler(Subsystem.KNOWLEDGE, handler)
        m = Mission(title="Test")
        step = MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, payload={"key": "value"})
        plan = MissionPlan(mission=m, steps=[step])
        result = await executor.execute_plan(plan)
        assert result.steps[0].result.get("key") == "value"
        assert result.steps[0].result.get("processed") is True


# ======================================================================
# MissionHistory
# ======================================================================


class TestMissionHistory:
    def test_record_and_query(self, history: MissionHistory) -> None:
        entry = HistoryEntry(mission_id="m1", status=MissionStatus.COMPLETED)
        history.record(entry)
        results = history.query()
        assert len(results) == 1

    def test_query_by_status(self, history: MissionHistory) -> None:
        history.record(HistoryEntry(mission_id="m1", status=MissionStatus.COMPLETED))
        history.record(HistoryEntry(mission_id="m2", status=MissionStatus.FAILED))
        completed = history.query(status=MissionStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].mission_id == "m1"

    def test_properties(self, history: MissionHistory) -> None:
        history.record(HistoryEntry(mission_id="m1", status=MissionStatus.COMPLETED))
        history.record(HistoryEntry(mission_id="m2", status=MissionStatus.FAILED))
        history.record(HistoryEntry(mission_id="m3", status=MissionStatus.CANCELLED))
        history.record(HistoryEntry(mission_id="m4", status=MissionStatus.RUNNING))
        assert len(history.completed) == 1
        assert len(history.failed) == 1
        assert len(history.cancelled) == 1
        assert len(history.running) == 1

    def test_total_entries(self, history: MissionHistory) -> None:
        assert history.total_entries == 0
        history.record(HistoryEntry(mission_id="m1"))
        assert history.total_entries == 1

    def test_ring_buffer(self, history: MissionHistory) -> None:
        h = MissionHistory(max_size=2)
        h.record(HistoryEntry(mission_id="m1"))
        h.record(HistoryEntry(mission_id="m2"))
        h.record(HistoryEntry(mission_id="m3"))
        assert h.total_entries == 2
        assert h.query(limit=10)[0].mission_id == "m3"

    def test_clear(self, history: MissionHistory) -> None:
        history.record(HistoryEntry(mission_id="m1"))
        history.clear()
        assert history.total_entries == 0


# ======================================================================
# MissionMetrics
# ======================================================================


class TestMissionMetrics:
    def test_defaults(self) -> None:
        m = MissionMetrics()
        assert m.missions_created == 0
        assert m.success_rate == 0.0
        assert m.average_duration == 0.0

    def test_success_rate(self) -> None:
        m = MissionMetrics()
        m.missions_completed = 8
        m.missions_failed = 2
        assert m.success_rate == 80.0

    def test_success_rate_no_data(self) -> None:
        m = MissionMetrics()
        assert m.success_rate == 0.0

    def test_average_duration(self) -> None:
        m = MissionMetrics()
        m.total_duration = 100.0
        m.missions_completed = 4
        m.missions_failed = 1
        assert m.average_duration == 20.0

    def test_average_duration_no_data(self) -> None:
        m = MissionMetrics()
        assert m.average_duration == 0.0


# ======================================================================
# MissionTemplates
# ======================================================================


class TestMissionTemplates:
    def test_default_templates_registered(self, templates: MissionTemplates) -> None:
        assert templates.template_count() >= 7

    def test_get_template(self, templates: MissionTemplates) -> None:
        t = templates.get("research_topic")
        assert t is not None
        assert t.name == "research_topic"
        assert len(t.steps) >= 4

    def test_get_missing_template(self, templates: MissionTemplates) -> None:
        assert templates.get("nonexistent") is None

    def test_list_templates(self, templates: MissionTemplates) -> None:
        names = [t.name for t in templates.list_templates()]
        assert "research_topic" in names
        assert "build_project" in names

    def test_apply_template(self, templates: MissionTemplates) -> None:
        m = Mission(title="Research AI")
        plan = templates.apply("research_topic", m)
        assert plan is not None
        assert len(plan.steps) >= 4
        assert plan.mission.title == "Research AI"

    def test_apply_missing_template(self, templates: MissionTemplates) -> None:
        m = Mission(title="Test")
        assert templates.apply("nonexistent", m) is None

    def test_register_custom_template(self, templates: MissionTemplates) -> None:
        t = MissionTemplate(
            name="custom",
            title="Custom",
            description="Custom template",
            objective="Do custom thing",
            tags=["custom"],
        )
        templates.register(t)
        assert templates.get("custom") is t

    def test_clear(self, templates: MissionTemplates) -> None:
        templates.clear()
        assert templates.template_count() == 0


# ======================================================================
# MissionContextBridge
# ======================================================================


class TestMissionContextBridge:
    async def test_sync_to_context(self, context_bridge: MissionContextBridge) -> None:
        ctx = AtlasContext()
        m = Mission(title="Test", mission_id="m1")
        step = MissionStep(title="Step 1", subsystem=Subsystem.KNOWLEDGE)
        await context_bridge.sync_to_context(ctx, m, step, 0.5)
        # Should not raise

    async def test_sync_without_step(self, context_bridge: MissionContextBridge) -> None:
        ctx = AtlasContext()
        m = Mission(title="Test")
        await context_bridge.sync_to_context(ctx, m)
        # Should not raise


# ======================================================================
# MissionEventBridge
# ======================================================================


class TestMissionEventBridge:
    async def test_publish_mission_created(self, bus: EventBus, event_bridge: MissionEventBridge) -> None:
        received: list = []
        async def handler(e: object) -> None:
            received.append(e)
        bus.subscribe("mission", handler)
        m = Mission(title="Test")
        await event_bridge.publish_mission_created(m)
        assert len(received) >= 1

    async def test_publish_mission_started(self, event_bridge: MissionEventBridge) -> None:
        m = Mission(title="Test")
        await event_bridge.publish_mission_started(m)

    async def test_publish_mission_completed(self, event_bridge: MissionEventBridge) -> None:
        m = Mission(title="Test")
        await event_bridge.publish_mission_completed(m, duration=10.0)

    async def test_publish_mission_failed(self, event_bridge: MissionEventBridge) -> None:
        m = Mission(title="Test")
        await event_bridge.publish_mission_failed(m, error="Something broke")

    async def test_publish_mission_paused(self, event_bridge: MissionEventBridge) -> None:
        m = Mission(title="Test")
        await event_bridge.publish_mission_paused(m)

    async def test_publish_mission_cancelled(self, event_bridge: MissionEventBridge) -> None:
        m = Mission(title="Test")
        await event_bridge.publish_mission_cancelled(m)

    async def test_publish_step_completed(self, event_bridge: MissionEventBridge) -> None:
        step = MissionStep(title="Step 1", subsystem=Subsystem.KNOWLEDGE)
        await event_bridge.publish_step_completed("m1", step)

    async def test_all_events_published(self, bus: EventBus) -> None:
        bridge = MissionEventBridge(bus)
        received: list = []
        async def handler(e: object) -> None:
            received.append(e)
        bus.subscribe("mission", handler)
        m = Mission(title="Events Test")
        await bridge.publish_mission_created(m)
        await bridge.publish_mission_started(m)
        await bridge.publish_mission_completed(m)
        await bridge.publish_mission_failed(m)
        await bridge.publish_mission_paused(m)
        await bridge.publish_mission_cancelled(m)
        assert len(received) >= 6


# ======================================================================
# MissionControl — IService Lifecycle
# ======================================================================


class TestMissionControlLifecycle:
    def test_name(self, ctrl: MissionControl) -> None:
        assert ctrl.name == "mission_control"

    async def test_initialize(self, ctrl: MissionControl) -> None:
        await ctrl.initialize()
        assert ctrl._running is False

    async def test_start_stop(self, ctrl: MissionControl) -> None:
        await ctrl.start()
        assert ctrl._running is True
        await ctrl.stop()
        assert ctrl._running is False

    async def test_health_check(self, ctrl: MissionControl) -> None:
        await ctrl.start()
        health = await ctrl.health_check()
        assert health.healthy is True
        assert "missions_created" in health.metadata
        assert "template_count" in health.metadata
        await ctrl.stop()

    async def test_set_context(self, ctrl: MissionControl) -> None:
        ctx = AtlasContext()
        ctrl.set_context(ctx)
        assert ctrl._context is ctx


# ======================================================================
# MissionControl — Mission Lifecycle
# ======================================================================


class TestMissionControlMissionLifecycle:
    async def test_create_mission(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Test Mission")
        assert m.title == "Test Mission"
        assert m.status == MissionStatus.CREATED
        assert ctrl.metrics.missions_created == 1

    async def test_get_mission(self, ctrl: MissionControl) -> None:
        created = await ctrl.create_mission(title="Find Me")
        fetched = await ctrl.get_mission(created.mission_id)
        assert fetched is not None
        assert fetched.title == "Find Me"

    async def test_get_missing_mission(self, ctrl: MissionControl) -> None:
        assert await ctrl.get_mission("missing") is None

    async def test_list_missions(self, ctrl: MissionControl) -> None:
        await ctrl.create_mission(title="A")
        await ctrl.create_mission(title="B")
        missions = await ctrl.list_missions()
        assert len(missions) == 2

    async def test_create_mission_with_priority(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="High Priority", priority=10)
        assert m.priority == 10


# ======================================================================
# MissionControl — Planning
# ======================================================================


class TestMissionControlPlanning:
    async def test_plan_mission(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Research AI", tags=["research"])
        plan = await ctrl.plan(m.mission_id)
        assert plan is not None
        assert len(plan.steps) >= 4

    async def test_plan_missing_mission(self, ctrl: MissionControl) -> None:
        assert await ctrl.plan("missing") is None

    async def test_plan_with_template(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Build App", tags=["build"])
        plan = await ctrl.plan(m.mission_id, template="build_project")
        assert plan is not None
        assert len(plan.steps) >= 5

    async def test_plan_with_invalid_template(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Test")
        assert await ctrl.plan(m.mission_id, template="nonexistent") is None

    async def test_get_plan(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Test")
        plan = await ctrl.plan(m.mission_id)
        fetched = await ctrl.get_plan(m.mission_id)
        assert fetched is not None
        assert len(fetched.steps) == len(plan.steps) if plan else 0

    async def test_get_missing_plan(self, ctrl: MissionControl) -> None:
        assert await ctrl.get_plan("missing") is None

    async def test_plan_changes_status(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Test")
        await ctrl.plan(m.mission_id)
        updated = await ctrl.get_mission(m.mission_id)
        assert updated is not None
        assert updated.status == MissionStatus.PLANNING


# ======================================================================
# MissionControl — Execution
# ======================================================================


class TestMissionControlExecution:
    async def test_execute_mission(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Execute Test", tags=["research"])
        await ctrl.plan(m.mission_id)
        result = await ctrl.execute(m.mission_id)
        assert result is not None
        assert result.status in (MissionStatus.COMPLETED, MissionStatus.FAILED)

    async def test_execute_missing_mission(self, ctrl: MissionControl) -> None:
        assert await ctrl.execute("missing") is None

    async def test_execute_no_plan(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="No Plan")
        assert await ctrl.execute(m.mission_id) is None

    async def test_execute_updates_metrics(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Metrics Test", tags=["research"])
        await ctrl.plan(m.mission_id)
        await ctrl.execute(m.mission_id)
        assert ctrl.metrics.steps_executed >= 1


# ======================================================================
# MissionControl — Pause / Resume / Cancel
# ======================================================================


class TestMissionControlPauseResumeCancel:
    async def test_pause_mission(self, ctrl: MissionControl) -> None:
        m = Mission(mission_id="pause-1", title="Pause Test", status=MissionStatus.RUNNING)
        ctrl._missions[m.mission_id] = m
        paused = await ctrl.pause_mission(m.mission_id)
        assert paused is not None
        assert paused.status == MissionStatus.PAUSED

    async def test_pause_missing(self, ctrl: MissionControl) -> None:
        assert await ctrl.pause_mission("missing") is None

    async def test_resume_mission(self, ctrl: MissionControl) -> None:
        m = Mission(mission_id="resume-1", title="Resume Test", status=MissionStatus.PAUSED)
        ctrl._missions[m.mission_id] = m
        resumed = await ctrl.resume_mission(m.mission_id)
        assert resumed is not None
        assert resumed.status == MissionStatus.RUNNING

    async def test_resume_missing(self, ctrl: MissionControl) -> None:
        assert await ctrl.resume_mission("missing") is None

    async def test_cancel_mission(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Cancel Test")
        cancelled = await ctrl.cancel_mission(m.mission_id)
        assert cancelled is not None
        assert cancelled.status == MissionStatus.CANCELLED

    async def test_cancel_missing(self, ctrl: MissionControl) -> None:
        assert await ctrl.cancel_mission("missing") is None

    async def test_cancel_updates_metrics(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Cancel Metrics")
        await ctrl.cancel_mission(m.mission_id)
        assert ctrl.metrics.missions_cancelled == 1


# ======================================================================
# MissionControl — Start mission (enqueue + execute)
# ======================================================================


class TestMissionControlStart:
    async def test_start_mission(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Start Test", tags=["research"])
        await ctrl.plan(m.mission_id)
        result = await ctrl.start_mission(m.mission_id)
        assert result is not None

    async def test_start_missing_mission(self, ctrl: MissionControl) -> None:
        assert await ctrl.start_mission("missing") is None


# ======================================================================
# MissionControl — History
# ======================================================================


class TestMissionControlHistory:
    async def test_history_after_execution(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="History Test", tags=["research"])
        await ctrl.plan(m.mission_id)
        await ctrl.execute(m.mission_id)
        entries = await ctrl.history()
        assert len(entries) >= 1

    async def test_history_with_status_filter(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="History Filter", tags=["research"])
        await ctrl.plan(m.mission_id)
        await ctrl.execute(m.mission_id)
        completed = await ctrl.history(status=MissionStatus.COMPLETED)
        failed = await ctrl.history(status=MissionStatus.FAILED)
        assert len(completed) + len(failed) >= 1

    async def test_history_empty(self, ctrl: MissionControl) -> None:
        entries = await ctrl.history()
        assert entries == []


# ======================================================================
# MissionControl — Templates property
# ======================================================================


class TestMissionControlTemplates:
    async def test_templates_accessible(self, ctrl: MissionControl) -> None:
        assert ctrl.templates.template_count() >= 7

    async def test_planner_accessible(self, ctrl: MissionControl) -> None:
        assert ctrl.planner is not None

    async def test_scheduler_accessible(self, ctrl: MissionControl) -> None:
        assert ctrl.scheduler is not None

    async def test_executor_accessible(self, ctrl: MissionControl) -> None:
        assert ctrl.executor is not None

    async def test_state_machine_accessible(self, ctrl: MissionControl) -> None:
        assert ctrl.state_machine is not None

    async def test_event_bridge_accessible(self, ctrl: MissionControl) -> None:
        assert ctrl.event_bridge is not None

    async def test_context_bridge_accessible(self, ctrl: MissionControl) -> None:
        assert ctrl.context_bridge is not None


# ======================================================================
# MissionControl — Event publishing
# ======================================================================


class TestMissionControlEvents:
    async def test_create_publishes_event(self, bus: EventBus) -> None:
        ctrl = MissionControl(bus)
        received: list = []
        async def handler(e: object) -> None:
            received.append(e)
        bus.subscribe("mission", handler)
        await ctrl.create_mission(title="Event Test")
        assert len(received) >= 1

    async def test_cancel_publishes_event(self, bus: EventBus) -> None:
        ctrl = MissionControl(bus)
        received: list = []
        async def handler(e: object) -> None:
            received.append(e)
        bus.subscribe("mission", handler)
        m = await ctrl.create_mission(title="Cancel")
        await ctrl.cancel_mission(m.mission_id)
        assert len(received) >= 2

    async def test_pause_publishes_event(self, bus: EventBus) -> None:
        ctrl = MissionControl(bus)
        received: list = []
        async def handler(e: object) -> None:
            received.append(e)
        bus.subscribe("mission", handler)
        m = Mission(mission_id="pause-event-1", title="Pause", status=MissionStatus.RUNNING)
        ctrl._missions[m.mission_id] = m
        await ctrl.pause_mission(m.mission_id)
        assert len(received) >= 1


# ======================================================================
# MissionControl — Edge cases
# ======================================================================


class TestMissionControlEdgeCases:
    async def test_illegal_transition_in_execute(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Bad")
        # Manually set to COMPLETED — planning from COMPLETED is illegal
        completed = Mission(
            mission_id=m.mission_id,
            title=m.title,
            status=MissionStatus.COMPLETED,
        )
        ctrl._missions[m.mission_id] = completed
        with pytest.raises(ValueError):
            await ctrl.plan(m.mission_id)

    async def test_create_mission_empty_title(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission()
        assert m.title == ""

    async def test_cancel_already_cancelled(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Cancel Test")
        await ctrl.cancel_mission(m.mission_id)
        # Second cancel is illegal (CANCELLED -> CANCELLED is ok since same status is allowed)
        result = await ctrl.cancel_mission(m.mission_id)
        assert result is not None
        assert result.status == MissionStatus.CANCELLED

    async def test_execute_updates_history(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="History", tags=["research"])
        await ctrl.plan(m.mission_id)
        await ctrl.execute(m.mission_id)
        entries = await ctrl.history()
        assert len(entries) >= 1
        assert entries[0].steps_total >= 1


# ======================================================================
# MissionControl — State machine enforcement
# ======================================================================


class TestMissionControlStateEnforcement:
    async def test_transition_via_plan(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="State Test")
        assert m.status == MissionStatus.CREATED
        await ctrl.plan(m.mission_id)
        updated = await ctrl.get_mission(m.mission_id)
        assert updated is not None
        assert updated.status == MissionStatus.PLANNING

    async def test_transition_via_execute(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Run State", tags=["research"])
        await ctrl.plan(m.mission_id)
        result = await ctrl.execute(m.mission_id)
        assert result is not None
        assert result.status in (MissionStatus.COMPLETED, MissionStatus.FAILED)

    async def test_transition_via_cancel(self, ctrl: MissionControl) -> None:
        m = await ctrl.create_mission(title="Cancel State")
        result = await ctrl.cancel_mission(m.mission_id)
        assert result is not None
        assert result.status == MissionStatus.CANCELLED


# ======================================================================
# Kernel integration
# ======================================================================


class TestKernelIntegration:
    async def test_kernel_creates_mission_control(self) -> None:
        from atlas_core.kernel import AtlasKernel
        kernel = AtlasKernel()
        kernel.initialize()
        kernel.boot()
        mc = kernel.mission_control
        assert mc.name == "mission_control"
        assert mc is kernel._mission_control
