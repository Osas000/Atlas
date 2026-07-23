"""Distributed Runtime for Atlas.

This subsystem enables multiple Atlas runtimes (nodes) to discover each other,
exchange messages, synchronize state, distribute workloads, and perform leader
election.

Architecture
- No networking implementation (ReferenceTransport is in-memory only)
- No cloud/Kubernetes/Docker integration
- No AI/browser/business logic
- IService lifecycle, frozen dataclasses, full typing, thread-safe
- EventBus-only integration via DistributedEventBridge
- PersistenceManager for durable state only
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Optional

from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory


# ======================================================================
# Enums
# ======================================================================

class NodeState(Enum):
    UNKNOWN = "unknown"
    DISCOVERING = "discovering"
    ONLINE = "online"
    OFFLINE = "offline"
    UNREACHABLE = "unreachable"
    LEADER = "leader"
    FOLLOWER = "follower"


# ======================================================================
# Frozen dataclasses
# ======================================================================

@dataclass(frozen=True)
class NodeInfo:
    node_id: str
    hostname: str
    version: str
    state: NodeState = NodeState.UNKNOWN
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClusterInfo:
    cluster_id: str
    leader_id: str
    members: tuple[NodeInfo, ...] = ()
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeHealth:
    latency: float = 0.0
    heartbeat_age: float = 0.0
    healthy: bool = True
    last_error: str = ""


# ======================================================================
# NodeRegistry
# ======================================================================

class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, NodeInfo] = {}
        self._health: dict[str, NodeHealth] = {}
        self._lock = Lock()

    def register_node(self, info: NodeInfo) -> None:
        with self._lock:
            self._nodes[info.node_id] = info
            if info.node_id not in self._health:
                self._health[info.node_id] = NodeHealth()

    def remove_node(self, node_id: str) -> Optional[NodeInfo]:
        with self._lock:
            self._health.pop(node_id, None)
            return self._nodes.pop(node_id, None)

    def lookup(self, node_id: str) -> Optional[NodeInfo]:
        with self._lock:
            return self._nodes.get(node_id)

    def list(self) -> tuple[NodeInfo, ...]:
        with self._lock:
            return tuple(self._nodes.values())

    def health(self, node_id: str) -> Optional[NodeHealth]:
        with self._lock:
            return self._health.get(node_id)

    def update_health(self, node_id: str, health: NodeHealth) -> None:
        with self._lock:
            self._health[node_id] = health

    def update_state(self, node_id: str, state: NodeState) -> None:
        with self._lock:
            node = self._nodes.get(node_id)
            if node is not None:
                self._nodes[node_id] = NodeInfo(
                    node_id=node.node_id,
                    hostname=node.hostname,
                    version=node.version,
                    state=state,
                    capabilities=node.capabilities,
                    metadata=node.metadata,
                )

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._nodes)


# ======================================================================
# Transport (ABC)
# ======================================================================

class Transport(ABC):
    @abstractmethod
    async def connect(self, node_id: str, address: str) -> bool: ...

    @abstractmethod
    async def disconnect(self, node_id: str) -> bool: ...

    @abstractmethod
    async def send(self, target_node: str, message: dict[str, Any]) -> bool: ...

    @abstractmethod
    async def broadcast(self, message: dict[str, Any]) -> int: ...

    @abstractmethod
    async def receive(self) -> list[tuple[str, dict[str, Any]]]: ...

    @abstractmethod
    async def health_check(self, node_id: str) -> NodeHealth: ...


# ======================================================================
# ReferenceTransport (in-memory)
# ======================================================================

class ReferenceTransport(Transport):
    def __init__(self) -> None:
        self._connections: dict[str, str] = {}
        self._mailbox: dict[str, list[dict[str, Any]]] = {}
        self._lock = Lock()
        self._latency: dict[str, float] = {}

    async def connect(self, node_id: str, address: str) -> bool:
        with self._lock:
            self._connections[node_id] = address
            self._mailbox.setdefault(node_id, [])
            self._latency[node_id] = 0.01
        return True

    async def disconnect(self, node_id: str) -> bool:
        with self._lock:
            self._connections.pop(node_id, None)
            self._mailbox.pop(node_id, None)
            self._latency.pop(node_id, None)
        return True

    async def send(self, target_node: str, message: dict[str, Any]) -> bool:
        with self._lock:
            if target_node not in self._mailbox:
                return False
            self._mailbox[target_node].append(message)
        return True

    async def broadcast(self, message: dict[str, Any]) -> int:
        count = 0
        with self._lock:
            for node_id in list(self._mailbox):
                self._mailbox[node_id].append(message)
                count += 1
        return count

    async def receive(self) -> list[tuple[str, dict[str, Any]]]:
        result: list[tuple[str, dict[str, Any]]] = []
        with self._lock:
            for node_id, messages in self._mailbox.items():
                for msg in messages:
                    result.append((node_id, msg))
                self._mailbox[node_id] = []
        return result

    async def health_check(self, node_id: str) -> NodeHealth:
        with self._lock:
            if node_id not in self._connections:
                return NodeHealth(healthy=False, last_error="not connected")
            return NodeHealth(
                latency=self._latency.get(node_id, 0.0),
                heartbeat_age=0.0,
                healthy=True,
            )

    @property
    def connection_count(self) -> int:
        with self._lock:
            return len(self._connections)


# ======================================================================
# LeaderElection (deterministic — lowest node_id wins)
# ======================================================================

class LeaderElection:
    def __init__(self) -> None:
        self._term: int = 0
        self._leader_id: str = ""
        self._lock = Lock()
        self._voted_for: Optional[str] = None

    def elect(self, candidates: list[str]) -> str:
        with self._lock:
            if not candidates:
                return ""
            self._term += 1
            # deterministic: lowest node_id wins
            winner = min(candidates)
            self._leader_id = winner
            self._voted_for = winner
            return winner

    def re_elect(self, candidates: list[str], exclude: Optional[list[str]] = None) -> str:
        filtered = [c for c in candidates if c not in (exclude or [])]
        return self.elect(filtered)

    def step_down(self) -> None:
        with self._lock:
            self._leader_id = ""
            self._voted_for = None

    @property
    def leader(self) -> str:
        with self._lock:
            return self._leader_id

    @property
    def term(self) -> int:
        with self._lock:
            return self._term

    @property
    def current_leader(self) -> str:
        return self.leader


# ======================================================================
# ClusterCoordinator
# ======================================================================

class ClusterCoordinator:
    def __init__(
        self,
        registry: NodeRegistry,
        transport: Transport,
        election: LeaderElection,
        cluster_id: str = "default",
    ) -> None:
        self._registry = registry
        self._transport = transport
        self._election = election
        self._cluster_id = cluster_id
        self._local_node_id: str = ""

    async def join_cluster(self, node: NodeInfo) -> bool:
        self._local_node_id = node.node_id
        self._registry.register_node(node)

        members = self._registry.list()
        member_ids = [m.node_id for m in members]
        leader_id = self._election.elect(member_ids)

        if node.node_id == leader_id:
            self._registry.update_state(node.node_id, NodeState.LEADER)
        else:
            self._registry.update_state(node.node_id, NodeState.FOLLOWER)

        await self._transport.connect(node.node_id, node.hostname)
        return True

    async def leave_cluster(self, node_id: str) -> bool:
        self._registry.remove_node(node_id)
        await self._transport.disconnect(node_id)

        if self._election.leader == node_id:
            members = self._registry.list()
            member_ids = [m.node_id for m in members]
            if member_ids:
                new_leader = self._election.re_elect(member_ids, exclude=[node_id])
                for m in members:
                    if m.node_id == new_leader:
                        self._registry.update_state(m.node_id, NodeState.LEADER)
                    else:
                        self._registry.update_state(m.node_id, NodeState.FOLLOWER)
            else:
                self._election.step_down()

        return True

    def leader(self) -> str:
        return self._election.leader

    def members(self) -> tuple[NodeInfo, ...]:
        return self._registry.list()

    def local_node_id(self) -> str:
        return self._local_node_id

    @property
    def cluster_id(self) -> str:
        return self._cluster_id


# ======================================================================
# HeartbeatManager
# ======================================================================

class HeartbeatManager:
    def __init__(self, registry: NodeRegistry, timeout: float = 5.0) -> None:
        self._registry = registry
        self._timeout = timeout
        self._heartbeats: dict[str, float] = {}
        self._lock = Lock()

    async def heartbeat(self, node_id: str) -> None:
        now = time.time()
        with self._lock:
            self._heartbeats[node_id] = now

    def check_timeouts(self) -> list[str]:
        timed_out: list[str] = []
        now = time.time()
        with self._lock:
            for node_id, last_beat in list(self._heartbeats.items()):
                age = now - last_beat
                if age > self._timeout:
                    timed_out.append(node_id)
                    self._heartbeats.pop(node_id, None)
                    self._registry.update_state(node_id, NodeState.UNREACHABLE)
        return timed_out

    def update(self, node_id: str) -> None:
        now = time.time()
        with self._lock:
            self._heartbeats[node_id] = now

    def get_heartbeat_age(self, node_id: str) -> float:
        now = time.time()
        with self._lock:
            last = self._heartbeats.get(node_id)
            if last is None:
                return float("inf")
            return now - last

    def is_alive(self, node_id: str) -> bool:
        age = self.get_heartbeat_age(node_id)
        return age < self._timeout

    @property
    def timeout(self) -> float:
        return self._timeout

    @timeout.setter
    def timeout(self, value: float) -> None:
        self._timeout = value

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._heartbeats)


# ======================================================================
# DistributedScheduler (deterministic — round-robin)
# ======================================================================

class DistributedScheduler:
    def __init__(self, registry: NodeRegistry) -> None:
        self._registry = registry
        self._assignment: dict[str, str] = {}
        self._lock = Lock()
        self._cursor: int = 0

    def assign(self, workflow_id: str) -> Optional[str]:
        with self._lock:
            nodes = [n for n in self._registry.list() if n.state in (NodeState.ONLINE, NodeState.LEADER, NodeState.FOLLOWER)]
            if not nodes:
                return None
            node = nodes[self._cursor % len(nodes)]
            self._cursor += 1
            self._assignment[workflow_id] = node.node_id
            return node.node_id

    def assign_to_node(self, workflow_id: str, node_id: str) -> bool:
        with self._lock:
            node = self._registry.lookup(node_id)
            if node is None:
                return False
            self._assignment[workflow_id] = node_id
            return True

    def get_assignment(self, workflow_id: str) -> Optional[str]:
        with self._lock:
            return self._assignment.get(workflow_id)

    def unassign(self, workflow_id: str) -> Optional[str]:
        with self._lock:
            return self._assignment.pop(workflow_id, None)

    def assignments(self) -> dict[str, str]:
        with self._lock:
            return dict(self._assignment)

    def clear(self) -> None:
        with self._lock:
            self._assignment.clear()
            self._cursor = 0


# ======================================================================
# ClusterHistory (ring buffer)
# ======================================================================

@dataclass(frozen=True)
class HistoryEntry:
    timestamp: float
    event_type: str
    node_id: str
    detail: str = ""


class ClusterHistory:
    def __init__(self, max_size: int = 1000) -> None:
        self._entries: deque[HistoryEntry] = deque(maxlen=max_size)
        self._lock = Lock()

    def record(self, entry: HistoryEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def recent(self, count: int = 100) -> list[HistoryEntry]:
        with self._lock:
            return list(self._entries)[-count:]

    def search(self, event_type: Optional[str] = None, node_id: Optional[str] = None) -> list[HistoryEntry]:
        results: list[HistoryEntry] = []
        with self._lock:
            for entry in self._entries:
                if event_type and entry.event_type != event_type:
                    continue
                if node_id and entry.node_id != node_id:
                    continue
                results.append(entry)
        return results

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)


# ======================================================================
# ClusterMetrics
# ======================================================================

class ClusterMetrics:
    def __init__(self) -> None:
        self._joins: int = 0
        self._leaves: int = 0
        self._heartbeats: int = 0
        self._messages_sent: int = 0
        self._messages_received: int = 0
        self._elections: int = 0
        self._failures: int = 0
        self._recoveries: int = 0
        self._lock = Lock()

    def increment_joins(self) -> None:
        with self._lock:
            self._joins += 1

    def increment_leaves(self) -> None:
        with self._lock:
            self._leaves += 1

    def increment_heartbeats(self) -> None:
        with self._lock:
            self._heartbeats += 1

    def increment_messages_sent(self) -> None:
        with self._lock:
            self._messages_sent += 1

    def increment_messages_received(self) -> None:
        with self._lock:
            self._messages_received += 1

    def increment_elections(self) -> None:
        with self._lock:
            self._elections += 1

    def increment_failures(self) -> None:
        with self._lock:
            self._failures += 1

    def increment_recoveries(self) -> None:
        with self._lock:
            self._recoveries += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "joins": self._joins,
                "leaves": self._leaves,
                "heartbeats": self._heartbeats,
                "messages_sent": self._messages_sent,
                "messages_received": self._messages_received,
                "elections": self._elections,
                "failures": self._failures,
                "recoveries": self._recoveries,
            }

    def reset(self) -> None:
        with self._lock:
            self._joins = 0
            self._leaves = 0
            self._heartbeats = 0
            self._messages_sent = 0
            self._messages_received = 0
            self._elections = 0
            self._failures = 0
            self._recoveries = 0

    @property
    def joins(self) -> int:
        with self._lock:
            return self._joins

    @property
    def leaves(self) -> int:
        with self._lock:
            return self._leaves

    @property
    def heartbeats(self) -> int:
        with self._lock:
            return self._heartbeats

    @property
    def messages_sent(self) -> int:
        with self._lock:
            return self._messages_sent

    @property
    def messages_received(self) -> int:
        with self._lock:
            return self._messages_received

    @property
    def elections(self) -> int:
        with self._lock:
            return self._elections

    @property
    def failures(self) -> int:
        with self._lock:
            return self._failures

    @property
    def recoveries(self) -> int:
        with self._lock:
            return self._recoveries


# ======================================================================
# DistributedEventBridge
# ======================================================================

class DistributedEventBridge:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def publish_node_joined(self, node_id: str, cluster_id: str) -> None:
        await self._publish("node_joined", node_id, {"cluster_id": cluster_id})

    async def publish_node_left(self, node_id: str, cluster_id: str) -> None:
        await self._publish("node_left", node_id, {"cluster_id": cluster_id})

    async def publish_leader_elected(self, leader_id: str, term: int) -> None:
        await self._publish("leader_elected", leader_id, {"term": term})

    async def publish_heartbeat(self, node_id: str) -> None:
        await self._publish("heartbeat", node_id, {})

    async def publish_message_sent(self, source: str, target: str, msg_type: str) -> None:
        await self._publish("message_sent", source, {"target": target, "message_type": msg_type})

    async def publish_message_received(self, target: str, source: str, msg_type: str) -> None:
        await self._publish("message_received", target, {"source": source, "message_type": msg_type})

    async def publish_node_failed(self, node_id: str, error: str) -> None:
        await self._publish("node_failed", node_id, {"error": error})

    async def publish_node_recovered(self, node_id: str) -> None:
        await self._publish("node_recovered", node_id, {})

    async def _publish(self, event_type: str, source: str, payload: dict[str, Any]) -> None:
        event = Event(
            source="distributed_runtime",
            category=EventCategory.DISTRIBUTED,
            payload={
                "event_type": event_type,
                "source_node": source,
                **payload,
            },
        )
        await self._event_bus.publish(event)


# ======================================================================
# DistributedRuntime (IService)
# ======================================================================

class DistributedRuntime(IService):
    def __init__(
        self,
        event_bus: EventBus,
        cluster_id: str = "default",
        node_id: str = "",
        hostname: str = "",
        version: str = "1.0.0",
    ) -> None:
        self._event_bus = event_bus
        self._cluster_id = cluster_id
        self._node_id = node_id
        self._hostname = hostname
        self._version = version
        self._service_state = ServiceState.CREATED
        self._service_metadata: dict[str, Any] = {}
        self._state_lock = Lock()
        self._initialized = False
        self._started = False
        self._stopped = False

        self._registry = NodeRegistry()
        self._transport = ReferenceTransport()
        self._election = LeaderElection()
        self._coordinator = ClusterCoordinator(self._registry, self._transport, self._election, cluster_id)
        self._heartbeat = HeartbeatManager(self._registry, timeout=5.0)
        self._scheduler = DistributedScheduler(self._registry)
        self._history = ClusterHistory(max_size=1000)
        self._metrics = ClusterMetrics()
        self._event_bridge = DistributedEventBridge(event_bus)
        self._background_tasks: list[asyncio.Task[Any]] = []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def registry(self) -> NodeRegistry:
        return self._registry

    @property
    def transport(self) -> Transport:
        return self._transport

    @property
    def coordinator(self) -> ClusterCoordinator:
        return self._coordinator

    @property
    def election(self) -> LeaderElection:
        return self._election

    @property
    def heartbeat_manager(self) -> HeartbeatManager:
        return self._heartbeat

    @property
    def scheduler(self) -> DistributedScheduler:
        return self._scheduler

    @property
    def history(self) -> ClusterHistory:
        return self._history

    @property
    def metrics(self) -> ClusterMetrics:
        return self._metrics

    @property
    def event_bridge(self) -> DistributedEventBridge:
        return self._event_bridge

    @property
    def cluster_id(self) -> str:
        return self._cluster_id

    @property
    def node_id(self) -> str:
        return self._node_id

    # ------------------------------------------------------------------
    # IService lifecycle
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "distributed_runtime"

    @property
    def service_id(self) -> str:
        return "distributed_runtime"

    @property
    def service_state(self) -> ServiceState:
        with self._state_lock:
            return self._service_state

    @property
    def service_metadata(self) -> dict[str, Any]:
        return dict(self._service_metadata)

    async def initialize(self) -> None:
        with self._state_lock:
            if self._initialized:
                raise RuntimeError("DistributedRuntime already initialized")
            self._service_state = ServiceState.INITIALIZED

        self._service_metadata["cluster_id"] = self._cluster_id
        self._service_metadata["node_id"] = self._node_id

        with self._state_lock:
            self._initialized = True
            self._service_state = ServiceState.INITIALIZED

    async def start(self) -> None:
        with self._state_lock:
            if not self._initialized:
                raise RuntimeError("DistributedRuntime not initialized")
            self._service_state = ServiceState.STARTING

        if self._node_id:
            local_node = NodeInfo(
                node_id=self._node_id,
                hostname=self._hostname or self._node_id,
                version=self._version,
                state=NodeState.DISCOVERING,
            )
            await self._coordinator.join_cluster(local_node)
            await self._heartbeat.heartbeat(self._node_id)
            self._metrics.increment_joins()
            self._history.record(HistoryEntry(time.time(), "join", self._node_id, "node joined cluster"))
            await self._event_bridge.publish_node_joined(self._node_id, self._cluster_id)

            if self._election.leader == self._node_id:
                self._history.record(HistoryEntry(time.time(), "leader_elected", self._node_id, "elected leader"))

        with self._state_lock:
            self._started = True
            self._service_state = ServiceState.RUNNING

    async def stop(self) -> None:
        with self._state_lock:
            if self._stopped:
                return
            self._service_state = ServiceState.STOPPING

        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()

        if self._node_id:
            self._registry.update_state(self._node_id, NodeState.OFFLINE)
            await self._event_bridge.publish_node_left(self._node_id, self._cluster_id)

        with self._state_lock:
            self._stopped = True
            self._service_state = ServiceState.STOPPED

    async def health_check(self) -> ServiceHealth:
        msg = ""
        with self._state_lock:
            state_str = self._service_state.value

        alive = self._heartbeat.is_alive(self._node_id) if self._node_id else True

        if not alive:
            msg = "heartbeat timeout"

        return ServiceHealth(
            healthy=alive and self._service_state == ServiceState.RUNNING,
            state=self._service_state,
            message=msg,
        )
