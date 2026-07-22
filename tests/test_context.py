"""Tests for the Atlas Context system."""

from uuid import UUID

import pytest

from atlas_core.context import (
    AIContext,
    AtlasContext,
    BrowserContext,
    ContextManager,
    ContextSnapshot,
    MemoryContext,
    MissionContext,
    PermissionContext,
    RuntimeContext,
    SettingsContext,
    UserContext,
)
from atlas_core.events import EventBus


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def manager(bus: EventBus) -> ContextManager:
    return ContextManager(bus)


# ======================================================================
# Sub-context models
# ======================================================================


class TestUserContext:
    def test_defaults(self) -> None:
        ctx = UserContext()
        assert ctx.user_id == ""
        assert ctx.display_name == ""
        assert ctx.timezone == "UTC"
        assert ctx.goals == []
        assert ctx.preferences == {}

    def test_custom_values(self) -> None:
        ctx = UserContext(
            user_id="u1",
            display_name="Alice",
            goals=["learn python"],
            preferences={"theme": "dark"},
        )
        assert ctx.user_id == "u1"
        assert ctx.display_name == "Alice"
        assert ctx.goals == ["learn python"]

    def test_frozen(self) -> None:
        ctx = UserContext()
        with pytest.raises(ValueError):  # pydantic frozen error
            ctx.user_id = "changed"


class TestRuntimeContext:
    def test_defaults(self) -> None:
        ctx = RuntimeContext()
        assert ctx.app_name == "Atlas"
        assert ctx.kernel_state == "created"
        assert ctx.health_status == "unknown"

    def test_uptime(self) -> None:
        ctx = RuntimeContext(uptime_seconds=123.4)
        assert ctx.uptime_seconds == 123.4


class TestMissionContext:
    def test_defaults(self) -> None:
        ctx = MissionContext()
        assert ctx.status == "idle"
        assert ctx.priority == "normal"

    def test_custom(self) -> None:
        ctx = MissionContext(title="Build Feature X", status="active")
        assert ctx.title == "Build Feature X"
        assert ctx.status == "active"


class TestBrowserContext:
    def test_defaults(self) -> None:
        ctx = BrowserContext()
        assert ctx.is_connected is False
        assert ctx.active_url == ""


class TestAIContext:
    def test_defaults(self) -> None:
        ctx = AIContext()
        assert ctx.is_available is False
        assert ctx.temperature == 0.7
        assert ctx.max_tokens == 4096

    def test_custom(self) -> None:
        ctx = AIContext(provider="openai", model="gpt-4", is_available=True)
        assert ctx.provider == "openai"
        assert ctx.is_available is True


class TestMemoryContext:
    def test_defaults(self) -> None:
        ctx = MemoryContext()
        assert ctx.total_count == 0

    def test_total_count(self) -> None:
        ctx = MemoryContext(working_count=5, long_term_count=10)
        assert ctx.total_count == 15

    def test_all_counts(self) -> None:
        ctx = MemoryContext(
            working_count=1, session_count=2, project_count=3,
            long_term_count=4, archive_count=5,
        )
        assert ctx.total_count == 15


class TestSettingsContext:
    def test_defaults(self) -> None:
        ctx = SettingsContext()
        assert ctx.theme == "light"
        assert ctx.language == "en"
        assert ctx.notification_enabled is True


class TestPermissionContext:
    def test_defaults(self) -> None:
        ctx = PermissionContext()
        assert ctx.permissions == {}
        assert ctx.granted_features == []


# ======================================================================
# AtlasContext
# ======================================================================


