"""Read/write HTTP boundary for Knowledge Evolution + Human Review (D-9C).

The router exposes the EXISTING D-8/D-9F lifecycle only:

    Investigation -> Pattern/Finding -> Hypothesis -> Validation
        -> Human Review -> Validated Knowledge (atomic promotion)

Authority contract:
    Investigation      = ANALYSIS_ONLY
    Pattern / Finding  = OBSERVATION_ONLY
    Hypothesis         = HYPOTHESIS_ONLY
    Validation         = ANALYSIS_ONLY
    Human Review       = HUMAN_REVIEW_REQUIRED (append-only)
    Validated Knowledge = INFORMATION_ONLY

No endpoint mutates the trading runtime, execution, strategy, Money Management
or Canonical Specification.  Human Review reviewer identity is derived ONLY
from a trusted server-side operator session (never the request body, never an
LLM/Advisor message).  The review subject fingerprint is derived server-side
from the persisted Hypothesis + Validation.

PROVIDER_NEUTRAL: no LLM SDK, no exchange client, no order placement.  The
router creates no second SQLite DB; it uses the shared KnowledgeEvolutionStore.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from backend.auth.dependencies import require_operator_session
from backend.knowledge_evolution.service import (
    KnowledgeApiError,
    KnowledgeEvolutionService,
    MAX_LIST_LIMIT,
)


# --------------------------------------------------------------------------- #
# Typed request models (strict: unknown fields rejected, bounded input)
# --------------------------------------------------------------------------- #

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigationCreateRequest(_Strict):
    question: str = Field(min_length=1, max_length=512)
    symbol: Optional[str] = Field(default=None, max_length=64)
    mode: Optional[str] = Field(default=None, max_length=32)
    started_from: Optional[str] = Field(default=None, max_length=64)
    started_to: Optional[str] = Field(default=None, max_length=64)
    trace_ids: list[str] = Field(default_factory=list, max_length=200)
    decision_ids: list[str] = Field(default_factory=list, max_length=200)
    trade_ids: list[str] = Field(default_factory=list, max_length=200)
    experience_types: list[str] = Field(default_factory=list, max_length=20)
    reason_codes: list[str] = Field(default_factory=list, max_length=200)
    outcomes: list[str] = Field(default_factory=list, max_length=200)
    completeness: list[str] = Field(default_factory=list, max_length=20)
    drift_statuses: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=100, ge=1, le=MAX_LIST_LIMIT)
    investigation_id: Optional[str] = Field(default=None, max_length=255)


class ValidationCriterionModel(_Strict):
    metric: Literal[
        "SAMPLE_SIZE", "SUPPORT_COUNT", "COUNTEREXAMPLE_COUNT", "SUPPORT_RATIO"
    ]
    relation: Literal["AT_LEAST", "AT_MOST"]
    threshold: float = Field(ge=0, le=100000.0)


class HypothesisCreateRequest(_Strict):
    statement: str = Field(min_length=1, max_length=512)
    derived_from_finding_ids: list[str] = Field(default_factory=list, max_length=40)
    supporting_pattern_ids: list[str] = Field(default_factory=list, max_length=40)
    expected_effect: str = Field(default="", max_length=512)
    validation_criteria: list[ValidationCriterionModel] = Field(
        default_factory=list, max_length=40
    )
    required_evidence: list[str] = Field(default_factory=list, max_length=200)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    hypothesis_id: Optional[str] = Field(default=None, max_length=255)


class HypothesisTransitionRequest(_Strict):
    target_status: Literal[
        "PROPOSED",
        "READY_FOR_VALIDATION",
        "VALIDATING",
        "SUPPORTED",
        "NOT_SUPPORTED",
        "INCONCLUSIVE",
        "REJECTED",
        "SUPERSEDED",
    ]


class AcceptanceCriterionModel(_Strict):
    metric: Literal[
        "SAMPLE_SIZE", "SUPPORT_COUNT", "COUNTEREXAMPLE_COUNT", "SUPPORT_RATIO"
    ]
    relation: Literal["AT_LEAST", "AT_MOST"]
    threshold: float = Field(ge=0, le=100000.0)


class ValidationCreateRequest(_Strict):
    hypothesis_id: str = Field(min_length=1, max_length=255)
    method: Literal[
        "HISTORICAL_REPLAY",
        "BACKTEST",
        "PAPER_RESULTS",
        "COMPARISON_COHORTS",
        "COUNTEREXAMPLE_ANALYSIS",
        "CONTRACT_ONLY",
        "UNAVAILABLE",
    ]
    sample_size: int = Field(ge=0, le=1000000)
    support_count: int = Field(ge=0, le=1000000)
    counterexample_count: int = Field(ge=0, le=1000000)
    dataset_references: list[str] = Field(default_factory=list, max_length=64)
    time_range: Optional[str] = Field(default=None, max_length=64)
    acceptance_criteria: list[AcceptanceCriterionModel] = Field(
        default_factory=list, max_length=40
    )
    limitations: list[str] = Field(default_factory=list, max_length=20)
    min_sample_size: int = Field(default=2, ge=1, le=1000)


class HumanReviewCreateRequest(_Strict):
    hypothesis_id: str = Field(min_length=1, max_length=255)
    validation_id: str = Field(min_length=1, max_length=255)
    decision: Literal["APPROVED", "REJECTED", "NEEDS_MORE_EVIDENCE"]
    notes: str = Field(default="", max_length=512)
    reviewed_at: Optional[str] = Field(default=None, max_length=64)


class PromotionCreateRequest(_Strict):
    hypothesis_id: str = Field(min_length=1, max_length=255)
    validation_id: str = Field(min_length=1, max_length=255)
    review_id: str = Field(min_length=1, max_length=255)
    version: str = Field(default="1.0", max_length=16)
    scope: str = Field(default="", max_length=256)
    limitations: list[str] = Field(default_factory=list, max_length=20)


# --------------------------------------------------------------------------- #
# Router factory
# --------------------------------------------------------------------------- #

_default_service: Optional[KnowledgeEvolutionService] = None


def _get_default_service() -> KnowledgeEvolutionService:
    global _default_service
    if _default_service is None:
        _default_service = KnowledgeEvolutionService()
    return _default_service


def _handle(error: KnowledgeApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={
            "status": "ERROR",
            "code": error.code.value,
            "message": error.message,
        },
    )


def _criteria_to_tuples(criteria):
    return [
        (item.metric, item.relation, item.threshold) for item in criteria
    ]


def create_knowledge_router(
    service: Optional[KnowledgeEvolutionService] = None,
) -> APIRouter:
    svc = service or _get_default_service()
    router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

    # -------------------------------------------------- #
    # Investigation
    # -------------------------------------------------- #

    @router.post("/investigations", status_code=201)
    def create_investigation(payload: InvestigationCreateRequest):
        try:
            return svc.create_investigation(**payload.model_dump())
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/investigations/{investigation_id}")
    def get_investigation(investigation_id: str):
        try:
            return svc.get_investigation(investigation_id)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/investigations")
    def list_investigations(
        limit: Optional[int] = Query(default=None, ge=1, le=MAX_LIST_LIMIT),
    ):
        try:
            return svc.list_investigations(limit=limit)
        except KnowledgeApiError as error:
            return _handle(error)

    # -------------------------------------------------- #
    # Pattern (read-only)
    # -------------------------------------------------- #

    @router.get("/patterns/{pattern_id}")
    def get_pattern(pattern_id: str):
        try:
            return svc.get_pattern(pattern_id)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/patterns")
    def list_patterns(
        limit: Optional[int] = Query(default=None, ge=1, le=MAX_LIST_LIMIT),
    ):
        try:
            return svc.list_patterns(limit=limit)
        except KnowledgeApiError as error:
            return _handle(error)

    # -------------------------------------------------- #
    # Finding (read-only)
    # -------------------------------------------------- #

    @router.get("/findings/{finding_id}")
    def get_finding(finding_id: str):
        try:
            return svc.get_finding(finding_id)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/findings")
    def list_findings(
        limit: Optional[int] = Query(default=None, ge=1, le=MAX_LIST_LIMIT),
    ):
        try:
            return svc.list_findings(limit=limit)
        except KnowledgeApiError as error:
            return _handle(error)

    # -------------------------------------------------- #
    # Hypothesis
    # -------------------------------------------------- #

    @router.post("/hypotheses", status_code=201)
    def create_hypothesis(payload: HypothesisCreateRequest):
        try:
            data = payload.model_dump(mode="python")
            data["validation_criteria"] = _criteria_to_tuples(
                payload.validation_criteria
            )
            return svc.create_hypothesis(**data)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/hypotheses/{hypothesis_id}")
    def get_hypothesis(hypothesis_id: str):
        try:
            return svc.get_hypothesis(hypothesis_id)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/hypotheses")
    def list_hypotheses(
        limit: Optional[int] = Query(default=None, ge=1, le=MAX_LIST_LIMIT),
    ):
        try:
            return svc.list_hypotheses(limit=limit)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.post("/hypotheses/{hypothesis_id}/transition")
    def transition_hypothesis(
        hypothesis_id: str, payload: HypothesisTransitionRequest
    ):
        try:
            return svc.transition_hypothesis(
                hypothesis_id, payload.target_status
            )
        except KnowledgeApiError as error:
            return _handle(error)

    # -------------------------------------------------- #
    # Validation
    # -------------------------------------------------- #

    @router.post("/validations", status_code=201)
    def create_validation(payload: ValidationCreateRequest):
        try:
            data = payload.model_dump(mode="python")
            data["acceptance_criteria"] = _criteria_to_tuples(
                payload.acceptance_criteria
            )
            return svc.create_validation(**data)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/validations/{validation_id}")
    def get_validation(validation_id: str):
        try:
            return svc.get_validation(validation_id)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/validations")
    def list_validations(
        limit: Optional[int] = Query(default=None, ge=1, le=MAX_LIST_LIMIT),
    ):
        try:
            return svc.list_validations(limit=limit)
        except KnowledgeApiError as error:
            return _handle(error)

    # -------------------------------------------------- #
    # Human Review (APPEND-ONLY)
    # -------------------------------------------------- #

    @router.post("/human-reviews", status_code=201)
    def record_human_review(
        payload: HumanReviewCreateRequest,
        reviewer: str = Depends(require_operator_session),
    ):
        try:
            return svc.record_human_review(
                hypothesis_id=payload.hypothesis_id,
                validation_id=payload.validation_id,
                decision=payload.decision,
                reviewer=reviewer,
                notes=payload.notes,
                reviewed_at=payload.reviewed_at,
            )
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/human-reviews/{review_id}")
    def get_human_review(review_id: str):
        try:
            return svc.get_human_review(review_id)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/human-reviews")
    def list_human_reviews(
        hypothesisId: Optional[str] = Query(default=None, max_length=255),
        limit: Optional[int] = Query(default=None, ge=1, le=MAX_LIST_LIMIT),
    ):
        try:
            return svc.list_human_reviews(
                hypothesis_id=hypothesisId, limit=limit
            )
        except KnowledgeApiError as error:
            return _handle(error)

    # -------------------------------------------------- #
    # Promotion (ATOMIC)
    # -------------------------------------------------- #

    @router.post("/promotions", status_code=201)
    def promote(payload: PromotionCreateRequest):
        try:
            data = payload.model_dump(mode="python")
            return svc.promote(**data)
        except KnowledgeApiError as error:
            return _handle(error)

    # -------------------------------------------------- #
    # Validated Knowledge (read-only)
    # -------------------------------------------------- #

    @router.get("/validated-knowledge/{knowledge_id}")
    def get_validated_knowledge(knowledge_id: str):
        try:
            return svc.get_validated_knowledge(knowledge_id)
        except KnowledgeApiError as error:
            return _handle(error)

    @router.get("/validated-knowledge")
    def list_validated_knowledge(
        limit: Optional[int] = Query(default=None, ge=1, le=MAX_LIST_LIMIT),
    ):
        try:
            return svc.list_validated_knowledge(limit=limit)
        except KnowledgeApiError as error:
            return _handle(error)

    return router


router = create_knowledge_router()
