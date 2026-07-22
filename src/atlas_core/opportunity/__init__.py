"""Opportunity Engine — discovers, stores, evaluates and ranks freelance opportunities.

Opportunity records are immutable.
Updates create new versions.
The Opportunity Engine never executes actions.
The Opportunity Engine never talks directly to AI providers.
All reasoning goes through the Intelligence Router.
All execution goes through the Execution Engine.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any
from uuid import UUID, uuid4

from atlas_core.context import AtlasContext
from atlas_core.events import EventBus
from atlas_core.interfaces import IService, ServiceHealth, ServiceState
from atlas_core.interfaces.events import Event, EventCategory, EventPriority


# ======================================================================
# Enums
# ======================================================================


class OpportunitySource(Enum):
    MANUAL = "manual"
    UPWORK = "upwork"
    FREELANCER = "freelancer"
    FIVERR = "fiverr"
    TOPTAL = "toptal"
    LINKEDIN = "linkedin"
    EMAIL = "email"
    REFERRAL = "referral"
    API = "api"
    WEB_SCRAPE = "web_scrape"
    OTHER = "other"


class OpportunityStatus(Enum):
    NEW = auto()
    DISCOVERED = auto()
    NORMALIZED = auto()
    SCORED = auto()
    MATCHED = auto()
    RECOMMENDED = auto()
    APPLIED = auto()
    INTERVIEWING = auto()
    OFFERED = auto()
    ACCEPTED = auto()
    REJECTED = auto()
    DECLINED = auto()
    ARCHIVED = auto()
    EXPIRED = auto()
    SCAM = auto()


class OpportunityImportance(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class ScoringDimension(Enum):
    SKILL_MATCH = "skill_match"
    BUDGET = "budget"
    DIFFICULTY = "difficulty"
    ESTIMATED_TIME = "estimated_time"
    SUCCESS_PROBABILITY = "success_probability"
    SCAM_RISK = "scam_risk"
    EXPECTED_ROI = "expected_roi"
    DEADLINE_URGENCY = "deadline_urgency"
    CLIENT_REPUTATION = "client_reputation"
    STRATEGIC_VALUE = "strategic_value"


class ScamRiskLevel(Enum):
    SAFE = "safe"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ======================================================================
# Core data classes
# ======================================================================


@dataclass(frozen=True)
class OpportunityRecord:
    """An immutable opportunity record.

    Once created, fields cannot be mutated.
    Updates create a new version via the OpportunityStore.
    """

    record_id: str = field(default_factory=lambda: str(uuid4()))
    collection_id: str = ""
    source: OpportunitySource = OpportunitySource.MANUAL
    status: OpportunityStatus = OpportunityStatus.NEW
    importance: OpportunityImportance = OpportunityImportance.MEDIUM
    title: str = ""
    description: str = ""
    client_name: str = ""
    client_email: str = ""
    client_reputation: float = 0.0
    budget_min: float = 0.0
    budget_max: float = 0.0
    currency: str = "USD"
    skills_required: list[str] = field(default_factory=list)
    estimated_hours: float = 0.0
    difficulty: float = 5.0
    deadline: str = ""
    url: str = ""
    location: str = ""
    remote: bool = True
    tags: list[str] = field(default_factory=list)
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OpportunityCollection:
    """A named group of opportunity records."""

    collection_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    record_count: int = 0


@dataclass
class ScamIndicator:
    """A detected scam indicator for an opportunity."""

    indicator_id: str = field(default_factory=lambda: str(uuid4()))
    record_id: str = ""
    indicator_type: str = ""
    description: str = ""
    severity: ScamRiskLevel = ScamRiskLevel.LOW
    matched_pattern: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class DimensionScore:
    """A single dimension score within an opportunity evaluation."""

    dimension: ScoringDimension = ScoringDimension.SKILL_MATCH
    score: float = 0.0
    weight: float = 1.0
    explanation: str = ""


@dataclass
class OpportunityScore:
    """A scored evaluation of an opportunity."""

    score_id: str = field(default_factory=lambda: str(uuid4()))
    record_id: str = ""
    total_score: float = 0.0
    dimensions: list[DimensionScore] = field(default_factory=list)
    scam_risk: ScamRiskLevel = ScamRiskLevel.SAFE
    scam_indicators: list[ScamIndicator] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class VersionEntry:
    """A single version entry in a record's version history."""

    version: int = 1
    record_id: str = ""
    snapshot: dict[str, Any] = field(default_factory=dict)
    change_description: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class SearchResult:
    """A single search result with relevance scoring."""

    record: OpportunityRecord | None = None
    score: float = 0.0
    matched_field: str = ""
    matched_text: str = ""
    collection_name: str = ""


@dataclass
class OpportunityMetrics:
    """Usage and content metrics for the Opportunity Engine."""

    total_records: int = 0
    total_collections: int = 0
    total_scores: int = 0
    total_scam_checks: int = 0
    scam_detected: int = 0
    total_recommendations: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_archived: int = 0
    searches_performed: int = 0
    errors: int = 0


# ======================================================================
# OpportunityStore
# ======================================================================


