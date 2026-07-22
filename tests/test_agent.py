"""Tests for Agent Runtime — Milestone 13."""

import asyncio
from datetime import datetime

import pytest

from atlas_core.agent import (
    AgentContextBridge,
    AgentEventBridge,
    AgentLoop,
    AgentMemoryBridge,
    AgentMetrics,
    AgentRegistry,
    AgentRuntime,
    AgentState,
    AtlasAgent,
    IAgent,
    WorkingMemory,
)
from atlas_core.events import EventBus
from atlas_core.interfaces import ServiceState
from atlas_core.interfaces.events import Event, EventCategory


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def runtime(event_bus):
    return AgentRuntime(event_bus=event_bus)


@pytest.fixture
def agent(event_bus):
    a = AtlasAgent(agent_id="test-1", name="Test Agent", event_bus=event_bus)
    return a


@pytest.fixture
def initialized_agent(agent):
    async def _init():
        await agent.initialize()
        return agent
    return _init


# ======================================================================
# Component 1 — AgentState
# ======================================================================


class TestAgentState:
    def test_has_required_states(self):
        assert AgentState.INITIALIZING
        assert AgentState.IDLE
        assert AgentState.OBSERVING
        assert AgentState.THINKING
        assert AgentState.PLANNING
        assert AgentState.EXECUTING
        assert AgentState.WAITING
        assert AgentState.PAUSED
        assert AgentState.STOPPING
        assert AgentState.STOPPED
        assert AgentState.FAILED

    def test_all_states_unique(self):
        values = {s.value for s in AgentState}
        assert len(values) == len(AgentState)

    def test_state_enum_values(self):
        assert AgentState.IDLE.value > AgentState.INITIALIZING.value


# ======================================================================
# Component 2 — IAgent
# ======================================================================


class TestIAgent:
    def test_iaagent_is_abstract(self):
        with pytest.raises(TypeError):
            IAgent()

    def test_iaagent_has_abstract_properties(self):
        methods = [
            "agent_id",
            "name",
            "state",
            "current_mission",
            "created_at",
            "last_heartbeat",
        ]
        for m in methods:
            assert hasattr(IAgent, m)

    def test_iaagent_has_async_methods(self):
        methods = [
            "initialize",
            "start",
            "stop",
            "pause",
            "resume",
            "heartbeat",
            "assign_mission",
            "current_mission_state",
        ]
        for m in methods:
            assert hasattr(IAgent, m)


# ======================================================================
# Component 3 — AtlasAgent
# ======================================================================


