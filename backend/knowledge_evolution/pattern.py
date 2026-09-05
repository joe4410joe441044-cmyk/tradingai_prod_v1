"""D-8 Pattern: a repeatable deterministic relationship observed in evidence.

A Pattern is an OBSERVATION.  It states association/co-occurrence, never
causation.  The mandatory rule is explicit and enforced by the contract:

    correlation/co-occurrence is NOT causation.

``causal_claim`` is always ``False`` on a Pattern.  Unless a separate validation
methodology actually supports causality, no causal statement may be produced.

Pattern Authority = OBSERVATION_ONLY.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Optional

from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_evolution._base import (
    MAX_D8_COUNTEREVIDENCE_IDS,
    MAX_D8_EVIDENCE_IDS,
    MAX_D8_FINDING_IDS,
    MAX_D8_SOURCE_REFERENCES,
    MAX_D8_WARNINGS,
    bound,
    dedupe,
    deterministic_id,
)
from backend.knowledge_evolution.authority import (
    KnowledgeEvolutionAuthority,
    PATTERN_AUTHORITY,
    mutation_interfaces,
)
from backend.knowledge_evolution.experience import ExperienceRecord
from backend.runtime.unified_trace import Provenance


class PatternType(str, Enum):
    """Categorization of the observed relationship.

    These are generic association categories; concrete trading patterns are
    never hard-coded here.
    """

    CO_OCCURRENCE = "CO_OCCURRENCE"
    FREQUENCY = "FREQUENCY"
    DISTRIBUTION = "DISTRIBUTION"
    GENERIC = "GENERIC"


class EvidenceStrength(str, Enum):
    """Categorical evidence strength (preferred over invented numeric confidence).

    Deterministically derived from support/sample/counterexample counts.
    """

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"
    INSUFFICIENT = "INSUFFICIENT"


class PatternStatus(str, Enum):
    """Lifecycle status of a Pattern (an observation, not a rule)."""

    OBSERVED = "OBSERVED"
    REPEATED = "REPEATED"
    SINGLETON = "SINGLETON"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class CooccurrenceCounts:
    """Deterministic support/sample/counterexample counts for one relationship."""

    support_count: int
    sample_size: int
    counterexample_count: int
    complement_count: int

    @property
    def has_repeated_support(self) -> bool:
        return self.sample_size >= 2 and self.support_count >= 2

    @property
    def support_ratio(self) -> float:
        if self.sample_size <= 0:
            return 0.0
        return self.support_count / self.sample_size


def count_cooccurrence(
    evidence: Iterable[ExperienceRecord],
    condition: Callable[[ExperienceRecord], bool],
    outcome: Callable[[ExperienceRecord], bool],
) -> tuple[CooccurrenceCounts, tuple[str, ...], tuple[str, ...]]:
    """Count support / counterexample / complement for a relationship.

    Returns ``(counts, supporting_ids, counterexample_ids)``.  Pure and
    non-mutating; ``condition`` and ``outcome`` are the only analysis inputs and
    both must be deterministic predicates.
    """
    support_ids: list[str] = []
    counter_ids: list[str] = []
    complement = 0
    for item in evidence:
        c = bool(condition(item))
        o = bool(outcome(item))
        if c and o:
            support_ids.append(item.experience_id)
        elif c and not o:
            counter_ids.append(item.experience_id)
        elif o and not c:
            complement += 1
    counts = CooccurrenceCounts(
        support_count=len(support_ids),
        sample_size=len(support_ids) + len(counter_ids),
        counterexample_count=len(counter_ids),
        complement_count=complement,
    )
    return counts, tuple(support_ids), tuple(counter_ids)


def resolve_evidence_strength(
    support_count: int,
    sample_size: int,
    counterexample_count: int,
) -> EvidenceStrength:
    """Deterministically map counts to a categorical evidence strength.

    A single observation is never given ``STRONG``/``MODERATE`` weight; when the
    sample is too small the strength is explicitly ``INSUFFICIENT``.
    """
    if sample_size <= 1 or support_count <= 0:
        return EvidenceStrength.INSUFFICIENT
    if sample_size < 5:
        return EvidenceStrength.WEAK
    ratio = support_count / sample_size
    if counterexample_count <= 0:
        return EvidenceStrength.STRONG
    if ratio >= 0.8:
        return EvidenceStrength.STRONG
    if ratio >= 0.6:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.WEAK


@dataclass(frozen=True)
class Pattern:
    """A typed, repeatable, observation-only relationship in evidence.

    ``causal_claim`` is always ``False``.  A Pattern never asserts that a
    condition caused an outcome unless a separate validation methodology
    actually supports it.
    """

    pattern_id: str
    pattern_type: PatternType
    description: str
    support_count: int
    sample_size: int
    counterexample_count: int
    supporting_experience_ids: tuple[str, ...]
    counterexample_experience_ids: tuple[str, ...]
    source_references: tuple[Provenance, ...] = ()
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    evidence_strength: EvidenceStrength = EvidenceStrength.INSUFFICIENT
    status: PatternStatus = PatternStatus.OBSERVED
    causal_claim: bool = False
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "patternId": self.pattern_id,
            "patternType": self.pattern_type.value,
            "description": self.description,
            "supportCount": self.support_count,
            "sampleSize": self.sample_size,
            "counterexampleCount": self.counterexample_count,
            "supportingExperienceIds": list(self.supporting_experience_ids),
            "counterexampleExperienceIds": list(self.counterexample_experience_ids),
            "sourceReferences": [p.to_dict() for p in self.source_references],
            "provenance": {
                "truthLevel": self.provenance.truth_level.value,
                "sourceReference": self.provenance.source_reference,
                "notes": self.provenance.notes,
            },
            "evidenceStrength": self.evidence_strength.value,
            "status": self.status.value,
            "causalClaim": self.causal_claim,
            "warnings": list(self.warnings),
            "authority": PATTERN_AUTHORITY.value,
        }

    @property
    def truth_level(self) -> TruthLevel:
        return TruthLevel.OBSERVATION_FINDING

    @property
    def authority(self) -> KnowledgeEvolutionAuthority:
        return PATTERN_AUTHORITY

    @property
    def operational_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def is_repeated(self) -> bool:
        return self.sample_size >= 2 and self.support_count >= 2

    def mutation_interfaces(self) -> tuple[str, ...]:
        return mutation_interfaces(self)

    @property
    def asserts_causation(self) -> bool:
        return self.causal_claim


def derive_pattern_id(
    *,
    pattern_type: PatternType,
    description: str,
    supporting_ids: Iterable[str],
    counter_ids: Iterable[str],
) -> str:
    return deterministic_id(
        "pattern",
        pattern_type.value,
        description,
        tuple(sorted(dedupe(supporting_ids))),
        tuple(sorted(dedupe(counter_ids))),
    )


def build_pattern(
    experiences: Iterable[ExperienceRecord],
    *,
    pattern_type: PatternType,
    description: str,
    condition: Callable[[ExperienceRecord], bool],
    outcome: Callable[[ExperienceRecord], bool],
    provenance: Optional[ProvenanceRecord] = None,
    pattern_id: Optional[str] = None,
) -> Pattern:
    """Deterministically build an observation-only Pattern from evidence.

    The relationship is counted from explicit ``condition``/``outcome``
    predicates over the provided experiences.  ``causal_claim`` is always
    ``False``; correlation is never presented as causation.
    """
    if not description.strip():
        raise ValueError("pattern description is required")
    counts, support_ids, counter_ids = count_cooccurrence(
        experiences, condition, outcome
    )
    strength = resolve_evidence_strength(
        counts.support_count, counts.sample_size, counts.counterexample_count
    )
    status = _status_for(counts)
    derived = pattern_id or derive_pattern_id(
        pattern_type=pattern_type,
        description=description,
        supporting_ids=support_ids,
        counter_ids=counter_ids,
    )
    warnings: list[str] = []
    if counts.sample_size <= 1 and counts.support_count >= 1:
        warnings.append("SINGLE_EVENT_NOT_REPEATED_PATTERN")
    if status is PatternStatus.INCONCLUSIVE:
        warnings.append("INCONCLUSIVE")
    if len(support_ids) > MAX_D8_EVIDENCE_IDS:
        warnings.append("SUPPORTING_EVIDENCE_TRUNCATED")
    if len(counter_ids) > MAX_D8_COUNTEREVIDENCE_IDS:
        warnings.append("COUNTEREXAMPLE_EVIDENCE_TRUNCATED")
    return Pattern(
        pattern_id=derived,
        pattern_type=pattern_type,
        description=bound(description, 512),
        support_count=counts.support_count,
        sample_size=counts.sample_size,
        counterexample_count=counts.counterexample_count,
        supporting_experience_ids=tuple(support_ids)[:MAX_D8_EVIDENCE_IDS],
        counterexample_experience_ids=tuple(counter_ids)[:MAX_D8_COUNTEREVIDENCE_IDS],
        source_references=_collect_source_references(experiences),
        provenance=provenance or _default_provenance(derived),
        evidence_strength=strength,
        status=status,
        causal_claim=False,
        warnings=tuple(dedupe(warnings))[:MAX_D8_WARNINGS],
    )


def _status_for(counts: CooccurrenceCounts) -> PatternStatus:
    if counts.sample_size <= 1:
        return PatternStatus.SINGLETON
    if counts.sample_size < counts.support_count:
        return PatternStatus.INCONCLUSIVE
    if counts.has_repeated_support:
        return PatternStatus.REPEATED
    return PatternStatus.SINGLETON


def _collect_source_references(
    experiences: Iterable[ExperienceRecord],
) -> tuple[Provenance, ...]:
    seen: dict[tuple[str, str, str], Provenance] = {}
    for item in experiences:
        for reference in item.source_references:
            key = (str(reference.source_subsystem), reference.source_type, reference.source_identifier)
            if key not in seen:
                seen[key] = reference
    return tuple(sorted(
        seen.values(),
        key=lambda p: (str(p.source_subsystem), p.source_type, p.source_identifier),
    ))[:MAX_D8_SOURCE_REFERENCES]


def _default_provenance(pattern_id: str) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.OBSERVATION_FINDING,
        source_category=SourceCategory.CONTRACT,
        source_reference=f"PATTERN:{pattern_id}",
        notes="deterministic co-occurrence observation",
    )


__all__ = [
    "CooccurrenceCounts",
    "EvidenceStrength",
    "Pattern",
    "PatternStatus",
    "PatternType",
    "build_pattern",
    "count_cooccurrence",
    "derive_pattern_id",
    "resolve_evidence_strength",
]
