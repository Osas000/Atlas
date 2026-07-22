"""Mission Control — the orchestration brain of Atlas.

Coordinates all subsystems.
Owns no business logic.
Never communicates directly with AI providers.
Never executes OS commands.
Never manipulates browsers.
Never stores knowledge.
Always delegates to the appropriate subsystem.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from atlas_core.context import AtlasContext
from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState, SubsystemResponse
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Enums
# ======================================================================


class Subsystem(Enum):
    MEMORY = "memory"
    KNOWLEDGE = "knowledge"
    INTELLIGENCE = "intelligence"
    EXECUTION = "execution"
    BROWSER = "browser"
    OPPORTUNITY = "opportunity"
    NOTIFICATION = "notification"


class MissionStatus(Enum):
    CREATED = auto()
    PLANNING = auto()
    WAITING = auto()
    RUNNING = auto()
    PAUSED = auto()
    BLOCKED = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()


class StepState(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    SKIPPED = auto()


# ======================================================================
# Core data classes
# ======================================================================


@dataclass(frozen=True)
class Mission:
    """An immutable mission — the unit of work in Mission Control.

    Once created, mission fields cannot be mutated.
    Status transitions go through MissionStateMachine.
    """

    mission_id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    description: str = ""
    objective: str = ""
    priority: int = 0
    status: MissionStatus = MissionStatus.CREATED
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MissionStep:
    """An immutable mission step — a single unit of work.

    Each step routes to exactly one Subsystem.
    The MissionExecutor coordinates execution but never performs work.
    """

    step_id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    description: str = ""
    order: int = 0
    subsystem: Subsystem = Subsystem.KNOWLEDGE
    dependencies: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    result: dict[str, Any] = field(default_factory=dict)
    state: StepState = StepState.PENDING
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class MissionPlan:
    """A mission with its ordered execution steps."""

    mission: Mission
    steps: list[MissionStep] = field(default_factory=list)


@dataclass
class HistoryEntry:
    """A single entry in mission history."""

    mission_id: str = ""
    title: str = ""
    status: MissionStatus = MissionStatus.CREATED
    priority: int = 0
    duration: float = 0.0
    steps_total: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    completed_at: datetime | None = None


@dataclass
class MissionMetrics:
    """Usage and performance metrics for Mission Control."""

    missions_created: int = 0
    missions_completed: int = 0
    missions_failed: int = 0
    missions_cancelled: int = 0
    steps_executed: int = 0
    steps_failed: int = 0
    active_missions: int = 0
    total_duration: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.missions_completed + self.missions_failed
        if total == 0:
            return 0.0
        return (self.missions_completed / total) * 100.0

    @property
    def average_duration(self) -> float:
        total = self.missions_completed + self.missions_failed
        if total == 0:
            return 0.0
        return self.total_duration / total


# ======================================================================
# MissionStateMachine
# ======================================================================


class MissionStateMachine:
    """Enforces legal mission status transitions.

    Rejects illegal transitions with a ValueError.
    """

    # Legal transitions map: current_status -> set of allowed next statuses
    TRANSITIONS: dict[MissionStatus, set[MissionStatus]] = {
        MissionStatus.CREATED: {MissionStatus.PLANNING, MissionStatus.CANCELLED},
        MissionStatus.PLANNING: {MissionStatus.RUNNING, MissionStatus.FAILED, MissionStatus.CANCELLED},
        MissionStatus.RUNNING: {
            MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.PAUSED,
            MissionStatus.BLOCKED, MissionStatus.WAITING, MissionStatus.CANCELLED,
        },
        MissionStatus.PAUSED: {MissionStatus.RUNNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.BLOCKED: {MissionStatus.WAITING, MissionStatus.RUNNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.WAITING: {MissionStatus.RUNNING, MissionStatus.CANCELLED, MissionStatus.FAILED},
        MissionStatus.COMPLETED: set(),
        MissionStatus.FAILED: {MissionStatus.CREATED},
        MissionStatus.CANCELLED: {MissionStatus.CREATED},
    }

    def transition(self, current: MissionStatus, target: MissionStatus) -> MissionStatus:
        """Transition from current to target status.

        Raises ValueError if the transition is illegal.
        Returns the target status on success.
        """
        if current == target:
            return target

        allowed = self.TRANSITIONS.get(current, set())
        if target not in allowed:
            raise ValueError(
                f"Illegal mission status transition: {current.name} -> {target.name}. "
                f"Allowed from {current.name}: {', '.join(s.name for s in allowed) or '(none)'}"
            )
        return target

    def is_legal(self, current: MissionStatus, target: MissionStatus) -> bool:
        try:
            self.transition(current, target)
            return True
        except ValueError:
            return False


# ======================================================================
# MissionPlanner
# ======================================================================


class MissionPlanner:
    """Rule-based mission planner.

    NO AI — purely rule-based.
    Input: Mission
    Output: MissionPlan
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def plan(self, mission: Mission) -> MissionPlan:
        """Generate a MissionPlan for the given mission.

        Uses rule-based planning based on mission title, tags, and objective.
        """
        steps: list[MissionStep] = []

        combined = f"{mission.title} {mission.description} {mission.objective}".lower()
        tags_lower = {t.lower() for t in mission.tags}

        if self._matches_template(combined, tags_lower, "daily"):
            steps = self._plan_daily_review(mission)
        elif self._matches_template(combined, tags_lower, "opportunities"):
            steps = self._plan_find_opportunities(mission)
        elif self._matches_template(combined, tags_lower, "research"):
            steps = self._plan_research(mission)
        elif self._matches_template(combined, tags_lower, "build"):
            steps = self._plan_build(mission)
        elif self._matches_template(combined, tags_lower, "analyze"):
            steps = self._plan_analyze(mission)
        elif self._matches_template(combined, tags_lower, "write"):
            steps = self._plan_write(mission)
        elif self._matches_template(combined, tags_lower, "review"):
            steps = self._plan_review(mission)
        else:
            steps = self._plan_generic(mission)

        return MissionPlan(mission=mission, steps=steps)

    def _matches_template(self, text: str, tags: set[str], keyword: str) -> bool:
        if keyword in tags:
            return True
        return keyword in text

    def _plan_research(self, mission: Mission) -> list[MissionStep]:
        return [
            MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Search existing knowledge"),
            MissionStep(order=2, subsystem=Subsystem.MEMORY, title="Recall relevant context"),
            MissionStep(order=3, subsystem=Subsystem.INTELLIGENCE, title="Analyze and synthesize"),
            MissionStep(order=4, subsystem=Subsystem.KNOWLEDGE, title="Store findings"),
            MissionStep(order=5, subsystem=Subsystem.NOTIFICATION, title="Notify completion"),
        ]

    def _plan_analyze(self, mission: Mission) -> list[MissionStep]:
        return [
            MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Retrieve repository data"),
            MissionStep(order=2, subsystem=Subsystem.EXECUTION, title="Run analysis commands"),
            MissionStep(order=3, subsystem=Subsystem.INTELLIGENCE, title="Interpret results"),
            MissionStep(order=4, subsystem=Subsystem.KNOWLEDGE, title="Store analysis report"),
        ]

    def _plan_write(self, mission: Mission) -> list[MissionStep]:
        return [
            MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Research topic"),
            MissionStep(order=2, subsystem=Subsystem.INTELLIGENCE, title="Draft content"),
            MissionStep(order=3, subsystem=Subsystem.KNOWLEDGE, title="Store draft"),
            MissionStep(order=4, subsystem=Subsystem.KNOWLEDGE, title="Review and refine"),
        ]

    def _plan_review(self, mission: Mission) -> list[MissionStep]:
        return [
            MissionStep(order=1, subsystem=Subsystem.EXECUTION, title="Fetch code"),
            MissionStep(order=2, subsystem=Subsystem.INTELLIGENCE, title="Review code quality"),
            MissionStep(order=3, subsystem=Subsystem.KNOWLEDGE, title="Store review report"),
            MissionStep(order=4, subsystem=Subsystem.NOTIFICATION, title="Notify author"),
        ]

    def _plan_find_opportunities(self, mission: Mission) -> list[MissionStep]:
        return [
            MissionStep(order=1, subsystem=Subsystem.OPPORTUNITY, title="Discover opportunities"),
            MissionStep(order=2, subsystem=Subsystem.MEMORY, title="Check past matches"),
            MissionStep(order=3, subsystem=Subsystem.INTELLIGENCE, title="Score and rank"),
            MissionStep(order=4, subsystem=Subsystem.KNOWLEDGE, title="Store results"),
            MissionStep(order=5, subsystem=Subsystem.NOTIFICATION, title="Alert user"),
        ]

    def _plan_daily_review(self, mission: Mission) -> list[MissionStep]:
        return [
            MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Collect recent activity"),
            MissionStep(order=2, subsystem=Subsystem.MEMORY, title="Recall priority items"),
            MissionStep(order=3, subsystem=Subsystem.OPPORTUNITY, title="Check new opportunities"),
            MissionStep(order=4, subsystem=Subsystem.INTELLIGENCE, title="Summarize"),
            MissionStep(order=5, subsystem=Subsystem.KNOWLEDGE, title="Store daily summary"),
            MissionStep(order=6, subsystem=Subsystem.NOTIFICATION, title="Deliver briefing"),
        ]

    def _plan_build(self, mission: Mission) -> list[MissionStep]:
        return [
            MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Gather requirements"),
            MissionStep(order=2, subsystem=Subsystem.INTELLIGENCE, title="Design architecture"),
            MissionStep(order=3, subsystem=Subsystem.EXECUTION, title="Implement"),
            MissionStep(order=4, subsystem=Subsystem.EXECUTION, title="Test"),
            MissionStep(order=5, subsystem=Subsystem.KNOWLEDGE, title="Document"),
            MissionStep(order=6, subsystem=Subsystem.NOTIFICATION, title="Report completion"),
        ]

    def _plan_generic(self, mission: Mission) -> list[MissionStep]:
        return [
            MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Gather information"),
            MissionStep(order=2, subsystem=Subsystem.INTELLIGENCE, title="Process"),
            MissionStep(order=3, subsystem=Subsystem.KNOWLEDGE, title="Store result"),
            MissionStep(order=4, subsystem=Subsystem.NOTIFICATION, title="Notify"),
        ]