class TestAtlasAgent:
    def test_create_agent(self, event_bus):
        a = AtlasAgent(agent_id="test-id", name="Test", event_bus=event_bus)
        assert a.agent_id == "test-id"
        assert a.name == "Test"
        assert a.state == AgentState.INITIALIZING
        assert a.current_mission is None
        assert a.created_at is not None
        assert a.last_heartbeat is None

    def test_agent_properties(self, agent, event_bus):
        assert agent.agent_id == "test-1"
        assert agent.name == "Test Agent"
        assert isinstance(agent.metrics, AgentMetrics)
        assert isinstance(agent.event_bridge, AgentEventBridge)
        assert isinstance(agent.context_bridge, AgentContextBridge)
        assert isinstance(agent.memory_bridge, AgentMemoryBridge)

    @pytest.mark.asyncio
    async def test_initialize(self, agent):
        await agent.initialize()
        assert agent.state == AgentState.INITIALIZING

    @pytest.mark.asyncio
    async def test_start(self, agent):
        await agent.initialize()
        await agent.start()
        assert agent.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_start_publishes_event(self, agent, event_bus):
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await agent.initialize()
        await agent.start()
        assert len(events) >= 1
        assert events[0].category == EventCategory.AGENT

    @pytest.mark.asyncio
    async def test_stop(self, agent):
        await agent.initialize()
        await agent.start()
        await agent.stop()
        assert agent.state == AgentState.STOPPED

    @pytest.mark.asyncio
    async def test_pause(self, agent):
        await agent.initialize()
        await agent.start()
        await agent.pause()
        assert agent.state == AgentState.PAUSED

    @pytest.mark.asyncio
    async def test_resume(self, agent):
        await agent.initialize()
        await agent.start()
        await agent.pause()
        await agent.resume()
        assert agent.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_heartbeat(self, agent):
        await agent.initialize()
        assert agent.last_heartbeat is None
        await agent.heartbeat()
        assert agent.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_heartbeat_increments_count(self, agent):
        await agent.initialize()
        c0 = agent.metrics.heartbeat_count
        await agent.heartbeat()
        assert agent.metrics.heartbeat_count == c0 + 1

    @pytest.mark.asyncio
    async def test_assign_mission(self, agent):
        await agent.initialize()
        await agent.assign_mission("mission-1")
        assert agent.current_mission == "mission-1"

    @pytest.mark.asyncio
    async def test_assign_mission_publishes_event(self, agent, event_bus):
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await agent.initialize()
        await agent.assign_mission("mission-1")
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert len(agent_events) >= 1
        assert agent_events[0].payload.get("action") == "mission_assigned"
        assert agent_events[0].payload.get("mission_id") == "mission-1"

    @pytest.mark.asyncio
    async def test_observe(self, agent):
        await agent.initialize()
        result = await agent.observe()
        assert result["agent_id"] == "test-1"
        assert result["state"] == "OBSERVING"
        assert agent.state == AgentState.OBSERVING

    @pytest.mark.asyncio
    async def test_think(self, agent):
        await agent.initialize()
        result = await agent.think()
        assert result["agent_id"] == "test-1"
        assert result["state"] == "THINKING"
        assert agent.state == AgentState.THINKING

    @pytest.mark.asyncio
    async def test_plan(self, agent):
        await agent.initialize()
        result = await agent.plan()
        assert result["agent_id"] == "test-1"
        assert result["state"] == "PLANNING"
        assert agent.state == AgentState.PLANNING

    @pytest.mark.asyncio
    async def test_execute(self, agent):
        await agent.initialize()
        result = await agent.execute()
        assert result["agent_id"] == "test-1"
        assert result["state"] == "EXECUTING"
        assert agent.state == AgentState.EXECUTING

    @pytest.mark.asyncio
    async def test_learn(self, agent):
        await agent.initialize()
        result = await agent.learn()
        assert "agent_id" in result
        assert "metrics" in result

    @pytest.mark.asyncio
    async def test_metrics_tracked_during_execute(self, agent):
        await agent.initialize()
        c0 = agent.metrics.steps_completed
        await agent.execute()
        assert agent.metrics.steps_completed == c0

    @pytest.mark.asyncio
    async def test_reasoning_time_tracked(self, agent):
        await agent.initialize()
        r0 = agent.metrics.reasoning_time
        await agent.think()
        assert agent.metrics.reasoning_time >= r0

    @pytest.mark.asyncio
    async def test_execution_time_tracked(self, agent):
        await agent.initialize()
        e0 = agent.metrics.execution_time
        await agent.execute()
        assert agent.metrics.execution_time >= e0

    @pytest.mark.asyncio
    async def test_observe_stores_memory(self, agent):
        await agent.initialize()
        assert len(agent.memory_bridge.working.observations) == 0
        await agent.observe()
        assert len(agent.memory_bridge.working.observations) == 1

    @pytest.mark.asyncio
    async def test_think_stores_memory(self, agent):
        await agent.initialize()
        assert len(agent.memory_bridge.working.thoughts) == 0
        await agent.think()
        assert len(agent.memory_bridge.working.thoughts) == 1

    @pytest.mark.asyncio
    async def test_plan_stores_memory(self, agent):
        await agent.initialize()
        assert len(agent.memory_bridge.working.plans) == 0
        await agent.plan()
        assert len(agent.memory_bridge.working.plans) == 1

    @pytest.mark.asyncio
    async def test_execute_stores_memory(self, agent):
        await agent.initialize()
        assert len(agent.memory_bridge.working.results) == 0
        await agent.execute()
        assert len(agent.memory_bridge.working.results) == 1

    @pytest.mark.asyncio
    async def test_context_synced_during_observe(self, agent, event_bus):
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("context", capture)
        await agent.initialize()
        await agent.observe()
        ctx_events = [e for e in events if e.category == EventCategory.CONTEXT]
        assert len(ctx_events) >= 1
        assert ctx_events[0].payload.get("state") == "OBSERVING"

    @pytest.mark.asyncio
    async def test_agent_id_unique(self, event_bus):
        a1 = AtlasAgent(agent_id="a1", name="A1", event_bus=event_bus)
        a2 = AtlasAgent(agent_id="a2", name="A2", event_bus=event_bus)
        assert a1.agent_id != a2.agent_id

    @pytest.mark.asyncio
    async def test_created_at_on_creation(self, event_bus):
        a = AtlasAgent(agent_id="ts", name="TS", event_bus=event_bus)
        assert isinstance(a.created_at, datetime)

    @pytest.mark.asyncio
    async def test_run_once(self, agent):
        await agent.initialize()
        await agent.start()
        await agent.run_once()
        assert agent.state in (AgentState.IDLE, AgentState.EXECUTING)

    @pytest.mark.asyncio
    async def test_run_forever_stops(self, agent):
        await agent.initialize()
        await agent.start()
        task = asyncio.create_task(agent.run_forever(interval=0.01))
        await asyncio.sleep(0.05)
        agent._loop.stop()
        await task

    @pytest.mark.asyncio
    async def test_observe_with_mission(self, agent):
        await agent.initialize()
        await agent.assign_mission("m-1")
        result = await agent.observe()
        assert result["current_mission"] == "m-1"

    @pytest.mark.asyncio
    async def test_learn_returns_metrics(self, agent):
        await agent.initialize()
        await agent.heartbeat()
        result = await agent.learn()
        assert result["metrics"]["heartbeat_count"] >= 1


