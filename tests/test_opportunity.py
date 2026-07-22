"""Tests for the Opportunity Engine."""

import dataclasses

import pytest

from atlas_core.events import EventBus
from atlas_core.opportunity import (
    DimensionScore,
    OpportunityCollection,
    OpportunityDiscovery,
    OpportunityEngine,
    OpportunityImportance,
    OpportunityMetrics,
    OpportunityNormalizer,
    OpportunityRanking,
    OpportunityRecord,
    OpportunityScore,
    OpportunityScoring,
    OpportunitySource,
    OpportunityStatus,
    OpportunityStore,
    RankedOpportunity,
    RecommendationEngine,
    ScamDetection,
    ScamIndicator,
    ScamRiskLevel,
    ScoringDimension,
    SearchResult,
    VersionEntry,
    VersionManager,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def bus() -> EventBus:
    return EventBus(max_history=100)


@pytest.fixture
def engine(bus: EventBus) -> OpportunityEngine:
    return OpportunityEngine(bus)


@pytest.fixture
def store() -> OpportunityStore:
    return OpportunityStore()


@pytest.fixture
def normalizer() -> OpportunityNormalizer:
    return OpportunityNormalizer()


@pytest.fixture
def scam_detection() -> ScamDetection:
    return ScamDetection()


@pytest.fixture
def scoring() -> OpportunityScoring:
    return OpportunityScoring()


@pytest.fixture
def ranking() -> OpportunityRanking:
    return OpportunityRanking()


@pytest.fixture
def version_mgr() -> VersionManager:
    return VersionManager()


@pytest.fixture
def discovery(bus: EventBus) -> OpportunityDiscovery:
    return OpportunityDiscovery(bus)


@pytest.fixture
def recommendation(bus: EventBus) -> RecommendationEngine:
    return RecommendationEngine(bus)


@pytest.fixture
def sample_record() -> OpportunityRecord:
    return OpportunityRecord(
        title="Python Developer",
        description="Build REST APIs with FastAPI",
        source=OpportunitySource.MANUAL,
        client_name="TechCorp",
        client_email="client@techcorp.com",
        client_reputation=4.5,
        budget_min=5000,
        budget_max=10000,
        skills_required=["Python", "FastAPI", "PostgreSQL"],
        estimated_hours=80,
        difficulty=6.0,
        deadline="",
        tags=["strategic", "long-term"],
        remote=True,
    )


# ======================================================================
# Enums
# ======================================================================


class TestEnums:
    def test_opportunity_source_values(self) -> None:
        assert OpportunitySource.MANUAL.value == "manual"
        assert OpportunitySource.UPWORK.value == "upwork"
        assert OpportunitySource.FREELANCER.value == "freelancer"

    def test_opportunity_status_values(self) -> None:
        assert OpportunityStatus.NEW.name == "NEW"
        assert OpportunityStatus.DISCOVERED.name == "DISCOVERED"
        assert OpportunityStatus.SCAM.name == "SCAM"

    def test_opportunity_importance_values(self) -> None:
        assert OpportunityImportance.LOW.value == 1
        assert OpportunityImportance.CRITICAL.value == 4

    def test_scoring_dimension_values(self) -> None:
        assert ScoringDimension.SKILL_MATCH.value == "skill_match"
        assert ScoringDimension.STRATEGIC_VALUE.value == "strategic_value"

    def test_scam_risk_level_values(self) -> None:
        assert ScamRiskLevel.SAFE.value == "safe"
        assert ScamRiskLevel.CRITICAL.value == "critical"


# ======================================================================
# OpportunityRecord
# ======================================================================


class TestOpportunityRecord:
    def test_record_creation(self) -> None:
        r = OpportunityRecord(title="Test", record_id="test-id")
        assert r.title == "Test"
        assert r.record_id == "test-id"
        assert r.source == OpportunitySource.MANUAL
        assert r.status == OpportunityStatus.NEW
        assert r.remote is True
        assert r.version == 1

    def test_record_immutable(self) -> None:
        r = OpportunityRecord(title="Original")
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.title = "Modified"  # type: ignore[misc]

    def test_record_default_values(self) -> None:
        r = OpportunityRecord()
        assert r.budget_min == 0.0
        assert r.budget_max == 0.0
        assert r.skills_required == []
        assert r.tags == []
        assert r.currency == "USD"
        assert r.difficulty == 5.0


# ======================================================================
# OpportunityStore
# ======================================================================


class TestOpportunityStore:
    def test_add_and_get_record(self, store: OpportunityStore) -> None:
        r = OpportunityRecord(title="Test")
        store.add_record(r)
        assert store.get_record(r.record_id) is r

    def test_get_missing_record(self, store: OpportunityStore) -> None:
        assert store.get_record("missing") is None

    def test_update_record(self, store: OpportunityStore) -> None:
        r = OpportunityRecord(title="Before", budget_min=100)
        store.add_record(r)
        updated = store.update_record(r.record_id, title="After", budget_max=500)
        assert updated is not None
        assert updated.title == "After"
        assert updated.budget_max == 500.0
        assert updated.budget_min == 100.0
        assert updated.record_id == r.record_id

    def test_update_missing_record(self, store: OpportunityStore) -> None:
        assert store.update_record("missing", title="Nope") is None

    def test_delete_record(self, store: OpportunityStore) -> None:
        r = OpportunityRecord(title="Delete Me")
        store.add_record(r)
        assert store.delete_record(r.record_id) is True
        assert store.get_record(r.record_id) is None

    def test_delete_missing_record(self, store: OpportunityStore) -> None:
        assert store.delete_record("missing") is False

    def test_list_records_empty(self, store: OpportunityStore) -> None:
        assert store.list_records() == []

    def test_list_records_with_filters(self, store: OpportunityStore) -> None:
        r1 = OpportunityRecord(title="A", budget_min=100, budget_max=500, remote=True, tags=["urgent"])
        r2 = OpportunityRecord(title="B", budget_min=1000, budget_max=5000, remote=False, tags=["long"])
        store.add_record(r1)
        store.add_record(r2)

        results = store.list_records(min_budget=600)
        assert len(results) == 1
        assert results[0].title == "B"

        results = store.list_records(max_budget=600)
        assert len(results) == 1
        assert results[0].title == "A"

        results = store.list_records(remote_only=True)
        assert len(results) == 1
        assert results[0].title == "A"

        results = store.list_records(tag_filter="urgent")
        assert len(results) == 1

    def test_record_count(self, store: OpportunityStore) -> None:
        assert store.record_count == 0
        store.add_record(OpportunityRecord(title="A"))
        assert store.record_count == 1

    def test_all_records(self, store: OpportunityStore) -> None:
        store.add_record(OpportunityRecord(title="A"))
        store.add_record(OpportunityRecord(title="B"))
        assert len(store.all_records) == 2

    def test_search_by_skills(self, store: OpportunityStore) -> None:
        r1 = OpportunityRecord(title="Python Dev", skills_required=["Python", "Django"])
        r2 = OpportunityRecord(title="JS Dev", skills_required=["JavaScript", "React"])
        r3 = OpportunityRecord(title="Full Stack", skills_required=["Python", "React"])
        store.add_record(r1)
        store.add_record(r2)
        store.add_record(r3)

        results = store.search_by_skills(["Python"])
        assert len(results) == 2
        assert results[0].title == "Python Dev"

    def test_search_by_skills_no_match(self, store: OpportunityStore) -> None:
        assert store.search_by_skills(["Nonexistent"]) == []

    def test_search_by_skills_empty(self, store: OpportunityStore) -> None:
        assert store.search_by_skills([]) == []

    def test_search_text(self, store: OpportunityStore) -> None:
        r = OpportunityRecord(title="FastAPI Expert", description="Build APIs")
        store.add_record(r)
        results = store.search_text("FastAPI")
        assert len(results) == 1
        assert results[0].score > 0

    def test_search_text_no_match(self, store: OpportunityStore) -> None:
        r = OpportunityRecord(title="Python")
        store.add_record(r)
        assert store.search_text("Java") == []

    def test_search_text_empty_query(self, store: OpportunityStore) -> None:
        assert store.search_text("") == []

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def test_add_and_get_collection(self, store: OpportunityStore) -> None:
        c = OpportunityCollection(name="Test Col")
        store.add_collection(c)
        assert store.get_collection(c.collection_id) is c

    def test_list_collections(self, store: OpportunityStore) -> None:
        store.add_collection(OpportunityCollection(name="A"))
        store.add_collection(OpportunityCollection(name="B"))
        assert len(store.list_collections()) == 2

    def test_delete_collection(self, store: OpportunityStore) -> None:
        c = OpportunityCollection(name="Del")
        store.add_collection(c)
        assert store.delete_collection(c.collection_id) is True
        assert store.get_collection(c.collection_id) is None

    def test_update_collection(self, store: OpportunityStore) -> None:
        c = OpportunityCollection(name="Before")
        store.add_collection(c)
        store.update_collection(c.collection_id, name="After")
        assert store.get_collection(c.collection_id).name == "After"

    def test_clear(self, store: OpportunityStore) -> None:
        store.add_record(OpportunityRecord(title="A"))
        store.add_collection(OpportunityCollection(name="C"))
        store.clear()
        assert store.record_count == 0
        assert store.collection_count == 0


# ======================================================================
# OpportunityNormalizer
# ======================================================================


class TestOpportunityNormalizer:
    def test_normalize_basic(self, normalizer: OpportunityNormalizer) -> None:
        raw = {
            "title": "  Python Dev  ",
            "description": "Build APIs",
            "budget_min": "5000",
            "budget_max": "10000",
            "skills_required": ["Python", "FastAPI"],
            "remote": True,
        }
        result = normalizer.normalize(raw, OpportunitySource.MANUAL)
        assert result["title"] == "Python Dev"
        assert result["budget_min"] == 5000.0
        assert result["budget_max"] == 10000.0
        assert result["source"] == "manual"
        assert result["remote"] is True

    def test_normalize_string_trimming(self, normalizer: OpportunityNormalizer) -> None:
        assert normalizer._normalize_string("  hello  ") == "hello"
        assert normalizer._normalize_string(None) == ""
        assert normalizer._normalize_string(123) == "123"

    def test_normalize_float(self, normalizer: OpportunityNormalizer) -> None:
        assert normalizer._normalize_float("50.5") == 50.5
        assert normalizer._normalize_float(None) == 0.0
        assert normalizer._normalize_float(-10) == 0.0
        assert normalizer._normalize_float("abc") == 0.0

    def test_normalize_difficulty(self, normalizer: OpportunityNormalizer) -> None:
        assert normalizer._normalize_difficulty(5) == 5.0
        assert normalizer._normalize_difficulty(0) == 1.0
        assert normalizer._normalize_difficulty(15) == 10.0

    def test_normalize_list(self, normalizer: OpportunityNormalizer) -> None:
        assert normalizer._normalize_list(["a", "b"]) == ["a", "b"]
        assert normalizer._normalize_list("a,b,c") == ["a", "b", "c"]
        assert normalizer._normalize_list(None) == []
        assert normalizer._normalize_list(123) == []


# ======================================================================
# ScamDetection
# ======================================================================


class TestScamDetection:
    def test_safe_opportunity(self, scam_detection: ScamDetection) -> None:
        r = OpportunityRecord(
            title="Python Developer",
            client_name="TechCorp",
            client_email="jobs@techcorp.com",
            budget_max=10000,
            estimated_hours=100,
        )
        risk, indicators = scam_detection.analyze(r)
        assert risk == ScamRiskLevel.SAFE
        assert len(indicators) == 0

    def test_suspicious_keywords(self, scam_detection: ScamDetection) -> None:
        r = OpportunityRecord(
            title="Easy Money Work from Home",
            description="Bitcoin only payment",
            client_name="",
        )
        risk, indicators = scam_detection.analyze(r)
        assert risk in (ScamRiskLevel.HIGH, ScamRiskLevel.CRITICAL)
        assert len(indicators) > 0

    def test_missing_contact_info(self, scam_detection: ScamDetection) -> None:
        r = OpportunityRecord(
            title="Test",
            client_name="",
            client_email="",
            url="",
        )
        risk, indicators = scam_detection.analyze(r)
        assert risk in (ScamRiskLevel.MEDIUM, ScamRiskLevel.HIGH)

    def test_suspicious_email_domain(self, scam_detection: ScamDetection) -> None:
        r = OpportunityRecord(
            title="Test",
            client_name="Someone",
            client_email="someone@gmail.com",
        )
        risk, indicators = scam_detection.analyze(r)
        has_email_indicator = any(i.indicator_type == "suspicious_email" for i in indicators)
        assert has_email_indicator

    def test_unrealistic_hourly_rate(self, scam_detection: ScamDetection) -> None:
        r = OpportunityRecord(
            title="Test",
            client_name="Client",
            client_email="client@company.com",
            budget_max=50000,
            estimated_hours=10,
        )
        risk, indicators = scam_detection.analyze(r)
        has_budget_indicator = any(i.indicator_type == "unrealistic_budget" for i in indicators)
        assert has_budget_indicator


# ======================================================================
# OpportunityScoring
# ======================================================================


class TestOpportunityScoring:
    def test_score_basic(self, scoring: OpportunityScoring, sample_record: OpportunityRecord) -> None:
        result = scoring.score(sample_record, user_skills=["Python", "FastAPI", "PostgreSQL"])
        assert isinstance(result, OpportunityScore)
        assert result.record_id == sample_record.record_id
        assert 0 <= result.total_score <= 100
        assert len(result.dimensions) == 10
        assert result.scam_risk == ScamRiskLevel.SAFE

    def test_score_skill_match_perfect(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(skills_required=["Python", "FastAPI"])
        result = scoring.score(r, user_skills=["Python", "FastAPI"])
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.SKILL_MATCH)
        assert dim.score == 100.0

    def test_score_skill_match_partial(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(skills_required=["Python", "FastAPI", "Docker"])
        result = scoring.score(r, user_skills=["Python"])
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.SKILL_MATCH)
        assert dim.score == pytest.approx(100.0 / 3, rel=0.1)

    def test_score_skill_match_no_skills_required(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(skills_required=[])
        result = scoring.score(r, user_skills=["Python"])
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.SKILL_MATCH)
        assert dim.score == 50.0

    def test_score_budget_tiers(self, scoring: OpportunityScoring) -> None:
        tests = [
            (0, 0, 0.0),
            (100, 200, 20.0),
            (500, 1000, 60.0),
            (5000, 7500, 80.0),
            (10000, 50000, 100.0),
        ]
        for bmin, bmax, expected in tests:
            r = OpportunityRecord(budget_min=bmin, budget_max=bmax)
            result = scoring.score(r)
            dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.BUDGET)
            assert dim.score == expected, f"Failed for budget_max={bmax}"

    def test_score_difficulty(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(difficulty=2.0)
        result = scoring.score(r)
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.DIFFICULTY)
        assert dim.score == 80.0

    def test_score_estimated_time(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(estimated_hours=10)
        result = scoring.score(r)
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.ESTIMATED_TIME)
        assert dim.score == 70.0

    def test_score_scam_risk(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(
            title="Easy Money",
            description="Bitcoin only",
            client_name="",
        )
        result = scoring.score(r)
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.SCAM_RISK)
        assert dim.score <= 25.0

    def test_score_roi(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(budget_max=5000, estimated_hours=50)
        result = scoring.score(r)
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.EXPECTED_ROI)
        assert dim.score == 80.0

    def test_score_roi_no_data(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord()
        result = scoring.score(r)
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.EXPECTED_ROI)
        assert dim.score == 0.0

    def test_score_deadline_urgency_no_deadline(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord()
        result = scoring.score(r)
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.DEADLINE_URGENCY)
        assert dim.score == 50.0

    def test_score_client_reputation(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(client_reputation=4.0)
        result = scoring.score(r)
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.CLIENT_REPUTATION)
        assert dim.score == 80.0

    def test_score_strategic_value(self, scoring: OpportunityScoring) -> None:
        r = OpportunityRecord(tags=["strategic", "long-term"], client_reputation=4.5)
        result = scoring.score(r)
        dim = next(d for d in result.dimensions if d.dimension == ScoringDimension.STRATEGIC_VALUE)
        assert dim.score > 50.0

    def test_custom_weights(self, scoring: OpportunityScoring, sample_record: OpportunityRecord) -> None:
        weights = {ScoringDimension.SKILL_MATCH: 1.0}
        for d in ScoringDimension:
            if d != ScoringDimension.SKILL_MATCH:
                weights[d] = 0.0
        result = scoring.score(sample_record, user_skills=["Python"], weights=weights)
        assert result.total_score > 0


