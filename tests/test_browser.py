"""Tests for the Browser Companion."""

import asyncio

import pytest

from atlas_core.browser import (
    BrowserAction,
    BrowserCompanion,
    BrowserCommandBridge,
    BrowserConnectionStatus,
    BrowserEventBridge,
    BrowserMetrics,
    BrowserPermissionManager,
    BrowserSession,
    BrowserSessionManager,
    DOMInspector,
    FormFieldState,
    FormState,
    FormTracker,
    PageContext,
    PageLoadStatus,
    SelectionState,
    SelectionTracker,
    SelectionType,
)
from atlas_core.context import AtlasContext, PermissionContext
from atlas_core.events import EventBus
from atlas_core.interfaces.events import EventCategory, EventPriority


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def companion(bus: EventBus) -> BrowserCompanion:
    return BrowserCompanion(bus)


@pytest.fixture
def session_manager() -> BrowserSessionManager:
    return BrowserSessionManager()


@pytest.fixture
def dom_inspector() -> DOMInspector:
    return DOMInspector()


@pytest.fixture
def selection_tracker() -> SelectionTracker:
    return SelectionTracker()


@pytest.fixture
def form_tracker() -> FormTracker:
    return FormTracker()


@pytest.fixture
def event_bridge(bus: EventBus) -> BrowserEventBridge:
    return BrowserEventBridge(bus)


@pytest.fixture
def perm_mgr() -> BrowserPermissionManager:
    return BrowserPermissionManager()


@pytest.fixture
def command_bridge() -> BrowserCommandBridge:
    return BrowserCommandBridge()


@pytest.fixture
def metrics() -> BrowserMetrics:
    return BrowserMetrics()


# ======================================================================
# Enums
# ======================================================================


class TestBrowserConnectionStatus:
    def test_values(self) -> None:
        assert BrowserConnectionStatus.DISCONNECTED != BrowserConnectionStatus.CONNECTED
        assert BrowserConnectionStatus.CONNECTING != BrowserConnectionStatus.ERROR


class TestPageLoadStatus:
    def test_values(self) -> None:
        assert PageLoadStatus.LOADING != PageLoadStatus.LOADED
        assert PageLoadStatus.ERROR != PageLoadStatus.TIMEOUT


class TestBrowserAction:
    def test_values(self) -> None:
        assert BrowserAction.NAVIGATE.value == "navigate"
        assert BrowserAction.CLICK.value == "click"
        assert BrowserAction.EXTRACT.value == "extract"
        assert BrowserAction.SCROLL.value == "scroll"
        assert BrowserAction.SCREENSHOT.value == "screenshot"
        assert BrowserAction.INJECT_SCRIPT.value == "inject_script"
        assert BrowserAction.FORM_FILL.value == "form_fill"
        assert BrowserAction.DOWNLOAD.value == "download"


class TestSelectionType:
    def test_values(self) -> None:
        assert SelectionType.TEXT != SelectionType.ELEMENT
        assert SelectionType.RANGE != SelectionType.TEXT


# ======================================================================
# Data classes
# ======================================================================


class TestBrowserSession:
    def test_defaults(self) -> None:
        s = BrowserSession()
        assert s.session_id is not None
        assert s.connection_status == BrowserConnectionStatus.DISCONNECTED
        assert s.capabilities == []


class TestPageContext:
    def test_defaults(self) -> None:
        p = PageContext()
        assert p.url == ""
        assert p.load_status == PageLoadStatus.LOADED
        assert p.metadata == {}


class TestSelectionState:
    def test_defaults(self) -> None:
        s = SelectionState()
        assert s.selected_text == ""
        assert s.selection_type == SelectionType.TEXT
        assert s.element_classes == []


class TestFormFieldState:
    def test_defaults(self) -> None:
        f = FormFieldState()
        assert f.name == ""
        assert f.field_type == ""
        assert f.current_value == ""
        assert f.is_dirty is False
        assert f.is_valid is True


class TestFormState:
    def test_defaults(self) -> None:
        f = FormState()
        assert f.form_id == ""
        assert f.method == "get"
        assert f.fields == {}
        assert f.is_dirty is False
        assert f.is_valid is True


