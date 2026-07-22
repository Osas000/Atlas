# Milestone 05 — Intelligence Router

**Version:** 0.1.0

**Date:** July 2026

**Status:** Complete

---

## Summary

The Intelligence Router is Atlas's AI capability layer. All AI requests pass through this router — no subsystem communicates directly with an AI provider. In v1, OpenCode is the sole production provider, with the interface designed so OpenAI, Claude, Gemini, and Ollama adapters can be added later without modifying the router.

---

## Deliverables

- **Provider ABC** — abstract interface for AI provider adapters
- **OpenCodeAdapter** — v1 production provider supporting all 8 capabilities
- **CapabilityRouter** — maps capabilities to providers with best-provider selection
- **PromptEngine** — per-capability system prompt builder with context injection
- **ResponseCache** — TTL-based response cache with per-capability invalidation
- **RateLimitManager** — per-provider RPM and concurrent request tracking
- **MetricsCollector** — per-provider and per-capability usage/performance stats
- **ProviderHealthMonitor** — periodic health checks with status tracking
- **ProviderManager** — register and select providers
- **IntelligenceRouter (IService)** — unified entry point with:
  - `request()` — synchronous request with caching, rate limiting, metrics
  - `request_async()` — background queue submission with worker pool
  - Event Bus integration on every request completion
  - Full sub-component accessors
- **66 automated tests** with 93% coverage

---

## Architecture

```
src/atlas_core/intelligence/
└── __init__.py          — All components (421 lines)
```

### Component Hierarchy

```
IntelligenceRouter (IService)
├── ProviderManager         — provider registry
├── CapabilityRouter        — capability → provider mapping
├── PromptEngine            — system/user prompt builder
├── ResponseCache           — TTL cache with invalidation
├── RateLimitManager        — RPM + concurrent limits
├── MetricsCollector        — per-provider/capability stats
└── ProviderHealthMonitor   — periodic health checks

Provider (ABC)
└── OpenCodeAdapter         — v1 production adapter
```

### Request Flow

```
subsystem.request(capability, prompt)
  → IntelligenceRouter.request()
    1. Check ResponseCache (return cached if hit)
    2. CapabilityRouter selects best provider
    3. PromptEngine builds system + user prompt
    4. RateLimitManager acquires slot
    5. Provider.execute(request)
    6. MetricsCollector.record()
    7. ResponseCache.set() if successful
    8. Publish Event Bus event
  → IntelligenceResponse
```

### Supported Capabilities

| Capability | System Prompt |
|---|---|
| reasoning | "Think step by step." |
| coding | "Write clean, well-documented code." |
| planning | "Break down complex tasks." |
| translation | "Preserve meaning and tone." |
| summarization | "Be concise and accurate." |
| research | "Be thorough and cite sources." |
| extraction | "Return structured data only." |
| classification | "Return categories with confidence." |

---

## Test Results

```
259 passed in 5.36s
Coverage: 94% overall
  intelligence   93%
  context        98%
  memory         99%
  kernel         97%
  events         97%
  operations     94%
  ...
```

---

## Known Issues

1. OpenCodeAdapter uses a simulated response — real API integration is deferred
2. Rate limiting uses in-memory sliding window — not persisted across restarts
3. ResponseCache is in-memory only — no persistent cache backend
4. Queue workers discard responses (fire-and-forget for `request_async`)

---

## Technical Debt

- No real OpenCode API integration (simulated adapter)
- No provider failover/fallback between multiple providers
- No streaming support
- No semantic caching (exact-match only)
- No persistent metrics storage
- No circuit breaker for unhealthy providers
- No per-user rate limiting (global only)

---

## Files Created

```
src/atlas_core/intelligence/__init__.py    — 887 lines, full Intelligence Router
tests/test_intelligence.py                 — 569 lines, 66 tests
```

---

## Commit

```
39112a5 feat(intelligence): complete milestone 5 — intelligence router
```

---

## Next Steps

- Knowledge Engine
- Opportunity Engine
- Execution Engine
- Browser Companion
- Mission Control
- Notification Service
- Real OpenCode API integration

---

*End of Milestone 5 Report*
