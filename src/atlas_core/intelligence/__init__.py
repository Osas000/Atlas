"""Intelligence Router — Atlas's AI capability layer.

Atlas requests capabilities. The router chooses how those are fulfilled.
No subsystem outside this module communicates directly with an AI provider.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Enums
# ======================================================================


class Capability(Enum):
    REASONING = "reasoning"
    CODING = "coding"
    PLANNING = "planning"
    TRANSLATION = "translation"
    SUMMARIZATION = "summarization"
    RESEARCH = "research"
    EXTRACTION = "extraction"
    CLASSIFICATION = "classification"


class ProviderType(Enum):
    OPENCODE = "opencode"
    # Future: OPENAI, CLAUDE, GEMINI, OLLAMA


class ProviderStatus(Enum):
    ONLINE = auto()
    DEGRADED = auto()
    OFFLINE = auto()
    UNKNOWN = auto()


# ======================================================================
# Request / Response models
# ======================================================================


class IntelligenceRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    capability: Capability
    prompt: str
    system_prompt: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    temperature: float = 0.7
    max_tokens: int = 4096
    priority: EventPriority = EventPriority.NORMAL
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class IntelligenceResponse(BaseModel):
    request_id: str
    content: str
    provider: str
    capability: Capability
    timing_ms: float = 0.0
    cached: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None

    model_config = {"frozen": True}


# ======================================================================
# Provider interface
# ======================================================================


class Provider(ABC):
    """Interface for AI provider adapters.

    All providers implement this interface so the router can treat
    them interchangeably.
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType: ...

    @abstractmethod
    async def execute(self, request: IntelligenceRequest) -> IntelligenceResponse: ...

    @abstractmethod
    async def check_health(self) -> ProviderStatus: ...

    @property
    @abstractmethod
    def supported_capabilities(self) -> set[Capability]: ...

    @property
    @abstractmethod
    def max_concurrent(self) -> int: ...


# ======================================================================
# OpenCodeAdapter
# ======================================================================


class OpenCodeAdapter(Provider):
    """Adapter for the OpenCode AI provider.

    In v1, this is the only production provider.  The adapter encapsulates
    all interaction with OpenCode behind the Provider interface so future
    providers can be added without changing the router.
    """

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    @property
    def name(self) -> str:
        return "opencode"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENCODE

    @property
    def supported_capabilities(self) -> set[Capability]:
        return {
            Capability.REASONING,
            Capability.CODING,
            Capability.PLANNING,
            Capability.TRANSLATION,
            Capability.SUMMARIZATION,
            Capability.RESEARCH,
            Capability.EXTRACTION,
            Capability.CLASSIFICATION,
        }

    @property
    def max_concurrent(self) -> int:
        return 10

    async def execute(self, request: IntelligenceRequest) -> IntelligenceResponse:
        """Execute a request against OpenCode.

        In this infrastructure layer the adapter simulates a response.
        A real implementation would call the OpenCode API.
        """
        start = time.monotonic()
        try:
            content = await self._call_opencode(request)
            elapsed = (time.monotonic() - start) * 1000
            return IntelligenceResponse(
                request_id=request.request_id,
                content=content,
                provider=self.name,
                capability=request.capability,
                timing_ms=elapsed,
                tokens_in=len(request.prompt.split()),
                tokens_out=len(content.split()),
            )
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            return IntelligenceResponse(
                request_id=request.request_id,
                content="",
                provider=self.name,
                capability=request.capability,
                timing_ms=elapsed,
                error=str(exc),
            )

    async def _call_opencode(self, request: IntelligenceRequest) -> str:
        """Simulated OpenCode call — replace with real API in production."""
        await asyncio.sleep(0.01)
        return f"OpenCode response for {request.capability.value}: {request.prompt[:50]}..."

    async def check_health(self) -> ProviderStatus:
        """Check if the provider is reachable."""
        try:
            await asyncio.sleep(0.001)
            return ProviderStatus.ONLINE
        except Exception:
            return ProviderStatus.OFFLINE


# ======================================================================
# PromptEngine
# ======================================================================