# ======================================================================
# Component 4 — AgentLoop
# ======================================================================


class TestAgentLoop:
    @pytest.mark.asyncio
    async def test_run_once_calls_all_phases(self, agent):
        await agent.initialize()
        loop = AgentLoop(agent)
        await loop.run_once()

    @pytest.mark.asyncio
    async def test_is_running_false_initially(self, agent):
        loop = AgentLoop(agent)
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_run_forever_sets_running(self, agent):
        await agent.initialize()
        await agent.start()
        loop = AgentLoop(agent)
        task = asyncio.create_task(loop.run_forever(interval=0.01))
        await asyncio.sleep(0.03)
        assert loop.is_running
        loop.stop()
        await task

    @pytest.mark.asyncio
    async def test_stop_loop(self, agent):
        loop = AgentLoop(agent)
        loop.stop()
        assert not loop.is_running

    @pytest.mark.asyncio
    async def test_pause_loop(self, agent):
        loop = AgentLoop(agent)
        loop.pause()
        loop.resume()

    @pytest.mark.asyncio
    async def test_run_once_when_paused(self, agent):
        await agent.initialize()
        await agent.pause()
        loop = AgentLoop(agent)
        await loop.run_once()
        assert agent.state == AgentState.PAUSED

    @pytest.mark.asyncio
    async def test_run_forever_stop(self, agent):
        await agent.initialize()
        await agent.start()
        loop = AgentLoop(agent)
        task = asyncio.create_task(loop.run_forever(interval=0.01))
        await asyncio.sleep(0.03)
        loop.stop()
        await asyncio.sleep(0.05)
        assert not loop.is_running
        await task


# ======================================================================
# Component 5 — AgentRuntime
# ======================================================================


