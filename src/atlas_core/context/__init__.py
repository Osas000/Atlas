"""Atlas Context — the complete runtime state of Atlas.

AtlasContext is the single object passed throughout Atlas.
Every subsystem reads from and writes to context through the ContextManager.
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Context changed event name constant
# ======================================================================

CONTEXT_CHANGED = "context.changed"


# ======================================================================
# Sub-context models
# ======================================================================


class UserContext(BaseModel):
    """User identity, goals, skills, and preferences."""

    user_id: str = ""
    display_name: str = ""
    email: str = ""
    goals: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    working_hours: str = ""
    timezone: str = "UTC"
    preferences: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class RuntimeContext(BaseModel):
    """System runtime state and version information."""

    start_time: datetime = Field(default_factory=datetime.now)
    version: str = ""
    app_name: str = "Atlas"
    kernel_state: str = "created"
    active_services: list[str] = Field(default_factory=list)
    health_status: str = "unknown"
    uptime_seconds: float = 0.0

    model_config = {"frozen": True}


class MissionContext(BaseModel):
    """Current mission or objective."""

    mission_id: str = ""
    title: str = ""
    description: str = ""
    status: str = "idle"
    priority: str = "normal"
    started_at: datetime | None = None
    deadline: datetime | None = None
    related_tasks: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class BrowserContext(BaseModel):
    """Current browser state.

    Stub — no browser automation in this milestone.
    """

    is_connected: bool = False
    active_url: str = ""
    active_tab_title: str = ""
    browser_type: str = ""

    model_config = {"frozen": True}


class AIContext(BaseModel):
    """AI provider configuration and availability.

    Stub — no AI routing in this milestone.
    """

    provider: str = ""
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    is_available: bool = False
    capabilities: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


class MemoryContext(BaseModel):
    """Snapshot of Memory Engine state."""

    working_count: int = 0
    session_count: int = 0
    project_count: int = 0
    long_term_count: int = 0
    archive_count: int = 0

    model_config = {"frozen": True}

    @property
    def total_count(self) -> int:
        return (
            self.working_count
            + self.session_count
            + self.project_count
            + self.long_term_count
            + self.archive_count
        )


class SettingsContext(BaseModel):
    """User settings and application configuration."""

    theme: str = "light"
    language: str = "en"
    notification_enabled: bool = True
    auto_save: bool = True
    storage_paths: dict[str, str] = Field(default_factory=dict)
    features: dict[str, bool] = Field(default_factory=dict)

    model_config = {"frozen": True}


class PermissionContext(BaseModel):
    """Runtime permission grants."""

    permissions: dict[str, bool] = Field(default_factory=dict)
    granted_features: list[str] = Field(default_factory=list)

    model_config = {"frozen": True}


# ======================================================================
# AtlasContext — single runtime state object
# ======================================================================


class AtlasContext(BaseModel):
    """Complete runtime state of Atlas.

    This is the single object passed throughout the system.
    Every sub-context is frozen and replaces existing patterns of
    long parameter lists and scattered state.
    """

    user: UserContext = Field(default_factory=UserContext)
    runtime: RuntimeContext = Field(default_factory=RuntimeContext)
    mission: MissionContext = Field(default_factory=MissionContext)
    browser: BrowserContext = Field(default_factory=BrowserContext)
    ai: AIContext = Field(default_factory=AIContext)
    memory: MemoryContext = Field(default_factory=MemoryContext)
    settings: SettingsContext = Field(default_factory=SettingsContext)
    permissions: PermissionContext = Field(default_factory=PermissionContext)

    context_id: UUID = Field(default_factory=uuid4)
    updated_at: datetime = Field(default_factory=datetime.now)

    model_config = {"frozen": True}


# ======================================================================
# Context Snapshot
# ======================================================================


class ContextSnapshot(BaseModel):
    """An immutable historical snapshot of AtlasContext."""

    snapshot_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.now)
    context: AtlasContext
    label: str = ""

    model_config = {"frozen": True}


# ======================================================================
# ContextManager — IService
# ======================================================================


class ContextManager(IService):
    """Manages the complete Atlas runtime context.

    Responsibilities:
    - Hold the current AtlasContext
    - Provide immutable snapshots via get_context()
    - Publish ContextChanged events on mutations
    - Support save/restore from snapshots
    - Validate context integrity
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._context = AtlasContext()
        self._snapshots: list[ContextSnapshot] = []
        self._max_snapshots = 50
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "context_manager"

    async def initialize(self) -> None:
        await super().initialize()
        self._logger.info("Context Manager initializing")

    async def start(self) -> None:
        await super().start()
        self._logger.info("Context Manager started")

    async def stop(self) -> None:
        await super().stop()
        self._logger.info("Context Manager stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "snapshots": len(self._snapshots),
            },
        )

    # ------------------------------------------------------------------
    # Context access
    # ------------------------------------------------------------------

    @property
    def context(self) -> AtlasContext:
        """Return the current context."""
        return self._context

    def get_context(self) -> AtlasContext:
        """Return the current context (method accessor, prefer property)."""
        return self._context

    # ------------------------------------------------------------------
    # Context mutations
    # ------------------------------------------------------------------

    async def update_user(self, **updates: Any) -> AtlasContext:
        return await self._update_subcontext("user", updates)

    async def update_runtime(self, **updates: Any) -> AtlasContext:
        return await self._update_subcontext("runtime", updates)

    async def update_mission(self, **updates: Any) -> AtlasContext:
        return await self._update_subcontext("mission", updates)

    async def update_browser(self, **updates: Any) -> AtlasContext:
        return await self._update_subcontext("browser", updates)

    async def update_ai(self, **updates: Any) -> AtlasContext:
        return await self._update_subcontext("ai", updates)

    async def update_memory(self, **updates: Any) -> AtlasContext:
        return await self._update_subcontext("memory", updates)

    async def update_settings(self, **updates: Any) -> AtlasContext:
        return await self._update_subcontext("settings", updates)

    async def update_permissions(self, **updates: Any) -> AtlasContext:
        return await self._update_subcontext("permissions", updates)

    async def _update_subcontext(self, field: str, updates: dict[str, Any]) -> AtlasContext:
        current = getattr(self._context, field)
        updated_sub = current.model_copy(update=updates)
        new_context = self._context.model_copy(
            update={field: updated_sub, "updated_at": datetime.now()},
        )
        self._context = new_context
        await self._publish_context_changed(field, list(updates.keys()))
        return self._context

    async def replace_context(self, context: AtlasContext) -> AtlasContext:
        """Replace the entire context (used during restore)."""
        self._context = context
        await self._publish_context_changed("all", [])
        return self._context

    # ------------------------------------------------------------------
    # Snapshot / restore
    # ------------------------------------------------------------------

    async def snapshot(self, label: str = "") -> ContextSnapshot:
        """Create an immutable snapshot of the current context."""
        snap = ContextSnapshot(
            context=self._context,
            label=label or f"snapshot_{len(self._snapshots)}",
        )
        self._snapshots.append(snap)
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots.pop(0)
        self._logger.debug("Context snapshot created: %s", snap.snapshot_id)
        return snap

    async def restore(self, snapshot_id: UUID) -> AtlasContext | None:
        """Restore context from a previous snapshot."""
        for snap in self._snapshots:
            if snap.snapshot_id == snapshot_id:
                self._context = snap.context
                self._logger.info("Context restored from snapshot %s", snapshot_id)
                await self._publish_context_changed("all", [])
                return self._context
        self._logger.warning("Snapshot not found: %s", snapshot_id)
        return None

    async def list_snapshots(self) -> list[ContextSnapshot]:
        """Return all stored snapshots."""
        return list(self._snapshots)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, context: AtlasContext | None = None) -> list[str]:
        """Validate context integrity.

        Returns a list of validation error messages (empty = valid).
        """
        errors: list[str] = []
        target = context or self._context

        if not target.user.user_id and target.user.display_name:
            errors.append("User has display_name but no user_id")
        if target.memory.total_count < 0:
            errors.append("Memory total_count is negative")
        if not target.runtime.app_name:
            errors.append("Runtime app_name is empty")
        if target.ai.temperature < 0.0 or target.ai.temperature > 2.0:
            errors.append("AI temperature out of range (0.0-2.0)")
        if target.ai.max_tokens < 1:
            errors.append("AI max_tokens must be positive")

        return errors

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def _publish_context_changed(self, field: str, changed_keys: list[str]) -> None:
        try:
            await self._event_bus.publish(Event(
                source="context_manager",
                category=EventCategory.CONTEXT,
                priority=EventPriority.NORMAL,
                payload={
                    "action": "context_changed",
                    "field": field,
                    "changed_keys": changed_keys,
                    "context_id": str(self._context.context_id),
                },
            ))
        except Exception:
            self._logger.exception("Failed to publish context changed event")