class TestBrowserMetrics:
    def test_defaults(self) -> None:
        m = BrowserMetrics()
        assert m.pages_visited == 0
        assert m.commands_executed == 0

    def test_avg_timing_zero(self) -> None:
        m = BrowserMetrics()
        assert m.avg_timing_ms == 0.0

    def test_avg_timing(self) -> None:
        m = BrowserMetrics(commands_executed=2, total_timing_ms=100.0)
        assert m.avg_timing_ms == 50.0

    def test_avg_timing_events_only(self) -> None:
        m = BrowserMetrics(events_processed=4, total_timing_ms=200.0)
        assert m.avg_timing_ms == 50.0


# ======================================================================
# BrowserSessionManager
# ======================================================================


class TestBrowserSessionManager:
    def test_create_session(self, session_manager: BrowserSessionManager) -> None:
        session = session_manager.create_session("chrome", "120.0", ["tabs", "navigation"])
        assert session.browser_type == "chrome"
        assert session.browser_version == "120.0"
        assert session.connection_status == BrowserConnectionStatus.CONNECTED
        assert "tabs" in session.capabilities
        assert session_manager.active_session_id == session.session_id

    def test_create_session_defaults(self, session_manager: BrowserSessionManager) -> None:
        session = session_manager.create_session()
        assert session.browser_type == ""
        assert session.capabilities == []

    def test_close_session(self, session_manager: BrowserSessionManager) -> None:
        session = session_manager.create_session("chrome")
        assert session_manager.close_session(session.session_id) is True
        assert session.connection_status == BrowserConnectionStatus.DISCONNECTED
        assert session_manager.active_session_id is None

    def test_close_session_nonexistent(self, session_manager: BrowserSessionManager) -> None:
        assert session_manager.close_session("nonexistent") is False

    def test_get_session(self, session_manager: BrowserSessionManager) -> None:
        created = session_manager.create_session("chrome")
        fetched = session_manager.get_session(created.session_id)
        assert fetched is created

    def test_get_session_nonexistent(self, session_manager: BrowserSessionManager) -> None:
        assert session_manager.get_session("nonexistent") is None

    def test_active_session(self, session_manager: BrowserSessionManager) -> None:
        assert session_manager.active_session is None
        created = session_manager.create_session("chrome")
        assert session_manager.active_session is created

    def test_set_active_session(self, session_manager: BrowserSessionManager) -> None:
        s1 = session_manager.create_session("chrome")
        s2 = session_manager.create_session("firefox")
        assert session_manager.active_session is s2
        assert session_manager.set_active_session(s1.session_id) is True
        assert session_manager.active_session is s1

    def test_set_active_session_nonexistent(self, session_manager: BrowserSessionManager) -> None:
        assert session_manager.set_active_session("nope") is False

    def test_touch_session(self, session_manager: BrowserSessionManager) -> None:
        session = session_manager.create_session("chrome")
        old = session.last_active
        session_manager.touch_session(session.session_id)
        assert session.last_active >= old

    def test_touch_session_nonexistent(self, session_manager: BrowserSessionManager) -> None:
        session_manager.touch_session("nope")  # should not raise

    def test_list_sessions(self, session_manager: BrowserSessionManager) -> None:
        session_manager.create_session("chrome")
        session_manager.create_session("firefox")
        assert len(session_manager.list_sessions()) == 2

    def test_session_count(self, session_manager: BrowserSessionManager) -> None:
        assert session_manager.session_count == 0
        session_manager.create_session("chrome")
        assert session_manager.session_count == 1

    def test_clear(self, session_manager: BrowserSessionManager) -> None:
        session_manager.create_session("chrome")
        session_manager.clear()
        assert session_manager.session_count == 0
        assert session_manager.active_session_id is None

    def test_active_session_id_property(self, session_manager: BrowserSessionManager) -> None:
        assert session_manager.active_session_id is None
        s = session_manager.create_session("chrome")
        assert session_manager.active_session_id == s.session_id


# ======================================================================
# DOMInspector
# ======================================================================


