"""Browser Companion — browser awareness for Atlas.

The Browser Companion observes browser state, forwards context to Atlas,
and executes only commands approved by the Execution Engine.
It never performs AI reasoning and never contains business logic.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from atlas_core.context import AtlasContext
from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Enums
# ======================================================================


class BrowserConnectionStatus(Enum):
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    ERROR = auto()


class PageLoadStatus(Enum):
    LOADING = auto()
    LOADED = auto()
    ERROR = auto()
    TIMEOUT = auto()


class BrowserAction(Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    EXTRACT = "extract"
    SCROLL = "scroll"
    SCREENSHOT = "screenshot"
    INJECT_SCRIPT = "inject_script"
    FORM_FILL = "form_fill"
    DOWNLOAD = "download"


class SelectionType(Enum):
    TEXT = auto()
    ELEMENT = auto()
    RANGE = auto()


# ======================================================================
# Browser session
# ======================================================================


@dataclass
class BrowserSession:
    session_id: str = field(default_factory=lambda: str(uuid4()))
    browser_type: str = ""
    browser_version: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    connection_status: BrowserConnectionStatus = BrowserConnectionStatus.DISCONNECTED
    capabilities: list[str] = field(default_factory=list)


# ======================================================================
# PageContext
# ======================================================================


@dataclass
class PageContext:
    url: str = ""
    title: str = ""
    load_status: PageLoadStatus = PageLoadStatus.LOADED
    viewport_width: int = 0
    viewport_height: int = 0
    scroll_x: float = 0.0
    scroll_y: float = 0.0
    dom_loaded: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=datetime.now)


# ======================================================================
# Selection state
# ======================================================================


@dataclass
class SelectionState:
    selected_text: str = ""
    selection_type: SelectionType = SelectionType.TEXT
    element_tag: str = ""
    element_id: str = ""
    element_classes: list[str] = field(default_factory=list)
    start_offset: int = 0
    end_offset: int = 0
    page_url: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


# ======================================================================
# Form state
# ======================================================================


@dataclass
class FormFieldState:
    name: str = ""
    field_type: str = ""
    current_value: str = ""
    is_dirty: bool = False
    is_valid: bool = True
    validation_message: str = ""


@dataclass
class FormState:
    form_id: str = ""
    action: str = ""
    method: str = "get"
    fields: dict[str, FormFieldState] = field(default_factory=dict)
    is_dirty: bool = False
    is_valid: bool = True
    page_url: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


# ======================================================================
# Browser metrics
# ======================================================================


@dataclass
class BrowserMetrics:
    pages_visited: int = 0
    commands_executed: int = 0
    events_processed: int = 0
    errors: int = 0
    total_timing_ms: float = 0.0
    selections_tracked: int = 0
    forms_tracked: int = 0

    @property
    def avg_timing_ms(self) -> float:
        total = self.commands_executed + self.events_processed
        return self.total_timing_ms / total if total > 0 else 0.0


# ======================================================================
# BrowserSessionManager
# ======================================================================


class BrowserSessionManager:
    """Manages browser session lifecycle and state."""

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._active_session_id: str | None = None
        self._logger = logging.getLogger(__name__)

    def create_session(
        self,
        browser_type: str = "",
        browser_version: str = "",
        capabilities: list[str] | None = None,
    ) -> BrowserSession:
        session = BrowserSession(
            browser_type=browser_type,
            browser_version=browser_version,
            connection_status=BrowserConnectionStatus.CONNECTED,
            capabilities=capabilities or [],
        )
        self._sessions[session.session_id] = session
        self._active_session_id = session.session_id
        self._logger.info("Created browser session %s (%s)", session.session_id, browser_type)
        return session

    def close_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            return False
        session.connection_status = BrowserConnectionStatus.DISCONNECTED
        if self._active_session_id == session_id:
            self._active_session_id = None
        self._logger.info("Closed browser session %s", session_id)
        return True

    def get_session(self, session_id: str) -> BrowserSession | None:
        return self._sessions.get(session_id)

    def active_session(self) -> BrowserSession | None:
        if self._active_session_id is None:
            return None
        return self._sessions.get(self._active_session_id)

    def set_active_session(self, session_id: str) -> bool:
        if session_id not in self._sessions:
            return False
        self._active_session_id = session_id
        return True

    def touch_session(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_active = datetime.now()

    def list_sessions(self) -> list[BrowserSession]:
        return list(self._sessions.values())

    @property
    def session_count(self) -> int:
        return len(self._sessions)

    @property
    def active_session_id(self) -> str | None:
        return self._active_session_id

    def clear(self) -> None:
        self._sessions.clear()
        self._active_session_id = None


# ======================================================================
# DOMInspector
# ======================================================================


class DOMInspector:
    """Inspector for DOM structure and content.

    In production, this would communicate with the browser extension
    to query the real DOM.  In v1, it operates on provided snapshots.
    """

    def __init__(self) -> None:
        self._current_page: PageContext | None = None
        self._logger = logging.getLogger(__name__)

    def set_page(self, page: PageContext) -> None:
        self._current_page = page

    def get_element_info(self, selector: str, attribute: str = "") -> dict[str, Any]:
        """Return info about an element matched by selector (stub)."""
        if self._current_page is None:
            return {"found": False, "error": "No page context"}
        return {
            "found": True,
            "selector": selector,
            "attribute": attribute,
            "page_url": self._current_page.url,
        }

    def query_elements(self, selector: str) -> list[dict[str, Any]]:
        """Return a list of elements matching the selector (stub)."""
        if self._current_page is None:
            return []
        return [
            {
                "found": True,
                "selector": selector,
                "page_url": self._current_page.url,
                "count": 0,
            }
        ]

    def get_page_text(self) -> str:
        """Return the visible text content of the current page (stub)."""
        return ""

    def get_element_by_id(self, element_id: str) -> dict[str, Any]:
        """Return element info by ID (stub)."""
        return {"found": False, "element_id": element_id}

    def get_attributes(self, element_id: str, attributes: list[str]) -> dict[str, Any]:
        """Return specified attributes of an element (stub)."""
        return {
            "found": False,
            "element_id": element_id,
            "attributes": {a: "" for a in attributes},
        }


# ======================================================================
# SelectionTracker
# ======================================================================


class SelectionTracker:
    """Tracks user text selections in the browser."""

    def __init__(self) -> None:
        self._selection: SelectionState | None = None
        self._history: list[SelectionState] = []
        self._logger = logging.getLogger(__name__)

    def on_selection_change(self, selection: SelectionState) -> None:
        self._selection = selection
        self._history.append(selection)
        self._logger.debug("Selection tracked: %d chars", len(selection.selected_text))

    def get_selection(self) -> SelectionState | None:
        return self._selection

    def clear_selection(self) -> None:
        self._selection = None

    def list_history(self, limit: int = 50) -> list[SelectionState]:
        return self._history[-limit:]

    @property
    def has_selection(self) -> bool:
        return self._selection is not None

    @property
    def selection_count(self) -> int:
        return len(self._history)

    def clear_history(self) -> None:
        self._history.clear()
        self._selection = None


# ======================================================================
# FormTracker
# ======================================================================


class FormTracker:
    """Tracks form state across pages."""

    def __init__(self) -> None:
        self._forms: dict[str, FormState] = {}
        self._logger = logging.getLogger(__name__)

    def track_form(self, form_id: str, action: str = "", method: str = "get") -> FormState:
        form = FormState(form_id=form_id, action=action, method=method)
        self._forms[form_id] = form
        self._logger.debug("Tracking form %s", form_id)
        return form

    def update_field(
        self,
        form_id: str,
        field_name: str,
        value: str,
        field_type: str = "text",
    ) -> bool:
        form = self._forms.get(form_id)
        if form is None:
            return False
        existing = form.fields.get(field_name)
        if existing is None:
            form.fields[field_name] = FormFieldState(
                name=field_name,
                field_type=field_type,
                current_value=value,
                is_dirty=False,
            )
        else:
            existing.current_value = value
            existing.is_dirty = True
        form.is_dirty = True
        form.timestamp = datetime.now()
        return True

    def set_field_validity(self, form_id: str, field_name: str, is_valid: bool, message: str = "") -> bool:
        form = self._forms.get(form_id)
        if form is None:
            return False
        field = form.fields.get(field_name)
        if field is None:
            return False
        field.is_valid = is_valid
        field.validation_message = message
        form.is_valid = all(f.is_valid for f in form.fields.values())
        return True

    def get_form(self, form_id: str) -> FormState | None:
        return self._forms.get(form_id)

    def remove_form(self, form_id: str) -> bool:
        if form_id in self._forms:
            del self._forms[form_id]
            return True
        return False

    def list_forms(self) -> list[FormState]:
        return list(self._forms.values())

    def clear(self) -> None:
        self._forms.clear()

    @property
    def form_count(self) -> int:
        return len(self._forms)


# ======================================================================
# BrowserEventBridge
# ======================================================================


class BrowserEventBridge:
    """Bridges browser events to the Atlas Event Bus."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        """Publish a browser event to the Event Bus."""
        await self._event_bus.publish(Event(
            source="browser_companion",
            category=EventCategory.BROWSER,
            priority=priority,
            payload={
                "action": action,
                **(payload or {}),
            },
        ))
        self._logger.debug("Published browser event: %s", action)

    async def publish_page_change(self, page: PageContext) -> None:
        await self.publish("page_changed", {
            "url": page.url,
            "title": page.title,
            "load_status": page.load_status.name,
        })

    async def publish_selection(self, selection: SelectionState) -> None:
        await self.publish("selection_changed", {
            "selected_text": selection.selected_text,
            "selection_type": selection.selection_type.name,
            "page_url": selection.page_url,
        })

    async def publish_form_change(self, form: FormState) -> None:
        await self.publish("form_changed", {
            "form_id": form.form_id,
            "is_dirty": form.is_dirty,
            "is_valid": form.is_valid,
            "page_url": form.page_url,
        })

    async def publish_connection_status(self, status: BrowserConnectionStatus) -> None:
        await self.publish("connection_status", {
            "status": status.name,
        }, priority=EventPriority.HIGH)

    async def publish_error(self, error: str, details: dict[str, Any] | None = None) -> None:
        await self.publish("error", {
            "error": error,
            **(details or {}),
        }, priority=EventPriority.HIGH)


# ======================================================================
# BrowserPermissionManager
# ======================================================================


class BrowserPermissionManager:
    """Manages browser-specific permission checks.

    Permissions are stored in AtlasContext.permissions with the
    prefix 'browser.' (e.g. 'browser.navigate', 'browser.extract').
    """

    def __init__(self) -> None:
        self._context: AtlasContext | None = None
        self._logger = logging.getLogger(__name__)

    def set_context(self, context: AtlasContext) -> None:
        self._context = context

    def check_permission(self, action: BrowserAction | str) -> bool:
        """Check if a browser action is permitted."""
        action_str = action.value if isinstance(action, BrowserAction) else action
        if self._context is None:
            return False
        return self._context.permissions.permissions.get(f"browser.{action_str}", False)

    def check_all_permissions(self, actions: list[BrowserAction | str]) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for action in actions:
            action_str = action.value if isinstance(action, BrowserAction) else action
            results[action_str] = self.check_permission(action_str)
        return results


# ======================================================================
# BrowserCommandBridge
# ======================================================================


class BrowserCommandBridge:
    """Translates approved commands into browser actions.

    In production this would send messages to the browser extension.
    In v1 it simulates execution and returns results.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    async def execute_navigate(self, url: str, session_id: str = "") -> dict[str, Any]:
        self._logger.info("Navigate: %s (session: %s)", url, session_id or "none")
        return {"success": True, "action": "navigate", "url": url}

    async def execute_click(self, selector: str, session_id: str = "") -> dict[str, Any]:
        self._logger.info("Click: %s (session: %s)", selector, session_id or "none")
        return {"success": True, "action": "click", "selector": selector}

    async def execute_extract(self, selector: str, attribute: str = "", session_id: str = "") -> dict[str, Any]:
        self._logger.info("Extract: %s attr=%s (session: %s)", selector, attribute, session_id or "none")
        return {"success": True, "action": "extract", "selector": selector, "attribute": attribute}

    async def execute_scroll(self, x: float, y: float, session_id: str = "") -> dict[str, Any]:
        self._logger.info("Scroll: (%f, %f) (session: %s)", x, y, session_id or "none")
        return {"success": True, "action": "scroll", "x": x, "y": y}

    async def execute_screenshot(self, session_id: str = "") -> dict[str, Any]:
        self._logger.info("Screenshot (session: %s)", session_id or "none")
        return {"success": True, "action": "screenshot"}

    async def execute_inject_script(self, script: str, session_id: str = "") -> dict[str, Any]:
        self._logger.info("Inject script (session: %s)", session_id or "none")
        return {"success": True, "action": "inject_script"}

    async def execute_form_fill(self, form_id: str, fields: dict[str, str], session_id: str = "") -> dict[str, Any]:
        self._logger.info("Form fill: %s (session: %s)", form_id, session_id or "none")
        return {"success": True, "action": "form_fill", "form_id": form_id, "fields": fields}

    async def execute_download(self, url: str, destination: str = "", session_id: str = "") -> dict[str, Any]:
        self._logger.info("Download: %s → %s (session: %s)", url, destination or "default", session_id or "none")
        return {"success": True, "action": "download", "url": url, "destination": destination}