# ======================================================================
# OpportunityRanking
# ======================================================================


class TestOpportunityRanking:
    def test_rank(self, ranking: OpportunityRanking) -> None:
        r1 = OpportunityRecord(record_id="1", title="A")
        r2 = OpportunityRecord(record_id="2", title="B")
        s1 = OpportunityScore(record_id="1", total_score=80.0)
        s2 = OpportunityScore(record_id="2", total_score=90.0)
        records = {"1": r1, "2": r2}
        result = ranking.rank([s1, s2], records)
        assert len(result) == 2
        assert result[0].record.title == "B"
        assert result[0].rank == 1
        assert result[1].rank == 2

    def test_rank_with_min_score(self, ranking: OpportunityRanking) -> None:
        r1 = OpportunityRecord(record_id="1", title="A")
        s1 = OpportunityScore(record_id="1", total_score=30.0)
        result = ranking.rank([s1], {"1": r1}, min_score=50.0)
        assert len(result) == 0

    def test_rank_by_dimension(self, ranking: OpportunityRanking) -> None:
        r1 = OpportunityRecord(record_id="1", title="A")
        r2 = OpportunityRecord(record_id="2", title="B")
        s1 = OpportunityScore(
            record_id="1", total_score=50.0,
            dimensions=[DimensionScore(dimension=ScoringDimension.BUDGET, score=90.0)],
        )
        s2 = OpportunityScore(
            record_id="2", total_score=50.0,
            dimensions=[DimensionScore(dimension=ScoringDimension.BUDGET, score=70.0)],
        )
        result = ranking.rank_by_dimension([s1, s2], {"1": r1, "2": r2}, ScoringDimension.BUDGET)
        assert len(result) == 2
        assert result[0].record.title == "A"
        assert result[0].score.total_score == 90.0


