"""D-8 Validation: deterministic evaluation of a Hypothesis against evidence.

Validation Authority = ANALYSIS_ONLY.

Acceptance criteria MUST be provided BEFORE the result is interpreted.  This
module never runs a backtest, replay, or PAPER engine: it only evaluates a
typed, caller-supplied :class:`ValidationEvidence` set against explicit
criteria.  If no executed validation evidence exists, the result is
``UNAVAILABLE`` (or ``INCONCLUSIVE`` when evidence is too small) - never a
fabricated pass/fail.

Result semantics are non-binary:

    SUPPORTED      evidence meets every acceptance criterion
    NOT_SUPPORTED  a criterion is violated (e.g. counterexamples exceed bound)
    INCONCLUSIVE   evidence is insufficient to decide
    UNAVAILABLE    required evidence / source cannot be obtained
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Optional

from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_evolution._base import (
    MAX_D8_LIMITATIONS,
    MAX_D8_WARNINGS,
    bound,
    dedupe,
    deterministic_id,
)
from backend.knowledge_evolution.authority import (
    KnowledgeEvolutionAuthority,
    VALIDATION_AUTHORITY,
    mutation_interfaces,
)
from backend.knowledge_evolution.hypothesis import Hypothesis
from backend.runtime.unified_trace import Provenance


class ValidationResult(str, Enum):
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNAVAILABLE = "UNAVAILABLE"


class ValidationMethod(str, Enum):
    """The methodology the caller is using to produce evidence.

    Only methods that plausibly exist in the platform may be named; nothing is
    invented here.  ``CONTRACT_ONLY`` marks the evidence-ingestion boundary
    where no executed engine currently exists.
    """

    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    BACKTEST = "BACKTEST"
    PAPER_RESULTS = "PAPER_RESULTS"
    COMPARISON_COHORTS = "COMPARISON_COHORTS"
    COUNTEREXAMPLE_ANALYSIS = "COUNTEREXAMPLE_ANALYSIS"
    CONTRACT_ONLY = "CONTRACT_ONLY"
    UNAVAILABLE = "UNAVAILABLE"


class ValidationMetric(str, Enum):
    SAMPLE_SIZE = "SAMPLE_SIZE"
    SUPPORT_COUNT = "SUPPORT_COUNT"
    COUNTEREXAMPLE_COUNT = "COUNTEREXAMPLE_COUNT"
    SUPPORT_RATIO = "SUPPORT_RATIO"


class Relation(str, Enum):
    AT_LEAST = "AT_LEAST"
    AT_MOST = "AT_MOST"


@dataclass(frozen=True)
class AcceptanceCriterion:
    """An explicit acceptance bound that must hold BEFORE interpreting a result."""

    metric: ValidationMetric
    relation: Relation
    threshold: float

    def satisfied(self, metrics: dict[str, float]) -> bool:
        value = metrics[self.metric.value]
        if self.relation is Relation.AT_LEAST:
            return value >= self.threshold
        return value <= self.threshold

    def to_tuple(self) -> tuple[str, str, float]:
        return (self.metric.value, self.relation.value, self.threshold)


@dataclass(frozen=True)
class ValidationEvidence:
    """Caller-supplied, typed evidence statistics (never fabricated internally).

    ``source_kind`` is the real provenance of the counts.  The module treats
    these as opaque input; it does not generate them.
    """

    sample_size: int
    support_count: int
    counterexample_count: int
    method: ValidationMethod
    dataset_references: tuple[str, ...] = ()
    time_range: Optional[str] = None
    source_references: tuple[Provenance, ...] = ()
    available: bool = True

    def metrics(self) -> dict[str, float]:
        ratio = 0.0
        if self.sample_size > 0:
            ratio = self.support_count / self.sample_size
        return {
            ValidationMetric.SAMPLE_SIZE.value: float(self.sample_size),
            ValidationMetric.SUPPORT_COUNT.value: float(self.support_count),
            ValidationMetric.COUNTEREXAMPLE_COUNT.value: float(self.counterexample_count),
            ValidationMetric.SUPPORT_RATIO.value: ratio,
        }


@dataclass(frozen=True)
class Validation:
    """A deterministic validation of a Hypothesis against explicit criteria."""

    validation_id: str
    hypothesis_id: str
    method: ValidationMethod
    evidence: ValidationEvidence
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    metrics: dict[str, float]
    sample_size: int
    support_count: int
    counterexample_count: int
    result: ValidationResult
    provenance: ProvenanceRecord
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "validationId": self.validation_id,
            "hypothesisId": self.hypothesis_id,
            "method": self.method.value,
            "evidence": {
                "sampleSize": self.evidence.sample_size,
                "supportCount": self.evidence.support_count,
                "counterexampleCount": self.evidence.counterexample_count,
                "datasetReferences": list(self.evidence.dataset_references),
                "timeRange": self.evidence.time_range,
                "available": self.evidence.available,
            },
            "acceptanceCriteria": [c.to_tuple() for c in self.acceptance_criteria],
            "metrics": self.metrics,
            "result": self.result.value,
            "provenance": {
                "truthLevel": self.provenance.truth_level.value,
                "sourceReference": self.provenance.source_reference,
                "notes": self.provenance.notes,
            },
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "authority": VALIDATION_AUTHORITY.value,
        }

    @property
    def authority(self) -> KnowledgeEvolutionAuthority:
        return VALIDATION_AUTHORITY

    @property
    def operational_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    def mutation_interfaces(self) -> tuple[str, ...]:
        return mutation_interfaces(self)

    @property
    def criteria_present(self) -> bool:
        return bool(self.acceptance_criteria)


def derive_validation_id(
    hypothesis_id: str,
    method: ValidationMethod,
    criteria: Iterable[AcceptanceCriterion],
    dataset_references: Iterable[str] = (),
) -> str:
    return deterministic_id(
        "validation",
        hypothesis_id,
        method.value,
        tuple((c.to_tuple()) for c in criteria),
        tuple(sorted(dedupe(dataset_references))),
    )


def evaluate_validation(
    hypothesis: Hypothesis,
    *,
    criteria: Iterable[AcceptanceCriterion],
    evidence: ValidationEvidence,
    provenance: Optional[ProvenanceRecord] = None,
    limitations: Iterable[str] = (),
    min_sample_size: int = 2,
) -> Validation:
    """Deterministically evaluate ``hypothesis`` against ``evidence``.

    Acceptance criteria are required BEFORE the result is computed; omitting
    them is an error (never a latent pass/fail).  The result is one of
    SUPPORTED / NOT_SUPPORTED / INCONCLUSIVE / UNAVAILABLE.
    """
    criteria_tuple = tuple(criteria)
    if not criteria_tuple:
        raise ValueError("acceptance criteria are required before evaluation")
    if not isinstance(hypothesis, Hypothesis):
        raise TypeError("typed Hypothesis required")
    if not isinstance(evidence, ValidationEvidence):
        raise TypeError("typed ValidationEvidence required")

    hypothesis_id = hypothesis.hypothesis_id
    validation_id = derive_validation_id(
        hypothesis_id,
        evidence.method,
        criteria_tuple,
        evidence.dataset_references,
    )

    warnings: list[str] = []
    if not evidence.available or evidence.method is ValidationMethod.UNAVAILABLE:
        result = ValidationResult.UNAVAILABLE
        warnings.append("VALIDATION_EVIDENCE_UNAVAILABLE")
    elif evidence.sample_size < min_sample_size:
        result = ValidationResult.INCONCLUSIVE
        warnings.append("INSUFFICIENT_EVIDENCE")
    elif evidence.method is ValidationMethod.CONTRACT_ONLY:
        result = _evaluate_criteria(criteria_tuple, evidence)
        warnings.append("CONTRACT_ONLY_EVIDENCE_BOUNDARY")
    else:
        result = _evaluate_criteria(criteria_tuple, evidence)

    if evidence.method is ValidationMethod.CONTRACT_ONLY and result is ValidationResult.SUPPORTED:
        warnings.append("REQUIRES_EXECUTED_EVIDENCE_CONFIRMATION")

    return Validation(
        validation_id=validation_id,
        hypothesis_id=hypothesis_id,
        method=evidence.method,
        evidence=evidence,
        acceptance_criteria=criteria_tuple,
        metrics=evidence.metrics(),
        sample_size=evidence.sample_size,
        support_count=evidence.support_count,
        counterexample_count=evidence.counterexample_count,
        result=result,
        provenance=provenance or _default_provenance(validation_id),
        limitations=tuple(dedupe(bound(item, 300) for item in limitations))[:MAX_D8_LIMITATIONS],
        warnings=tuple(dedupe(warnings))[:MAX_D8_WARNINGS],
    )


def _evaluate_criteria(
    criteria: tuple[AcceptanceCriterion, ...],
    evidence: ValidationEvidence,
) -> ValidationResult:
    metrics = evidence.metrics()
    for criterion in criteria:
        if not criterion.satisfied(metrics):
            if criterion.metric is ValidationMetric.COUNTEREXAMPLE_COUNT and criterion.relation is Relation.AT_MOST:
                return ValidationResult.NOT_SUPPORTED
            if criterion.metric is ValidationMetric.SUPPORT_RATIO and criterion.relation is Relation.AT_LEAST:
                return ValidationResult.NOT_SUPPORTED
            if criterion.metric is ValidationMetric.SUPPORT_COUNT and criterion.relation is Relation.AT_LEAST:
                return ValidationResult.NOT_SUPPORTED
            if criterion.metric is ValidationMetric.SAMPLE_SIZE and criterion.relation is Relation.AT_LEAST:
                return ValidationResult.INCONCLUSIVE
            return ValidationResult.NOT_SUPPORTED
    return ValidationResult.SUPPORTED


def _default_provenance(validation_id: str) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.OBSERVATION_FINDING,
        source_category=SourceCategory.CONTRACT,
        source_reference=f"VALIDATION:{validation_id}",
        notes="deterministic validation evaluation",
    )


__all__ = [
    "AcceptanceCriterion",
    "Relation",
    "Validation",
    "ValidationEvidence",
    "ValidationMetric",
    "ValidationMethod",
    "ValidationResult",
    "derive_validation_id",
    "evaluate_validation",
]
