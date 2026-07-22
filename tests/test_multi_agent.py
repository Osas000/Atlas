"""Tests for Multi-Agent Coordination — Milestone 14."""

import asyncio
from datetime import datetime

import pytest

from atlas_core.multi_agent import (
    AgentTeam,
    AgentTeamRegistry,
    CoordinationHistory,
    CoordinationMetrics,
    CoordinationPolicy,
    HistoryEntry,
    MultiAgentRuntime,
    TaskAllocator,
    TeamCoordinator,
    TeamEventBridge,
    TeamMember,
    TeamRole,
    TEAM_STATE_ACTIVE,
    TEAM_STATE_IDLE,
    TEAM_STATE_PAUSED,
    TEAM_STATE_STOPPED,
)
from atlas_core.events import EventBus
from atlas_core.interfaces import ServiceState
from atlas_core.interfaces.events import EventCategory


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def runtime(event_bus):
    return MultiAgentRuntime(event_bus=event_bus)


@pytest.fixture
def sample_members():
    return [
        TeamMember(agent_id="a1", role=TeamRole.LEADER, capabilities=["plan", "decide"]),
        TeamMember(agent_id="a2", role=TeamRole.PLANNER, capabilities=["plan", "research"]),
        TeamMember(agent_id="a3", role=TeamRole.EXECUTOR, capabilities=["execute", "build"]),
        TeamMember(agent_id="a4", role=TeamRole.REVIEWER, capabilities=["review", "analyze"]),
    ]


# ======================================================================
# Component 1 — TeamRole
# ======================================================================


class TestTeamRole:
    def test_has_required_roles(self):
        assert TeamRole.LEADER
        assert TeamRole.PLANNER
        assert TeamRole.RESEARCHER
        assert TeamRole.EXECUTOR
        assert TeamRole.REVIEWER
        assert TeamRole.OBSERVER
        assert TeamRole.SPECIALIST

    def test_all_roles_unique(self):
        values = {r.value for r in TeamRole}
        assert len(values) == len(TeamRole)

    def test_role_enum_order(self):
        assert TeamRole.LEADER.value < TeamRole.PLANNER.value


# ======================================================================
# Component 2 — TeamMember
# ======================================================================


class TestTeamMember:
    def test_create_member(self):
        m = TeamMember(agent_id="a1", role=TeamRole.LEADER)
        assert m.agent_id == "a1"
        assert m.role == TeamRole.LEADER
        assert m.capabilities == []
        assert m.state == "idle"

    def test_member_with_capabilities(self):
        m = TeamMember(agent_id="a1", role=TeamRole.SPECIALIST, capabilities=["python", "docker"])
        assert "python" in m.capabilities
        assert "docker" in m.capabilities

    def test_member_custom_state(self):
        m = TeamMember(agent_id="a1", role=TeamRole.EXECUTOR, state="busy")
        assert m.state == "busy"

    def test_member_is_frozen(self):
        m = TeamMember(agent_id="a1", role=TeamRole.LEADER)
        with pytest.raises(AttributeError):
            m.agent_id = "a2"  # type: ignore

    def test_member_equality(self):
        m1 = TeamMember(agent_id="a1", role=TeamRole.LEADER)
        m2 = TeamMember(agent_id="a1", role=TeamRole.LEADER)
        assert m1 == m2

    def test_member_inequality(self):
        m1 = TeamMember(agent_id="a1", role=TeamRole.LEADER)
        m2 = TeamMember(agent_id="a2", role=TeamRole.LEADER)
        assert m1 != m2


# ======================================================================
# Component 3 — AgentTeam
# ======================================================================


class TestAgentTeam:
    def test_create_team(self, sample_members):
        team = AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members), mission="Test mission")
        assert team.team_id == "t1"
        assert team.name == "Alpha"
        assert team.leader == "a1"
        assert len(team.members) == 4
        assert team.mission == "Test mission"
        assert isinstance(team.created_at, datetime)

    def test_team_no_members(self):
        team = AgentTeam(team_id="t1", name="Solo", leader="a1")
        assert len(team.members) == 0

    def test_team_with_metadata(self):
        team = AgentTeam(team_id="t1", name="Beta", leader="a1", metadata={"priority": "high"})
        assert team.metadata["priority"] == "high"

    def test_team_is_frozen(self):
        team = AgentTeam(team_id="t1", name="Gamma", leader="a1")
        with pytest.raises(AttributeError):
            team.name = "Delta"  # type: ignore

    def test_team_leader_in_members(self, sample_members):
        team = AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members))
        assert any(m.agent_id == team.leader for m in team.members)