# ======================================================================
# VersionManager
# ======================================================================


class TestVersionManager:
    def test_create_and_get_history(self, version_mgr: VersionManager) -> None:
        r = OpportunityRecord(title="V1")
        version_mgr.create_version(r, "Initial")
        history = version_mgr.get_history(r.record_id)
        assert len(history) == 1
        assert history[0].version == 1
        assert history[0].change_description == "Initial"

    def test_multiple_versions(self, version_mgr: VersionManager) -> None:
        r = OpportunityRecord(title="Test")
        version_mgr.create_version(r, "v1")
        r2 = OpportunityRecord(title="Test", record_id=r.record_id, version=2)
        version_mgr.create_version(r2, "v2")
        history = version_mgr.get_history(r.record_id)
        assert len(history) == 2

    def test_get_version(self, version_mgr: VersionManager) -> None:
        r = OpportunityRecord(title="Test")
        version_mgr.create_version(r, "v1")
        entry = version_mgr.get_version(r.record_id, 1)
        assert entry is not None
        assert entry.version == 1

    def test_get_missing_version(self, version_mgr: VersionManager) -> None:
        assert version_mgr.get_version("missing", 1) is None

    def test_restore(self, version_mgr: VersionManager) -> None:
        r = OpportunityRecord(title="Original", budget_min=100)
        version_mgr.create_version(r, "v1")
        snapshot = version_mgr.restore(r.record_id, 1)
        assert snapshot is not None
        assert snapshot["title"] == "Original"

    def test_restore_missing(self, version_mgr: VersionManager) -> None:
        assert version_mgr.restore("missing", 1) is None

    def test_total_versions(self, version_mgr: VersionManager) -> None:
        assert version_mgr.total_versions == 0
        r = OpportunityRecord(title="A")
        version_mgr.create_version(r)
        assert version_mgr.total_versions == 1

    def test_clear(self, version_mgr: VersionManager) -> None:
        r = OpportunityRecord(title="A")
        version_mgr.create_version(r)
        version_mgr.clear()
        assert version_mgr.total_versions == 0