class TestAtlasContext:
    def test_defaults(self) -> None:
        ctx = AtlasContext()
        assert isinstance(ctx.user, UserContext)
        assert isinstance(ctx.runtime, RuntimeContext)
        assert isinstance(ctx.mission, MissionContext)
        assert isinstance(ctx.browser, BrowserContext)
        assert isinstance(ctx.ai, AIContext)
        assert isinstance(ctx.memory, MemoryContext)
        assert isinstance(ctx.settings, SettingsContext)
        assert isinstance(ctx.permissions, PermissionContext)
        assert isinstance(ctx.context_id, UUID)

    def test_custom_sub_contexts(self) -> None:
        user = UserContext(display_name="Bob")
        runtime = RuntimeContext(app_name="TestAtlas")
        ctx = AtlasContext(user=user, runtime=runtime)
        assert ctx.user.display_name == "Bob"
        assert ctx.runtime.app_name == "TestAtlas"

    def test_frozen(self) -> None:
        ctx = AtlasContext()
        with pytest.raises(ValueError):
            ctx.user = UserContext()

    def test_serialization(self) -> None:
        ctx = AtlasContext(
            user=UserContext(display_name="Serialize Me"),
            memory=MemoryContext(working_count=42),
        )
        data = ctx.model_dump()
        restored = AtlasContext.model_validate(data)
        assert restored.user.display_name == "Serialize Me"
        assert restored.memory.working_count == 42


# ======================================================================
# ContextSnapshot
# ======================================================================


class TestContextSnapshot:
    def test_create(self) -> None:
        ctx = AtlasContext()
        snap = ContextSnapshot(context=ctx, label="test_snap")
        assert snap.context is ctx
        assert snap.label == "test_snap"
        assert isinstance(snap.snapshot_id, UUID)
        assert isinstance(snap.timestamp, datetime)  # noqa: F821

    def test_frozen(self) -> None:
        ctx = AtlasContext()
        snap = ContextSnapshot(context=ctx)
        with pytest.raises(ValueError):
            snap.label = "changed"


from datetime import datetime  # noqa: E402


# ======================================================================
# ContextManager
# ======================================================================