class TestAgentRuntime:
    @pytest.mark.asyncio
    async def test_create(self, event_bus):
        rt = AgentRuntime(event_bus=event_bus)
        assert rt.name == "agent_runtime"
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
    async def test_create_agent(self, runtime):
        a = await runtime.create_agent("a1", "Agent One")
        assert a.agent_id == "a1"
        assert a.name == "Agent One"
        assert runtime.registry.count == 1

    @pytest.mark.asyncio
    async def test_create_agent_duplicate(self, runtime):
        await runtime.create_agent("a1", "One")
        with pytest.raises(ValueError, match="already exists"):
            await runtime.create_agent("a1", "Duplicate")

    @pytest.mark.asyncio
    async def test_remove_agent(self, runtime):
        await runtime.create_agent("a1", "One")
        assert runtime.registry.count == 1
        await runtime.remove_agent("a1")
        assert runtime.registry.count == 0

    @pytest.mark.asyncio
    async def test_remove_agent_not_found(self, runtime):
        with pytest.raises(ValueError, match="not found"):
            await runtime.remove_agent("nonexistent")

    @pytest.mark.asyncio
    async def test_get_agent(self, runtime):
        a = await runtime.create_agent("a1", "One")
        assert runtime.get_agent("a1") is a
        assert runtime.get_agent("nonexistent") is None

    @pytest.mark.asyncio
    async def test_list_agents(self, runtime):
        await runtime.create_agent("a1", "One")
        await runtime.create_agent("a2", "Two")
        agents = runtime.list_agents()
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_start_agent(self, runtime):
        a = await runtime.create_agent("a1", "One")
        await runtime.start_agent("a1")
        assert a.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_start_agent_not_found(self, runtime):
        with pytest.raises(ValueError, match="not found"):
            await runtime.start_agent("nonexistent")

    @pytest.mark.asyncio
    async def test_stop_agent(self, runtime):
        a = await runtime.create_agent("a1", "One")
        await runtime.start_agent("a1")
        await runtime.stop_agent("a1")
        assert a.state == AgentState.STOPPED

    @pytest.mark.asyncio
    async def test_pause_agent(self, runtime):
        a = await runtime.create_agent("a1", "One")
        await runtime.start_agent("a1")
        await runtime.pause_agent("a1")
        assert a.state == AgentState.PAUSED

    @pytest.mark.asyncio
    async def test_resume_agent(self, runtime):
        a = await runtime.create_agent("a1", "One")
        await runtime.start_agent("a1")
        await runtime.pause_agent("a1")
        await runtime.resume_agent("a1")
        assert a.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_assign_mission_via_runtime(self, runtime):
        await runtime.create_agent("a1", "One")
        await runtime.assign_mission("a1", "mission-1")
        a = runtime.get_agent("a1")
        assert a.current_mission == "mission-1"

    @pytest.mark.asyncio
    async def test_assign_mission_not_found(self, runtime):
        with pytest.raises(ValueError, match="not found"):
            await runtime.assign_mission("nonexistent", "m-1")

    @pytest.mark.asyncio
    async def test_heartbeat_all(self, runtime):
        a1 = await runtime.create_agent("a1", "One")
        a2 = await runtime.create_agent("a2", "Two")
        assert a1.last_heartbeat is None
        assert a2.last_heartbeat is None
        await runtime.heartbeat_all()
        assert a1.last_heartbeat is not None
        assert a2.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_stop_stops_all_agents(self, runtime):
        a1 = await runtime.create_agent("a1", "One")
        await runtime.start_agent("a1")
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()
        assert a1.state == AgentState.STOPPED

    @pytest.mark.asyncio
    async def test_iservice_lifecycle(self, runtime):
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()

    @pytest.mark.asyncio
    async def test_super_called_in_lifecycle(self, event_bus):
        calls = []

        class TrackingRuntime(AgentRuntime):
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
    async def test_multiple_agents(self, runtime):
        for i in range(5):
            await runtime.create_agent(f"a{i}", f"Agent {i}")
        assert runtime.registry.count == 5

    @pytest.mark.asyncio
    async def test_agent_state_tracked_in_registry(self, runtime):
        await runtime.create_agent("a1", "One")
        assert len(runtime.registry.idle) == 0
        await runtime.start_agent("a1")
        assert len(runtime.registry.idle) == 1
        await runtime.pause_agent("a1")
        assert len(runtime.registry.paused) == 1


# ======================================================================
# Component 6 — AgentRegistry
# ======================================================================


class TestAgentRegistry:
    def test_register(self, event_bus):
        reg = AgentRegistry()
        a = AtlasAgent(agent_id="r1", name="R1", event_bus=event_bus)
        reg.register(a)
        assert reg.count == 1

    def test_unregister(self, event_bus):
        reg = AgentRegistry()
        a = AtlasAgent(agent_id="r1", name="R1", event_bus=event_bus)
        reg.register(a)
        reg.unregister("r1")
        assert reg.count == 0

    def test_get(self, event_bus):
        reg = AgentRegistry()
        a = AtlasAgent(agent_id="r1", name="R1", event_bus=event_bus)
        reg.register(a)
        assert reg.get("r1") is a
        assert reg.get("none") is None

    def test_list_all(self, event_bus):
        reg = AgentRegistry()
        reg.register(AtlasAgent("r1", "R1", event_bus))
        reg.register(AtlasAgent("r2", "R2", event_bus))
        assert len(reg.list_all()) == 2

    def test_list_by_state(self, event_bus):
        reg = AgentRegistry()
        a1 = AtlasAgent("r1", "R1", event_bus)
        a1._state = AgentState.IDLE
        a2 = AtlasAgent("r2", "R2", event_bus)
        a2._state = AgentState.PAUSED
        reg.register(a1)
        reg.register(a2)
        idle = reg.list_by_state(AgentState.IDLE)
        assert len(idle) == 1
        assert idle[0].agent_id == "r1"

    def test_state_properties(self, event_bus):
        reg = AgentRegistry()
        a = AtlasAgent("r1", "R1", event_bus)
        a._state = AgentState.IDLE
        reg.register(a)
        assert len(reg.running) == 1  # IDLE counts as running
        assert len(reg.paused) == 0
        assert len(reg.failed) == 0
        assert len(reg.stopped) == 0

    def test_clear(self, event_bus):
        reg = AgentRegistry()
        reg.register(AtlasAgent("r1", "R1", event_bus))
        reg.register(AtlasAgent("r2", "R2", event_bus))
        reg.clear()
        assert reg.count == 0

    def test_multiple_state_groups(self, event_bus):
        reg = AgentRegistry()
        states = [AgentState.IDLE, AgentState.PAUSED, AgentState.FAILED, AgentState.STOPPED]
        for i, s in enumerate(states):
            a = AtlasAgent(f"a{i}", f"A{i}", event_bus)
            a._state = s
            reg.register(a)
        assert len(reg.idle) == 1
        assert len(reg.paused) == 1
        assert len(reg.failed) == 1
        assert len(reg.stopped) == 1