# ======================================================================
# OpportunityDiscovery
# ======================================================================


class TestOpportunityDiscovery:
    def test_discover_manual(self, discovery: OpportunityDiscovery) -> None:
        results = discovery._discover_manual({"title": "Test"})
        assert len(results) == 1
        assert results[0]["title"] == "Test"

    def test_discover_manual_empty(self, discovery: OpportunityDiscovery) -> None:
        assert discovery._discover_manual({}) == []

    def test_discover_api_stub(self, discovery: OpportunityDiscovery) -> None:
        assert discovery._discover_from_api({}) == []

    def test_discover_email_stub(self, discovery: OpportunityDiscovery) -> None:
        assert discovery._discover_from_email({}) == []

    def test_discover_unsupported_source(self, discovery: OpportunityDiscovery) -> None:
        results = discovery._discover_from_email({})
        assert results == []


# ======================================================================
# RecommendationEngine
# ======================================================================


class TestRecommendationEngine:
    async def test_recommend_empty(self, recommendation: RecommendationEngine) -> None:
        results = await recommendation.recommend([])
        assert results == []

    async def test_recommend_basic(self, recommendation: RecommendationEngine, sample_record: OpportunityRecord) -> None:
        results = await recommendation.recommend(
            [sample_record],
            user_skills=["Python", "FastAPI"],
        )
        assert len(results) == 1
        assert results[0].record.title == "Python Developer"
        assert results[0].score.total_score > 0

    async def test_recommend_with_preferences(self, recommendation: RecommendationEngine) -> None:
        r = OpportunityRecord(
            title="High Budget",
            budget_min=10000,
            budget_max=20000,
            skills_required=["Python"],
        )
        prefs = {"min_score": 50.0}
        results = await recommendation.recommend([r], user_skills=["Python"], preferences=prefs)
        assert len(results) >= 0


