# Milestone 10 — Opportunity Engine

**Version:** 0.1.0

**Date:** July 2026

**Status:** Complete

---

## Summary

The Opportunity Engine discovers, stores, evaluates and ranks freelance opportunities. It performs no browser automation, no direct AI provider communication, and executes no actions. All reasoning goes through the Intelligence Router; all execution goes through the Execution Engine. Opportunity records are immutable — updates create new versions via the VersionManager.

---

## Deliverables

- **OpportunityEngine (IService)** — central orchestrator with full lifecycle (initialize/start/stop/health_check)
- **OpportunityRecord** — frozen dataclass with title, description, client info, budget, skills, difficulty, deadline, tags
- **OpportunityStore** — in-memory storage with filtering (source, status, budget range, remote, tags), text search, skill-based search
- **OpportunityCollection** — named group of records with auto-updating counts
- **OpportunityNormalizer** — field mapping, type coercion, source-agnostic normalization
- **OpportunityDiscovery** — source abstraction (manual, API, email) — no browser automation
- **ScamDetection** — 6 indicator types (suspicious keywords, scam phrases, suspicious email domains, unrealistic budgets, missing client name, missing contact info) with 5 risk levels
- **OpportunityScoring** — 10 scoring dimensions with configurable weights:
  - Skill Match, Budget, Difficulty, Estimated Time, Success Probability
  - Scam Risk (inverted), Expected ROI, Deadline Urgency, Client Reputation, Strategic Value
- **OpportunityRanking** — rank by total score or single dimension with min-score filter
- **VersionManager** — full version history with snapshots and restore capability
- **RecommendationEngine** — context-aware recommendations using user skills and preference overrides
- **OpportunityMetrics** — records created/updated/archived, scores, scam checks, searches, recommendations
- **Event Bus integration** — publishes OPPORTUNITY category events for all mutating operations
- **AtlasContext integration** — reads user skills from context for scoring/recommendations
- **Kernel registration** — created and registered in AtlasKernel.boot()

---

## Architecture

```
src/atlas_core/opportunity/
└── __init__.py          — All components (1,730 lines, 89% coverage)
```

### Component Hierarchy

```
OpportunityEngine (IService)
├── OpportunityStore           — in-memory storage
├── OpportunityNormalizer      — data normalization
├── ScamDetection              — fraud indicator analysis
├── OpportunityScoring         — 10-dimension weighted scoring
├── OpportunityRanking         — sort by score/dimension
├── VersionManager             — version history + restore
├── OpportunityDiscovery       — source abstraction
├── RecommendationEngine       — context-aware ranking
└── OpportunityMetrics         — usage statistics
```

### Scoring Dimensions

| Dimension | Weight | Range | Description |
|-----------|--------|-------|-------------|
| Skill Match | 0.20 | 0–100 | Overlap between required and user skills |
| Budget | 0.15 | 0–100 | Budget max tiers |
| Difficulty | 0.05 | 0–100 | Inverted difficulty (easier = higher) |
| Estimated Time | 0.05 | 0–100 | Shorter projects score higher |
| Success Probability | 0.15 | 0–100 | Client rep, difficulty, budget spread |
| Scam Risk | 0.10 | 0–100 | Inverted scam risk score |
| Expected ROI | 0.10 | 0–100 | Hourly rate tiers |
| Deadline Urgency | 0.05 | 0–100 | More time = higher score |
| Client Reputation | 0.05 | 0–100 | reputation × 20 |
| Strategic Value | 0.10 | 0–100 | Tags, source, client quality |

### Data Flow

```
create_record(title, skills, budget, ...)
  → OpportunityStore.add_record()
  → VersionManager.create_version()
  → publish OPPORTUNITY event

score(record_id, user_skills)
  → OpportunityStore.get_record()
  → ScamDetection.analyze()
  → OpportunityScoring.score() (10 dimensions)
  → OpportunityScore

recommend(user_skills, preferences)
  → OpportunityStore (all records or by ID)
  → OpportunityScoring.score() for each
  → OpportunityRanking.rank() with min_score
  → publish recommendation event
  → list[RankedOpportunity]
```

---

## Test Results

```
740 passed in 10.6s
Coverage: 95% overall
  opportunity      89%
  knowledge        98%
  browser          99%
  context          98%
  memory           99%
  kernel           97%
  execution        98%
  events           97%
  ...
```

113 new tests covering:
- Enums, records, store CRUD/filters/search
- Normalization, scam detection, scoring, ranking, versioning
- Engine lifecycle, record ops, collections, search, scoring, ranking
- Event publishing, metrics, version history, recommendations
- Kernel integration

---

## Known Issues

1. All storage is in-memory — no persistence across restarts
2. External source discovery (API, email) are stubs — no real integrations
3. ScamDetection uses simple keyword matching — no ML or reputation databases
4. RecommendationEngine does not learn from past user interactions
5. Scoring weights are static defaults — no adaptive weight tuning
6. Skill matching is exact string match — no synonym/stemming support

---

## Technical Debt

- No persistent storage backend (SQLite, PostgreSQL, etc.)
- No real Upwork/Freelancer/Fiverr API integrations
- No email scraping implementation
- No user feedback loop for recommendation tuning
- No batch operations (bulk create/update/delete)
- No pagination across large result sets
- No export/import for opportunity data
- Scoring dimensions could benefit from Intelligence Router integration for advanced analysis

---

## Files Created

```
src/atlas_core/opportunity/__init__.py   — 1,730 lines, full Opportunity Engine
tests/test_opportunity.py                 — 670 lines, 113 tests
docs/releases/MILESTONE_10_OPPORTUNITY_ENGINE.md
```

---

## Commit

```
108c5c1 feat(opportunity): complete layer 9 (stabilization) and layer 10 (opportunity engine)
```

---

## Next Steps

- Mission Control
- Notification Service
- Persistent storage backends
- Real API integrations for opportunity discovery

---

*End of Milestone 10 Report*