class OpportunityStore:
    """In-memory storage for opportunity records and collections."""

    def __init__(self) -> None:
        self._records: dict[str, OpportunityRecord] = {}
        self._collections: dict[str, OpportunityCollection] = {}
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Records
    # ------------------------------------------------------------------

    def add_record(self, record: OpportunityRecord) -> OpportunityRecord:
        self._records[record.record_id] = record
        self._logger.debug("Added opportunity %s (%s)", record.record_id, record.title)
        return record

    def get_record(self, record_id: str) -> OpportunityRecord | None:
        return self._records.get(record_id)

    def update_record(self, record_id: str, **updates: Any) -> OpportunityRecord | None:
        existing = self._records.get(record_id)
        if existing is None:
            return None
        mutable = {k: v for k, v in existing.__dict__.items()}
        for key, value in updates.items():
            if key in ("record_id", "created_at"):
                continue
            if hasattr(existing, key):
                mutable[key] = value
        mutable["updated_at"] = datetime.now()
        record = OpportunityRecord(**mutable)
        self._records[record_id] = record
        return record

    def delete_record(self, record_id: str) -> bool:
        if record_id in self._records:
            del self._records[record_id]
            return True
        return False

    def list_records(
        self,
        collection_id: str | None = None,
        source_filter: OpportunitySource | None = None,
        status_filter: OpportunityStatus | None = None,
        tag_filter: str | None = None,
        min_budget: float | None = None,
        max_budget: float | None = None,
        remote_only: bool | None = None,
        limit: int = 100,
    ) -> list[OpportunityRecord]:
        results: list[OpportunityRecord] = []
        for r in self._records.values():
            if collection_id is not None and r.collection_id != collection_id:
                continue
            if source_filter is not None and r.source != source_filter:
                continue
            if status_filter is not None and r.status != status_filter:
                continue
            if tag_filter is not None and tag_filter not in r.tags:
                continue
            if min_budget is not None and r.budget_max < min_budget:
                continue
            if max_budget is not None and r.budget_min > max_budget:
                continue
            if remote_only is not None and r.remote != remote_only:
                continue
            results.append(r)
            if len(results) >= limit:
                break
        return results

    @property
    def record_count(self) -> int:
        return len(self._records)

    @property
    def all_records(self) -> list[OpportunityRecord]:
        return list(self._records.values())

    def search_by_skills(self, skills: list[str], limit: int = 20) -> list[OpportunityRecord]:
        if not skills:
            return []
        skill_set = {s.lower() for s in skills}
        scored: list[tuple[OpportunityRecord, int]] = []
        for r in self._records.values():
            match_count = sum(1 for s in r.skills_required if s.lower() in skill_set)
            if match_count > 0:
                scored.append((r, match_count))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [r for r, _ in scored[:limit]]

    def search_text(self, query: str, limit: int = 20) -> list[SearchResult]:
        if not query.strip():
            return []
        query_lower = query.lower()
        results: list[SearchResult] = []
        for r in self._records.values():
            score = 0.0
            matched_field = ""
            matched_text = ""
            if query_lower in r.title.lower():
                score += 10
                matched_field = "title"
                matched_text = r.title
            if query_lower in r.description.lower():
                score += 5
                matched_field = "description"
                idx = r.description.lower().find(query_lower)
                start = max(0, idx - 40)
                end = min(len(r.description), idx + 60)
                matched_text = r.description[start:end]
            if query_lower in r.client_name.lower():
                score += 3
                if not matched_field:
                    matched_field = "client_name"
                    matched_text = r.client_name
            if query_lower in r.tags:
                score += 2
            if any(query_lower in s.lower() for s in r.skills_required):
                score += 8
                if not matched_field:
                    matched_field = "skills_required"
            if score > 0:
                results.append(SearchResult(
                    record=r,
                    score=score,
                    matched_field=matched_field or "general",
                    matched_text=matched_text,
                ))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def add_collection(self, collection: OpportunityCollection) -> OpportunityCollection:
        self._collections[collection.collection_id] = collection
        self._logger.debug("Added collection %s (%s)", collection.collection_id, collection.name)
        return collection

    def get_collection(self, collection_id: str) -> OpportunityCollection | None:
        return self._collections.get(collection_id)

    def update_collection(self, collection_id: str, **updates: Any) -> OpportunityCollection | None:
        existing = self._collections.get(collection_id)
        if existing is None:
            return None
        for key, value in updates.items():
            if hasattr(existing, key) and key not in ("collection_id", "created_at"):
                setattr(existing, key, value)
        existing.updated_at = datetime.now()
        existing.record_count = sum(
            1 for r in self._records.values() if r.collection_id == collection_id
        )
        return existing

    def delete_collection(self, collection_id: str) -> bool:
        if collection_id in self._collections:
            del self._collections[collection_id]
            return True
        return False

    def list_collections(self) -> list[OpportunityCollection]:
        return list(self._collections.values())

    @property
    def collection_count(self) -> int:
        return len(self._collections)

    def clear(self) -> None:
        self._records.clear()
        self._collections.clear()


# ======================================================================
# OpportunityNormalizer
# ======================================================================


