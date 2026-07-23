"""Configuration & Feature Flag Framework for Atlas.

Centralized runtime configuration, feature flags, schema validation,
environment overrides, configuration snapshots, and configuration events.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from abc import ABC, abstractmethod
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Callable, Optional

from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory


# ======================================================================
# Enums
# ======================================================================

class ConfigurationScope(Enum):
    GLOBAL = "global"
    SYSTEM = "system"
    SERVICE = "service"
    PLUGIN = "plugin"
    CONNECTOR = "connector"
    WORKFLOW = "workflow"
    AGENT = "agent"
    SESSION = "session"
    USER = "user"


# ======================================================================
# Frozen dataclasses
# ======================================================================

@dataclass(frozen=True)
class ConfigurationValue:
    key: str
    value: Any
    scope: ConfigurationScope = ConfigurationScope.GLOBAL
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class FeatureFlag:
    flag_id: str
    name: str
    enabled: bool = False
    description: str = ""
    rollout_percentage: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: tuple[str, ...] = ()


# ======================================================================
# ConfigurationValidator
# ======================================================================

ValidatorFunc = Callable[[Any], Optional[str]]


class ConfigurationValidator:
    def __init__(self) -> None:
        self._custom_validators: dict[str, list[ValidatorFunc]] = {}
        self._lock = Lock()

    def register_validator(self, key: str, validator: ValidatorFunc) -> None:
        with self._lock:
            self._custom_validators.setdefault(key, []).append(validator)

    def unregister_validator(self, key: str, validator: ValidatorFunc) -> bool:
        with self._lock:
            lst = self._custom_validators.get(key)
            if lst is None:
                return False
            try:
                lst.remove(validator)
                return True
            except ValueError:
                return False

    def validate_type(self, value: Any, expected_type: type) -> Optional[str]:
        if not isinstance(value, expected_type):
            return f"expected {expected_type.__name__}, got {type(value).__name__}"
        return None

    def validate_required(self, value: Any) -> Optional[str]:
        if value is None:
            return "value is required"
        return None

    def validate_enum(self, value: Any, allowed: tuple[Any, ...]) -> Optional[str]:
        if value not in allowed:
            return f"value must be one of {allowed}"
        return None

    def validate_range(self, value: Any, min_val: Optional[float] = None, max_val: Optional[float] = None) -> Optional[str]:
        if not isinstance(value, (int, float)):
            return None
        if min_val is not None and value < min_val:
            return f"value must be >= {min_val}"
        if max_val is not None and value > max_val:
            return f"value must be <= {max_val}"
        return None

    def validate(self, key: str, value: Any, schema: Optional[dict[str, Any]] = None) -> ValidationResult:
        errors: list[str] = []
        if schema:
            if "type" in schema:
                err = self.validate_type(value, schema["type"])
                if err:
                    errors.append(err)
            if schema.get("required", False):
                err = self.validate_required(value)
                if err:
                    errors.append(err)
            if "enum" in schema:
                err = self.validate_enum(value, tuple(schema["enum"]))
                if err:
                    errors.append(err)
            if "min" in schema or "max" in schema:
                err = self.validate_range(value, schema.get("min"), schema.get("max"))
                if err:
                    errors.append(err)
        with self._lock:
            validators = self._custom_validators.get(key, [])
            for v in validators:
                err = v(value)
                if err:
                    errors.append(err)
        return ValidationResult(valid=len(errors) == 0, errors=tuple(errors))


# ======================================================================
# ConfigurationSchema
# ======================================================================

class ConfigurationSchema:
    def __init__(self, validator: ConfigurationValidator) -> None:
        self._schemas: dict[str, dict[str, Any]] = {}
        self._validator = validator
        self._lock = Lock()

    def register(self, key: str, schema: dict[str, Any]) -> None:
        with self._lock:
            self._schemas[key] = schema

    def unregister(self, key: str) -> bool:
        with self._lock:
            return self._schemas.pop(key, None) is not None

    def validate(self, key: str, value: Any) -> ValidationResult:
        schema = self.get(key)
        if schema is None:
            return ValidationResult(valid=True)
        return self._validator.validate(key, value, schema)

    def get(self, key: str) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._schemas.get(key)

    def list(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._schemas.keys())

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._schemas)


# ======================================================================
# ConfigurationCache (LRU)
# ======================================================================

class ConfigurationCache:
    def __init__(self, max_size: int = 100) -> None:
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._max_size = max_size
        self._lock = Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            if len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def remove(self, key: str) -> bool:
        with self._lock:
            return self._cache.pop(key, None) is not None

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def keys(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._cache.keys())

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    @property
    def max_size(self) -> int:
        return self._max_size


# ======================================================================
# ConfigurationStore (uses PersistenceManager)
# ======================================================================

class ConfigurationStore:
    _COLLECTION = "configuration"

    def __init__(self, persistence: Any) -> None:
        self._persistence = persistence

    async def set(self, key: str, value: ConfigurationValue) -> None:
        data = {
            "key": value.key,
            "value": value.value,
            "scope": value.scope.value,
            "version": value.version,
            "metadata": value.metadata,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }
        await self._persistence.save(self._COLLECTION, key, data)

    async def get(self, key: str) -> Optional[ConfigurationValue]:
        data = await self._persistence.load(self._COLLECTION, key)
        if data is None:
            return None
        return ConfigurationValue(
            key=data["key"],
            value=data["value"],
            scope=ConfigurationScope(data["scope"]),
            version=data["version"],
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", 0.0),
            updated_at=data.get("updated_at", 0.0),
        )

    async def delete(self, key: str) -> bool:
        return await self._persistence.delete(self._COLLECTION, key)

    async def exists(self, key: str) -> bool:
        return await self._persistence.load(self._COLLECTION, key) is not None

    async def list_keys(self) -> list[str]:
        return await self._persistence.list_keys(self._COLLECTION)

    async def list_scope(self, scope: ConfigurationScope) -> list[ConfigurationValue]:
        keys = await self._persistence.list_keys(self._COLLECTION)
        result: list[ConfigurationValue] = []
        for key in keys:
            val = await self.get(key)
            if val is not None and val.scope == scope:
                result.append(val)
        return result

    async def clear_scope(self, scope: ConfigurationScope) -> int:
        keys = await self._persistence.list_keys(self._COLLECTION)
        removed = 0
        for key in keys:
            val = await self.get(key)
            if val is not None and val.scope == scope:
                if await self.delete(key):
                    removed += 1
        return removed

    async def export(self) -> str:
        keys = await self._persistence.list_keys(self._COLLECTION)
        data: dict[str, Any] = {}
        for key in keys:
            val = await self.get(key)
            if val is not None:
                data[key] = {
                    "value": val.value,
                    "scope": val.scope.value,
                    "version": val.version,
                    "metadata": val.metadata,
                }
        return json.dumps(data, indent=2)

    async def import_data(self, raw: str) -> int:
        data = json.loads(raw)
        count = 0
        now = time.time()
        for key, item in data.items():
            cv = ConfigurationValue(
                key=key,
                value=item["value"],
                scope=ConfigurationScope(item.get("scope", "global")),
                version=item.get("version", 1),
                metadata=item.get("metadata", {}),
                created_at=now,
                updated_at=now,
            )
            await self.set(key, cv)
            count += 1
        return count


# ======================================================================
# EnvironmentResolver
# ======================================================================

class EnvironmentResolver:
    def __init__(self) -> None:
        self._prefix = "ATLAS_"

    def resolve(self, key: str) -> Optional[str]:
        env_key = f"{self._prefix}{key.upper().replace('.', '_')}"
        return os.environ.get(env_key)

    def resolve_all(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for env_name, env_value in os.environ.items():
            if env_name.startswith(self._prefix):
                config_key = env_name[len(self._prefix):].lower().replace("_", ".")
                result[config_key] = env_value
        return result

    @property
    def prefix(self) -> str:
        return self._prefix


# ======================================================================
# FeatureFlagManager
# ======================================================================

class FeatureFlagManager:
    def __init__(self) -> None:
        self._flags: dict[str, FeatureFlag] = {}
        self._lock = Lock()

    def register(self, flag: FeatureFlag) -> None:
        with self._lock:
            self._flags[flag.flag_id] = flag

    def enable(self, flag_id: str) -> bool:
        with self._lock:
            flag = self._flags.get(flag_id)
            if flag is None:
                return False
            self._flags[flag_id] = FeatureFlag(
                flag_id=flag.flag_id,
                name=flag.name,
                enabled=True,
                description=flag.description,
                rollout_percentage=flag.rollout_percentage,
                metadata=flag.metadata,
            )
            return True

    def disable(self, flag_id: str) -> bool:
        with self._lock:
            flag = self._flags.get(flag_id)
            if flag is None:
                return False
            self._flags[flag_id] = FeatureFlag(
                flag_id=flag.flag_id,
                name=flag.name,
                enabled=False,
                description=flag.description,
                rollout_percentage=flag.rollout_percentage,
                metadata=flag.metadata,
            )
            return True

    def delete(self, flag_id: str) -> bool:
        with self._lock:
            return self._flags.pop(flag_id, None) is not None

    def exists(self, flag_id: str) -> bool:
        with self._lock:
            return flag_id in self._flags

    def list(self) -> tuple[FeatureFlag, ...]:
        with self._lock:
            return tuple(self._flags.values())

    def evaluate(self, flag_id: str, context: Optional[dict[str, Any]] = None) -> bool:
        with self._lock:
            flag = self._flags.get(flag_id)
            if flag is None:
                return False
            if not flag.enabled:
                return False
            if flag.rollout_percentage >= 100:
                return True
            if flag.rollout_percentage <= 0:
                return False
            # Deterministic rollout based on flag_id hash
            hash_val = int(hashlib.md5(flag_id.encode()).hexdigest()[:8], 16)
            return (hash_val % 100) < flag.rollout_percentage

    def get(self, flag_id: str) -> Optional[FeatureFlag]:
        with self._lock:
            return self._flags.get(flag_id)


# ======================================================================
# ConfigurationWatcher
# ======================================================================

WatcherCallback = Callable[[str, Any, Any], None]


class ConfigurationWatcher:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[WatcherCallback]] = {}
        self._lock = Lock()

    def subscribe(self, key: str, callback: WatcherCallback) -> None:
        with self._lock:
            self._subscribers.setdefault(key, []).append(callback)

    def unsubscribe(self, key: str, callback: WatcherCallback) -> bool:
        with self._lock:
            lst = self._subscribers.get(key)
            if lst is None:
                return False
            try:
                lst.remove(callback)
                return True
            except ValueError:
                return False

    def notify(self, key: str, old_value: Any, new_value: Any) -> int:
        count = 0
        with self._lock:
            for sub_key, callbacks in list(self._subscribers.items()):
                if sub_key == "*" or sub_key == key:
                    for cb in callbacks:
                        count += 1
                        try:
                            cb(key, old_value, new_value)
                        except Exception:
                            pass
        return count

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._subscribers.values())


# ======================================================================
# ConfigurationHistory (ring buffer)
# ======================================================================

@dataclass(frozen=True)
class HistoryEntry:
    timestamp: float
    action: str
    key: str
    detail: str = ""


class ConfigurationHistory:
    def __init__(self, max_size: int = 1000) -> None:
        self._entries: deque[HistoryEntry] = deque(maxlen=max_size)
        self._lock = Lock()

    def record(self, entry: HistoryEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def recent(self, count: int = 100) -> list[HistoryEntry]:
        with self._lock:
            return list(self._entries)[-count:]

    def search(self, action: Optional[str] = None, key: Optional[str] = None) -> list[HistoryEntry]:
        results: list[HistoryEntry] = []
        with self._lock:
            for entry in self._entries:
                if action and entry.action != action:
                    continue
                if key and entry.key != key:
                    continue
                results.append(entry)
        return results

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)


# ======================================================================
# ConfigurationMetrics
# ======================================================================

class ConfigurationMetrics:
    def __init__(self) -> None:
        self._reads: int = 0
        self._writes: int = 0
        self._deletes: int = 0
        self._imports: int = 0
        self._exports: int = 0
        self._validations: int = 0
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._feature_evaluations: int = 0
        self._watcher_notifications: int = 0
        self._lock = Lock()

    def increment_reads(self) -> None:
        with self._lock:
            self._reads += 1

    def increment_writes(self) -> None:
        with self._lock:
            self._writes += 1

    def increment_deletes(self) -> None:
        with self._lock:
            self._deletes += 1

    def increment_imports(self) -> None:
        with self._lock:
            self._imports += 1

    def increment_exports(self) -> None:
        with self._lock:
            self._exports += 1

    def increment_validations(self) -> None:
        with self._lock:
            self._validations += 1

    def increment_cache_hits(self) -> None:
        with self._lock:
            self._cache_hits += 1

    def increment_cache_misses(self) -> None:
        with self._lock:
            self._cache_misses += 1

    def increment_feature_evaluations(self) -> None:
        with self._lock:
            self._feature_evaluations += 1

    def increment_watcher_notifications(self) -> None:
        with self._lock:
            self._watcher_notifications += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "reads": self._reads,
                "writes": self._writes,
                "deletes": self._deletes,
                "imports": self._imports,
                "exports": self._exports,
                "validations": self._validations,
                "cache_hits": self._cache_hits,
                "cache_misses": self._cache_misses,
                "feature_evaluations": self._feature_evaluations,
                "watcher_notifications": self._watcher_notifications,
            }

    def reset(self) -> None:
        with self._lock:
            self._reads = 0
            self._writes = 0
            self._deletes = 0
            self._imports = 0
            self._exports = 0
            self._validations = 0
            self._cache_hits = 0
            self._cache_misses = 0
            self._feature_evaluations = 0
            self._watcher_notifications = 0

    @property
    def reads(self) -> int:
        with self._lock:
            return self._reads

    @property
    def writes(self) -> int:
        with self._lock:
            return self._writes

    @property
    def deletes(self) -> int:
        with self._lock:
            return self._deletes


# ======================================================================
# ConfigurationEventBridge
# ======================================================================

class ConfigurationEventBridge:
    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus

    async def publish_config_set(self, key: str, scope: str) -> None:
        await self._publish("config_set", key, {"scope": scope})

    async def publish_config_updated(self, key: str, scope: str, version: int) -> None:
        await self._publish("config_updated", key, {"scope": scope, "version": version})

    async def publish_config_deleted(self, key: str, scope: str) -> None:
        await self._publish("config_deleted", key, {"scope": scope})

    async def publish_config_imported(self, count: int) -> None:
        await self._publish("config_imported", "config_manager", {"count": count})

    async def publish_config_exported(self, count: int) -> None:
        await self._publish("config_exported", "config_manager", {"count": count})

    async def publish_feature_enabled(self, flag_id: str) -> None:
        await self._publish("feature_enabled", flag_id, {})

    async def publish_feature_disabled(self, flag_id: str) -> None:
        await self._publish("feature_disabled", flag_id, {})

    async def publish_feature_evaluated(self, flag_id: str, result: bool) -> None:
        await self._publish("feature_evaluated", flag_id, {"result": result})

    async def publish_schema_registered(self, key: str) -> None:
        await self._publish("schema_registered", "config_manager", {"key": key})

    async def publish_schema_validation_failed(self, key: str, errors: tuple[str, ...]) -> None:
        await self._publish("schema_validation_failed", "config_manager", {"key": key, "errors": list(errors)})

    async def _publish(self, event_type: str, source: str, payload: dict[str, Any]) -> None:
        event = Event(
            source="configuration_manager",
            category=EventCategory.CONFIGURATION,
            payload={
                "event_type": event_type,
                "source": source,
                **payload,
            },
        )
        await self._event_bus.publish(event)


# ======================================================================
# ConfigurationSnapshot
# ======================================================================

class ConfigurationSnapshot:
    _COLLECTION = "configuration_snapshots"

    def __init__(self, persistence: Any) -> None:
        self._persistence = persistence

    async def create(self, name: str, data: dict[str, Any]) -> bool:
        existing = await self._persistence.load(self._COLLECTION, name)
        if existing is not None:
            return False
        snapshot = {
            "name": name,
            "data": data,
            "created_at": time.time(),
        }
        await self._persistence.save(self._COLLECTION, name, snapshot)
        return True

    async def restore(self, name: str) -> Optional[dict[str, Any]]:
        snapshot = await self._persistence.load(self._COLLECTION, name)
        if snapshot is None:
            return None
        return snapshot.get("data", {})

    async def delete(self, name: str) -> bool:
        return await self._persistence.delete(self._COLLECTION, name)

    async def list(self) -> list[str]:
        return await self._persistence.list_keys(self._COLLECTION)

    async def compare(self, name_a: str, name_b: str) -> dict[str, Any]:
        data_a = await self.restore(name_a) or {}
        data_b = await self.restore(name_b) or {}
        keys_a = set(data_a.keys())
        keys_b = set(data_b.keys())
        return {
            "added": list(keys_b - keys_a),
            "removed": list(keys_a - keys_b),
            "changed": [k for k in keys_a & keys_b if data_a[k] != data_b[k]],
            "unchanged": [k for k in keys_a & keys_b if data_a[k] == data_b[k]],
        }


# ======================================================================
# ConfigurationManager (IService)
# ======================================================================

class ConfigurationManager(IService):
    def __init__(
        self,
        event_bus: EventBus,
        persistence_manager: Any,
    ) -> None:
        self._event_bus = event_bus
        self._persistence = persistence_manager
        self._service_state = ServiceState.CREATED
        self._initialized = False
        self._started = False
        self._stopped = False
        self._state_lock = Lock()
        self._service_metadata: dict[str, Any] = {}

        self._validator = ConfigurationValidator()
        self._schema = ConfigurationSchema(self._validator)
        self._store = ConfigurationStore(persistence_manager)
        self._cache = ConfigurationCache(max_size=100)
        self._env_resolver = EnvironmentResolver()
        self._feature_flags = FeatureFlagManager()
        self._watcher = ConfigurationWatcher()
        self._history = ConfigurationHistory(max_size=1000)
        self._metrics = ConfigurationMetrics()
        self._event_bridge = ConfigurationEventBridge(event_bus)
        self._snapshots = ConfigurationSnapshot(persistence_manager)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "configuration_manager"

    @property
    def store(self) -> ConfigurationStore:
        return self._store

    @property
    def schema(self) -> ConfigurationSchema:
        return self._schema

    @property
    def validator(self) -> ConfigurationValidator:
        return self._validator

    @property
    def cache(self) -> ConfigurationCache:
        return self._cache

    @property
    def env_resolver(self) -> EnvironmentResolver:
        return self._env_resolver

    @property
    def feature_flags(self) -> FeatureFlagManager:
        return self._feature_flags

    @property
    def watcher(self) -> ConfigurationWatcher:
        return self._watcher

    @property
    def history(self) -> ConfigurationHistory:
        return self._history

    @property
    def metrics(self) -> ConfigurationMetrics:
        return self._metrics

    @property
    def event_bridge(self) -> ConfigurationEventBridge:
        return self._event_bridge

    @property
    def snapshots(self) -> ConfigurationSnapshot:
        return self._snapshots

    # ------------------------------------------------------------------
    # IService lifecycle
    # ------------------------------------------------------------------

    @property
    def service_state(self) -> ServiceState:
        with self._state_lock:
            return self._service_state

    @property
    def service_metadata(self) -> dict[str, Any]:
        return dict(self._service_metadata)

    async def initialize(self) -> None:
        with self._state_lock:
            if self._initialized:
                raise RuntimeError("ConfigurationManager already initialized")
            self._service_state = ServiceState.INITIALIZED

        self._service_metadata["cache_size"] = self._cache.max_size
        self._service_metadata["history_size"] = self._history.size

        with self._state_lock:
            self._initialized = True
            self._service_state = ServiceState.INITIALIZED

    async def start(self) -> None:
        with self._state_lock:
            if not self._initialized:
                raise RuntimeError("ConfigurationManager not initialized")
            self._service_state = ServiceState.STARTING

        with self._state_lock:
            self._started = True
            self._service_state = ServiceState.RUNNING

    async def stop(self) -> None:
        with self._state_lock:
            if self._stopped:
                return
            self._service_state = ServiceState.STOPPING

        self._cache.clear()

        with self._state_lock:
            self._stopped = True
            self._service_state = ServiceState.STOPPED

    async def health_check(self) -> ServiceHealth:
        with self._state_lock:
            return ServiceHealth(
                healthy=self._service_state == ServiceState.RUNNING,
                state=self._service_state,
                message="Configuration Manager operational",
                metadata=self._metrics.snapshot(),
            )

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def get(self, key: str, default: Any = None) -> Any:
        cached = self._cache.get(key)
        if cached is not None:
            self._metrics.increment_cache_hits()
            return cached
        self._metrics.increment_cache_misses()

        env_val = self._env_resolver.resolve(key)
        if env_val is not None:
            self._metrics.increment_reads()
            return env_val

        stored = await self._store.get(key)
        if stored is not None:
            self._metrics.increment_reads()
            self._cache.set(key, stored.value)
            return stored.value

        return default

    async def set(self, key: str, value: Any, scope: ConfigurationScope = ConfigurationScope.GLOBAL) -> ConfigurationValue:
        schema_result = self._schema.validate(key, value)
        if not schema_result.valid:
            await self._event_bridge.publish_schema_validation_failed(key, schema_result.errors)
            raise ValueError(f"Validation failed for '{key}': {', '.join(schema_result.errors)}")

        old = await self._store.get(key)
        now = time.time()
        version = (old.version + 1) if old else 1
        cv = ConfigurationValue(
            key=key,
            value=value,
            scope=scope,
            version=version,
            created_at=old.created_at if old else now,
            updated_at=now,
        )
        await self._store.set(key, cv)
        self._cache.set(key, value)
        self._metrics.increment_writes()

        if old is None:
            await self._event_bridge.publish_config_set(key, scope.value)
            self._history.record(HistoryEntry(now, "set", key, f"created scope={scope.value}"))
        else:
            await self._event_bridge.publish_config_updated(key, scope.value, version)
            self._history.record(HistoryEntry(now, "update", key, f"v{version} scope={scope.value}"))
            self._watcher.notify(key, old.value, value)

        return cv

    async def delete(self, key: str) -> bool:
        old = await self._store.get(key)
        if old is None:
            return False
        result = await self._store.delete(key)
        if result:
            self._cache.remove(key)
            self._metrics.increment_deletes()
            await self._event_bridge.publish_config_deleted(key, old.scope.value)
            self._history.record(HistoryEntry(time.time(), "delete", key))
        return result

    async def exists(self, key: str) -> bool:
        return await self._store.exists(key)