# ======================================================================
# Component 4 — AgentTeamRegistry
# ======================================================================


class TestAgentTeamRegistry:
    def test_register(self, sample_members):
        reg = AgentTeamRegistry()
        team = AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members))
        reg.register(team)
        assert reg.count == 1

    def test_register_with_state(self, sample_members):
        reg = AgentTeamRegistry()
        team = AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members))
        reg.register(team, "active")
        assert reg.get_state("t1") == "active"

    def test_unregister(self, sample_members):
        reg = AgentTeamRegistry()
        team = AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members))
        reg.register(team)
        reg.unregister("t1")
        assert reg.count == 0

    def test_get(self, sample_members):
        reg = AgentTeamRegistry()
        team = AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members))
        reg.register(team)
        assert reg.get("t1") is team
        assert reg.get("nonexistent") is None

    def test_get_state(self, sample_members):
        reg = AgentTeamRegistry()
        team = AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members))
        reg.register(team, "active")
        assert reg.get_state("t1") == "active"
        assert reg.get_state("none") is None

    def test_set_state(self, sample_members):
        reg = AgentTeamRegistry()
        team = AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members))
        reg.register(team, "idle")
        reg.set_state("t1", "active")
        assert reg.get_state("t1") == "active"

    def test_list_all(self, sample_members):
        reg = AgentTeamRegistry()
        reg.register(AgentTeam(team_id="t1", name="A", leader="a1", members=tuple(sample_members)))
        reg.register(AgentTeam(team_id="t2", name="B", leader="a2"))
        assert len(reg.list_all()) == 2

    def test_search_by_name(self, sample_members):
        reg = AgentTeamRegistry()
        reg.register(AgentTeam(team_id="t1", name="Alpha Team", leader="a1", members=tuple(sample_members)))
        reg.register(AgentTeam(team_id="t2", name="Beta Squad", leader="a2"))
        assert len(reg.search_by_name("alpha")) == 1
        assert len(reg.search_by_name("team")) == 1
        assert len(reg.search_by_name("squad")) == 1

    def test_search_by_leader(self, sample_members):
        reg = AgentTeamRegistry()
        reg.register(AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members)))
        reg.register(AgentTeam(team_id="t2", name="Beta", leader="a2"))
        assert len(reg.search_by_leader("a1")) == 1
        assert len(reg.search_by_leader("a3")) == 0

    def test_search_by_member(self, sample_members):
        reg = AgentTeamRegistry()
        reg.register(AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members)))
        assert len(reg.search_by_member("a2")) == 1
        assert len(reg.search_by_member("a5")) == 0

    def test_search_by_mission(self, sample_members):
        reg = AgentTeamRegistry()
        reg.register(AgentTeam(team_id="t1", name="Alpha", leader="a1", members=tuple(sample_members), mission="Explore mars"))
        reg.register(AgentTeam(team_id="t2", name="Beta", leader="a2", mission="Build base"))
        assert len(reg.search_by_mission("mars")) == 1
        assert len(reg.search_by_mission("explore")) == 1

    def test_list_by_state(self, sample_members):
        reg = AgentTeamRegistry()
        t1 = AgentTeam(team_id="t1", name="A", leader="a1", members=tuple(sample_members))
        t2 = AgentTeam(team_id="t2", name="B", leader="a2")
        reg.register(t1, "active")
        reg.register(t2, "paused")
        assert len(reg.list_by_state("active")) == 1
        assert len(reg.list_by_state("paused")) == 1
        assert len(reg.list_by_state("idle")) == 0

    def test_state_properties(self, sample_members):
        reg = AgentTeamRegistry()
        t1 = AgentTeam(team_id="t1", name="A", leader="a1", members=tuple(sample_members))
        t2 = AgentTeam(team_id="t2", name="B", leader="a2")
        t3 = AgentTeam(team_id="t3", name="C", leader="a3")
        reg.register(t1, "active")
        reg.register(t2, "paused")
        reg.register(t3, "idle")
        assert len(reg.active) == 1
        assert len(reg.paused) == 1
        assert len(reg.idle) == 1

    def test_clear(self, sample_members):
        reg = AgentTeamRegistry()
        reg.register(AgentTeam(team_id="t1", name="A", leader="a1", members=tuple(sample_members)))
        reg.register(AgentTeam(team_id="t2", name="B", leader="a2"))
        reg.clear()
        assert reg.count == 0

    def test_statistics(self, sample_members):
        reg = AgentTeamRegistry()
        reg.register(AgentTeam(team_id="t1", name="A", leader="a1", members=tuple(sample_members)), "active")
        reg.register(AgentTeam(team_id="t2", name="B", leader="a2"), "paused")
        stats = reg.statistics()
        assert stats["total"] == 2
        assert stats["active"] == 1
        assert stats["paused"] == 1


