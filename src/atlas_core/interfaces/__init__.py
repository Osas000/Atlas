"""Abstract interfaces and shared types for the Atlas service architecture."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ServiceState(Enum):
    CREATED = auto()
    INITIALIZED = auto()
    STARTING = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPING = auto()
    STOPPED = auto()
    DISPOSED = auto()
    FAILED = auto()


class KernelState(Enum):
    CREATED = auto()
    INITIALIZED = auto()
    BOOTED = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()
    FAILED = auto()


@dataclass
class ServiceHealth:
    healthy: bool
    state: ServiceState
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class IService(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def dependencies(self) -> list[str]:
        return []

    async def initialize(self) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(healthy=True, state=ServiceState.RUNNING)


class IPlugin(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    @property
    def dependencies(self) -> list[str]:
        return []

    async def on_load(self) -> None: ...

    async def on_unload(self) -> None: ...
