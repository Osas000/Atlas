"""Comprehensive tests for the Security Framework."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import pytest

from atlas_core.interfaces.events import EventCategory
from atlas_core.security import (
    AuditEntry,
    AuditLogger,
    AuthorizationManager,
    EncryptionProvider,
    Permission,
    Principal,
    Role,
    SecretManager,
    SecretReference,
    SecurityEventBridge,
    SecurityLevel,
    SecurityManager,
    SecurityMetrics,
)


# ======================================================================
# MockPersistence — simulates PersistenceManager for testing
# ======================================================================


class MockPersistence:
    def __init__(self) -> None:
        self._storage: dict[str, dict[str, Any]] = {}

    async def save(self, collection: str, key: str, value: Any) -> None:
        if collection not in self._storage:
            self._storage[collection] = {}
        self._storage[collection][key] = value

    async def load(self, collection: str, key: str) -> Any:
        col = self._storage.get(collection)
        if col is None:
            return None
        return col.get(key)

    async def delete(self, collection: str, key: str) -> bool:
        col = self._storage.get(collection)
        if col is None:
            return False
        return col.pop(key, None) is not None

    async def list_keys(self, collection: str) -> list[str]:
        col = self._storage.get(collection)
        return list(col.keys()) if col else []


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def mock_persistence() -> MockPersistence:
    return MockPersistence()


@pytest.fixture
def encryption() -> EncryptionProvider:
    return EncryptionProvider()


@pytest.fixture
def secret_manager(mock_persistence: MockPersistence, encryption: EncryptionProvider) -> SecretManager:
    return SecretManager(mock_persistence, encryption)


@pytest.fixture
def event_bus() -> Any:
    from atlas_core.events import EventBus
    return EventBus()


@pytest.fixture
def security_manager(event_bus: Any, mock_persistence: MockPersistence) -> SecurityManager:
    return SecurityManager(event_bus=event_bus, persistence_manager=mock_persistence)


@pytest.fixture
def sample_permission() -> Permission:
    return Permission(permission_id="p1", resource="report", action="read")


@pytest.fixture
def sample_role(sample_permission: Permission) -> Role:
    return Role(role_id="admin", name="Administrator", permissions=(sample_permission,))


@pytest.fixture
def sample_principal() -> Principal:
    return Principal(principal_id="user1", name="User One", roles=("admin",))


@pytest.fixture
def auth_manager() -> AuthorizationManager:
    return AuthorizationManager()


# ======================================================================
# SecurityLevel
# ======================================================================


class TestSecurityLevel:
    def test_enum_values(self) -> None:
        assert len(SecurityLevel) == 5
        assert SecurityLevel.PUBLIC.name == "PUBLIC"
        assert SecurityLevel.INTERNAL.name == "INTERNAL"
        assert SecurityLevel.CONFIDENTIAL.name == "CONFIDENTIAL"
        assert SecurityLevel.SECRET.name == "SECRET"
        assert SecurityLevel.TOP_SECRET.name == "TOP_SECRET"


# ======================================================================
# Permission
# ======================================================================


class TestPermission:
    def test_frozen(self) -> None:
        p = Permission(permission_id="p1", resource="r", action="a")
        with pytest.raises(AttributeError):
            p.resource = "r2"  # type: ignore[misc]

    def test_default_security_level(self) -> None:
        p = Permission(permission_id="p1", resource="r", action="a")
        assert p.security_level == SecurityLevel.INTERNAL

    def test_full(self) -> None:
        p = Permission(
            permission_id="p1", resource="secret", action="write",
            security_level=SecurityLevel.SECRET,
        )
        assert p.permission_id == "p1"
        assert p.security_level == SecurityLevel.SECRET


# ======================================================================
# Role
# ======================================================================


class TestRole:
    def test_frozen(self) -> None:
        r = Role(role_id="r1", name="R1")
        with pytest.raises(AttributeError):
            r.name = "R2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        r = Role(role_id="r1", name="R1")
        assert r.permissions == ()
        assert r.metadata == {}

    def test_full(self, sample_permission: Permission) -> None:
        r = Role(
            role_id="admin", name="Admin",
            permissions=(sample_permission,),
            metadata={"level": "high"},
        )
        assert r.role_id == "admin"
        assert len(r.permissions) == 1
        assert r.metadata["level"] == "high"


# ======================================================================
# Principal
# ======================================================================


class TestPrincipal:
    def test_frozen(self) -> None:
        p = Principal(principal_id="p1", name="P1")
        with pytest.raises(AttributeError):
            p.name = "P2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        p = Principal(principal_id="p1", name="P1")
        assert p.roles == ()
        assert p.attributes == {}

    def test_full(self) -> None:
        p = Principal(
            principal_id="u1", name="User",
            roles=("admin",),
            attributes={"email": "user@test.com"},
        )
        assert p.principal_id == "u1"
        assert "admin" in p.roles
        assert p.attributes["email"] == "user@test.com"


# ======================================================================
# SecretReference
# ======================================================================


class TestSecretReference:
    def test_frozen(self) -> None:
        s = SecretReference(secret_id="s1", name="S1")
        with pytest.raises(AttributeError):
            s.name = "S2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        s = SecretReference(secret_id="s1", name="S1")
        assert s.metadata == {}

    def test_full(self) -> None:
        s = SecretReference(
            secret_id="s1", name="DB Password",
            metadata={"env": "prod"},
        )
        assert s.secret_id == "s1"
        assert s.metadata["env"] == "prod"


# ======================================================================
# EncryptionProvider
# ======================================================================


class TestEncryptionProvider:
    def test_encrypt_decrypt(self, encryption: EncryptionProvider) -> None:
        original = "my_secret_value"
        encrypted = encryption.encrypt(original)
        assert encrypted != original
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == original

    def test_key_generation(self) -> None:
        e1 = EncryptionProvider()
        e2 = EncryptionProvider()
        assert e1.key != e2.key

    def test_custom_key(self) -> None:
        key = b"test_key_32_bytes_long!!!!!!!!!!"
        e = EncryptionProvider(key)
        ct = e.encrypt("hello")
        assert e.decrypt(ct) == "hello"

    def test_hash(self, encryption: EncryptionProvider) -> None:
        h = encryption.hash("password123")
        assert "$" in h
        assert encryption.verify("password123", h) is True

    def test_hash_wrong_value(self, encryption: EncryptionProvider) -> None:
        h = encryption.hash("password123")
        assert encryption.verify("wrong", h) is False

    def test_verify_invalid_format(self, encryption: EncryptionProvider) -> None:
        assert encryption.verify("value", "invalid_format") is False

    def test_verify_empty(self, encryption: EncryptionProvider) -> None:
        assert encryption.verify("value", "") is False

    def test_hash_no_salt(self, encryption: EncryptionProvider) -> None:
        h1 = encryption.hash("test")
        h2 = encryption.hash("test")
        assert h1 != h2  # different salts

    def test_key_property(self, encryption: EncryptionProvider) -> None:
        assert len(encryption.key) == 32


# ======================================================================
# SecretManager
# ======================================================================


class TestSecretManager:
    async def test_create_secret(self, secret_manager: SecretManager) -> None:
        ref = await secret_manager.create_secret("s1", "API Key", "sk-12345")
        assert ref.secret_id == "s1"
        assert ref.name == "API Key"

    async def test_create_duplicate_raises(self, secret_manager: SecretManager) -> None:
        await secret_manager.create_secret("s1", "Key", "val")
        with pytest.raises(ValueError, match="already exists"):
            await secret_manager.create_secret("s1", "Key", "val2")

    async def test_retrieve_secret(self, secret_manager: SecretManager) -> None:
        await secret_manager.create_secret("s1", "Key", "my_value")
        value = await secret_manager.retrieve_secret("s1")
        assert value == "my_value"

    async def test_retrieve_nonexistent(self, secret_manager: SecretManager) -> None:
        value = await secret_manager.retrieve_secret("missing")
        assert value is None

    async def test_update_secret(self, secret_manager: SecretManager) -> None:
        await secret_manager.create_secret("s1", "Key", "old")
        ref = await secret_manager.update_secret("s1", "new")
        assert ref.secret_id == "s1"
        value = await secret_manager.retrieve_secret("s1")
        assert value == "new"

    async def test_update_nonexistent_raises(self, secret_manager: SecretManager) -> None:
        with pytest.raises(ValueError, match="not found"):
            await secret_manager.update_secret("missing", "val")

    async def test_delete_secret(self, secret_manager: SecretManager) -> None:
        await secret_manager.create_secret("s1", "Key", "val")
        result = await secret_manager.delete_secret("s1")
        assert result is True
        value = await secret_manager.retrieve_secret("s1")
        assert value is None

    async def test_delete_nonexistent(self, secret_manager: SecretManager) -> None:
        result = await secret_manager.delete_secret("missing")
        assert result is False

    async def test_rotate_secret(self, secret_manager: SecretManager) -> None:
        await secret_manager.create_secret("s1", "Key", "old")
        ref = await secret_manager.rotate_secret("s1", "rotated")
        value = await secret_manager.retrieve_secret("s1")
        assert value == "rotated"

    async def test_exists(self, secret_manager: SecretManager) -> None:
        assert await secret_manager.exists("s1") is False
        await secret_manager.create_secret("s1", "Key", "val")
        assert await secret_manager.exists("s1") is True

    async def test_get_reference(self, secret_manager: SecretManager) -> None:
        ref = await secret_manager.create_secret("s1", "Key", "val")
        cached = secret_manager.get_reference("s1")
        assert cached is ref

    async def test_get_reference_missing(self, secret_manager: SecretManager) -> None:
        assert secret_manager.get_reference("missing") is None

    async def test_create_with_metadata(self, secret_manager: SecretManager) -> None:
        ref = await secret_manager.create_secret("s1", "Key", "val", metadata={"env": "prod"})
        assert ref.metadata["env"] == "prod"

    async def test_secret_encrypted_at_rest(self, secret_manager: SecretManager, mock_persistence: MockPersistence) -> None:
        await secret_manager.create_secret("s1", "Key", "plaintext_value")
        data = await mock_persistence.load("secrets", "s1")
        assert data is not None
        assert "encrypted_value" in data
        assert data["encrypted_value"] != "plaintext_value"


# ======================================================================
# AuthorizationManager
# ======================================================================


class TestAuthorizationManager:
    async def test_register_role(self, auth_manager: AuthorizationManager, sample_role: Role) -> None:
        await auth_manager.register_role(sample_role)
        assert auth_manager.get_role("admin") is sample_role

    async def test_register_duplicate_role_raises(self, auth_manager: AuthorizationManager, sample_role: Role) -> None:
        await auth_manager.register_role(sample_role)
        with pytest.raises(ValueError, match="already exists"):
            await auth_manager.register_role(sample_role)

    async def test_unregister_role(self, auth_manager: AuthorizationManager, sample_role: Role) -> None:
        await auth_manager.register_role(sample_role)
        result = await auth_manager.unregister_role("admin")
        assert result is sample_role
        assert auth_manager.get_role("admin") is None

    async def test_unregister_missing_role(self, auth_manager: AuthorizationManager) -> None:
        result = await auth_manager.unregister_role("missing")
        assert result is None

    async def test_register_principal(self, auth_manager: AuthorizationManager, sample_principal: Principal) -> None:
        await auth_manager.register_principal(sample_principal)
        assert auth_manager.get_principal("user1") is sample_principal

    async def test_register_duplicate_principal_raises(self, auth_manager: AuthorizationManager, sample_principal: Principal) -> None:
        await auth_manager.register_principal(sample_principal)
        with pytest.raises(ValueError, match="already exists"):
            await auth_manager.register_principal(sample_principal)

    async def test_unregister_principal(self, auth_manager: AuthorizationManager, sample_principal: Principal) -> None:
        await auth_manager.register_principal(sample_principal)
        result = await auth_manager.unregister_principal("user1")
        assert result is sample_principal

    async def test_authorize_granted(self, auth_manager: AuthorizationManager, sample_role: Role, sample_principal: Principal) -> None:
        await auth_manager.register_role(sample_role)
        await auth_manager.register_principal(sample_principal)
        result = await auth_manager.authorize("user1", "report", "read")
        assert result is True

    async def test_authorize_denied_wrong_action(self, auth_manager: AuthorizationManager, sample_role: Role, sample_principal: Principal) -> None:
        await auth_manager.register_role(sample_role)
        await auth_manager.register_principal(sample_principal)
        result = await auth_manager.authorize("user1", "report", "write")
        assert result is False

    async def test_authorize_denied_unknown_principal(self, auth_manager: AuthorizationManager) -> None:
        result = await auth_manager.authorize("unknown", "report", "read")
        assert result is False

    async def test_get_principal_permissions(self, auth_manager: AuthorizationManager, sample_role: Role, sample_principal: Principal, sample_permission: Permission) -> None:
        await auth_manager.register_role(sample_role)
        await auth_manager.register_principal(sample_principal)
        perms = await auth_manager.get_principal_permissions("user1")
        assert sample_permission in perms

    async def test_get_principal_permissions_unknown(self, auth_manager: AuthorizationManager) -> None:
        perms = await auth_manager.get_principal_permissions("unknown")
        assert perms == []

    async def test_list_roles(self, auth_manager: AuthorizationManager, sample_role: Role) -> None:
        assert auth_manager.list_roles() == []
        await auth_manager.register_role(sample_role)
        assert len(auth_manager.list_roles()) == 1

    async def test_list_principals(self, auth_manager: AuthorizationManager, sample_principal: Principal) -> None:
        assert auth_manager.list_principals() == []
        await auth_manager.register_principal(sample_principal)
        assert len(auth_manager.list_principals()) == 1

    async def test_authorize_multiple_roles(self, auth_manager: AuthorizationManager) -> None:
        r1 = Role(role_id="r1", name="R1", permissions=(Permission(permission_id="p1", resource="r", action="a"),))
        r2 = Role(role_id="r2", name="R2", permissions=(Permission(permission_id="p2", resource="r", action="b"),))
        p = Principal(principal_id="u1", name="U1", roles=("r1", "r2"))
        await auth_manager.register_role(r1)
        await auth_manager.register_role(r2)
        await auth_manager.register_principal(p)
        assert await auth_manager.authorize("u1", "r", "a") is True
        assert await auth_manager.authorize("u1", "r", "b") is True
        assert await auth_manager.authorize("u1", "r", "c") is False


# ======================================================================
# AuditEntry
# ======================================================================


class TestAuditEntry:
    def test_frozen(self) -> None:
        e = AuditEntry(principal="p", action="a", resource="r")
        with pytest.raises(AttributeError):
            e.action = "b"  # type: ignore[misc]

    def test_defaults(self) -> None:
        e = AuditEntry()
        assert e.principal == ""
        assert e.action == ""
        assert e.resource == ""

    def test_full(self) -> None:
        e = AuditEntry(
            principal="user1", action="read", resource="report",
            result="success", metadata={"ip": "127.0.0.1"},
        )
        assert e.principal == "user1"
        assert e.result == "success"


# ======================================================================
# AuditLogger
# ======================================================================


class TestAuditLogger:
    @pytest.fixture
    def audit_logger(self, mock_persistence: MockPersistence) -> AuditLogger:
        return AuditLogger(mock_persistence)

    async def test_record(self, audit_logger: AuditLogger) -> None:
        await audit_logger.record(AuditEntry(principal="u1", action="read", resource="r1"))
        assert audit_logger.size == 1

    async def test_get_entries(self, audit_logger: AuditLogger) -> None:
        await audit_logger.record(AuditEntry(principal="u1", action="read", resource="r1"))
        await audit_logger.record(AuditEntry(principal="u2", action="write", resource="r2"))
        entries = await audit_logger.get_entries()
        assert len(entries) == 2

    async def test_filter_by_principal(self, audit_logger: AuditLogger) -> None:
        await audit_logger.record(AuditEntry(principal="u1", action="read", resource="r1"))
        await audit_logger.record(AuditEntry(principal="u2", action="write", resource="r2"))
        entries = await audit_logger.get_entries(principal="u1")
        assert len(entries) == 1
        assert entries[0].principal == "u1"

    async def test_filter_by_action(self, audit_logger: AuditLogger) -> None:
        await audit_logger.record(AuditEntry(principal="u1", action="read", resource="r1"))
        await audit_logger.record(AuditEntry(principal="u2", action="write", resource="r2"))
        entries = await audit_logger.get_entries(action="write")
        assert len(entries) == 1

    async def test_limit(self, audit_logger: AuditLogger) -> None:
        for i in range(10):
            await audit_logger.record(AuditEntry(principal="u1", action="read", resource=f"r{i}"))
        entries = await audit_logger.get_entries(limit=3)
        assert len(entries) == 3

    async def test_clear(self, audit_logger: AuditLogger) -> None:
        await audit_logger.record(AuditEntry(principal="u1", action="read", resource="r1"))
        await audit_logger.clear()
        assert audit_logger.size == 0

    async def test_export_json(self, audit_logger: AuditLogger) -> None:
        await audit_logger.record(AuditEntry(principal="u1", action="read", resource="r1", result="ok"))
        exported = await audit_logger.export("json")
        data = json.loads(exported)
        assert len(data) == 1
        assert data[0]["principal"] == "u1"
        assert data[0]["result"] == "ok"

    async def test_export_empty(self, audit_logger: AuditLogger) -> None:
        exported = await audit_logger.export("json")
        assert exported == "[]"

    async def test_persistence_integration(self, audit_logger: AuditLogger, mock_persistence: MockPersistence) -> None:
        await audit_logger.record(AuditEntry(principal="u1", action="read", resource="r1"))
        keys = await mock_persistence.list_keys("audit_log")
        assert len(keys) == 1


# ======================================================================
# SecurityMetrics
# ======================================================================


class TestSecurityMetrics:
    async def test_initial(self, security_manager: SecurityManager) -> None:
        m = security_manager.metrics
        assert m.auth_requests == 0
        assert m.denials == 0
        assert m.secret_reads == 0
        assert m.secret_writes == 0
        assert m.rotations == 0
        assert m.audit_events == 0

    async def test_metrics(self) -> None:
        m = SecurityMetrics()
        await m.record_auth_request(True)
        assert m.auth_requests == 1
        assert m.denials == 0

        await m.record_auth_request(False)
        assert m.auth_requests == 2
        assert m.denials == 1

        await m.record_secret_read()
        assert m.secret_reads == 1

        await m.record_secret_write()
        assert m.secret_writes == 1

        await m.record_rotation()
        assert m.rotations == 1

        await m.record_audit_event()
        assert m.audit_events == 1

    async def test_snapshot(self) -> None:
        m = SecurityMetrics()
        await m.record_secret_write()
        await m.record_secret_write()
        await m.record_auth_request(False)
        snap = m.snapshot()
        assert snap["secret_writes"] == 2
        assert snap["denials"] == 1
        assert snap["auth_requests"] == 1


# ======================================================================
# SecurityEventBridge
# ======================================================================


class TestSecurityEventBridge:
    @pytest.fixture
    def bridge(self, event_bus: Any) -> SecurityEventBridge:
        return SecurityEventBridge(event_bus)

    async def receive(self, event_bus: Any) -> list:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("security", handler)
        return received

    async def test_secret_created(self, bridge: SecurityEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.secret_created("s1")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "SECRET_CREATED"

    async def test_secret_rotated(self, bridge: SecurityEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.secret_rotated("s1")
        assert len(received) == 1

    async def test_secret_deleted(self, bridge: SecurityEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.secret_deleted("s1")
        assert len(received) == 1

    async def test_authorization_granted(self, bridge: SecurityEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.authorization_granted("u1", "report", "read")
        assert len(received) == 1

    async def test_authorization_denied(self, bridge: SecurityEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.authorization_denied("u1", "report", "write")
        assert len(received) == 1

    async def test_audit_recorded(self, bridge: SecurityEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        entry = AuditEntry(principal="u1", action="read", resource="r1")
        await bridge.audit_recorded(entry)
        assert len(received) == 1

    async def test_security_alert(self, bridge: SecurityEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.security_alert("Intrusion detected", "high")
        assert len(received) == 1
        assert received[0].payload["severity"] == "high"

    async def test_publish_category(self, bridge: SecurityEventBridge, event_bus: Any) -> None:
        received = await self.receive(event_bus)
        await bridge.publish("TEST_EVENT", key="val")
        assert len(received) == 1
        assert received[0].category == EventCategory.SECURITY
        assert received[0].source == "security_manager"

    async def test_publish_no_failure(self) -> None:
        class FakeBus:
            async def publish(self, event: Any) -> None:
                raise RuntimeError("bus down")
        bridge = SecurityEventBridge(FakeBus())
        await bridge.publish("TEST")


# ======================================================================
# SecurityManager (IService)
# ======================================================================


class TestSecurityManager:
    async def test_name(self, security_manager: SecurityManager) -> None:
        assert security_manager.name == "security_manager"

    async def test_iservice_lifecycle(self, security_manager: SecurityManager) -> None:
        await security_manager.initialize()
        await security_manager.start()
        await security_manager.stop()

    async def test_health_check(self, security_manager: SecurityManager) -> None:
        health = await security_manager.health_check()
        assert health.healthy is True
        assert "Security Manager" in health.message

    async def test_authorize(self, security_manager: SecurityManager, sample_role: Role, sample_principal: Principal) -> None:
        await security_manager.auth.register_role(sample_role)
        await security_manager.auth.register_principal(sample_principal)
        result = await security_manager.authorize("user1", "report", "read")
        assert result is True

    async def test_authorize_denied(self, security_manager: SecurityManager) -> None:
        result = await security_manager.authorize("unknown", "report", "read")
        assert result is False

    async def test_create_secret(self, security_manager: SecurityManager) -> None:
        ref = await security_manager.create_secret("s1", "Key", "value")
        assert ref.secret_id == "s1"

    async def test_rotate_secret(self, security_manager: SecurityManager) -> None:
        await security_manager.create_secret("s1", "Key", "old")
        ref = await security_manager.rotate_secret("s1", "new")
        value = await security_manager.retrieve_secret("s1")
        assert value == "new"

    async def test_retrieve_secret(self, security_manager: SecurityManager) -> None:
        await security_manager.create_secret("s1", "Key", "secret_value")
        value = await security_manager.retrieve_secret("s1")
        assert value == "secret_value"

    async def test_retrieve_nonexistent(self, security_manager: SecurityManager) -> None:
        value = await security_manager.retrieve_secret("missing")
        assert value is None

    async def test_record_audit(self, security_manager: SecurityManager) -> None:
        entry = AuditEntry(principal="u1", action="read", resource="r1")
        await security_manager.record_audit(entry)
        assert security_manager.audit.size == 1

    async def test_properties(self, security_manager: SecurityManager) -> None:
        assert security_manager.encryption is not None
        assert security_manager.secrets is not None
        assert security_manager.auth is not None
        assert security_manager.audit is not None
        assert security_manager.metrics is not None

    async def test_metrics_tracking(self, security_manager: SecurityManager, sample_role: Role, sample_principal: Principal) -> None:
        await security_manager.auth.register_role(sample_role)
        await security_manager.auth.register_principal(sample_principal)
        await security_manager.authorize("user1", "report", "read")
        assert security_manager.metrics.auth_requests == 1
        assert security_manager.metrics.denials == 0

        await security_manager.create_secret("s1", "Key", "val")
        assert security_manager.metrics.secret_writes == 1

        await security_manager.rotate_secret("s1", "new")
        assert security_manager.metrics.rotations == 1


# ======================================================================
# Kernel Integration
# ======================================================================


class TestKernelIntegration:
    @pytest.fixture
    def kernel(self, tmp_path):
        from atlas_core.kernel import AtlasKernel
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "default.yaml").write_text(
            "app_name: TestKernel\n"
            "version: 9.9.9\n"
            "log_level: DEBUG\n"
            "log_dir: '" + str(tmp_path / "logs").replace("\\", "\\\\") + "'\n"
        )
        return AtlasKernel(config_dir)

    async def test_kernel_boot_registers_security_manager(self, kernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.registry.count == 15
        assert kernel.security_manager is not None
        from atlas_core.security import SecurityManager
        assert isinstance(kernel.security_manager, SecurityManager)

    async def test_kernel_before_init_raises(self):
        from atlas_core.kernel import AtlasKernel
        k = AtlasKernel()
        with pytest.raises(RuntimeError):
            _ = k.security_manager

    async def test_security_manager_property(self, kernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.security_manager is not None
        assert isinstance(kernel.security_manager, SecurityManager)


# ======================================================================
# EventCategory
# ======================================================================


class TestEventCategory:
    def test_security_category_exists(self) -> None:
        assert EventCategory.SECURITY.value == "security"


# ======================================================================
# Thread Safety
# ======================================================================


class TestThreadSafety:
    async def test_metrics_concurrent(self) -> None:
        m = SecurityMetrics()
        async def record() -> None:
            for _ in range(100):
                await m.record_auth_request(True)
                await m.record_secret_read()
        async def read() -> None:
            for _ in range(100):
                _ = m.auth_requests
                _ = m.snapshot()
        await asyncio.gather(record(), read())
        assert m.auth_requests == 100
        assert m.secret_reads == 100

    async def test_auth_concurrent(self, auth_manager: AuthorizationManager) -> None:
        r = Role(role_id="r1", name="R1", permissions=(Permission(permission_id="p1", resource="r", action="a"),))
        p = Principal(principal_id="u1", name="U1", roles=("r1",))
        await auth_manager.register_role(r)
        await auth_manager.register_principal(p)

        async def check() -> None:
            for _ in range(50):
                await auth_manager.authorize("u1", "r", "a")
        async def modify() -> None:
            for _ in range(10):
                await auth_manager.unregister_role("r1")
                await auth_manager.register_role(r)
        await asyncio.gather(check(), modify())

    async def test_secret_concurrent(self, secret_manager: SecretManager) -> None:
        async def write() -> None:
            for i in range(20):
                await secret_manager.create_secret(f"s{i}", f"Key{i}", f"val{i}")
        async def read() -> None:
            for i in range(20):
                await secret_manager.retrieve_secret(f"s{i}")
        await asyncio.gather(write(), read())
