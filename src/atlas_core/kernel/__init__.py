"""AtlasKernel — the permanent runtime foundation of Atlas.

The Kernel is responsible for:
- Booting Atlas
- Loading configuration
- Loading environment variables
- Initialising logging
- Initialising dependency injection (service registry)
- Creating the Event Bus
- Creating the Operations Core
- Loading plugins
- Registering services
- Starting modules
- Monitoring health
- Graceful shutdown

It never performs business logic.  Its only responsibility is lifecycle
management.
"""

import logging
from pathlib import Path
from typing import Optional

from atlas_core import __app_name__, __version__
from atlas_core.config import AtlasConfig, ConfigurationManager
from atlas_core.events import EventBus
from atlas_core.interfaces import KernelState
from atlas_core.lifecycle import LifecycleManager
from atlas_core.logging import setup_logging
from atlas_core.memory import MemoryManager
from atlas_core.monitoring import HealthMonitor, HealthSummary
from atlas_core.operations import OperationsCore
from atlas_core.mission import MissionControl
from atlas_core.notification import NotificationService
from atlas_core.agent import AgentRuntime
from atlas_core.multi_agent import MultiAgentRuntime
from atlas_core.monitor import SystemMonitor
from atlas_core.monitor_api import MonitoringAPI
from atlas_core.persistence import PersistenceManager
from atlas_core.opportunity import OpportunityEngine
from atlas_core.connectors import ConnectorManager
from atlas_core.plugins import ModuleLoader, PluginManager
from atlas_core.registry import ServiceRegistry
from atlas_core.workflow import WorkflowEngine


