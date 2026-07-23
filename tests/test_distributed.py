"""Comprehensive tests for the Distributed Runtime."""
from __future__ import annotations

import asyncio
import time
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Optional

import pytest

from atlas_core.distributed import (
    ClusterCoordinator,
    ClusterHistory,
    ClusterInfo,
    ClusterMetrics,
    DistributedEventBridge,
    DistributedRuntime,
    DistributedScheduler,
    HeartbeatManager,
    HistoryEntry,
    LeaderElection,
    NodeHealth,
    NodeInfo,
    NodeRegistry,
    NodeState,
    ReferenceTransport,
    Transport,
)
from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory
from atlas_core.kernel import AtlasKernel


# ------------------------------------------------------------------
# Helper fixtures
# ------------------------------------------------------------------

@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def kernel(tmp_path: Path) -> AtlasKernel:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "default.yaml").write_text(
        "app_name: TestDistributed\n"
        "version: 9.9.9\n"
        "log_level: DEBUG\n"
        "log_dir: '" + str(tmp_path / "logs").replace("\\", "\\\\") + "'\n"
    )
    return AtlasKernel(config_dir)


# ======================================================================
# TestNodeState
# ======================================================================

class TestNodeState:
    def test_values(self) -> None:
        assert NodeState.UNKNOWN.value == "unknown"
        assert NodeState.DISCOVERING.value == "discovering"
        assert NodeState.ONLINE.value == "online"
        assert NodeState.OFFLINE.value == "offline"
        assert NodeState.UNREACHABLE.value == "unreachable"
        assert NodeState.LEADER.value == "leader"
        assert NodeState.FOLLOWER.value == "follower"

    def test_all_members(self) -> None:
        expected = {
            "UNKNOWN", "DISCOVERING", "ONLINE", "OFFLINE",
            "UNREACHABLE", "LEADER", "FOLLOWER",
        }
        assert {m.name for m in NodeState} == expected


# ======================================================================
# TestNodeInfo
# ======================================================================

class TestNodeInfo:
    def test_create(self) -> None:
        n = NodeInfo(node_id="n1", hostname="host1", version="1.0")
        assert n.node_id == "n1"
        assert n.hostname == "host1"
        assert n.version == "1.0"
        assert n.state == NodeState.UNKNOWN
        assert n.capabilities == ()
        assert n.metadata == {}

    def test_with_all_fields(self) -> None:
        n = NodeInfo(
            node_id="n1",
            hostname="host1",
            version="1.0",
            state=NodeState.ONLINE,
            capabilities=("workflow", "compute"),
            metadata={"region": "us-east"},
        )
        assert n.state == NodeState.ONLINE
        assert "workflow" in n.capabilities
        assert n.metadata["region"] == "us-east"

    def test_frozen(self) -> None:
        n = NodeInfo(node_id="n1", hostname="h", version="1")
        with pytest.raises(FrozenInstanceError):
            n.node_id = "n2"

    def test_equality(self) -> None:
        a = NodeInfo(node_id="n1", hostname="h", version="1")
        b = NodeInfo(node_id="n1", hostname="h", version="1")
        assert a == b

    def test_string_representation(self) -> None:
        n = NodeInfo(node_id="n1", hostname="h", version="1")
        assert "n1" in repr(n)


# ======================================================================
# TestClusterInfo
# ======================================================================

class TestClusterInfo:
    def test_create(self) -> None:
        c = ClusterInfo(cluster_id="c1", leader_id="n1")
        assert c.cluster_id == "c1"
        assert c.leader_id == "n1"
        assert c.members == ()
        assert c.created_at is not None
        assert c.metadata == {}

    def test_with_members(self) -> None:
        members = (NodeInfo(node_id="n1", hostname="h", version="1"),)
        c = ClusterInfo(cluster_id="c1", leader_id="n1", members=members)
        assert len(c.members) == 1

    def test_frozen(self) -> None:
        c = ClusterInfo(cluster_id="c1", leader_id="n1")
        with pytest.raises(FrozenInstanceError):
            c.cluster_id = "c2"


# ======================================================================
# TestNodeHealth
# ======================================================================

class TestNodeHealth:
    def test_defaults(self) -> None:
        h = NodeHealth()
        assert h.latency == 0.0
        assert h.heartbeat_age == 0.0
        assert h.healthy is True
        assert h.last_error == ""

    def test_custom(self) -> None:
        h = NodeHealth(latency=1.5, heartbeat_age=2.0, healthy=False, last_error="timeout")
        assert h.latency == 1.5
        assert h.heartbeat_age == 2.0
        assert h.healthy is False
        assert h.last_error == "timeout"

    def test_frozen(self) -> None:
        h = NodeHealth()
        with pytest.raises(FrozenInstanceError):
            h.latency = 5.0


# ======================================================================
# TestNodeRegistry
# ======================================================================