class TestDOMInspector:
    def test_get_element_info_no_page(self, dom_inspector: DOMInspector) -> None:
        info = dom_inspector.get_element_info("#my-id")
        assert info["found"] is False
        assert "No page context" in info["error"]

    def test_get_element_info_with_page(self, dom_inspector: DOMInspector) -> None:
        page = PageContext(url="https://example.com")
        dom_inspector.set_page(page)
        info = dom_inspector.get_element_info("#my-id", "href")
        assert info["found"] is True
        assert info["page_url"] == "https://example.com"

    def test_query_elements_no_page(self, dom_inspector: DOMInspector) -> None:
        assert dom_inspector.query_elements("div") == []

    def test_query_elements_with_page(self, dom_inspector: DOMInspector) -> None:
        page = PageContext(url="https://example.com")
        dom_inspector.set_page(page)
        results = dom_inspector.query_elements("div")
        assert len(results) == 1
        assert results[0]["page_url"] == "https://example.com"

    def test_get_page_text(self, dom_inspector: DOMInspector) -> None:
        assert dom_inspector.get_page_text() == ""

    def test_get_element_by_id(self, dom_inspector: DOMInspector) -> None:
        info = dom_inspector.get_element_by_id("main")
        assert info["found"] is False
        assert info["element_id"] == "main"

    def test_get_attributes(self, dom_inspector: DOMInspector) -> None:
        info = dom_inspector.get_attributes("main", ["href", "class"])
        assert info["found"] is False
        assert "href" in info["attributes"]
        assert "class" in info["attributes"]

    def test_set_page_updates_current(self, dom_inspector: DOMInspector) -> None:
        page = PageContext(url="https://example.com")
        dom_inspector.set_page(page)
        assert dom_inspector._current_page is page


# ======================================================================
# SelectionTracker
# ======================================================================


class TestSelectionTracker:
    def test_initial_state(self, selection_tracker: SelectionTracker) -> None:
        assert selection_tracker.has_selection is False
        assert selection_tracker.get_selection() is None
        assert selection_tracker.selection_count == 0

    def test_on_selection_change(self, selection_tracker: SelectionTracker) -> None:
        sel = SelectionState(selected_text="hello world")
        selection_tracker.on_selection_change(sel)
        assert selection_tracker.has_selection is True
        assert selection_tracker.get_selection() is sel

    def test_clear_selection(self, selection_tracker: SelectionTracker) -> None:
        selection_tracker.on_selection_change(SelectionState(selected_text="test"))
        selection_tracker.clear_selection()
        assert selection_tracker.has_selection is False
        assert selection_tracker.get_selection() is None

    def test_list_history(self, selection_tracker: SelectionTracker) -> None:
        selection_tracker.on_selection_change(SelectionState(selected_text="a"))
        selection_tracker.on_selection_change(SelectionState(selected_text="b"))
        history = selection_tracker.list_history()
        assert len(history) == 2
        assert history[0].selected_text == "a"
        assert history[1].selected_text == "b"

    def test_list_history_limit(self, selection_tracker: SelectionTracker) -> None:
        for i in range(100):
            selection_tracker.on_selection_change(SelectionState(selected_text=str(i)))
        history = selection_tracker.list_history(limit=3)
        assert len(history) == 3

    def test_selection_count(self, selection_tracker: SelectionTracker) -> None:
        assert selection_tracker.selection_count == 0
        selection_tracker.on_selection_change(SelectionState(selected_text="a"))
        assert selection_tracker.selection_count == 1

    def test_clear_history(self, selection_tracker: SelectionTracker) -> None:
        selection_tracker.on_selection_change(SelectionState(selected_text="a"))
        selection_tracker.clear_history()
        assert selection_tracker.selection_count == 0
        assert selection_tracker.has_selection is False


# ======================================================================
# FormTracker
# ======================================================================