# ======================================================================
# Component 5 — CoordinationPolicy
# ======================================================================


class TestCoordinationPolicy:
    def test_has_required_policies(self):
        assert CoordinationPolicy.SEQUENTIAL
        assert CoordinationPolicy.PARALLEL
        assert CoordinationPolicy.CONSENSUS
        assert CoordinationPolicy.LEADER_APPROVAL
        assert CoordinationPolicy.ROUND_ROBIN
        assert CoordinationPolicy.BROADCAST

    def test_all_policies_unique(self):
        values = {p.value for p in CoordinationPolicy}
        assert len(values) == len(CoordinationPolicy)


# ======================================================================
# Component 6 — TaskAllocator
# ======================================================================


class TestTaskAllocator:
    def test_round_robin(self, sample_members):
        alloc = TaskAllocator()
        a1 = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "task1")
        a2 = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "task1")
        a3 = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "task1")
        a4 = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "task1")
        a5 = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "task1")
        assert a1 != a2 or len(sample_members) == 1
        assert a5 == a1  # wraps around

    def test_least_busy(self, sample_members):
        alloc = TaskAllocator()
        alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "t1")
        alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "t1")
        alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "t1")
        # a4 should be least busy now
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.LEAST_BUSY)
        assert chosen == "a4"

    def test_role_match_plan(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROLE_MATCH, "create plan")
        assert chosen == "a2"  # PLANNER

    def test_role_match_execute(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROLE_MATCH, "execute build")
        assert chosen == "a3"  # EXECUTOR

    def test_role_match_review(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROLE_MATCH, "review code")
        assert chosen == "a4"  # REVIEWER

    def test_role_match_fallback(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROLE_MATCH, "unknown task")
        assert chosen in [m.agent_id for m in sample_members]

    def test_capability_match(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.CAPABILITY_MATCH, task_capability="build")
        assert chosen == "a3"  # has "build" capability

    def test_capability_match_fallback(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.CAPABILITY_MATCH, task_capability="unknown")
        assert chosen in [m.agent_id for m in sample_members]

    def test_priority(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.PRIORITY)
        assert chosen == "a1"  # LEADER

    def test_sequential(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.SEQUENTIAL)
        assert chosen in [m.agent_id for m in sample_members]

    def test_leader_approval(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.LEADER_APPROVAL, leader_id="a1")
        assert chosen == "a1"

    def test_leader_approval_not_member(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.LEADER_APPROVAL, leader_id="a99")
        assert chosen in [m.agent_id for m in sample_members]

    def test_broadcast(self, sample_members):
        alloc = TaskAllocator()
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.BROADCAST)
        assert chosen == "a1"

    def test_consensus(self):
        members = (
            TeamMember(agent_id="a1", role=TeamRole.LEADER),
            TeamMember(agent_id="a2", role=TeamRole.PLANNER),
            TeamMember(agent_id="a3", role=TeamRole.EXECUTOR),
        )
        alloc = TaskAllocator()
        chosen = alloc.allocate(members, CoordinationPolicy.CONSENSUS)
        assert chosen == "a1"

    def test_consensus_too_few(self):
        members = (
            TeamMember(agent_id="a1", role=TeamRole.LEADER),
            TeamMember(agent_id="a2", role=TeamRole.PLANNER),
        )
        alloc = TaskAllocator()
        chosen = alloc.allocate(members, CoordinationPolicy.CONSENSUS)
        assert chosen is None

    def test_empty_members(self):
        alloc = TaskAllocator()
        chosen = alloc.allocate((), CoordinationPolicy.ROUND_ROBIN)
        assert chosen is None

    def test_get_task_count(self, sample_members):
        alloc = TaskAllocator()
        alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "t1")
        assert alloc.get_task_count("a1") >= 1

    def test_reset_counts(self, sample_members):
        alloc = TaskAllocator()
        alloc.allocate(tuple(sample_members), CoordinationPolicy.ROUND_ROBIN, "t1")
        alloc.reset_counts()
        assert alloc.get_task_count("a1") == 0

    def test_role_match_research(self, sample_members):
        alloc = TaskAllocator()
        # No RESEARCHER in sample_members, falls back to round robin
        chosen = alloc.allocate(tuple(sample_members), CoordinationPolicy.ROLE_MATCH, "research topic")
        assert chosen in [m.agent_id for m in sample_members]