class AtlasKernel:
    def __init__(self, config_dir: str | Path = "config") -> None:
        self._config_dir = Path(config_dir)
        self._config: Optional[AtlasConfig] = None
        self._config_manager: Optional[ConfigurationManager] = None
        self._logger: Optional[logging.Logger] = None
        self._registry: Optional[ServiceRegistry] = None
        self._module_loader: Optional[ModuleLoader] = None
        self._event_bus: Optional[EventBus] = None
        self._operations_core: Optional[OperationsCore] = None
        self._memory_manager: Optional[MemoryManager] = None
        self._opportunity_engine: Optional[OpportunityEngine] = None
        self._mission_control: Optional[MissionControl] = None
        self._notification_service: Optional[NotificationService] = None
        self._agent_runtime: Optional[AgentRuntime] = None
        self._multi_agent_runtime: Optional[MultiAgentRuntime] = None
        self._persistence_manager: Optional[PersistenceManager] = None
        self._system_monitor: Optional[SystemMonitor] = None
        self._monitoring_api: Optional[MonitoringAPI] = None
        self._plugin_manager: Optional[PluginManager] = None
        self._connector_manager: Optional[ConnectorManager] = None
        self._workflow_engine: Optional[WorkflowEngine] = None
        self._lifecycle: Optional[LifecycleManager] = None
        self._health_monitor: Optional[HealthMonitor] = None
        self._state = KernelState.CREATED

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> KernelState:
        return self._state

    @property
    def config(self) -> AtlasConfig:
        if self._config is None:
            raise RuntimeError("Kernel has not been initialized")
        return self._config

    @property
    def registry(self) -> ServiceRegistry:
        if self._registry is None:
            raise RuntimeError("Kernel has not been initialized")
        return self._registry

    @property
    def health_monitor(self) -> HealthMonitor:
        if self._health_monitor is None:
            raise RuntimeError("Kernel has not been initialized")
        return self._health_monitor

    @property
    def event_bus(self) -> EventBus:
        if self._event_bus is None:
            raise RuntimeError("Kernel has not been initialized")
        return self._event_bus

    @property
    def operations_core(self) -> OperationsCore:
        if self._operations_core is None:
            raise RuntimeError("Operations Core has not been created")
        return self._operations_core

    @property
    def memory_manager(self) -> MemoryManager:
        if self._memory_manager is None:
            raise RuntimeError("Memory Manager has not been created")
        return self._memory_manager

    @property
    def memory_engine(self) -> MemoryManager:
        """Deprecated: use memory_manager instead."""
        return self.memory_manager

    @property
    def opportunity_engine(self) -> OpportunityEngine:
        if self._opportunity_engine is None:
            raise RuntimeError("Opportunity Engine has not been created")
        return self._opportunity_engine

    @property
    def mission_control(self) -> MissionControl:
        if self._mission_control is None:
            raise RuntimeError("Mission Control has not been created")
        return self._mission_control

    @property
    def notification_service(self) -> NotificationService:
        if self._notification_service is None:
            raise RuntimeError("Notification Service has not been created")
        return self._notification_service

    @property
    def agent_runtime(self) -> AgentRuntime:
        if self._agent_runtime is None:
            raise RuntimeError("Agent Runtime has not been created")
        return self._agent_runtime

    @property
    def multi_agent_runtime(self) -> MultiAgentRuntime:
        if self._multi_agent_runtime is None:
            raise RuntimeError("Multi-Agent Runtime has not been created")
        return self._multi_agent_runtime

    @property
    def persistence_manager(self) -> PersistenceManager:
        if self._persistence_manager is None:
            raise RuntimeError("Persistence Manager has not been created")
        return self._persistence_manager

    @property
    def system_monitor(self) -> SystemMonitor:
        if self._system_monitor is None:
            raise RuntimeError("System Monitor has not been created")
        return self._system_monitor

    @property
    def monitoring_api(self) -> MonitoringAPI:
        if self._monitoring_api is None:
            raise RuntimeError("Monitoring API has not been created")
        return self._monitoring_api

    @property
    def plugin_manager(self) -> PluginManager:
        if self._plugin_manager is None:
            raise RuntimeError("Plugin Manager has not been created")
        return self._plugin_manager

    @property
    def connector_manager(self) -> ConnectorManager:
        if self._connector_manager is None:
            raise RuntimeError("Connector Manager has not been created")
        return self._connector_manager

    @property
    def workflow_engine(self) -> WorkflowEngine:
        if self._workflow_engine is None:
            raise RuntimeError("Workflow Engine has not been created")
        return self._workflow_engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Phase 1 — load configuration, set up logging and infrastructure."""
        if self._state != KernelState.CREATED:
            raise RuntimeError("Kernel can only be initialized once")

        self._state = KernelState.INITIALIZED

        # 1. Configuration
        self._config_manager = ConfigurationManager(self._config_dir)
        self._config = self._config_manager.initialize()

        # 2. Logging
        self._logger = setup_logging(
            log_dir=Path(self._config.log_dir),
            level=self._config.log_level,
            app_name=self._config.app_name,
        )
        self._logger.info(
            "%s v%s initializing …", __app_name__, __version__
        )

        # 3. Infrastructure
        self._registry = ServiceRegistry()
        self._module_loader = ModuleLoader()
        self._event_bus = EventBus()
        self._lifecycle = LifecycleManager(self._registry)
        self._health_monitor = HealthMonitor(self._registry)

        self._logger.info("Kernel initialized successfully")

    def boot(self) -> None:
        """Phase 2 — discover plugins, register services, resolve dependencies.

        Registers the Operations Core (which depends on the Event Bus) and
        any application-level services.  Once booted the dependency graph is
        frozen.
        """
        if self._state != KernelState.INITIALIZED:
            raise RuntimeError("Kernel must be initialized before booting")

        self._memory_manager = MemoryManager(event_bus=self._event_bus)
        self._operations_core = OperationsCore(event_bus=self._event_bus)
        self._opportunity_engine = OpportunityEngine(event_bus=self._event_bus)
        self._mission_control = MissionControl(event_bus=self._event_bus)
        self._notification_service = NotificationService(event_bus=self._event_bus)
        self._agent_runtime = AgentRuntime(event_bus=self._event_bus)
        self._multi_agent_runtime = MultiAgentRuntime(event_bus=self._event_bus)
        self._persistence_manager = PersistenceManager(event_bus=self._event_bus)
        self._system_monitor = SystemMonitor(event_bus=self._event_bus)

        self._registry.register(self._memory_manager)
        self._registry.register(self._operations_core)
        self._registry.register(self._opportunity_engine)
        self._registry.register(self._mission_control)
        self._registry.register(self._notification_service)
        self._registry.register(self._agent_runtime)
        self._registry.register(self._multi_agent_runtime)
        self._registry.register(self._persistence_manager)
        self._registry.register(self._system_monitor)

        self._system_monitor.register_service("memory_manager", self._memory_manager)
        self._system_monitor.register_service("operations_core", self._operations_core)
        self._system_monitor.register_service("opportunity_engine", self._opportunity_engine)
        self._system_monitor.register_service("mission_control", self._mission_control)
        self._system_monitor.register_service("notification_service", self._notification_service)
        self._system_monitor.register_service("agent_runtime", self._agent_runtime)
        self._system_monitor.register_service("multi_agent_runtime", self._multi_agent_runtime)
        self._system_monitor.register_service("persistence_manager", self._persistence_manager)
        self._system_monitor.register_service("system_monitor", self._system_monitor)

        self._monitoring_api = MonitoringAPI(
            event_bus=self._event_bus,
            persistence_manager=self._persistence_manager,
            system_monitor=self._system_monitor,
        )
        self._registry.register(self._monitoring_api)

        self._plugin_manager = PluginManager(
            event_bus=self._event_bus,
            registry=self._registry,
        )
        self._registry.register(self._plugin_manager)

        self._connector_manager = ConnectorManager(
            event_bus=self._event_bus,
        )
        self._registry.register(self._connector_manager)

        self._workflow_engine = WorkflowEngine(
            event_bus=self._event_bus,
            connector_manager=self._connector_manager,
            mission_control=self._mission_control,
            notification_service=self._notification_service,
        )
        self._registry.register(self._workflow_engine)

        self._state = KernelState.BOOTED
        self._logger.info(
            "Kernel booted — %d service(s) registered", self._registry.count
        )

    async def start(self) -> None:
        """Phase 3 — initialize and start all registered services."""
        if self._state != KernelState.BOOTED:
            raise RuntimeError("Kernel must be booted before starting")
        self._state = KernelState.STARTING

        self._logger.info("Starting %d service(s) …", self._registry.count)
        await self._lifecycle.initialize_all()
        await self._lifecycle.start_all()

        summary = await self._health_monitor.check_all()
        self._logger.info(
            "Health check — status=%s  (%d/%d healthy)",
            summary.status,
            summary.healthy_services,
            summary.total_services,
        )

        self._state = KernelState.RUNNING
        self._logger.info("Kernel is running")

    async def stop(self) -> None:
        """Graceful shutdown — stop services in reverse dependency order."""
        self._logger.info("Stopping kernel …")
        self._state = KernelState.STOPPING

        await self._lifecycle.stop_all()

        self._state = KernelState.STOPPED
        self._logger.info("Kernel stopped")
        self._close_log_handlers()

    @staticmethod
    def _close_log_handlers() -> None:
        root = logging.getLogger()
        for handler in list(root.handlers):
            handler.close()
            root.removeHandler(handler)

    async def restart(self) -> None:
        """Restart the kernel (stop then boot + start)."""
        await self.stop()
        self._state = KernelState.BOOTED
        await self.start()

    async def health_check(self) -> HealthSummary:
        """Run an immediate health check across all registered services."""
        return await self._health_monitor.check_all()