class TestNodeRegistry:
    @pytest.fixture
    def registry(self) -> NodeRegistry:
        return NodeRegistry()

    def test_register_and_lookup(self, registry: NodeRegistry) -> None:
        n = NodeInfo(node_id="n1", hostname="h1", version="1")
        registry.register_node(n)
        assert registry.lookup("n1") == n

    def test_register_duplicate_overwrites(self, registry: NodeRegistry) -> None:
        n1 = NodeInfo(node_id="n1", hostname="h1", version="1")
        n2 = NodeInfo(node_id="n1", hostname="h2", version="2")
        registry.register_node(n1)
        registry.register_node(n2)
        assert registry.lookup("n1").hostname == "h2"

    def test_lookup_missing(self, registry: NodeRegistry) -> None:
        assert registry.lookup("nonexistent") is None

    def test_remove_node(self, registry: NodeRegistry) -> None:
        n = NodeInfo(node_id="n1", hostname="h1", version="1")
        registry.register_node(n)
        removed = registry.remove_node("n1")
        assert removed is not None
        assert removed.node_id == "n1"
        assert registry.lookup("n1") is None

    def test_remove_missing(self, registry: NodeRegistry) -> None:
        assert registry.remove_node("nonexistent") is None

    def test_list_empty(self, registry: NodeRegistry) -> None:
        assert registry.list() == ()

    def test_list(self, registry: NodeRegistry) -> None:
        n1 = NodeInfo(node_id="n1", hostname="h1", version="1")
        n2 = NodeInfo(node_id="n2", hostname="h2", version="2")
        registry.register_node(n1)
        registry.register_node(n2)
        nodes = registry.list()
        assert len(nodes) == 2

    def test_health_default(self, registry: NodeRegistry) -> None:
        n = NodeInfo(node_id="n1", hostname="h1", version="1")
        registry.register_node(n)
        h = registry.health("n1")
        assert h is not None
        assert h.healthy is True

    def test_health_missing(self, registry: NodeRegistry) -> None:
        assert registry.health("nonexistent") is None

    def test_update_health(self, registry: NodeRegistry) -> None:
        n = NodeInfo(node_id="n1", hostname="h1", version="1")
        registry.register_node(n)
        h = NodeHealth(latency=0.5, healthy=True)
        registry.update_health("n1", h)
        assert registry.health("n1") == h

    def test_update_health_unknown_node(self, registry: NodeRegistry) -> None:
        h = NodeHealth()
        registry.update_health("unknown", h)
        assert registry.health("unknown") == h

    def test_update_state(self, registry: NodeRegistry) -> None:
        n = NodeInfo(node_id="n1", hostname="h1", version="1")
        registry.register_node(n)
        registry.update_state("n1", NodeState.ONLINE)
        assert registry.lookup("n1").state == NodeState.ONLINE

    def test_update_state_unknown_node(self, registry: NodeRegistry) -> None:
        registry.update_state("unknown", NodeState.ONLINE)
        assert registry.lookup("unknown") is None

    def test_count(self, registry: NodeRegistry) -> None:
        assert registry.count == 0
        registry.register_node(NodeInfo(node_id="n1", hostname="h", version="1"))
        assert registry.count == 1
        registry.register_node(NodeInfo(node_id="n2", hostname="h", version="1"))
        assert registry.count == 2
        registry.remove_node("n1")
        assert registry.count == 1

    def test_remove_node_clears_health(self, registry: NodeRegistry) -> None:
        n = NodeInfo(node_id="n1", hostname="h1", version="1")
        registry.register_node(n)
        registry.update_health("n1", NodeHealth(latency=1.0, healthy=False))
        registry.remove_node("n1")
        assert registry.health("n1") is None


# ======================================================================
# TestTransport (ABC)
# ======================================================================

class TestTransport:
    def test_abstract_methods(self) -> None:
        missing = {
            "connect", "disconnect", "send", "broadcast",
            "receive", "health_check",
        }
        for method in missing:
            assert hasattr(Transport, method)


# ======================================================================
# TestReferenceTransport
# ======================================================================

