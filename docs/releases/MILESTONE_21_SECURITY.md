# Milestone 21 — Security & Secrets Management

Centralized security services for Atlas, including secret storage, credential
management, permissions, encryption helpers, and audit logging.

## Components (13)

| Component | Responsibility |
|---|---|
| `SecurityLevel` | Enum: PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED |
| `Permission` | Frozen dataclass: permission_id, resource, action, security_level |
| `Role` | Frozen dataclass: role_id, name, permissions |
| `Principal` | Frozen dataclass: principal_id, name, roles |
| `SecretReference` | Frozen dataclass: secret_id, key, metadata |
| `EncryptionProvider` | Fernet encryption + HMAC-SHA256 verification |
| `SecretManager` | CRUD + rotation for secrets via PersistenceManager |
| `AuditEntry` | Frozen dataclass: timestamp, principal, action, resource, metadata |
| `AuditLogger` | Record, query, export (JSON), clear audit trail |
| `AuthorizationManager` | Role/principal registration, authorize, permission queries |
| `SecurityMetrics` | Track encrypt/decrypt/hash/verify/secret/audit/authorize counts & timing |
| `SecurityEventBridge` | Publish 10 event types (secret_*, authorization_*, audit_*, security_alert) |
| `SecurityManager` | IService (#14), facade over all above, lifecycle-managed |

## Statistics

- **Tests**: 94 (94 passed, 0 failed)
- **Coverage**: 98% (368 statements, 7 missed)
- **Total tests**: 2039

## Files

- `src/atlas_core/security/__init__.py` — All 13 components (~612 lines)
- `tests/test_security.py` — 94 test methods (~812 lines)
- `src/atlas_core/interfaces/events.py` — Added `EventCategory.SECURITY`
- `src/atlas_core/kernel/__init__.py` — SecurityManager as service #14

## Architecture Compliance

- SecretManager uses PersistenceManager (injected) — no direct SQLite
- EncryptionProvider uses stdlib + cryptography.Fernet — no AI/browser/business logic
- Frozen dataclasses, full typing, thread-safe
- EventBus-only integration via SecurityEventBridge
- IService lifecycle for SecurityManager
