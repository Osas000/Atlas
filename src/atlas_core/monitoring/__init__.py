"""Health monitoring — checks service status and produces system health reports."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.registry import ServiceRegistry


@dataclass
class HealthSummary:
    status: str  # "healthy" | "degraded" | "unhealthy"
    total_services: int
    healthy_services: int
    failed_services: int
    checks: dict[str, ServiceHealth] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class HealthMonitor:
    def __init__(self, registry: ServiceRegistry) -> None:
        self._registry = registry
        self._last_summary: Optional[HealthSummary] = None
        self._logger = logging.getLogger(__name__)

    async def check_all(self) -> HealthSummary:
        checks: dict[str, ServiceHealth] = {}
        healthy = 0
        failed = 0

        for name, definition in self._registry.services.items():
            try:
                health = await definition.service.health_check()
                checks[name] = health
            except Exception as exc:
                checks[name] = ServiceHealth(
                    healthy=False,
                    state=ServiceState.FAILED,
                    message=str(exc),
                )
                self._logger.exception("Health check failed for service '%s'", name)

            if checks[name].healthy:
                healthy += 1
            else:
                failed += 1

        total = len(self._registry.services)
        if failed == 0:
            status = "healthy"
        elif healthy > 0:
            status = "degraded"
        else:
            status = "unhealthy"

        self._last_summary = HealthSummary(
            status=status,
            total_services=total,
            healthy_services=healthy,
            failed_services=failed,
            checks=checks,
        )
        return self._last_summary

    @property
    def last_summary(self) -> Optional[HealthSummary]:
        return self._last_summary