class TestReferenceTransport:
    @pytest.fixture
    def transport(self) -> ReferenceTransport:
        return ReferenceTransport()

    async def test_connect(self, transport: ReferenceTransport) -> None:
        result = await transport.connect("n1", "addr1")
        assert result is True

    async def test_disconnect(self, transport: ReferenceTransport) -> None:
        await transport.connect("n1", "addr1")
        result = await transport.disconnect("n1")
        assert result is True

    async def test_disconnect_not_connected(self, transport: ReferenceTransport) -> None:
        result = await transport.disconnect("nonexistent")
        assert result is True

    async def test_send(self, transport: ReferenceTransport) -> None:
        await transport.connect("n1", "addr1")
        result = await transport.send("n1", {"type": "ping"})
        assert result is True

    async def test_send_to_nonexistent(self, transport: ReferenceTransport) -> None:
        result = await transport.send("nonexistent", {"type": "ping"})
        assert result is False

    async def test_broadcast(self, transport: ReferenceTransport) -> None:
        await transport.connect("n1", "addr1")
        await transport.connect("n2", "addr2")
        count = await transport.broadcast({"type": "ping"})
        assert count == 2

    async def test_broadcast_no_connections(self, transport: ReferenceTransport) -> None:
        count = await transport.broadcast({"type": "ping"})
        assert count == 0

    async def test_receive(self, transport: ReferenceTransport) -> None:
        await transport.connect("n1", "addr1")
        await transport.connect("n2", "addr2")
        await transport.send("n1", {"type": "msg1"})
        await transport.send("n2", {"type": "msg2"})
        messages = await transport.receive()
        assert len(messages) == 2

    async def test_receive_clears_queue(self, transport: ReferenceTransport) -> None:
        await transport.connect("n1", "addr1")
        await transport.send("n1", {"type": "msg"})
        await transport.receive()
        messages = await transport.receive()
        assert len(messages) == 0

    async def test_health_check_healthy(self, transport: ReferenceTransport) -> None:
        await transport.connect("n1", "addr1")
        health = await transport.health_check("n1")
        assert health.healthy is True

    async def test_health_check_unhealthy(self, transport: ReferenceTransport) -> None:
        health = await transport.health_check("nonexistent")
        assert health.healthy is False
        assert health.last_error == "not connected"

    async def test_connection_count(self, transport: ReferenceTransport) -> None:
        assert transport.connection_count == 0
        await transport.connect("n1", "addr1")
        assert transport.connection_count == 1
        await transport.disconnect("n1")
        assert transport.connection_count == 0


# ======================================================================
# TestLeaderElection
# ======================================================================

class TestLeaderElection:
    @pytest.fixture
    def election(self) -> LeaderElection:
        return LeaderElection()

    def test_elect_lowest_wins(self, election: LeaderElection) -> None:
        winner = election.elect(["n3", "n1", "n2"])
        assert winner == "n1"
        assert election.leader == "n1"

    def test_elect_increments_term(self, election: LeaderElection) -> None:
        election.elect(["n1", "n2"])
        assert election.term == 1
        election.elect(["n1", "n2"])
        assert election.term == 2

    def test_elect_empty_candidates(self, election: LeaderElection) -> None:
        winner = election.elect([])
        assert winner == ""

    def test_re_elect(self, election: LeaderElection) -> None:
        election.elect(["n1", "n2", "n3"])
        assert election.leader == "n1"
        winner = election.re_elect(["n2", "n3"], exclude=["n2"])
        assert winner == "n3"

    def test_re_elect_no_exclude(self, election: LeaderElection) -> None:
        election.elect(["n3", "n1", "n2"])
        winner = election.re_elect(["n2", "n3"])
        assert winner == "n2"

    def test_re_elect_all_excluded(self, election: LeaderElection) -> None:
        winner = election.re_elect(["n1"], exclude=["n1"])
        assert winner == ""

    def test_step_down(self, election: LeaderElection) -> None:
        election.elect(["n1", "n2"])
        assert election.leader == "n1"
        election.step_down()
        assert election.leader == ""

    def test_current_leader_property(self, election: LeaderElection) -> None:
        election.elect(["n1"])
        assert election.current_leader == "n1"

    def test_term_initial(self, election: LeaderElection) -> None:
        assert election.term == 0

    def test_voted_for_after_election(self, election: LeaderElection) -> None:
        election.elect(["n2", "n1"])
        assert election._voted_for == "n1"


# ======================================================================
# TestClusterCoordinator
# ======================================================================