# ======================================================================
# Component 7 — AgentContextBridge
# ======================================================================


class TestAgentContextBridge:
    @pytest.mark.asyncio
    async def test_sync_state_publishes_event(self, event_bus):
        bridge = AgentContextBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("context", capture)
        await bridge.sync_state(AgentState.OBSERVING)
        assert len(events) >= 1
        assert events[0].category == EventCategory.CONTEXT
        assert events[0].payload.get("state") == "OBSERVING"

    @pytest.mark.asyncio
    async def test_sync_state_with_mission(self, event_bus):
        bridge = AgentContextBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("context", capture)
        await bridge.sync_state(AgentState.EXECUTING, mission_id="m-1")
        assert events[0].payload.get("mission_id") == "m-1"

    @pytest.mark.asyncio
    async def test_sync_mission(self, event_bus):
        bridge = AgentContextBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("context", capture)
        await bridge.sync_mission("m-1", "RUNNING")
        assert events[0].payload.get("mission_id") == "m-1"
        assert events[0].payload.get("mission_status") == "RUNNING"

    @pytest.mark.asyncio
    async def test_sync_mission_action(self, event_bus):
        bridge = AgentContextBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("context", capture)
        await bridge.sync_mission("m-1", "COMPLETED")
        assert events[0].payload.get("action") == "agent_mission_synced"


# ======================================================================
# Component 8 — AgentMemoryBridge
# ======================================================================


class TestAgentMemoryBridge:
    @pytest.mark.asyncio
    async def test_store_observation(self, event_bus):
        bridge = AgentMemoryBridge(event_bus, "agent-1")
        assert len(bridge.working.observations) == 0
        await bridge.store_observation({"key": "value"})
        assert len(bridge.working.observations) == 1
        assert bridge.working.observations[0]["key"] == "value"

    @pytest.mark.asyncio
    async def test_store_thought(self, event_bus):
        bridge = AgentMemoryBridge(event_bus, "agent-1")
        await bridge.store_thought({"content": "hello"})
        assert len(bridge.working.thoughts) == 1

    @pytest.mark.asyncio
    async def test_store_plan(self, event_bus):
        bridge = AgentMemoryBridge(event_bus, "agent-1")
        await bridge.store_plan({"steps": []})
        assert len(bridge.working.plans) == 1

    @pytest.mark.asyncio
    async def test_store_result(self, event_bus):
        bridge = AgentMemoryBridge(event_bus, "agent-1")
        await bridge.store_result({"success": True})
        assert len(bridge.working.results) == 1

    @pytest.mark.asyncio
    async def test_clear_working(self, event_bus):
        bridge = AgentMemoryBridge(event_bus, "agent-1")
        await bridge.store_observation({"key": "value"})
        await bridge.store_thought({"content": "hello"})
        await bridge.clear_working()
        assert len(bridge.working.observations) == 0
        assert len(bridge.working.thoughts) == 0
        assert len(bridge.working.plans) == 0
        assert len(bridge.working.results) == 0

    @pytest.mark.asyncio
    async def test_store_publishes_event(self, event_bus):
        bridge = AgentMemoryBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("memory", capture)
        await bridge.store_observation({"key": "value"})
        mem_events = [e for e in events if e.category == EventCategory.MEMORY]
        assert len(mem_events) >= 1

    @pytest.mark.asyncio
    async def test_working_memory_max_size(self, event_bus):
        bridge = AgentMemoryBridge(event_bus, "agent-1")
        for i in range(200):
            await bridge.store_observation({"i": i})
        assert len(bridge.working.observations) <= 100


