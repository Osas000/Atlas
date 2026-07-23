# Milestone 19: Connector Framework

**Date:** 2026-07-23

## Summary

Connector Framework provides the standard integration layer between Atlas and external systems. Every external integration (GitHub, REST APIs, databases, email, filesystem, webhooks, etc.) is implemented as a Connector. All connectors communicate only through public interfaces — no Event Bus, Execution Engine, Persistence Layer, or Intelligence Router bypass.

## Components

### Core Types (`connectors/__init__.py`)
- **ConnectorState** — lifecycle states: DISCONNECTED, CONNECTING, CONNECTED, AUTHENTICATING, READY, FAILED, DISCONNECTING
- **ConnectorCapability** — capability flags: FILESYSTEM, REST_API, DATABASE, EMAIL, WEBHOOK, GITHUB, LOCAL_PROCESS, CUSTOM
- **ConnectorManifest** — frozen dataclass: connector_id, name, version, author, capabilities, supported_operations, configuration_schema
- **ConnectorSession** — frozen dataclass: session_id, connector_id, created_at, last_activity, authenticated, metadata
- **ConnectorCredentials** — secure credential container with masked output, supports API keys, tokens, username/password, never logs secrets
- **ConnectorHealth** — connected, latency, last_error, uptime, health_score
- **Connector (ABC)** — abstract base with connect, disconnect, authenticate, execute, validate, health_check, supports

### Infrastructure
- **ConnectorRegistry** — thread-safe registry with register, unregister, lookup, list, capability filtering, health lookup
- **ConnectorFactory** — creates connector instances, validates manifests, dependency injection
- **ConnectorMetrics** — tracks connections, disconnections, auth failures, executions, latency, active sessions
- **ConnectorEventBridge** — publishes lifecycle events: CONNECTOR_REGISTERED, CONNECTED, DISCONNECTED, AUTHENTICATED, EXECUTED, FAILED, HEALTH_CHANGED

### ConnectorManager (IService)
- Full IService lifecycle (`create` by kernel boot, `initialize`, `start`, `stop`, `dispose`)
- Registers as `connector_manager` in kernel (service #12)
- Exposed as `kernel.connector_manager`
- Owns registry, factory, metrics, event bridge, sessions
- Methods: register_connector, remove_connector, connect, disconnect, execute, create_session, close_session, list_connectors
- Stop disconnects all connected connectors

### Reference Connectors (Stubs)
- **FilesystemConnector** — FILESYSTEM capability
- **RESTConnector** — REST_API, CUSTOM capabilities
- **GitHubConnector** — GITHUB capability
- **DatabaseConnector** — DATABASE capability
- **EmailConnector** — EMAIL capability
- **WebhookConnector** — WEBHOOK capability

All are infrastructure-only. No real API integrations. No network traffic. Methods return stub responses suitable for testing.

## Files Changed

- `src/atlas_core/connectors/__init__.py` — new file, ~410 lines
- `src/atlas_core/interfaces/events.py` — added `CONNECTOR` to `EventCategory`
- `src/atlas_core/kernel/__init__.py` — imports ConnectorManager, registers as service #12, exposes `connector_manager` property
- `tests/test_connectors.py` — 122 tests, 100% coverage
- `tests/test_kernel.py` — boot count 12, health count 13
- `tests/test_monitor.py` — `kernel.registry.count` updated to 12
- `tests/test_monitor_api.py` — `kernel.registry.count` updated to 12
- `tests/test_plugins.py` — `kernel.registry.count` updated to 12

## Test Results

- **Total:** 1809 tests passing (up from 1687)
- **Connector coverage:** 100% (409/409 lines)
- **122 connector tests** covering: lifecycle, registration, connection, authentication, execution, health, capability filtering, sessions, metrics, events, kernel integration, thread safety, and failure paths
- No regressions

## Architecture Compliance

- Package: `atlas_core.connectors` ✓
- Python 3.12, src-layout ✓
- IService lifecycle ✓
- Full typing, frozen dataclasses ✓
- Dependency injection, thread-safe ✓
- No circular imports ✓
- No AI/browser/business logic ✓
- No direct SQLite access ✓
- No private state access across subsystems ✓
- All communication through public interfaces ✓

## Notes

- Reference connectors remain stubs — no real external integrations yet
- Atlas gains a unified external integration layer ready for future production connectors
- Future connectors should subclass `Connector` (or `_BaseReferenceConnector` for convenience) and implement the abstract methods
