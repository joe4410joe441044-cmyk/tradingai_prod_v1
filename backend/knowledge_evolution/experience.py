"""D-8 Experience Memory: deterministic historical evidence records.

Experience Memory is EVIDENCE_ONLY (``KnowledgeEvolutionAuthority.EVIDENCE_ONLY``).
It represents historical evidence about what TradingAI actually observed,
decided and did.  It is a *derived, rebuildable index* over the existing
authoritative evidence, not a second source of truth:

* It REUSES the authoritative D-5 trace (``UnifiedTradingTrace`` /
  ``TradingTraceStore``) and the authoritative identity fields
  (``traceId``/``decisionId``/``orderId``/``fillId``/``positionId``/``tradeId``).
* It REUSES D-1 ``ProvenanceRecord``, ``TruthLevel`` and D-5
  ``TraceReasonCode``/``Provenance``/``TraceCompleteness``.
* It never fabricates IDs: if no authoritative trace/identity exists the record
  carries ``None`` and its deterministic D-8 ID is derived only from the stable
  evidence that does exist.

Authority contract:

    Experience Memory Authority      = EVIDENCE_ONLY
    Operational Authority             = NONE
    Execution Authority               = NONE
    Strategy / MM / Canonical Mutation = NONE
    Config / governance authority     = NONE

A repeated observation inside Experience Memory is NOT automatically canonical
truth and NOT automatically Validated Knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any, Mapping, Optional

from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_core.drift import DriftAssessment
from backend.knowledge_evolution._base import (
    MAX_D8_REASON_CODES,
    MAX_D8_SOURCE_REFERENCES,
    MAX_D8_SUMMARY,
    MAX_D8_TAGS,
    MAX_D8_TEXT,
    MAX_D8_WARNINGS,
    bound,
    clean_tags,
    dedupe,
    deterministic_id,
)
from backend.knowledge_evolution.authority import (
    EXPERIENCE_MEMORY_AUTHORITY,
    KnowledgeEvolutionAuthority,
    mutation_interfaces,
)
from backend.runtime.unified_trace import (
    Provenance,
    TraceCompleteness,
    TraceReasonCode,
    UnifiedTradingTrace,
)


class ExperienceType(str, Enum):
    """Categories of historical evidence that TradingAI actually produced.

    These mirror the actual D-5 trace node types / existing runtime domains.
    Only categories with the corresponding evidence are produced; nothing is
    fabricated.
    """

    TRADE = "TRADE"
    DECISION = "DECISION"
    NO_TRADE = "NO_TRADE"
    ENTRY_REJECTION = "ENTRY_REJECTION"
    EXECUTION = "EXECUTION"
    POSITION = "POSITION"
    EXIT = "EXIT"
    TRADE_RESULT = "TRADE_RESULT"
    MARKET_OBSERVATION = "MARKET_OBSERVATION"
    DOM_MICROSTRUCTURE = "DOM_MICROSTRUCTURE"
    RUNTIME_STATE = "RUNTIME_STATE"
    AUTHORITY_STATE = "AUTHORITY_STATE"
    MONEY_MANAGEMENT_STATE = "MONEY_MANAGEMENT_STATE"
    SUPERVISOR_FINDING = "SUPERVISOR_FINDING"
    INCIDENT = "INCIDENT"


class ExperienceStatus(str, Enum):
    """Deterministic evidence-quality status of a single experience."""

    EVIDENCE_ONLY = "EVIDENCE_ONLY"
    PARTIAL = "PARTIAL"
    AMBIGUOUS = "AMBIGUOUS"
    STALE = "STALE"
    DRIFTED = "DRIFTED"


def derive_experience_id(
    *,
    experience_type: ExperienceType,
    trace_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    order_id: Optional[str] = None,
    fill_id: Optional[str] = None,
    position_id: Optional[str] = None,
    trade_id: Optional[str] = None,
    started_at: Optional[str] = None,
    span_key: Optional[str] = None,
) -> str:
    """Deterministic experience identity derived from stable authoritative IDs.

    No random generator is ever used.  If no authoritative ID is available, the
    identity still derives deterministically from the type + timestamps + span
    key, so two identical inputs always produce the same ID.
    """
    return deterministic_id(
        "experience",
        experience_type.value,
        trace_id or "",
        decision_id or "",
        order_id or "",
        fill_id or "",
        position_id or "",
        trade_id or "",
        started_at or "",
        span_key or "",
    )


@dataclass(frozen=True)
class ExperienceRecord:
    """A typed, immutable, evidence-only experience record.

    It references authoritative evidence rather than duplicating it.  All
    collections are bounded and truncation is surfaced via ``warnings``.
    """

    experience_id: str
    experience_type: ExperienceType
    symbol: Optional[str] = None
    mode: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    trace_id: Optional[str] = None
    decision_id: Optional[str] = None
    order_id: Optional[str] = None
    fill_id: Optional[str] = None
    position_id: Optional[str] = None
    trade_id: Optional[str] = None
    marker_id: Optional[str] = None
    ranking_cycle_id: Optional[str] = None
    outcome: Optional[str] = None
    source_references: tuple[Provenance, ...] = field(default_factory=tuple)
    reason_codes: tuple[TraceReasonCode, ...] = field(default_factory=tuple)
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)
    completeness: TraceCompleteness = TraceCompleteness.UNAVAILABLE
    drift: Optional[DriftAssessment] = None
    summary: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experienceId": self.experience_id,
            "experienceType": self.experience_type.value,
            "symbol": self.symbol,
            "mode": self.mode,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "traceId": self.trace_id,
            "decisionId": self.decision_id,
            "orderId": self.order_id,
            "fillId": self.fill_id,
            "positionId": self.position_id,
            "tradeId": self.trade_id,
            "markerId": self.marker_id,
            "rankingCycleId": self.ranking_cycle_id,
            "outcome": self.outcome,
            "sourceReferences": [p.to_dict() for p in self.source_references],
            "reasonCodes": [r.to_dict() for r in self.reason_codes],
            "provenance": _provenance_dict(self.provenance),
            "completeness": self.completeness.value,
            "drift": self.drift.stable_json() if self.drift else None,
            "summary": self.summary,
            "tags": list(self.tags),
            "warnings": list(self.warnings),
            "authority": EXPERIENCE_MEMORY_AUTHORITY.value,
        }

    @property
    def authority(self) -> KnowledgeEvolutionAuthority:
        return EXPERIENCE_MEMORY_AUTHORITY

    @property
    def operational_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def execution_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    @property
    def mutation_authority(self) -> KnowledgeEvolutionAuthority:
        return KnowledgeEvolutionAuthority.NONE

    def mutation_interfaces(self) -> tuple[str, ...]:
        return mutation_interfaces(self)

    @property
    def is_evidence_only(self) -> bool:
        return self.authority is EXPERIENCE_MEMORY_AUTHORITY


def _provenance_dict(record: ProvenanceRecord) -> dict[str, Any]:
    return {
        "truthLevel": record.truth_level.value,
        "sourceCategory": record.source_category.value,
        "sourceReference": record.source_reference,
        "sourcePath": record.source_path,
        "symbol": record.symbol,
        "version": record.version,
        "contentHash": record.content_hash,
        "verified": record.verified,
        "notes": record.notes,
    }


def normalize_experience(
    record: ExperienceRecord,
    *,
    max_summary_len: int = MAX_D8_SUMMARY,
    max_tags: int = MAX_D8_TAGS,
    max_reason_codes: int = MAX_D8_REASON_CODES,
    max_source_refs: int = MAX_D8_SOURCE_REFERENCES,
    max_warnings: int = MAX_D8_WARNINGS,
) -> ExperienceRecord:
    """Return a fully-bounded copy of ``record`` (never mutates the input).

    Builders call this to guarantee no unbounded collections survive, and to
    surface truncation explicitly as warnings.
    """
    warnings = list(record.warnings)
    tags = list(record.tags)
    if len(tags) > max_tags:
        warnings.append("TAGS_TRUNCATED")
        tags = tags[:max_tags]
    if len(record.reason_codes) > max_reason_codes:
        warnings.append("REASON_CODES_TRUNCATED")
    if len(record.source_references) > max_source_refs:
        warnings.append("SOURCE_REFERENCES_TRUNCATED")
    if len(warnings) > max_warnings:
        warnings = warnings[:max_warnings]
    return ExperienceRecord(
        experience_id=record.experience_id,
        experience_type=record.experience_type,
        symbol=bound(record.symbol, 64),
        mode=bound(record.mode, 16),
        started_at=record.started_at,
        ended_at=record.ended_at,
        trace_id=record.trace_id,
        decision_id=record.decision_id,
        order_id=record.order_id,
        fill_id=record.fill_id,
        position_id=record.position_id,
        trade_id=record.trade_id,
        marker_id=record.marker_id,
        ranking_cycle_id=record.ranking_cycle_id,
        outcome=record.outcome,
        source_references=record.source_references[:max_source_refs],
        reason_codes=record.reason_codes[:max_reason_codes],
        provenance=record.provenance,
        completeness=record.completeness,
        drift=record.drift,
        summary=bound(record.summary, max_summary_len),
        tags=tuple(tags),
        warnings=tuple(warnings),
    )


def make_experience(
    *,
    experience_type: ExperienceType,
    symbol: Optional[str] = None,
    mode: Optional[str] = None,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    trace_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    order_id: Optional[str] = None,
    fill_id: Optional[str] = None,
    position_id: Optional[str] = None,
    trade_id: Optional[str] = None,
    marker_id: Optional[str] = None,
    ranking_cycle_id: Optional[str] = None,
    outcome: Optional[str] = None,
    source_references: tuple[Provenance, ...] = (),
    reason_codes: tuple[TraceReasonCode, ...] = (),
    provenance: Optional[ProvenanceRecord] = None,
    completeness: TraceCompleteness = TraceCompleteness.COMPLETE,
    drift: Optional[DriftAssessment] = None,
    summary: str = "",
    tags: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    experience_id: Optional[str] = None,
) -> ExperienceRecord:
    """Construct a bounded, deterministic ExperienceRecord.

    ``experience_id`` is derived deterministically when not supplied; the
    caller may never supply an arbitrary random UUID to mask missing linkage.
    """
    derived = experience_id or derive_experience_id(
        experience_type=experience_type,
        trace_id=trace_id,
        decision_id=decision_id,
        order_id=order_id,
        fill_id=fill_id,
        position_id=position_id,
        trade_id=trade_id,
        started_at=started_at,
    )
    record = ExperienceRecord(
        experience_id=derived,
        experience_type=experience_type,
        symbol=symbol,
        mode=mode,
        started_at=started_at,
        ended_at=ended_at,
        trace_id=trace_id,
        decision_id=decision_id,
        order_id=order_id,
        fill_id=fill_id,
        position_id=position_id,
        trade_id=trade_id,
        marker_id=marker_id,
        ranking_cycle_id=ranking_cycle_id,
        outcome=outcome,
        source_references=source_references,
        reason_codes=reason_codes,
        provenance=provenance or ProvenanceRecord(
            truth_level=TruthLevel.OBSERVATION_FINDING,
            source_category=SourceCategory.HISTORY,
            source_reference=summary or derived,
        ),
        completeness=completeness,
        drift=drift,
        summary=summary,
        tags=clean_tags(tags),
        warnings=tuple(dedupe(warnings)),
    )
    return normalize_experience(record)


# --------------------------------------------------------------------------- #
# Deterministic derivation from the authoritative D-5 trace.
# --------------------------------------------------------------------------- #


def _primary_type(trace: UnifiedTradingTrace) -> ExperienceType:
    if trace.rejection is not None:
        return ExperienceType.ENTRY_REJECTION
    if trace.no_trade is not None:
        return ExperienceType.NO_TRADE
    if trace.trade_result is not None:
        return ExperienceType.TRADE_RESULT
    if trace.execution_attempt is not None:
        return ExperienceType.EXECUTION
    if trace.position is not None:
        return ExperienceType.POSITION
    if trace.decision is not None:
        return ExperienceType.DECISION
    if trace.market_observation is not None:
        return ExperienceType.MARKET_OBSERVATION
    return ExperienceType.RUNTIME_STATE


def _identity(trace: UnifiedTradingTrace, key: str) -> Optional[str]:
    for node in trace.nodes:
        value = node.identity.get(key)
        if value is not None:
            return str(value)
    return None


def experience_from_trace(trace: UnifiedTradingTrace) -> ExperienceRecord:
    """Derive a deterministic ExperienceRecord from one authoritative D-5 trace.

    This is a VIEW over the authoritative trace: it never mutates the trace and
    never creates a parallel source of truth.  If the trace is partial/ambiguous
    the record preserves that state instead of inflating certainty.
    """
    if not isinstance(trace, UnifiedTradingTrace):
        raise TypeError("typed UnifiedTradingTrace required")
    experience_type = _primary_type(trace)
    provenance = _provenance_from_trace(trace)
    return make_experience(
        experience_type=experience_type,
        symbol=trace.symbol,
        mode=trace.mode,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        trace_id=trace.trace_id,
        decision_id=_identity(trace, "decisionId"),
        order_id=_identity(trace, "orderId"),
        fill_id=_identity(trace, "fillId"),
        position_id=_identity(trace, "positionId"),
        trade_id=_identity(trace, "tradeId"),
        marker_id=_identity(trace, "markerId"),
        ranking_cycle_id=_identity(trace, "rankingCycleId"),
        outcome=_derive_outcome(trace, experience_type),
        source_references=trace.source_references,
        reason_codes=trace.reason_codes,
        provenance=provenance,
        completeness=trace.completeness,
        summary=_compose_summary(experience_type, trace),
        tags=_compose_tags(experience_type),
        warnings=trace.warnings,
    )


def _compose_summary(experience_type: ExperienceType, trace: UnifiedTradingTrace) -> str:
    reason = "+".join(
        code.code for code in trace.reason_codes[:8]
    )
    from backend.knowledge_evolution._base import bound

    if experience_type is ExperienceType.NO_TRADE:
        text = f"NO_TRADE {trace.symbol or ''} {reason}".strip()
    elif experience_type is ExperienceType.ENTRY_REJECTION:
        text = f"ENTRY_REJECTION {trace.symbol or ''} {reason}".strip()
    elif experience_type is ExperienceType.TRADE_RESULT:
        text = f"TRADE_RESULT {trace.symbol or ''} {reason}".strip()
    elif experience_type is ExperienceType.EXECUTION:
        text = f"EXECUTION {trace.symbol or ''} {reason}".strip()
    else:
        text = f"{experience_type.value} {trace.symbol or ''}".strip()
    return bound(text, MAX_D8_SUMMARY)


def _compose_tags(experience_type: ExperienceType) -> tuple[str, ...]:
    return clean_tags((experience_type.value,))


def _derive_outcome(trace: UnifiedTradingTrace, experience_type: ExperienceType) -> Optional[str]:
    """Deterministically classify an outcome for evidence filtering.

    Only signs the underlying evidence actually supports are produced.  When no
    outcome evidence is present the value is ``None`` (UNKNOWN) - it is never
    guessed.
    """
    if experience_type is ExperienceType.ENTRY_REJECTION:
        return "BLOCKED"
    if experience_type is ExperienceType.NO_TRADE:
        return "SUPPRESSED"
    if experience_type is ExperienceType.EXECUTION and trace.execution_attempt is not None:
        if trace.execution_attempt.no_trade_kind is not None:
            return "EXECUTION_FAILED"
        return "EXECUTION_ATTEMPTED"
    if experience_type is ExperienceType.TRADE_RESULT and trace.trade_result is not None:
        pnl = trace.trade_result.data.get("netPnL")
        if pnl is None:
            pnl = trace.trade_result.identity.get("netPnL")
            if pnl is None:
                pnl = trace.trade_result.data.get("grossPnL")
        try:
            value = float(pnl)
        except (TypeError, ValueError):
            return None
        if value > 0:
            return "WIN"
        if value < 0:
            return "LOSS"
        return "FLAT"
    return None


def _provenance_from_trace(trace: UnifiedTradingTrace) -> ProvenanceRecord:
    from backend.knowledge_core.drift import provenance_from_trace

    reference = trace.source_references
    base = provenance_from_trace(
        reference[0] if reference else {"source_type": "UNIFIED_TRACE", "source_identifier": trace.trace_id},
        truth_level=TruthLevel.OBSERVATION_FINDING,
        source_reference=f"UNIFIED_TRACE:{trace.trace_id}",
    )
    # Set truth-level / category explicitly (provenance_from_trace defaults to
    # OBSERVATION_FINDING / HISTORY, which is correct for experience evidence).
    return ProvenanceRecord(
        truth_level=TruthLevel.OBSERVATION_FINDING,
        source_category=SourceCategory.HISTORY,
        source_reference=base.source_reference,
        source_path=base.source_path,
        symbol=trace.symbol,
        source_subsystem=base.source_subsystem,
        source_type=base.source_type,
        source_identifier=base.source_identifier,
        source_timestamp=base.source_timestamp,
        notes=f"DERIVED_FROM_D5_TRACE:{trace.trace_id}",
    )


__all__ = [
    "ExperienceRecord",
    "ExperienceStatus",
    "ExperienceType",
    "derive_experience_id",
    "experience_from_trace",
    "make_experience",
    "normalize_experience",
]