class TestClusterCoordinator:
    @pytest.fixture
    def coordinator(self) -> ClusterCoordinator:
        registry = NodeRegistry()
        transport = ReferenceTransport()
        election = LeaderElection()
        return ClusterCoordinator(registry, transport, election, cluster_id="test_cluster")

    async def test_join_cluster(self, coordinator: ClusterCoordinator) -> None:
        node = NodeInfo(node_id="n1", hostname="h1", version="1")
        result = await coordinator.join_cluster(node)
        assert result is True
        assert coordinator.local_node_id() == "n1"
        assert coordinator.leader() == "n1"
        assert len(coordinator.members()) == 1

    async def test_join_multiple_nodes(self, coordinator: ClusterCoordinator) -> None:
        n1 = NodeInfo(node_id="n1", hostname="h1", version="1")
        n2 = NodeInfo(node_id="n2", hostname="h2", version="1")
        await coordinator.join_cluster(n1)
        await coordinator.join_cluster(n2)
        assert coordinator.leader() == "n1"
        assert len(coordinator.members()) == 2

    async def test_leave_cluster(self, coordinator: ClusterCoordinator) -> None:
        n1 = NodeInfo(node_id="n1", hostname="h1", version="1")
        n2 = NodeInfo(node_id="n2", hostname="h2", version="1")
        await coordinator.join_cluster(n1)
        await coordinator.join_cluster(n2)
        result = await coordinator.leave_cluster("n2")
        assert result is True
        assert len(coordinator.members()) == 1

    async def test_leave_leader_triggers_re_election(self, coordinator: ClusterCoordinator) -> None:
        n1 = NodeInfo(node_id="n1", hostname="h1", version="1")
        n2 = NodeInfo(node_id="n2", hostname="h2", version="1")
        await coordinator.join_cluster(n1)
        await coordinator.join_cluster(n2)
        assert coordinator.leader() == "n1"
        await coordinator.leave_cluster("n1")
        assert coordinator.leader() == "n2"

    async def test_leave_leader_last_node(self, coordinator: ClusterCoordinator) -> None:
        n1 = NodeInfo(node_id="n1", hostname="h1", version="1")
        await coordinator.join_cluster(n1)
        await coordinator.leave_cluster("n1")
        assert coordinator.leader() == ""

    async def test_cluster_id(self, coordinator: ClusterCoordinator) -> None:
        assert coordinator.cluster_id == "test_cluster"

    async def test_local_node_id_empty_initially(self, coordinator: ClusterCoordinator) -> None:
        assert coordinator.local_node_id() == ""

    async def test_leader_after_join(self, coordinator: ClusterCoordinator) -> None:
        n1 = NodeInfo(node_id="n2", hostname="h1", version="1")
        n2 = NodeInfo(node_id="n1", hostname="h2", version="1")
        await coordinator.join_cluster(n1)
        await coordinator.join_cluster(n2)
        assert coordinator.leader() == "n1"


# ======================================================================
# TestHeartbeatManager
# ======================================================================

class TestHeartbeatManager:
    @pytest.fixture
    def hb_manager(self) -> HeartbeatManager:
        registry = NodeRegistry()
        return HeartbeatManager(registry, timeout=0.1)

    async def test_heartbeat(self, hb_manager: HeartbeatManager) -> None:
        await hb_manager.heartbeat("n1")
        assert hb_manager.get_heartbeat_age("n1") < 1.0

    async def test_update(self, hb_manager: HeartbeatManager) -> None:
        hb_manager.update("n1")
        assert hb_manager.get_heartbeat_age("n1") < 1.0

    async def test_is_alive(self, hb_manager: HeartbeatManager) -> None:
        await hb_manager.heartbeat("n1")
        assert hb_manager.is_alive("n1") is True

    async def test_is_alive_timeout(self, hb_manager: HeartbeatManager) -> None:
        # Set very short timeout; don't send heartbeat
        hb_manager.timeout = 0.001
        hb_manager.update("n1")
        await asyncio.sleep(0.1)
        assert hb_manager.is_alive("n1") is False

    async def test_check_timeouts_empty(self, hb_manager: HeartbeatManager) -> None:
        result = hb_manager.check_timeouts()
        assert result == []

    async def test_check_timeouts_detects_dead_nodes(self, hb_manager: HeartbeatManager) -> None:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(node_id="n1", hostname="h", version="1"))
        hb = HeartbeatManager(registry, timeout=0.001)
        hb.update("n1")
        await asyncio.sleep(0.1)
        timed_out = hb.check_timeouts()
        assert "n1" in timed_out

    async def test_heartbeat_age_infinite_for_unknown(self, hb_manager: HeartbeatManager) -> None:
        age = hb_manager.get_heartbeat_age("nonexistent")
        assert age == float("inf")

    async def test_timeout_property(self, hb_manager: HeartbeatManager) -> None:
        assert hb_manager.timeout == 0.1
        hb_manager.timeout = 1.0
        assert hb_manager.timeout == 1.0

    async def test_active_count(self, hb_manager: HeartbeatManager) -> None:
        assert hb_manager.active_count == 0
        hb_manager.update("n1")
        assert hb_manager.active_count == 1
        hb_manager.update("n2")
        assert hb_manager.active_count == 2


# ======================================================================
# TestDistributedScheduler
# ======================================================================