class OpportunityNormalizer:
    """Normalizes opportunity data from various sources into a standard format."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def normalize(
        self,
        raw: dict[str, Any],
        source: OpportunitySource = OpportunitySource.MANUAL,
    ) -> dict[str, Any]:
        """Normalize raw opportunity data into a standard dictionary.

        Handles field mapping and type coercion for different sources.
        """
        normalized: dict[str, Any] = {}

        normalized["title"] = self._normalize_string(raw.get("title", ""))
        normalized["description"] = self._normalize_string(raw.get("description", ""))
        normalized["client_name"] = self._normalize_string(raw.get("client_name", ""))
        normalized["client_email"] = self._normalize_string(raw.get("client_email", ""))
        normalized["url"] = self._normalize_string(raw.get("url", ""))

        normalized["budget_min"] = self._normalize_float(raw.get("budget_min", 0.0))
        normalized["budget_max"] = self._normalize_float(raw.get("budget_max", 0.0))
        normalized["currency"] = raw.get("currency", "USD")
        normalized["estimated_hours"] = self._normalize_float(raw.get("estimated_hours", 0.0))
        normalized["difficulty"] = self._normalize_difficulty(raw.get("difficulty", 5.0))
        normalized["client_reputation"] = self._normalize_float(raw.get("client_reputation", 0.0), max_val=5.0)
        normalized["deadline"] = self._normalize_string(raw.get("deadline", ""))

        normalized["skills_required"] = self._normalize_list(raw.get("skills_required", []))
        normalized["tags"] = self._normalize_list(raw.get("tags", []))
        normalized["location"] = self._normalize_string(raw.get("location", ""))
        normalized["remote"] = bool(raw.get("remote", True))

        normalized["source"] = source.value if isinstance(source, OpportunitySource) else source
        normalized["metadata"] = raw.get("metadata", {})

        return normalized

    @staticmethod
    def _normalize_string(value: Any) -> str:
        if not isinstance(value, str):
            return str(value) if value is not None else ""
        return value.strip()

    @staticmethod
    def _normalize_float(value: Any, max_val: float | None = None) -> float:
        try:
            v = float(value)
            if max_val is not None:
                v = min(v, max_val)
            return max(0.0, v)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _normalize_difficulty(value: Any) -> float:
        try:
            v = float(value)
            return max(1.0, min(10.0, v))
        except (TypeError, ValueError):
            return 5.0

    @staticmethod
    def _normalize_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if item]
        if isinstance(value, str):
            return [s.strip() for s in value.split(",") if s.strip()]
        return []


# ======================================================================
# ScamDetection
# ======================================================================


class ScamDetection:
    """Detects potentially fraudulent or scam opportunities."""

    # Common scam patterns
    SUSPICIOUS_KEYWORDS: list[str] = [
        "paypal", "western union", "money gram", "wire transfer",
        "advance fee", "processing fee", "registration fee",
        "upfront payment", "money laundering", "easy money",
        "work from home", "make money fast", "untaxed",
        "offshore account", "bitcoin only", "crypto only",
    ]

    SUSPICIOUS_EMAIL_DOMAINS: list[str] = [
        "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
        "yandex.com", "protonmail.com", "tempmail.com",
    ]

    KNOWN_SCAM_PHRASES: list[str] = [
        "no experience necessary", "guaranteed income",
        "earn thousands", "limited time offer", "act now",
        "exclusive opportunity", "secret method",
    ]

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def analyze(self, record: OpportunityRecord) -> tuple[ScamRiskLevel, list[ScamIndicator]]:
        """Analyze an opportunity for scam indicators.

        Returns a tuple of (risk_level, list_of_indicators).
        """
        indicators: list[ScamIndicator] = []
        total_risk_score = 0

        # Check title and description for suspicious keywords
        text_to_check = f"{record.title} {record.description}".lower()
        for keyword in self.SUSPICIOUS_KEYWORDS:
            if keyword in text_to_check:
                indicators.append(ScamIndicator(
                    record_id=record.record_id,
                    indicator_type="suspicious_keyword",
                    description=f"Contains suspicious keyword: '{keyword}'",
                    severity=ScamRiskLevel.HIGH if keyword in ("bitcoin only", "crypto only", "money laundering") else ScamRiskLevel.MEDIUM,
                    matched_pattern=keyword,
                ))
                total_risk_score += 15

        # Check for known scam phrases
        for phrase in self.KNOWN_SCAM_PHRASES:
            if phrase in text_to_check:
                indicators.append(ScamIndicator(
                    record_id=record.record_id,
                    indicator_type="scam_phrase",
                    description=f"Contains known scam phrase: '{phrase}'",
                    severity=ScamRiskLevel.HIGH,
                    matched_pattern=phrase,
                ))
                total_risk_score += 20

        # Check email domain
        email = record.client_email.lower()
        if email:
            for domain in self.SUSPICIOUS_EMAIL_DOMAINS:
                if domain in email:
                    indicators.append(ScamIndicator(
                        record_id=record.record_id,
                        indicator_type="suspicious_email",
                        description=f"Uses generic email domain: {domain}",
                        severity=ScamRiskLevel.LOW,
                        matched_pattern=domain,
                    ))
                    total_risk_score += 5
                    break

        # Check for unrealistic budget
        if record.budget_max > 0 and record.estimated_hours > 0:
            hourly_rate = record.budget_max / record.estimated_hours
            if hourly_rate > 1000:
                indicators.append(ScamIndicator(
                    record_id=record.record_id,
                    indicator_type="unrealistic_budget",
                    description=f"Unrealistic hourly rate: ${hourly_rate:.2f}/hr",
                    severity=ScamRiskLevel.MEDIUM,
                    matched_pattern=f"${hourly_rate:.2f}/hr",
                ))
                total_risk_score += 15

        # Check for missing client info
        if not record.client_name:
            indicators.append(ScamIndicator(
                record_id=record.record_id,
                indicator_type="missing_client_name",
                description="No client name provided",
                severity=ScamRiskLevel.MEDIUM,
                matched_pattern="",
            ))
            total_risk_score += 10

        if not record.client_email and not record.url:
            indicators.append(ScamIndicator(
                record_id=record.record_id,
                indicator_type="missing_contact",
                description="No contact information provided",
                severity=ScamRiskLevel.HIGH,
                matched_pattern="",
            ))
            total_risk_score += 20

        # Determine overall risk level
        if total_risk_score >= 50:
            risk = ScamRiskLevel.CRITICAL
        elif total_risk_score >= 30:
            risk = ScamRiskLevel.HIGH
        elif total_risk_score >= 15:
            risk = ScamRiskLevel.MEDIUM
        elif total_risk_score >= 5:
            risk = ScamRiskLevel.LOW
        else:
            risk = ScamRiskLevel.SAFE

        return risk, indicators


# ======================================================================
# OpportunityScoring
# ======================================================================


class OpportunityScoring:
    """Scores opportunities across multiple dimensions."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)
        self._default_weights: dict[ScoringDimension, float] = {
            ScoringDimension.SKILL_MATCH: 0.20,
            ScoringDimension.BUDGET: 0.15,
            ScoringDimension.DIFFICULTY: 0.05,
            ScoringDimension.ESTIMATED_TIME: 0.05,
            ScoringDimension.SUCCESS_PROBABILITY: 0.15,
            ScoringDimension.SCAM_RISK: 0.10,
            ScoringDimension.EXPECTED_ROI: 0.10,
            ScoringDimension.DEADLINE_URGENCY: 0.05,
            ScoringDimension.CLIENT_REPUTATION: 0.05,
            ScoringDimension.STRATEGIC_VALUE: 0.10,
        }

    def score(
        self,
        record: OpportunityRecord,
        user_skills: list[str] | None = None,
        weights: dict[ScoringDimension, float] | None = None,
    ) -> OpportunityScore:
        """Score an opportunity across all dimensions.

        Args:
            record: The opportunity record to score.
            user_skills: List of user's skills for skill matching.
            weights: Optional dimension weight overrides.

        Returns:
            An OpportunityScore with dimension scores and total.
        """
        effective_weights = {**self._default_weights, **(weights or {})}
        dimensions: list[DimensionScore] = []

        # 1. Skill Match
        skill_score = self._score_skill_match(record, user_skills or [])
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.SKILL_MATCH,
            score=skill_score,
            weight=effective_weights[ScoringDimension.SKILL_MATCH],
            explanation=self._skill_match_explanation(record, user_skills or []),
        ))

        # 2. Budget
        budget_score = self._score_budget(record)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.BUDGET,
            score=budget_score,
            weight=effective_weights[ScoringDimension.BUDGET],
            explanation=f"Budget range: ${record.budget_min:.2f} - ${record.budget_max:.2f}",
        ))

        # 3. Difficulty
        difficulty_score = self._score_difficulty(record)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.DIFFICULTY,
            score=difficulty_score,
            weight=effective_weights[ScoringDimension.DIFFICULTY],
            explanation=f"Difficulty level: {record.difficulty}/10",
        ))

        # 4. Estimated Time
        time_score = self._score_estimated_time(record)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.ESTIMATED_TIME,
            score=time_score,
            weight=effective_weights[ScoringDimension.ESTIMATED_TIME],
            explanation=f"Estimated hours: {record.estimated_hours}",
        ))

        # 5. Success Probability
        prob_score = self._score_success_probability(record)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.SUCCESS_PROBABILITY,
            score=prob_score,
            weight=effective_weights[ScoringDimension.SUCCESS_PROBABILITY],
            explanation=self._success_prob_explanation(record),
        ))

        # 6. Scam Risk (inverted — higher scam risk = lower score)
        scam_risk, scam_indicators = ScamDetection().analyze(record)
        scam_score = self._score_scam_risk(scam_risk)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.SCAM_RISK,
            score=scam_score,
            weight=effective_weights[ScoringDimension.SCAM_RISK],
            explanation=f"Scam risk: {scam_risk.value}",
        ))

        # 7. Expected ROI
        roi_score = self._score_expected_roi(record)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.EXPECTED_ROI,
            score=roi_score,
            weight=effective_weights[ScoringDimension.EXPECTED_ROI],
            explanation=self._roi_explanation(record),
        ))

        # 8. Deadline Urgency
        urgency_score = self._score_deadline_urgency(record)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.DEADLINE_URGENCY,
            score=urgency_score,
            weight=effective_weights[ScoringDimension.DEADLINE_URGENCY],
            explanation=f"Deadline: {record.deadline or 'No deadline set'}",
        ))

        # 9. Client Reputation
        reputation_score = self._score_client_reputation(record)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.CLIENT_REPUTATION,
            score=reputation_score,
            weight=effective_weights[ScoringDimension.CLIENT_REPUTATION],
            explanation=f"Client reputation: {record.client_reputation}/5.0",
        ))

        # 10. Strategic Value
        strategic_score = self._score_strategic_value(record)
        dimensions.append(DimensionScore(
            dimension=ScoringDimension.STRATEGIC_VALUE,
            score=strategic_score,
            weight=effective_weights[ScoringDimension.STRATEGIC_VALUE],
            explanation=self._strategic_value_explanation(record),
        ))

        # Calculate weighted total
        total_weight = sum(d.weight for d in dimensions)
        weighted_sum = sum(d.score * d.weight for d in dimensions)
        total_score = (weighted_sum / total_weight) if total_weight > 0 else 0.0

        return OpportunityScore(
            record_id=record.record_id,
            total_score=round(total_score, 2),
            dimensions=dimensions,
            scam_risk=scam_risk,
            scam_indicators=scam_indicators,
        )

    def _score_skill_match(self, record: OpportunityRecord, user_skills: list[str]) -> float:
        if not record.skills_required:
            return 50.0
        if not user_skills:
            return 25.0
        user_set = {s.lower() for s in user_skills}
        required_set = {s.lower() for s in record.skills_required}
        if not required_set:
            return 50.0
        matches = required_set & user_set
        ratio = len(matches) / len(required_set)
        return min(100.0, ratio * 100.0)

    def _skill_match_explanation(self, record: OpportunityRecord, user_skills: list[str]) -> str:
        if not record.skills_required:
            return "No skills required"
        user_set = {s.lower() for s in user_skills}
        matches = [s for s in record.skills_required if s.lower() in user_set]
        missing = [s for s in record.skills_required if s.lower() not in user_set]
        parts = []
        if matches:
            parts.append(f"Matched: {', '.join(matches)}")
        if missing:
            parts.append(f"Missing: {', '.join(missing)}")
        return "; ".join(parts) if parts else "No skills provided"

    def _score_budget(self, record: OpportunityRecord) -> float:
        if record.budget_max <= 0:
            return 0.0
        if record.budget_max >= 10000:
            return 100.0
        if record.budget_max >= 5000:
            return 80.0
        if record.budget_max >= 1000:
            return 60.0
        if record.budget_max >= 500:
            return 40.0
        if record.budget_max >= 100:
            return 20.0
        return 10.0

    def _score_difficulty(self, record: OpportunityRecord) -> float:
        d = record.difficulty
        if d <= 2.0:
            return 80.0
        if d <= 4.0:
            return 60.0
        if d <= 6.0:
            return 50.0
        if d <= 8.0:
            return 40.0
        return 30.0

    def _score_estimated_time(self, record: OpportunityRecord) -> float:
        h = record.estimated_hours
        if h <= 0:
            return 50.0
        if h <= 5:
            return 90.0
        if h <= 20:
            return 70.0
        if h <= 40:
            return 50.0
        if h <= 100:
            return 30.0
        return 10.0

    def _score_success_probability(self, record: OpportunityRecord) -> float:
        score = 50.0
        if record.client_reputation >= 4.0:
            score += 20
        elif record.client_reputation >= 3.0:
            score += 10
        elif record.client_reputation <= 1.0:
            score -= 20
        if record.difficulty <= 3.0:
            score += 15
        elif record.difficulty >= 8.0:
            score -= 15
        if record.budget_min > 0 and record.budget_max > 0:
            spread = record.budget_max - record.budget_min
            if spread > record.budget_min * 2:
                score -= 10
        return max(0.0, min(100.0, score))

    def _success_prob_explanation(self, record: OpportunityRecord) -> str:
        factors: list[str] = []
        if record.client_reputation >= 4.0:
            factors.append("High client reputation")
        elif record.client_reputation <= 1.0:
            factors.append("Low client reputation")
        if record.difficulty <= 3.0:
            factors.append("Low difficulty")
        elif record.difficulty >= 8.0:
            factors.append("High difficulty")
        return "; ".join(factors) if factors else "Standard probability"

    def _score_scam_risk(self, risk: ScamRiskLevel) -> float:
        mapping = {
            ScamRiskLevel.SAFE: 100.0,
            ScamRiskLevel.LOW: 75.0,
            ScamRiskLevel.MEDIUM: 50.0,
            ScamRiskLevel.HIGH: 25.0,
            ScamRiskLevel.CRITICAL: 0.0,
        }
        return mapping.get(risk, 50.0)

    def _score_expected_roi(self, record: OpportunityRecord) -> float:
        if record.estimated_hours <= 0 or record.budget_max <= 0:
            return 0.0
        hourly = record.budget_max / record.estimated_hours
        if hourly >= 200:
            return 100.0
        if hourly >= 100:
            return 80.0
        if hourly >= 50:
            return 60.0
        if hourly >= 25:
            return 40.0
        if hourly >= 10:
            return 20.0
        return 10.0

    def _roi_explanation(self, record: OpportunityRecord) -> str:
        if record.estimated_hours <= 0 or record.budget_max <= 0:
            return "Insufficient data to calculate ROI"
        hourly = record.budget_max / record.estimated_hours
        return f"Estimated hourly rate: ${hourly:.2f}/hr"

    def _score_deadline_urgency(self, record: OpportunityRecord) -> float:
        if not record.deadline:
            return 50.0
        try:
            deadline = datetime.fromisoformat(record.deadline)
            now = datetime.now()
            days_remaining = (deadline - now).total_seconds() / 86400
            if days_remaining <= 1:
                return 10.0
            if days_remaining <= 3:
                return 30.0
            if days_remaining <= 7:
                return 50.0
            if days_remaining <= 14:
                return 70.0
            if days_remaining <= 30:
                return 80.0
            return 90.0
        except (ValueError, TypeError):
            return 50.0

    def _score_client_reputation(self, record: OpportunityRecord) -> float:
        return min(100.0, record.client_reputation * 20.0)

    def _score_strategic_value(self, record: OpportunityRecord) -> float:
        score = 50.0
        tags_lower = {t.lower() for t in record.tags}
        if "strategic" in tags_lower or "long-term" in tags_lower:
            score += 20
        if "portfolio" in tags_lower or "showcase" in tags_lower:
            score += 15
        if "referral" in tags_lower or "repeat" in tags_lower:
            score += 15
        if record.client_reputation >= 4.0:
            score += 10
        if record.source in (OpportunitySource.REFERRAL, OpportunitySource.TOPTAL):
            score += 10
        return min(100.0, score)

    def _strategic_value_explanation(self, record: OpportunityRecord) -> str:
        factors: list[str] = []
        tags_lower = {t.lower() for t in record.tags}
        if "strategic" in tags_lower or "long-term" in tags_lower:
            factors.append("Strategic/Long-term potential")
        if "portfolio" in tags_lower or "showcase" in tags_lower:
            factors.append("Portfolio value")
        if "referral" in tags_lower or "repeat" in tags_lower:
            factors.append("Repeat/Referral opportunity")
        if record.client_reputation >= 4.0:
            factors.append("High-value client")
        return "; ".join(factors) if factors else "Standard value"


