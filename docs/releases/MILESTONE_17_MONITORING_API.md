# Milestone 17 — Monitoring API & Runtime Streaming

**Version:** 0.1.0

**Date:** July 2026

**Status:** Complete

---

## Summary

Phase Seven of Atlas. Builds the **Monitoring API** — the backend monitoring interface layer. Exposes monitoring information to future clients while keeping the architecture completely backend-only. No GUI, no web frontend, no browser code, no AI, no business logic.

---

## Deliverables

### 11 Components in `src/atlas_core/monitor_api/__init__.py`

| # | Component | Description |
|---|-----------|-------------|
| 1 | **StreamingChannel** | Enum: HEALTH, METRICS, SNAPSHOTS, ALERTS, SYSTEM |
| 2 | **StreamingEvent** | Frozen dataclass: channel, event_type, payload, timestamp |
| 3 | **Subscription** | Frozen dataclass with filters: categories, services, severities, metrics, snapshot_types |
| 4 | **SubscriptionManager** | Subscribe/unsubscribe/list/count/matching subscribers, thread-safe |
| 5 | **StreamingManager** | Async subscribe/unsubscribe/publish APIs for future transports asyncio.Queue delivery |
| 6 | **HealthEndpoint** | System health, service health (filtered), health summary |
| 7 | **MetricsEndpoint** | Performance metrics, monitor metrics, event throughput, service latency, queue sizes |
| 8 | **SnapshotEndpoint** | Latest snapshot, historical snapshots, take snapshot |
| 9 | **AlertEndpoint** | Active alerts, alert rules, alert history |
| 10 | **HistoryEndpoint** | Persisted history via PersistenceManager (snapshots, health, alerts, time range queries) |
| 11 | **APIEventBridge** | Event publishing for HEALTH_REQUESTED, METRICS_REQUESTED, SNAPSHOT_REQUESTED, etc. |

### Supporting Components

| # | Component | Description |
|---|-----------|-------------|
| 12 | **MetricsAggregator** | Track subscriptions, messages published/dropped, history reads/writes, stream latency |
| 13 | **MonitoringAPI** | Main IService: owns all endpoints, streaming, history, metrics, event bridge |

### Architecture Compliance

- ✓ No GUI, no web frontend, no browser code
- ✓ No AI provider communication
- ✓ No command execution
- ✓ No business logic
- ✓ Read-only — never modifies monitored services
- ✓ Uses PersistenceManager — no direct SQLite access
- ✓ Event Bus communication only
- ✓ IService lifecycle with super() calls
- ✓ Full typing
- ✓ Frozen dataclasses (StreamingEvent, Subscription)
- ✓ RLock for thread safety in SubscriptionManager, StreamingManager, MetricsAggregator
- ✓ No circular imports

---

## Data Flow

```
MonitoringAPI (IService)
├── HealthEndpoint → SystemMonitor.health()
├── MetricsEndpoint → SystemMonitor.performance()
├── SnapshotEndpoint → SystemMonitor.snapshot()
├── AlertEndpoint → SystemMonitor.alert_manager
├── HistoryEndpoint → PersistenceManager (monitor_snapshots, monitor_health, monitor_alerts)
├── SubscriptionManager
│   └── Subscription( filters: channel, services, severities, metrics, snapshot_types )
├── StreamingManager
│   ├── subscribe() → asyncio.Queue[StreamingEvent]
│   ├── unsubscribe()
│   └── publish() → deliver to matching subscribers
├── MetricsAggregator → subscription/message/history/latency tracking
├── APIEventBridge → EventBus (EventCategory.MONITOR)
└── SystemMonitor (dependency injection — no private access)
```

---

## Streaming Architecture

```
Client code          StreamingManager          SubscriptionManager
    │                      │                         │
    │──subscribe(id,ch)───>│──subscribe(sub)────────>│
    │<──asyncio.Queue───── │                         │
    │                      │                         │
    │──publish(event)─────>│                         │
    │                      │──matching_subscribers───>│
    │                      │<──[s1, s2]───────────────│
    │                      │──put_nowait(queue)──>s1  │
    │                      │──put_nowait(queue)──>s2  │
    │<──delivered: 2────── │                         │
    │                      │                         │
    │──unsubscribe(id)───> │──unsubscribe(id)───────>│
```

---

## Persistence Collections

| Collection | Content | Key Format |
|------------|---------|------------|
| `monitor_snapshots` | ResourceSnapshot data | timestamp float |
| `monitor_health` | Health report dict | datetime timestamp |
| `monitor_alerts` | Alert data (name, severity, status) | name_timestamp |

---

## Test Results

```
1584 passed in 20.33s
Coverage: 95% monitor_api module
  monitor_api        95%
```

New tests: 94 monitor_api tests covering all components, endpoints, streaming, subscriptions, persistence integration, and event publishing.

---

## Files Created/Modified

| File | Lines | Action |
|------|-------|--------|
| `src/atlas_core/monitor_api/__init__.py` | 732 | Created — all 11+ components |
| `src/atlas_core/interfaces/events.py` | 50 | Modified — added EventCategory.MONITOR_API |
| `src/atlas_core/kernel/__init__.py` | 305 | Modified — MonitoringAPI registration |
| `tests/test_monitor_api.py` | 775 | Created — 94 tests |
| `tests/test_monitor.py` | 1068 | Modified — updated kernel service count (9→10) |
| `tests/test_kernel.py` | 140 | Modified — updated service counts (9→10, 10→11) |
| `docs/releases/MILESTONE_17_MONITORING_API.md` | — | Created |

---

## Known Issues

1. StreamingManager uses unbounded asyncio.Queue — memory could grow if subscribers are slow
2. HistoryEndpoint accesses `self._persistence._storage` directly (private attribute) for `list_keys()`
3. No backpressure mechanism for streaming subscribers
4. Subscription filters are applied at publish time, not subscribe time
5. No authentication or authorization for subscriptions
6. History queries filter in-memory after loading all keys (inefficient for large datasets)

---

## Technical Debt

- HistoryEndpoint could use a dedicated Repository from PersistenceManager instead of direct storage access
- StreamingManager lacks heartbeat/timeout mechanisms for stale subscribers
- No batching or compression for stream events
- MetricsAggregator latencies are cumulative averages — no windowing
- Subscription filters are basic (exact match only, no glob/regex)
- No WebSocket or SSE transport implementation (intentionally deferred)

---

## Commit

```
feat(monitor-api): complete milestone 17 — monitoring API & runtime streaming
```

---

## Next Steps

- Milestone 18: System Dashboard (frontend)
- Wire WebSocket transport for StreamingManager
- Add authentication for monitoring API access
- Implement efficient paginated history queries
- Add real-time dashboard visualization

---

*End of Milestone 17 Report*
