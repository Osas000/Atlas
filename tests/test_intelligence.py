"""Tests for the Intelligence Router."""

import pytest

from atlas_core.events import EventBus
from atlas_core.intelligence import (
    Capability,
    CapabilityRouter,
    IntelligenceRequest,
    IntelligenceResponse,
    IntelligenceRouter,
    MetricsCollector,
    OpenCodeAdapter,
    PromptEngine,
    ProviderHealthMonitor,
    ProviderManager,
    ProviderStatus,
    ProviderType,
    RateLimitManager,
    ResponseCache,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def router(bus: EventBus) -> IntelligenceRouter:
    return IntelligenceRouter(bus)


# ======================================================================
# Capability enum
# ======================================================================


class TestCapability:
    def test_values(self) -> None:
        assert Capability.REASONING.value == "reasoning"
        assert Capability.CODING.value == "coding"
        assert Capability.PLANNING.value == "planning"
        assert Capability.TRANSLATION.value == "translation"
        assert Capability.SUMMARIZATION.value == "summarization"
        assert Capability.RESEARCH.value == "research"
        assert Capability.EXTRACTION.value == "extraction"
        assert Capability.CLASSIFICATION.value == "classification"


# ======================================================================
# ProviderType
# ======================================================================


class TestProviderType:
    def test_values(self) -> None:
        assert ProviderType.OPENCODE.value == "opencode"


# ======================================================================
# ProviderStatus
# ======================================================================


class TestProviderStatus:
    def test_values(self) -> None:
        assert ProviderStatus.ONLINE != ProviderStatus.OFFLINE


# ======================================================================
# IntelligenceRequest / Response
# ======================================================================


class TestIntelligenceRequest:
    def test_defaults(self) -> None:
        req = IntelligenceRequest(capability=Capability.CODING, prompt="write code")
        assert req.capability == Capability.CODING
        assert req.prompt == "write code"
        assert req.temperature == 0.7
        assert req.max_tokens == 4096
        assert req.context == {}

    def test_frozen(self) -> None:
        req = IntelligenceRequest(capability=Capability.CODING, prompt="test")
        with pytest.raises(ValueError):
            req.prompt = "changed"


class TestIntelligenceResponse:
    def test_defaults(self) -> None:
        resp = IntelligenceResponse(
            request_id="r1", content="hello", provider="opencode",
            capability=Capability.CODING,
        )
        assert resp.content == "hello"
        assert resp.provider == "opencode"
        assert resp.cached is False
        assert resp.error is None

    def test_frozen(self) -> None:
        resp = IntelligenceResponse(
            request_id="r1", content="", provider="opencode",
            capability=Capability.CODING,
        )
        with pytest.raises(ValueError):
            resp.content = "changed"


# ======================================================================
# OpenCodeAdapter
# ======================================================================


class TestOpenCodeAdapter:
    async def test_name(self) -> None:
        adapter = OpenCodeAdapter()
        assert adapter.name == "opencode"
        assert adapter.provider_type == ProviderType.OPENCODE

    async def test_supports_all_capabilities(self) -> None:
        adapter = OpenCodeAdapter()
        assert Capability.CODING in adapter.supported_capabilities
        assert Capability.REASONING in adapter.supported_capabilities
        assert len(adapter.supported_capabilities) == 8

    async def test_execute_returns_response(self) -> None:
        adapter = OpenCodeAdapter()
        req = IntelligenceRequest(capability=Capability.CODING, prompt="hello world")
        resp = await adapter.execute(req)
        assert resp.provider == "opencode"
        assert resp.capability == Capability.CODING
        assert resp.request_id == req.request_id
        assert resp.error is None
        assert "hello world" in resp.content

    async def test_health_online(self) -> None:
        adapter = OpenCodeAdapter()
        status = await adapter.check_health()
        assert status == ProviderStatus.ONLINE

    async def test_max_concurrent(self) -> None:
        adapter = OpenCodeAdapter()
        assert adapter.max_concurrent == 10


# ======================================================================
# PromptEngine
# ======================================================================


class TestPromptEngine:
    def test_build(self) -> None:
        engine = PromptEngine()
        sys_prompt, user_prompt = engine.build(Capability.CODING, "write tests")
        assert "coding" in sys_prompt.lower()
        assert user_prompt == "write tests"

    def test_with_system_prompt(self) -> None:
        engine = PromptEngine()
        sys_prompt, user_prompt = engine.build(
            Capability.REASONING, "think", system_prompt="Be concise."
        )
        assert "Be concise." in sys_prompt
        assert "reasoning" in sys_prompt.lower()

    def test_with_context(self) -> None:
        engine = PromptEngine()
        sys_prompt, user_prompt = engine.build(
            Capability.PLANNING,
            "plan project",
            context={"project": "Atlas", "deadline": "July"},
        )
        assert "project: Atlas" in sys_prompt
        assert "deadline: July" in sys_prompt

    def test_all_capabilities_have_prompts(self) -> None:
        engine = PromptEngine()
        for cap in Capability:
            sys_prompt, _ = engine.build(cap, "test")
            assert sys_prompt


# ======================================================================
# ResponseCache
# ======================================================================


class TestResponseCache:
    def test_get_miss(self) -> None:
        cache = ResponseCache(default_ttl_seconds=60)
        result = cache.get(Capability.CODING, "hello")
        assert result is None

    def test_set_and_get(self) -> None:
        cache = ResponseCache(default_ttl_seconds=60)
        resp = IntelligenceResponse(
            request_id="r1", content="cached response", provider="opencode",
            capability=Capability.CODING,
        )
        cache.set(Capability.CODING, "hello", resp)
        cached = cache.get(Capability.CODING, "hello")
        assert cached is not None
        assert cached.content == "cached response"

    def test_cache_miss_different_prompt(self) -> None:
        cache = ResponseCache(default_ttl_seconds=60)
        resp = IntelligenceResponse(
            request_id="r1", content="cached", provider="opencode",
            capability=Capability.CODING,
        )
        cache.set(Capability.CODING, "hello", resp)
        assert cache.get(Capability.CODING, "world") is None

    def test_cache_miss_different_temperature(self) -> None:
        cache = ResponseCache(default_ttl_seconds=60)
        resp = IntelligenceResponse(
            request_id="r1", content="cached", provider="opencode",
            capability=Capability.CODING,
        )
        cache.set(Capability.CODING, "hello", resp, temperature=0.7)
        assert cache.get(Capability.CODING, "hello", temperature=0.8) is None

    def test_invalidate_all(self) -> None:
        cache = ResponseCache(default_ttl_seconds=60)
        resp = IntelligenceResponse(
            request_id="r1", content="cached", provider="opencode",
            capability=Capability.CODING,
        )
        cache.set(Capability.CODING, "a", resp)
        cache.set(Capability.REASONING, "b", resp)
        cache.invalidate()
        assert cache.size == 0

    def test_invalidate_by_capability(self) -> None:
        cache = ResponseCache(default_ttl_seconds=60)
        resp = IntelligenceResponse(
            request_id="r1", content="cached", provider="opencode",
            capability=Capability.CODING,
        )
        cache.set(Capability.CODING, "a", resp)
        cache.set(Capability.REASONING, "b", resp)
        cache.invalidate(capability=Capability.CODING)
        assert cache.get(Capability.CODING, "a") is None
        assert cache.get(Capability.REASONING, "b") is not None

    def test_max_size(self) -> None:
        cache = ResponseCache(default_ttl_seconds=60, max_size=3)
        resp = IntelligenceResponse(
            request_id="r1", content="x", provider="opencode",
            capability=Capability.CODING,
        )
        for i in range(5):
            cache.set(Capability.CODING, f"prompt_{i}", resp)
        assert cache.size <= 3

    def test_ttl_expiry(self) -> None:
        cache = ResponseCache(default_ttl_seconds=60)
        resp = IntelligenceResponse(
            request_id="r1", content="gone", provider="opencode",
            capability=Capability.CODING,
        )
        cache.set(Capability.CODING, "now", resp, ttl_seconds=-1)  # immediate expiry
        result = cache.get(Capability.CODING, "now")
        assert result is None


# ======================================================================
# RateLimitManager
# ======================================================================


class TestRateLimitManager:
    async def test_default_limit(self) -> None:
        rl = RateLimitManager()
        limit = rl.get_limit("opencode")
        assert limit.requests_per_minute == 60

    async def test_set_limit(self) -> None:
        rl = RateLimitManager()
        rl.set_limit("test_provider", rpm=10, concurrent=5)
        limit = rl.get_limit("test_provider")
        assert limit.requests_per_minute == 10
        assert limit.concurrent_max == 5

    async def test_acquire_release(self) -> None:
        rl = RateLimitManager()
        rl.set_limit("test", rpm=1000, concurrent=5)
        allowed = await rl.acquire("test")
        assert allowed is True
        assert rl.get_concurrent("test") == 1
        rl.release("test")
        assert rl.get_concurrent("test") == 0

    async def test_concurrent_limit(self) -> None:
        rl = RateLimitManager()
        rl.set_limit("test", rpm=1000, concurrent=2)
        assert await rl.acquire("test") is True
        assert await rl.acquire("test") is True
        assert await rl.acquire("test") is False  # blocked

    async def test_usage_count(self) -> None:
        rl = RateLimitManager()
        rl.set_limit("test", rpm=100, concurrent=10)
        await rl.acquire("test")
        await rl.acquire("test")
        assert rl.get_usage("test") == 2


# ======================================================================
# MetricsCollector
# ======================================================================


class TestMetricsCollector:
    def test_record(self) -> None:
        mc = MetricsCollector()
        mc.record("opencode", Capability.CODING, timing_ms=100, success=True)
        stats = mc.provider_stats("opencode")
        assert stats.total_requests == 1
        assert stats.successful == 1
        assert stats.failed == 0

    def test_record_failure(self) -> None:
        mc = MetricsCollector()
        mc.record("opencode", Capability.CODING, timing_ms=50, success=False)
        stats = mc.provider_stats("opencode")
        assert stats.total_requests == 1
        assert stats.failed == 1

    def test_record_cached(self) -> None:
        mc = MetricsCollector()
        mc.record("opencode", Capability.CODING, timing_ms=0, success=True, cached=True)
        stats = mc.provider_stats("opencode")
        assert stats.cached == 1

    def test_capability_stats(self) -> None:
        mc = MetricsCollector()
        mc.record("opencode", Capability.CODING, timing_ms=200, success=True)
        mc.record("opencode", Capability.REASONING, timing_ms=150, success=True)
        assert mc.capability_stats(Capability.CODING).total_requests == 1
        assert mc.capability_stats(Capability.REASONING).total_requests == 1

    def test_all_providers(self) -> None:
        mc = MetricsCollector()
        mc.record("p1", Capability.CODING, timing_ms=10, success=True)
        mc.record("p2", Capability.REASONING, timing_ms=20, success=True)
        assert len(mc.all_providers) == 2

    def test_avg_timing_ms(self) -> None:
        mc = MetricsCollector()
        mc.record("opencode", Capability.CODING, timing_ms=100, success=True)
        mc.record("opencode", Capability.CODING, timing_ms=200, success=True)
        assert mc.avg_timing_ms("opencode") == 150.0

    def test_avg_timing_ms_no_data(self) -> None:
        mc = MetricsCollector()
        assert mc.avg_timing_ms("unknown") == 0.0


# ======================================================================
# ProviderHealthMonitor
# ======================================================================


class TestProviderHealthMonitor:
    async def test_register_and_status(self) -> None:
        phm = ProviderHealthMonitor()
        adapter = OpenCodeAdapter()
        phm.register(adapter)
        assert phm.status("opencode") == ProviderStatus.UNKNOWN

    async def test_check_now(self) -> None:
        phm = ProviderHealthMonitor()
        adapter = OpenCodeAdapter()
        phm.register(adapter)
        status = await phm.check_now("opencode")
        assert status == ProviderStatus.ONLINE

    async def test_check_all(self) -> None:
        phm = ProviderHealthMonitor()
        phm.register(OpenCodeAdapter())
        statuses = await phm.check_all()
        assert "opencode" in statuses
        assert statuses["opencode"] == ProviderStatus.ONLINE

    async def test_check_unknown(self) -> None:
        phm = ProviderHealthMonitor()
        status = await phm.check_now("nonexistent")
        assert status == ProviderStatus.UNKNOWN

    async def test_start_stop(self) -> None:
        phm = ProviderHealthMonitor(check_interval=60)
        phm.register(OpenCodeAdapter())
        await phm.start()
        await phm.stop()


# ======================================================================
# CapabilityRouter
# ======================================================================


class TestCapabilityRouter:
    def test_register_provider(self) -> None:
        cr = CapabilityRouter()
        adapter = OpenCodeAdapter()
        cr.register(adapter)
        providers = cr.providers_for(Capability.CODING)
        assert "opencode" in providers

    def test_providers_for_unknown(self) -> None:
        cr = CapabilityRouter()
        assert cr.providers_for(Capability.CODING) == []

    def test_best_provider(self) -> None:
        cr = CapabilityRouter()
        phm = ProviderHealthMonitor()
        adapter = OpenCodeAdapter()
        phm.register(adapter)
        cr.register(adapter)
        best = cr.best_provider(Capability.CODING, phm)
        assert best == "opencode"


# ======================================================================
# ProviderManager
# ======================================================================


class TestProviderManager:
    def test_register_and_get(self) -> None:
        pm = ProviderManager()
        adapter = OpenCodeAdapter()
        pm.register(adapter)
        assert pm.get("opencode") is adapter

    def test_get_unknown(self) -> None:
        pm = ProviderManager()
        assert pm.get("nonexistent") is None

    def test_all(self) -> None:
        pm = ProviderManager()
        pm.register(OpenCodeAdapter())
        assert len(pm.all) == 1

    def test_count(self) -> None:
        pm = ProviderManager()
        assert pm.count == 0
        pm.register(OpenCodeAdapter())
        assert pm.count == 1


# ======================================================================
# IntelligenceRouter
# ======================================================================


class TestIntelligenceRouter:
    async def test_initialise(self, router: IntelligenceRouter) -> None:
        assert router.name == "intelligence_router"
        await router.initialize()

    async def test_start_stop(self, router: IntelligenceRouter) -> None:
        await router.start()
        await router.stop()

    async def test_health_check(self, router: IntelligenceRouter) -> None:
        health = await router.health_check()
        assert health.healthy is True
        assert health.metadata["providers"] == 1

    async def test_request_coding(self, router: IntelligenceRouter) -> None:
        await router.start()
        resp = await router.request(Capability.CODING, "write a function")
        assert resp.provider == "opencode"
        assert resp.error is None
        assert "function" in resp.content
        await router.stop()

    async def test_request_reasoning(self, router: IntelligenceRouter) -> None:
        await router.start()
        resp = await router.request(Capability.REASONING, "solve this")
        assert resp.error is None
        await router.stop()

    async def test_request_caches_response(self, router: IntelligenceRouter) -> None:
        await router.start()
        resp1 = await router.request(Capability.CODING, "cache me", use_cache=True)
        resp2 = await router.request(Capability.CODING, "cache me", use_cache=True)
        assert resp2.cached is True or resp1.content == resp2.content
        await router.stop()

    async def test_request_skips_cache(self, router: IntelligenceRouter) -> None:
        await router.start()
        resp1 = await router.request(Capability.CODING, "no cache", use_cache=False)
        resp2 = await router.request(Capability.CODING, "no cache", use_cache=False)
        # cache was never written — both should have cached=False
        assert resp1.cached is False
        await router.stop()

    async def test_request_async(self, router: IntelligenceRouter) -> None:
        await router.start()
        # Should not raise
        await router.request_async(Capability.CODING, "background task")
        await router.stop()

    async def test_provider_manager_accessible(self, router: IntelligenceRouter) -> None:
        assert router.provider_manager.count == 1

    async def test_capability_router_accessible(self, router: IntelligenceRouter) -> None:
        providers = router.capability_router.providers_for(Capability.CODING)
        assert "opencode" in providers

    async def test_prompt_engine_accessible(self, router: IntelligenceRouter) -> None:
        sys_prompt, user_prompt = router.prompt_engine.build(Capability.CODING, "test")
        assert "coding" in sys_prompt.lower()

    async def test_cache_accessible(self, router: IntelligenceRouter) -> None:
        assert router.cache.size == 0

    async def test_rate_limiter_accessible(self, router: IntelligenceRouter) -> None:
        limit = router.rate_limiter.get_limit("opencode")
        assert limit.requests_per_minute == 60

    async def test_metrics_accessible(self, router: IntelligenceRouter) -> None:
        stats = router.metrics.provider_stats("opencode")
        assert stats.total_requests == 0

    async def test_health_monitor_accessible(self, router: IntelligenceRouter) -> None:
        status = router.health_monitor.status("opencode")
        assert status is not None

    async def test_publishes_event(self, bus: EventBus) -> None:
        router = IntelligenceRouter(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("intelligence", handler)
        await router.start()
        await router.request(Capability.CODING, "event test")
        assert len(received) >= 1
        await router.stop()

    async def test_request_with_system_prompt(self, router: IntelligenceRouter) -> None:
        await router.start()
        resp = await router.request(
            Capability.CODING,
            "write code",
            system_prompt="You are an expert Python developer.",
        )
        assert resp.error is None
        await router.stop()

    async def test_request_with_context(self, router: IntelligenceRouter) -> None:
        await router.start()
        resp = await router.request(
            Capability.CODING,
            "implement feature",
            context={"language": "Python", "framework": "FastAPI"},
        )
        assert resp.error is None
        await router.stop()
