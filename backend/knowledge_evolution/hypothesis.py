"""D-8 Hypothesis: a testable proposition derived from Findings/Patterns.

A Hypothesis is explicitly provisional.  Truth level = ``HYPOTHESIS``.  It
does NOT become a strategy parameter and does NOT alter execution.

Hypothesis Authority = HYPOTHESIS_ONLY.

The lifecycle is explicit and deterministic.  A ``PROPOSED`` hypothesis is
never silently promoted to VALIDATED KNOWLEDGE; validation and human review are
mandatory.  Transition rules are enforced by :func:`advance_hypothesis`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional

from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_evolution._base import (
    MAX_D8_LIMITATIONS,
    MAX_D8_PATTERN_IDS,
    MAX_D8_TEXT,
    MAX_D8_WARNINGS,
    bound,
    dedupe,
    deterministic_id,
    order_annotations,
)
from backend.knowledge_evolution.authority import (
    HYPOTHESIS_AUTHORITY,
    KnowledgeEvolutionAuthority,
    mutation_interfaces,
)


class HypothesisStatus(str, Enum):
    """Explicit, deterministic hypothesis lifecycle states."""

    PROPOSED = "PROPOSED"
    READY_FOR_VALIDATION = "READY_FOR_VALIDATION"
    VALIDATING = "VALIDATING"
    SUPPORTED = "SUPPORTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


# Deterministic allowed transitions.  A PROPOSED hypothesis can only reach
# READY_FOR_VALIDATION (and only with explicit validation criteria); there is
# no direct PROPOSED -> SUPPORTED / VALIDATED edge.
_ALLOWED_TRANSITIONS: dict[HypothesisStatus, tuple[HypothesisStatus, ...]] = {
    HypothesisStatus.PROPOSED: (HypothesisStatus.READY_FOR_VALIDATION, HypothesisStatus.REJECTED),
    HypothesisStatus.READY_FOR_VALIDATION: (HypothesisStatus.VALIDATING, HypothesisStatus.REJECTED),
    HypothesisStatus.VALIDATING: (
        HypothesisStatus.SUPPORTED,
        HypothesisStatus.NOT_SUPPORTED,
        HypothesisStatus.INCONCLUSIVE,
        HypothesisStatus.REJECTED,
    ),
    HypothesisStatus.SUPPORTED: (HypothesisStatus.SUPERSEDED, HypothesisStatus.INCONCLUSIVE),
    HypothesisStatus.NOT_SUPPORTED: (HypothesisStatus.SUPERSEDED, HypothesisStatus.REJECTED),
    HypothesisStatus.INCONCLUSIVE: (HypothesisStatus.VALIDATING, HypothesisStatus.REJECTED, HypothesisStatus.SUPERSEDED),
    HypothesisStatus.REJECTED: (HypothesisStatus.SUPERSEDED,),
    HypothesisStatus.SUPERSEDED: (),
}


@dataclass(frozen=True)
class Hypothesis:
    """A testable, explicitly provisional proposition."""

    hypothesis_id: str
    statement: str
    derived_from_finding_ids: tuple[str, ...] = ()
    supporting_pattern_ids: tuple[str, ...] = ()
    expected_effect: str = ""
    validation_criteria: tuple[tuple[str, str], ...] = ()
    required_evidence: tuple[str, ...] = ()
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    limitations: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    strategy_mutation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesisId": self.hypothesis_id,
            "statement": self.statement,
            "derivedFromFindingIds": list(self.derived_from_finding_ids),
            "supportingPatternIds": list(self.supporting_pattern_ids),
            "expectedEffect": self.expected_effect,
            "validationCriteria": list(self.validation_criteria),
            "requiredEvidence": list(self.required_evidence),
            "status": self.status.value,
            "provenance": {
                "truthLevel": self.provenance.truth_level.value,
                "sourceReference": self.provenance.source_reference,
                "notes": self.provenance.notes,
            },
            "limitations": list(self.limitations),
            "warnings": list(self.warnings),
            "strategyMutation": self.strategy_mutation,
            "authority": HYPOTHESIS_AUTHORITY.value,
        }

    @property
    def truth_level(self) -> TruthLevel:
        return TruthLevel.HYPOTHESIS

    @property
    def authority(self) -> KnowledgeEvolutionAuthority:
        return HYPOTHESIS_AUTHORITY

    @property
    def operational_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def execution_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def strategy_mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    def mutation_interfaces(self) -> tuple[str, ...]:
        return mutation_interfaces(self)

    @property
    def has_validation_criteria(self) -> bool:
        return bool(self.validation_criteria)

    @property
    def is_provisional(self) -> bool:
        return self.status in {
            HypothesisStatus.PROPOSED,
            HypothesisStatus.READY_FOR_VALIDATION,
            HypothesisStatus.VALIDATING,
            HypothesisStatus.INCONCLUSIVE,
        }


def derive_hypothesis_id(
    statement: str,
    finding_ids: Iterable[str] = (),
    pattern_ids: Iterable[str] = (),
) -> str:
    return deterministic_id(
        "hypothesis",
        statement,
        tuple(sorted(dedupe(finding_ids))),
        tuple(sorted(dedupe(pattern_ids))),
    )


def propose_hypothesis(
    *,
    statement: str,
    derived_from_finding_ids: Iterable[str] = (),
    supporting_pattern_ids: Iterable[str] = (),
    expected_effect: str = "",
    validation_criteria: Iterable[tuple[str, str]] = (),
    required_evidence: Iterable[str] = (),
    provenance: Optional[ProvenanceRecord] = None,
    limitations: Iterable[str] = (),
    hypothesis_id: Optional[str] = None,
) -> Hypothesis:
    """Create a new hypothesis in ``PROPOSED`` state."""
    if not statement.strip():
        raise ValueError("hypothesis statement is required")
    derived = hypothesis_id or derive_hypothesis_id(
        statement, derived_from_finding_ids, supporting_pattern_ids
    )
    return Hypothesis(
        hypothesis_id=derived,
        statement=bound(statement, MAX_D8_TEXT),
        derived_from_finding_ids=order_annotations(derived_from_finding_ids)[:40],
        supporting_pattern_ids=order_annotations(supporting_pattern_ids)[:MAX_D8_PATTERN_IDS],
        expected_effect=bound(expected_effect, MAX_D8_TEXT),
        validation_criteria=tuple(sorted(tuple(v) for v in validation_criteria)),
        required_evidence=order_annotations(required_evidence)[:40],
        status=HypothesisStatus.PROPOSED,
        provenance=provenance or _default_provenance(derived),
        limitations=tuple(dedupe(bound(item, 300) for item in limitations))[:MAX_D8_LIMITATIONS],
    )


def advance_hypothesis(
    hypothesis: Hypothesis,
    target: HypothesisStatus,
    *,
    require_criteria_if_ready: bool = True,
) -> Hypothesis:
    """Deterministically transition a hypothesis to ``target``.

    The transition is only allowed if it is in :data:`_ALLOWED_TRANSITIONS`.
    A ``PROPOSED`` hypothesis cannot jump to ``SUPPORTED``/``VALIDATED`` and a
    ``READY_FOR_VALIDATION`` hypothesis must carry validation criteria before it
    is eligible.
    """
    if target is HypothesisStatus.READY_FOR_VALIDATION and require_criteria_if_ready:
        if not hypothesis.has_validation_criteria:
            raise ValueError(
                "validation criteria are required before a hypothesis can be "
                "READY_FOR_VALIDATION"
            )
    allowed = _ALLOWED_TRANSITIONS.get(hypothesis.status, ())
    if target not in allowed:
        raise ValueError(
            f"illegal hypothesis transition {hypothesis.status.value} -> {target.value}"
        )
    return Hypothesis(
        hypothesis_id=hypothesis.hypothesis_id,
        statement=hypothesis.statement,
        derived_from_finding_ids=hypothesis.derived_from_finding_ids,
        supporting_pattern_ids=hypothesis.supporting_pattern_ids,
        expected_effect=hypothesis.expected_effect,
        validation_criteria=hypothesis.validation_criteria,
        required_evidence=hypothesis.required_evidence,
        status=target,
        provenance=hypothesis.provenance,
        limitations=hypothesis.limitations,
        warnings=hypothesis.warnings,
        strategy_mutation=False,
    )


def _default_provenance(hypothesis_id: str) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.HYPOTHESIS,
        source_category=SourceCategory.CONTRACT,
        source_reference=f"HYPOTHESIS:{hypothesis_id}",
        notes="explicitly provisional hypothesis",
    )


__all__ = [
    "Hypothesis",
    "HypothesisStatus",
    "advance_hypothesis",
    "derive_hypothesis_id",
    "propose_hypothesis",
]