class TestFormTracker:
    def test_track_form(self, form_tracker: FormTracker) -> None:
        form = form_tracker.track_form("login", "/submit", "post")
        assert form.form_id == "login"
        assert form.action == "/submit"
        assert form.method == "post"

    def test_update_field_creates(self, form_tracker: FormTracker) -> None:
        form_tracker.track_form("login")
        assert form_tracker.update_field("login", "username", "john") is True
        form = form_tracker.get_form("login")
        assert form is not None
        assert form.fields["username"].current_value == "john"
        assert form.is_dirty is True

    def test_update_field_nonexistent_form(self, form_tracker: FormTracker) -> None:
        assert form_tracker.update_field("nope", "f", "v") is False

    def test_update_field_existing(self, form_tracker: FormTracker) -> None:
        form_tracker.track_form("login")
        form_tracker.update_field("login", "email", "a@b.com")
        form_tracker.update_field("login", "email", "c@d.com")
        form = form_tracker.get_form("login")
        assert form is not None
        assert form.fields["email"].current_value == "c@d.com"
        assert form.fields["email"].is_dirty is True

    def test_set_field_validity(self, form_tracker: FormTracker) -> None:
        form_tracker.track_form("login")
        form_tracker.update_field("login", "email", "bad")
        assert form_tracker.set_field_validity("login", "email", False, "Invalid email") is True
        form = form_tracker.get_form("login")
        assert form is not None
        assert form.fields["email"].is_valid is False
        assert form.fields["email"].validation_message == "Invalid email"
        assert form.is_valid is False

    def test_set_field_validity_nonexistent_form(self, form_tracker: FormTracker) -> None:
        assert form_tracker.set_field_validity("nope", "f", False) is False

    def test_set_field_validity_nonexistent_field(self, form_tracker: FormTracker) -> None:
        form_tracker.track_form("login")
        assert form_tracker.set_field_validity("login", "nope", False) is False

    def test_get_form(self, form_tracker: FormTracker) -> None:
        created = form_tracker.track_form("login")
        fetched = form_tracker.get_form("login")
        assert fetched is created

    def test_get_form_nonexistent(self, form_tracker: FormTracker) -> None:
        assert form_tracker.get_form("nope") is None

    def test_remove_form(self, form_tracker: FormTracker) -> None:
        form_tracker.track_form("login")
        assert form_tracker.remove_form("login") is True
        assert form_tracker.get_form("login") is None

    def test_remove_form_nonexistent(self, form_tracker: FormTracker) -> None:
        assert form_tracker.remove_form("nope") is False

    def test_list_forms(self, form_tracker: FormTracker) -> None:
        form_tracker.track_form("login")
        form_tracker.track_form("signup")
        assert len(form_tracker.list_forms()) == 2

    def test_clear(self, form_tracker: FormTracker) -> None:
        form_tracker.track_form("login")
        form_tracker.clear()
        assert form_tracker.form_count == 0

    def test_form_count(self, form_tracker: FormTracker) -> None:
        assert form_tracker.form_count == 0
        form_tracker.track_form("login")
        assert form_tracker.form_count == 1


# ======================================================================
# BrowserEventBridge
# ======================================================================


