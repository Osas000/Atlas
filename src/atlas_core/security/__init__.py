"""Security Framework — centralized security services for Atlas.

Includes secret storage, credential management, permissions,
authentication models, encryption helpers, and audit logging.

This subsystem owns security concerns only.  It does NOT implement
user login, OAuth, or external identity providers.  It prepares
Atlas for secure production deployments.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional

from atlas_core.interfaces import IService, ServiceHealth, ServiceState


# ======================================================================
# SecurityLevel
# ======================================================================


class SecurityLevel(Enum):
    PUBLIC = auto()
    INTERNAL = auto()
    CONFIDENTIAL = auto()
    SECRET = auto()
    TOP_SECRET = auto()


# ======================================================================
# Permission
# ======================================================================


@dataclass(frozen=True)
class Permission:
    permission_id: str
    resource: str
    action: str
    security_level: SecurityLevel = SecurityLevel.INTERNAL


# ======================================================================
# Role
# ======================================================================


@dataclass(frozen=True)
class Role:
    role_id: str
    name: str
    permissions: tuple[Permission, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# Principal
# ======================================================================


@dataclass(frozen=True)
class Principal:
    principal_id: str
    name: str
    roles: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# SecretReference
# ======================================================================


@dataclass(frozen=True)
class SecretReference:
    secret_id: str
    name: str
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# EncryptionProvider
# ======================================================================


class EncryptionProvider:
    def __init__(self, key: bytes | None = None) -> None:
        self._logger = logging.getLogger(__name__)
        if key is not None:
            self._key = key
        else:
            self._key = os.urandom(32)
        self._fernet: Any | None = None

    def _get_fernet(self) -> Any:
        if self._fernet is None:
            from cryptography.fernet import Fernet
            self._fernet = Fernet(base64.urlsafe_b64encode(self._key))
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        f = self._get_fernet()
        token = f.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        f = self._get_fernet()
        token = f.decrypt(ciphertext.encode("utf-8"))
        return token.decode("utf-8")

    def hash(self, value: str, salt: str | None = None) -> str:
        if salt is None:
            salt = os.urandom(16).hex()
        h = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt.encode("utf-8"), 100000)
        return f"{salt}${base64.b64encode(h).decode('utf-8')}"

    def verify(self, value: str, hashed: str) -> bool:
        try:
            parts = hashed.split("$")
            if len(parts) != 2:
                return False
            salt, expected = parts
            h = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt.encode("utf-8"), 100000)
            computed = base64.b64encode(h).decode("utf-8")
            return hmac.compare_digest(computed, expected)
        except Exception:
            return False

    @property
    def key(self) -> bytes:
        return self._key


# ======================================================================
# SecretManager
# ======================================================================


class SecretManager:
    def __init__(self, persistence_manager: Any, encryption_provider: EncryptionProvider) -> None:
        self._persistence = persistence_manager
        self._encryption = encryption_provider
        self._lock = asyncio.Lock()
        self._cache: dict[str, SecretReference] = {}
        self._logger = logging.getLogger(__name__)
        self._collection = "secrets"

    async def create_secret(self, secret_id: str, name: str, value: str, metadata: dict[str, Any] | None = None) -> SecretReference:
        async with self._lock:
            existing = await self._exists(secret_id)
            if existing:
                raise ValueError(f"Secret already exists: {secret_id}")
            encrypted = self._encryption.encrypt(value)
            ref = SecretReference(
                secret_id=secret_id,
                name=name,
                metadata=metadata or {},
            )
            await self._persistence.save(self._collection, secret_id, {
                "encrypted_value": encrypted,
                "reference": {
                    "secret_id": secret_id,
                    "name": name,
                    "created_at": ref.created_at.isoformat(),
                    "updated_at": ref.updated_at.isoformat(),
                    "metadata": ref.metadata,
                },
            })
            self._cache[secret_id] = ref
            return ref

    async def update_secret(self, secret_id: str, value: str, metadata: dict[str, Any] | None = None) -> SecretReference:
        async with self._lock:
            data = await self._persistence.load(self._collection, secret_id)
            if data is None:
                raise ValueError(f"Secret not found: {secret_id}")
            encrypted = self._encryption.encrypt(value)
            now = datetime.now()
            ref = SecretReference(
                secret_id=secret_id,
                name=data["reference"]["name"],
                created_at=datetime.fromisoformat(data["reference"]["created_at"]),
                updated_at=now,
                metadata=metadata or data["reference"].get("metadata", {}),
            )
            await self._persistence.save(self._collection, secret_id, {
                "encrypted_value": encrypted,
                "reference": {
                    "secret_id": secret_id,
                    "name": ref.name,
                    "created_at": ref.created_at.isoformat(),
                    "updated_at": now.isoformat(),
                    "metadata": ref.metadata,
                },
            })
            self._cache[secret_id] = ref
            return ref

    async def delete_secret(self, secret_id: str) -> bool:
        async with self._lock:
            self._cache.pop(secret_id, None)
            return await self._persistence.delete(self._collection, secret_id)

    async def rotate_secret(self, secret_id: str, new_value: str) -> SecretReference:
        return await self.update_secret(secret_id, new_value)

    async def retrieve_secret(self, secret_id: str) -> Optional[str]:
        data = await self._persistence.load(self._collection, secret_id)
        if data is None:
            return None
        return self._encryption.decrypt(data["encrypted_value"])

    async def exists(self, secret_id: str) -> bool:
        return await self._exists(secret_id)

    async def _exists(self, secret_id: str) -> bool:
        if secret_id in self._cache:
            return True
        data = await self._persistence.load(self._collection, secret_id)
        return data is not None

    def get_reference(self, secret_id: str) -> Optional[SecretReference]:
        return self._cache.get(secret_id)


# ======================================================================
# AuditEntry
# ======================================================================


@dataclass(frozen=True)
class AuditEntry:
    timestamp: datetime = field(default_factory=datetime.now)
    principal: str = ""
    action: str = ""
    resource: str = ""
    result: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# AuditLogger
# ======================================================================


class AuditLogger:
    def __init__(self, persistence_manager: Any, max_size: int = 1000) -> None:
        self._persistence = persistence_manager
        self._lock = asyncio.Lock()
        self._entries: deque[AuditEntry] = deque(maxlen=max_size)
        self._collection = "audit_log"

    async def record(self, entry: AuditEntry) -> None:
        async with self._lock:
            self._entries.append(entry)
        try:
            await self._persistence.save(
                self._collection,
                f"{entry.timestamp.isoformat()}_{uuid.uuid4().hex[:8]}",
                {
                    "timestamp": entry.timestamp.isoformat(),
                    "principal": entry.principal,
                    "action": entry.action,
                    "resource": entry.resource,
                    "result": entry.result,
                    "metadata": entry.metadata,
                },
            )
        except Exception:
            pass

    async def get_entries(
        self,
        principal: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        async with self._lock:
            matches = list(self._entries)
        if principal:
            matches = [e for e in matches if e.principal == principal]
        if action:
            matches = [e for e in matches if e.action == action]
        return matches[-limit:]

    async def export(self, format: str = "json") -> str:
        entries = await self.get_entries()
        if format == "json":
            data = [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "principal": e.principal,
                    "action": e.action,
                    "resource": e.resource,
                    "result": e.result,
                    "metadata": e.metadata,
                }
                for e in entries
            ]
            return json.dumps(data, indent=2)
        return ""

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)


# ======================================================================
# AuthorizationManager
# ======================================================================


class AuthorizationManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._roles: dict[str, Role] = {}
        self._principals: dict[str, Principal] = {}

    async def register_role(self, role: Role) -> None:
        async with self._lock:
            if role.role_id in self._roles:
                raise ValueError(f"Role already exists: {role.role_id}")
            self._roles[role.role_id] = role

    async def unregister_role(self, role_id: str) -> Optional[Role]:
        async with self._lock:
            return self._roles.pop(role_id, None)

    async def register_principal(self, principal: Principal) -> None:
        async with self._lock:
            if principal.principal_id in self._principals:
                raise ValueError(f"Principal already exists: {principal.principal_id}")
            self._principals[principal.principal_id] = principal

    async def unregister_principal(self, principal_id: str) -> Optional[Principal]:
        async with self._lock:
            return self._principals.pop(principal_id, None)

    async def authorize(self, principal_id: str, resource: str, action: str) -> bool:
        async with self._lock:
            principal = self._principals.get(principal_id)
            if principal is None:
                return False
            for role_id in principal.roles:
                role = self._roles.get(role_id)
                if role is None:
                    continue
                for perm in role.permissions:
                    if perm.resource == resource and perm.action == action:
                        return True
            return False

    async def get_principal_permissions(self, principal_id: str) -> list[Permission]:
        permissions: list[Permission] = []
        async with self._lock:
            principal = self._principals.get(principal_id)
            if principal is None:
                return permissions
            for role_id in principal.roles:
                role = self._roles.get(role_id)
                if role is None:
                    continue
                permissions.extend(role.permissions)
        return permissions

    def get_role(self, role_id: str) -> Optional[Role]:
        return self._roles.get(role_id)

    def get_principal(self, principal_id: str) -> Optional[Principal]:
        return self._principals.get(principal_id)

    def list_roles(self) -> list[Role]:
        return list(self._roles.values())

    def list_principals(self) -> list[Principal]:
        return list(self._principals.values())


# ======================================================================
# SecurityMetrics
# ======================================================================


class SecurityMetrics:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._auth_requests = 0
        self._denials = 0
        self._secret_reads = 0
        self._secret_writes = 0
        self._rotations = 0
        self._audit_events = 0

    async def record_auth_request(self, granted: bool) -> None:
        async with self._lock:
            self._auth_requests += 1
            if not granted:
                self._denials += 1

    async def record_secret_read(self) -> None:
        async with self._lock:
            self._secret_reads += 1

    async def record_secret_write(self) -> None:
        async with self._lock:
            self._secret_writes += 1

    async def record_rotation(self) -> None:
        async with self._lock:
            self._rotations += 1

    async def record_audit_event(self) -> None:
        async with self._lock:
            self._audit_events += 1

    @property
    def auth_requests(self) -> int:
        return self._auth_requests

    @property
    def denials(self) -> int:
        return self._denials

    @property
    def secret_reads(self) -> int:
        return self._secret_reads

    @property
    def secret_writes(self) -> int:
        return self._secret_writes

    @property
    def rotations(self) -> int:
        return self._rotations

    @property
    def audit_events(self) -> int:
        return self._audit_events

    def snapshot(self) -> dict[str, Any]:
        return {
            "auth_requests": self._auth_requests,
            "denials": self._denials,
            "secret_reads": self._secret_reads,
            "secret_writes": self._secret_writes,
            "rotations": self._rotations,
            "audit_events": self._audit_events,
        }


# ======================================================================
# SecurityEventBridge
# ======================================================================


class SecurityEventBridge:
    def __init__(self, event_bus: Any) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(self, event_type: str, **extra: Any) -> None:
        try:
            from atlas_core.interfaces.events import Event, EventCategory
            event = Event(
                source="security_manager",
                category=EventCategory.SECURITY,
                payload={"event_type": event_type, **extra},
            )
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish security event")

    async def secret_created(self, secret_id: str) -> None:
        await self.publish("SECRET_CREATED", secret_id=secret_id)

    async def secret_rotated(self, secret_id: str) -> None:
        await self.publish("SECRET_ROTATED", secret_id=secret_id)

    async def secret_deleted(self, secret_id: str) -> None:
        await self.publish("SECRET_DELETED", secret_id=secret_id)

    async def authorization_granted(self, principal_id: str, resource: str, action: str) -> None:
        await self.publish("AUTHORIZATION_GRANTED", principal_id=principal_id, resource=resource, action=action)

    async def authorization_denied(self, principal_id: str, resource: str, action: str) -> None:
        await self.publish("AUTHORIZATION_DENIED", principal_id=principal_id, resource=resource, action=action)

    async def audit_recorded(self, entry: AuditEntry) -> None:
        await self.publish("AUDIT_RECORDED", principal=entry.principal, action=entry.action, resource=entry.resource)

    async def security_alert(self, message: str, severity: str = "low") -> None:
        await self.publish("SECURITY_ALERT", message=message, severity=severity)


# ======================================================================
# SecurityManager (IService)
# ======================================================================


class SecurityManager(IService):
    def __init__(
        self,
        event_bus: Any,
        persistence_manager: Any,
    ) -> None:
        self._event_bus = event_bus
        self._persistence = persistence_manager
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)

        self._encryption = EncryptionProvider()
        self._secret_manager = SecretManager(persistence_manager, self._encryption)
        self._auth_manager = AuthorizationManager()
        self._audit_logger = AuditLogger(persistence_manager)
        self._metrics = SecurityMetrics()
        self._event_bridge = SecurityEventBridge(event_bus)

    @property
    def name(self) -> str:
        return "security_manager"

    @property
    def encryption(self) -> EncryptionProvider:
        return self._encryption

    @property
    def secrets(self) -> SecretManager:
        return self._secret_manager

    @property
    def auth(self) -> AuthorizationManager:
        return self._auth_manager

    @property
    def audit(self) -> AuditLogger:
        return self._audit_logger

    @property
    def metrics(self) -> SecurityMetrics:
        return self._metrics

    async def initialize(self) -> None:
        self._state = ServiceState.INITIALIZED
        self._logger.info("Security Manager initialized")

    async def start(self) -> None:
        self._state = ServiceState.RUNNING
        self._logger.info("Security Manager started")

    async def stop(self) -> None:
        self._state = ServiceState.STOPPED
        self._logger.info("Security Manager stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=self._state,
            message="Security Manager operational",
            metadata=self._metrics.snapshot(),
        )

    async def authorize(self, principal_id: str, resource: str, action: str) -> bool:
        result = await self._auth_manager.authorize(principal_id, resource, action)
        await self._metrics.record_auth_request(result)
        if result:
            await self._event_bridge.authorization_granted(principal_id, resource, action)
        else:
            await self._event_bridge.authorization_denied(principal_id, resource, action)
        return result

    async def create_secret(self, secret_id: str, name: str, value: str, metadata: dict[str, Any] | None = None) -> SecretReference:
        ref = await self._secret_manager.create_secret(secret_id, name, value, metadata)
        await self._metrics.record_secret_write()
        await self._event_bridge.secret_created(secret_id)
        return ref

    async def rotate_secret(self, secret_id: str, new_value: str) -> SecretReference:
        ref = await self._secret_manager.rotate_secret(secret_id, new_value)
        await self._metrics.record_rotation()
        await self._event_bridge.secret_rotated(secret_id)
        return ref

    async def retrieve_secret(self, secret_id: str) -> Optional[str]:
        value = await self._secret_manager.retrieve_secret(secret_id)
        if value is not None:
            await self._metrics.record_secret_read()
        return value

    async def record_audit(self, entry: AuditEntry) -> None:
        await self._audit_logger.record(entry)
        await self._metrics.record_audit_event()
        await self._event_bridge.audit_recorded(entry)