class TestDistributedScheduler:
    @pytest.fixture
    def scheduler(self) -> DistributedScheduler:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(
            node_id="n1", hostname="h1", version="1", state=NodeState.ONLINE,
        ))
        registry.register_node(NodeInfo(
            node_id="n2", hostname="h2", version="1", state=NodeState.ONLINE,
        ))
        return DistributedScheduler(registry)

    def test_assign_round_robin(self, scheduler: DistributedScheduler) -> None:
        a1 = scheduler.assign("wf1")
        a2 = scheduler.assign("wf2")
        a3 = scheduler.assign("wf3")
        assert a1 is not None
        assert a2 is not None
        assert a3 is not None
        # Round-robin across 2 nodes should alternate
        assert a1 != a2 or a2 != a3

    def test_assign_to_node(self, scheduler: DistributedScheduler) -> None:
        result = scheduler.assign_to_node("wf1", "n1")
        assert result is True
        assert scheduler.get_assignment("wf1") == "n1"

    def test_assign_to_nonexistent_node(self, scheduler: DistributedScheduler) -> None:
        result = scheduler.assign_to_node("wf1", "nonexistent")
        assert result is False

    def test_get_assignment_none(self, scheduler: DistributedScheduler) -> None:
        assert scheduler.get_assignment("nonexistent") is None

    def test_unassign(self, scheduler: DistributedScheduler) -> None:
        scheduler.assign_to_node("wf1", "n1")
        node = scheduler.unassign("wf1")
        assert node == "n1"
        assert scheduler.get_assignment("wf1") is None

    def test_unassign_none(self, scheduler: DistributedScheduler) -> None:
        assert scheduler.unassign("nonexistent") is None

    def test_assignments(self, scheduler: DistributedScheduler) -> None:
        scheduler.assign_to_node("wf1", "n1")
        scheduler.assign_to_node("wf2", "n2")
        assignments = scheduler.assignments()
        assert assignments == {"wf1": "n1", "wf2": "n2"}

    def test_clear(self, scheduler: DistributedScheduler) -> None:
        scheduler.assign_to_node("wf1", "n1")
        scheduler.clear()
        assert scheduler.assignments() == {}

    def test_assign_no_online_nodes(self) -> None:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(
            node_id="n1", hostname="h1", version="1", state=NodeState.OFFLINE,
        ))
        s = DistributedScheduler(registry)
        result = s.assign("wf1")
        assert result is None

    def test_assign_includes_leaders_and_followers(self) -> None:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(
            node_id="n1", hostname="h1", version="1", state=NodeState.LEADER,
        ))
        registry.register_node(NodeInfo(
            node_id="n2", hostname="h2", version="1", state=NodeState.FOLLOWER,
        ))
        s = DistributedScheduler(registry)
        assert s.assign("wf1") is not None

    def test_assign_empty_registry(self) -> None:
        s = DistributedScheduler(NodeRegistry())
        assert s.assign("wf1") is None


# ======================================================================
# TestHistoryEntry
# ======================================================================

class TestHistoryEntry:
    def test_create(self) -> None:
        t = time.time()
        e = HistoryEntry(t, "join", "n1", "detail")
        assert e.timestamp == t
        assert e.event_type == "join"
        assert e.node_id == "n1"
        assert e.detail == "detail"

    def test_frozen(self) -> None:
        e = HistoryEntry(time.time(), "join", "n1")
        with pytest.raises(FrozenInstanceError):
            e.event_type = "leave"


# ======================================================================
# TestClusterHistory
# ======================================================================

class TestClusterHistory:
    @pytest.fixture
    def history(self) -> ClusterHistory:
        return ClusterHistory(max_size=10)

    def test_record_and_size(self, history: ClusterHistory) -> None:
        assert history.size == 0
        history.record(HistoryEntry(time.time(), "join", "n1"))
        assert history.size == 1

    def test_recent(self, history: ClusterHistory) -> None:
        history.record(HistoryEntry(time.time(), "join", "n1"))
        history.record(HistoryEntry(time.time(), "leave", "n2"))
        recent = history.recent(1)
        assert len(recent) == 1
        assert recent[0].event_type == "leave"

    def test_recent_all(self, history: ClusterHistory) -> None:
        history.record(HistoryEntry(time.time(), "join", "n1"))
        recent = history.recent(100)
        assert len(recent) == 1

    def test_search_by_type(self, history: ClusterHistory) -> None:
        history.record(HistoryEntry(time.time(), "join", "n1"))
        history.record(HistoryEntry(time.time(), "leave", "n2"))
        results = history.search(event_type="join")
        assert len(results) == 1
        assert results[0].node_id == "n1"

    def test_search_by_node(self, history: ClusterHistory) -> None:
        history.record(HistoryEntry(time.time(), "join", "n1"))
        history.record(HistoryEntry(time.time(), "leave", "n1"))
        history.record(HistoryEntry(time.time(), "join", "n2"))
        results = history.search(node_id="n1")
        assert len(results) == 2

    def test_search_by_both(self, history: ClusterHistory) -> None:
        history.record(HistoryEntry(time.time(), "join", "n1"))
        history.record(HistoryEntry(time.time(), "leave", "n1"))
        results = history.search(event_type="join", node_id="n1")
        assert len(results) == 1

    def test_search_empty(self, history: ClusterHistory) -> None:
        assert history.search() == []

    def test_clear(self, history: ClusterHistory) -> None:
        history.record(HistoryEntry(time.time(), "join", "n1"))
        history.clear()
        assert history.size == 0

    def test_ring_buffer_overflow(self, history: ClusterHistory) -> None:
        for i in range(20):
            history.record(HistoryEntry(float(i), "join", f"n{i}"))
        assert history.size == 10