# ======================================================================
# MissionScheduler
# ======================================================================


@dataclass
class ScheduledMission:
    """A mission queued in the scheduler."""

    mission_id: str
    priority: int
    enqueued_at: float = field(default_factory=time.time)
    is_paused: bool = False


class MissionScheduler:
    """Priority queue for missions.

    Supports enqueue, dequeue, priority, pause, resume, cancel.
    """

    def __init__(self) -> None:
        self._queue: list[ScheduledMission] = []
        self._missions: dict[str, ScheduledMission] = {}
        self._logger = logging.getLogger(__name__)

    def enqueue(self, mission_id: str, priority: int = 0) -> ScheduledMission:
        """Enqueue a mission with the given priority.

        Higher priority values are dequeued first.
        """
        sm = ScheduledMission(mission_id=mission_id, priority=priority)
        self._missions[mission_id] = sm
        self._queue.append(sm)
        self._queue.sort(key=lambda x: x.priority, reverse=True)
        self._logger.debug("Enqueued mission %s (priority=%d)", mission_id, priority)
        return sm

    def dequeue(self) -> ScheduledMission | None:
        """Dequeue the highest-priority non-paused mission."""
        for sm in self._queue:
            if not sm.is_paused:
                self._queue.remove(sm)
                self._missions.pop(sm.mission_id, None)
                self._logger.debug("Dequeued mission %s", sm.mission_id)
                return sm
        return None

    def peek(self) -> ScheduledMission | None:
        """Peek at the highest-priority non-paused mission without removing it."""
        for sm in self._queue:
            if not sm.is_paused:
                return sm
        return None

    def pause(self, mission_id: str) -> bool:
        """Pause a mission. Returns True if found."""
        sm = self._missions.get(mission_id)
        if sm is None:
            return False
        sm.is_paused = True
        self._logger.debug("Paused mission %s", mission_id)
        return True

    def resume(self, mission_id: str) -> bool:
        """Resume a paused mission. Returns True if found."""
        sm = self._missions.get(mission_id)
        if sm is None:
            return False
        sm.is_paused = False
        self._logger.debug("Resumed mission %s", mission_id)
        return True

    def cancel(self, mission_id: str) -> bool:
        """Remove a mission from the queue entirely. Returns True if found."""
        sm = self._missions.pop(mission_id, None)
        if sm is None:
            return False
        if sm in self._queue:
            self._queue.remove(sm)
        self._logger.debug("Cancelled mission %s from scheduler", mission_id)
        return True

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    @property
    def pending_count(self) -> int:
        return sum(1 for sm in self._queue if not sm.is_paused)

    @property
    def paused_count(self) -> int:
        return sum(1 for sm in self._queue if sm.is_paused)

    def list_queued(self) -> list[ScheduledMission]:
        return list(self._queue)

    def clear(self) -> None:
        self._queue.clear()
        self._missions.clear()


