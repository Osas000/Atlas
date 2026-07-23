"""Connector Framework — unified integration layer for external systems.

Every external integration (GitHub, REST APIs, databases, email,
filesystem, webhooks, etc.) must be implemented as a Connector.

Connectors never bypass the Event Bus, Execution Engine, Persistence
Layer, or Intelligence Router.  They communicate only through public
interfaces.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Optional

from atlas_core.interfaces import IService, ServiceHealth, ServiceState


# ======================================================================
# ConnectorState
# ======================================================================


class ConnectorState(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    AUTHENTICATING = auto()
    READY = auto()
    FAILED = auto()
    DISCONNECTING = auto()


# ======================================================================
# ConnectorCapability
# ======================================================================


class ConnectorCapability(Enum):
    FILESYSTEM = auto()
    REST_API = auto()
    DATABASE = auto()
    EMAIL = auto()
    WEBHOOK = auto()
    GITHUB = auto()
    LOCAL_PROCESS = auto()
    CUSTOM = auto()


# ======================================================================
# ConnectorManifest
# ======================================================================


@dataclass(frozen=True)
class ConnectorManifest:
    connector_id: str
    name: str
    version: str = "0.1.0"
    author: str = ""
    capabilities: tuple[ConnectorCapability, ...] = ()
    supported_operations: tuple[str, ...] = ()
    configuration_schema: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# ConnectorSession
# ======================================================================


@dataclass(frozen=True)
class ConnectorSession:
    session_id: str
    connector_id: str
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    authenticated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ======================================================================
# ConnectorCredentials
# ======================================================================


class ConnectorCredentials:
    """Secure credential container.

    Supports API keys, tokens, and username/password pairs.
    Never logs secrets.  Ready for future Secrets Manager integration.
    """

    def __init__(
        self,
        api_key: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        **extra: str,
    ) -> None:
        self._api_key = api_key
        self._token = token
        self._username = username
        self._password = password
        self._extra = dict(extra)
        self._locked = False

    @property
    def has_api_key(self) -> bool:
        return self._api_key is not None

    @property
    def has_token(self) -> bool:
        return self._token is not None

    @property
    def has_username(self) -> bool:
        return self._username is not None

    @property
    def masked_api_key(self) -> str:
        if self._api_key is None:
            return ""
        if len(self._api_key) <= 8:
            return "***"
        return self._api_key[:4] + "***" + self._api_key[-4:]

    @property
    def masked_token(self) -> str:
        if self._token is None:
            return ""
        if len(self._token) <= 8:
            return "***"
        return self._token[:4] + "***" + self._token[-4:]

    @property
    def has_password(self) -> bool:
        return self._password is not None

    def get_api_key(self) -> str | None:
        return self._api_key

    def get_token(self) -> str | None:
        return self._token

    def get_username(self) -> str | None:
        return self._username

    def get_password(self) -> str | None:
        return self._password

    def get_extra(self, key: str) -> str | None:
        return self._extra.get(key)

    def lock(self) -> None:
        self._locked = True

    @property
    def locked(self) -> bool:
        return self._locked


# ======================================================================
# ConnectorHealth
# ======================================================================


@dataclass
class ConnectorHealth:
    connected: bool = False
    latency: float = 0.0
    last_error: str = ""
    uptime: float = 0.0
    health_score: float = 0.0


# ======================================================================
# Connector (ABC)
# ======================================================================


class Connector(ABC):
    def __init__(self, manifest: ConnectorManifest) -> None:
        self._manifest = manifest
        self._state = ConnectorState.DISCONNECTED
        self._credentials: ConnectorCredentials | None = None
        self._connected_at: float | None = None
        self._last_error: str = ""
        self._logger = logging.getLogger(f"{__name__}.{manifest.connector_id}")

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    @property
    def state(self) -> ConnectorState:
        return self._state

    @abstractmethod
    async def connect(self) -> bool:
        ...

    @abstractmethod
    async def disconnect(self) -> bool:
        ...

    @abstractmethod
    async def authenticate(self, credentials: ConnectorCredentials) -> bool:
        ...

    @abstractmethod
    async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        ...

    @abstractmethod
    async def validate(self) -> list[str]:
        ...

    @abstractmethod
    async def health_check(self) -> ConnectorHealth:
        ...

    @abstractmethod
    def supports(self, capability: ConnectorCapability) -> bool:
        ...


# ======================================================================
# ConnectorRegistry
# ======================================================================


class ConnectorRegistry:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connectors: dict[str, Connector] = {}
        self._manifests: dict[str, ConnectorManifest] = {}

    async def register(self, connector: Connector) -> None:
        async with self._lock:
            cid = connector.manifest.connector_id
            if cid in self._connectors:
                raise ValueError(f"Connector already registered: {cid}")
            self._connectors[cid] = connector
            self._manifests[cid] = connector.manifest

    async def unregister(self, connector_id: str) -> Optional[Connector]:
        async with self._lock:
            connector = self._connectors.pop(connector_id, None)
            self._manifests.pop(connector_id, None)
            return connector

    def lookup(self, connector_id: str) -> Optional[Connector]:
        return self._connectors.get(connector_id)

    def list_connectors(self) -> list[Connector]:
        return list(self._connectors.values())

    def find_by_capability(self, capability: ConnectorCapability) -> list[Connector]:
        return [c for c in self._connectors.values() if c.supports(capability)]

    def get_health(self, connector_id: str) -> Optional[ConnectorHealth]:
        connector = self._connectors.get(connector_id)
        if connector is None:
            return None
        return self._compute_health_sync(connector)

    @staticmethod
    def _compute_health_sync(connector: Connector) -> ConnectorHealth:
        return ConnectorHealth(
            connected=connector.state in (ConnectorState.CONNECTED, ConnectorState.READY),
            latency=0.0,
            last_error="",
            uptime=0.0,
            health_score=1.0 if connector.state == ConnectorState.READY else 0.5,
        )

    @property
    def count(self) -> int:
        return len(self._connectors)


# ======================================================================
# ConnectorFactory
# ======================================================================


class ConnectorFactory:
    def __init__(self, registry: ConnectorRegistry) -> None:
        self._registry = registry
        self._logger = logging.getLogger(__name__)

    def create_connector(
        self,
        connector_class: type[Connector],
        manifest: ConnectorManifest,
    ) -> Connector:
        errors = self.validate_manifest(manifest)
        if errors:
            raise ValueError(f"Invalid connector manifest: {'; '.join(errors)}")
        instance = connector_class(manifest)
        return instance

    async def register_connector(
        self,
        connector_class: type[Connector],
        manifest: ConnectorManifest,
    ) -> Connector:
        connector = self.create_connector(connector_class, manifest)
        await self._registry.register(connector)
        return connector

    def validate_manifest(self, manifest: ConnectorManifest) -> list[str]:
        errors: list[str] = []
        if not manifest.connector_id:
            errors.append("connector_id is required")
        if not manifest.name:
            errors.append("name is required")
        if not manifest.version:
            errors.append("version is required")
        return errors


# ======================================================================
# ConnectorMetrics
# ======================================================================


class ConnectorMetrics:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._connections = 0
        self._disconnections = 0
        self._auth_failures = 0
        self._successful_executions = 0
        self._failed_executions = 0
        self._total_latency = 0.0
        self._execution_count = 0
        self._active_sessions = 0

    async def record_connection(self) -> None:
        async with self._lock:
            self._connections += 1

    async def record_disconnection(self) -> None:
        async with self._lock:
            self._disconnections += 1

    async def record_auth_failure(self) -> None:
        async with self._lock:
            self._auth_failures += 1

    async def record_execution(self, duration: float, success: bool) -> None:
        async with self._lock:
            self._execution_count += 1
            self._total_latency += duration
            if success:
                self._successful_executions += 1
            else:
                self._failed_executions += 1

    async def record_session_start(self) -> None:
        async with self._lock:
            self._active_sessions += 1

    async def record_session_end(self) -> None:
        async with self._lock:
            if self._active_sessions > 0:
                self._active_sessions -= 1

    @property
    def connections(self) -> int:
        return self._connections

    @property
    def disconnections(self) -> int:
        return self._disconnections

    @property
    def auth_failures(self) -> int:
        return self._auth_failures

    @property
    def successful_executions(self) -> int:
        return self._successful_executions

    @property
    def failed_executions(self) -> int:
        return self._failed_executions

    @property
    def average_latency(self) -> float:
        if self._execution_count == 0:
            return 0.0
        return self._total_latency / self._execution_count

    @property
    def active_sessions(self) -> int:
        return self._active_sessions

    def snapshot(self) -> dict[str, Any]:
        return {
            "connections": self._connections,
            "disconnections": self._disconnections,
            "auth_failures": self._auth_failures,
            "successful_executions": self._successful_executions,
            "failed_executions": self._failed_executions,
            "average_latency": self.average_latency,
            "active_sessions": self._active_sessions,
        }


# ======================================================================
# ConnectorEventBridge
# ======================================================================


class ConnectorEventBridge:
    def __init__(self, event_bus: Any) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            from atlas_core.interfaces.events import Event, EventCategory
            event = Event(
                source="connectors",
                category=EventCategory.CONNECTOR,
                payload={"event_type": event_type, **payload},
            )
            await self._event_bus.publish(event)
        except Exception:
            self._logger.exception("Failed to publish connector event")

    async def connector_registered(self, connector_id: str, name: str) -> None:
        await self.publish("CONNECTOR_REGISTERED", {"connector_id": connector_id, "name": name})

    async def connector_connected(self, connector_id: str) -> None:
        await self.publish("CONNECTOR_CONNECTED", {"connector_id": connector_id})

    async def connector_disconnected(self, connector_id: str) -> None:
        await self.publish("CONNECTOR_DISCONNECTED", {"connector_id": connector_id})

    async def connector_authenticated(self, connector_id: str) -> None:
        await self.publish("CONNECTOR_AUTHENTICATED", {"connector_id": connector_id})

    async def connector_executed(self, connector_id: str, operation: str) -> None:
        await self.publish("CONNECTOR_EXECUTED", {"connector_id": connector_id, "operation": operation})

    async def connector_failed(self, connector_id: str, error: str) -> None:
        await self.publish("CONNECTOR_FAILED", {"connector_id": connector_id, "error": error})

    async def connector_health_changed(self, connector_id: str, health: ConnectorHealth) -> None:
        await self.publish("CONNECTOR_HEALTH_CHANGED", {"connector_id": connector_id, "health": health})


# ======================================================================
# ConnectorManager (IService)
# ======================================================================


class ConnectorManager(IService):
    def __init__(self, event_bus: Any) -> None:
        self._event_bus = event_bus
        self._state = ServiceState.CREATED
        self._logger = logging.getLogger(__name__)
        self._registry = ConnectorRegistry()
        self._factory = ConnectorFactory(self._registry)
        self._metrics = ConnectorMetrics()
        self._event_bridge = ConnectorEventBridge(event_bus)
        self._sessions: dict[str, ConnectorSession] = {}
        self._sessions_lock = asyncio.Lock()

    @property
    def name(self) -> str:
        return "connector_manager"

    @property
    def registry(self) -> ConnectorRegistry:
        return self._registry

    @property
    def factory(self) -> ConnectorFactory:
        return self._factory

    @property
    def metrics(self) -> ConnectorMetrics:
        return self._metrics

    async def initialize(self) -> None:
        self._state = ServiceState.INITIALIZED
        self._logger.info("Connector Manager initialized")

    async def start(self) -> None:
        self._state = ServiceState.RUNNING
        self._logger.info("Connector Manager started")

    async def stop(self) -> None:
        self._state = ServiceState.STOPPED
        for connector in self._registry.list_connectors():
            try:
                if connector.state in (ConnectorState.CONNECTED, ConnectorState.READY):
                    await connector.disconnect()
            except Exception:
                self._logger.exception("Error disconnecting %s", connector.manifest.connector_id)
        self._logger.info("Connector Manager stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=self._state,
            message=f"Connector Manager: {self._registry.count} connector(s)",
            metadata={
                "connectors": self._registry.count,
                "active_sessions": len(self._sessions),
                **self._metrics.snapshot(),
            },
        )

    async def register_connector(
        self,
        connector_class: type[Connector],
        manifest: ConnectorManifest,
    ) -> Connector:
        connector = await self._factory.register_connector(connector_class, manifest)
        await self._event_bridge.connector_registered(manifest.connector_id, manifest.name)
        return connector

    async def remove_connector(self, connector_id: str) -> Optional[Connector]:
        connector = await self._registry.unregister(connector_id)
        if connector is not None and connector.state in (ConnectorState.CONNECTED, ConnectorState.READY):
            try:
                await connector.disconnect()
            except Exception:
                self._logger.exception("Error disconnecting %s", connector_id)
        return connector

    async def connect(self, connector_id: str, credentials: ConnectorCredentials | None = None) -> bool:
        connector = self._registry.lookup(connector_id)
        if connector is None:
            raise ValueError(f"Connector not found: {connector_id}")
        await self._metrics.record_connection()
        result = await connector.connect()
        if result:
            await self._event_bridge.connector_connected(connector_id)
            if credentials is not None:
                auth_ok = await connector.authenticate(credentials)
                if auth_ok:
                    await self._event_bridge.connector_authenticated(connector_id)
                else:
                    await self._metrics.record_auth_failure()
        else:
            await self._metrics.record_disconnection()
            await self._event_bridge.connector_failed(connector_id, "Connection failed")
        return result

    async def disconnect(self, connector_id: str) -> bool:
        connector = self._registry.lookup(connector_id)
        if connector is None:
            raise ValueError(f"Connector not found: {connector_id}")
        await self._metrics.record_disconnection()
        result = await connector.disconnect()
        await self._event_bridge.connector_disconnected(connector_id)
        return result

    async def execute(self, connector_id: str, operation: str, **kwargs: Any) -> dict[str, Any]:
        connector = self._registry.lookup(connector_id)
        if connector is None:
            raise ValueError(f"Connector not found: {connector_id}")
        start = time.monotonic()
        try:
            result = await connector.execute(operation, **kwargs)
            duration = time.monotonic() - start
            await self._metrics.record_execution(duration, True)
            await self._event_bridge.connector_executed(connector_id, operation)
            return result
        except Exception as e:
            duration = time.monotonic() - start
            await self._metrics.record_execution(duration, False)
            await self._event_bridge.connector_failed(connector_id, str(e))
            raise

    async def create_session(self, connector_id: str) -> ConnectorSession:
        session = ConnectorSession(
            session_id=str(uuid.uuid4()),
            connector_id=connector_id,
        )
        async with self._sessions_lock:
            self._sessions[session.session_id] = session
        await self._metrics.record_session_start()
        return session

    async def close_session(self, session_id: str) -> None:
        async with self._sessions_lock:
            self._sessions.pop(session_id, None)
        await self._metrics.record_session_end()

    def list_connectors(self) -> list[Connector]:
        return self._registry.list_connectors()


# ======================================================================
# Reference Connectors
# ======================================================================

class _BaseReferenceConnector(Connector):
    """Base class for reference (stub) connectors."""

    def __init__(self, manifest: ConnectorManifest) -> None:
        super().__init__(manifest)
        self._authenticated = False

    async def connect(self) -> bool:
        self._state = ConnectorState.CONNECTING
        await asyncio.sleep(0.01)
        self._state = ConnectorState.CONNECTED
        self._connected_at = time.time()
        return True

    async def disconnect(self) -> bool:
        self._state = ConnectorState.DISCONNECTING
        await asyncio.sleep(0.01)
        self._state = ConnectorState.DISCONNECTED
        self._authenticated = False
        return True

    async def authenticate(self, credentials: ConnectorCredentials) -> bool:
        self._state = ConnectorState.AUTHENTICATING
        await asyncio.sleep(0.01)
        self._authenticated = True
        self._state = ConnectorState.READY
        return True

    async def validate(self) -> list[str]:
        errors: list[str] = []
        if not self._manifest.connector_id:
            errors.append("connector_id is required")
        return errors

    async def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(
            connected=self._state in (ConnectorState.CONNECTED, ConnectorState.READY),
            latency=0.0,
            last_error=self._last_error,
            uptime=(time.time() - self._connected_at) if self._connected_at else 0.0,
            health_score=1.0 if self._state == ConnectorState.READY else 0.5,
        )

    def supports(self, capability: ConnectorCapability) -> bool:
        return capability in self._manifest.capabilities


class FilesystemConnector(_BaseReferenceConnector):
    async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "connector": self._manifest.connector_id,
            "operation": operation,
            "status": "ok",
            "stub": True,
        }


class RESTConnector(_BaseReferenceConnector):
    async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "connector": self._manifest.connector_id,
            "operation": operation,
            "status": "ok",
            "stub": True,
        }


class GitHubConnector(_BaseReferenceConnector):
    async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "connector": self._manifest.connector_id,
            "operation": operation,
            "status": "ok",
            "stub": True,
        }


class DatabaseConnector(_BaseReferenceConnector):
    async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "connector": self._manifest.connector_id,
            "operation": operation,
            "status": "ok",
            "stub": True,
        }


class EmailConnector(_BaseReferenceConnector):
    async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "connector": self._manifest.connector_id,
            "operation": operation,
            "status": "ok",
            "stub": True,
        }


class WebhookConnector(_BaseReferenceConnector):
    async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
        return {
            "connector": self._manifest.connector_id,
            "operation": operation,
            "status": "ok",
            "stub": True,
        }
