"""Multi-Agent Coordination — coordinates multiple Atlas agents into teams.

This layer allows multiple agents to cooperate safely.
It does NOT introduce AI reasoning.
It does NOT execute commands.
It ONLY coordinates agents.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Component 1 — TeamRole
# ======================================================================


class TeamRole(Enum):
    LEADER = auto()
    PLANNER = auto()
    RESEARCHER = auto()
    EXECUTOR = auto()
    REVIEWER = auto()
    OBSERVER = auto()
    SPECIALIST = auto()


# ======================================================================
# Component 2 — TeamMember
# ======================================================================


@dataclass(frozen=True)
class TeamMember:
    agent_id: str
    role: TeamRole
    capabilities: list[str] = field(default_factory=list)
    state: str = "idle"


# ======================================================================
# Component 3 — AgentTeam
# ======================================================================


@dataclass(frozen=True)
class AgentTeam:
    team_id: str
    name: str
    leader: str
    members: tuple[TeamMember, ...] = field(default_factory=tuple)
    mission: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# Component 7 — TeamEventBridge
# ======================================================================


class TeamEventBridge:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(self, action: str, team_id: str, payload: dict[str, Any] | None = None) -> None:
        event = Event(
            source=f"multi_agent:{team_id}",
            category=EventCategory.MULTI_AGENT,
            priority=EventPriority.NORMAL,
            payload={
                "team_id": team_id,
                "action": action,
                "timestamp": datetime.now().isoformat(),
                **(payload or {}),
            },
        )
        try:
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish team event")

    async def team_created(self, team_id: str, name: str) -> None:
        await self.publish("team_created", team_id, {"name": name})

    async def team_disbanded(self, team_id: str) -> None:
        await self.publish("team_disbanded", team_id)

    async def team_started(self, team_id: str) -> None:
        await self.publish("team_started", team_id)

    async def team_stopped(self, team_id: str) -> None:
        await self.publish("team_stopped", team_id)

    async def team_paused(self, team_id: str) -> None:
        await self.publish("team_paused", team_id)

    async def team_resumed(self, team_id: str) -> None:
        await self.publish("team_resumed", team_id)

    async def task_assigned(self, team_id: str, agent_id: str, task: str) -> None:
        await self.publish("task_assigned", team_id, {"agent_id": agent_id, "task": task})

    async def task_completed(self, team_id: str, agent_id: str, task: str) -> None:
        await self.publish("task_completed", team_id, {"agent_id": agent_id, "task": task})

    async def leader_changed(self, team_id: str, old_leader: str, new_leader: str) -> None:
        await self.publish("leader_changed", team_id, {"old_leader": old_leader, "new_leader": new_leader})


# ======================================================================
# Component 9 — CoordinationMetrics
# ======================================================================


@dataclass
class CoordinationMetrics:
    teams_created: int = 0
    teams_active: int = 0
    missions_completed: int = 0
    assignments: int = 0
    reassignments: int = 0
    errors: int = 0
    utilization: float = 0.0
    _start_time: float = field(default_factory=time.time)

    def record_team_created(self) -> None:
        self.teams_created += 1
        self.teams_active += 1

    def record_team_disbanded(self) -> None:
        self.teams_active = max(0, self.teams_active - 1)

    def record_mission_completed(self) -> None:
        self.missions_completed += 1

    def record_assignment(self) -> None:
        self.assignments += 1

    def record_reassignment(self) -> None:
        self.reassignments += 1

    def record_error(self) -> None:
        self.errors += 1

    def update_utilization(self, ratio: float) -> None:
        self.utilization = ratio

    def snapshot(self) -> dict[str, Any]:
        return {
            "teams_created": self.teams_created,
            "teams_active": self.teams_active,
            "missions_completed": self.missions_completed,
            "assignments": self.assignments,
            "reassignments": self.reassignments,
            "errors": self.errors,
            "utilization": self.utilization,
        }

    def reset(self) -> None:
        self.teams_created = 0
        self.teams_active = 0
        self.missions_completed = 0
        self.assignments = 0
        self.reassignments = 0
        self.errors = 0
        self.utilization = 0.0
        self._start_time = time.time()


# ======================================================================
# Component 8 — CoordinationHistory
# ======================================================================


@dataclass
class HistoryEntry:
    timestamp: datetime = field(default_factory=datetime.now)
    event_type: str = ""
    team_id: str = ""
    agent_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class CoordinationHistory:
    def __init__(self, max_size: int = 1000) -> None:
        self._entries: deque[HistoryEntry] = deque(maxlen=max_size)

    def record(self, entry: HistoryEntry) -> None:
        self._entries.append(entry)

    def record_event(self, event_type: str, team_id: str = "", agent_id: str = "", **details: Any) -> None:
        self._entries.append(HistoryEntry(
            event_type=event_type,
            team_id=team_id,
            agent_id=agent_id,
            details=details,
        ))

    def query(self, event_type: str | None = None, team_id: str | None = None, agent_id: str | None = None, limit: int = 100) -> list[HistoryEntry]:
        result: list[HistoryEntry] = []
        for entry in reversed(self._entries):
            if event_type is not None and entry.event_type != event_type:
                continue
            if team_id is not None and entry.team_id != team_id:
                continue
            if agent_id is not None and entry.agent_id != agent_id:
                continue
            result.append(entry)
            if len(result) >= limit:
                break
        return result

    def clear(self) -> None:
        self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def last(self) -> Optional[HistoryEntry]:
        return self._entries[-1] if self._entries else None


# ======================================================================
# Component 4 — AgentTeamRegistry
# ======================================================================


class AgentTeamRegistry:
    def __init__(self) -> None:
        self._teams: dict[str, AgentTeam] = {}
        self._team_states: dict[str, str] = {}

    def register(self, team: AgentTeam, state: str = "idle") -> None:
        self._teams[team.team_id] = team
        self._team_states[team.team_id] = state

    def unregister(self, team_id: str) -> None:
        self._teams.pop(team_id, None)
        self._team_states.pop(team_id, None)

    def get(self, team_id: str) -> Optional[AgentTeam]:
        return self._teams.get(team_id)

    def get_state(self, team_id: str) -> Optional[str]:
        return self._team_states.get(team_id)

    def set_state(self, team_id: str, state: str) -> None:
        if team_id in self._teams:
            self._team_states[team_id] = state

    def list_all(self) -> list[AgentTeam]:
        return list(self._teams.values())

    def search_by_name(self, name: str) -> list[AgentTeam]:
        return [t for t in self._teams.values() if name.lower() in t.name.lower()]

    def search_by_leader(self, leader_id: str) -> list[AgentTeam]:
        return [t for t in self._teams.values() if t.leader == leader_id]

    def search_by_member(self, agent_id: str) -> list[AgentTeam]:
        return [t for t in self._teams.values() if any(m.agent_id == agent_id for m in t.members)]

    def search_by_mission(self, mission: str) -> list[AgentTeam]:
        return [t for t in self._teams.values() if mission.lower() in t.mission.lower()]

    def list_by_state(self, state: str) -> list[AgentTeam]:
        return [t for t in self._teams.values() if self._team_states.get(t.team_id) == state]

    @property
    def count(self) -> int:
        return len(self._teams)

    @property
    def active(self) -> list[AgentTeam]:
        return self.list_by_state("active")

    @property
    def paused(self) -> list[AgentTeam]:
        return self.list_by_state("paused")

    @property
    def idle(self) -> list[AgentTeam]:
        return self.list_by_state("idle")

    def clear(self) -> None:
        self._teams.clear()
        self._team_states.clear()

    def statistics(self) -> dict[str, Any]:
        return {
            "total": self.count,
            "active": len(self.active),
            "paused": len(self.paused),
            "idle": len(self.idle),
            "states": dict(self._team_states),
        }


# ======================================================================
# Component 5 — CoordinationPolicy
# ======================================================================


class CoordinationPolicy(Enum):
    SEQUENTIAL = auto()
    PARALLEL = auto()
    CONSENSUS = auto()
    LEADER_APPROVAL = auto()
    ROUND_ROBIN = auto()
    BROADCAST = auto()
    LEAST_BUSY = auto()
    ROLE_MATCH = auto()
    CAPABILITY_MATCH = auto()
    PRIORITY = auto()


# ======================================================================
# Component 6 — TaskAllocator
# ======================================================================


class TaskAllocator:
    def __init__(self) -> None:
        self._round_robin_index: dict[str, int] = {}
        self._task_counts: dict[str, int] = {}
        self._logger = logging.getLogger(__name__)

    def allocate(
        self,
        members: tuple[TeamMember, ...],
        policy: CoordinationPolicy,
        task: str = "",
        task_capability: str = "",
        leader_id: str = "",
    ) -> Optional[str]:
        if not members:
            return None

        if policy == CoordinationPolicy.ROUND_ROBIN:
            return self._round_robin(members, task)
        elif policy == CoordinationPolicy.LEAST_BUSY:
            return self._least_busy(members)
        elif policy == CoordinationPolicy.ROLE_MATCH:
            return self._role_match(members, task)
        elif policy == CoordinationPolicy.CAPABILITY_MATCH:
            return self._capability_match(members, task_capability)
        elif policy == CoordinationPolicy.PRIORITY:
            return self._priority(members)
        elif policy == CoordinationPolicy.SEQUENTIAL:
            return self._sequential(members)
        elif policy == CoordinationPolicy.LEADER_APPROVAL:
            return self._leader_approval(members, leader_id)
        elif policy == CoordinationPolicy.BROADCAST:
            return self._broadcast(members)
        elif policy == CoordinationPolicy.CONSENSUS:
            return self._consensus(members)
        else:
            return self._round_robin(members, task)

    def _round_robin(self, members: tuple[TeamMember, ...], task: str) -> str:
        key = task or "default"
        idx = self._round_robin_index.get(key, 0)
        selected = members[idx % len(members)].agent_id
        self._round_robin_index[key] = (idx + 1) % len(members)
        self._increment_count(selected)
        return selected

    def _least_busy(self, members: tuple[TeamMember, ...]) -> str:
        selected = min(members, key=lambda m: self._task_counts.get(m.agent_id, 0))
        self._increment_count(selected.agent_id)
        return selected.agent_id

    def _role_match(self, members: tuple[TeamMember, ...], task: str) -> str:
        role_map = {
            "plan": TeamRole.PLANNER,
            "research": TeamRole.RESEARCHER,
            "execute": TeamRole.EXECUTOR,
            "review": TeamRole.REVIEWER,
            "observe": TeamRole.OBSERVER,
        }
        target_role = None
        for keyword, role in role_map.items():
            if keyword in task.lower():
                target_role = role
                break
        if target_role:
            matched = [m for m in members if m.role == target_role]
            if matched:
                self._increment_count(matched[0].agent_id)
                return matched[0].agent_id
        return self._round_robin(members, task)

    def _capability_match(self, members: tuple[TeamMember, ...], capability: str) -> str:
        if capability:
            matched = [m for m in members if capability.lower() in [c.lower() for c in m.capabilities]]
            if matched:
                self._increment_count(matched[0].agent_id)
                return matched[0].agent_id
        return self._least_busy(members)

    def _priority(self, members: tuple[TeamMember, ...]) -> str:
        leader_members = [m for m in members if m.role == TeamRole.LEADER]
        if leader_members:
            self._increment_count(leader_members[0].agent_id)
            return leader_members[0].agent_id
        return self._least_busy(members)

    def _sequential(self, members: tuple[TeamMember, ...]) -> str:
        return self._round_robin(members, "sequential")

    def _leader_approval(self, members: tuple[TeamMember, ...], leader_id: str) -> Optional[str]:
        if leader_id and any(m.agent_id == leader_id for m in members):
            self._increment_count(leader_id)
            return leader_id
        return self._least_busy(members)

    def _broadcast(self, members: tuple[TeamMember, ...]) -> Optional[str]:
        if members:
            return members[0].agent_id
        return None

    def _consensus(self, members: tuple[TeamMember, ...]) -> Optional[str]:
        if len(members) >= 3:
            return members[0].agent_id
        return None

    def _increment_count(self, agent_id: str) -> None:
        self._task_counts[agent_id] = self._task_counts.get(agent_id, 0) + 1

    def get_task_count(self, agent_id: str) -> int:
        return self._task_counts.get(agent_id, 0)

    def reset_counts(self) -> None:
        self._task_counts.clear()
        self._round_robin_index.clear()


# ======================================================================
# Component 7 — TeamCoordinator
# ======================================================================


TEAM_STATE_IDLE = "idle"
TEAM_STATE_ACTIVE = "active"
TEAM_STATE_PAUSED = "paused"
TEAM_STATE_STOPPED = "stopped"


class TeamCoordinator:
    def __init__(self, event_bus: EventBus, registry: AgentTeamRegistry, metrics: CoordinationMetrics, history: CoordinationHistory, event_bridge: TeamEventBridge) -> None:
        self._event_bus = event_bus
        self._registry = registry
        self._metrics = metrics
        self._history = history
        self._event_bridge = event_bridge
        self._allocator = TaskAllocator()
        self._logger = logging.getLogger(__name__)

    @property
    def allocator(self) -> TaskAllocator:
        return self._allocator

    async def create_team(self, team_id: str, name: str, leader: str, members: list[TeamMember], mission: str = "") -> AgentTeam:
        if self._registry.get(team_id):
            raise ValueError(f"Team already exists: {team_id}")
        team_members = tuple(members)
        if not any(m.agent_id == leader for m in team_members):
            team_members = tuple(list(team_members) + [TeamMember(agent_id=leader, role=TeamRole.LEADER)])
        team = AgentTeam(team_id=team_id, name=name, leader=leader, members=team_members, mission=mission)
        self._registry.register(team, TEAM_STATE_IDLE)
        self._metrics.record_team_created()
        self._history.record_event("team_created", team_id=team_id, leader=leader, name=name)
        await self._event_bridge.team_created(team_id, name)
        self._logger.info("Created team %s (%s)", team_id, name)
        return team

    async def disband_team(self, team_id: str) -> None:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        if self._registry.get_state(team_id) == TEAM_STATE_ACTIVE:
            await self.stop_team(team_id)
        self._registry.unregister(team_id)
        self._metrics.record_team_disbanded()
        self._history.record_event("team_disbanded", team_id=team_id)
        await self._event_bridge.team_disbanded(team_id)
        self._logger.info("Disbanded team %s", team_id)

    async def assign_agent(self, team_id: str, agent_id: str, role: TeamRole, capabilities: list[str] | None = None) -> AgentTeam:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        if any(m.agent_id == agent_id for m in team.members):
            raise ValueError(f"Agent {agent_id} is already in team {team_id}")
        member = TeamMember(agent_id=agent_id, role=role, capabilities=capabilities or [])
        new_members = team.members + (member,)
        new_team = AgentTeam(team_id=team.team_id, name=team.name, leader=team.leader, members=new_members, mission=team.mission, created_at=team.created_at, metadata=team.metadata)
        self._registry.register(new_team, self._registry.get_state(team_id) or TEAM_STATE_IDLE)
        self._history.record_event("agent_assigned", team_id=team_id, agent_id=agent_id, role=role.name)
        await self._publish_event("agent_assigned", team_id, {"agent_id": agent_id, "role": role.name})
        self._logger.info("Assigned agent %s to team %s as %s", agent_id, team_id, role.name)
        return new_team

    async def remove_agent(self, team_id: str, agent_id: str) -> AgentTeam:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        if agent_id == team.leader:
            raise ValueError(f"Cannot remove leader {agent_id} from team {team_id}. Change leader first.")
        new_members = tuple(m for m in team.members if m.agent_id != agent_id)
        if len(new_members) == len(team.members):
            raise ValueError(f"Agent {agent_id} not found in team {team_id}")
        new_team = AgentTeam(team_id=team.team_id, name=team.name, leader=team.leader, members=new_members, mission=team.mission, created_at=team.created_at, metadata=team.metadata)
        self._registry.register(new_team, self._registry.get_state(team_id) or TEAM_STATE_IDLE)
        self._history.record_event("agent_removed", team_id=team_id, agent_id=agent_id)
        await self._publish_event("agent_removed", team_id, {"agent_id": agent_id})
        self._logger.info("Removed agent %s from team %s", agent_id, team_id)
        return new_team

    async def change_leader(self, team_id: str, new_leader: str) -> AgentTeam:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        if not any(m.agent_id == new_leader for m in team.members):
            raise ValueError(f"Agent {new_leader} is not a member of team {team_id}")
        old_leader = team.leader
        new_team = AgentTeam(team_id=team.team_id, name=team.name, leader=new_leader, members=team.members, mission=team.mission, created_at=team.created_at, metadata=team.metadata)
        self._registry.register(new_team, self._registry.get_state(team_id) or TEAM_STATE_IDLE)
        self._history.record_event("leader_changed", team_id=team_id, old_leader=old_leader, new_leader=new_leader)
        await self._event_bridge.leader_changed(team_id, old_leader, new_leader)
        self._logger.info("Changed leader of team %s from %s to %s", team_id, old_leader, new_leader)
        return new_team

    async def start_team(self, team_id: str) -> None:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        self._registry.set_state(team_id, TEAM_STATE_ACTIVE)
        self._history.record_event("team_started", team_id=team_id)
        await self._event_bridge.team_started(team_id)
        self._logger.info("Started team %s", team_id)

    async def pause_team(self, team_id: str) -> None:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        self._registry.set_state(team_id, TEAM_STATE_PAUSED)
        self._history.record_event("team_paused", team_id=team_id)
        await self._event_bridge.team_paused(team_id)
        self._logger.info("Paused team %s", team_id)

    async def resume_team(self, team_id: str) -> None:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        self._registry.set_state(team_id, TEAM_STATE_ACTIVE)
        self._history.record_event("team_resumed", team_id=team_id)
        await self._event_bridge.team_resumed(team_id)
        self._logger.info("Resumed team %s", team_id)

    async def stop_team(self, team_id: str) -> None:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        self._registry.set_state(team_id, TEAM_STATE_STOPPED)
        self._history.record_event("team_stopped", team_id=team_id)
        await self._event_bridge.team_stopped(team_id)
        self._logger.info("Stopped team %s", team_id)

    def status(self, team_id: str) -> dict[str, Any]:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        state = self._registry.get_state(team_id) or "unknown"
        return {
            "team_id": team_id,
            "name": team.name,
            "state": state,
            "leader": team.leader,
            "member_count": len(team.members),
            "members": [{"agent_id": m.agent_id, "role": m.role.name, "state": m.state} for m in team.members],
            "mission": team.mission,
            "created_at": team.created_at.isoformat(),
        }

    async def allocate_task(self, team_id: str, policy: CoordinationPolicy, task: str = "", capability: str = "") -> Optional[str]:
        team = self._registry.get(team_id)
        if team is None:
            raise ValueError(f"Team not found: {team_id}")
        agent_id = self._allocator.allocate(team.members, policy, task, capability, team.leader)
        if agent_id:
            self._metrics.record_assignment()
            self._history.record_event("task_assigned", team_id=team_id, agent_id=agent_id, policy=policy.name, task=task)
            await self._event_bridge.task_assigned(team_id, agent_id, task)
        return agent_id

    async def _publish_event(self, action: str, team_id: str, payload: dict[str, Any]) -> None:
        await self._event_bridge.publish(action, team_id, payload)


# ======================================================================
# Component 11 — MultiAgentRuntime (IService)
# ======================================================================


class MultiAgentRuntime(IService):
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._registry = AgentTeamRegistry()
        self._metrics = CoordinationMetrics()
        self._history = CoordinationHistory()
        self._event_bridge = TeamEventBridge(event_bus)
        self._coordinator = TeamCoordinator(event_bus, self._registry, self._metrics, self._history, self._event_bridge)
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return "multi_agent_runtime"

    @property
    def registry(self) -> AgentTeamRegistry:
        return self._registry

    @property
    def metrics(self) -> CoordinationMetrics:
        return self._metrics

    @property
    def history(self) -> CoordinationHistory:
        return self._history

    @property
    def coordinator(self) -> TeamCoordinator:
        return self._coordinator

    @property
    def event_bridge(self) -> TeamEventBridge:
        return self._event_bridge

    async def initialize(self) -> None:
        await super().initialize()
        self._state = ServiceState.INITIALIZED
        self._logger.info("Multi-Agent Runtime initialized")

    async def start(self) -> None:
        await super().start()
        self._state = ServiceState.RUNNING
        self._logger.info("Multi-Agent Runtime started")

    async def stop(self) -> None:
        await super().stop()
        self._state = ServiceState.STOPPED
        self._logger.info("Multi-Agent Runtime stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=self._state == ServiceState.RUNNING,
            state=self._state,
            message=f"MultiAgentRuntime managing {self._registry.count} teams",
            metadata={
                "team_count": self._registry.count,
                "active_teams": len(self._registry.active),
                "metrics": self._metrics.snapshot(),
            },
        )

    async def create_team(self, team_id: str, name: str, leader: str, members: list[TeamMember] | None = None, mission: str = "") -> AgentTeam:
        return await self._coordinator.create_team(team_id, name, leader, members or [], mission)

    async def disband_team(self, team_id: str) -> None:
        await self._coordinator.disband_team(team_id)

    async def assign_agent(self, team_id: str, agent_id: str, role: TeamRole, capabilities: list[str] | None = None) -> AgentTeam:
        return await self._coordinator.assign_agent(team_id, agent_id, role, capabilities)

    async def remove_agent(self, team_id: str, agent_id: str) -> AgentTeam:
        return await self._coordinator.remove_agent(team_id, agent_id)

    async def change_leader(self, team_id: str, new_leader: str) -> AgentTeam:
        return await self._coordinator.change_leader(team_id, new_leader)

    async def start_team(self, team_id: str) -> None:
        await self._coordinator.start_team(team_id)

    async def pause_team(self, team_id: str) -> None:
        await self._coordinator.pause_team(team_id)

    async def resume_team(self, team_id: str) -> None:
        await self._coordinator.resume_team(team_id)

    async def stop_team(self, team_id: str) -> None:
        await self._coordinator.stop_team(team_id)

    def team_status(self, team_id: str) -> dict[str, Any]:
        return self._coordinator.status(team_id)

    async def allocate_task(self, team_id: str, policy: CoordinationPolicy, task: str = "", capability: str = "") -> Optional[str]:
        return await self._coordinator.allocate_task(team_id, policy, task, capability)

    def get_team(self, team_id: str) -> Optional[AgentTeam]:
        return self._registry.get(team_id)

    def list_teams(self) -> list[AgentTeam]:
        return self._registry.list_all()

    def search_teams(self, name: str = "", leader: str = "", member: str = "", mission: str = "") -> list[AgentTeam]:
        results: list[AgentTeam] = []
        seen: set[str] = set()
        if name:
            for t in self._registry.search_by_name(name):
                if t.team_id not in seen:
                    results.append(t)
                    seen.add(t.team_id)
        if leader:
            for t in self._registry.search_by_leader(leader):
                if t.team_id not in seen:
                    results.append(t)
                    seen.add(t.team_id)
        if member:
            for t in self._registry.search_by_member(member):
                if t.team_id not in seen:
                    results.append(t)
                    seen.add(t.team_id)
        if mission:
            for t in self._registry.search_by_mission(mission):
                if t.team_id not in seen:
                    results.append(t)
                    seen.add(t.team_id)
        if not name and not leader and not member and not mission:
            return self.list_teams()
        return results