class TestBrowserEventBridge:
    async def test_publish(self, bus: EventBus) -> None:
        bridge = BrowserEventBridge(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("browser", handler)
        await bridge.publish("test_action", {"key": "val"})
        assert len(received) == 1
        e = received[0]
        assert e.source == "browser_companion"
        assert e.category == EventCategory.BROWSER
        assert e.payload["action"] == "test_action"
        assert e.payload["key"] == "val"

    async def test_publish_page_change(self, bus: EventBus) -> None:
        bridge = BrowserEventBridge(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("browser", handler)
        page = PageContext(url="https://example.com", title="Test")
        await bridge.publish_page_change(page)
        assert len(received) == 1
        assert received[0].payload["action"] == "page_changed"
        assert received[0].payload["url"] == "https://example.com"

    async def test_publish_selection(self, bus: EventBus) -> None:
        bridge = BrowserEventBridge(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("browser", handler)
        sel = SelectionState(selected_text="hello", page_url="https://example.com")
        await bridge.publish_selection(sel)
        assert len(received) == 1
        assert received[0].payload["action"] == "selection_changed"
        assert received[0].payload["selected_text"] == "hello"

    async def test_publish_form_change(self, bus: EventBus) -> None:
        bridge = BrowserEventBridge(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("browser", handler)
        form = FormState(form_id="login", is_dirty=True, is_valid=True)
        await bridge.publish_form_change(form)
        assert len(received) == 1
        assert received[0].payload["action"] == "form_changed"
        assert received[0].payload["form_id"] == "login"

    async def test_publish_connection_status(self, bus: EventBus) -> None:
        bridge = BrowserEventBridge(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("browser", handler)
        await bridge.publish_connection_status(BrowserConnectionStatus.CONNECTED)
        assert len(received) == 1
        assert received[0].payload["status"] == "CONNECTED"
        assert received[0].priority == EventPriority.HIGH

    async def test_publish_error(self, bus: EventBus) -> None:
        bridge = BrowserEventBridge(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("browser", handler)
        await bridge.publish_error("something went wrong", {"code": 500})
        assert len(received) == 1
        assert received[0].payload["action"] == "error"
        assert received[0].payload["error"] == "something went wrong"
        assert received[0].payload["code"] == 500
        assert received[0].priority == EventPriority.HIGH


# ======================================================================
# BrowserPermissionManager
# ======================================================================


class TestBrowserPermissionManager:
    def test_check_permission_no_context(self, perm_mgr: BrowserPermissionManager) -> None:
        assert perm_mgr.check_permission(BrowserAction.NAVIGATE) is False

    def test_check_permission_granted(self, perm_mgr: BrowserPermissionManager) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True}))
        perm_mgr.set_context(ctx)
        assert perm_mgr.check_permission(BrowserAction.NAVIGATE) is True

    def test_check_permission_denied(self, perm_mgr: BrowserPermissionManager) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True}))
        perm_mgr.set_context(ctx)
        assert perm_mgr.check_permission(BrowserAction.CLICK) is False

    def test_check_permission_str(self, perm_mgr: BrowserPermissionManager) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.extract": True}))
        perm_mgr.set_context(ctx)
        assert perm_mgr.check_permission("extract") is True
        assert perm_mgr.check_permission("navigate") is False

    def test_check_all_permissions(self, perm_mgr: BrowserPermissionManager) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True, "browser.click": True}))
        perm_mgr.set_context(ctx)
        results = perm_mgr.check_all_permissions([BrowserAction.NAVIGATE, BrowserAction.CLICK, BrowserAction.EXTRACT])
        assert results["navigate"] is True
        assert results["click"] is True
        assert results["extract"] is False

    def test_set_context(self, perm_mgr: BrowserPermissionManager) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={}))
        perm_mgr.set_context(ctx)
        assert perm_mgr._context is ctx

    def test_check_all_permissions_with_strings(self, perm_mgr: BrowserPermissionManager) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.scroll": True}))
        perm_mgr.set_context(ctx)
        results = perm_mgr.check_all_permissions(["scroll", "click"])
        assert results["scroll"] is True
        assert results["click"] is False


# ======================================================================
# BrowserCommandBridge
# ======================================================================


class TestBrowserCommandBridge:
    async def test_execute_navigate(self, command_bridge: BrowserCommandBridge) -> None:
        result = await command_bridge.execute_navigate("https://example.com")
        assert result["success"] is True
        assert result["action"] == "navigate"
        assert result["url"] == "https://example.com"

    async def test_execute_click(self, command_bridge: BrowserCommandBridge) -> None:
        result = await command_bridge.execute_click("#submit-btn")
        assert result["success"] is True
        assert result["selector"] == "#submit-btn"

    async def test_execute_extract(self, command_bridge: BrowserCommandBridge) -> None:
        result = await command_bridge.execute_extract("h1", "textContent")
        assert result["success"] is True
        assert result["attribute"] == "textContent"

    async def test_execute_scroll(self, command_bridge: BrowserCommandBridge) -> None:
        result = await command_bridge.execute_scroll(0, 500)
        assert result["success"] is True
        assert result["y"] == 500

    async def test_execute_screenshot(self, command_bridge: BrowserCommandBridge) -> None:
        result = await command_bridge.execute_screenshot()
        assert result["success"] is True
        assert result["action"] == "screenshot"

    async def test_execute_inject_script(self, command_bridge: BrowserCommandBridge) -> None:
        result = await command_bridge.execute_inject_script("alert('hello')")
        assert result["success"] is True
        assert result["action"] == "inject_script"

    async def test_execute_form_fill(self, command_bridge: BrowserCommandBridge) -> None:
        result = await command_bridge.execute_form_fill("login", {"user": "john", "pass": "secret"})
        assert result["success"] is True
        assert result["form_id"] == "login"
        assert result["fields"]["user"] == "john"

    async def test_execute_download(self, command_bridge: BrowserCommandBridge) -> None:
        result = await command_bridge.execute_download("https://example.com/file.pdf", "/tmp/file.pdf")
        assert result["success"] is True
        assert result["url"] == "https://example.com/file.pdf"
        assert result["destination"] == "/tmp/file.pdf"