class PromptEngine:
    """Builds prompts with system context for AI requests."""

    def build(
        self,
        capability: Capability,
        prompt: str,
        system_prompt: str = "",
        context: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Build system and user prompt from capability and context.

        Returns (system_prompt, user_prompt).
        """
        parts = [system_prompt] if system_prompt else []
        base = _CAPABILITY_PROMPTS.get(capability, "")
        if base:
            parts.append(base)

        if context:
            ctx_lines = []
            for k, v in context.items():
                ctx_lines.append(f"{k}: {v}")
            if ctx_lines:
                parts.append("Context:\n" + "\n".join(ctx_lines))

        full_system = "\n\n".join(parts) if parts else ""
        return full_system, prompt


_CAPABILITY_PROMPTS: dict[Capability, str] = {
    Capability.REASONING: "You are a reasoning engine. Think step by step.",
    Capability.CODING: "You are a coding assistant. Write clean, well-documented code.",
    Capability.PLANNING: "You are a planning assistant. Break down complex tasks.",
    Capability.TRANSLATION: "You are a translator. Preserve meaning and tone.",
    Capability.SUMMARIZATION: "You are a summarizer. Be concise and accurate.",
    Capability.RESEARCH: "You are a research assistant. Be thorough and cite sources.",
    Capability.EXTRACTION: "You are an extraction engine. Return structured data only.",
    Capability.CLASSIFICATION: "You are a classifier. Return categories with confidence.",
}


# ======================================================================
# ResponseCache
# ======================================================================


class ResponseCache:
    """TTL-based cache for AI responses."""

    def __init__(self, default_ttl_seconds: float = 300.0, max_size: int = 1000) -> None:
        self._cache: dict[str, tuple[float, IntelligenceResponse]] = {}
        self._default_ttl = default_ttl_seconds
        self._max_size = max_size

    def _make_key(self, capability: Capability, prompt: str, temperature: float) -> str:
        return f"{capability.value}:{hash(prompt)}:{temperature}"

    def get(self, capability: Capability, prompt: str, temperature: float = 0.7) -> IntelligenceResponse | None:
        key = self._make_key(capability, prompt, temperature)
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, response = entry
        if time.monotonic() > expires_at:
            del self._cache[key]
            return None
        return response

    def set(
        self,
        capability: Capability,
        prompt: str,
        response: IntelligenceResponse,
        temperature: float = 0.7,
        ttl_seconds: float | None = None,
    ) -> None:
        key = self._make_key(capability, prompt, temperature)
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        self._cache[key] = (time.monotonic() + ttl, response)
        if len(self._cache) > self._max_size:
            self._evict()

    def invalidate(self, capability: Capability | None = None) -> None:
        if capability is None:
            self._cache.clear()
        else:
            prefix = f"{capability.value}:"
            self._cache = {k: v for k, v in self._cache.items() if not k.startswith(prefix)}

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [k for k, (exp, _) in self._cache.items() if now > exp]
        for k in expired:
            del self._cache[k]
        while len(self._cache) > self._max_size:
            self._cache.pop(next(iter(self._cache)))

    @property
    def size(self) -> int:
        return len(self._cache)


# ======================================================================
# RateLimitManager
# ======================================================================


@dataclass
class RateLimit:
    requests_per_minute: int = 60
    concurrent_max: int = 10


class RateLimitManager:
    """Tracks and enforces per-provider rate limits."""

    def __init__(self) -> None:
        self._limits: dict[str, RateLimit] = {}
        self._windows: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=10000)
        )
        self._concurrent: dict[str, int] = defaultdict(int)

    def set_limit(self, provider: str, rpm: int, concurrent: int = 10) -> None:
        self._limits[provider] = RateLimit(rpm, concurrent)

    def get_limit(self, provider: str) -> RateLimit:
        return self._limits.get(provider, RateLimit())

    async def acquire(self, provider: str) -> bool:
        """Try to acquire a rate-limited slot. Returns True if allowed."""
        limit = self.get_limit(provider)
        if self._concurrent[provider] >= limit.concurrent_max:
            return False

        now = time.monotonic()
        window = self._windows[provider]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()

        if len(window) >= limit.requests_per_minute:
            return False

        window.append(now)
        self._concurrent[provider] += 1
        return True

    def release(self, provider: str) -> None:
        self._concurrent[provider] = max(0, self._concurrent[provider] - 1)

    def get_concurrent(self, provider: str) -> int:
        return self._concurrent.get(provider, 0)

    def get_usage(self, provider: str) -> int:
        now = time.monotonic()
        window = self._windows[provider]
        cutoff = now - 60.0
        return sum(1 for t in window if t >= cutoff)


# ======================================================================
# MetricsCollector
# ======================================================================


@dataclass
class ProviderMetrics:
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    cached: int = 0
    total_timing_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


class MetricsCollector:
    """Collects usage and performance metrics for providers and capabilities."""

    def __init__(self) -> None:
        self._provider_metrics: dict[str, ProviderMetrics] = defaultdict(ProviderMetrics)
        self._capability_metrics: dict[str, ProviderMetrics] = defaultdict(ProviderMetrics)

    def record(
        self,
        provider: str,
        capability: Capability,
        timing_ms: float,
        success: bool,
        cached: bool = False,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        pm = self._provider_metrics[provider]
        pm.total_requests += 1
        pm.total_timing_ms += timing_ms
        pm.tokens_in += tokens_in
        pm.tokens_out += tokens_out
        if success:
            pm.successful += 1
        else:
            pm.failed += 1
        if cached:
            pm.cached += 1

        cm = self._capability_metrics[capability.value]
        cm.total_requests += 1
        cm.total_timing_ms += timing_ms
        if success:
            cm.successful += 1
        else:
            cm.failed += 1
        if cached:
            cm.cached += 1

    def provider_stats(self, provider: str) -> ProviderMetrics:
        return self._provider_metrics.get(provider, ProviderMetrics())

    def capability_stats(self, capability: Capability) -> ProviderMetrics:
        return self._capability_metrics.get(capability.value, ProviderMetrics())

    @property
    def all_providers(self) -> dict[str, ProviderMetrics]:
        return dict(self._provider_metrics)

    @property
    def all_capabilities(self) -> dict[str, ProviderMetrics]:
        return dict(self._capability_metrics)

    def avg_timing_ms(self, provider: str) -> float:
        pm = self._provider_metrics.get(provider)
        if pm is None or pm.total_requests == 0:
            return 0.0
        return pm.total_timing_ms / pm.total_requests


# ======================================================================
# ProviderHealthMonitor
# ======================================================================


class ProviderHealthMonitor:
    """Periodically checks provider health and tracks status."""

    def __init__(self, check_interval: float = 30.0) -> None:
        self._providers: dict[str, Provider] = {}
        self._statuses: dict[str, ProviderStatus] = {}
        self._check_interval = check_interval
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._logger = logging.getLogger(__name__)

    def register(self, provider: Provider) -> None:
        self._providers[provider.name] = provider
        self._statuses[provider.name] = ProviderStatus.UNKNOWN

    def status(self, provider: str) -> ProviderStatus:
        return self._statuses.get(provider, ProviderStatus.UNKNOWN)

    async def check_now(self, provider: str) -> ProviderStatus:
        p = self._providers.get(provider)
        if p is None:
            return ProviderStatus.UNKNOWN
        self._statuses[provider] = await p.check_health()
        return self._statuses[provider]

    async def check_all(self) -> dict[str, ProviderStatus]:
        for name, provider in self._providers.items():
            self._statuses[name] = await provider.check_health()
        return dict(self._statuses)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        self._logger.info("Provider health monitor started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._logger.info("Provider health monitor stopped")

    async def _run(self) -> None:
        while self._running:
            try:
                await self.check_all()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                break
            except Exception:
                self._logger.exception("Health monitor error")

    @property
    def all_statuses(self) -> dict[str, ProviderStatus]:
        return dict(self._statuses)


# ======================================================================
# CapabilityRouter
# ======================================================================


class CapabilityRouter:
    """Maps capabilities to the best provider for each."""

    def __init__(self) -> None:
        self._mappings: dict[Capability, list[str]] = defaultdict(list)

    def register(self, provider: Provider) -> None:
        for cap in provider.supported_capabilities:
            self._mappings[cap].append(provider.name)

    def providers_for(self, capability: Capability) -> list[str]:
        return list(self._mappings.get(capability, []))

    def best_provider(self, capability: Capability, health: ProviderHealthMonitor) -> str | None:
        providers = self._mappings.get(capability, [])
        if not providers:
            return None
        for p in providers:
            if health.status(p) == ProviderStatus.ONLINE:
                return p
        return providers[0] if providers else None


# ======================================================================
# ProviderManager
# ======================================================================


class ProviderManager:
    """Registers and selects AI providers."""

    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        self._providers[provider.name] = provider

    def get(self, name: str) -> Provider | None:
        return self._providers.get(name)

    @property
    def all(self) -> dict[str, Provider]:
        return dict(self._providers)

    @property
    def count(self) -> int:
        return len(self._providers)


# ======================================================================
# IntelligenceRouter — IService
# ======================================================================


DEFAULT_RPM = 60


class IntelligenceRouter(IService):
    """Central AI capability router for Atlas.

    All AI requests pass through this router.  No subsystem communicates
    directly with an AI provider.

    Responsibilities:
    - Route capability requests to the best provider
    - Rate-limit and queue requests
    - Cache responses
    - Collect metrics
    - Monitor provider health
    - Publish events on the Event Bus
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        self._provider_manager = ProviderManager()
        self._capability_router = CapabilityRouter()
        self._prompt_engine = PromptEngine()
        self._cache = ResponseCache()
        self._rate_limiter = RateLimitManager()
        self._metrics = MetricsCollector()
        self._health_monitor = ProviderHealthMonitor()

        self._queue: asyncio.Queue[IntelligenceRequest] = asyncio.Queue()
        self._queue_workers: list[asyncio.Task[None]] = []
        self._num_workers = 4
        self._running = False

        self._register_default_providers()

    # ------------------------------------------------------------------
    # Default setup
    # ------------------------------------------------------------------

    def _register_default_providers(self) -> None:
        opencode = OpenCodeAdapter()
        self._provider_manager.register(opencode)
        self._capability_router.register(opencode)
        self._health_monitor.register(opencode)
        self._rate_limiter.set_limit("opencode", DEFAULT_RPM, concurrent=10)

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "intelligence_router"

    async def initialize(self) -> None:
        self._logger.info("Intelligence Router initializing")

    async def start(self) -> None:
        self._running = True
        await self._health_monitor.start()
        self._queue_workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self._num_workers)
        ]
        self._logger.info(
            "Intelligence Router started (%d workers)", self._num_workers
        )

    async def stop(self) -> None:
        self._running = False
        await self._health_monitor.stop()
        for w in self._queue_workers:
            w.cancel()
        await asyncio.gather(*self._queue_workers, return_exceptions=True)
        self._queue_workers.clear()
        self._logger.info("Intelligence Router stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "providers": self._provider_manager.count,
                "cache_size": self._cache.size,
                "queue_size": self._queue.qsize(),
            },
        )

    # ------------------------------------------------------------------
    # Public API — the main entry point for all AI requests
    # ------------------------------------------------------------------

    async def request(
        self,
        capability: Capability,
        prompt: str,
        system_prompt: str = "",
        context: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        use_cache: bool = True,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> IntelligenceResponse:
        """Submit a capability request and wait for the response.

        This is the primary entry point for all AI interactions in Atlas.
        """
        req = IntelligenceRequest(
            capability=capability,
            prompt=prompt,
            system_prompt=system_prompt,
            context=context or {},
            temperature=temperature,
            max_tokens=max_tokens,
            priority=priority,
        )

        # 1. Check cache
        if use_cache:
            cached = self._cache.get(capability, prompt, temperature)
            if cached is not None:
                self._metrics.record(
                    provider=cached.provider,
                    capability=capability,
                    timing_ms=0,
                    success=True,
                    cached=True,
                )
                return cached

        # 2. Find best provider
        provider_name = self._capability_router.best_provider(
            capability, self._health_monitor
        )
        if provider_name is None:
            no_provider = IntelligenceResponse(
                request_id=req.request_id,
                content="",
                provider="",
                capability=capability,
                error=f"No provider available for {capability.value}",
            )
            await self._publish_event(req, no_provider)
            return no_provider

        provider = self._provider_manager.get(provider_name)
        if provider is None:
            err_resp = IntelligenceResponse(
                request_id=req.request_id,
                content="",
                provider="",
                capability=capability,
                error=f"Provider '{provider_name}' not registered",
            )
            await self._publish_event(req, err_resp)
            return err_resp

        # 3. Build prompts
        sys_prompt, user_prompt = self._prompt_engine.build(
            capability, prompt, system_prompt, context
        )
        req_with_prompts = req  # prompts carried in the request model

        # 4. Enforce rate limits
        allowed = await self._rate_limiter.acquire(provider_name)
        if not allowed:
            err_resp = IntelligenceResponse(
                request_id=req.request_id,
                content="",
                provider=provider_name,
                capability=capability,
                error="Rate limit exceeded",
            )
            await self._publish_event(req, err_resp)
            return err_resp

        try:
            # 5. Execute
            response = await provider.execute(req)

            # 6. Update metrics
            self._metrics.record(
                provider=provider_name,
                capability=capability,
                timing_ms=response.timing_ms,
                success=response.error is None,
                tokens_in=response.tokens_in,
                tokens_out=response.tokens_out,
            )

            # 7. Cache if successful
            if response.error is None and use_cache:
                self._cache.set(capability, prompt, response, temperature)

            # 8. Event
            await self._publish_event(req, response)

            return response
        finally:
            self._rate_limiter.release(provider_name)

    async def request_async(
        self,
        capability: Capability,
        prompt: str,
        system_prompt: str = "",
        context: dict[str, Any] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        use_cache: bool = True,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> None:
        """Submit a request and return immediately (processed by queue)."""
        req = IntelligenceRequest(
            capability=capability,
            prompt=prompt,
            system_prompt=system_prompt,
            context=context or {},
            temperature=temperature,
            max_tokens=max_tokens,
            priority=priority,
        )
        await self._queue.put(req)

    # ------------------------------------------------------------------
    # Queue worker
    # ------------------------------------------------------------------

    async def _worker(self, worker_id: int) -> None:
        self._logger.debug("Worker %d started", worker_id)
        while self._running:
            try:
                req = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self.request(
                    capability=req.capability,
                    prompt=req.prompt,
                    system_prompt=req.system_prompt,
                    context=dict(req.context),
                    temperature=req.temperature,
                    max_tokens=req.max_tokens,
                    use_cache=True,
                    priority=req.priority,
                )
                self._queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                self._logger.exception("Worker %d error", worker_id)
        self._logger.debug("Worker %d stopped", worker_id)

    # ------------------------------------------------------------------
    # Sub-component accessors
    # ------------------------------------------------------------------

    @property
    def provider_manager(self) -> ProviderManager:
        return self._provider_manager

    @property
    def capability_router(self) -> CapabilityRouter:
        return self._capability_router

    @property
    def prompt_engine(self) -> PromptEngine:
        return self._prompt_engine

    @property
    def cache(self) -> ResponseCache:
        return self._cache

    @property
    def rate_limiter(self) -> RateLimitManager:
        return self._rate_limiter

    @property
    def metrics(self) -> MetricsCollector:
        return self._metrics

    @property
    def health_monitor(self) -> ProviderHealthMonitor:
        return self._health_monitor

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def _publish_event(self, request: IntelligenceRequest, response: IntelligenceResponse) -> None:
        try:
            await self._event_bus.publish(Event(
                source="intelligence_router",
                category=EventCategory.WORKFLOW,
                priority=request.priority,
                payload={
                    "action": "request_completed",
                    "request_id": request.request_id,
                    "capability": request.capability.value,
                    "provider": response.provider,
                    "error": response.error,
                    "timing_ms": response.timing_ms,
                    "cached": response.cached,
                },
            ))
        except Exception:
            self._logger.exception("Failed to publish intelligence event")