# ======================================================================
# BrowserCompanion — IService
# ======================================================================


class BrowserCompanion(IService):
    """Central orchestrator for browser awareness.

    Observes browser state, forwards context to Atlas,
    and executes only commands approved by the Execution Engine.
    Never performs AI reasoning. Never contains business logic.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        self._session_manager = BrowserSessionManager()
        self._dom_inspector = DOMInspector()
        self._selection_tracker = SelectionTracker()
        self._form_tracker = FormTracker()
        self._event_bridge = BrowserEventBridge(event_bus)
        self._permission_manager = BrowserPermissionManager()
        self._command_bridge = BrowserCommandBridge()
        self._metrics = BrowserMetrics()

        self._current_page: PageContext = PageContext()
        self._running = False

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "browser_companion"

    async def initialize(self) -> None:
        self._logger.info("Browser Companion initializing")

    async def start(self) -> None:
        self._running = True
        self._logger.info("Browser Companion started")

    async def stop(self) -> None:
        self._running = False
        self._logger.info("Browser Companion stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "sessions": self._session_manager.session_count,
                "active_session": self._session_manager.active_session_id or "none",
                "current_url": self._current_page.url,
                "pages_visited": self._metrics.pages_visited,
                "commands_executed": self._metrics.commands_executed,
                "forms_tracked": self._form_tracker.form_count,
                "selections_tracked": self._selection_tracker.selection_count,
            },
        )

    # ------------------------------------------------------------------
    # Context integration
    # ------------------------------------------------------------------

    def set_context(self, context: AtlasContext) -> None:
        self._permission_manager.set_context(context)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    @property
    def session_manager(self) -> BrowserSessionManager:
        return self._session_manager

    async def connect_browser(
        self,
        browser_type: str = "",
        browser_version: str = "",
        capabilities: list[str] | None = None,
    ) -> str:
        session = self._session_manager.create_session(browser_type, browser_version, capabilities)
        await self._event_bridge.publish_connection_status(BrowserConnectionStatus.CONNECTED)
        return session.session_id

    async def disconnect_browser(self, session_id: str) -> bool:
        result = self._session_manager.close_session(session_id)
        if result:
            await self._event_bridge.publish_connection_status(BrowserConnectionStatus.DISCONNECTED)
        return result

    # ------------------------------------------------------------------
    # Page management
    # ------------------------------------------------------------------

    @property
    def current_page(self) -> PageContext:
        return self._current_page

    async def update_page(self, **updates: Any) -> PageContext:
        for key, value in updates.items():
            if hasattr(self._current_page, key):
                setattr(self._current_page, key, value)
        self._current_page.updated_at = datetime.now()

        if "url" in updates:
            self._metrics.pages_visited += 1

        await self._event_bridge.publish_page_change(self._current_page)
        self._dom_inspector.set_page(self._current_page)
        return self._current_page

    # ------------------------------------------------------------------
    # DOM inspection
    # ------------------------------------------------------------------

    @property
    def dom_inspector(self) -> DOMInspector:
        return self._dom_inspector

    # ------------------------------------------------------------------
    # Selection tracking
    # ------------------------------------------------------------------

    @property
    def selection_tracker(self) -> SelectionTracker:
        return self._selection_tracker

    async def track_selection(self, selection: SelectionState) -> None:
        self._selection_tracker.on_selection_change(selection)
        self._metrics.selections_tracked += 1
        await self._event_bridge.publish_selection(selection)

    # ------------------------------------------------------------------
    # Form tracking
    # ------------------------------------------------------------------

    @property
    def form_tracker(self) -> FormTracker:
        return self._form_tracker

    async def track_form(self, form_id: str, action: str = "", method: str = "get") -> FormState:
        form = self._form_tracker.track_form(form_id, action, method)
        self._metrics.forms_tracked += 1
        return form

    # ------------------------------------------------------------------
    # Permission management
    # ------------------------------------------------------------------

    @property
    def permission_manager(self) -> BrowserPermissionManager:
        return self._permission_manager

    # ------------------------------------------------------------------
    # Command execution
    # ------------------------------------------------------------------

    @property
    def command_bridge(self) -> BrowserCommandBridge:
        return self._command_bridge

    async def execute_action(self, action: BrowserAction | str, **params: Any) -> dict[str, Any]:
        """Execute a browser action after permission check.

        In production this would route through the Execution Engine.
        """
        action_str = action.value if isinstance(action, BrowserAction) else action

        if not self._permission_manager.check_permission(action_str):
            self._metrics.errors += 1
            return {"success": False, "error": f"Permission denied: browser.{action_str}"}

        start = time.monotonic()
        try:
            result = await self._route_action(action_str, params)
            elapsed = (time.monotonic() - start) * 1000
            self._metrics.commands_executed += 1
            self._metrics.total_timing_ms += elapsed
            return result
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            self._metrics.errors += 1
            self._metrics.total_timing_ms += elapsed
            await self._event_bridge.publish_error(str(exc))
            return {"success": False, "error": str(exc)}

    async def _route_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.pop("session_id", "")
        method_map: dict[str, Any] = {
            "navigate": self._command_bridge.execute_navigate,
            "click": self._command_bridge.execute_click,
            "extract": self._command_bridge.execute_extract,
            "scroll": self._command_bridge.execute_scroll,
            "screenshot": self._command_bridge.execute_screenshot,
            "inject_script": self._command_bridge.execute_inject_script,
            "form_fill": self._command_bridge.execute_form_fill,
            "download": self._command_bridge.execute_download,
        }
        handler = method_map.get(action)
        if handler is None:
            raise ValueError(f"Unknown browser action: {action}")
        return await handler(**params, session_id=session_id)

    # ------------------------------------------------------------------
    # Event bridge
    # ------------------------------------------------------------------

    @property
    def event_bridge(self) -> BrowserEventBridge:
        return self._event_bridge

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def metrics(self) -> BrowserMetrics:
        return self._metrics