# ======================================================================
# BrowserCompanion (IService)
# ======================================================================


class TestBrowserCompanion:
    async def test_initialize(self, companion: BrowserCompanion) -> None:
        assert companion.name == "browser_companion"
        await companion.initialize()

    async def test_start_stop(self, companion: BrowserCompanion) -> None:
        await companion.start()
        assert companion._running
        await companion.stop()
        assert not companion._running

    async def test_health_check(self, companion: BrowserCompanion) -> None:
        health = await companion.health_check()
        assert health.healthy
        assert health.metadata["sessions"] == 0
        assert health.metadata["current_url"] == ""

    async def test_connect_browser(self, companion: BrowserCompanion) -> None:
        session_id = await companion.connect_browser("chrome", "120.0", ["tabs"])
        assert session_id is not None
        assert companion.session_manager.session_count == 1
        session = companion.session_manager.get_session(session_id)
        assert session is not None
        assert session.browser_type == "chrome"

    async def test_disconnect_browser(self, companion: BrowserCompanion) -> None:
        session_id = await companion.connect_browser("chrome")
        assert await companion.disconnect_browser(session_id) is True
        assert companion.session_manager.active_session_id is None

    async def test_disconnect_nonexistent(self, companion: BrowserCompanion) -> None:
        assert await companion.disconnect_browser("nope") is False

    async def test_update_page(self, companion: BrowserCompanion) -> None:
        page = await companion.update_page(url="https://example.com", title="Test")
        assert page.url == "https://example.com"
        assert page.title == "Test"
        assert companion.metrics.pages_visited == 1

    async def test_update_page_increments_visited(self, companion: BrowserCompanion) -> None:
        await companion.update_page(url="https://example.com")
        await companion.update_page(url="https://other.com")
        assert companion.metrics.pages_visited == 2

    async def test_update_page_no_url_no_increment(self, companion: BrowserCompanion) -> None:
        await companion.update_page(title="New Title")
        assert companion.metrics.pages_visited == 0

    async def test_current_page_property(self, companion: BrowserCompanion) -> None:
        page = companion.current_page
        assert isinstance(page, PageContext)

    async def test_track_selection(self, companion: BrowserCompanion) -> None:
        sel = SelectionState(selected_text="hello", page_url="https://example.com")
        await companion.track_selection(sel)
        assert companion.selection_tracker.has_selection is True
        assert companion.metrics.selections_tracked == 1

    async def test_track_form(self, companion: BrowserCompanion) -> None:
        form = await companion.track_form("login", "/submit", "post")
        assert form.form_id == "login"
        assert companion.form_tracker.form_count == 1
        assert companion.metrics.forms_tracked == 1

    async def test_set_context(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True}))
        companion.set_context(ctx)
        assert companion.permission_manager._context is ctx

    async def test_execute_action_permission_denied(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={}))
        companion.set_context(ctx)
        result = await companion.execute_action(BrowserAction.NAVIGATE, url="https://example.com")
        assert result["success"] is False
        assert "Permission denied" in result["error"]
        assert companion.metrics.errors == 1

    async def test_execute_action_success(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True}))
        companion.set_context(ctx)
        result = await companion.execute_action(BrowserAction.NAVIGATE, url="https://example.com")
        assert result["success"] is True
        assert companion.metrics.commands_executed == 1

    async def test_execute_action_unknown(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.unknown": True}))
        companion.set_context(ctx)
        result = await companion.execute_action("unknown")
        assert result["success"] is False
        assert "Unknown browser action" in result["error"]
        assert companion.metrics.errors == 1

    async def test_execute_action_via_string(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.click": True}))
        companion.set_context(ctx)
        result = await companion.execute_action("click", selector="#btn")
        assert result["success"] is True
        assert result["selector"] == "#btn"

    async def test_execute_action_increments_metrics(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True, "browser.click": True}))
        companion.set_context(ctx)
        await companion.execute_action("navigate", url="https://example.com")
        await companion.execute_action("click", selector="#btn")
        assert companion.metrics.commands_executed == 2
        assert companion.metrics.total_timing_ms >= 0

    async def test_session_manager_property(self, companion: BrowserCompanion) -> None:
        assert companion.session_manager is companion._session_manager

    async def test_dom_inspector_property(self, companion: BrowserCompanion) -> None:
        assert companion.dom_inspector is companion._dom_inspector

    async def test_selection_tracker_property(self, companion: BrowserCompanion) -> None:
        assert companion.selection_tracker is companion._selection_tracker

    async def test_form_tracker_property(self, companion: BrowserCompanion) -> None:
        assert companion.form_tracker is companion._form_tracker

    async def test_permission_manager_property(self, companion: BrowserCompanion) -> None:
        assert companion.permission_manager is companion._permission_manager

    async def test_command_bridge_property(self, companion: BrowserCompanion) -> None:
        assert companion.command_bridge is companion._command_bridge

    async def test_event_bridge_property(self, companion: BrowserCompanion) -> None:
        assert companion.event_bridge is companion._event_bridge

    async def test_metrics_property(self, companion: BrowserCompanion) -> None:
        assert companion.metrics is companion._metrics

    async def test_health_after_actions(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True}))
        companion.set_context(ctx)
        await companion.connect_browser("chrome")
        await companion.update_page(url="https://example.com", title="Test")
        await companion.execute_action("navigate", url="https://example.com")
        health = await companion.health_check()
        assert health.metadata["sessions"] == 1
        assert health.metadata["pages_visited"] == 1
        assert health.metadata["commands_executed"] == 1
        assert health.metadata["current_url"] == "https://example.com"

    async def test_publishes_events(self, bus: EventBus) -> None:
        companion = BrowserCompanion(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("browser", handler)
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True}))
        companion.set_context(ctx)
        await companion.connect_browser("chrome")
        await companion.update_page(url="https://example.com")
        await companion.execute_action("navigate", url="https://example.com")
        assert len(received) >= 2

    async def test_update_page_integrates_dom_inspector(self, companion: BrowserCompanion) -> None:
        await companion.update_page(url="https://example.com")
        info = companion.dom_inspector.get_element_info("#main")
        assert info["page_url"] == "https://example.com"

    async def test_execute_action_with_session_id(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(permissions={"browser.navigate": True}))
        companion.set_context(ctx)
        result = await companion.execute_action("navigate", url="https://example.com", session_id="sess-1")
        assert result["success"] is True

    async def test_execute_all_action_types(self, companion: BrowserCompanion) -> None:
        ctx = AtlasContext(permissions=PermissionContext(
            permissions={
                "browser.navigate": True,
                "browser.click": True,
                "browser.extract": True,
                "browser.scroll": True,
                "browser.screenshot": True,
                "browser.inject_script": True,
                "browser.form_fill": True,
                "browser.download": True,
            },
        ))
        companion.set_context(ctx)

        assert (await companion.execute_action("navigate", url="https://x.com"))["success"] is True
        assert (await companion.execute_action("click", selector="#btn"))["success"] is True
        assert (await companion.execute_action("extract", selector="h1"))["success"] is True
        assert (await companion.execute_action("scroll", x=0, y=100))["success"] is True
        assert (await companion.execute_action("screenshot"))["success"] is True
        assert (await companion.execute_action("inject_script", script="alert(1)"))["success"] is True
        assert (await companion.execute_action("form_fill", form_id="f", fields={"a": "b"}))["success"] is True
        assert (await companion.execute_action("download", url="https://x.com/f.pdf"))["success"] is True
        assert companion.metrics.commands_executed == 8