# ======================================================================
# TestClusterMetrics
# ======================================================================

class TestClusterMetrics:
    @pytest.fixture
    def metrics(self) -> ClusterMetrics:
        return ClusterMetrics()

    def test_initial_values(self, metrics: ClusterMetrics) -> None:
        s = metrics.snapshot()
        assert all(v == 0 for v in s.values())

    def test_joins(self, metrics: ClusterMetrics) -> None:
        metrics.increment_joins()
        assert metrics.joins == 1

    def test_leaves(self, metrics: ClusterMetrics) -> None:
        metrics.increment_leaves()
        assert metrics.leaves == 1

    def test_heartbeats(self, metrics: ClusterMetrics) -> None:
        metrics.increment_heartbeats()
        assert metrics.heartbeats == 1

    def test_messages_sent(self, metrics: ClusterMetrics) -> None:
        metrics.increment_messages_sent()
        assert metrics.messages_sent == 1

    def test_messages_received(self, metrics: ClusterMetrics) -> None:
        metrics.increment_messages_received()
        assert metrics.messages_received == 1

    def test_elections(self, metrics: ClusterMetrics) -> None:
        metrics.increment_elections()
        assert metrics.elections == 1

    def test_failures(self, metrics: ClusterMetrics) -> None:
        metrics.increment_failures()
        assert metrics.failures == 1

    def test_recoveries(self, metrics: ClusterMetrics) -> None:
        metrics.increment_recoveries()
        assert metrics.recoveries == 1

    def test_snapshot(self, metrics: ClusterMetrics) -> None:
        metrics.increment_joins()
        metrics.increment_leaves()
        s = metrics.snapshot()
        assert s["joins"] == 1
        assert s["leaves"] == 1

    def test_reset(self, metrics: ClusterMetrics) -> None:
        metrics.increment_joins()
        metrics.increment_leaves()
        metrics.reset()
        s = metrics.snapshot()
        assert all(v == 0 for v in s.values())

    def test_multiple_increments(self, metrics: ClusterMetrics) -> None:
        for _ in range(5):
            metrics.increment_joins()
        assert metrics.joins == 5


# ======================================================================
# TestDistributedEventBridge
# ======================================================================

