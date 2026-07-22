"""Agent Runtime — orchestrates existing subsystems into autonomous agents."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Component 1 — AgentState
# ======================================================================


class AgentState(Enum):
    INITIALIZING = auto()
    IDLE = auto()
    OBSERVING = auto()
    THINKING = auto()
    PLANNING = auto()
    EXECUTING = auto()
    WAITING = auto()
    PAUSED = auto()
    STOPPING = auto()
    STOPPED = auto()
    FAILED = auto()


# ======================================================================
# Component 2 — IAgent
# ======================================================================


class IAgent(ABC):
    @property
    @abstractmethod
    def agent_id(self) -> str: ...

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def state(self) -> AgentState: ...

    @property
    @abstractmethod
    def current_mission(self) -> Optional[str]: ...

    @property
    @abstractmethod
    def created_at(self) -> datetime: ...

    @property
    @abstractmethod
    def last_heartbeat(self) -> Optional[datetime]: ...

    async def initialize(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def pause(self) -> None: ...
    async def resume(self) -> None: ...

    async def heartbeat(self) -> None: ...
    async def assign_mission(self, mission_id: str) -> None: ...
    async def current_mission_state(self) -> Optional[str]: ...


# ======================================================================
# Component 9 — AgentMetrics
# ======================================================================


@dataclass
class AgentMetrics:
    missions_completed: int = 0
    missions_failed: int = 0
    steps_completed: int = 0
    reasoning_time: float = 0.0
    execution_time: float = 0.0
    uptime: float = 0.0
    idle_time: float = 0.0
    heartbeat_count: int = 0
    errors: int = 0
    _start_time: float = field(default_factory=time.time)

    def record_mission_completed(self) -> None:
        self.missions_completed += 1

    def record_mission_failed(self) -> None:
        self.missions_failed += 1

    def record_step_completed(self) -> None:
        self.steps_completed += 1

    def record_reasoning(self, duration: float) -> None:
        self.reasoning_time += duration

    def record_execution(self, duration: float) -> None:
        self.execution_time += duration

    def record_error(self) -> None:
        self.errors += 1

    def record_heartbeat(self) -> None:
        self.heartbeat_count += 1

    @property
    def current_uptime(self) -> float:
        return time.time() - self._start_time

    def reset(self) -> None:
        self.missions_completed = 0
        self.missions_failed = 0
        self.steps_completed = 0
        self.reasoning_time = 0.0
        self.execution_time = 0.0
        self.uptime = 0.0
        self.idle_time = 0.0
        self.heartbeat_count = 0
        self.errors = 0
        self._start_time = time.time()

    def snapshot(self) -> dict[str, Any]:
        return {
            "missions_completed": self.missions_completed,
            "missions_failed": self.missions_failed,
            "steps_completed": self.steps_completed,
            "reasoning_time": self.reasoning_time,
            "execution_time": self.execution_time,
            "uptime": self.current_uptime,
            "idle_time": self.idle_time,
            "heartbeat_count": self.heartbeat_count,
            "errors": self.errors,
        }


# ======================================================================
# Component 10 — AgentEventBridge
# ======================================================================


class AgentEventBridge:
    def __init__(self, event_bus: EventBus, agent_id: str) -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id
        self._logger = logging.getLogger(__name__)

    async def publish(self, action: str, payload: dict[str, Any] | None = None) -> None:
        event = Event(
            source=f"agent:{self._agent_id}",
            category=EventCategory.AGENT,
            priority=EventPriority.NORMAL,
            payload={
                "agent_id": self._agent_id,
                "action": action,
                "timestamp": datetime.now().isoformat(),
                **(payload or {}),
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish agent event")

    async def agent_started(self) -> None:
        await self.publish("agent_started")

    async def agent_stopped(self) -> None:
        await self.publish("agent_stopped")

    async def agent_paused(self) -> None:
        await self.publish("agent_paused")

    async def agent_resumed(self) -> None:
        await self.publish("agent_resumed")

    async def mission_assigned(self, mission_id: str) -> None:
        await self.publish("mission_assigned", {"mission_id": mission_id})

    async def mission_completed(self, mission_id: str) -> None:
        await self.publish("mission_completed", {"mission_id": mission_id})

    async def heartbeat(self) -> None:
        await self.publish("heartbeat")

    async def agent_error(self, error: str) -> None:
        await self.publish("agent_error", {"error": error})


# ======================================================================
# Component 7 — AgentContextBridge
# ======================================================================


class AgentContextBridge:
    def __init__(self, event_bus: EventBus, agent_id: str) -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id
        self._logger = logging.getLogger(__name__)

    async def sync_state(self, state: AgentState, mission_id: str | None = None) -> None:
        event = Event(
            source=f"agent_context_bridge:{self._agent_id}",
            category=EventCategory.CONTEXT,
            priority=EventPriority.NORMAL,
            payload={
                "agent_id": self._agent_id,
                "state": state.name,
                "mission_id": mission_id,
                "action": "agent_state_changed",
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to sync agent state to context")

    async def sync_mission(self, mission_id: str, mission_status: str) -> None:
        event = Event(
            source=f"agent_context_bridge:{self._agent_id}",
            category=EventCategory.CONTEXT,
            priority=EventPriority.NORMAL,
            payload={
                "agent_id": self._agent_id,
                "mission_id": mission_id,
                "mission_status": mission_status,
                "action": "agent_mission_synced",
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to sync agent mission to context")


# ======================================================================
# Component 8 — AgentMemoryBridge
# ======================================================================


@dataclass
class WorkingMemory:
    observations: list[dict[str, Any]] = field(default_factory=list)
    thoughts: list[dict[str, Any]] = field(default_factory=list)
    plans: list[dict[str, Any]] = field(default_factory=list)
    results: list[dict[str, Any]] = field(default_factory=list)
    max_size: int = 100

    def add_observation(self, data: dict[str, Any]) -> None:
        self.observations.append(data)
        if len(self.observations) > self.max_size:
            self.observations.pop(0)

    def add_thought(self, data: dict[str, Any]) -> None:
        self.thoughts.append(data)
        if len(self.thoughts) > self.max_size:
            self.thoughts.pop(0)

    def add_plan(self, data: dict[str, Any]) -> None:
        self.plans.append(data)
        if len(self.plans) > self.max_size:
            self.plans.pop(0)

    def add_result(self, data: dict[str, Any]) -> None:
        self.results.append(data)
        if len(self.results) > self.max_size:
            self.results.pop(0)

    def clear(self) -> None:
        self.observations.clear()
        self.thoughts.clear()
        self.plans.clear()
        self.results.clear()


class AgentMemoryBridge:
    def __init__(self, event_bus: EventBus, agent_id: str) -> None:
        self._event_bus = event_bus
        self._agent_id = agent_id
        self._working = WorkingMemory()
        self._logger = logging.getLogger(__name__)

    @property
    def working(self) -> WorkingMemory:
        return self._working

    async def store_observation(self, data: dict[str, Any]) -> None:
        self._working.add_observation(data)
        await self._publish_memory_event("observation_stored", data)

    async def store_thought(self, data: dict[str, Any]) -> None:
        self._working.add_thought(data)
        await self._publish_memory_event("thought_stored", data)

    async def store_plan(self, data: dict[str, Any]) -> None:
        self._working.add_plan(data)
        await self._publish_memory_event("plan_stored", data)

    async def store_result(self, data: dict[str, Any]) -> None:
        self._working.add_result(data)
        await self._publish_memory_event("result_stored", data)

    async def _publish_memory_event(self, action: str, data: dict[str, Any]) -> None:
        event = Event(
            source=f"agent_memory_bridge:{self._agent_id}",
            category=EventCategory.MEMORY,
            priority=EventPriority.LOW,
            payload={
                "agent_id": self._agent_id,
                "action": action,
                "data": data,
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish agent memory event")

    async def clear_working(self) -> None:
        self._working.clear()
        event = Event(
            source=f"agent_memory_bridge:{self._agent_id}",
            category=EventCategory.MEMORY,
            priority=EventPriority.LOW,
            payload={
                "agent_id": self._agent_id,
                "action": "working_memory_cleared",
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish memory clear event")


# ======================================================================
# Component 4 — AgentLoop
# ======================================================================


class AgentLoop:
    def __init__(self, agent: AtlasAgent) -> None:
        self._agent = agent
        self._running = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._logger = logging.getLogger(__name__)

    @property
    def is_running(self) -> bool:
        return self._running

    async def run_once(self) -> None:
        if self._agent._state == AgentState.PAUSED:
            await self._pause_event.wait()
            return

        self._agent._metrics.idle_time = 0.0

        await self._agent.observe()
        if self._agent._state == AgentState.PAUSED:
            return

        await self._agent.think()
        if self._agent._state == AgentState.PAUSED:
            return

        await self._agent.plan()
        if self._agent._state == AgentState.PAUSED:
            return

        await self._agent.execute()
        if self._agent._state == AgentState.PAUSED:
            return

        await self._agent.learn()
        if self._agent._state == AgentState.PAUSED:
            return

        await self._agent.heartbeat()

    async def run_forever(self, interval: float = 0.5) -> None:
        self._running = True
        self._pause_event.set()
        try:
            while self._running:
                await self.run_once()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            self._running = False
        except Exception:
            self._logger.exception("Agent loop crashed")
            self._running = False
            raise

    def stop(self) -> None:
        self._running = False

    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()


# ======================================================================
# Component 3 — AtlasAgent
# ======================================================================


class AtlasAgent(IAgent):
    def __init__(
        self,
        agent_id: str,
        name: str,
        event_bus: EventBus,
    ) -> None:
        self._agent_id = agent_id
        self._name = name
        self._event_bus = event_bus
        self._state = AgentState.INITIALIZING
        self._current_mission: Optional[str] = None
        self._created_at = datetime.now()
        self._last_heartbeat: Optional[datetime] = None
        self._metrics = AgentMetrics()
        self._event_bridge = AgentEventBridge(event_bus, agent_id)
        self._context_bridge = AgentContextBridge(event_bus, agent_id)
        self._memory_bridge = AgentMemoryBridge(event_bus, agent_id)
        self._loop: Optional[AgentLoop] = None
        self._logger = logging.getLogger(__name__)

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> AgentState:
        return self._state

    @property
    def current_mission(self) -> Optional[str]:
        return self._current_mission

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def last_heartbeat(self) -> Optional[datetime]:
        return self._last_heartbeat

    @property
    def metrics(self) -> AgentMetrics:
        return self._metrics

    @property
    def event_bridge(self) -> AgentEventBridge:
        return self._event_bridge

    @property
    def context_bridge(self) -> AgentContextBridge:
        return self._context_bridge

    @property
    def memory_bridge(self) -> AgentMemoryBridge:
        return self._memory_bridge

    async def initialize(self) -> None:
        self._state = AgentState.INITIALIZING
        self._loop = AgentLoop(self)
        self._logger.info("Agent %s initialized", self._agent_id)

    async def start(self) -> None:
        self._state = AgentState.IDLE
        await self._event_bridge.agent_started()
        self._logger.info("Agent %s started", self._agent_id)

    async def stop(self) -> None:
        self._state = AgentState.STOPPING
        if self._loop:
            self._loop.stop()
        self._state = AgentState.STOPPED
        await self._event_bridge.agent_stopped()
        self._logger.info("Agent %s stopped", self._agent_id)

    async def pause(self) -> None:
        self._state = AgentState.PAUSED
        if self._loop:
            self._loop.pause()
        await self._event_bridge.agent_paused()
        self._logger.info("Agent %s paused", self._agent_id)

    async def resume(self) -> None:
        if self._loop:
            self._loop.resume()
        self._state = AgentState.IDLE
        await self._event_bridge.agent_resumed()
        self._logger.info("Agent %s resumed", self._agent_id)

    async def heartbeat(self) -> None:
        self._last_heartbeat = datetime.now()
        self._metrics.record_heartbeat()
        await self._event_bridge.heartbeat()

    async def assign_mission(self, mission_id: str) -> None:
        self._current_mission = mission_id
        await self._event_bridge.mission_assigned(mission_id)
        self._logger.info("Agent %s assigned mission %s", self._agent_id, mission_id)

    async def current_mission_state(self) -> Optional[str]:
        return self._current_mission

    async def observe(self) -> dict[str, Any]:
        self._state = AgentState.OBSERVING
        await self._context_bridge.sync_state(self._state, self._current_mission)
        observations = {
            "agent_id": self._agent_id,
            "timestamp": datetime.now().isoformat(),
            "state": self._state.name,
            "current_mission": self._current_mission,
            "metrics": self._metrics.snapshot(),
        }
        await self._memory_bridge.store_observation(observations)
        self._logger.debug("Agent %s observed", self._agent_id)
        return observations

    async def think(self) -> dict[str, Any]:
        self._state = AgentState.THINKING
        await self._context_bridge.sync_state(self._state, self._current_mission)
        start = time.time()
        thought = {
            "agent_id": self._agent_id,
            "timestamp": datetime.now().isoformat(),
            "state": self._state.name,
            "current_mission": self._current_mission,
        }
        duration = time.time() - start
        self._metrics.record_reasoning(duration)
        await self._memory_bridge.store_thought(thought)
        self._logger.debug("Agent %s thought (%.3fs)", self._agent_id, duration)
        return thought

    async def plan(self) -> dict[str, Any]:
        self._state = AgentState.PLANNING
        await self._context_bridge.sync_state(self._state, self._current_mission)
        plan_data = {
            "agent_id": self._agent_id,
            "timestamp": datetime.now().isoformat(),
            "state": self._state.name,
            "current_mission": self._current_mission,
        }
        await self._memory_bridge.store_plan(plan_data)
        self._logger.debug("Agent %s planned", self._agent_id)
        return plan_data

    async def execute(self) -> dict[str, Any]:
        self._state = AgentState.EXECUTING
        await self._context_bridge.sync_state(self._state, self._current_mission)
        start = time.time()
        result = {
            "agent_id": self._agent_id,
            "timestamp": datetime.now().isoformat(),
            "state": self._state.name,
            "current_mission": self._current_mission,
        }
        duration = time.time() - start
        self._metrics.record_execution(duration)
        await self._memory_bridge.store_result(result)
        self._logger.debug("Agent %s executed (%.3fs)", self._agent_id, duration)
        return result

    async def learn(self) -> dict[str, Any]:
        await self._context_bridge.sync_state(self._state, self._current_mission)
        learning = {
            "agent_id": self._agent_id,
            "timestamp": datetime.now().isoformat(),
            "metrics": self._metrics.snapshot(),
        }
        self._logger.debug("Agent %s learned", self._agent_id)
        return learning

    async def run_once(self) -> None:
        if self._loop:
            await self._loop.run_once()

    async def run_forever(self, interval: float = 0.5) -> None:
        if self._loop:
            await self._loop.run_forever(interval)


# ======================================================================
# Component 6 — AgentRegistry
# ======================================================================


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AtlasAgent] = {}

    def register(self, agent: AtlasAgent) -> None:
        self._agents[agent.agent_id] = agent

    def unregister(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    def get(self, agent_id: str) -> Optional[AtlasAgent]:
        return self._agents.get(agent_id)

    def list_all(self) -> list[AtlasAgent]:
        return list(self._agents.values())

    def list_by_state(self, state: AgentState) -> list[AtlasAgent]:
        return [a for a in self._agents.values() if a.state == state]

    @property
    def running(self) -> list[AtlasAgent]:
        return self.list_by_state(AgentState.IDLE)

    @property
    def paused(self) -> list[AtlasAgent]:
        return self.list_by_state(AgentState.PAUSED)

    @property
    def failed(self) -> list[AtlasAgent]:
        return self.list_by_state(AgentState.FAILED)

    @property
    def idle(self) -> list[AtlasAgent]:
        return self.list_by_state(AgentState.IDLE)

    @property
    def stopped(self) -> list[AtlasAgent]:
        return self.list_by_state(AgentState.STOPPED)

    @property
    def count(self) -> int:
        return len(self._agents)

    def clear(self) -> None:
        self._agents.clear()


# ======================================================================
# Component 5 — AgentRuntime (IService)
# ======================================================================


class AgentRuntime(IService):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._registry = AgentRegistry()
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return "agent_runtime"

    @property
    def registry(self) -> AgentRegistry:
        return self._registry

    async def initialize(self) -> None:
        await super().initialize()
        self._state = ServiceState.INITIALIZED
        self._logger.info("Agent Runtime initialized")

    async def start(self) -> None:
        await super().start()
        self._state = ServiceState.RUNNING
        self._logger.info("Agent Runtime started")

    async def stop(self) -> None:
        await super().stop()
        await self._stop_all_agents()
        self._state = ServiceState.STOPPED
        self._logger.info("Agent Runtime stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=self._state == ServiceState.RUNNING,
            state=self._state,
            message=f"AgentRuntime managing {self._registry.count} agents",
            metadata={"agent_count": self._registry.count},
        )

    async def _stop_all_agents(self) -> None:
        for agent in self._registry.list_all():
            if agent.state in (AgentState.IDLE, AgentState.PAUSED, AgentState.INITIALIZING):
                try:
                    await agent.stop()
                except Exception:
                    self._logger.exception("Failed to stop agent %s", agent.agent_id)

    async def create_agent(self, agent_id: str, name: str) -> AtlasAgent:
        if self._registry.get(agent_id):
            raise ValueError(f"Agent already exists: {agent_id}")
        agent = AtlasAgent(agent_id=agent_id, name=name, event_bus=self._event_bus)
        await agent.initialize()
        self._registry.register(agent)
        self._logger.info("Created agent %s (%s)", agent_id, name)
        return agent

    async def remove_agent(self, agent_id: str) -> None:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")
        if agent.state in (AgentState.IDLE, AgentState.OBSERVING, AgentState.THINKING, AgentState.PLANNING, AgentState.EXECUTING):
            await agent.stop()
        self._registry.unregister(agent_id)
        self._logger.info("Removed agent %s", agent_id)

    def get_agent(self, agent_id: str) -> Optional[AtlasAgent]:
        return self._registry.get(agent_id)

    def list_agents(self) -> list[AtlasAgent]:
        return self._registry.list_all()

    async def start_agent(self, agent_id: str) -> None:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")
        await agent.start()

    async def stop_agent(self, agent_id: str) -> None:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")
        await agent.stop()

    async def pause_agent(self, agent_id: str) -> None:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")
        await agent.pause()

    async def resume_agent(self, agent_id: str) -> None:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")
        await agent.resume()

    async def assign_mission(self, agent_id: str, mission_id: str) -> None:
        agent = self._registry.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent not found: {agent_id}")
        await agent.assign_mission(mission_id)

    async def heartbeat_all(self) -> None:
        for agent in self._registry.list_all():
            try:
                await agent.heartbeat()
            except Exception:
                self._logger.exception("Failed to heartbeat agent %s", agent.agent_id)