class TestWorkingMemory:
    def test_add_observation(self):
        wm = WorkingMemory()
        wm.add_observation({"key": "value"})
        assert len(wm.observations) == 1

    def test_add_thought(self):
        wm = WorkingMemory()
        wm.add_thought({"content": "hello"})
        assert len(wm.thoughts) == 1

    def test_add_plan(self):
        wm = WorkingMemory()
        wm.add_plan({"steps": []})
        assert len(wm.plans) == 1

    def test_add_result(self):
        wm = WorkingMemory()
        wm.add_result({"success": True})
        assert len(wm.results) == 1

    def test_clear(self):
        wm = WorkingMemory()
        wm.add_observation({"key": "value"})
        wm.add_thought({"content": "hello"})
        wm.clear()
        assert len(wm.observations) == 0
        assert len(wm.thoughts) == 0
        assert len(wm.plans) == 0
        assert len(wm.results) == 0

    def test_max_size_eviction(self):
        wm = WorkingMemory(max_size=3)
        for i in range(5):
            wm.add_observation({"i": i})
        assert len(wm.observations) == 3
        assert wm.observations[-1]["i"] == 4

    def test_separate_lists(self):
        wm = WorkingMemory()
        wm.add_observation({"type": "obs"})
        wm.add_thought({"type": "thought"})
        assert len(wm.observations) == 1
        assert len(wm.thoughts) == 1


# ======================================================================
# Component 9 — AgentMetrics
# ======================================================================


class TestAgentMetrics:
    def test_initial_values(self):
        m = AgentMetrics()
        assert m.missions_completed == 0
        assert m.missions_failed == 0
        assert m.steps_completed == 0
        assert m.reasoning_time == 0.0
        assert m.execution_time == 0.0
        assert m.heartbeat_count == 0
        assert m.errors == 0

    def test_record_mission_completed(self):
        m = AgentMetrics()
        m.record_mission_completed()
        assert m.missions_completed == 1

    def test_record_mission_failed(self):
        m = AgentMetrics()
        m.record_mission_failed()
        assert m.missions_failed == 1

    def test_record_step(self):
        m = AgentMetrics()
        m.record_step_completed()
        assert m.steps_completed == 1

    def test_record_reasoning(self):
        m = AgentMetrics()
        m.record_reasoning(1.5)
        assert m.reasoning_time == 1.5
        m.record_reasoning(0.5)
        assert m.reasoning_time == 2.0

    def test_record_execution(self):
        m = AgentMetrics()
        m.record_execution(2.0)
        assert m.execution_time == 2.0

    def test_record_error(self):
        m = AgentMetrics()
        m.record_error()
        assert m.errors == 1

    def test_record_heartbeat(self):
        m = AgentMetrics()
        m.record_heartbeat()
        assert m.heartbeat_count == 1

    def test_reset(self):
        m = AgentMetrics()
        m.record_mission_completed()
        m.record_error()
        m.record_heartbeat()
        m.reset()
        assert m.missions_completed == 0
        assert m.errors == 0
        assert m.heartbeat_count == 0

    def test_snapshot(self):
        m = AgentMetrics()
        m.record_mission_completed()
        m.record_heartbeat()
        s = m.snapshot()
        assert s["missions_completed"] == 1
        assert s["heartbeat_count"] == 1
        assert "uptime" in s

    def test_current_uptime(self):
        m = AgentMetrics()
        assert m.current_uptime >= 0

    def test_snapshot_includes_all_keys(self):
        m = AgentMetrics()
        s = m.snapshot()
        expected = [
            "missions_completed", "missions_failed", "steps_completed",
            "reasoning_time", "execution_time", "uptime", "idle_time",
            "heartbeat_count", "errors",
        ]
        for key in expected:
            assert key in s


# ======================================================================
# Component 10 — AgentEventBridge
# ======================================================================


