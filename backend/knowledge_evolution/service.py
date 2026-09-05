"""Deterministic Knowledge Evolution service boundary (D-9C).

The service sits between the HTTP API and the durable
:class:`KnowledgeEvolutionStore`.  It:

  * validates API inputs into the typed D-8 domain contracts;
  * resolves persisted records through the store (the sole persistence
    authority);
  * invokes the existing deterministic D-8 domain functions;
  * enforces the Human Review + promotion boundaries;
  * maps domain / store failures into typed, safe API outcomes;
  * returns bounded, allowlisted projections.

PROVIDER_NEUTRAL - no LLM, no exchange, no ExecutionEngine, no runtime
mutation.  Never starts/stops the BOT or Loop, never changes Auto Trade,
strategy, Money Management or Canonical Specification.  The service is an
ANALYSIS / READ authority only; Human Review and Promotion are exposed guarded
by the D-9F store gate.

Authority ladder preserved:
    Investigation   = ANALYSIS_ONLY
    Pattern         = OBSERVATION_ONLY
    Finding         = OBSERVATION_ONLY
    Hypothesis      = HYPOTHESIS_ONLY
    Validation      = ANALYSIS_ONLY
    HumanReview     = HUMAN_REVIEW_REQUIRED
    ValidatedKnowledge = INFORMATION_ONLY
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional

from backend.knowledge_evolution.authority import (
    FINDING_AUTHORITY,
    HYPOTHESIS_AUTHORITY,
    INVESTIGATION_AUTHORITY,
    KNOWLEDGE_PROMOTION_AUTHORITY,
    PATTERN_AUTHORITY,
    VALIDATED_KNOWLEDGE_AUTHORITY,
    VALIDATION_AUTHORITY,
)
from backend.knowledge_evolution.human_review import (
    ReviewDecision,
    record_human_review,
)
from backend.knowledge_evolution.hypothesis import (
    HypothesisStatus,
    propose_hypothesis,
)
from backend.knowledge_evolution.investigation import (
    InvestigationFilter,
    make_investigation,
)
from backend.knowledge_evolution.knowledge import KnowledgePromotionError
from backend.knowledge_evolution.store import (
    DEFAULT_KNOWLEDGE_STORE_PATH,
    KnowledgeEvolutionStore,
    KnowledgeStoreError,
    KnowledgeStoreErrorCode,
)
from backend.knowledge_evolution.validation import (
    AcceptanceCriterion,
    Relation,
    ValidationEvidence,
    ValidationMethod,
    ValidationMetric,
    evaluate_validation,
)


# --------------------------------------------------------------------------- #
# Bounded list defaults
# --------------------------------------------------------------------------- #

DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 200


# --------------------------------------------------------------------------- #
# Typed service failure codes + HTTP mapping
# --------------------------------------------------------------------------- #


class KnowledgeApiErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    STALE_REVIEW = "STALE_REVIEW"
    ORPHAN_REFERENCE = "ORPHAN_REFERENCE"
    REVIEW_NOT_APPROVED = "REVIEW_NOT_APPROVED"
    PROMOTION_REJECTED = "PROMOTION_REJECTED"
    CORRUPT_RECORD = "CORRUPT_RECORD"
    SCHEMA_UNAVAILABLE = "SCHEMA_UNAVAILABLE"
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    AUTH_REQUIRED = "AUTH_REQUIRED"


class KnowledgeApiError(Exception):
    """A typed, safe API failure - never carries a raw sqlite/db path/secret."""

    def __init__(self, code: KnowledgeApiErrorCode, message: str, status_code: int):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(f"knowledge api: {message}")


# Maps the durable store failure codes to typed API outcomes.
_STORE_ERROR_MAP: dict[KnowledgeStoreErrorCode, tuple[KnowledgeApiErrorCode, int]] = {
    KnowledgeStoreErrorCode.STORE_UNAVAILABLE: (KnowledgeApiErrorCode.STORE_UNAVAILABLE, 503),
    KnowledgeStoreErrorCode.SCHEMA_MISMATCH: (KnowledgeApiErrorCode.SCHEMA_UNAVAILABLE, 503),
    KnowledgeStoreErrorCode.OPERATOR_ACTION_REQUIRED: (
        KnowledgeApiErrorCode.SCHEMA_UNAVAILABLE,
        503,
    ),
    KnowledgeStoreErrorCode.INPUT_INVALID: (KnowledgeApiErrorCode.INVALID_REQUEST, 400),
    KnowledgeStoreErrorCode.NOT_FOUND: (KnowledgeApiErrorCode.NOT_FOUND, 404),
    KnowledgeStoreErrorCode.DUPLICATE_CONFLICT: (
        KnowledgeApiErrorCode.DUPLICATE_CONFLICT,
        409,
    ),
    KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION: (
        KnowledgeApiErrorCode.ORPHAN_REFERENCE,
        409,
    ),
    KnowledgeStoreErrorCode.CORRUPT_RECORD: (KnowledgeApiErrorCode.CORRUPT_RECORD, 422),
    KnowledgeStoreErrorCode.INVALID_TRANSITION: (
        KnowledgeApiErrorCode.INVALID_TRANSITION,
        409,
    ),
    KnowledgeStoreErrorCode.REVIEW_NOT_APPROVED: (
        KnowledgeApiErrorCode.REVIEW_NOT_APPROVED,
        409,
    ),
    KnowledgeStoreErrorCode.REVIEW_VALIDATION_MISMATCH: (
        KnowledgeApiErrorCode.PROMOTION_REJECTED,
        409,
    ),
    KnowledgeStoreErrorCode.STALE_REVIEW: (KnowledgeApiErrorCode.STALE_REVIEW, 409),
    KnowledgeStoreErrorCode.PROMOTION_BLOCKED: (
        KnowledgeApiErrorCode.PROMOTION_REJECTED,
        409,
    ),
    KnowledgeStoreErrorCode.APPEND_ONLY_VIOLATION: (
        KnowledgeApiErrorCode.DUPLICATE_CONFLICT,
        409,
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_limit(limit: Optional[int]) -> int:
    if limit is None:
        return DEFAULT_LIST_LIMIT
    if not isinstance(limit, int) or limit < 1 or limit > MAX_LIST_LIMIT:
        raise KnowledgeApiError(
            KnowledgeApiErrorCode.INVALID_REQUEST,
            "limit must be a positive integer <= %d" % MAX_LIST_LIMIT,
            400,
        )
    return limit


def _list_envelope(items: Iterable[dict[str, Any]], authority: str) -> dict[str, Any]:
    materialized = list(items)
    return {
        "items": materialized,
        "count": len(materialized),
        "authority": authority,
    }


class KnowledgeEvolutionService:
    """Focused deterministic service boundary around ``KnowledgeEvolutionStore``.

    The store is the single durable knowledge authority.  The service never
    fabricates a second SQLite DB, a JSONL knowledge store or an in-memory
    authoritative registry, and it never touches the trading runtime.
    """

    def __init__(
        self,
        store: Optional[KnowledgeEvolutionStore] = None,
        *,
        store_path: Optional[Path] = None,
    ):
        self._store = store
        self._store_path = Path(store_path or DEFAULT_KNOWLEDGE_STORE_PATH)

    @property
    def store(self) -> KnowledgeEvolutionStore:
        """Lazily obtain the store.

        The store is the single durable knowledge authority.  It is only
        constructed on first use so no DB is created at import time (matching
        the application convention of avoiding import-time side effects).
        """
        if self._store is None:
            try:
                self._store = KnowledgeEvolutionStore(self._store_path)
            except KnowledgeStoreError as error:
                self._raise_store(error)
        return self._store

    # ------------------------------------------------------------------ #
    # Investigation
    # ------------------------------------------------------------------ #

    def create_investigation(
        self,
        *,
        question: str,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
        started_from: Optional[str] = None,
        started_to: Optional[str] = None,
        trace_ids: Iterable[str] = (),
        decision_ids: Iterable[str] = (),
        trade_ids: Iterable[str] = (),
        experience_types: Iterable[str] = (),
        reason_codes: Iterable[str] = (),
        outcomes: Iterable[str] = (),
        completeness: Iterable[str] = (),
        drift_statuses: Iterable[str] = (),
        limit: int = 100,
        investigation_id: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            criterion = InvestigationFilter(
                symbol=symbol,
                mode=mode,
                started_from=started_from,
                started_to=started_to,
                trace_ids=tuple(trace_ids),
                decision_ids=tuple(decision_ids),
                trade_ids=tuple(trade_ids),
                experience_types=self._experience_types(experience_types),
                reason_codes=tuple(reason_codes),
                outcomes=tuple(outcomes),
                completeness=self._completeness(completeness),
                drift_statuses=self._drift_statuses(drift_statuses),
            )
            request = make_investigation(
                question=question,
                criterion=criterion,
                limit=limit,
                investigation_id=investigation_id,
            )
        except (ValueError, TypeError) as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.INVALID_REQUEST,
                "investigation is invalid: %s" % error,
                400,
            ) from error
        try:
            self.store.save_investigation(request)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return self._get_investigation(request.investigation_id)

    def _get_investigation(self, investigation_id: str) -> dict[str, Any]:
        try:
            request = self.store.get_investigation(investigation_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if request is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND,
                "investigation not found",
                404,
            )
        return request.to_dict()

    def get_investigation(self, investigation_id: str) -> dict[str, Any]:
        return self._get_investigation(investigation_id)

    def list_investigations(
        self, *, limit: Optional[int] = None
    ) -> dict[str, Any]:
        try:
            items = self.store.list_investigations(limit=_bounded_limit(limit))
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return _list_envelope(
            (item.to_dict() for item in items), INVESTIGATION_AUTHORITY.value
        )

    # ------------------------------------------------------------------ #
    # Pattern / Finding (read-only)
    # ------------------------------------------------------------------ #

    def get_pattern(self, pattern_id: str) -> dict[str, Any]:
        try:
            pattern = self.store.get_pattern(pattern_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if pattern is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "pattern not found", 404
            )
        return pattern.to_dict()

    def list_patterns(self, *, limit: Optional[int] = None) -> dict[str, Any]:
        try:
            items = self.store.list_patterns(limit=_bounded_limit(limit))
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return _list_envelope(
            (item.to_dict() for item in items), PATTERN_AUTHORITY.value
        )

    def get_finding(self, finding_id: str) -> dict[str, Any]:
        try:
            finding = self.store.get_finding(finding_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if finding is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "finding not found", 404
            )
        return finding.to_dict()

    def list_findings(self, *, limit: Optional[int] = None) -> dict[str, Any]:
        try:
            items = self.store.list_findings(limit=_bounded_limit(limit))
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return _list_envelope(
            (item.to_dict() for item in items), FINDING_AUTHORITY.value
        )

    # ------------------------------------------------------------------ #
    # Hypothesis
    # ------------------------------------------------------------------ #

    def create_hypothesis(
        self,
        *,
        statement: str,
        derived_from_finding_ids: Iterable[str] = (),
        supporting_pattern_ids: Iterable[str] = (),
        expected_effect: str = "",
        validation_criteria: Iterable[tuple[str, str, float]] = (),
        required_evidence: Iterable[str] = (),
        limitations: Iterable[str] = (),
        hypothesis_id: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            hypothesis = propose_hypothesis(
                statement=statement,
                derived_from_finding_ids=tuple(derived_from_finding_ids),
                supporting_pattern_ids=tuple(supporting_pattern_ids),
                expected_effect=expected_effect,
                validation_criteria=tuple(tuple(c) for c in validation_criteria),
                required_evidence=tuple(required_evidence),
                limitations=tuple(limitations),
                hypothesis_id=hypothesis_id,
            )
        except (ValueError, TypeError) as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.INVALID_REQUEST,
                "hypothesis is invalid: %s" % error,
                400,
            ) from error
        try:
            self.store.create_hypothesis(hypothesis)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return self._get_hypothesis(hypothesis.hypothesis_id)

    def _get_hypothesis(self, hypothesis_id: str) -> dict[str, Any]:
        try:
            hypothesis = self.store.get_hypothesis(hypothesis_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if hypothesis is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "hypothesis not found", 404
            )
        return hypothesis.to_dict()

    def get_hypothesis(self, hypothesis_id: str) -> dict[str, Any]:
        return self._get_hypothesis(hypothesis_id)

    def list_hypotheses(self, *, limit: Optional[int] = None) -> dict[str, Any]:
        try:
            items = self.store.list_hypotheses(limit=_bounded_limit(limit))
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return _list_envelope(
            (item.to_dict() for item in items), HYPOTHESIS_AUTHORITY.value
        )

    def transition_hypothesis(
        self, hypothesis_id: str, target_status: str
    ) -> dict[str, Any]:
        try:
            target = HypothesisStatus(target_status)
        except ValueError as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.INVALID_REQUEST,
                "target status is invalid",
                400,
            ) from error
        try:
            advanced = self.store.transition_hypothesis(hypothesis_id, target)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return advanced.to_dict()

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def create_validation(
        self,
        *,
        hypothesis_id: str,
        method: str,
        sample_size: int,
        support_count: int,
        counterexample_count: int,
        dataset_references: Iterable[str] = (),
        time_range: Optional[str] = None,
        acceptance_criteria: Iterable[tuple[str, str, float]] = (),
        limitations: Iterable[str] = (),
        min_sample_size: int = 2,
    ) -> dict[str, Any]:
        try:
            hypothesis = self.store.get_hypothesis(hypothesis_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if hypothesis is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "hypothesis not found", 404
            )
        try:
            method_enum = ValidationMethod(method)
        except ValueError as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.INVALID_REQUEST, "validation method is invalid", 400
            ) from error
        try:
            criteria = tuple(
                AcceptanceCriterion(
                    metric=ValidationMetric(metric),
                    relation=Relation(relation),
                    threshold=float(threshold),
                )
                for metric, relation, threshold in acceptance_criteria
            )
        except (ValueError, TypeError) as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.INVALID_REQUEST,
                "acceptance criterion is invalid",
                400,
            ) from error
        evidence = ValidationEvidence(
            sample_size=int(sample_size),
            support_count=int(support_count),
            counterexample_count=int(counterexample_count),
            method=method_enum,
            dataset_references=tuple(dataset_references),
            time_range=time_range,
        )
        try:
            validation = evaluate_validation(
                hypothesis,
                criteria=criteria,
                evidence=evidence,
                limitations=tuple(limitations),
                min_sample_size=min_sample_size,
            )
        except (ValueError, TypeError) as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.INVALID_REQUEST,
                "validation is invalid: %s" % error,
                400,
            ) from error
        try:
            self.store.save_validation(validation)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return self._get_validation(validation.validation_id)

    def _get_validation(self, validation_id: str) -> dict[str, Any]:
        try:
            validation = self.store.get_validation(validation_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if validation is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "validation not found", 404
            )
        return validation.to_dict()

    def get_validation(self, validation_id: str) -> dict[str, Any]:
        return self._get_validation(validation_id)

    def list_validations(self, *, limit: Optional[int] = None) -> dict[str, Any]:
        try:
            items = self.store.list_validations(limit=_bounded_limit(limit))
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return _list_envelope(
            (item.to_dict() for item in items), VALIDATION_AUTHORITY.value
        )

    # ------------------------------------------------------------------ #
    # Human Review (APPEND-ONLY)
    # ------------------------------------------------------------------ #

    def record_human_review(
        self,
        *,
        hypothesis_id: str,
        validation_id: str,
        decision: str,
        reviewer: str,
        notes: str = "",
        reviewed_at: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            decision_enum = ReviewDecision(decision)
        except ValueError as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.INVALID_REQUEST, "review decision is invalid", 400
            ) from error
        try:
            hypothesis = self.store.get_hypothesis(hypothesis_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if hypothesis is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "hypothesis not found", 404
            )
        try:
            persisted_validation = self.store.get_validation(validation_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if persisted_validation is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "validation not found", 404
            )
        if persisted_validation.hypothesis_id != hypothesis_id:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.ORPHAN_REFERENCE,
                "validation does not belong to hypothesis",
                409,
            )
        try:
            review = record_human_review(
                hypothesis_id=hypothesis_id,
                decision=decision_enum,
                reviewer=reviewer,
                reviewed_at=reviewed_at or _now(),
                notes=notes,
            )
        except (ValueError, TypeError) as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.INVALID_REQUEST,
                "human review is invalid: %s" % error,
                400,
            ) from error
        try:
            review_id = self.store.append_human_review(
                review, validation=persisted_validation
            )
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return self._get_human_review(review_id)

    def _get_human_review(self, review_id: str) -> dict[str, Any]:
        try:
            projection = self.store.get_human_review_projection(review_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if projection is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "human review not found", 404
            )
        return projection

    def get_human_review(self, review_id: str) -> dict[str, Any]:
        return self._get_human_review(review_id)

    def list_human_reviews(
        self,
        hypothesis_id: Optional[str] = None,
        *,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        try:
            items = self.store.list_human_reviews(
                hypothesis_id=hypothesis_id, limit=_bounded_limit(limit)
            )
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return _list_envelope(items, KNOWLEDGE_PROMOTION_AUTHORITY.value)

    # ------------------------------------------------------------------ #
    # Promotion (ATOMIC) + Validated Knowledge
    # ------------------------------------------------------------------ #

    def promote(
        self,
        *,
        hypothesis_id: str,
        validation_id: str,
        review_id: str,
        version: str = "1.0",
        scope: str = "",
        limitations: Iterable[str] = (),
    ) -> dict[str, Any]:
        try:
            promoted = self.store.promote_to_validated_knowledge(
                hypothesis_id=hypothesis_id,
                validation_id=validation_id,
                review_id=review_id,
                version=version,
                created_at=_now(),
                scope=scope,
                limitations=tuple(limitations),
            )
        except KnowledgeStoreError as error:
            self._raise_store(error)
        except KnowledgePromotionError as error:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.PROMOTION_REJECTED,
                str(error),
                409,
            ) from error
        return promoted.to_dict()

    def _get_validated_knowledge(self, knowledge_id: str) -> dict[str, Any]:
        try:
            item = self.store.get_validated_knowledge(knowledge_id)
        except KnowledgeStoreError as error:
            self._raise_store(error)
        if item is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.NOT_FOUND, "validated knowledge not found", 404
            )
        return item.to_dict()

    def get_validated_knowledge(self, knowledge_id: str) -> dict[str, Any]:
        return self._get_validated_knowledge(knowledge_id)

    def list_validated_knowledge(
        self, *, limit: Optional[int] = None
    ) -> dict[str, Any]:
        try:
            items = self.store.list_validated_knowledge(limit=_bounded_limit(limit))
        except KnowledgeStoreError as error:
            self._raise_store(error)
        return _list_envelope(
            (item.to_dict() for item in items), VALIDATED_KNOWLEDGE_AUTHORITY.value
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _raise_store(self, error: KnowledgeStoreError) -> None:
        mapped = _STORE_ERROR_MAP.get(error.code)
        if mapped is None:
            raise KnowledgeApiError(
                KnowledgeApiErrorCode.STORE_UNAVAILABLE,
                "knowledge store unavailable",
                503,
            ) from error
        code, status = mapped
        raise KnowledgeApiError(code, error.safe_message, status) from error

    def _experience_types(self, values: Iterable[str]):
        from backend.knowledge_evolution.experience import ExperienceType

        return tuple(ExperienceType(v) for v in values)

    def _completeness(self, values: Iterable[str]):
        from backend.runtime.unified_trace import TraceCompleteness

        return tuple(TraceCompleteness(v) for v in values)

    def _drift_statuses(self, values: Iterable[str]):
        from backend.knowledge_core.drift import DriftStatus

        return tuple(DriftStatus(v) for v in values)
