# Milestone 20: Workflow Engine

**Date:** 2026-07-23

## Summary

The Workflow Engine coordinates multi-step business workflows across Missions, Agents, Connectors, Notifications, Persistence, and Monitoring. It does NOT execute OS commands, communicate with AI providers, or contain business logic — it only orchestrates existing services.

## Components

### Core Types (`workflow/__init__.py`)
- **WorkflowState** — 9 states: CREATED, VALIDATING, READY, RUNNING, WAITING, PAUSED, FAILED, COMPLETED, CANCELLED
- **WorkflowStep** — frozen dataclass: step_id, name, action, dependencies, connector, timeout, retry_count, payload, metadata
- **Workflow** — frozen dataclass: workflow_id, name, description, steps, state, created_at, metadata
- **ValidationResult** — valid flag with errors and warnings lists

### Infrastructure
- **WorkflowDefinition** — reusable workflow registry with register, unregister, get, list, clone (generates new IDs)
- **WorkflowValidator** — validates duplicate IDs, missing dependencies, circular dependencies, invalid state transitions, missing connectors; returns `ValidationResult` (no exceptions for normal validation)
- **WorkflowScheduler** — priority queue with enqueue, dequeue, pause, resume, cancel; supports Priority.CRITICAL/HIGH/NORMAL/LOW ordering
- **WorkflowExecutor** — orchestrates step execution through ConnectorManager, MissionControl, NotificationService via public interfaces only; retry logic with configurable attempt count and backoff
- **WorkflowHistory** — ring buffer (default 1000 entries) storing started, completed, failed, cancelled, paused, resumed events; supports per-workflow filtering and clearing
- **WorkflowMetrics** — tracks created, completed, failed, cancelled, average runtime, active workflows, step execution count, retry count
- **WorkflowEventBridge** — publishes 11 event types: WORKFLOW_CREATED, STARTED, PAUSED, RESUMED, COMPLETED, FAILED, CANCELLED, STEP_STARTED, COMPLETED, FAILED

### WorkflowEngine (IService)
- Full IService lifecycle (create → initialize → start → stop)
- Internal async worker loop processes queued workflows
- Owns validator, scheduler, executor, history, metrics, definitions, event bridge
- Methods: create_workflow, register_definition, execute, pause, resume, cancel, validate, history, metrics
- Registers as `workflow_engine` in kernel (service #13)
- Exposed as `kernel.workflow_engine`

## Data Flow

```
WorkflowEngine
  → WorkflowValidator  (validate structure)
  → WorkflowScheduler  (priority queue)
  → WorkflowExecutor   (orchestrate steps)
    → ConnectorManager (via public interface)
    → MissionControl   (via public interface)
    → NotificationService (via public interface)
  → WorkflowEventBridge (publish lifecycle events)
  → WorkflowHistory    (record history)
  → WorkflowMetrics    (track metrics)
```

## Files Changed

- `src/atlas_core/workflow/__init__.py` — new file, ~900 lines
- `src/atlas_core/kernel/__init__.py` — imports WorkflowEngine, registers as service #13, exposes `workflow_engine` property
- `tests/test_workflow.py` — 136 tests, 97% coverage
- `tests/test_kernel.py` — boot count 13, health count 14
- `tests/test_monitor.py` — `kernel.registry.count` updated to 13
- `tests/test_monitor_api.py` — `kernel.registry.count` updated to 13
- `tests/test_plugins.py` — `kernel.registry.count` updated to 13
- `tests/test_connectors.py` — `kernel.registry.count` updated to 13

## Test Results

- **Total:** 1945 tests passing (up from 1809)
- **Workflow coverage:** 97% (502/516 lines)
- **136 workflow tests** covering: immutability, validator, dependency graphs, scheduler, executor, history, metrics, event bridge, kernel registration, edge cases, thread safety, failure propagation, retry logic, priority ordering, workflow cancellation, pausing, resuming
- No regressions

## Architecture Compliance

- No AI provider communication ✓
- No browser logic ✓
- No OS execution ✓
- No direct SQLite access ✓
- No EventBus bypass ✓
- No private member access ✓
- IService lifecycle ✓
- Frozen dataclasses ✓ (Workflow, WorkflowStep)
- Full typing ✓
- Thread-safe collections ✓
- No circular imports ✓
- Public interfaces only ✓
- All communication through existing Atlas services ✓
- No business logic — orchestrates only ✓

## Known Issues / Technical Debt

- 14 defensive/unreachable lines not covered (edge case safety checks, worker loop exception handlers, fallback returns)
- Linear step processor handles simple dependency chains but not complex DAG scheduling (steps are visited in order; skipped dependencies may cause workflow to fail)
- Worker loop polls with 100ms sleep when queue is empty (acceptable for current scale)

## Commit

`feat(workflow): complete milestone 20 — workflow engine`

## Next Steps

Stop and wait for Chief Software Architect approval before beginning Milestone 21.