# ======================================================================
# Component 7 — TeamEventBridge
# ======================================================================


class TestTeamEventBridge:
    @pytest.mark.asyncio
    async def test_publish(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.publish("test", "team-1", {"data": "value"})
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_team_created(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.team_created("t1", "Alpha")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert len(ma_events) >= 1
        assert ma_events[0].payload.get("action") == "team_created"

    @pytest.mark.asyncio
    async def test_team_disbanded(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.team_disbanded("t1")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert ma_events[0].payload.get("action") == "team_disbanded"

    @pytest.mark.asyncio
    async def test_team_started(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.team_started("t1")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert ma_events[0].payload.get("action") == "team_started"

    @pytest.mark.asyncio
    async def test_team_stopped(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.team_stopped("t1")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert ma_events[0].payload.get("action") == "team_stopped"

    @pytest.mark.asyncio
    async def test_team_paused(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.team_paused("t1")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert ma_events[0].payload.get("action") == "team_paused"

    @pytest.mark.asyncio
    async def test_team_resumed(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.team_resumed("t1")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert ma_events[0].payload.get("action") == "team_resumed"

    @pytest.mark.asyncio
    async def test_task_assigned(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.task_assigned("t1", "a1", "build")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert ma_events[0].payload.get("action") == "task_assigned"
        assert ma_events[0].payload.get("agent_id") == "a1"

    @pytest.mark.asyncio
    async def test_task_completed(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.task_completed("t1", "a1", "build")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert ma_events[0].payload.get("action") == "task_completed"

    @pytest.mark.asyncio
    async def test_leader_changed(self, event_bus):
        bridge = TeamEventBridge(event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await bridge.leader_changed("t1", "a1", "a2")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert ma_events[0].payload.get("action") == "leader_changed"
        assert ma_events[0].payload.get("old_leader") == "a1"
        assert ma_events[0].payload.get("new_leader") == "a2"


# ======================================================================
# Component 8 — CoordinationHistory
# ======================================================================


class TestCoordinationHistory:
    def test_record_entry(self):
        h = CoordinationHistory()
        assert h.size == 0
        h.record(HistoryEntry(event_type="test", team_id="t1"))
        assert h.size == 1

    def test_record_event(self):
        h = CoordinationHistory()
        h.record_event("team_created", team_id="t1")
        assert h.size == 1
        assert h.last.event_type == "team_created"

    def test_query_by_type(self):
        h = CoordinationHistory()
        h.record_event("team_created", team_id="t1")
        h.record_event("team_disbanded", team_id="t2")
        h.record_event("team_created", team_id="t3")
        results = h.query(event_type="team_created")
        assert len(results) == 2

    def test_query_by_team(self):
        h = CoordinationHistory()
        h.record_event("team_created", team_id="t1")
        h.record_event("task_assigned", team_id="t1")
        h.record_event("task_assigned", team_id="t2")
        results = h.query(team_id="t1")
        assert len(results) == 2

    def test_query_by_agent(self):
        h = CoordinationHistory()
        h.record_event("task_assigned", team_id="t1", agent_id="a1")
        h.record_event("task_assigned", team_id="t2", agent_id="a2")
        results = h.query(agent_id="a1")
        assert len(results) == 1

    def test_query_combined(self):
        h = CoordinationHistory()
        h.record_event("task_assigned", team_id="t1", agent_id="a1")
        h.record_event("task_assigned", team_id="t1", agent_id="a2")
        h.record_event("task_assigned", team_id="t2", agent_id="a1")
        results = h.query(event_type="task_assigned", team_id="t1")
        assert len(results) == 2

    def test_clear(self):
        h = CoordinationHistory()
        h.record_event("test", team_id="t1")
        h.clear()
        assert h.size == 0

    def test_last_property(self):
        h = CoordinationHistory()
        assert h.last is None
        h.record_event("first", team_id="t1")
        h.record_event("last", team_id="t1")
        assert h.last.event_type == "last"

    def test_max_size(self):
        h = CoordinationHistory(max_size=3)
        for i in range(10):
            h.record_event(f"e{i}", team_id=f"t{i}")
        assert h.size <= 3
        assert h.last.event_type == "e9"

    def test_query_limit(self):
        h = CoordinationHistory()
        for i in range(10):
            h.record_event("test", team_id=f"t{i}")
        results = h.query(limit=3)
        assert len(results) == 3

    def test_query_no_match(self):
        h = CoordinationHistory()
        h.record_event("team_created", team_id="t1")
        results = h.query(event_type="nonexistent")
        assert len(results) == 0


# ======================================================================
# Component 9 — CoordinationMetrics
# ======================================================================


class TestCoordinationMetrics:
    def test_initial_values(self):
        m = CoordinationMetrics()
        assert m.teams_created == 0
        assert m.teams_active == 0
        assert m.missions_completed == 0
        assert m.assignments == 0
        assert m.reassignments == 0
        assert m.errors == 0
        assert m.utilization == 0.0

    def test_record_team_created(self):
        m = CoordinationMetrics()
        m.record_team_created()
        assert m.teams_created == 1
        assert m.teams_active == 1

    def test_record_team_disbanded(self):
        m = CoordinationMetrics()
        m.record_team_created()
        m.record_team_disbanded()
        assert m.teams_active == 0

    def test_mission_completed(self):
        m = CoordinationMetrics()
        m.record_mission_completed()
        assert m.missions_completed == 1

    def test_assignment(self):
        m = CoordinationMetrics()
        m.record_assignment()
        assert m.assignments == 1

    def test_reassignment(self):
        m = CoordinationMetrics()
        m.record_reassignment()
        assert m.reassignments == 1

    def test_error(self):
        m = CoordinationMetrics()
        m.record_error()
        assert m.errors == 1

    def test_utilization(self):
        m = CoordinationMetrics()
        m.update_utilization(0.75)
        assert m.utilization == 0.75

    def test_snapshot(self):
        m = CoordinationMetrics()
        m.record_team_created()
        m.record_assignment()
        s = m.snapshot()
        assert s["teams_created"] == 1
        assert s["assignments"] == 1
        assert "teams_active" in s
        assert "utilization" in s

    def test_reset(self):
        m = CoordinationMetrics()
        m.record_team_created()
        m.record_error()
        m.reset()
        assert m.teams_created == 0
        assert m.errors == 0
        assert m.assignments == 0

    def test_teams_active_never_negative(self):
        m = CoordinationMetrics()
        m.record_team_disbanded()  # should not go below 0
        assert m.teams_active == 0


# ======================================================================
# Component 10 — TeamCoordinator
# ======================================================================


class TestTeamCoordinator:
    @pytest.mark.asyncio
    async def test_create_team(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        team = await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members, "Mission")
        assert team.team_id == "t1"
        assert team.name == "Alpha"
        assert rt.registry.count == 1

    @pytest.mark.asyncio
    async def test_create_team_adds_leader(self, event_bus):
        rt = MultiAgentRuntime(event_bus=event_bus)
        team = await rt.coordinator.create_team("t1", "Alpha", "a1", [], "Mission")
        assert any(m.agent_id == "a1" for m in team.members)

    @pytest.mark.asyncio
    async def test_create_team_duplicate(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members)
        with pytest.raises(ValueError, match="already exists"):
            await rt.coordinator.create_team("t1", "Beta", "a2", sample_members)

    @pytest.mark.asyncio
    async def test_disband_team(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members)
        await rt.coordinator.disband_team("t1")
        assert rt.registry.count == 0

    @pytest.mark.asyncio
    async def test_disband_nonexistent(self, event_bus):
        rt = MultiAgentRuntime(event_bus=event_bus)
        with pytest.raises(ValueError, match="not found"):
            await rt.coordinator.disband_team("nonexistent")

    @pytest.mark.asyncio
    async def test_assign_agent(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members[:1])
        team = await rt.coordinator.assign_agent("t1", "a5", TeamRole.RESEARCHER, ["research"])
        assert any(m.agent_id == "a5" for m in team.members)
        assert rt.metrics.assignments == 0  # assign_agent is not task assignment

    @pytest.mark.asyncio
    async def test_assign_agent_duplicate(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members[:1])
        with pytest.raises(ValueError, match="already in team"):
            await rt.coordinator.assign_agent("t1", "a1", TeamRole.EXECUTOR)

    @pytest.mark.asyncio
    async def test_remove_agent(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members[:2])
        team = await rt.coordinator.remove_agent("t1", "a2")
        assert not any(m.agent_id == "a2" for m in team.members)

    @pytest.mark.asyncio
    async def test_remove_leader_forbidden(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members[:1])
        with pytest.raises(ValueError, match="Cannot remove leader"):
            await rt.coordinator.remove_agent("t1", "a1")

    @pytest.mark.asyncio
    async def test_remove_nonexistent_agent(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members[:1])
        with pytest.raises(ValueError, match="not found"):
            await rt.coordinator.remove_agent("t1", "a99")

    @pytest.mark.asyncio
    async def test_change_leader(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members[:2])
        team = await rt.coordinator.change_leader("t1", "a2")
        assert team.leader == "a2"

    @pytest.mark.asyncio
    async def test_change_leader_not_member(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members[:1])
        with pytest.raises(ValueError, match="not a member"):
            await rt.coordinator.change_leader("t1", "a99")

    @pytest.mark.asyncio
    async def test_team_lifecycle(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members)
        assert rt.registry.get_state("t1") == TEAM_STATE_IDLE
        await rt.coordinator.start_team("t1")
        assert rt.registry.get_state("t1") == TEAM_STATE_ACTIVE
        await rt.coordinator.pause_team("t1")
        assert rt.registry.get_state("t1") == TEAM_STATE_PAUSED
        await rt.coordinator.resume_team("t1")
        assert rt.registry.get_state("t1") == TEAM_STATE_ACTIVE
        await rt.coordinator.stop_team("t1")
        assert rt.registry.get_state("t1") == TEAM_STATE_STOPPED

    @pytest.mark.asyncio
    async def test_start_nonexistent(self, event_bus):
        rt = MultiAgentRuntime(event_bus=event_bus)
        with pytest.raises(ValueError, match="not found"):
            await rt.coordinator.start_team("nonexistent")

    @pytest.mark.asyncio
    async def test_status(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members)
        status = rt.coordinator.status("t1")
        assert status["team_id"] == "t1"
        assert status["name"] == "Alpha"
        assert status["leader"] == "a1"
        assert status["member_count"] == 4

    @pytest.mark.asyncio
    async def test_status_nonexistent(self, event_bus):
        rt = MultiAgentRuntime(event_bus=event_bus)
        with pytest.raises(ValueError, match="not found"):
            rt.coordinator.status("nonexistent")

    @pytest.mark.asyncio
    async def test_allocate_task(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members)
        agent_id = await rt.coordinator.allocate_task("t1", CoordinationPolicy.ROUND_ROBIN, "build")
        assert agent_id in [m.agent_id for m in sample_members]

    @pytest.mark.asyncio
    async def test_allocate_task_tracks_metrics(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members)
        await rt.coordinator.allocate_task("t1", CoordinationPolicy.ROUND_ROBIN, "build")
        assert rt.metrics.assignments == 1

    @pytest.mark.asyncio
    async def test_allocate_task_tracks_history(self, event_bus, sample_members):
        rt = MultiAgentRuntime(event_bus=event_bus)
        await rt.coordinator.create_team("t1", "Alpha", "a1", sample_members)
        await rt.coordinator.allocate_task("t1", CoordinationPolicy.ROUND_ROBIN, "build")
        entries = rt.history.query(event_type="task_assigned")
        assert len(entries) >= 1

    @pytest.mark.asyncio
    async def test_allocate_task_nonexistent_team(self, event_bus):
        rt = MultiAgentRuntime(event_bus=event_bus)
        with pytest.raises(ValueError, match="not found"):
            await rt.coordinator.allocate_task("nonexistent", CoordinationPolicy.ROUND_ROBIN)


# ======================================================================
# Component 11 — MultiAgentRuntime (IService)
# ======================================================================


class TestMultiAgentRuntime:
    @pytest.mark.asyncio
    async def test_create(self, event_bus):
        rt = MultiAgentRuntime(event_bus=event_bus)
        assert rt.name == "multi_agent_runtime"
        assert rt.registry.count == 0

    @pytest.mark.asyncio
    async def test_initialize(self, runtime):
        await runtime.initialize()
        assert runtime._state == ServiceState.INITIALIZED

    @pytest.mark.asyncio
    async def test_start(self, runtime):
        await runtime.initialize()
        await runtime.start()
        assert runtime._state == ServiceState.RUNNING

    @pytest.mark.asyncio
    async def test_stop(self, runtime):
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()
        assert runtime._state == ServiceState.STOPPED

    @pytest.mark.asyncio
    async def test_health_check_not_running(self, runtime):
        health = await runtime.health_check()
        assert not health.healthy

    @pytest.mark.asyncio
    async def test_health_check_running(self, runtime):
        await runtime.initialize()
        await runtime.start()
        health = await runtime.health_check()
        assert health.healthy

    @pytest.mark.asyncio
    async def test_create_team(self, runtime, sample_members):
        team = await runtime.create_team("t1", "Alpha", "a1", sample_members, "Mission")
        assert team.team_id == "t1"
        assert runtime.registry.count == 1

    @pytest.mark.asyncio
    async def test_create_team_no_members(self, runtime):
        team = await runtime.create_team("t1", "Alpha", "a1")
        assert team.team_id == "t1"
        assert len(team.members) >= 1  # leader auto-added

    @pytest.mark.asyncio
    async def test_disband_team(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.disband_team("t1")
        assert runtime.registry.count == 0

    @pytest.mark.asyncio
    async def test_assign_agent(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members[:1])
        team = await runtime.assign_agent("t1", "a9", TeamRole.OBSERVER)
        assert any(m.agent_id == "a9" for m in team.members)

    @pytest.mark.asyncio
    async def test_remove_agent(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members[:2])
        team = await runtime.remove_agent("t1", "a2")
        assert not any(m.agent_id == "a2" for m in team.members)

    @pytest.mark.asyncio
    async def test_change_leader(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members[:2])
        team = await runtime.change_leader("t1", "a2")
        assert team.leader == "a2"

    @pytest.mark.asyncio
    async def test_start_team(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.start_team("t1")
        assert runtime.registry.get_state("t1") == TEAM_STATE_ACTIVE

    @pytest.mark.asyncio
    async def test_pause_team(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.start_team("t1")
        await runtime.pause_team("t1")
        assert runtime.registry.get_state("t1") == TEAM_STATE_PAUSED

    @pytest.mark.asyncio
    async def test_resume_team(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.start_team("t1")
        await runtime.pause_team("t1")
        await runtime.resume_team("t1")
        assert runtime.registry.get_state("t1") == TEAM_STATE_ACTIVE

    @pytest.mark.asyncio
    async def test_stop_team(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.start_team("t1")
        await runtime.stop_team("t1")
        assert runtime.registry.get_state("t1") == TEAM_STATE_STOPPED

    @pytest.mark.asyncio
    async def test_team_status(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        status = runtime.team_status("t1")
        assert status["team_id"] == "t1"

    @pytest.mark.asyncio
    async def test_allocate_task(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        agent_id = await runtime.allocate_task("t1", CoordinationPolicy.ROUND_ROBIN, "build")
        assert agent_id is not None

    @pytest.mark.asyncio
    async def test_get_team(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        team = runtime.get_team("t1")
        assert team is not None
        assert team.name == "Alpha"

    @pytest.mark.asyncio
    async def test_get_team_not_found(self, runtime):
        assert runtime.get_team("none") is None

    @pytest.mark.asyncio
    async def test_list_teams(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.create_team("t2", "Beta", "a2")
        assert len(runtime.list_teams()) == 2

    @pytest.mark.asyncio
    async def test_search_teams_by_name(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha Team", "a1", sample_members)
        await runtime.create_team("t2", "Beta Squad", "a2")
        results = runtime.search_teams(name="alpha")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_teams_by_leader(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.create_team("t2", "Beta", "a2")
        results = runtime.search_teams(leader="a1")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_teams_by_member(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        results = runtime.search_teams(member="a2")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_teams_by_mission(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members, mission="Explore mars")
        results = runtime.search_teams(mission="mars")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_teams_no_filters(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.create_team("t2", "Beta", "a2")
        results = runtime.search_teams()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_iservice_lifecycle(self, runtime):
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()

    @pytest.mark.asyncio
    async def test_super_called_in_lifecycle(self, event_bus):
        calls = []

        class TrackingRuntime(MultiAgentRuntime):
            async def initialize(self):
                await super().initialize()
                calls.append("initialize")
            async def start(self):
                await super().start()
                calls.append("start")
            async def stop(self):
                await super().stop()
                calls.append("stop")

        rt = TrackingRuntime(event_bus=event_bus)
        await rt.initialize()
        await rt.start()
        await rt.stop()
        assert calls == ["initialize", "start", "stop"]

    @pytest.mark.asyncio
    async def test_properties(self, runtime):
        assert runtime.registry is not None
        assert runtime.metrics is not None
        assert runtime.history is not None
        assert runtime.coordinator is not None
        assert runtime.event_bridge is not None

    @pytest.mark.asyncio
    async def test_metrics_tracked(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        assert runtime.metrics.teams_created == 1
        assert runtime.metrics.teams_active == 1
        await runtime.disband_team("t1")
        assert runtime.metrics.teams_active == 0


# ======================================================================
# Kernel Integration
# ======================================================================


class TestKernelIntegration:
    @pytest.mark.asyncio
    async def test_kernel_registers_multi_agent_runtime(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        assert kernel.multi_agent_runtime is not None
        assert kernel.multi_agent_runtime.name == "multi_agent_runtime"

    @pytest.mark.asyncio
    async def test_kernel_multi_agent_runtime_health(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        await kernel.start()
        health = await kernel.multi_agent_runtime.health_check()
        assert health.healthy
        await kernel.stop()

    @pytest.mark.asyncio
    async def test_kernel_multi_agent_runtime_property_guard(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        with pytest.raises(RuntimeError):
            _ = kernel.multi_agent_runtime

    @pytest.mark.asyncio
    async def test_kernel_multi_agent_runtime_is_service(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        svc = kernel.registry.resolve("multi_agent_runtime")
        assert svc is not None
        assert svc.name == "multi_agent_runtime"

    @pytest.mark.asyncio
    async def test_kernel_lifecycle_with_team(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        await kernel.start()
        team = await kernel.multi_agent_runtime.create_team("t1", "Kernel Team", "a1")
        assert team.team_id == "t1"
        await kernel.stop()
        assert kernel.state.name == "STOPPED"


# ======================================================================
# EventCategory.MULTI_AGENT
# ======================================================================


class TestMultiAgentEventCategory:
    def test_multi_agent_category_exists(self):
        assert hasattr(EventCategory, "MULTI_AGENT")
        assert EventCategory.MULTI_AGENT.value == "multi_agent"

    def test_category_is_unique(self):
        values = {c.value for c in EventCategory}
        assert "multi_agent" in values


# ======================================================================
# Edge Cases & Error Handling
# ======================================================================


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_team_name(self, runtime):
        team = await runtime.create_team("t1", "", "a1")
        assert team.name == ""

    @pytest.mark.asyncio
    async def test_team_with_special_chars(self, runtime):
        team = await runtime.create_team("t.1-2_3", "Special Team", "a1")
        assert team.team_id == "t.1-2_3"

    @pytest.mark.asyncio
    async def test_no_duplicate_team_ids(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        with pytest.raises(ValueError):
            await runtime.create_team("t1", "Beta", "a2")

    @pytest.mark.asyncio
    async def test_coordinator_not_found_errors(self, runtime):
        with pytest.raises(ValueError, match="not found"):
            await runtime.start_team("none")
        with pytest.raises(ValueError, match="not found"):
            await runtime.pause_team("none")
        with pytest.raises(ValueError, match="not found"):
            await runtime.resume_team("none")
        with pytest.raises(ValueError, match="not found"):
            await runtime.stop_team("none")
        with pytest.raises(ValueError, match="not found"):
            runtime.team_status("none")

    @pytest.mark.asyncio
    async def test_history_recorded_for_events(self, runtime, sample_members):
        await runtime.create_team("t1", "Alpha", "a1", sample_members)
        await runtime.start_team("t1")
        await runtime.pause_team("t1")
        await runtime.resume_team("t1")
        await runtime.stop_team("t1")
        await runtime.disband_team("t1")
        assert runtime.history.size >= 5

    @pytest.mark.asyncio
    async def test_metrics_after_multiple_teams(self, runtime, sample_members):
        for i in range(3):
            await runtime.create_team(f"t{i}", f"Team {i}", f"a{i}", sample_members)
        assert runtime.metrics.teams_created == 3
        assert runtime.metrics.teams_active == 3

    @pytest.mark.asyncio
    async def test_event_published_on_create(self, event_bus):
        rt = MultiAgentRuntime(event_bus=event_bus)
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("multi_agent", capture)
        await rt.create_team("t1", "Alpha", "a1")
        ma_events = [e for e in events if e.category == EventCategory.MULTI_AGENT]
        assert len(ma_events) >= 1

    @pytest.mark.asyncio
    async def test_stale_team_operations(self, runtime):
        with pytest.raises(ValueError):
            await runtime.start_team("ghost")

    @pytest.mark.asyncio
    async def test_implements_iservice(self, runtime):
        from atlas_core.interfaces import IService

        assert isinstance(runtime, IService)