class TestContextManager:
    async def test_initialise(self, manager: ContextManager) -> None:
        assert manager.name == "context_manager"
        await manager.initialize()

    async def test_start_stop(self, manager: ContextManager) -> None:
        await manager.start()
        await manager.stop()

    async def test_health_check(self, manager: ContextManager) -> None:
        health = await manager.health_check()
        assert health.healthy is True

    async def test_get_context_returns_frozen(self, manager: ContextManager) -> None:
        ctx = manager.get_context()
        assert isinstance(ctx, AtlasContext)
        assert ctx.runtime.app_name == "Atlas"

    async def test_get_context_same_object(self, manager: ContextManager) -> None:
        ctx1 = manager.get_context()
        ctx2 = manager.get_context()
        # Same object returned — safe because context is frozen/immutable
        assert ctx1 is ctx2

    async def test_update_user(self, manager: ContextManager) -> None:
        ctx = await manager.update_user(display_name="Charlie")
        assert ctx.user.display_name == "Charlie"
        # verify it persisted
        assert manager.get_context().user.display_name == "Charlie"

    async def test_update_runtime(self, manager: ContextManager) -> None:
        ctx = await manager.update_runtime(kernel_state="running")
        assert ctx.runtime.kernel_state == "running"

    async def test_update_mission(self, manager: ContextManager) -> None:
        ctx = await manager.update_mission(title="Mission Alpha", status="active")
        assert ctx.mission.title == "Mission Alpha"
        assert ctx.mission.status == "active"

    async def test_update_browser(self, manager: ContextManager) -> None:
        ctx = await manager.update_browser(is_connected=True, active_url="https://example.com")
        assert ctx.browser.is_connected is True
        assert ctx.browser.active_url == "https://example.com"

    async def test_update_ai(self, manager: ContextManager) -> None:
        ctx = await manager.update_ai(provider="anthropic", is_available=True)
        assert ctx.ai.provider == "anthropic"
        assert ctx.ai.is_available is True

    async def test_update_memory(self, manager: ContextManager) -> None:
        ctx = await manager.update_memory(working_count=10, long_term_count=5)
        assert ctx.memory.working_count == 10
        assert ctx.memory.total_count == 15

    async def test_update_settings(self, manager: ContextManager) -> None:
        ctx = await manager.update_settings(theme="dark", language="fr")
        assert ctx.settings.theme == "dark"
        assert ctx.settings.language == "fr"

    async def test_update_permissions(self, manager: ContextManager) -> None:
        ctx = await manager.update_permissions(
            permissions={"can_export": True},
            granted_features=["export"],
        )
        assert ctx.permissions.permissions["can_export"] is True
        assert "export" in ctx.permissions.granted_features

    async def test_replace_context(self, manager: ContextManager) -> None:
        new_ctx = AtlasContext(
            user=UserContext(display_name="Replaced"),
            runtime=RuntimeContext(app_name="NewAtlas"),
        )
        result = await manager.replace_context(new_ctx)
        assert result.user.display_name == "Replaced"
        assert manager.get_context().runtime.app_name == "NewAtlas"

    async def test_multiple_updates_accumulate(self, manager: ContextManager) -> None:
        await manager.update_user(display_name="First")
        await manager.update_user(display_name="Second", email="a@b.com")
        ctx = manager.get_context()
        assert ctx.user.display_name == "Second"
        assert ctx.user.email == "a@b.com"

    # ------------------------------------------------------------------
    # Context changed events
    # ------------------------------------------------------------------

    async def test_update_publishes_event(self, bus: EventBus) -> None:
        manager = ContextManager(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("system", handler)
        await manager.update_user(display_name="Event Test")
        assert len(received) == 1

    async def test_replace_publishes_event(self, bus: EventBus) -> None:
        manager = ContextManager(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("system", handler)
        await manager.replace_context(AtlasContext())
        assert len(received) == 1

    # ------------------------------------------------------------------
    # Snapshot / restore
    # ------------------------------------------------------------------

    async def test_snapshot(self, manager: ContextManager) -> None:
        await manager.update_user(display_name="Snap")
        snap = await manager.snapshot(label="test")
        assert snap.label == "test"
        assert snap.context.user.display_name == "Snap"

    async def test_restore(self, manager: ContextManager) -> None:
        await manager.update_user(display_name="SaveMe")
        snap = await manager.snapshot(label="before_change")
        await manager.update_user(display_name="Changed")
        assert manager.get_context().user.display_name == "Changed"

        result = await manager.restore(snap.snapshot_id)
        assert result is not None
        assert manager.get_context().user.display_name == "SaveMe"

    async def test_restore_unknown(self, manager: ContextManager) -> None:
        result = await manager.restore(UUID(int=0))
        assert result is None

    async def test_list_snapshots(self, manager: ContextManager) -> None:
        assert await manager.list_snapshots() == []
        await manager.snapshot("s1")
        await manager.snapshot("s2")
        snaps = await manager.list_snapshots()
        assert len(snaps) == 2

    async def test_snapshot_max_limit(self, manager: ContextManager) -> None:
        # override max_snapshots for test
        manager._max_snapshots = 3  # type: ignore[attr-defined]
        for i in range(5):
            await manager.snapshot(f"s{i}")
        assert len(await manager.list_snapshots()) == 3

    async def test_snapshot_does_not_affect_current(self, manager: ContextManager) -> None:
        await manager.update_user(display_name="Original")
        snap = await manager.snapshot("before")
        await manager.update_user(display_name="Modified")
        assert snap.context.user.display_name == "Original"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    async def test_validate_valid(self, manager: ContextManager) -> None:
        errors = manager.validate()
        assert errors == []

    async def test_validate_user_no_id(self, manager: ContextManager) -> None:
        ctx = AtlasContext(user=UserContext(display_name="NoID"))
        errors = manager.validate(ctx)
        assert "User has display_name but no user_id" in errors

    async def test_validate_ai_temperature(self, manager: ContextManager) -> None:
        ctx = AtlasContext(ai=AIContext(temperature=3.0))
        errors = manager.validate(ctx)
        assert any("temperature" in e for e in errors)

    async def test_validate_ai_max_tokens(self, manager: ContextManager) -> None:
        ctx = AtlasContext(ai=AIContext(max_tokens=0))
        errors = manager.validate(ctx)
        assert any("max_tokens" in e for e in errors)

    async def test_validate_runtime_app_name(self, manager: ContextManager) -> None:
        ctx = AtlasContext(runtime=RuntimeContext(app_name=""))
        errors = manager.validate(ctx)
        assert any("app_name" in e for e in errors)