# ======================================================================
# MissionExecutor
# ======================================================================


class MissionExecutor:
    """Coordinates execution of mission steps.

    For every MissionStep, routes by subsystem to the appropriate engine.
    NEVER performs work itself — always delegates.
    Consumes ONLY SubsystemResponse from registered handlers.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)
        self._handlers: dict[Subsystem, Any] = {}

    def register_handler(self, subsystem: Subsystem, handler: Any) -> None:
        """Register a callable handler for a subsystem.

        The handler must accept a dict payload and return SubsystemResponse.
        """
        self._handlers[subsystem] = handler
        self._logger.debug("Registered handler for subsystem: %s", subsystem.value)

    def unregister_handler(self, subsystem: Subsystem) -> None:
        self._handlers.pop(subsystem, None)
        self._logger.debug("Unregistered handler for subsystem: %s", subsystem.value)

    async def execute_step(
        self,
        step: MissionStep,
        context: dict[str, Any] | None = None,
    ) -> MissionStep:
        """Execute a single mission step by routing to the appropriate subsystem.

        Looks up a registered handler for the step's Subsystem.
        Calls the handler with step payload.
        Consumes SubsystemResponse to build the result MissionStep.
        """
        context = context or {}
        subsystem_name = step.subsystem.value
        self._logger.info(
            "Routing step '%s' (order=%d) to subsystem '%s'",
            step.title, step.order, subsystem_name,
        )

        handler = self._handlers.get(step.subsystem)
        if handler is not None:
            try:
                response = await handler(step.payload)
                if not isinstance(response, SubsystemResponse):
                    response = SubsystemResponse(
                        success=False,
                        status="error",
                        errors=["Handler did not return a SubsystemResponse"],
                        subsystem=subsystem_name,
                    )
            except Exception as e:
                response = SubsystemResponse(
                    success=False,
                    status="error",
                    errors=[str(e)],
                    subsystem=subsystem_name,
                )
        else:
            response = SubsystemResponse(
                success=True,
                status="completed",
                payload={"subsystem": subsystem_name, "title": step.title},
                subsystem=subsystem_name,
            )

        step_state = StepState.COMPLETED if response.success else StepState.FAILED

        new_step = MissionStep(
            step_id=step.step_id,
            title=step.title,
            description=step.description,
            order=step.order,
            subsystem=step.subsystem,
            dependencies=list(step.dependencies),
            retry_count=step.retry_count,
            max_retries=step.max_retries,
            result=response.payload,
            state=step_state,
            payload=dict(step.payload),
        )

        await self._publish_event("step_routed" if response.success else "step_failed", {
            "step_id": step.step_id,
            "subsystem": subsystem_name,
            "title": step.title,
            "order": step.order,
            "success": response.success,
            "errors": response.errors,
        })

        return new_step

    async def execute_plan(
        self,
        plan: MissionPlan,
        context: dict[str, Any] | None = None,
    ) -> MissionPlan:
        """Execute all steps in a mission plan in dependency order."""
        context = context or {}
        executed_steps: list[MissionStep] = []
        step_map: dict[str, MissionStep] = {s.step_id: s for s in plan.steps}

        completed_ids: set[str] = set()

        while len(executed_steps) < len(plan.steps):
            progress = False
            for step in plan.steps:
                if step.step_id in completed_ids:
                    continue
                deps_met = all(d in completed_ids for d in step.dependencies)
                if deps_met:
                    result_step = await self.execute_step(step, context)
                    executed_steps.append(result_step)
                    completed_ids.add(step.step_id)
                    progress = True

            if not progress:
                self._logger.warning("No progress in plan execution — possible circular dependency")
                break

        return MissionPlan(mission=plan.mission, steps=executed_steps)

    async def _publish_event(self, action: str, payload: dict[str, Any]) -> None:
        try:
            await self._event_bus.publish(Event(
                source="mission_executor",
                category=EventCategory.MISSION,
                priority=EventPriority.NORMAL,
                payload={"action": action, **payload},
            ))
        except Exception:
            self._logger.exception("Failed to publish mission executor event")


# ======================================================================
# MissionHistory
# ======================================================================


class MissionHistory:
    """Ring buffer of mission history entries."""

    def __init__(self, max_size: int = 100) -> None:
        self._entries: deque[HistoryEntry] = deque(maxlen=max_size)
        self._logger = logging.getLogger(__name__)

    def record(self, entry: HistoryEntry) -> None:
        self._entries.append(entry)

    def query(
        self,
        status: MissionStatus | None = None,
        limit: int = 20,
    ) -> list[HistoryEntry]:
        results: list[HistoryEntry] = []
        for entry in reversed(self._entries):
            if status is not None and entry.status != status:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    @property
    def completed(self) -> list[HistoryEntry]:
        return self.query(status=MissionStatus.COMPLETED)

    @property
    def failed(self) -> list[HistoryEntry]:
        return self.query(status=MissionStatus.FAILED)

    @property
    def cancelled(self) -> list[HistoryEntry]:
        return self.query(status=MissionStatus.CANCELLED)

    @property
    def running(self) -> list[HistoryEntry]:
        return self.query(status=MissionStatus.RUNNING)

    @property
    def total_entries(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()


# ======================================================================
# MissionTemplates
# ======================================================================


@dataclass
class MissionTemplate:
    """A reusable mission template."""

    name: str
    title: str
    description: str
    objective: str
    tags: list[str]
    default_priority: int = 0
    steps: list[MissionStep] = field(default_factory=list)


class MissionTemplates:
    """Library of reusable mission templates.

    Templates expand into MissionSteps.
    """

    def __init__(self) -> None:
        self._templates: dict[str, MissionTemplate] = {}
        self._logger = logging.getLogger(__name__)
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(MissionTemplate(
            name="research_topic",
            title="Research Topic",
            description="Research a topic using knowledge, memory, and intelligence",
            objective="Research and store findings on a given topic",
            tags=["research"],
            default_priority=1,
            steps=[
                MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Search existing knowledge"),
                MissionStep(order=2, subsystem=Subsystem.MEMORY, title="Recall relevant context"),
                MissionStep(order=3, subsystem=Subsystem.INTELLIGENCE, title="Analyze and synthesize"),
                MissionStep(order=4, subsystem=Subsystem.KNOWLEDGE, title="Store findings"),
            ],
        ))
        self.register(MissionTemplate(
            name="analyze_repository",
            title="Analyze Repository",
            description="Analyze a code repository for quality and structure",
            objective="Run analysis tools and store results",
            tags=["analyze"],
            default_priority=2,
            steps=[
                MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Retrieve repository data"),
                MissionStep(order=2, subsystem=Subsystem.EXECUTION, title="Run analysis commands"),
                MissionStep(order=3, subsystem=Subsystem.INTELLIGENCE, title="Interpret results"),
                MissionStep(order=4, subsystem=Subsystem.KNOWLEDGE, title="Store analysis report"),
            ],
        ))
        self.register(MissionTemplate(
            name="write_article",
            title="Write Article",
            description="Research, draft, and store an article",
            objective="Produce a well-researched article",
            tags=["write"],
            default_priority=1,
            steps=[
                MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Research topic"),
                MissionStep(order=2, subsystem=Subsystem.INTELLIGENCE, title="Draft content"),
                MissionStep(order=3, subsystem=Subsystem.KNOWLEDGE, title="Store draft"),
            ],
        ))
        self.register(MissionTemplate(
            name="review_code",
            title="Review Code",
            description="Review code quality and provide feedback",
            objective="Analyze code and generate review report",
            tags=["review"],
            default_priority=2,
            steps=[
                MissionStep(order=1, subsystem=Subsystem.EXECUTION, title="Fetch code"),
                MissionStep(order=2, subsystem=Subsystem.INTELLIGENCE, title="Review code quality"),
                MissionStep(order=3, subsystem=Subsystem.KNOWLEDGE, title="Store review report"),
            ],
        ))
        self.register(MissionTemplate(
            name="find_opportunities",
            title="Find Opportunities",
            description="Discover and rank freelance opportunities",
            objective="Find the best matching freelance opportunities",
            tags=["opportunities"],
            default_priority=2,
            steps=[
                MissionStep(order=1, subsystem=Subsystem.OPPORTUNITY, title="Discover opportunities"),
                MissionStep(order=2, subsystem=Subsystem.MEMORY, title="Check past matches"),
                MissionStep(order=3, subsystem=Subsystem.INTELLIGENCE, title="Score and rank"),
                MissionStep(order=4, subsystem=Subsystem.KNOWLEDGE, title="Store results"),
            ],
        ))
        self.register(MissionTemplate(
            name="daily_review",
            title="Daily Review",
            description="Daily summary of activity, priorities, and opportunities",
            objective="Produce a daily briefing",
            tags=["daily"],
            default_priority=0,
            steps=[
                MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Collect recent activity"),
                MissionStep(order=2, subsystem=Subsystem.MEMORY, title="Recall priority items"),
                MissionStep(order=3, subsystem=Subsystem.OPPORTUNITY, title="Check new opportunities"),
                MissionStep(order=4, subsystem=Subsystem.INTELLIGENCE, title="Summarize"),
                MissionStep(order=5, subsystem=Subsystem.KNOWLEDGE, title="Store daily summary"),
            ],
        ))
        self.register(MissionTemplate(
            name="build_project",
            title="Build Project",
            description="Gather requirements, design, implement, test, and document",
            objective="Complete a full project build cycle",
            tags=["build"],
            default_priority=3,
            steps=[
                MissionStep(order=1, subsystem=Subsystem.KNOWLEDGE, title="Gather requirements"),
                MissionStep(order=2, subsystem=Subsystem.INTELLIGENCE, title="Design architecture"),
                MissionStep(order=3, subsystem=Subsystem.EXECUTION, title="Implement"),
                MissionStep(order=4, subsystem=Subsystem.EXECUTION, title="Test"),
                MissionStep(order=5, subsystem=Subsystem.KNOWLEDGE, title="Document"),
            ],
        ))

    def register(self, template: MissionTemplate) -> None:
        self._templates[template.name] = template
        self._logger.debug("Registered template '%s'", template.name)

    def get(self, name: str) -> MissionTemplate | None:
        return self._templates.get(name)

    def list_templates(self) -> list[MissionTemplate]:
        return list(self._templates.values())

    def apply(self, name: str, mission: Mission) -> MissionPlan | None:
        """Apply a template to create a MissionPlan from a Mission."""
        template = self._templates.get(name)
        if template is None:
            return None
        steps = [
            MissionStep(
                order=s.order,
                title=s.title,
                description=s.description,
                subsystem=s.subsystem,
                dependencies=list(s.dependencies),
                max_retries=s.max_retries,
                payload=dict(s.payload),
            )
            for s in template.steps
        ]
        return MissionPlan(mission=mission, steps=steps)

    def template_count(self) -> int:
        return len(self._templates)

    def clear(self) -> None:
        self._templates.clear()


# ======================================================================
# MissionContextBridge
# ======================================================================


class MissionContextBridge:
    """Synchronizes mission state into AtlasContext."""

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def sync_to_context(
        self,
        context: AtlasContext,
        mission: Mission,
        current_step: MissionStep | None = None,
        progress: float = 0.0,
    ) -> None:
        """Update AtlasContext with current mission state."""
        try:
            mission_data: dict[str, Any] = {
                "mission_id": mission.mission_id,
                "title": mission.title,
                "status": mission.status.name,
                "priority": mission.priority,
                "progress": progress,
            }
            if current_step is not None:
                mission_data["current_step"] = {
                    "step_id": current_step.step_id,
                    "title": current_step.title,
                    "subsystem": current_step.subsystem.value,
                    "order": current_step.order,
                    "state": current_step.state.name,
                }

            # Publish context update event
            await self._publish_event("context_synced", {
                "mission_id": mission.mission_id,
                "mission_data": mission_data,
            })
        except Exception:
            self._logger.exception("Failed to sync mission context")

    async def _publish_event(self, action: str, payload: dict[str, Any]) -> None:
        try:
            await self._event_bus.publish(Event(
                source="mission_context_bridge",
                category=EventCategory.MISSION,
                priority=EventPriority.NORMAL,
                payload={"action": action, **payload},
            ))
        except Exception:
            self._logger.exception("Failed to publish context bridge event")


# ======================================================================
# MissionEventBridge
# ======================================================================


class MissionEventBridge:
    """Publishes mission life cycle events to the Event Bus.
    """

    EVENT_MISSION_CREATED = "mission_created"
    EVENT_MISSION_STARTED = "mission_started"
    EVENT_MISSION_PAUSED = "mission_paused"
    EVENT_MISSION_COMPLETED = "mission_completed"
    EVENT_MISSION_FAILED = "mission_failed"
    EVENT_MISSION_CANCELLED = "mission_cancelled"
    EVENT_STEP_COMPLETED = "step_completed"

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def publish_mission_created(self, mission: Mission) -> None:
        await self._publish(self.EVENT_MISSION_CREATED, mission, {})

    async def publish_mission_started(self, mission: Mission) -> None:
        await self._publish(self.EVENT_MISSION_STARTED, mission, {})

    async def publish_mission_paused(self, mission: Mission) -> None:
        await self._publish(self.EVENT_MISSION_PAUSED, mission, {})

    async def publish_mission_completed(self, mission: Mission, duration: float = 0.0) -> None:
        await self._publish(self.EVENT_MISSION_COMPLETED, mission, {"duration": duration})

    async def publish_mission_failed(self, mission: Mission, error: str = "") -> None:
        await self._publish(self.EVENT_MISSION_FAILED, mission, {"error": error})

    async def publish_mission_cancelled(self, mission: Mission) -> None:
        await self._publish(self.EVENT_MISSION_CANCELLED, mission, {})

    async def publish_step_completed(
        self, mission_id: str, step: MissionStep
    ) -> None:
        await self._event_bus.publish(Event(
            source="mission_event_bridge",
            category=EventCategory.MISSION,
            priority=EventPriority.NORMAL,
            payload={
                "action": self.EVENT_STEP_COMPLETED,
                "mission_id": mission_id,
                "step_id": step.step_id,
                "step_title": step.title,
                "subsystem": step.subsystem.value,
                "order": step.order,
                "state": step.state.name,
                "result": step.result,
            },
        ))

    async def _publish(self, action: str, mission: Mission, extra: dict[str, Any]) -> None:
        try:
            await self._event_bus.publish(Event(
                source="mission_event_bridge",
                category=EventCategory.MISSION,
                priority=EventPriority.NORMAL,
                payload={
                    "action": action,
                    "mission_id": mission.mission_id,
                    "title": mission.title,
                    "status": mission.status.name,
                    "priority": mission.priority,
                    **extra,
                },
            ))
        except Exception:
            self._logger.exception("Failed to publish mission event: %s", action)


# ======================================================================
# MissionControl — IService
# ======================================================================


class MissionControl(IService):
    """Central orchestration for Atlas.

    Coordinates all subsystems.
    Owns no business logic.
    Delegates all work to appropriate subsystems.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        self._state_machine = MissionStateMachine()
        self._planner = MissionPlanner()
        self._scheduler = MissionScheduler()
        self._executor = MissionExecutor(event_bus)
        self._history = MissionHistory()
        self._metrics = MissionMetrics()
        self._templates = MissionTemplates()
        self._context_bridge = MissionContextBridge(event_bus)
        self._event_bridge = MissionEventBridge(event_bus)

        self._missions: dict[str, Mission] = {}
        self._plans: dict[str, MissionPlan] = {}
        self._running = False
        self._context: AtlasContext | None = None
        self._mission_times: dict[str, float] = {}

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "mission_control"

    async def initialize(self) -> None:
        await super().initialize()
        self._logger.info("Mission Control initializing")

    async def start(self) -> None:
        await super().start()
        self._running = True
        self._logger.info("Mission Control started")

    async def stop(self) -> None:
        await super().stop()
        self._running = False
        self._logger.info("Mission Control stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "missions_created": self._metrics.missions_created,
                "missions_completed": self._metrics.missions_completed,
                "missions_failed": self._metrics.missions_failed,
                "active_missions": self._metrics.active_missions,
                "success_rate": round(self._metrics.success_rate, 1),
                "queued_missions": self._scheduler.queued_count,
                "template_count": self._templates.template_count(),
            },
        )

    # ------------------------------------------------------------------
    # Context integration
    # ------------------------------------------------------------------

    def set_context(self, context: AtlasContext) -> None:
        self._context = context

    # ------------------------------------------------------------------
    # Mission lifecycle
    # ------------------------------------------------------------------

    async def create_mission(
        self,
        title: str = "",
        description: str = "",
        objective: str = "",
        priority: int = 0,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Mission:
        mission = Mission(
            title=title,
            description=description,
            objective=objective,
            priority=priority,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._missions[mission.mission_id] = mission
        self._metrics.missions_created += 1
        self._metrics.active_missions += 1

        await self._event_bridge.publish_mission_created(mission)
        self._logger.info("Mission created: %s (%s)", mission.title, mission.mission_id)
        return mission

    async def get_mission(self, mission_id: str) -> Mission | None:
        return self._missions.get(mission_id)

    async def list_missions(self) -> list[Mission]:
        return list(self._missions.values())

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    async def plan(self, mission_id: str, template: str | None = None) -> MissionPlan | None:
        """Create a plan for the given mission.

        If a template name is provided, apply the template.
        Otherwise, use the rule-based MissionPlanner.
        """
        mission = self._missions.get(mission_id)
        if mission is None:
            return None

        # Transition to PLANNING
        mission = self._transition_mission(mission, MissionStatus.PLANNING)
        self._missions[mission_id] = mission

        if template is not None:
            plan = self._templates.apply(template, mission)
            if plan is None:
                return None
        else:
            plan = self._planner.plan(mission)

        self._plans[mission_id] = plan
        self._logger.info("Mission planned: %s (%d steps)", mission.title, len(plan.steps))
        return plan

    async def get_plan(self, mission_id: str) -> MissionPlan | None:
        return self._plans.get(mission_id)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, mission_id: str) -> Mission | None:
        """Execute a mission plan."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return None
        plan = self._plans.get(mission_id)
        if plan is None:
            return None

        # Transition to RUNNING
        mission = self._transition_mission(mission, MissionStatus.RUNNING)
        self._missions[mission_id] = mission
        self._mission_times[mission_id] = time.time()

        await self._event_bridge.publish_mission_started(mission)

        # Sync context
        if self._context is not None:
            await self._context_bridge.sync_to_context(self._context, mission, progress=0.0)

        # Execute plan
        result_plan = await self._executor.execute_plan(plan)

        # Determine outcome
        all_completed = all(s.state == StepState.COMPLETED for s in result_plan.steps)
        has_failures = any(s.state == StepState.FAILED for s in result_plan.steps)

        duration = time.time() - self._mission_times.get(mission_id, time.time())

        if all_completed:
            mission = self._transition_mission(mission, MissionStatus.COMPLETED)
            self._metrics.missions_completed += 1
            self._metrics.total_duration += duration
            await self._event_bridge.publish_mission_completed(mission, duration)
        elif has_failures:
            mission = self._transition_mission(mission, MissionStatus.FAILED)
            self._metrics.missions_failed += 1
            await self._event_bridge.publish_mission_failed(mission, "Step failures detected")
        else:
            mission = self._transition_mission(mission, MissionStatus.COMPLETED)
            self._metrics.missions_completed += 1
            await self._event_bridge.publish_mission_completed(mission, duration)

        self._metrics.active_missions = max(0, self._metrics.active_missions - 1)
        self._metrics.steps_executed += sum(1 for s in result_plan.steps if s.state == StepState.COMPLETED)
        self._metrics.steps_failed += sum(1 for s in result_plan.steps if s.state == StepState.FAILED)
        self._missions[mission_id] = mission
        self._plans[mission_id] = result_plan

        # History
        self._history.record(HistoryEntry(
            mission_id=mission.mission_id,
            title=mission.title,
            status=mission.status,
            priority=mission.priority,
            duration=duration,
            steps_total=len(result_plan.steps),
            steps_completed=sum(1 for s in result_plan.steps if s.state == StepState.COMPLETED),
            steps_failed=sum(1 for s in result_plan.steps if s.state == StepState.FAILED),
            completed_at=datetime.now(),
        ))

        return mission

    # ------------------------------------------------------------------
    # Lifecycle control
    # ------------------------------------------------------------------

    async def start_mission(self, mission_id: str) -> Mission | None:
        """Start a mission by enqueuing and executing it."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return None

        self._scheduler.enqueue(mission_id, mission.priority)
        return await self.execute(mission_id)

    async def pause_mission(self, mission_id: str) -> Mission | None:
        """Pause a mission."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return None
        mission = self._transition_mission(mission, MissionStatus.PAUSED)
        self._missions[mission_id] = mission
        self._scheduler.pause(mission_id)
        await self._event_bridge.publish_mission_paused(mission)
        self._logger.info("Mission paused: %s", mission.title)
        return mission

    async def resume_mission(self, mission_id: str) -> Mission | None:
        """Resume a paused mission."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return None
        mission = self._transition_mission(mission, MissionStatus.RUNNING)
        self._missions[mission_id] = mission
        self._scheduler.resume(mission_id)
        await self._event_bridge.publish_mission_started(mission)
        self._logger.info("Mission resumed: %s", mission.title)
        return mission

    async def cancel_mission(self, mission_id: str) -> Mission | None:
        """Cancel a mission."""
        mission = self._missions.get(mission_id)
        if mission is None:
            return None
        mission = self._transition_mission(mission, MissionStatus.CANCELLED)
        self._missions[mission_id] = mission
        self._scheduler.cancel(mission_id)
        self._metrics.active_missions = max(0, self._metrics.active_missions - 1)
        self._metrics.missions_cancelled += 1
        await self._event_bridge.publish_mission_cancelled(mission)
        self._logger.info("Mission cancelled: %s", mission.title)
        return mission

    # ------------------------------------------------------------------
    # State machine helper
    # ------------------------------------------------------------------

    def _transition_mission(self, mission: Mission, target: MissionStatus) -> Mission:
        new_status = self._state_machine.transition(mission.status, target)
        return Mission(
            mission_id=mission.mission_id,
            title=mission.title,
            description=mission.description,
            objective=mission.objective,
            priority=mission.priority,
            status=new_status,
            created_at=mission.created_at,
            updated_at=datetime.now(),
            tags=list(mission.tags),
            metadata=dict(mission.metadata),
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    async def history(
        self,
        status: MissionStatus | None = None,
        limit: int = 20,
    ) -> list[HistoryEntry]:
        return self._history.query(status=status, limit=limit)

    @property
    def metrics(self) -> MissionMetrics:
        return self._metrics

    @property
    def scheduler(self) -> MissionScheduler:
        return self._scheduler

    @property
    def planner(self) -> MissionPlanner:
        return self._planner

    @property
    def executor(self) -> MissionExecutor:
        return self._executor

    @property
    def templates(self) -> MissionTemplates:
        return self._templates

    @property
    def state_machine(self) -> MissionStateMachine:
        return self._state_machine

    @property
    def event_bridge(self) -> MissionEventBridge:
        return self._event_bridge

    @property
    def context_bridge(self) -> MissionContextBridge:
        return self._context_bridge