class TestDistributedEventBridge:
    @pytest.fixture
    def bridge(self, event_bus: EventBus) -> DistributedEventBridge:
        return DistributedEventBridge(event_bus)

    async def test_publish_node_joined(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_node_joined("n1", "c1")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "node_joined"

    async def test_publish_node_left(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_node_left("n1", "c1")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "node_left"

    async def test_publish_leader_elected(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_leader_elected("n1", 3)
        assert len(received) == 1
        assert received[0].payload["event_type"] == "leader_elected"
        assert received[0].payload["term"] == 3

    async def test_publish_heartbeat(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_heartbeat("n1")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "heartbeat"

    async def test_publish_message_sent(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_message_sent("src", "tgt", "ping")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "message_sent"
        assert received[0].payload["target"] == "tgt"

    async def test_publish_message_received(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_message_received("tgt", "src", "pong")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "message_received"
        assert received[0].payload["source"] == "src"

    async def test_publish_node_failed(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_node_failed("n1", "crash")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "node_failed"
        assert received[0].payload["error"] == "crash"

    async def test_publish_node_recovered(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_node_recovered("n1")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "node_recovered"

    async def test_event_source(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_node_joined("n1", "c1")
        assert received[0].source == "distributed_runtime"

    async def test_event_category(self, bridge: DistributedEventBridge, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)
        await bridge.publish_node_joined("n1", "c1")
        assert received[0].category == EventCategory.DISTRIBUTED


# ======================================================================
# TestDistributedRuntime
# ======================================================================

class TestDistributedRuntime:
    @pytest.fixture
    def runtime(self, event_bus: EventBus) -> DistributedRuntime:
        return DistributedRuntime(
            event_bus=event_bus,
            cluster_id="test_cluster",
            node_id="n1",
            hostname="host1",
            version="1.0.0",
        )

    def test_service_id(self, runtime: DistributedRuntime) -> None:
        assert runtime.service_id == "distributed_runtime"

    def test_initial_state(self, runtime: DistributedRuntime) -> None:
        assert runtime.service_state == ServiceState.CREATED

    async def test_initialize(self, runtime: DistributedRuntime) -> None:
        await runtime.initialize()
        assert runtime.service_state == ServiceState.INITIALIZED
        assert runtime.service_metadata["cluster_id"] == "test_cluster"
        assert runtime.service_metadata["node_id"] == "n1"

    async def test_initialize_twice_raises(self, runtime: DistributedRuntime) -> None:
        await runtime.initialize()
        with pytest.raises(RuntimeError):
            await runtime.initialize()

    async def test_start_before_init_raises(self, runtime: DistributedRuntime) -> None:
        with pytest.raises(RuntimeError):
            await runtime.start()

    async def test_start(self, runtime: DistributedRuntime) -> None:
        await runtime.initialize()
        await runtime.start()
        assert runtime.service_state == ServiceState.RUNNING
        assert runtime.registry.count == 1
        assert runtime.coordinator.leader() == "n1"

    async def test_stop(self, runtime: DistributedRuntime) -> None:
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()
        assert runtime.service_state == ServiceState.STOPPED

    async def test_stop_twice(self, runtime: DistributedRuntime) -> None:
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()
        await runtime.stop()

    async def test_health_healthy(self, runtime: DistributedRuntime) -> None:
        await runtime.initialize()
        await runtime.start()
        health = await runtime.health_check()
        assert health.healthy is True

    async def test_health_not_started(self, runtime: DistributedRuntime) -> None:
        await runtime.initialize()
        health = await runtime.health_check()
        assert health.healthy is False

    async def test_properties(self, runtime: DistributedRuntime) -> None:
        assert isinstance(runtime.registry, NodeRegistry)
        assert isinstance(runtime.transport, Transport)
        assert isinstance(runtime.coordinator, ClusterCoordinator)
        assert isinstance(runtime.election, LeaderElection)
        assert isinstance(runtime.heartbeat_manager, HeartbeatManager)
        assert isinstance(runtime.scheduler, DistributedScheduler)
        assert isinstance(runtime.history, ClusterHistory)
        assert isinstance(runtime.metrics, ClusterMetrics)
        assert isinstance(runtime.event_bridge, DistributedEventBridge)
        assert runtime.cluster_id == "test_cluster"
        assert runtime.node_id == "n1"

    async def test_lifecycle_produces_events(self, event_bus: EventBus) -> None:
        received: list[Event] = []
        async def handler(e: Event) -> None:
            received.append(e)
        event_bus.subscribe("distributed", handler)

        runtime = DistributedRuntime(
            event_bus=event_bus,
            node_id="n1",
            hostname="host1",
        )
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()

        event_types = {e.payload["event_type"] for e in received}
        assert "node_joined" in event_types
        assert "node_left" in event_types


# ======================================================================
# TestKernelIntegration
# ======================================================================

class TestKernelIntegration:
    async def test_kernel_registers_distributed_runtime(self, kernel: Any) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.registry.count == 16
        from atlas_core.configuration import ConfigurationManager as ConfigManager
        assert isinstance(kernel.configuration_manager, ConfigManager)
        assert kernel.configuration_manager.name == "configuration_manager"

    async def test_kernel_property_before_boot_raises(self, kernel: Any) -> None:
        kernel.initialize()
        with pytest.raises(RuntimeError):
            _ = kernel.distributed_runtime

    async def test_kernel_distributed_healthy(self, kernel: Any) -> None:
        kernel.initialize()
        kernel.boot()
        await kernel.start()
        assert kernel.registry.count == 16
        health = await kernel.distributed_runtime.health_check()
        assert health.healthy is True
        await kernel.stop()


# ======================================================================
# TestThreadSafety
# ======================================================================

class TestThreadSafety:
    async def test_registry_concurrent(self) -> None:
        registry = NodeRegistry()

        async def register(i: int) -> None:
            for _ in range(50):
                registry.register_node(NodeInfo(
                    node_id=f"n{i}", hostname=f"h{i}", version="1",
                ))

        await asyncio.gather(*[register(i) for i in range(10)])
        assert registry.count <= 10

    async def test_history_concurrent(self) -> None:
        history = ClusterHistory(max_size=1000)

        async def record(i: int) -> None:
            for _ in range(50):
                history.record(HistoryEntry(time.time(), "join", f"n{i}"))

        await asyncio.gather(*[record(i) for i in range(10)])
        assert history.size == 500

    async def test_scheduler_concurrent(self) -> None:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(
            node_id="n1", hostname="h1", version="1", state=NodeState.ONLINE,
        ))
        s = DistributedScheduler(registry)

        async def assign(base: int) -> None:
            for j in range(20):
                s.assign(f"wf_{base}_{j}")

        await asyncio.gather(*[assign(i) for i in range(5)])
        assert len(s.assignments()) == 100

    async def test_metrics_concurrent(self) -> None:
        m = ClusterMetrics()

        async def increment() -> None:
            for _ in range(100):
                m.increment_joins()

        await asyncio.gather(*[increment() for _ in range(10)])
        assert m.joins == 1000

    async def test_transport_concurrent(self) -> None:
        t = ReferenceTransport()
        await t.connect("n1", "addr1")
        await t.connect("n2", "addr2")

        async def send_messages() -> None:
            for i in range(50):
                await t.send("n1", {"seq": i})
                await t.broadcast({"seq": i})

        async def receive() -> None:
            for _ in range(25):
                await t.receive()

        await asyncio.gather(send_messages(), receive())

    async def test_heartbeat_concurrent(self) -> None:
        registry = NodeRegistry()
        hb = HeartbeatManager(registry)

        async def beat(i: int) -> None:
            for _ in range(50):
                await hb.heartbeat(f"n{i}")

        await asyncio.gather(*[beat(i) for i in range(5)])
        assert hb.active_count == 5


# ======================================================================
# TestEdgeCases
# ======================================================================

class TestEdgeCases:
    async def test_leader_election_single_node(self) -> None:
        e = LeaderElection()
        winner = e.elect(["n1"])
        assert winner == "n1"
        assert e.term == 1

    async def test_leader_election_same_candidates_reelect(self) -> None:
        e = LeaderElection()
        e.elect(["n2", "n1"])
        e.elect(["n2", "n1"])
        assert e.term == 2

    async def test_node_registry_remove_unknown(self) -> None:
        r = NodeRegistry()
        assert r.remove_node("unknown") is None

    async def test_scheduler_assign_respects_node_state(self) -> None:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(
            node_id="n1", hostname="h1", version="1", state=NodeState.OFFLINE,
        ))
        registry.register_node(NodeInfo(
            node_id="n2", hostname="h2", version="1", state=NodeState.UNREACHABLE,
        ))
        s = DistributedScheduler(registry)
        assert s.assign("wf1") is None

    async def test_heartbeat_check_timeouts_updates_state(self) -> None:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(node_id="n1", hostname="h", version="1"))
        hb = HeartbeatManager(registry, timeout=0.001)
        hb.update("n1")
        await asyncio.sleep(0.1)
        hb.check_timeouts()
        node = registry.lookup("n1")
        assert node is not None
        assert node.state == NodeState.UNREACHABLE

    async def test_history_search_no_match(self) -> None:
        h = ClusterHistory()
        h.record(HistoryEntry(time.time(), "join", "n1"))
        results = h.search(event_type="leave")
        assert results == []

    async def test_transport_send_receive_roundtrip(self) -> None:
        t = ReferenceTransport()
        await t.connect("n1", "addr1")
        await t.send("n1", {"data": "hello"})
        msgs = await t.receive()
        assert len(msgs) == 1
        assert msgs[0][1] == {"data": "hello"}

    async def test_transport_broadcast_to_none(self) -> None:
        t = ReferenceTransport()
        count = await t.broadcast({"data": "test"})
        assert count == 0

    async def test_coordinator_leader_method(self) -> None:
        registry = NodeRegistry()
        transport = ReferenceTransport()
        election = LeaderElection()
        c = ClusterCoordinator(registry, transport, election)
        assert c.leader() == ""

    async def test_runtime_health_after_stop(self, event_bus: EventBus) -> None:
        runtime = DistributedRuntime(event_bus=event_bus, node_id="n1", hostname="h")
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()
        health = await runtime.health_check()
        assert health.healthy is False

    async def test_heartbeat_concurrent_check_timeouts(self) -> None:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(node_id="n1", hostname="h", version="1"))
        hb = HeartbeatManager(registry, timeout=0.001)
        hb.update("n1")
        await asyncio.sleep(0.1)
        async def check() -> None:
            for _ in range(10):
                hb.check_timeouts()
        await asyncio.gather(check(), check())

    async def test_metrics_snapshot_isolated(self) -> None:
        m = ClusterMetrics()
        m.increment_joins()
        s = m.snapshot()
        assert s["joins"] == 1
        m.increment_joins()
        assert m.joins == 2
        assert s["joins"] == 1  # snapshot should be isolated

    async def test_election_step_down_no_leader(self) -> None:
        e = LeaderElection()
        e.step_down()
        assert e.leader == ""

    async def test_runtime_stop_without_start(self, event_bus: EventBus) -> None:
        runtime = DistributedRuntime(event_bus=event_bus, node_id="n1", hostname="h")
        await runtime.initialize()
        await runtime.stop()
        assert runtime.service_state == ServiceState.STOPPED

    async def test_runtime_no_node_id(self, event_bus: EventBus) -> None:
        runtime = DistributedRuntime(event_bus=event_bus)
        await runtime.initialize()
        await runtime.start()
        await runtime.stop()

    async def test_reference_transport_receive_after_disconnect(self) -> None:
        t = ReferenceTransport()
        await t.connect("n1", "addr1")
        await t.disconnect("n1")
        msgs = await t.receive()
        assert msgs == []

    async def test_distributed_scheduler_cursor_reset(self) -> None:
        registry = NodeRegistry()
        registry.register_node(NodeInfo(
            node_id="n1", hostname="h1", version="1", state=NodeState.ONLINE,
        ))
        s = DistributedScheduler(registry)
        s.assign("wf1")
        s.clear()
        assert s.assignments() == {}
        assert s.assign("wf2") == "n1"
