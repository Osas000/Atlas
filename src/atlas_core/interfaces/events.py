"""Event types, enums, and protocols for the Atlas Event Bus."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    DEFERRED = 4


class EventCategory(Enum):
    SYSTEM = "system"
    WORKFLOW = "workflow"
    BROWSER = "browser"
    OPPORTUNITY = "opportunity"
    APPLICATION = "application"
    PROJECT = "project"
    MEMORY = "memory"
    KNOWLEDGE = "knowledge"
    EXECUTION = "execution"
    INTELLIGENCE = "intelligence"
    CONTEXT = "context"
    OPERATIONS = "operations"
    CLIENT = "client"
    PAYMENT = "payment"
    USER = "user"
    ERROR = "error"
    HEALTH = "health"
    MISSION = "mission"
    NOTIFICATION = "notification"
    AGENT = "agent"
    MULTI_AGENT = "multi_agent"
    PERSISTENCE = "persistence"
    MONITOR = "monitor"
    MONITOR_API = "monitor_api"


class Event(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=datetime.now)
    source: str
    category: EventCategory
    priority: EventPriority = EventPriority.NORMAL
    payload: dict[str, Any] = Field(default_factory=dict)
    related_workflow: str | None = None
    status: str = "pending"
    confidence: float = 1.0

    model_config = {"frozen": True}


@runtime_checkable
class EventHandler(Protocol):
    async def __call__(self, event: Event) -> None: ...
