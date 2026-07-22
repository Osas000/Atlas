# Milestone 04 — Atlas Context

**Version:** 0.1.0

**Date:** July 2026

**Status:** Complete

---

## Summary

The Atlas Context system is the complete runtime state of Atlas, represented as a single `AtlasContext` object that every subsystem receives instead of scattered parameter lists. It provides immutable snapshots, change events, validation, and save/restore capability.

---

## Deliverables

- **8 sub-context models** (all frozen pydantic):
  - `UserContext` — identity, goals, skills, preferences, timezone
  - `RuntimeContext` — kernel state, version, uptime, active services
  - `MissionContext` — current mission title, status, priority, deadlines
  - `BrowserContext` — browser connection state (stub)
  - `AIContext` — AI provider/model/temperature (stub)
  - `MemoryContext` — per-layer memory counts with computed `total_count`
  - `SettingsContext` — theme, language, notifications, storage paths
  - `PermissionContext` — runtime permission grants and feature flags
- **AtlasContext** — frozen pydantic composing all eight sub-contexts, `context_id`, `updated_at`
- **ContextSnapshot** — immutable historical snapshot with UUID and label
- **ContextManager (IService)**:
  - `get_context()` — returns current frozen `AtlasContext`
  - `update_<subcontext>(**updates)` — immutable updates via `model_copy`
  - `replace_context()` — full context replacement
  - `snapshot(label)` — creates immutable snapshot (max 50 ring buffer)
  - `restore(snapshot_id)` — restores from historical snapshot
  - `list_snapshots()` — returns all stored snapshots
  - `validate(context)` — integrity validation (user, AI, runtime checks)
  - Event Bus integration — `ContextChanged` events on every mutation
- 49 automated tests with 98% code coverage

---

## Architecture

```
src/atlas_core/context/
└── __init__.py          — All context models + ContextManager
```

### Context Hierarchy

```
AtlasContext (frozen)
├── user: UserContext
├── runtime: RuntimeContext
├── mission: MissionContext
├── browser: BrowserContext
├── ai: AIContext
├── memory: MemoryContext
├── settings: SettingsContext
└── permissions: PermissionContext
```

### ContextManager

```
ContextManager (IService)
├── get_context()          → AtlasContext
├── update_user(...)       → AtlasContext + Event
├── update_runtime(...)    → AtlasContext + Event
├── update_mission(...)    → AtlasContext + Event
├── update_browser(...)    → AtlasContext + Event
├── update_ai(...)         → AtlasContext + Event
├── update_memory(...)     → AtlasContext + Event
├── update_settings(...)   → AtlasContext + Event
├── update_permissions(...)→ AtlasContext + Event
├── replace_context(ctx)   → AtlasContext + Event
├── snapshot(label)        → ContextSnapshot
├── restore(snapshot_id)   → AtlasContext | None
├── list_snapshots()       → list[ContextSnapshot]
└── validate(ctx)          → list[str] (errors)
```

---

## Test Results

```
193 passed in 2.57s
Coverage: 94% overall
  context     98%
  memory      99%
  kernel      97%
  events      97%
  ...
```

---

## Known Issues

1. ContextManager holds state in memory only — no persistent storage for snapshots yet
2. `_publish_context_changed` exception handler is untested (EventBus.publish is reliable)
3. Memory validation check for negative total_count is unreachable (computed from non-negative fields)

---

## Technical Debt

- No persistent context snapshot storage
- No cross-Kernel context synchronization
- BrowserContext and AIContext are stubs awaiting real implementation
- Permission system is declarative only — no enforcement layer yet

---

## Files Created

```
src/atlas_core/context/__init__.py    — 372 lines, full Context system
tests/test_context.py                 — 397 lines, 49 tests
```

---

## Commit

```
b47d6a7 feat(context): complete milestone 4 — atlas context
```

---

## Next Steps

- Knowledge Engine
- AI Router (provider abstraction)
- Opportunity Engine
- Execution Engine
- Browser Companion
- Mission Control
- Notification Service

---

*End of Milestone 4 Report*