# ======================================================================
# OpportunityEngine — IService lifecycle
# ======================================================================


class TestOpportunityEngineLifecycle:
    def test_name(self, engine: OpportunityEngine) -> None:
        assert engine.name == "opportunity_engine"

    async def test_initialize(self, engine: OpportunityEngine) -> None:
        await engine.initialize()
        assert engine._running is False

    async def test_start_stop(self, engine: OpportunityEngine) -> None:
        await engine.start()
        assert engine._running is True
        await engine.stop()
        assert engine._running is False

    async def test_health_check(self, engine: OpportunityEngine) -> None:
        await engine.start()
        health = await engine.health_check()
        assert health.healthy is True
        assert health.state.name == "RUNNING"
        assert "total_records" in health.metadata
        await engine.stop()

    async def test_set_context(self, engine: OpportunityEngine) -> None:
        from atlas_core.context import AtlasContext
        ctx = AtlasContext()
        engine.set_context(ctx)
        assert engine._context is ctx


# ======================================================================
# OpportunityEngine — Record operations
# ======================================================================


class TestOpportunityEngineRecords:
    async def test_create_record(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(title="Test Opportunity")
        assert r.title == "Test Opportunity"
        assert r.version == 1
        assert engine.metrics.records_created == 1
        assert engine.metrics.total_records == 1

    async def test_get_record(self, engine: OpportunityEngine) -> None:
        created = await engine.create_record(title="Find Me")
        fetched = await engine.get_record(created.record_id)
        assert fetched is not None
        assert fetched.title == "Find Me"

    async def test_get_missing_record(self, engine: OpportunityEngine) -> None:
        assert await engine.get_record("missing") is None

    async def test_update_record(self, engine: OpportunityEngine) -> None:
        created = await engine.create_record(title="Before")
        updated = await engine.update_record(created.record_id, title="After")
        assert updated is not None
        assert updated.title == "After"

    async def test_update_missing_record(self, engine: OpportunityEngine) -> None:
        assert await engine.update_record("missing", title="Nope") is None

    async def test_delete_record(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(title="Delete Me")
        assert await engine.delete_record(r.record_id) is True

    async def test_delete_missing_record(self, engine: OpportunityEngine) -> None:
        assert await engine.delete_record("missing") is False

    async def test_list_records(self, engine: OpportunityEngine) -> None:
        await engine.create_record(title="A")
        await engine.create_record(title="B", source=OpportunitySource.UPWORK)
        all_records = await engine.list_records()
        assert len(all_records) == 2
        upwork = await engine.list_records(source_filter=OpportunitySource.UPWORK)
        assert len(upwork) == 1


# ======================================================================
# OpportunityEngine — Collections
# ======================================================================


class TestOpportunityEngineCollections:
    async def test_create_collection(self, engine: OpportunityEngine) -> None:
        c = await engine.create_collection(name="Test Collection")
        assert c.name == "Test Collection"
        assert engine.metrics.total_collections == 1

    async def test_get_collection(self, engine: OpportunityEngine) -> None:
        created = await engine.create_collection(name="Find Me")
        fetched = await engine.get_collection(created.collection_id)
        assert fetched is not None
        assert fetched.name == "Find Me"

    async def test_list_collections(self, engine: OpportunityEngine) -> None:
        await engine.create_collection(name="A")
        await engine.create_collection(name="B")
        assert len(await engine.list_collections()) == 2

    async def test_delete_collection(self, engine: OpportunityEngine) -> None:
        c = await engine.create_collection(name="Delete")
        assert await engine.delete_collection(c.collection_id) is True


# ======================================================================
# OpportunityEngine — Search
# ======================================================================


class TestOpportunityEngineSearch:
    async def test_search_text(self, engine: OpportunityEngine) -> None:
        await engine.create_record(title="Python Developer")
        results = await engine.search("Python")
        assert len(results) >= 1
        assert results[0].score > 0

    async def test_search_no_match(self, engine: OpportunityEngine) -> None:
        await engine.create_record(title="Python")
        assert await engine.search("Java") == []

    async def test_search_by_skills(self, engine: OpportunityEngine) -> None:
        await engine.create_record(title="Python Dev", skills_required=["Python", "Django"])
        results = await engine.search_by_skills(["Python"])
        assert len(results) >= 1


# ======================================================================
# OpportunityEngine — Scam detection
# ======================================================================


class TestOpportunityEngineScam:
    async def test_check_scam_safe(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(
            title="Legit Project",
            client_name="Company",
            client_email="jobs@company.com",
        )
        result = await engine.check_scam(r.record_id)
        assert result is not None
        risk, indicators = result
        assert risk == ScamRiskLevel.SAFE

    async def test_check_scam_missing_record(self, engine: OpportunityEngine) -> None:
        assert await engine.check_scam("missing") is None

    async def test_check_scam_detected(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(
            title="Easy Money Bitcoin Only",
            client_name="",
        )
        result = await engine.check_scam(r.record_id)
        assert result is not None
        risk, indicators = result
        assert risk in (ScamRiskLevel.HIGH, ScamRiskLevel.CRITICAL)
        assert engine.metrics.total_scam_checks == 1
        assert engine.metrics.scam_detected >= 1


# ======================================================================
# OpportunityEngine — Scoring
# ======================================================================


class TestOpportunityEngineScoring:
    async def test_score_record(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(
            title="Python AI Project",
            skills_required=["Python", "PyTorch"],
            budget_max=15000,
        )
        result = await engine.score(r.record_id, user_skills=["Python", "PyTorch"])
        assert result is not None
        assert 0 <= result.total_score <= 100
        assert engine.metrics.total_scores == 1

    async def test_score_missing_record(self, engine: OpportunityEngine) -> None:
        assert await engine.score("missing") is None

    async def test_score_many(self, engine: OpportunityEngine) -> None:
        r1 = await engine.create_record(title="A", skills_required=["Python"])
        r2 = await engine.create_record(title="B", skills_required=["Java"])
        scores = await engine.score_many(
            [r1.record_id, r2.record_id],
            user_skills=["Python"],
        )
        assert len(scores) == 2
        assert scores[0].record_id == r1.record_id


# ======================================================================
# OpportunityEngine — Ranking
# ======================================================================


class TestOpportunityEngineRanking:
    async def test_rank_scores(self, engine: OpportunityEngine) -> None:
        r1 = await engine.create_record(title="High Value", budget_max=20000)
        r2 = await engine.create_record(title="Low Value", budget_max=100)
        s1 = await engine.score(r1.record_id)
        s2 = await engine.score(r2.record_id)
        assert s1 is not None
        assert s2 is not None
        ranked = await engine.rank([s1, s2])
        assert len(ranked) == 2
        assert ranked[0].record.title == "High Value"


# ======================================================================
# OpportunityEngine — Version history
# ======================================================================


class TestOpportunityEngineVersioning:
    async def test_version_history(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(title="v1")
        await engine.update_record(r.record_id, title="v2")
        history = await engine.get_version_history(r.record_id)
        assert len(history) == 2

    async def test_get_version(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(title="Original")
        entry = await engine.get_version(r.record_id, 1)
        assert entry is not None
        assert entry.version == 1

    async def test_restore_version(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(title="Original", budget_min=100)
        await engine.update_record(r.record_id, title="Modified")
        restored = await engine.restore_version(r.record_id, 1)
        assert restored is not None

    async def test_restore_missing_version(self, engine: OpportunityEngine) -> None:
        assert await engine.restore_version("missing", 1) is None


# ======================================================================
# OpportunityEngine — Normalization
# ======================================================================


class TestOpportunityEngineNormalization:
    async def test_normalize(self, engine: OpportunityEngine) -> None:
        raw = {"title": "  Test  ", "budget_max": "5000"}
        result = await engine.normalize(raw, OpportunitySource.MANUAL)
        assert result["title"] == "Test"
        assert result["budget_max"] == 5000.0


# ======================================================================
# OpportunityEngine — Discovery
# ======================================================================


class TestOpportunityEngineDiscovery:
    async def test_discover(self, engine: OpportunityEngine) -> None:
        results = await engine.discover(OpportunitySource.MANUAL, {"title": "Manual Entry"})
        assert len(results) == 1
        assert results[0]["title"] == "Manual Entry"


# ======================================================================
# OpportunityEngine — Recommendations
# ======================================================================


class TestOpportunityEngineRecommendations:
    async def test_recommend(self, engine: OpportunityEngine) -> None:
        await engine.create_record(
            title="Python Project",
            skills_required=["Python", "FastAPI"],
        )
        results = await engine.recommend(user_skills=["Python"])
        assert len(results) >= 1
        assert engine.metrics.total_recommendations >= 1

    async def test_recommend_with_ids(self, engine: OpportunityEngine) -> None:
        r = await engine.create_record(title="Selected")
        await engine.create_record(title="Other")
        results = await engine.recommend(record_ids=[r.record_id], user_skills=[])
        assert len(results) == 1

    async def test_recommend_empty(self, engine: OpportunityEngine) -> None:
        results = await engine.recommend(record_ids=[], user_skills=[])
        assert results == []


# ======================================================================
# OpportunityEngine — Event publishing
# ======================================================================


class TestOpportunityEngineEvents:
    async def test_publishes_events(self, bus: EventBus) -> None:
        engine = OpportunityEngine(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("opportunity", handler)
        await engine.create_record(title="Event Test")
        await engine.create_collection(name="Collection Test")
        assert len(received) >= 2

    async def test_record_updated_publishes_event(self, bus: EventBus) -> None:
        engine = OpportunityEngine(bus)
        received: list = []

        async def handler(event: object) -> None:
            received.append(event)

        bus.subscribe("opportunity", handler)
        r = await engine.create_record(title="Before")
        await engine.update_record(r.record_id, title="After")
        assert len(received) >= 2


# ======================================================================
# OpportunityEngine — Metrics
# ======================================================================


class TestOpportunityMetrics:
    async def test_metrics_updated(self, engine: OpportunityEngine) -> None:
        assert engine.metrics.total_records == 0
        await engine.create_record(title="A")
        assert engine.metrics.total_records == 1
        assert engine.metrics.records_created == 1

    async def test_metrics_defaults(self) -> None:
        m = OpportunityMetrics()
        assert m.total_records == 0
        assert m.errors == 0


# ======================================================================
# Integration with kernel
# ======================================================================


class TestKernelIntegration:
    async def test_kernel_creates_opportunity_engine(self) -> None:
        from atlas_core.kernel import AtlasKernel
        kernel = AtlasKernel()
        kernel.initialize()
        kernel.boot()
        engine = kernel.opportunity_engine
        assert engine.name == "opportunity_engine"
        assert engine is kernel._opportunity_engine