# ======================================================================
# OpportunityRanking
# ======================================================================


@dataclass
class RankedOpportunity:
    """A scored and ranked opportunity."""

    record: OpportunityRecord
    score: OpportunityScore
    rank: int = 0


class OpportunityRanking:
    """Ranks scored opportunities by configurable criteria."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def rank(
        self,
        scores: list[OpportunityScore],
        records: dict[str, OpportunityRecord],
        min_score: float = 0.0,
        max_results: int = 20,
    ) -> list[RankedOpportunity]:
        """Rank scored opportunities by total score.

        Args:
            scores: List of opportunity scores.
            records: Dict of record_id -> OpportunityRecord for lookup.
            min_score: Minimum total score to include.
            max_results: Maximum number of results to return.

        Returns:
            Ranked list of RankedOpportunity.
        """
        ranked: list[RankedOpportunity] = []
        for s in scores:
            if s.total_score < min_score:
                continue
            record = records.get(s.record_id)
            if record is None:
                continue
            ranked.append(RankedOpportunity(record=record, score=s))

        ranked.sort(key=lambda x: x.score.total_score, reverse=True)

        for i, item in enumerate(ranked[:max_results]):
            item.rank = i + 1

        return ranked[:max_results]

    def rank_by_dimension(
        self,
        scores: list[OpportunityScore],
        records: dict[str, OpportunityRecord],
        dimension: ScoringDimension,
        max_results: int = 20,
    ) -> list[RankedOpportunity]:
        """Rank scored opportunities by a specific dimension."""
        ranked: list[RankedOpportunity] = []
        for s in scores:
            record = records.get(s.record_id)
            if record is None:
                continue
            dim_scores = [d for d in s.dimensions if d.dimension == dimension]
            if not dim_scores:
                continue
            dim_score = dim_scores[0]

            adjusted = OpportunityScore(
                record_id=s.record_id,
                total_score=dim_score.score,
                dimensions=s.dimensions,
                scam_risk=s.scam_risk,
                scam_indicators=s.scam_indicators,
            )
            ranked.append(RankedOpportunity(record=record, score=adjusted))

        ranked.sort(key=lambda x: x.score.total_score, reverse=True)
        for i, item in enumerate(ranked[:max_results]):
            item.rank = i + 1
        return ranked[:max_results]


# ======================================================================
# VersionManager
# ======================================================================


class VersionManager:
    """Manages version history for opportunity records."""

    def __init__(self) -> None:
        self._versions: dict[str, list[VersionEntry]] = defaultdict(list)
        self._logger = logging.getLogger(__name__)

    def create_version(self, record: OpportunityRecord, change_description: str = "") -> VersionEntry:
        snapshot = {
            "record_id": record.record_id,
            "collection_id": record.collection_id,
            "source": record.source.value,
            "status": record.status.name,
            "title": record.title,
            "description": record.description,
            "client_name": record.client_name,
            "client_email": record.client_email,
            "client_reputation": record.client_reputation,
            "budget_min": record.budget_min,
            "budget_max": record.budget_max,
            "currency": record.currency,
            "skills_required": list(record.skills_required),
            "estimated_hours": record.estimated_hours,
            "difficulty": record.difficulty,
            "deadline": record.deadline,
            "url": record.url,
            "location": record.location,
            "remote": record.remote,
            "tags": list(record.tags),
            "version": record.version,
            "metadata": dict(record.metadata),
        }
        entry = VersionEntry(
            version=record.version,
            record_id=record.record_id,
            snapshot=snapshot,
            change_description=change_description,
        )
        self._versions[record.record_id].append(entry)
        return entry

    def get_history(self, record_id: str) -> list[VersionEntry]:
        return list(self._versions.get(record_id, []))

    def get_version(self, record_id: str, version: int) -> VersionEntry | None:
        for entry in self._versions.get(record_id, []):
            if entry.version == version:
                return entry
        return None

    def restore(self, record_id: str, version: int) -> dict[str, Any] | None:
        entry = self.get_version(record_id, version)
        if entry is None:
            return None
        return dict(entry.snapshot)

    @property
    def total_versions(self) -> int:
        return sum(len(v) for v in self._versions.values())

    def clear(self) -> None:
        self._versions.clear()


# ======================================================================
# OpportunityDiscovery
# ======================================================================


class OpportunityDiscovery:
    """Discovers opportunities from various sources.

    Performs NO browser automation.
    Communicates with external sources through the public API only.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def discover(
        self,
        source: OpportunitySource = OpportunitySource.MANUAL,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Discover opportunities from a source.

        Args:
            source: The source to discover from.
            params: Additional parameters for the discovery.

        Returns:
            A list of raw opportunity data dicts ready for normalization.
        """
        self._logger.info("Discovering opportunities from %s", source.value)
        raw_results: list[dict[str, Any]] = []

        params = params or {}

        if source == OpportunitySource.MANUAL:
            raw_results = self._discover_manual(params)
        elif source == OpportunitySource.API:
            raw_results = self._discover_from_api(params)
        elif source == OpportunitySource.EMAIL:
            raw_results = self._discover_from_email(params)
        else:
            self._logger.warning("Discovery from %s not yet implemented", source.value)

        if self._event_bus:
            try:
                await self._event_bus.publish(Event(
                    source="opportunity_discovery",
                    category=EventCategory.OPPORTUNITY,
                    priority=EventPriority.NORMAL,
                    payload={
                        "action": "discovery_completed",
                        "source": source.value,
                        "count": len(raw_results),
                    },
                ))
            except Exception:
                self._logger.exception("Failed to publish discovery event")

        return raw_results

    def _discover_manual(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Manual entry — return params as-is wrapped in a list."""
        if params:
            return [params]
        return []

    def _discover_from_api(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Discover from an external API source.

        This is a stub — real integration requires specific API clients.
        """
        endpoint = params.get("endpoint", "")
        if endpoint:
            self._logger.info("API discovery from %s (stub)", endpoint)
        return []

    def _discover_from_email(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Discover from email.

        This is a stub — real integration requires email client.
        """
        self._logger.info("Email discovery (stub)")
        return []


# ======================================================================
# RecommendationEngine
# ======================================================================


class RecommendationEngine:
    """Recommends opportunities based on user context, skills, and history.

    All reasoning goes through the Intelligence Router (via public API).
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def recommend(
        self,
        records: list[OpportunityRecord],
        user_skills: list[str] | None = None,
        preferences: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[RankedOpportunity]:
        """Generate recommendations from a list of opportunities.

        Uses OpportunityScoring and OpportunityRanking internally.
        All scoring is deterministic — no AI reasoning is performed here.

        Args:
            records: List of opportunity records to evaluate.
            user_skills: List of user's skills.
            preferences: User preference overrides for scoring weights.
            limit: Maximum number of recommendations.

        Returns:
            Ranked list of recommended opportunities.
        """
        if not records:
            return []

        user_skills = user_skills or []
        preferences = preferences or {}

        scorer = OpportunityScoring()
        ranking = OpportunityRanking()

        weight_overrides: dict[ScoringDimension, float] = {}
        for key, value in preferences.items():
            try:
                dim = ScoringDimension(key)
                weight_overrides[dim] = float(value)
            except (ValueError, TypeError):
                pass

        scores: list[OpportunityScore] = []
        for record in records:
            s = scorer.score(record, user_skills=user_skills, weights=weight_overrides or None)
            scores.append(s)

        records_map = {r.record_id: r for r in records}
        min_score = preferences.get("min_score", 0.0)
        ranked = ranking.rank(scores, records_map, min_score=float(min_score), max_results=limit)

        if self._event_bus:
            try:
                await self._event_bus.publish(Event(
                    source="opportunity_recommendation",
                    category=EventCategory.OPPORTUNITY,
                    priority=EventPriority.NORMAL,
                    payload={
                        "action": "recommendations_generated",
                        "count": len(ranked),
                        "limit": limit,
                    },
                ))
            except Exception:
                self._logger.exception("Failed to publish recommendation event")

        return ranked


# ======================================================================
# OpportunityEngine — IService
# ======================================================================


class OpportunityEngine(IService):
    """Central opportunity management for Atlas.

    Discovers, stores, evaluates and ranks freelance opportunities.
    Records are immutable — updates create new versions.
    Never executes actions or communicates directly with AI providers.
    """

    def __init__(self, event_bus: EventBus) -> None:
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

        self._store = OpportunityStore()
        self._normalizer = OpportunityNormalizer()
        self._scam_detection = ScamDetection()
        self._scoring = OpportunityScoring()
        self._ranking = OpportunityRanking()
        self._version_manager = VersionManager()
        self._discovery = OpportunityDiscovery(event_bus)
        self._recommendation = RecommendationEngine(event_bus)
        self._metrics = OpportunityMetrics()

        self._running = False
        self._context: AtlasContext | None = None

    # ------------------------------------------------------------------
    # IService
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "opportunity_engine"

    async def initialize(self) -> None:
        await super().initialize()
        self._logger.info("Opportunity Engine initializing")

    async def start(self) -> None:
        await super().start()
        self._running = True
        self._logger.info("Opportunity Engine started")

    async def stop(self) -> None:
        await super().stop()
        self._running = False
        self._logger.info("Opportunity Engine stopped")

    async def health_check(self) -> ServiceHealth:
        return ServiceHealth(
            healthy=True,
            state=ServiceState.RUNNING,
            metadata={
                "total_records": self._metrics.total_records,
                "total_collections": self._metrics.total_collections,
                "total_scores": self._metrics.total_scores,
                "total_scam_checks": self._metrics.total_scam_checks,
                "scam_detected": self._metrics.scam_detected,
                "total_recommendations": self._metrics.total_recommendations,
            },
        )

    # ------------------------------------------------------------------
    # Context integration
    # ------------------------------------------------------------------

    def set_context(self, context: AtlasContext) -> None:
        self._context = context

    # ------------------------------------------------------------------
    # Record operations
    # ------------------------------------------------------------------

    async def create_record(
        self,
        collection_id: str = "",
        title: str = "",
        description: str = "",
        source: OpportunitySource = OpportunitySource.MANUAL,
        status: OpportunityStatus = OpportunityStatus.NEW,
        importance: OpportunityImportance = OpportunityImportance.MEDIUM,
        client_name: str = "",
        client_email: str = "",
        client_reputation: float = 0.0,
        budget_min: float = 0.0,
        budget_max: float = 0.0,
        currency: str = "USD",
        skills_required: list[str] | None = None,
        estimated_hours: float = 0.0,
        difficulty: float = 5.0,
        deadline: str = "",
        url: str = "",
        location: str = "",
        remote: bool = True,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> OpportunityRecord:
        record = OpportunityRecord(
            collection_id=collection_id,
            source=source,
            status=status,
            importance=importance,
            title=title,
            description=description,
            client_name=client_name,
            client_email=client_email,
            client_reputation=client_reputation,
            budget_min=budget_min,
            budget_max=budget_max,
            currency=currency,
            skills_required=skills_required or [],
            estimated_hours=estimated_hours,
            difficulty=difficulty,
            deadline=deadline,
            url=url,
            location=location,
            remote=remote,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._store.add_record(record)
        self._version_manager.create_version(record, "Initial version")
        self._metrics.records_created += 1
        self._metrics.total_records = self._store.record_count

        if collection_id:
            self._store.update_collection(collection_id)

        await self._publish_event("record_created", {
            "record_id": record.record_id,
            "collection_id": collection_id,
            "title": title,
        })
        return record

    async def get_record(self, record_id: str) -> OpportunityRecord | None:
        return self._store.get_record(record_id)

    async def update_record(
        self,
        record_id: str,
        change_description: str = "",
        **updates: Any,
    ) -> OpportunityRecord | None:
        existing = self._store.get_record(record_id)
        if existing is None:
            return None

        self._version_manager.create_version(existing, change_description or f"Version {existing.version}")

        updates["version"] = existing.version + 1
        updated = self._store.update_record(record_id, **updates)
        if updated is None:
            return None

        self._metrics.records_updated += 1
        self._metrics.total_records = self._store.record_count

        await self._publish_event("record_updated", {
            "record_id": record_id,
            "new_version": updated.version,
            "change_description": change_description,
        })
        return updated

    async def delete_record(self, record_id: str) -> bool:
        result = self._store.delete_record(record_id)
        if result:
            self._metrics.records_archived += 1
            self._metrics.total_records = self._store.record_count
            await self._publish_event("record_deleted", {"record_id": record_id})
        return result

    async def list_records(
        self,
        collection_id: str | None = None,
        source_filter: OpportunitySource | None = None,
        status_filter: OpportunityStatus | None = None,
        tag_filter: str | None = None,
        min_budget: float | None = None,
        max_budget: float | None = None,
        remote_only: bool | None = None,
        limit: int = 100,
    ) -> list[OpportunityRecord]:
        return self._store.list_records(
            collection_id=collection_id,
            source_filter=source_filter,
            status_filter=status_filter,
            tag_filter=tag_filter,
            min_budget=min_budget,
            max_budget=max_budget,
            remote_only=remote_only,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Collection operations
    # ------------------------------------------------------------------

    async def create_collection(
        self,
        name: str,
        description: str = "",
        tags: list[str] | None = None,
    ) -> OpportunityCollection:
        collection = OpportunityCollection(
            name=name,
            description=description,
            tags=tags or [],
        )
        self._store.add_collection(collection)
        self._metrics.total_collections = self._store.collection_count
        await self._publish_event("collection_created", {
            "collection_id": collection.collection_id,
            "name": name,
        })
        return collection

    async def get_collection(self, collection_id: str) -> OpportunityCollection | None:
        return self._store.get_collection(collection_id)

    async def list_collections(self) -> list[OpportunityCollection]:
        return self._store.list_collections()

    async def delete_collection(self, collection_id: str) -> bool:
        result = self._store.delete_collection(collection_id)
        if result:
            self._metrics.total_collections = self._store.collection_count
            await self._publish_event("collection_deleted", {"collection_id": collection_id})
        return result

    # ------------------------------------------------------------------
    # Normalization
    # ------------------------------------------------------------------

    async def normalize(
        self,
        raw: dict[str, Any],
        source: OpportunitySource = OpportunitySource.MANUAL,
    ) -> dict[str, Any]:
        return self._normalizer.normalize(raw, source)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover(
        self,
        source: OpportunitySource = OpportunitySource.MANUAL,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return await self._discovery.discover(source, params)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[SearchResult]:
        self._metrics.searches_performed += 1
        return self._store.search_text(query, limit)

    async def search_by_skills(
        self,
        skills: list[str],
        limit: int = 20,
    ) -> list[OpportunityRecord]:
        self._metrics.searches_performed += 1
        return self._store.search_by_skills(skills, limit)

    # ------------------------------------------------------------------
    # Scam detection
    # ------------------------------------------------------------------

    async def check_scam(
        self,
        record_id: str,
    ) -> tuple[ScamRiskLevel, list[ScamIndicator]] | None:
        record = self._store.get_record(record_id)
        if record is None:
            return None
        self._metrics.total_scam_checks += 1
        risk, indicators = self._scam_detection.analyze(record)
        if risk in (ScamRiskLevel.HIGH, ScamRiskLevel.CRITICAL):
            self._metrics.scam_detected += 1
            if risk == ScamRiskLevel.CRITICAL:
                self._store.update_record(record_id, status=OpportunityStatus.SCAM)
        return risk, indicators

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    async def score(
        self,
        record_id: str,
        user_skills: list[str] | None = None,
        weights: dict[ScoringDimension, float] | None = None,
    ) -> OpportunityScore | None:
        record = self._store.get_record(record_id)
        if record is None:
            return None
        self._metrics.total_scores += 1
        return self._scoring.score(record, user_skills=user_skills, weights=weights)

    async def score_many(
        self,
        record_ids: list[str],
        user_skills: list[str] | None = None,
        weights: dict[ScoringDimension, float] | None = None,
    ) -> list[OpportunityScore]:
        scores: list[OpportunityScore] = []
        for rid in record_ids:
            record = self._store.get_record(rid)
            if record is not None:
                self._metrics.total_scores += 1
                scores.append(self._scoring.score(record, user_skills=user_skills, weights=weights))
        return scores

    # ------------------------------------------------------------------
    # Ranking
    # ------------------------------------------------------------------

    async def rank(
        self,
        scores: list[OpportunityScore],
        min_score: float = 0.0,
        max_results: int = 20,
    ) -> list[RankedOpportunity]:
        records_map = {}
        for s in scores:
            r = self._store.get_record(s.record_id)
            if r is not None:
                records_map[s.record_id] = r
        return self._ranking.rank(scores, records_map, min_score=min_score, max_results=max_results)

    # ------------------------------------------------------------------
    # Version history
    # ------------------------------------------------------------------

    async def get_version_history(self, record_id: str) -> list[VersionEntry]:
        return self._version_manager.get_history(record_id)

    async def get_version(self, record_id: str, version: int) -> VersionEntry | None:
        return self._version_manager.get_version(record_id, version)

    async def restore_version(self, record_id: str, version: int) -> OpportunityRecord | None:
        snapshot = self._version_manager.restore(record_id, version)
        if snapshot is None:
            return None
        existing = self._store.get_record(record_id)
        if existing is None:
            return None

        self._version_manager.create_version(existing, f"Restored from version {version}")
        restored = self._store.update_record(
            record_id,
            title=snapshot.get("title", existing.title),
            description=snapshot.get("description", existing.description),
            status=OpportunityStatus[snapshot.get("status", "NEW")],
            source=OpportunitySource(snapshot.get("source", "manual")),
        )
        if restored:
            self._metrics.records_updated += 1
        return restored

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    async def recommend(
        self,
        record_ids: list[str] | None = None,
        user_skills: list[str] | None = None,
        preferences: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[RankedOpportunity]:
        if record_ids is None:
            records = self._store.all_records
        else:
            records = [r for rid in record_ids if (r := self._store.get_record(rid)) is not None]

        user_skills = user_skills or self._get_skills_from_context()
        ranked = await self._recommendation.recommend(
            records,
            user_skills=user_skills,
            preferences=preferences,
            limit=limit,
        )
        self._metrics.total_recommendations += len(ranked)
        return ranked

    def _get_skills_from_context(self) -> list[str]:
        if self._context is None:
            return []
        try:
            profile = self._context.user.profile if hasattr(self._context, "user") else {}
            if isinstance(profile, dict):
                return profile.get("skills", [])
            return getattr(profile, "skills", []) if hasattr(profile, "skills") else []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @property
    def metrics(self) -> OpportunityMetrics:
        return self._metrics

    # ------------------------------------------------------------------
    # Sub-component accessors
    # ------------------------------------------------------------------

    @property
    def store(self) -> OpportunityStore:
        return self._store

    @property
    def normalizer(self) -> OpportunityNormalizer:
        return self._normalizer

    @property
    def scam_detection(self) -> ScamDetection:
        return self._scam_detection

    @property
    def scoring(self) -> OpportunityScoring:
        return self._scoring

    @property
    def ranking(self) -> OpportunityRanking:
        return self._ranking

    @property
    def version_manager(self) -> VersionManager:
        return self._version_manager

    @property
    def discovery(self) -> OpportunityDiscovery:
        return self._discovery

    @property
    def recommendation(self) -> RecommendationEngine:
        return self._recommendation

    # ------------------------------------------------------------------
    # Event publishing
    # ------------------------------------------------------------------

    async def _publish_event(self, action: str, payload: dict[str, Any]) -> None:
        try:
            await self._event_bus.publish(Event(
                source="opportunity_engine",
                category=EventCategory.OPPORTUNITY,
                priority=EventPriority.NORMAL,
                payload={"action": action, **payload},
            ))
        except Exception:
            self._logger.exception("Failed to publish opportunity event")
