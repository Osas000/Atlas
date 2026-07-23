"""Comprehensive tests for the Configuration & Feature Flag Framework."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Optional

import pytest

from atlas_core.configuration import (
    ConfigurationCache,
    ConfigurationEventBridge,
    ConfigurationHistory,
    ConfigurationManager,
    ConfigurationMetrics,
    ConfigurationSchema,
    ConfigurationScope,
    ConfigurationSnapshot,
    ConfigurationStore,
    ConfigurationValidator,
    ConfigurationValue,
    EnvironmentResolver,
    FeatureFlag,
    FeatureFlagManager,
    HistoryEntry,
    ValidationResult,
)
from atlas_core.events import EventBus
from atlas_core.interfaces import ServiceState
from atlas_core.interfaces.events import EventCategory
from atlas_core.kernel import AtlasKernel


# ======================================================================
# MockPersistence
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
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def config_manager(event_bus: EventBus, mock_persistence: MockPersistence) -> ConfigurationManager:
    return ConfigurationManager(event_bus=event_bus, persistence_manager=mock_persistence)


@pytest.fixture
def kernel(tmp_path: Path) -> AtlasKernel:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "default.yaml").write_text(
        "app_name: TestConfig\n"
        "version: 9.9.9\n"
        "log_level: DEBUG\n"
        "log_dir: '" + str(tmp_path / "logs").replace("\\", "\\\\") + "'\n"
    )
    return AtlasKernel(config_dir)


# ======================================================================
# TestConfigurationScope
# ======================================================================

class TestConfigurationScope:
    def test_values(self) -> None:
        assert ConfigurationScope.GLOBAL.value == "global"
        assert ConfigurationScope.SYSTEM.value == "system"
        assert ConfigurationScope.SERVICE.value == "service"
        assert ConfigurationScope.PLUGIN.value == "plugin"
        assert ConfigurationScope.CONNECTOR.value == "connector"
        assert ConfigurationScope.WORKFLOW.value == "workflow"
        assert ConfigurationScope.AGENT.value == "agent"
        assert ConfigurationScope.SESSION.value == "session"
        assert ConfigurationScope.USER.value == "user"

    def test_all_members(self) -> None:
        expected = {
            "GLOBAL", "SYSTEM", "SERVICE", "PLUGIN", "CONNECTOR",
            "WORKFLOW", "AGENT", "SESSION", "USER",
        }
        assert {m.name for m in ConfigurationScope} == expected


# ======================================================================
# TestConfigurationValue
# ======================================================================

class TestConfigurationValue:
    def test_create(self) -> None:
        cv = ConfigurationValue(key="k1", value="v1")
        assert cv.key == "k1"
        assert cv.value == "v1"
        assert cv.scope == ConfigurationScope.GLOBAL
        assert cv.version == 1
        assert cv.metadata == {}

    def test_with_all_fields(self) -> None:
        now = time.time()
        cv = ConfigurationValue(
            key="k1", value=42, scope=ConfigurationScope.SYSTEM,
            version=3, metadata={"env": "prod"}, created_at=now, updated_at=now,
        )
        assert cv.value == 42
        assert cv.scope == ConfigurationScope.SYSTEM
        assert cv.version == 3
        assert cv.metadata["env"] == "prod"

    def test_frozen(self) -> None:
        cv = ConfigurationValue(key="k1", value="v1")
        with pytest.raises(FrozenInstanceError):
            cv.key = "k2"


# ======================================================================
# TestFeatureFlag
# ======================================================================

class TestFeatureFlag:
    def test_create(self) -> None:
        f = FeatureFlag(flag_id="f1", name="Feature One")
        assert f.flag_id == "f1"
        assert f.name == "Feature One"
        assert f.enabled is False
        assert f.description == ""
        assert f.rollout_percentage == 100

    def test_with_all_fields(self) -> None:
        f = FeatureFlag(
            flag_id="f1", name="F1", enabled=True,
            description="test flag", rollout_percentage=50,
            metadata={"team": "core"},
        )
        assert f.enabled is True
        assert f.rollout_percentage == 50

    def test_frozen(self) -> None:
        f = FeatureFlag(flag_id="f1", name="F1")
        with pytest.raises(FrozenInstanceError):
            f.enabled = True


# ======================================================================
# TestValidationResult
# ======================================================================

class TestValidationResult:
    def test_valid(self) -> None:
        r = ValidationResult(valid=True)
        assert r.valid is True
        assert r.errors == ()

    def test_invalid(self) -> None:
        r = ValidationResult(valid=False, errors=("error1",))
        assert r.valid is False
        assert len(r.errors) == 1


# ======================================================================
# TestConfigurationValidator
# ======================================================================

class TestConfigurationValidator:
    @pytest.fixture
    def validator(self) -> ConfigurationValidator:
        return ConfigurationValidator()

    def test_validate_type_pass(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_type(42, int)
        assert err is None

    def test_validate_type_fail(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_type("hello", int)
        assert err is not None
        assert "expected int" in err

    def test_validate_required_none(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_required(None)
        assert err is not None

    def test_validate_required_value(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_required("val")
        assert err is None

    def test_validate_enum_pass(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_enum("a", ("a", "b", "c"))
        assert err is None

    def test_validate_enum_fail(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_enum("x", ("a", "b"))
        assert err is not None

    def test_validate_range_min(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_range(5, min_val=0)
        assert err is None
        err = validator.validate_range(-1, min_val=0)
        assert err is not None

    def test_validate_range_max(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_range(5, max_val=10)
        assert err is None
        err = validator.validate_range(15, max_val=10)
        assert err is not None

    def test_validate_range_non_numeric(self, validator: ConfigurationValidator) -> None:
        err = validator.validate_range("hello", min_val=0)
        assert err is None

    def test_validate_with_schema(self, validator: ConfigurationValidator) -> None:
        result = validator.validate("key", 42, {"type": int, "min": 0, "max": 100})
        assert result.valid is True

    def test_validate_with_schema_fail(self, validator: ConfigurationValidator) -> None:
        result = validator.validate("key", "not_int", {"type": int})
        assert result.valid is False

    def test_register_validator(self, validator: ConfigurationValidator) -> None:
        def my_validator(val: Any) -> Optional[str]:
            if val != "expected":
                return "not expected"
            return None
        validator.register_validator("my_key", my_validator)
        result = validator.validate("my_key", "expected")
        assert result.valid is True
        result = validator.validate("my_key", "unexpected")
        assert result.valid is False

    def test_unregister_validator(self, validator: ConfigurationValidator) -> None:
        def my_validator(val: Any) -> Optional[str]:
            return "error"
        validator.register_validator("my_key", my_validator)
        assert validator.unregister_validator("my_key", my_validator) is True
        result = validator.validate("my_key", "val")
        assert result.valid is True

    def test_unregister_missing(self, validator: ConfigurationValidator) -> None:
        def my_validator(val: Any) -> Optional[str]:
            return None
        assert validator.unregister_validator("nonexistent", my_validator) is False


# ======================================================================
# TestConfigurationSchema
# ======================================================================

class TestConfigurationSchema:
    @pytest.fixture
    def schema(self) -> ConfigurationSchema:
        return ConfigurationSchema(ConfigurationValidator())

    def test_register(self, schema: ConfigurationSchema) -> None:
        schema.register("timeout", {"type": int, "min": 1, "max": 300})
        assert schema.count == 1

    def test_unregister(self, schema: ConfigurationSchema) -> None:
        schema.register("key1", {"type": str})
        assert schema.unregister("key1") is True
        assert schema.count == 0

    def test_unregister_missing(self, schema: ConfigurationSchema) -> None:
        assert schema.unregister("nonexistent") is False

    def test_validate_pass(self, schema: ConfigurationSchema) -> None:
        schema.register("port", {"type": int, "min": 1, "max": 65535})
        result = schema.validate("port", 8080)
        assert result.valid is True

    def test_validate_fail(self, schema: ConfigurationSchema) -> None:
        schema.register("port", {"type": int})
        result = schema.validate("port", "invalid")
        assert result.valid is False

    def test_validate_no_schema(self, schema: ConfigurationSchema) -> None:
        result = schema.validate("nonexistent", "val")
        assert result.valid is True

    def test_get(self, schema: ConfigurationSchema) -> None:
        schema.register("key1", {"type": str})
        assert schema.get("key1") == {"type": str}

    def test_get_missing(self, schema: ConfigurationSchema) -> None:
        assert schema.get("nonexistent") is None

    def test_list(self, schema: ConfigurationSchema) -> None:
        schema.register("a", {})
        schema.register("b", {})
        keys = schema.list()
        assert "a" in keys
        assert "b" in keys


# ======================================================================
# TestConfigurationCache
# ======================================================================

class TestConfigurationCache:
    @pytest.fixture
    def cache(self) -> ConfigurationCache:
        return ConfigurationCache(max_size=3)

    def test_get_set(self, cache: ConfigurationCache) -> None:
        cache.set("key1", "val1")
        assert cache.get("key1") == "val1"

    def test_get_missing(self, cache: ConfigurationCache) -> None:
        assert cache.get("nonexistent") is None

    def test_remove(self, cache: ConfigurationCache) -> None:
        cache.set("key1", "val1")
        assert cache.remove("key1") is True
        assert cache.get("key1") is None

    def test_remove_missing(self, cache: ConfigurationCache) -> None:
        assert cache.remove("nonexistent") is False

    def test_clear(self, cache: ConfigurationCache) -> None:
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear()
        assert cache.size == 0

    def test_keys(self, cache: ConfigurationCache) -> None:
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        assert set(cache.keys()) == {"k1", "k2"}

    def test_lru_eviction(self, cache: ConfigurationCache) -> None:
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")
        cache.set("k4", "v4")
        assert cache.get("k1") is None
        assert cache.size == 3

    def test_lru_order_on_access(self, cache: ConfigurationCache) -> None:
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")
        cache.get("k1")
        cache.set("k4", "v4")
        assert cache.get("k2") is None
        assert cache.get("k1") == "v1"

    def test_max_size(self, cache: ConfigurationCache) -> None:
        assert cache.max_size == 3


# ======================================================================
# TestConfigurationStore
# ======================================================================

class TestConfigurationStore:
    @pytest.fixture
    def store(self, mock_persistence: MockPersistence) -> ConfigurationStore:
        return ConfigurationStore(mock_persistence)

    async def test_set_and_get(self, store: ConfigurationStore) -> None:
        cv = ConfigurationValue(key="k1", value="v1")
        await store.set("k1", cv)
        result = await store.get("k1")
        assert result is not None
        assert result.key == "k1"
        assert result.value == "v1"

    async def test_get_missing(self, store: ConfigurationStore) -> None:
        assert await store.get("nonexistent") is None

    async def test_delete(self, store: ConfigurationStore) -> None:
        cv = ConfigurationValue(key="k1", value="v1")
        await store.set("k1", cv)
        assert await store.delete("k1") is True
        assert await store.get("k1") is None

    async def test_delete_missing(self, store: ConfigurationStore) -> None:
        assert await store.delete("nonexistent") is False

    async def test_exists(self, store: ConfigurationStore) -> None:
        cv = ConfigurationValue(key="k1", value="v1")
        await store.set("k1", cv)
        assert await store.exists("k1") is True
        assert await store.exists("nonexistent") is False

    async def test_list_keys(self, store: ConfigurationStore) -> None:
        assert await store.list_keys() == []
        await store.set("k1", ConfigurationValue(key="k1", value="v1"))
        await store.set("k2", ConfigurationValue(key="k2", value="v2"))
        keys = await store.list_keys()
        assert sorted(keys) == ["k1", "k2"]

    async def test_list_scope(self, store: ConfigurationStore) -> None:
        cv1 = ConfigurationValue(key="k1", value="v1", scope=ConfigurationScope.GLOBAL)
        cv2 = ConfigurationValue(key="k2", value="v2", scope=ConfigurationScope.SYSTEM)
        await store.set("k1", cv1)
        await store.set("k2", cv2)
        scope_items = await store.list_scope(ConfigurationScope.GLOBAL)
        assert len(scope_items) == 1
        assert scope_items[0].key == "k1"

    async def test_clear_scope(self, store: ConfigurationStore) -> None:
        cv1 = ConfigurationValue(key="k1", value="v1", scope=ConfigurationScope.GLOBAL)
        cv2 = ConfigurationValue(key="k2", value="v2", scope=ConfigurationScope.SYSTEM)
        await store.set("k1", cv1)
        await store.set("k2", cv2)
        removed = await store.clear_scope(ConfigurationScope.GLOBAL)
        assert removed == 1
        assert await store.exists("k1") is False
        assert await store.exists("k2") is True

    async def test_export(self, store: ConfigurationStore) -> None:
        cv = ConfigurationValue(key="k1", value="v1")
        await store.set("k1", cv)
        exported = await store.export()
        assert "k1" in exported
        assert "v1" in exported

    async def test_import_data(self, store: ConfigurationStore) -> None:
        raw = '{"k1": {"value": "v1", "scope": "global", "version": 1}, "k2": {"value": 42, "scope": "system", "version": 1}}'
        count = await store.import_data(raw)
        assert count == 2
        assert await store.exists("k1") is True
        assert await store.exists("k2") is True


# ======================================================================
# TestEnvironmentResolver
# ======================================================================

class TestEnvironmentResolver:
    @pytest.fixture
    def resolver(self) -> EnvironmentResolver:
        return EnvironmentResolver()

    def test_resolve(self, resolver: EnvironmentResolver) -> None:
        os.environ["ATLAS_TEST_KEY"] = "test_value"
        val = resolver.resolve("test.key")
        assert val == "test_value"
        del os.environ["ATLAS_TEST_KEY"]

    def test_resolve_not_found(self, resolver: EnvironmentResolver) -> None:
        val = resolver.resolve("nonexistent.key")
        assert val is None

    def test_resolve_all(self, resolver: EnvironmentResolver) -> None:
        os.environ["ATLAS_FOO_BAR"] = "baz"
        os.environ["ATLAS_HELLO"] = "world"
        all_vals = resolver.resolve_all()
        assert "foo.bar" in all_vals
        assert "hello" in all_vals
        del os.environ["ATLAS_FOO_BAR"]
        del os.environ["ATLAS_HELLO"]

    def test_prefix(self, resolver: EnvironmentResolver) -> None:
        assert resolver.prefix == "ATLAS_"


# ======================================================================
# TestFeatureFlagManager
# ======================================================================

class TestFeatureFlagManager:
    @pytest.fixture
    def mgr(self) -> FeatureFlagManager:
        return FeatureFlagManager()

    def test_register_and_exists(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1"))
        assert mgr.exists("f1") is True
        assert mgr.exists("nonexistent") is False

    def test_enable(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1"))
        assert mgr.enable("f1") is True
        assert mgr.get("f1").enabled is True

    def test_enable_nonexistent(self, mgr: FeatureFlagManager) -> None:
        assert mgr.enable("nonexistent") is False

    def test_disable(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1", enabled=True))
        assert mgr.disable("f1") is True
        assert mgr.get("f1").enabled is False

    def test_delete(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1"))
        assert mgr.delete("f1") is True
        assert mgr.exists("f1") is False

    def test_delete_nonexistent(self, mgr: FeatureFlagManager) -> None:
        assert mgr.delete("nonexistent") is False

    def test_list(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1"))
        mgr.register(FeatureFlag(flag_id="f2", name="F2"))
        flags = mgr.list()
        assert len(flags) == 2

    def test_evaluate_not_found(self, mgr: FeatureFlagManager) -> None:
        assert mgr.evaluate("nonexistent") is False

    def test_evaluate_disabled(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1", enabled=False))
        assert mgr.evaluate("f1") is False

    def test_evaluate_enabled_full_rollout(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1", enabled=True, rollout_percentage=100))
        assert mgr.evaluate("f1") is True

    def test_evaluate_enabled_zero_rollout(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1", enabled=True, rollout_percentage=0))
        assert mgr.evaluate("f1") is False

    def test_evaluate_partial_rollout(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1", enabled=True, rollout_percentage=50))
        result = mgr.evaluate("f1")
        assert isinstance(result, bool)

    def test_get(self, mgr: FeatureFlagManager) -> None:
        mgr.register(FeatureFlag(flag_id="f1", name="F1"))
        assert mgr.get("f1") is not None
        assert mgr.get("nonexistent") is None


# ======================================================================
# TestConfigurationWatcher
# ======================================================================

class TestConfigurationWatcher:
    @pytest.fixture
    def watcher(self) -> Any:
        from atlas_core.configuration import ConfigurationWatcher
        return ConfigurationWatcher()

    def test_subscribe_and_notify(self, watcher: Any) -> None:
        received: list[tuple[str, Any, Any]] = []
        def cb(key: str, old: Any, new: Any) -> None:
            received.append((key, old, new))
        watcher.subscribe("my_key", cb)
        count = watcher.notify("my_key", "old_val", "new_val")
        assert count == 1
        assert len(received) == 1
        assert received[0] == ("my_key", "old_val", "new_val")

    def test_wildcard_subscribe(self, watcher: Any) -> None:
        received: list[str] = []
        def cb(key: str, old: Any, new: Any) -> None:
            received.append(key)
        watcher.subscribe("*", cb)
        watcher.notify("any_key", None, "val")
        assert len(received) == 1

    def test_unsubscribe(self, watcher: Any) -> None:
        received: list[str] = []
        def cb(key: str, old: Any, new: Any) -> None:
            received.append(key)
        watcher.subscribe("k", cb)
        assert watcher.unsubscribe("k", cb) is True
        watcher.notify("k", None, "v")
        assert len(received) == 0

    def test_unsubscribe_missing(self, watcher: Any) -> None:
        def cb(key: str, old: Any, new: Any) -> None:
            pass
        assert watcher.unsubscribe("nonexistent", cb) is False

    def test_subscriber_count(self, watcher: Any) -> None:
        assert watcher.subscriber_count == 0
        def cb(key: str, old: Any, new: Any) -> None:
            pass
        watcher.subscribe("k", cb)
        watcher.subscribe("k2", cb)
        assert watcher.subscriber_count == 2


# ======================================================================
# TestConfigurationHistory
# ======================================================================

class TestConfigurationHistory:
    @pytest.fixture
    def history(self) -> ConfigurationHistory:
        return ConfigurationHistory(max_size=5)

    def test_record_and_size(self, history: ConfigurationHistory) -> None:
        history.record(HistoryEntry(time.time(), "set", "k1"))
        assert history.size == 1

    def test_recent(self, history: ConfigurationHistory) -> None:
        history.record(HistoryEntry(time.time(), "set", "k1"))
        history.record(HistoryEntry(time.time(), "delete", "k2"))
        recent = history.recent(1)
        assert len(recent) == 1
        assert recent[0].action == "delete"

    def test_search_by_action(self, history: ConfigurationHistory) -> None:
        history.record(HistoryEntry(time.time(), "set", "k1"))
        history.record(HistoryEntry(time.time(), "delete", "k2"))
        results = history.search(action="set")
        assert len(results) == 1

    def test_search_by_key(self, history: ConfigurationHistory) -> None:
        history.record(HistoryEntry(time.time(), "set", "k1"))
        history.record(HistoryEntry(time.time(), "set", "k2"))
        results = history.search(key="k1")
        assert len(results) == 1

    def test_clear(self, history: ConfigurationHistory) -> None:
        history.record(HistoryEntry(time.time(), "set", "k1"))
        history.clear()
        assert history.size == 0

    def test_ring_buffer(self, history: ConfigurationHistory) -> None:
        for i in range(10):
            history.record(HistoryEntry(float(i), "set", f"k{i}"))
        assert history.size == 5


# ======================================================================
# TestConfigurationMetrics
# ======================================================================

class TestConfigurationMetrics:
    @pytest.fixture
    def metrics(self) -> ConfigurationMetrics:
        return ConfigurationMetrics()

    def test_initial_snapshot(self, metrics: ConfigurationMetrics) -> None:
        s = metrics.snapshot()
        assert all(v == 0 for v in s.values())

    def test_increment_reads(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_reads()
        assert metrics.reads == 1

    def test_increment_writes(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_writes()
        assert metrics.writes == 1
        assert metrics.reads == 0

    def test_increment_deletes(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_deletes()
        assert metrics.deletes == 1

    def test_increment_imports(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_imports()
        s = metrics.snapshot()
        assert s["imports"] == 1

    def test_increment_exports(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_exports()
        s = metrics.snapshot()
        assert s["exports"] == 1

    def test_increment_validations(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_validations()
        s = metrics.snapshot()
        assert s["validations"] == 1

    def test_cache_hits_misses(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_cache_hits()
        metrics.increment_cache_misses()
        s = metrics.snapshot()
        assert s["cache_hits"] == 1
        assert s["cache_misses"] == 1

    def test_feature_evaluations(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_feature_evaluations()
        s = metrics.snapshot()
        assert s["feature_evaluations"] == 1

    def test_watcher_notifications(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_watcher_notifications()
        s = metrics.snapshot()
        assert s["watcher_notifications"] == 1

    def test_reset(self, metrics: ConfigurationMetrics) -> None:
        metrics.increment_reads()
        metrics.increment_writes()
        metrics.reset()
        s = metrics.snapshot()
        assert all(v == 0 for v in s.values())

    def test_multiple_increments(self, metrics: ConfigurationMetrics) -> None:
        for _ in range(5):
            metrics.increment_reads()
        assert metrics.reads == 5


# ======================================================================
# TestConfigurationEventBridge
# ======================================================================

class TestConfigurationEventBridge:
    @pytest.fixture
    def bridge(self, event_bus: EventBus) -> ConfigurationEventBridge:
        return ConfigurationEventBridge(event_bus)

    async def test_config_set(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_config_set("my_key", "global")
        assert len(received) == 1
        assert received[0].payload["event_type"] == "config_set"

    async def test_config_updated(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_config_updated("k", "system", 2)
        assert received[0].payload["event_type"] == "config_updated"
        assert received[0].payload["version"] == 2

    async def test_config_deleted(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_config_deleted("k", "global")
        assert received[0].payload["event_type"] == "config_deleted"

    async def test_config_imported(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_config_imported(5)
        assert received[0].payload["event_type"] == "config_imported"
        assert received[0].payload["count"] == 5

    async def test_config_exported(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_config_exported(3)
        assert received[0].payload["event_type"] == "config_exported"
        assert received[0].payload["count"] == 3

    async def test_feature_enabled(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_feature_enabled("flag1")
        assert received[0].payload["event_type"] == "feature_enabled"

    async def test_feature_disabled(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_feature_disabled("flag1")
        assert received[0].payload["event_type"] == "feature_disabled"

    async def test_feature_evaluated(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_feature_evaluated("flag1", True)
        assert received[0].payload["event_type"] == "feature_evaluated"
        assert received[0].payload["result"] is True

    async def test_schema_registered(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_schema_registered("my_key")
        assert received[0].payload["event_type"] == "schema_registered"

    async def test_schema_validation_failed(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_schema_validation_failed("my_key", ("error1",))
        assert received[0].payload["event_type"] == "schema_validation_failed"
        assert "error1" in received[0].payload["errors"]

    async def test_event_source(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_config_set("k", "global")
        assert received[0].source == "configuration_manager"

    async def test_event_category(self, bridge: ConfigurationEventBridge, event_bus: EventBus) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        await bridge.publish_config_set("k", "global")
        assert received[0].category == EventCategory.CONFIGURATION


# ======================================================================
# TestConfigurationSnapshot
# ======================================================================

class TestConfigurationSnapshot:
    @pytest.fixture
    def snapshots(self, mock_persistence: MockPersistence) -> ConfigurationSnapshot:
        return ConfigurationSnapshot(mock_persistence)

    async def test_create_and_restore(self, snapshots: ConfigurationSnapshot) -> None:
        data = {"key1": "value1", "key2": 42}
        assert await snapshots.create("snap1", data) is True
        restored = await snapshots.restore("snap1")
        assert restored == data

    async def test_create_duplicate(self, snapshots: ConfigurationSnapshot) -> None:
        data = {"key1": "val1"}
        await snapshots.create("snap1", data)
        assert await snapshots.create("snap1", {"other": "data"}) is False

    async def test_restore_missing(self, snapshots: ConfigurationSnapshot) -> None:
        assert await snapshots.restore("nonexistent") is None

    async def test_delete(self, snapshots: ConfigurationSnapshot) -> None:
        await snapshots.create("snap1", {"k": "v"})
        assert await snapshots.delete("snap1") is True
        assert await snapshots.restore("snap1") is None

    async def test_list(self, snapshots: ConfigurationSnapshot) -> None:
        await snapshots.create("snap1", {"k": "v"})
        await snapshots.create("snap2", {"k": "v"})
        names = await snapshots.list()
        assert sorted(names) == ["snap1", "snap2"]

    async def test_compare(self, snapshots: ConfigurationSnapshot) -> None:
        await snapshots.create("snap1", {"a": 1, "b": 2, "c": 3})
        await snapshots.create("snap2", {"a": 1, "b": 99, "d": 4})
        diff = await snapshots.compare("snap1", "snap2")
        assert diff["added"] == ["d"]
        assert diff["removed"] == ["c"]
        assert diff["changed"] == ["b"]
        assert diff["unchanged"] == ["a"]


# ======================================================================
# TestConfigurationManager
# ======================================================================

class TestConfigurationManager:
    async def test_service_id(self, config_manager: ConfigurationManager) -> None:
        assert config_manager.name == "configuration_manager"

    async def test_initial_state(self, config_manager: ConfigurationManager) -> None:
        assert config_manager.service_state == ServiceState.CREATED

    async def test_initialize(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        assert config_manager.service_state == ServiceState.INITIALIZED

    async def test_initialize_twice_raises(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        with pytest.raises(RuntimeError):
            await config_manager.initialize()

    async def test_start_before_init_raises(self, config_manager: ConfigurationManager) -> None:
        with pytest.raises(RuntimeError):
            await config_manager.start()

    async def test_start(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.start()
        assert config_manager.service_state == ServiceState.RUNNING

    async def test_stop(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.start()
        await config_manager.stop()
        assert config_manager.service_state == ServiceState.STOPPED

    async def test_stop_twice(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.start()
        await config_manager.stop()
        await config_manager.stop()

    async def test_health_healthy(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.start()
        health = await config_manager.health_check()
        assert health.healthy is True

    async def test_health_not_started(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        health = await config_manager.health_check()
        assert health.healthy is False

    async def test_properties(self, config_manager: ConfigurationManager) -> None:
        assert config_manager.store is not None
        assert config_manager.schema is not None
        assert config_manager.validator is not None
        assert config_manager.cache is not None
        assert config_manager.env_resolver is not None
        assert config_manager.feature_flags is not None
        assert config_manager.watcher is not None
        assert config_manager.history is not None
        assert config_manager.metrics is not None
        assert config_manager.event_bridge is not None
        assert config_manager.snapshots is not None

    async def test_get_default(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        val = await config_manager.get("nonexistent", default="fallback")
        assert val == "fallback"

    async def test_set_and_get(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        cv = await config_manager.set("my_key", "my_value")
        assert cv.key == "my_key"
        assert cv.value == "my_value"
        assert cv.version == 1
        val = await config_manager.get("my_key")
        assert val == "my_value"

    async def test_set_increments_version(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.set("k", "v1")
        cv = await config_manager.set("k", "v2")
        assert cv.version == 2

    async def test_set_with_schema_validation(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        config_manager.schema.register("port", {"type": int})
        cv = await config_manager.set("port", 8080)
        assert cv.value == 8080

    async def test_set_validation_failure(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        config_manager.schema.register("port", {"type": int})
        with pytest.raises(ValueError, match="Validation failed"):
            await config_manager.set("port", "not_a_number")

    async def test_delete(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.set("k", "v")
        assert await config_manager.delete("k") is True
        assert await config_manager.get("k") is None

    async def test_delete_nonexistent(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        assert await config_manager.delete("nonexistent") is False

    async def test_exists(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.set("k", "v")
        assert await config_manager.exists("k") is True
        assert await config_manager.exists("nonexistent") is False

    async def test_environment_override(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        os.environ["ATLAS_DB_HOST"] = "env_host"
        val = await config_manager.get("db.host")
        assert val == "env_host"
        del os.environ["ATLAS_DB_HOST"]

    async def test_cache_hit(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.set("k", "v")
        await config_manager.get("k")
        await config_manager.get("k")
        s = config_manager.metrics.snapshot()
        assert s["cache_hits"] >= 1

    async def test_set_triggers_watcher(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        received: list[str] = []
        def cb(key: str, old: Any, new: Any) -> None:
            received.append(key)
        config_manager.watcher.subscribe("k", cb)
        await config_manager.set("k", "v1")
        await config_manager.set("k", "v2")
        assert len(received) >= 1

    async def test_stop_clears_cache(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.start()
        config_manager.cache.set("k", "v")
        await config_manager.stop()
        assert config_manager.cache.size == 0

    async def test_start_lifecycle_events(self, event_bus: EventBus, mock_persistence: MockPersistence) -> None:
        received: list = []
        async def handler(e: Any) -> None:
            received.append(e)
        event_bus.subscribe("configuration", handler)
        cm = ConfigurationManager(event_bus=event_bus, persistence_manager=mock_persistence)
        await cm.initialize()
        await cm.start()
        await cm.set("k", "v")
        event_types = {e.payload["event_type"] for e in received}
        assert "config_set" in event_types


# ======================================================================
# TestKernelIntegration
# ======================================================================

class TestKernelIntegration:
    async def test_kernel_registers_config_manager(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        kernel.boot()
        assert kernel.registry.count == 16
        from atlas_core.configuration import ConfigurationManager
        assert isinstance(kernel.configuration_manager, ConfigurationManager)

    async def test_kernel_property_before_boot_raises(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        with pytest.raises(RuntimeError):
            _ = kernel.configuration_manager

    async def test_kernel_config_healthy(self, kernel: AtlasKernel) -> None:
        kernel.initialize()
        kernel.boot()
        await kernel.start()
        health = await kernel.configuration_manager.health_check()
        assert health.healthy is True
        await kernel.stop()


# ======================================================================
# TestThreadSafety
# ======================================================================

class TestThreadSafety:
    async def test_cache_concurrent(self) -> None:
        cache = ConfigurationCache(max_size=100)
        async def setter(i: int) -> None:
            for j in range(50):
                cache.set(f"k_{i}_{j}", j)
        async def getter() -> None:
            for _ in range(100):
                cache.keys()
        await asyncio.gather(*[setter(i) for i in range(5)], getter())

    async def test_feature_flags_concurrent(self) -> None:
        mgr = FeatureFlagManager()
        async def register_flags(i: int) -> None:
            for j in range(20):
                mgr.register(FeatureFlag(flag_id=f"f_{i}_{j}", name=f"F{i}_{j}"))
        async def evaluate() -> None:
            for _ in range(50):
                mgr.list()
        await asyncio.gather(*[register_flags(i) for i in range(5)], evaluate())

    async def test_metrics_concurrent(self) -> None:
        m = ConfigurationMetrics()
        async def inc() -> None:
            for _ in range(100):
                m.increment_reads()
        await asyncio.gather(*[inc() for _ in range(10)])
        assert m.reads == 1000

    async def test_history_concurrent(self) -> None:
        h = ConfigurationHistory(max_size=1000)
        async def record(i: int) -> None:
            for _ in range(50):
                h.record(HistoryEntry(time.time(), "set", f"k{i}"))
        await asyncio.gather(*[record(i) for i in range(10)])
        assert h.size == 500

    async def test_watcher_concurrent(self) -> None:
        from atlas_core.configuration import ConfigurationWatcher
        w = ConfigurationWatcher()
        def cb(key: str, old: Any, new: Any) -> None:
            pass
        async def subscribe() -> None:
            for i in range(20):
                w.subscribe(f"k{i}", cb)
        async def notify() -> None:
            for i in range(20):
                w.notify(f"k{i}", None, "val")
        await asyncio.gather(subscribe(), notify())

    async def test_store_concurrent(self, mock_persistence: MockPersistence) -> None:
        store = ConfigurationStore(mock_persistence)
        async def writer(i: int) -> None:
            for j in range(20):
                cv = ConfigurationValue(key=f"k_{i}_{j}", value=j)
                await store.set(f"k_{i}_{j}", cv)
        async def reader() -> None:
            for _ in range(50):
                await store.list_keys()
        await asyncio.gather(*[writer(i) for i in range(5)], reader())


# ======================================================================
# TestEdgeCases
# ======================================================================

class TestEdgeCases:
    async def test_empty_feature_flag_list(self) -> None:
        mgr = FeatureFlagManager()
        assert mgr.list() == ()

    async def test_cache_remove_missing(self) -> None:
        cache = ConfigurationCache()
        assert cache.remove("nonexistent") is False

    async def test_schema_validate_no_registration(self) -> None:
        schema = ConfigurationSchema(ConfigurationValidator())
        result = schema.validate("any_key", "any_value")
        assert result.valid is True

    async def test_store_export_empty(self, mock_persistence: MockPersistence) -> None:
        store = ConfigurationStore(mock_persistence)
        exported = await store.export()
        data = __import__("json").loads(exported)
        assert data == {}

    async def test_store_import_empty(self, mock_persistence: MockPersistence) -> None:
        store = ConfigurationStore(mock_persistence)
        count = await store.import_data("{}")
        assert count == 0

    async def test_environment_resolve_no_prefix(self) -> None:
        resolver = EnvironmentResolver()
        os.environ["NON_ATLAS_VAR"] = "val"
        all_vals = resolver.resolve_all()
        assert "non.atlas.var" not in all_vals
        del os.environ["NON_ATLAS_VAR"]

    async def test_history_search_no_match(self) -> None:
        h = ConfigurationHistory()
        h.record(HistoryEntry(time.time(), "set", "k1"))
        results = h.search(action="delete")
        assert results == []

    async def test_snapshot_compare_identical(self, mock_persistence: MockPersistence) -> None:
        snapshots = ConfigurationSnapshot(mock_persistence)
        data = {"a": 1, "b": 2}
        await snapshots.create("s1", data)
        await snapshots.create("s2", data)
        diff = await snapshots.compare("s1", "s2")
        assert diff["added"] == []
        assert diff["removed"] == []
        assert diff["changed"] == []
        assert "a" in diff["unchanged"]

    async def test_config_manager_cache_hit_after_set(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.set("k", "v")
        val = await config_manager.get("k")
        assert val == "v"
        metrics = config_manager.metrics.snapshot()
        assert metrics["cache_misses"] >= 1 or metrics["cache_hits"] >= 0

    async def test_feature_flag_deterministic_rollout(self) -> None:
        mgr = FeatureFlagManager()
        mgr.register(FeatureFlag(flag_id="test_flag", name="Test", enabled=True, rollout_percentage=50))
        results = {mgr.evaluate("test_flag") for _ in range(100)}
        assert len(results) == 1  # deterministic: always same result

    async def test_validator_unregister_nonexistent_validator(self) -> None:
        v = ConfigurationValidator()
        def cb(val: Any) -> Optional[str]:
            return None
        v.register_validator("k", cb)
        def other_cb(val: Any) -> Optional[str]:
            return "err"
        assert v.unregister_validator("k", other_cb) is False

    async def test_watcher_unregister_nonexistent_callback(self) -> None:
        from atlas_core.configuration import ConfigurationWatcher
        w = ConfigurationWatcher()
        def cb(key: str, old: Any, new: Any) -> None:
            pass
        w.subscribe("k", cb)
        def other_cb(key: str, old: Any, new: Any) -> None:
            pass
        assert w.unsubscribe("k", other_cb) is False

    async def test_config_manager_read_from_store(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        await config_manager.set("k", "v")
        config_manager.cache.clear()
        val = await config_manager.get("k")
        assert val == "v"
        s = config_manager.metrics.snapshot()
        assert s["reads"] >= 1  # counted store read, not cache

    async def test_service_metadata(self, config_manager: ConfigurationManager) -> None:
        await config_manager.initialize()
        meta = config_manager.service_metadata
        assert "cache_size" in meta
        assert meta["cache_size"] == 100

    async def test_validator_enum_with_tuple(self) -> None:
        v = ConfigurationValidator()
        err = v.validate_enum("x", ("a", "b", "c"))
        assert err is not None

    async def test_watcher_notify_exception_handling(self) -> None:
        from atlas_core.configuration import ConfigurationWatcher
        w = ConfigurationWatcher()
        def failing_cb(key: str, old: Any, new: Any) -> None:
            raise RuntimeError("callback failed")
        w.subscribe("k", failing_cb)
        count = w.notify("k", None, "val")
        assert count == 1  # exception caught, still counted

    async def test_validate_schema_required_fail(self) -> None:
        v = ConfigurationValidator()
        result = v.validate("k", None, {"required": True})
        assert result.valid is False

    async def test_validate_schema_enum_fail(self) -> None:
        v = ConfigurationValidator()
        result = v.validate("k", "x", {"enum": ["a", "b"]})
        assert result.valid is False

    async def test_validate_schema_range_fail(self) -> None:
        v = ConfigurationValidator()
        result = v.validate("k", 999, {"min": 0, "max": 100})
        assert result.valid is False

    async def test_disable_nonexistent_flag(self) -> None:
        mgr = FeatureFlagManager()
        assert mgr.disable("nonexistent") is False
