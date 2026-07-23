"""Comprehensive tests for the Connector Framework."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from atlas_core.connectors import (
    Connector,
    ConnectorCapability,
    ConnectorCredentials,
    ConnectorEventBridge,
    ConnectorFactory,
    ConnectorHealth,
    ConnectorManager,
    ConnectorManifest,
    ConnectorMetrics,
    ConnectorRegistry,
    ConnectorSession,
    ConnectorState,
    DatabaseConnector,
    EmailConnector,
    FilesystemConnector,
    GitHubConnector,
    RESTConnector,
    WebhookConnector,
    _BaseReferenceConnector,
)
from atlas_core.interfaces import ServiceState
from atlas_core.interfaces.events import EventCategory


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def sample_manifest() -> ConnectorManifest:
    return ConnectorManifest(
        connector_id="test_fs",
        name="Test Filesystem",
        version="1.0.0",
        author="Tester",
        capabilities=(ConnectorCapability.FILESYSTEM,),
        supported_operations=("read", "write", "list"),
        configuration_schema={"root_path": {"type": "string"}},
    )


@pytest.fixture
def fs_connector(sample_manifest: ConnectorManifest) -> FilesystemConnector:
    return FilesystemConnector(sample_manifest)


@pytest.fixture
def rest_manifest() -> ConnectorManifest:
    return ConnectorManifest(
        connector_id="test_rest",
        name="Test REST",
        version="1.0.0",
        capabilities=(ConnectorCapability.REST_API, ConnectorCapability.CUSTOM),
    )


@pytest.fixture
def rest_connector(rest_manifest: ConnectorManifest) -> RESTConnector:
    return RESTConnector(rest_manifest)


@pytest.fixture
def github_manifest() -> ConnectorManifest:
    return ConnectorManifest(
        connector_id="test_gh",
        name="Test GitHub",
        capabilities=(ConnectorCapability.GITHUB,),
    )


@pytest.fixture
def github_connector(github_manifest: ConnectorManifest) -> GitHubConnector:
    return GitHubConnector(github_manifest)


@pytest.fixture
def db_manifest() -> ConnectorManifest:
    return ConnectorManifest(
        connector_id="test_db",
        name="Test Database",
        capabilities=(ConnectorCapability.DATABASE,),
    )


@pytest.fixture
def db_connector(db_manifest: ConnectorManifest) -> DatabaseConnector:
    return DatabaseConnector(db_manifest)


@pytest.fixture
def email_manifest() -> ConnectorManifest:
    return ConnectorManifest(
        connector_id="test_email",
        name="Test Email",
        capabilities=(ConnectorCapability.EMAIL,),
    )


@pytest.fixture
def email_connector(email_manifest: ConnectorManifest) -> EmailConnector:
    return EmailConnector(email_manifest)


@pytest.fixture
def webhook_manifest() -> ConnectorManifest:
    return ConnectorManifest(
        connector_id="test_wh",
        name="Test Webhook",
        capabilities=(ConnectorCapability.WEBHOOK,),
    )


@pytest.fixture
def webhook_connector(webhook_manifest: ConnectorManifest) -> WebhookConnector:
    return WebhookConnector(webhook_manifest)


@pytest.fixture
def credentials() -> ConnectorCredentials:
    return ConnectorCredentials(api_key="sk-test-12345678")


@pytest.fixture
def registry() -> ConnectorRegistry:
    return ConnectorRegistry()


@pytest.fixture
def factory(registry: ConnectorRegistry) -> ConnectorFactory:
    return ConnectorFactory(registry)


@pytest.fixture
def metrics() -> ConnectorMetrics:
    return ConnectorMetrics()


@pytest.fixture
def connector_manager() -> ConnectorManager:
    from atlas_core.events import EventBus
    return ConnectorManager(EventBus())


# ======================================================================
# ConnectorState
# ======================================================================


class TestConnectorState:
    def test_enum_values(self) -> None:
        assert len(ConnectorState) == 7
        assert ConnectorState.DISCONNECTED.value == 1
        assert ConnectorState.CONNECTING.value == 2
        assert ConnectorState.CONNECTED.value == 3
        assert ConnectorState.AUTHENTICATING.value == 4
        assert ConnectorState.READY.value == 5
        assert ConnectorState.FAILED.value == 6
        assert ConnectorState.DISCONNECTING.value == 7


# ======================================================================
# ConnectorCapability
# ======================================================================


class TestConnectorCapability:
    def test_enum_values(self) -> None:
        assert len(ConnectorCapability) == 8
        assert ConnectorCapability.FILESYSTEM.name == "FILESYSTEM"
        assert ConnectorCapability.REST_API.name == "REST_API"
        assert ConnectorCapability.DATABASE.name == "DATABASE"
        assert ConnectorCapability.EMAIL.name == "EMAIL"
        assert ConnectorCapability.WEBHOOK.name == "WEBHOOK"
        assert ConnectorCapability.GITHUB.name == "GITHUB"
        assert ConnectorCapability.LOCAL_PROCESS.name == "LOCAL_PROCESS"
        assert ConnectorCapability.CUSTOM.name == "CUSTOM"


# ======================================================================
# ConnectorManifest
# ======================================================================


class TestConnectorManifest:
    def test_frozen(self) -> None:
        m = ConnectorManifest(connector_id="x", name="X")
        with pytest.raises(AttributeError):
            m.name = "Y"  # type: ignore[misc]

    def test_defaults(self) -> None:
        m = ConnectorManifest(connector_id="x", name="X")
        assert m.version == "0.1.0"
        assert m.author == ""
        assert m.capabilities == ()
        assert m.supported_operations == ()
        assert m.configuration_schema == {}

    def test_full(self) -> None:
        m = ConnectorManifest(
            connector_id="fs1",
            name="FS One",
            version="2.0.0",
            author="Dev",
            capabilities=(ConnectorCapability.FILESYSTEM,),
            supported_operations=("read",),
            configuration_schema={"path": "string"},
        )
        assert m.connector_id == "fs1"
        assert m.name == "FS One"
        assert m.version == "2.0.0"
        assert m.author == "Dev"
        assert ConnectorCapability.FILESYSTEM in m.capabilities
        assert "read" in m.supported_operations
        assert m.configuration_schema["path"] == "string"


# ======================================================================
# ConnectorSession
# ======================================================================


class TestConnectorSession:
    def test_frozen(self) -> None:
        s = ConnectorSession(session_id="s1", connector_id="c1")
        with pytest.raises(AttributeError):
            s.connector_id = "c2"  # type: ignore[misc]

    def test_defaults(self) -> None:
        s = ConnectorSession(session_id="s1", connector_id="c1")
        assert s.authenticated is False
        assert s.metadata == {}

    def test_full(self) -> None:
        s = ConnectorSession(
            session_id="s1",
            connector_id="c1",
            authenticated=True,
            metadata={"key": "val"},
        )
        assert s.session_id == "s1"
        assert s.connector_id == "c1"
        assert s.authenticated is True
        assert s.metadata["key"] == "val"


# ======================================================================
# ConnectorCredentials
# ======================================================================


class TestConnectorCredentials:
    def test_api_key(self) -> None:
        c = ConnectorCredentials(api_key="sk-test-abcdefgh")
        assert c.has_api_key is True
        assert c.has_token is False
        assert c.has_username is False
        assert c.has_password is False
        assert c.get_api_key() == "sk-test-abcdefgh"
        assert c.masked_api_key == "sk-t***efgh"

    def test_token(self) -> None:
        c = ConnectorCredentials(token="ghp_test_token_12345")
        assert c.has_token is True
        assert c.has_api_key is False
        assert c.get_token() == "ghp_test_token_12345"

    def test_username_password(self) -> None:
        c = ConnectorCredentials(username="admin", password="secret123")
        assert c.has_username is True
        assert c.has_password is True
        assert c.get_username() == "admin"
        assert c.get_password() == "secret123"

    def test_extra(self) -> None:
        c = ConnectorCredentials(tenant="mytenant", region="us-east")
        assert c.get_extra("tenant") == "mytenant"
        assert c.get_extra("region") == "us-east"
        assert c.get_extra("missing") is None

    def test_masked_api_key_short(self) -> None:
        c = ConnectorCredentials(api_key="short")
        assert c.masked_api_key == "***"

    def test_masked_api_key_empty(self) -> None:
        c = ConnectorCredentials()
        assert c.masked_api_key == ""

    def test_masked_token_short(self) -> None:
        c = ConnectorCredentials(token="short")
        assert c.masked_token == "***"

    def test_masked_token_empty(self) -> None:
        c = ConnectorCredentials()
        assert c.masked_token == ""

    def test_lock(self) -> None:
        c = ConnectorCredentials(api_key="key")
        assert c.locked is False
        c.lock()
        assert c.locked is True

    def test_no_secrets_in_repr(self) -> None:
        c = ConnectorCredentials(api_key="SUPER_SECRET_KEY")
        r = repr(c)
        assert "SUPER_SECRET_KEY" not in r


# ======================================================================
# ConnectorHealth
# ======================================================================


class TestConnectorHealth:
    def test_defaults(self) -> None:
        h = ConnectorHealth()
        assert h.connected is False
        assert h.latency == 0.0
        assert h.last_error == ""
        assert h.uptime == 0.0
        assert h.health_score == 0.0

    def test_full(self) -> None:
        h = ConnectorHealth(
            connected=True,
            latency=12.5,
            last_error="",
            uptime=3600.0,
            health_score=0.95,
        )
        assert h.connected is True
        assert h.latency == 12.5
        assert h.health_score == 0.95


# ======================================================================
# _BaseReferenceConnector
# ======================================================================


class TestBaseReferenceConnector:
    async def test_initial_state(self, fs_connector: FilesystemConnector) -> None:
        assert fs_connector.state == ConnectorState.DISCONNECTED

    async def test_manifest_property(self, fs_connector: FilesystemConnector, sample_manifest: ConnectorManifest) -> None:
        assert fs_connector.manifest is sample_manifest
        assert fs_connector.manifest.connector_id == "test_fs"

    async def test_connect(self, fs_connector: FilesystemConnector) -> None:
        result = await fs_connector.connect()
        assert result is True
        assert fs_connector.state == ConnectorState.CONNECTED

    async def test_disconnect(self, fs_connector: FilesystemConnector) -> None:
        await fs_connector.connect()
        result = await fs_connector.disconnect()
        assert result is True
        assert fs_connector.state == ConnectorState.DISCONNECTED

    async def test_authenticate(self, fs_connector: FilesystemConnector, credentials: ConnectorCredentials) -> None:
        await fs_connector.connect()
        result = await fs_connector.authenticate(credentials)
        assert result is True
        assert fs_connector.state == ConnectorState.READY

    async def test_validate_ok(self, fs_connector: FilesystemConnector) -> None:
        errors = await fs_connector.validate()
        assert errors == []

    async def test_health_check_disconnected(self, fs_connector: FilesystemConnector) -> None:
        health = await fs_connector.health_check()
        assert health.connected is False
        assert health.health_score == 0.5

    async def test_health_check_ready(self, fs_connector: FilesystemConnector, credentials: ConnectorCredentials) -> None:
        await fs_connector.connect()
        await fs_connector.authenticate(credentials)
        health = await fs_connector.health_check()
        assert health.connected is True
        assert health.health_score == 1.0

    async def test_supports(self, fs_connector: FilesystemConnector) -> None:
        assert fs_connector.supports(ConnectorCapability.FILESYSTEM) is True
        assert fs_connector.supports(ConnectorCapability.REST_API) is False
        assert fs_connector.supports(ConnectorCapability.DATABASE) is False

    async def test_execute_disconnected(self, fs_connector: FilesystemConnector) -> None:
        result = await fs_connector.execute("read", path="/test")
        assert result["stub"] is True
        assert result["operation"] == "read"


# ======================================================================
# Reference Connectors - execute
# ======================================================================


class TestFilesystemConnector:
    async def test_execute(self, fs_connector: FilesystemConnector) -> None:
        result = await fs_connector.execute("list", path="/")
        assert result["connector"] == "test_fs"
        assert result["operation"] == "list"
        assert result["status"] == "ok"


class TestRESTConnector:
    async def test_execute(self, rest_connector: RESTConnector) -> None:
        result = await rest_connector.execute("GET", url="https://example.com")
        assert result["connector"] == "test_rest"
        assert result["operation"] == "GET"

    async def test_supports(self, rest_connector: RESTConnector) -> None:
        assert rest_connector.supports(ConnectorCapability.REST_API) is True
        assert rest_connector.supports(ConnectorCapability.CUSTOM) is True
        assert rest_connector.supports(ConnectorCapability.FILESYSTEM) is False


class TestGitHubConnector:
    async def test_execute(self, github_connector: GitHubConnector) -> None:
        result = await github_connector.execute("list_repos")
        assert result["connector"] == "test_gh"

    async def test_supports(self, github_connector: GitHubConnector) -> None:
        assert github_connector.supports(ConnectorCapability.GITHUB) is True
        assert github_connector.supports(ConnectorCapability.REST_API) is False


class TestDatabaseConnector:
    async def test_execute(self, db_connector: DatabaseConnector) -> None:
        result = await db_connector.execute("query", sql="SELECT 1")
        assert result["connector"] == "test_db"

    async def test_supports(self, db_connector: DatabaseConnector) -> None:
        assert db_connector.supports(ConnectorCapability.DATABASE) is True
        assert db_connector.supports(ConnectorCapability.EMAIL) is False


class TestEmailConnector:
    async def test_execute(self, email_connector: EmailConnector) -> None:
        result = await email_connector.execute("send", to="test@example.com")
        assert result["connector"] == "test_email"

    async def test_supports(self, email_connector: EmailConnector) -> None:
        assert email_connector.supports(ConnectorCapability.EMAIL) is True
        assert email_connector.supports(ConnectorCapability.FILESYSTEM) is False


class TestWebhookConnector:
    async def test_execute(self, webhook_connector: WebhookConnector) -> None:
        result = await webhook_connector.execute("trigger", event="push")
        assert result["connector"] == "test_wh"

    async def test_supports(self, webhook_connector: WebhookConnector) -> None:
        assert webhook_connector.supports(ConnectorCapability.WEBHOOK) is True
        assert webhook_connector.supports(ConnectorCapability.GITHUB) is False


# ======================================================================
# ConnectorRegistry
# ======================================================================


class TestConnectorRegistry:
    async def test_register(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector) -> None:
        await registry.register(fs_connector)
        assert registry.count == 1

    async def test_register_duplicate_raises(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector) -> None:
        await registry.register(fs_connector)
        with pytest.raises(ValueError, match="already registered"):
            await registry.register(fs_connector)

    async def test_unregister(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector) -> None:
        await registry.register(fs_connector)
        result = await registry.unregister("test_fs")
        assert result is fs_connector
        assert registry.count == 0

    async def test_unregister_missing(self, registry: ConnectorRegistry) -> None:
        result = await registry.unregister("nonexistent")
        assert result is None

    async def test_lookup(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector) -> None:
        await registry.register(fs_connector)
        assert registry.lookup("test_fs") is fs_connector
        assert registry.lookup("missing") is None

    async def test_list_connectors(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector, rest_connector: RESTConnector) -> None:
        await registry.register(fs_connector)
        await registry.register(rest_connector)
        connectors = registry.list_connectors()
        assert len(connectors) == 2
        assert fs_connector in connectors
        assert rest_connector in connectors

    async def test_find_by_capability(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector, rest_connector: RESTConnector) -> None:
        await registry.register(fs_connector)
        await registry.register(rest_connector)
        fs_list = registry.find_by_capability(ConnectorCapability.FILESYSTEM)
        assert len(fs_list) == 1
        assert fs_list[0] is fs_connector
        rest_list = registry.find_by_capability(ConnectorCapability.REST_API)
        assert len(rest_list) == 1
        assert rest_list[0] is rest_connector
        db_list = registry.find_by_capability(ConnectorCapability.DATABASE)
        assert db_list == []

    async def test_get_health(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector) -> None:
        await registry.register(fs_connector)
        health = registry.get_health("test_fs")
        assert health is not None
        assert health.connected is False
        assert registry.get_health("missing") is None

    async def test_get_health_after_connect(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector, credentials: ConnectorCredentials) -> None:
        await registry.register(fs_connector)
        await fs_connector.connect()
        await fs_connector.authenticate(credentials)
        health = registry.get_health("test_fs")
        assert health is not None
        assert health.connected is True
        assert health.health_score == 1.0

    async def test_count(self, registry: ConnectorRegistry, fs_connector: FilesystemConnector) -> None:
        assert registry.count == 0
        await registry.register(fs_connector)
        assert registry.count == 1


# ======================================================================
# ConnectorFactory
# ======================================================================


class TestConnectorFactory:
    async def test_create_connector(self, factory: ConnectorFactory, sample_manifest: ConnectorManifest) -> None:
        connector = factory.create_connector(FilesystemConnector, sample_manifest)
        assert isinstance(connector, FilesystemConnector)
        assert connector.manifest.connector_id == "test_fs"

    async def test_create_connector_invalid_manifest(self, factory: ConnectorFactory) -> None:
        invalid = ConnectorManifest(connector_id="", name="")
        with pytest.raises(ValueError, match="Invalid connector manifest"):
            factory.create_connector(FilesystemConnector, invalid)

    async def test_register_connector(self, factory: ConnectorFactory, sample_manifest: ConnectorManifest) -> None:
        connector = await factory.register_connector(FilesystemConnector, sample_manifest)
        assert connector is not None
        assert factory._registry.count == 1

    async def test_validate_manifest_valid(self, factory: ConnectorFactory, sample_manifest: ConnectorManifest) -> None:
        errors = factory.validate_manifest(sample_manifest)
        assert errors == []

    async def test_validate_manifest_missing_id(self, factory: ConnectorFactory) -> None:
        m = ConnectorManifest(connector_id="", name="Test")
        errors = factory.validate_manifest(m)
        assert "connector_id is required" in errors

    async def test_validate_manifest_missing_name(self, factory: ConnectorFactory) -> None:
        m = ConnectorManifest(connector_id="c1", name="")
        errors = factory.validate_manifest(m)
        assert "name is required" in errors

    async def test_validate_manifest_missing_version(self, factory: ConnectorFactory) -> None:
        m = ConnectorManifest(connector_id="c1", name="Test", version="")
        errors = factory.validate_manifest(m)
        assert "version is required" in errors


# ======================================================================
# ConnectorMetrics
# ======================================================================


class TestConnectorMetrics:
    async def test_initial_state(self, metrics: ConnectorMetrics) -> None:
        assert metrics.connections == 0
        assert metrics.disconnections == 0
        assert metrics.auth_failures == 0
        assert metrics.successful_executions == 0
        assert metrics.failed_executions == 0
        assert metrics.average_latency == 0.0
        assert metrics.active_sessions == 0

    async def test_record_connection(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_connection()
        assert metrics.connections == 1

    async def test_record_disconnection(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_disconnection()
        assert metrics.disconnections == 1

    async def test_record_auth_failure(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_auth_failure()
        assert metrics.auth_failures == 1

    async def test_record_successful_execution(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_execution(0.5, True)
        assert metrics.successful_executions == 1
        assert metrics.failed_executions == 0
        assert metrics.average_latency == 0.5

    async def test_record_failed_execution(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_execution(1.0, False)
        assert metrics.failed_executions == 1
        assert metrics.successful_executions == 0
        assert metrics.average_latency == 1.0

    async def test_average_latency_multiple(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_execution(1.0, True)
        await metrics.record_execution(3.0, True)
        assert metrics.average_latency == 2.0

    async def test_record_session_start_end(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_session_start()
        assert metrics.active_sessions == 1
        await metrics.record_session_start()
        assert metrics.active_sessions == 2
        await metrics.record_session_end()
        assert metrics.active_sessions == 1
        await metrics.record_session_end()
        assert metrics.active_sessions == 0

    async def test_record_session_end_below_zero(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_session_end()
        assert metrics.active_sessions == 0

    async def test_snapshot(self, metrics: ConnectorMetrics) -> None:
        await metrics.record_connection()
        await metrics.record_execution(2.0, True)
        await metrics.record_session_start()
        snap = metrics.snapshot()
        assert snap["connections"] == 1
        assert snap["successful_executions"] == 1
        assert snap["average_latency"] == 2.0
        assert snap["active_sessions"] == 1


# ======================================================================
# ConnectorEventBridge
# ======================================================================


class TestConnectorEventBridge:
    @pytest.fixture
    def event_bus(self) -> Any:
        from atlas_core.events import EventBus
        return EventBus()

    @pytest.fixture
    def bridge(self, event_bus: Any) -> ConnectorEventBridge:
        return ConnectorEventBridge(event_bus)

    async def test_connector_registered(self, bridge: ConnectorEventBridge, event_bus: Any) -> None:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("connector", handler)
        await bridge.connector_registered("c1", "Test")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "CONNECTOR_REGISTERED"

    async def test_connector_connected(self, bridge: ConnectorEventBridge, event_bus: Any) -> None:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("connector", handler)
        await bridge.connector_connected("c1")
        assert len(received) == 1

    async def test_connector_disconnected(self, bridge: ConnectorEventBridge, event_bus: Any) -> None:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("connector", handler)
        await bridge.connector_disconnected("c1")
        assert len(received) == 1

    async def test_connector_authenticated(self, bridge: ConnectorEventBridge, event_bus: Any) -> None:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("connector", handler)
        await bridge.connector_authenticated("c1")
        assert len(received) == 1

    async def test_connector_executed(self, bridge: ConnectorEventBridge, event_bus: Any) -> None:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("connector", handler)
        await bridge.connector_executed("c1", "read")
        assert len(received) == 1

    async def test_connector_failed(self, bridge: ConnectorEventBridge, event_bus: Any) -> None:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("connector", handler)
        await bridge.connector_failed("c1", "timeout")
        assert len(received) == 1

    async def test_connector_health_changed(self, bridge: ConnectorEventBridge, event_bus: Any) -> None:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("connector", handler)
        health = ConnectorHealth(connected=True)
        await bridge.connector_health_changed("c1", health)
        assert len(received) == 1

    async def test_publish_creates_event(self, bridge: ConnectorEventBridge, event_bus: Any) -> None:
        received: list = []
        async def handler(event: Any) -> None:
            received.append(event)
        event_bus.subscribe("connector", handler)
        await bridge.publish("TEST_EVENT", {"key": "val"})
        assert len(received) == 1
        assert received[0].category == EventCategory.CONNECTOR
        assert received[0].source == "connectors"
        assert received[0].payload["key"] == "val"

    async def test_publish_no_event_bus_failure(self) -> None:
        class FakeBus:
            async def publish(self, event: Any) -> None:
                raise RuntimeError("bus down")
        bridge = ConnectorEventBridge(FakeBus())
        await bridge.publish("TEST", {})  # should not raise


# ======================================================================
# ConnectorManager (IService)
# ======================================================================


class TestConnectorManager:
    async def test_initial_state(self, connector_manager: ConnectorManager) -> None:
        assert connector_manager.name == "connector_manager"
        assert connector_manager.registry.count == 0

    async def test_iservice_lifecycle(self, connector_manager: ConnectorManager) -> None:
        await connector_manager.initialize()
        await connector_manager.start()
        await connector_manager.stop()

    async def test_register_connector(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        connector = await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        assert connector.manifest.connector_id == "test_fs"
        assert connector_manager.registry.count == 1

    async def test_remove_connector(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        removed = await connector_manager.remove_connector("test_fs")
        assert removed is not None
        assert connector_manager.registry.count == 0

    async def test_remove_missing_connector(self, connector_manager: ConnectorManager) -> None:
        result = await connector_manager.remove_connector("nonexistent")
        assert result is None

    async def test_connect(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        connector = await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        result = await connector_manager.connect("test_fs")
        assert result is True
        assert connector.state == ConnectorState.CONNECTED

    async def test_connect_with_credentials(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest, credentials: ConnectorCredentials) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        result = await connector_manager.connect("test_fs", credentials)
        assert result is True
        assert connector_manager.registry.lookup("test_fs").state == ConnectorState.READY

    async def test_connect_nonexistent_raises(self, connector_manager: ConnectorManager) -> None:
        with pytest.raises(ValueError, match="Connector not found"):
            await connector_manager.connect("missing")

    async def test_disconnect(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        await connector_manager.connect("test_fs")
        result = await connector_manager.disconnect("test_fs")
        assert result is True
        assert connector_manager.registry.lookup("test_fs").state == ConnectorState.DISCONNECTED

    async def test_disconnect_nonexistent_raises(self, connector_manager: ConnectorManager) -> None:
        with pytest.raises(ValueError, match="Connector not found"):
            await connector_manager.disconnect("missing")

    async def test_execute(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        result = await connector_manager.execute("test_fs", "read", path="/test")
        assert result["status"] == "ok"
        assert result["operation"] == "read"

    async def test_execute_nonexistent_raises(self, connector_manager: ConnectorManager) -> None:
        with pytest.raises(ValueError, match="Connector not found"):
            await connector_manager.execute("missing", "op")

    async def test_list_connectors(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest, rest_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        await connector_manager.register_connector(RESTConnector, rest_manifest)
        connectors = connector_manager.list_connectors()
        assert len(connectors) == 2

    async def test_create_session(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        session = await connector_manager.create_session("test_fs")
        assert session.connector_id == "test_fs"
        assert session.authenticated is False
        assert connector_manager.metrics.active_sessions == 1

    async def test_create_session_nonexistent(self, connector_manager: ConnectorManager) -> None:
        session = await connector_manager.create_session("missing")
        assert session.connector_id == "missing"

    async def test_close_session(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        session = await connector_manager.create_session("test_fs")
        await connector_manager.close_session(session.session_id)
        assert connector_manager.metrics.active_sessions == 0

    async def test_health_check(self, connector_manager: ConnectorManager) -> None:
        health = await connector_manager.health_check()
        assert health.healthy is True
        assert "Connector Manager" in health.message
        assert health.metadata["connectors"] == 0

    async def test_stop_disconnects_connectors(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        connector = await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        await connector_manager.connect("test_fs")
        assert connector.state == ConnectorState.CONNECTED
        await connector_manager.stop()
        assert connector.state == ConnectorState.DISCONNECTED


# ======================================================================
# Kernel Integration
# ======================================================================


class TestKernelIntegration:
    @pytest.fixture
    def kernel(self, tmp_path: Path):
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

    async def test_kernel_boot_registers_connector_manager(self, kernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.registry.count == 13
        assert kernel.connector_manager is not None
        from atlas_core.connectors import ConnectorManager
        assert isinstance(kernel.connector_manager, ConnectorManager)

    async def test_kernel_before_init_raises(self):
        from atlas_core.kernel import AtlasKernel
        k = AtlasKernel()
        with pytest.raises(RuntimeError):
            _ = k.connector_manager

    async def test_connector_manager_property(self, kernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.connector_manager is not None
        assert isinstance(kernel.connector_manager, ConnectorManager)


# ======================================================================
# Thread Safety
# ======================================================================


class TestThreadSafety:
    async def test_registry_concurrent_register(self, registry: ConnectorRegistry) -> None:
        manifests = [
            ConnectorManifest(connector_id=f"c{i}", name=f"C{i}")
            for i in range(10)
        ]
        async def register_all() -> None:
            for m in manifests:
                await registry.register(FilesystemConnector(m))
        async def read_all() -> None:
            for _ in range(100):
                _ = registry.list_connectors()
                _ = registry.count
        await asyncio.gather(register_all(), read_all())
        assert registry.count == 10

    async def test_metrics_concurrent_access(self, metrics: ConnectorMetrics) -> None:
        async def record_many() -> None:
            for _ in range(100):
                await metrics.record_connection()
                await metrics.record_execution(0.1, True)
        async def read_many() -> None:
            for _ in range(100):
                _ = metrics.connections
                _ = metrics.average_latency
                _ = metrics.snapshot()
        await asyncio.gather(record_many(), read_many())
        assert metrics.connections == 100
        assert metrics.successful_executions == 100


# ======================================================================
# Failure Paths
# ======================================================================


class TestFailurePaths:
    async def test_connect_not_in_registry(self, connector_manager: ConnectorManager) -> None:
        with pytest.raises(ValueError):
            await connector_manager.connect("unknown")

    async def test_disconnect_not_in_registry(self, connector_manager: ConnectorManager) -> None:
        with pytest.raises(ValueError):
            await connector_manager.disconnect("unknown")

    async def test_execute_not_in_registry(self, connector_manager: ConnectorManager) -> None:
        with pytest.raises(ValueError):
            await connector_manager.execute("unknown", "op")

    async def test_factory_invalid_connector_class(self, factory: ConnectorFactory, sample_manifest: ConnectorManifest) -> None:
        class NotAConnector:
            pass
        with pytest.raises(TypeError):
            factory.create_connector(NotAConnector, sample_manifest)  # type: ignore[arg-type]

    async def test_remove_connector_disconnects(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        connector = await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        await connector_manager.connect("test_fs")
        assert connector.state == ConnectorState.CONNECTED
        removed = await connector_manager.remove_connector("test_fs")
        assert removed is not None
        assert removed.state == ConnectorState.DISCONNECTED

    async def test_connect_with_bad_credentials(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        class FailAuthConnector(_BaseReferenceConnector):
            async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
                return {"stub": True}
            async def authenticate(self, credentials: ConnectorCredentials) -> bool:
                self._state = ConnectorState.FAILED
                return False
        connector = await connector_manager.register_connector(
            FailAuthConnector,
            sample_manifest,
        )
        bad_creds = ConnectorCredentials(api_key="bad")
        result = await connector_manager.connect("test_fs", bad_creds)
        assert result is True
        assert connector.state == ConnectorState.FAILED


# ======================================================================
# EventCategory
# ======================================================================


class TestEventCategory:
    def test_connector_category_exists(self) -> None:
        assert EventCategory.CONNECTOR.value == "connector"


# ======================================================================
# ConnectorRegistry edge cases
# ======================================================================


class TestRegistryEdgeCases:
    async def test_empty_registry(self, registry: ConnectorRegistry) -> None:
        assert registry.count == 0
        assert registry.list_connectors() == []
        assert registry.find_by_capability(ConnectorCapability.FILESYSTEM) == []
        assert registry.get_health("anything") is None
        assert registry.lookup("anything") is None

    async def test_register_multiple(self, registry: ConnectorRegistry) -> None:
        for i in range(5):
            m = ConnectorManifest(connector_id=f"c{i}", name=f"C{i}")
            await registry.register(FilesystemConnector(m))
        assert registry.count == 5


# ======================================================================
# ConnectorManager edge cases
# ======================================================================


class TestManagerEdgeCases:
    async def test_remove_while_disconnected(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        removed = await connector_manager.remove_connector("test_fs")
        assert removed is not None
        assert removed.state == ConnectorState.DISCONNECTED

    async def test_connect_twice(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        await connector_manager.connect("test_fs")
        await connector_manager.connect("test_fs")
        connector = connector_manager.registry.lookup("test_fs")
        assert connector.state == ConnectorState.CONNECTED

    async def test_factory_property(self, connector_manager: ConnectorManager) -> None:
        assert connector_manager.factory is not None
        from atlas_core.connectors import ConnectorFactory
        assert isinstance(connector_manager.factory, ConnectorFactory)

    async def test_metrics_property(self, connector_manager: ConnectorManager) -> None:
        assert connector_manager.metrics is not None
        from atlas_core.connectors import ConnectorMetrics
        assert isinstance(connector_manager.metrics, ConnectorMetrics)

    async def test_stop_with_connected_connector(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        await connector_manager.connect("test_fs")
        await connector_manager.stop()
        connector = connector_manager.registry.lookup("test_fs")
        assert connector.state == ConnectorState.DISCONNECTED

    async def test_stop_with_failing_disconnect(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        class FailDisconnectConnector(_BaseReferenceConnector):
            async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
                return {"stub": True}
            async def disconnect(self) -> bool:
                raise RuntimeError("disconnect failed")
        await connector_manager.register_connector(FailDisconnectConnector, sample_manifest)
        await connector_manager.connect("test_fs")
        await connector_manager.stop()

    async def test_remove_connected_connector(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        await connector_manager.register_connector(FilesystemConnector, sample_manifest)
        await connector_manager.connect("test_fs")
        removed = await connector_manager.remove_connector("test_fs")
        assert removed is not None
        assert removed.state == ConnectorState.DISCONNECTED

    async def test_remove_failing_disconnect(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        class FailDisconnectConnector(_BaseReferenceConnector):
            async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
                return {"stub": True}
            async def disconnect(self) -> bool:
                raise RuntimeError("remove failed")
        await connector_manager.register_connector(FailDisconnectConnector, sample_manifest)
        await connector_manager.connect("test_fs")
        removed = await connector_manager.remove_connector("test_fs")
        assert removed is not None

    async def test_connect_fails(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        class FailConnectConnector(_BaseReferenceConnector):
            async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
                return {"stub": True}
            async def connect(self) -> bool:
                self._state = ConnectorState.FAILED
                return False
        await connector_manager.register_connector(FailConnectConnector, sample_manifest)
        result = await connector_manager.connect("test_fs")
        assert result is False

    async def test_execute_raises(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        class FailExecConnector(_BaseReferenceConnector):
            async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
                raise RuntimeError("execution error")
        await connector_manager.register_connector(FailExecConnector, sample_manifest)
        with pytest.raises(RuntimeError, match="execution error"):
            await connector_manager.execute("test_fs", "read")

    async def test_base_validate_empty_id(self) -> None:
        manifest = ConnectorManifest(connector_id="", name="Empty")
        connector = FilesystemConnector(manifest)
        errors = await connector.validate()
        assert "connector_id is required" in errors

    async def test_masked_token_long(self) -> None:
        c = ConnectorCredentials(token="abcdefghijklmnop")
        assert c.masked_token == "abcd***mnop"

    async def test_connect_with_bad_auth_tracking(self, connector_manager: ConnectorManager, sample_manifest: ConnectorManifest) -> None:
        class FailAuthConnector(_BaseReferenceConnector):
            async def execute(self, operation: str, **kwargs: Any) -> dict[str, Any]:
                return {"stub": True}
            async def authenticate(self, credentials: ConnectorCredentials) -> bool:
                return False
        await connector_manager.register_connector(FailAuthConnector, sample_manifest)
        bad_creds = ConnectorCredentials(token="bad")
        result = await connector_manager.connect("test_fs", bad_creds)
        assert result is True
        assert connector_manager.metrics.auth_failures == 1