class TestAgentEventBridge:
    @pytest.mark.asyncio
    async def test_publish(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.publish("test_action", {"data": "value"})
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_agent_started(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.agent_started()
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert len(agent_events) >= 1
        assert agent_events[0].payload.get("action") == "agent_started"

    @pytest.mark.asyncio
    async def test_agent_stopped(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.agent_stopped()
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert len(agent_events) >= 1
        assert agent_events[0].payload.get("action") == "agent_stopped"

    @pytest.mark.asyncio
    async def test_agent_paused(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.agent_paused()
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert len(agent_events) >= 1

    @pytest.mark.asyncio
    async def test_agent_resumed(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.agent_resumed()
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert len(agent_events) >= 1

    @pytest.mark.asyncio
    async def test_mission_assigned(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.mission_assigned("m-1")
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert agent_events[0].payload.get("mission_id") == "m-1"

    @pytest.mark.asyncio
    async def test_mission_completed(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.mission_completed("m-1")
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert agent_events[0].payload.get("action") == "mission_completed"

    @pytest.mark.asyncio
    async def test_heartbeat_event(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.heartbeat()
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert agent_events[0].payload.get("action") == "heartbeat"

    @pytest.mark.asyncio
    async def test_agent_error(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-1")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.agent_error("something broke")
        agent_events = [e for e in events if e.category == EventCategory.AGENT]
        assert agent_events[0].payload.get("error") == "something broke"

    @pytest.mark.asyncio
    async def test_agent_id_in_events(self, event_bus):
        bridge = AgentEventBridge(event_bus, "agent-99")
        events = []

        async def capture(e):
            events.append(e)

        event_bus.subscribe("agent", capture)
        await bridge.agent_started()
        assert events[0].source == "agent:agent-99"
        assert events[0].payload.get("agent_id") == "agent-99"


# ======================================================================
# Kernel Integration
# ======================================================================


class TestKernelIntegration:
    @pytest.mark.asyncio
    async def test_kernel_registers_agent_runtime(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        assert kernel.agent_runtime is not None
        assert kernel.agent_runtime.name == "agent_runtime"

    @pytest.mark.asyncio
    async def test_kernel_agent_runtime_health(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        await kernel.start()
        health = await kernel.agent_runtime.health_check()
        assert health.healthy
        await kernel.stop()

    @pytest.mark.asyncio
    async def test_kernel_agent_runtime_property_guard(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        with pytest.raises(RuntimeError):
            _ = kernel.agent_runtime

    @pytest.mark.asyncio
    async def test_kernel_agent_runtime_is_service(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        svc = kernel.registry.resolve("agent_runtime")
        assert svc is not None
        assert svc.name == "agent_runtime"

    @pytest.mark.asyncio
    async def test_kernel_agent_runtime_create_agent(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        await kernel.start()
        a = await kernel.agent_runtime.create_agent("k1", "Kernel Agent")
        assert a.agent_id == "k1"
        await kernel.stop()

    @pytest.mark.asyncio
    async def test_kernel_lifecycle_with_agent(self):
        from atlas_core.kernel import AtlasKernel

        kernel = AtlasKernel(config_dir="config")
        kernel.initialize()
        kernel.boot()
        await kernel.start()
        await kernel.agent_runtime.create_agent("lk1", "Lifecycle Agent")
        await kernel.stop()
        assert kernel.state.name == "STOPPED"


# ======================================================================
# EventCategory.AGENT
# ======================================================================


class TestAgentEventCategory:
    def test_agent_category_exists(self):
        assert hasattr(EventCategory, "AGENT")
        assert EventCategory.AGENT.value == "agent"

    def test_agent_category_is_unique(self):
        values = {c.value for c in EventCategory}
        assert "agent" in values


# ======================================================================
# Error Handling
# ======================================================================


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_create_agent_after_stop(self, runtime):
        await runtime.initialize()
        await runtime.start()
        a = await runtime.create_agent("e1", "Error Agent")
        await runtime.stop_agent("e1")
        assert a.state == AgentState.STOPPED

    @pytest.mark.asyncio
    async def test_double_stop_agent(self, runtime):
        a = await runtime.create_agent("e1", "E1")
        await runtime.start_agent("e1")
        await runtime.stop_agent("e1")
        await runtime.stop_agent("e1")
        assert a.state == AgentState.STOPPED

    @pytest.mark.asyncio
    async def test_pause_idle_agent(self, runtime):
        a = await runtime.create_agent("e1", "E1")
        await runtime.start_agent("e1")
        await runtime.pause_agent("e1")
        assert a.state == AgentState.PAUSED

    @pytest.mark.asyncio
    async def test_resume_non_paused_agent(self, runtime):
        a = await runtime.create_agent("e1", "E1")
        await runtime.start_agent("e1")
        await runtime.resume_agent("e1")
        assert a.state == AgentState.IDLE

    @pytest.mark.asyncio
    async def test_runtime_manager_agent_errors(self, runtime):
        await runtime.initialize()
        await runtime.start()
        a = await runtime.create_agent("e1", "E1")
        await agent_methods_that_might_fail(a)
        health = await runtime.health_check()
        assert health.healthy
        await runtime.stop()


async def agent_methods_that_might_fail(agent):
    try:
        await agent.observe()
        await agent.think()
        await agent.plan()
        await agent.execute()
        await agent.learn()
        await agent.heartbeat()
    except Exception:
        pass


# ======================================================================
# Concurrent Operations
# ======================================================================


class TestConcurrentOperations:
    @pytest.mark.asyncio
    async def test_parallel_heartbeat(self, runtime):
        await runtime.create_agent("c1", "C1")
        await runtime.create_agent("c2", "C2")
        await runtime.create_agent("c3", "C3")
        await asyncio.gather(
            runtime.heartbeat_all(),
            runtime.heartbeat_all(),
            runtime.heartbeat_all(),
        )
        for agent in runtime.list_agents():
            assert agent.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_multiple_agents_independent(self, runtime):
        a1 = await runtime.create_agent("m1", "M1")
        a2 = await runtime.create_agent("m2", "M2")
        await runtime.start_agent("m1")
        await runtime.start_agent("m2")
        await runtime.assign_mission("m1", "mission-a")
        await runtime.assign_mission("m2", "mission-b")
        assert a1.current_mission == "mission-a"
        assert a2.current_mission == "mission-b"
        assert a1.agent_id != a2.agent_id


# ======================================================================
# Lifecycle
# ======================================================================


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_full_agent_lifecycle(self, agent):
        await agent.initialize()
        assert agent.state == AgentState.INITIALIZING
        await agent.start()
        assert agent.state == AgentState.IDLE
        await agent.observe()
        assert agent.state == AgentState.OBSERVING
        await agent.think()
        assert agent.state == AgentState.THINKING
        await agent.plan()
        assert agent.state == AgentState.PLANNING
        await agent.execute()
        assert agent.state == AgentState.EXECUTING
        await agent.learn()
        await agent.heartbeat()
        await agent.pause()
        assert agent.state == AgentState.PAUSED
        await agent.resume()
        assert agent.state == AgentState.IDLE
        await agent.stop()
        assert agent.state == AgentState.STOPPED

    @pytest.mark.asyncio
    async def test_agent_metrics_after_full_lifecycle(self, agent):
        await agent.initialize()
        await agent.start()
        await agent.observe()
        await agent.think()
        await agent.plan()
        await agent.execute()
        await agent.learn()
        await agent.heartbeat()
        s = agent.metrics.snapshot()
        assert s["heartbeat_count"] >= 1
        assert s["reasoning_time"] >= 0
        assert s["execution_time"] >= 0

    @pytest.mark.asyncio
    async def test_runtime_manages_multiple_lifecycles(self, runtime):
        agents = []
        for i in range(3):
            a = await runtime.create_agent(f"l{i}", f"L{i}")
            agents.append(a)
            await runtime.start_agent(f"l{i}")
        assert all(a.state == AgentState.IDLE for a in agents)
        for i in range(3):
            await runtime.stop_agent(f"l{i}")
        assert all(a.state == AgentState.STOPPED for a in agents)

    @pytest.mark.asyncio
    async def test_implements_iservice(self, runtime):
        from atlas_core.interfaces import IService
        assert isinstance(runtime, IService)


# ======================================================================
# Edge Cases
# ======================================================================


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_agent_with_empty_id(self, event_bus):
        a = AtlasAgent(agent_id="", name="Empty", event_bus=event_bus)
        assert a.agent_id == ""

    @pytest.mark.asyncio
    async def test_agent_with_special_chars(self, event_bus):
        a = AtlasAgent(agent_id="a.b-c_d", name="Special", event_bus=event_bus)
        await a.initialize()
        assert a.agent_id == "a.b-c_d"

    @pytest.mark.asyncio
    async def test_many_agents_in_registry(self, runtime):
        for i in range(50):
            await runtime.create_agent(f"bulk-{i}", f"Bulk {i}")
        assert runtime.registry.count == 50

    @pytest.mark.asyncio
    async def test_heartbeat_before_start(self, agent):
        await agent.initialize()
        await agent.heartbeat()
        assert agent.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_assign_mission_before_start(self, agent):
        await agent.initialize()
        await agent.assign_mission("pre-start-mission")
        assert agent.current_mission == "pre-start-mission"
