"""Lifecycle manager — orchestrates service init, start, and stop."""

import logging
from typing import Optional

from atlas_core.interfaces import ServiceState
from atlas_core.registry import ServiceRegistry


class LifecycleManager:
    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry
        self._states: dict[str, ServiceState] = {}
        self._logger = logging.getLogger(__name__)

    def get_state(self, name: str) -> Optional[ServiceState]:
        return self._states.get(name)

    @property
    def states(self) -> dict[str, ServiceState]:
        return dict(self._states)

    async def initialize_all(self) -> None:
        order = self._registry.dependency_order()
        for name in order:
            service = self._registry.resolve(name)
            if service is None:
                continue
            try:
                await service.initialize()
                self._states[name] = ServiceState.INITIALIZED
                self._logger.info("Initialised service: %s", name)
            except Exception:
                self._states[name] = ServiceState.FAILED
                self._logger.exception("Failed to initialize service '%s'", name)

    async def start_all(self) -> None:
        order = self._registry.dependency_order()
        for name in order:
            service = self._registry.resolve(name)
            if service is None:
                continue
            if self._states.get(name) == ServiceState.FAILED:
                self._logger.warning("Skipping failed service: %s", name)
                continue
            try:
                self._states[name] = ServiceState.STARTING
                await service.start()
                self._states[name] = ServiceState.RUNNING
                self._logger.info("Started service: %s", name)
            except Exception:
                self._states[name] = ServiceState.FAILED
                self._logger.exception("Failed to start service '%s'", name)

    async def stop_all(self) -> None:
        order = list(reversed(self._registry.dependency_order()))
        for name in order:
            service = self._registry.resolve(name)
            if service is None:
                continue
            current = self._states.get(name)
            if current in (ServiceState.FAILED, ServiceState.CREATED, ServiceState.STOPPED):
                continue
            try:
                self._states[name] = ServiceState.STOPPING
                await service.stop()
                self._states[name] = ServiceState.STOPPED
                self._logger.info("Stopped service: %s", name)
            except Exception:
                self._logger.exception("Error while stopping service '%s'", name)
