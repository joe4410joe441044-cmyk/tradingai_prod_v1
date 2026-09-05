"""Focused D-8 tests: Experience Memory, Investigation, Pattern/Finding,
Hypothesis, Validation, Human Review and Validated Knowledge.

Authority contract under test (task section 44):

    Experience Memory      = EVIDENCE_ONLY
    Investigation          = ANALYSIS_ONLY
    Pattern / Finding      = OBSERVATION_ONLY
    Hypothesis             = HYPOTHESIS_ONLY
    Validation             = ANALYSIS_ONLY
    Validated Knowledge    = INFORMATION_ONLY
    Knowledge Promotion    = HUMAN_REVIEW_REQUIRED
    Advisor                = READ_ONLY
    Supervisor             = READ_ONLY_ANALYSIS
    Operational / Execution / Strategy / MM / Canonical Mutation = NONE
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.runtime.trading_trace import TradingTraceStore, make_event, new_trace_id
from backend.runtime.unified_trace import (
    StaticTraceEvidenceSource,
    TraceCompleteness,
    UnifiedTraceAssembler,
)

from backend.knowledge_core.authority import (
    SourceCategory,
    TRUTH_PRIORITY,
    TruthLevel,
)
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_core.drift import (
    AUTHORITY_CONFLICT,
    DriftAssessment,
    DriftFinding,
    DriftStatus,
    SourceKind,
    assess_provenance,
    build_conflicting_assessment,
)

from backend.knowledge_evolution import (
    AcceptanceCriterion,
    AdvisorKnowledgeProjection,
    CooccurrenceCounts,
    EvidenceStrength,
    ExperienceRecord,
    ExperienceType,
    Finding,
    FindingStatus,
    Hypothesis,
    HypothesisStatus,
    InvestigationFilter,
    InvestigationOutcome,
    InvestigationResult,
    KnowledgePromotionError,
    KnowledgeStateLabel,
    Pattern,
    PatternStatus,
    PatternType,
    Relation,
    ReviewDecision,
    SupervisorKnowledgeContext,
    Validation,
    ValidationEvidence,
    ValidationMetric,
    ValidationMethod,
    ValidationResult,
    ValidatedKnowledge,
    ValidatedKnowledgeStatus,
    advance_hypothesis,
    build_advisor_knowledge_projection,
    build_finding,
    build_pattern,
    build_supervisor_knowledge_context,
    derive_experience_id,
    derive_finding_id,
    derive_hypothesis_id,
    derive_knowledge_id,
    derive_pattern_id,
    derive_review_id,
    derive_validation_id,
    evaluate_validation,
    experience_from_trace,
    investigation_summary,
    label_object,
    make_experience,
    make_investigation,
    mutation_interfaces,
    promote_to_validated_knowledge,
    propose_hypothesis,
    record_human_review,
    run_investigation,
    select_experiences,
)


def _trace(*, kind: str = "win", symbol: str = "BTCUSDT", mode: str = "PAPER"):
    tid = new_trace_id()
    if kind == "win":
        events = [
            make_event(trace_id=tid, mode=mode, stage="STRATEGY", status="BUY", symbol=symbol,
                       decision_id="d1", reason_code="SPREAD_OK",
                       metadata={"decisionId": "d1"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="EXECUTION", status="PAPER_FILLED", symbol=symbol,
                       decision_id="d1", metadata={"decisionId": "d1", "orderId": "o1"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="POSITION", status="OPEN", symbol=symbol,
                       decision_id="d1", metadata={"decisionId": "d1", "positionId": "p1", "orderId": "o1"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="RESULT", status="EXECUTED", symbol=symbol,
                       decision_id="d1", metadata={"decision": "BUY", "netPnL": 2.0, "tradeId": "t1", "decisionId": "d1"}).to_dict(),
        ]
    elif kind == "loss":
        events = [
            make_event(trace_id=tid, mode=mode, stage="STRATEGY", status="BUY", symbol=symbol,
                       decision_id="d2", reason_code="SPREAD_OK",
                       metadata={"decisionId": "d2"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="EXECUTION", status="PAPER_FILLED", symbol=symbol,
                       decision_id="d2", metadata={"decisionId": "d2", "orderId": "o2"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="POSITION", status="OPEN", symbol=symbol,
                       decision_id="d2", metadata={"decisionId": "d2", "positionId": "p2", "orderId": "o2"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="RESULT", status="EXECUTED", symbol=symbol,
                       decision_id="d2", metadata={"decision": "BUY", "netPnL": -1.5, "tradeId": "t2", "decisionId": "d2"}).to_dict(),
        ]
    elif kind == "blocked":
        events = [
            make_event(trace_id=tid, mode=mode, stage="STRATEGY", status="BUY", symbol=symbol,
                       decision_id="d3", reason_code="SPREAD_OK",
                       metadata={"decisionId": "d3"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="MONEY_MANAGEMENT", status="BLOCKED", symbol=symbol,
                       decision_id="d3", reason_code="MAXIMUM_DRAWDOWN",
                       metadata={"decisionId": "d3"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="RESULT", status="BLOCKED", symbol=symbol,
                       decision_id="d3", reason_code="MAXIMUM_DRAWDOWN",
                       metadata={"decisionId": "d3"}).to_dict(),
        ]
    elif kind == "hold":
        events = [
            make_event(trace_id=tid, mode=mode, stage="STRATEGY", status="HOLD", symbol=symbol,
                       decision_id="d4", reason_code="LIQUIDITY_INSTABILITY",
                       metadata={"decisionId": "d4"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="RESULT", status="SUPPRESSED", symbol=symbol,
                       decision_id="d4", reason_code="LIQUIDITY_INSTABILITY",
                       metadata={"decisionId": "d4"}).to_dict(),
        ]
    elif kind == "partial":
        events = [
            make_event(trace_id=tid, mode=mode, stage="STRATEGY", status="BUY", symbol=symbol,
                       decision_id="d5", metadata={"decisionId": "d5"}).to_dict(),
            make_event(trace_id=tid, mode=mode, stage="GOVERNANCE", status="ALLOW", symbol=symbol,
                       decision_id="d5", metadata={"decisionId": "d5"}).to_dict(),
        ]
    else:
        raise ValueError(f"unknown kind {kind}")
    return UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(tid)


def _experiences(*kinds: str, symbol: str = "BTCUSDT"):
    return [experience_from_trace(_trace(kind=k, symbol=symbol)) for k in kinds]


def _win_experiences(n: int):
    return _experiences(*(["win"] * n))


# --------------------------------------------------------------------------- #
# Experience
# --------------------------------------------------------------------------- #


def test_d8_01_experience_deterministic():
    a = make_experience(experience_type=ExperienceType.NO_TRADE, trace_id="tracing-1", symbol="BTCUSDT")
    b = make_experience(experience_type=ExperienceType.NO_TRADE, trace_id="tracing-1", symbol="BTCUSDT")
    assert a.experience_id == b.experience_id


def test_d8_02_stable_id_derivation():
    i1 = derive_experience_id(experience_type=ExperienceType.NO_TRADE, trace_id="tracing-1")
    i2 = derive_experience_id(experience_type=ExperienceType.NO_TRADE, trace_id="tracing-1")
    assert i1 == i2
    i3 = derive_experience_id(experience_type=ExperienceType.NO_TRADE, trace_id="tracing-2")
    assert i1 != i3


def test_d8_03_authoritative_source_ids_reused():
    exp = experience_from_trace(_trace(kind="win"))
    assert exp.trace_id.startswith("trading-e2e-")
    assert exp.decision_id == "d1"
    assert exp.order_id == "o1"
    assert exp.position_id == "p1"
    assert exp.trade_id == "t1"


def test_d8_04_no_random_id():
    trace = _trace(kind="win")
    exp = experience_from_trace(trace)
    assert exp.experience_id.startswith("experience:")
    assert "uuid" not in exp.experience_id.lower()
    # identical input -> identical deterministic id (no random generator)
    assert exp.experience_id == experience_from_trace(trace).experience_id


def test_d8_05_input_non_mutation():
    trace = _trace(kind="win")
    snapshot = trace.to_dict()
    experience_from_trace(trace)
    assert trace.to_dict() == snapshot
    exp = make_experience(experience_type=ExperienceType.TRADE_RESULT, summary="x", tags=("a", "b"))
    assert exp.tags == ("a", "b")


def test_d8_06_d5_provenance_preserved():
    trace = _trace(kind="win")
    exp = experience_from_trace(trace)
    assert trace.trace_id in exp.provenance.source_reference
    assert exp.source_references == trace.source_references


def test_d8_07_trace_completeness_preserved():
    trace = _trace(kind="win")
    exp = experience_from_trace(trace)
    assert exp.completeness is trace.completeness
    assert exp.completeness is TraceCompleteness.COMPLETE


def test_d8_08_reason_codes_preserved():
    exp = experience_from_trace(_trace(kind="blocked"))
    codes = {code.code for code in exp.reason_codes}
    assert "MAXIMUM_DRAWDOWN" in codes


def test_d8_09_partial_remains_partial():
    exp = experience_from_trace(_trace(kind="partial"))
    assert exp.completeness is TraceCompleteness.PARTIAL
    assert any("MISSING" in w or "PARTIAL" in w.upper() for w in exp.warnings)


def test_d8_10_ambiguous_remains_ambiguous():
    tid = new_trace_id()
    events = [
        make_event(trace_id=tid, mode="PAPER", stage="STRATEGY", status="BUY", symbol="BTCUSDT").to_dict(),
        make_event(trace_id=tid, mode="PAPER", stage="STRATEGY", status="SELL", symbol="BTCUSDT").to_dict(),
        make_event(trace_id=tid, mode="PAPER", stage="EXECUTION", status="PAPER_FILLED", symbol="BTCUSDT",
                   metadata={"orderId": "o1"}).to_dict(),
    ]
    trace = UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(tid)
    exp = experience_from_trace(trace)
    assert exp.completeness is TraceCompleteness.AMBIGUOUS


# --------------------------------------------------------------------------- #
# Investigation
# --------------------------------------------------------------------------- #


def test_d8_11_deterministic_evidence_selection():
    exps = _experiences("win", "loss", "blocked")
    criterion = InvestigationFilter(symbol="BTCUSDT")
    a = select_experiences(exps, criterion)
    b = select_experiences(exps, criterion)
    assert [e.experience_id for e in a] == [e.experience_id for e in b]


def test_d8_12_symbol_filter():
    exps = _experiences("win", "loss", symbol="BTCUSDT") + _experiences("win", symbol="ETHUSDT")
    selected = select_experiences(exps, InvestigationFilter(symbol="BTCUSDT"))
    assert selected
    assert all(e.symbol == "BTCUSDT" for e in selected)


def test_d8_13_time_filter():
    exps = [
        make_experience(experience_type=ExperienceType.NO_TRADE, symbol="BTCUSDT", started_at="2026-01-01T00:00:00Z"),
        make_experience(experience_type=ExperienceType.TRADE_RESULT, symbol="BTCUSDT", started_at="2026-06-01T00:00:00Z"),
    ]
    selected = select_experiences(
        exps,
        InvestigationFilter(started_from="2026-03-01T00:00:00Z", started_to="2026-12-01T00:00:00Z"),
    )
    assert len(selected) == 1
    assert selected[0].experience_type is ExperienceType.TRADE_RESULT


def test_d8_14_reason_code_filter():
    exp_blocked = experience_from_trace(_trace(kind="blocked"))
    exp_win = experience_from_trace(_trace(kind="win"))
    selected = select_experiences(
        [exp_blocked, exp_win],
        InvestigationFilter(reason_codes=("MAXIMUM_DRAWDOWN",)),
    )
    assert selected == (exp_blocked,)


def test_d8_15_experience_type_filter():
    exps = _experiences("win", "blocked")
    selected = select_experiences(
        exps, InvestigationFilter(experience_types=(ExperienceType.ENTRY_REJECTION,))
    )
    assert len(selected) == 1
    assert selected[0].experience_type is ExperienceType.ENTRY_REJECTION


def test_d8_16_completeness_filter():
    exps = [experience_from_trace(_trace(kind="win")), experience_from_trace(_trace(kind="partial"))]
    selected = select_experiences(
        exps, InvestigationFilter(completeness=(TraceCompleteness.PARTIAL,))
    )
    assert all(e.completeness is TraceCompleteness.PARTIAL for e in selected)


def test_d8_17_bounded_evidence():
    exps = _win_experiences(5)
    selected = select_experiences(exps, InvestigationFilter(symbol="BTCUSDT"), limit=2)
    assert len(selected) == 2


def test_d8_18_truncation_explicit():
    exps = _win_experiences(5)
    inv = make_investigation(
        question="bounded test", criterion=InvestigationFilter(symbol="BTCUSDT"), limit=10
    )
    result = run_investigation(inv, exps, evidence_limit=2)
    assert result.evidence_set.truncated
    assert "EVIDENCE_TRUNCATED" in result.evidence_set.warnings


def test_d8_19_missing_evidence_handled():
    inv = make_investigation(
        question="missing", criterion=InvestigationFilter(symbol="DOGEUSDT")
    )
    result = run_investigation(inv, _experiences("win"))
    assert result.outcome is InvestigationOutcome.NO_MATCHING_EVIDENCE
    assert "NO_MATCHING_EVIDENCE" in result.evidence_set.warnings


def test_d8_20_counterevidence_retained():
    exps = _experiences("win", "loss", "blocked")
    inv = make_investigation(
        question="co-occurrence", criterion=InvestigationFilter(symbol="BTCUSDT")
    )
    result = run_investigation(inv, exps)
    assert len(result.evidence_set.evidence) == 3
    outcomes = {e.outcome for e in result.evidence_set.evidence}
    assert "WIN" in outcomes and "LOSS" in outcomes  # counterexample retained


# --------------------------------------------------------------------------- #
# Pattern / Finding
# --------------------------------------------------------------------------- #


def _condition_spread(e: ExperienceRecord) -> bool:
    return any(code.code == "SPREAD_OK" for code in e.reason_codes)


def test_d8_21_deterministic_pattern_id():
    exps = _experiences("win", "loss")
    p1 = build_pattern(exps, pattern_type=PatternType.CO_OCCURRENCE, description="x",
                       condition=_condition_spread, outcome=lambda e: e.outcome == "WIN")
    p2 = build_pattern(exps, pattern_type=PatternType.CO_OCCURRENCE, description="x",
                       condition=_condition_spread, outcome=lambda e: e.outcome == "WIN")
    assert p1.pattern_id == p2.pattern_id
    assert derive_pattern_id(pattern_type=p1.pattern_type, description=p1.description,
                             supporting_ids=p1.supporting_experience_ids,
                             counter_ids=p1.counterexample_experience_ids) == p1.pattern_id


def test_d8_22_support_count_correct():
    exps = _experiences("win", "loss", "win", "blocked")
    pattern = build_pattern(exps, pattern_type=PatternType.CO_OCCURRENCE, description="x",
                            condition=lambda e: e.outcome in {"WIN", "LOSS"},
                            outcome=lambda e: e.outcome == "WIN")
    assert pattern.support_count == 2
    assert pattern.sample_size == 3
    assert pattern.counterexample_count == 1


def test_d8_23_sample_size_correct():
    exps = _experiences("win", "blocked")
    counts, _, _ = _count(exps, lambda e: e.outcome == "WIN")
    assert counts.sample_size == 1


def _count(exps, condition):
    from backend.knowledge_evolution.pattern import count_cooccurrence
    return count_cooccurrence(exps, condition, lambda e: e.outcome == "WIN")


def test_d8_24_counterexample_count_correct():
    exps = _experiences("win", "loss", "loss")
    pattern = build_pattern(exps, pattern_type=PatternType.CO_OCCURRENCE, description="x",
                            condition=lambda e: e.outcome in {"WIN", "LOSS"},
                            outcome=lambda e: e.outcome == "WIN")
    assert pattern.support_count == 1
    assert pattern.counterexample_count == 2


def test_d8_25_one_event_not_repeated_pattern():
    exps = _experiences("win")
    pattern = build_pattern(exps, pattern_type=PatternType.CO_OCCURRENCE, description="single",
                            condition=_condition_spread, outcome=lambda e: e.outcome == "WIN")
    assert pattern.is_repeated is False
    assert pattern.evidence_strength is EvidenceStrength.INSUFFICIENT
    assert pattern.status is PatternStatus.SINGLETON
    assert "SINGLE_EVENT_NOT_REPEATED_PATTERN" in pattern.warnings


def test_d8_26_no_causal_claim_from_correlation():
    exps = _experiences("win", "win", "loss")
    pattern = build_pattern(exps, pattern_type=PatternType.CO_OCCURRENCE, description="x",
                            condition=_condition_spread, outcome=lambda e: e.outcome == "WIN")
    assert pattern.causal_claim is False
    assert pattern.asserts_causation is False


def test_d8_27_finding_linked_to_evidence():
    result = run_investigation(
        make_investigation(question="q", criterion=InvestigationFilter(symbol="BTCUSDT")),
        _experiences("win", "loss", "blocked"),
    )
    finding = build_finding(result, statement="observation")
    assert finding.investigation_id == result.investigation_id
    assert finding.supporting_evidence_ids
    assert finding.truth_level is TruthLevel.OBSERVATION_FINDING


def test_d8_28_orphan_finding_rejected():
    inv = make_investigation(question="empty", criterion=InvestigationFilter(symbol="DOGEUSDT"))
    result = run_investigation(inv, _experiences("win"))
    assert result.evidence_set.empty
    with pytest.raises(ValueError):
        build_finding(result, statement="orphan")


def test_d8_29_finding_truth_level_observation():
    result = run_investigation(
        make_investigation(question="q", criterion=InvestigationFilter(symbol="BTCUSDT")),
        _experiences("win", "loss"),
    )
    finding = build_finding(result, statement="obs")
    assert finding.truth_level is TruthLevel.OBSERVATION_FINDING
    assert finding.authority.value == "OBSERVATION_ONLY"


# --------------------------------------------------------------------------- #
# Hypothesis
# --------------------------------------------------------------------------- #


def test_d8_30_deterministic_hypothesis_id():
    h1 = propose_hypothesis(statement="s", derived_from_finding_ids=("f1",))
    h2 = propose_hypothesis(statement="s", derived_from_finding_ids=("f1",))
    assert h1.hypothesis_id == h2.hypothesis_id
    assert derive_hypothesis_id(statement="s", finding_ids=("f1",)) == h1.hypothesis_id


def test_d8_31_derived_finding_refs_preserved():
    h = propose_hypothesis(statement="s", derived_from_finding_ids=("f1", "f2"),
                           supporting_pattern_ids=("p1",))
    assert h.derived_from_finding_ids == ("f1", "f2")
    assert h.supporting_pattern_ids == ("p1",)


def test_d8_32_lifecycle_explicit():
    h = propose_hypothesis(statement="s", validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.6),))
    assert h.status is HypothesisStatus.PROPOSED
    h = advance_hypothesis(h, HypothesisStatus.READY_FOR_VALIDATION)
    assert h.status is HypothesisStatus.READY_FOR_VALIDATION
    h = advance_hypothesis(h, HypothesisStatus.VALIDATING)
    assert h.status is HypothesisStatus.VALIDATING


def test_d8_33_proposed_not_validated():
    h = propose_hypothesis(statement="s")
    assert h.status is HypothesisStatus.PROPOSED
    with pytest.raises(ValueError):
        advance_hypothesis(h, HypothesisStatus.SUPPORTED)


def test_d8_34_no_automatic_promotion():
    h = propose_hypothesis(statement="s")
    with pytest.raises(ValueError):
        advance_hypothesis(h, HypothesisStatus.READY_FOR_VALIDATION)
    h2 = propose_hypothesis(statement="s", validation_criteria=(("X", "AT_LEAST", 1.0),))
    assert h2.status is HypothesisStatus.PROPOSED  # still not validated
    with pytest.raises(ValueError):
        advance_hypothesis(h2, HypothesisStatus.SUPPORTED)


def test_d8_35_no_strategy_mutation():
    h = propose_hypothesis(statement="s")
    assert h.strategy_mutation is False
    assert h.strategy_mutation_authority.value == "NONE"
    assert mutation_interfaces(h) == ()
    advanced = advance_hypothesis(h, HypothesisStatus.REJECTED)
    assert advanced.strategy_mutation is False


def test_d8_36_limitations_preserved():
    h = propose_hypothesis(statement="s", limitations=("small sample", "no live data"))
    assert "small sample" in h.limitations
    advanced = advance_hypothesis(h, HypothesisStatus.REJECTED)
    assert advanced.limitations == h.limitations


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _ready_hypothesis():
    return propose_hypothesis(
        statement="s",
        validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.6),),
    )


def test_d8_37_validation_criteria_required():
    h = _ready_hypothesis()
    evidence = ValidationEvidence(sample_size=10, support_count=8,
                                  counterexample_count=2, method=ValidationMethod.PAPER_RESULTS)
    with pytest.raises(ValueError):
        evaluate_validation(h, evidence=evidence, criteria=())


def test_d8_38_criteria_precede_result():
    h = _ready_hypothesis()
    evidence = ValidationEvidence(sample_size=10, support_count=8, counterexample_count=2,
                                  method=ValidationMethod.PAPER_RESULTS)
    result = evaluate_validation(h, evidence=evidence,
                                 criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),))
    assert result.result is ValidationResult.SUPPORTED
    result2 = evaluate_validation(h, evidence=evidence,
                                  criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.95),))
    assert result2.result is ValidationResult.NOT_SUPPORTED


def test_d8_39_evidence_references_preserved():
    h = _ready_hypothesis()
    evidence = ValidationEvidence(sample_size=10, support_count=8, counterexample_count=2,
                                  method=ValidationMethod.PAPER_RESULTS,
                                  dataset_references=("paper-run/2026-01", "trace-5"))
    result = evaluate_validation(h, evidence=evidence,
                                 criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),))
    assert result.evidence.dataset_references == ("paper-run/2026-01", "trace-5")
    assert derive_validation_id(h.hypothesis_id, result.method, result.acceptance_criteria,
                                result.evidence.dataset_references) == result.validation_id


def test_d8_40_supported_result():
    h = _ready_hypothesis()
    result = evaluate_validation(h, evidence=ValidationEvidence(sample_size=10, support_count=8,
                                                                counterexample_count=2,
                                                                method=ValidationMethod.PAPER_RESULTS),
                                 criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),))
    assert result.result is ValidationResult.SUPPORTED


def test_d8_41_not_supported_result():
    h = _ready_hypothesis()
    result = evaluate_validation(h, evidence=ValidationEvidence(sample_size=10, support_count=2,
                                                                counterexample_count=8,
                                                                method=ValidationMethod.HISTORICAL_REPLAY),
                                 criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.8),))
    assert result.result is ValidationResult.NOT_SUPPORTED


def test_d8_42_inconclusive_result():
    h = _ready_hypothesis()
    result = evaluate_validation(h, evidence=ValidationEvidence(sample_size=3, support_count=2,
                                                                counterexample_count=1,
                                                                method=ValidationMethod.HISTORICAL_REPLAY),
                                 criteria=(AcceptanceCriterion(ValidationMetric.SAMPLE_SIZE, Relation.AT_LEAST, 10),))
    assert result.result is ValidationResult.INCONCLUSIVE


def test_d8_43_insufficient_evidence_inconclusive():
    h = _ready_hypothesis()
    result = evaluate_validation(h, evidence=ValidationEvidence(sample_size=1, support_count=1,
                                                                counterexample_count=0,
                                                                method=ValidationMethod.HISTORICAL_REPLAY),
                                 criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),))
    assert result.result is ValidationResult.INCONCLUSIVE
    assert "INSUFFICIENT_EVIDENCE" in result.warnings


def test_d8_44_counterevidence_affects_result():
    h = _ready_hypothesis()
    crit = (AcceptanceCriterion(ValidationMetric.COUNTEREXAMPLE_COUNT, Relation.AT_MOST, 2),)
    low = evaluate_validation(h, evidence=ValidationEvidence(sample_size=10, support_count=9,
                                                             counterexample_count=1,
                                                             method=ValidationMethod.HISTORICAL_REPLAY),
                              criteria=crit)
    assert low.result is ValidationResult.SUPPORTED
    high = evaluate_validation(h, evidence=ValidationEvidence(sample_size=10, support_count=9,
                                                              counterexample_count=5,
                                                              method=ValidationMethod.HISTORICAL_REPLAY),
                               criteria=crit)
    assert high.result is ValidationResult.NOT_SUPPORTED


def test_d8_45_no_fabricated_validation_evidence():
    h = _ready_hypothesis()
    result = evaluate_validation(h, evidence=ValidationEvidence(sample_size=0, support_count=0,
                                                                counterexample_count=0,
                                                                method=ValidationMethod.UNAVAILABLE,
                                                                available=False),
                                 criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),))
    assert result.result is ValidationResult.UNAVAILABLE
    assert mutation_interfaces(result) == ()


def test_d8_46_paper_evidence_read_only():
    h = _ready_hypothesis()
    result = evaluate_validation(h, evidence=ValidationEvidence(sample_size=4, support_count=4,
                                                                counterexample_count=0,
                                                                method=ValidationMethod.PAPER_RESULTS),
                                 criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),))
    assert result.result is ValidationResult.SUPPORTED
    assert mutation_interfaces(result) == ()
    assert result.method is ValidationMethod.PAPER_RESULTS


# --------------------------------------------------------------------------- #
# Human Review / Validated Knowledge
# --------------------------------------------------------------------------- #


def _promotion_inputs():
    h = _ready_hypothesis()
    h = advance_hypothesis(h, HypothesisStatus.READY_FOR_VALIDATION)
    h = advance_hypothesis(h, HypothesisStatus.VALIDATING)
    validation = evaluate_validation(h, evidence=ValidationEvidence(sample_size=10, support_count=8,
                                                                    counterexample_count=2,
                                                                    method=ValidationMethod.HISTORICAL_REPLAY),
                                     criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),))
    return h, validation


def test_d8_47_no_human_approval_no_promotion():
    h, validation = _promotion_inputs()
    with pytest.raises((KnowledgePromotionError, TypeError)):
        promote_to_validated_knowledge(h, validation, None)


def test_d8_48_approved_and_supported_allowed():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review, version="1.0",
                                        created_at="2026-09-05T10:01:00Z")
    assert isinstance(vk, ValidatedKnowledge)
    assert vk.status is ValidatedKnowledgeStatus.VALIDATED_KNOWN


def test_d8_49_rejected_no_promotion():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.REJECTED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    with pytest.raises(KnowledgePromotionError):
        promote_to_validated_knowledge(h, validation, review)


def test_d8_50_needs_more_evidence_no_promotion():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    with pytest.raises(KnowledgePromotionError):
        promote_to_validated_knowledge(h, validation, review)


def test_d8_51_validated_knowledge_retains_hypothesis_reference():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review)
    assert vk.origin_hypothesis_id == h.hypothesis_id
    assert derive_knowledge_id(h.hypothesis_id, vk.version, vk.validation_references) == vk.knowledge_id


def test_d8_52_validation_provenance_retained():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review)
    assert validation.validation_id in vk.validation_references


def test_d8_53_human_review_reference_retained():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review)
    assert vk.human_review_reference == review.review_id


def test_d8_54_canonical_not_overwritten():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review)
    assert vk.can_write_canonical is False
    assert vk.mutation_authority.value == "NONE"


def test_d8_55_validated_knowledge_below_canonical_runtime():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review)
    assert vk.truth_level is TruthLevel.VALIDATED_KNOWLEDGE
    assert TRUTH_PRIORITY[vk.truth_level] > TRUTH_PRIORITY[TruthLevel.CANONICAL_SPECIFICATION]
    assert TRUTH_PRIORITY[vk.truth_level] > TRUTH_PRIORITY[TruthLevel.CURRENT_SOURCE_RUNTIME]


# --------------------------------------------------------------------------- #
# D-7 provenance / drift
# --------------------------------------------------------------------------- #


def _assessed_at():
    return datetime.now(timezone.utc)


def test_d8_56_stale_provenance_remains_visible():
    now = _assessed_at()
    expected = ProvenanceRecord(truth_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
                                source_category=SourceCategory.RUNTIME, source_reference="runtime")
    current = ProvenanceRecord(truth_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
                               source_category=SourceCategory.RUNTIME, source_reference="runtime",
                               source_subsystem="BOT", source_type="RUNTIME", source_identifier="x",
                               source_timestamp=now - timedelta(seconds=100))
    drift = assess_provenance(subject="subject", source_kind=SourceKind.CURRENT_RUNTIME,
                              expected=expected, current=current, assessed_at=now,
                              freshness_window_seconds=10)
    exp = make_experience(experience_type=ExperienceType.RUNTIME_STATE, drift=drift)
    assert exp.drift.status is DriftStatus.STALE
    inv = run_investigation(
        make_investigation(question="stale", criterion=InvestigationFilter(experience_types=(ExperienceType.RUNTIME_STATE,))),
        [exp],
    )
    assert inv.evidence_set.evidence[0].drift.status is DriftStatus.STALE


def test_d8_57_drifted_provenance_remains_visible():
    expected = ProvenanceRecord(truth_level=TruthLevel.CANONICAL_SPECIFICATION,
                                source_category=SourceCategory.SPECIFICATION,
                                source_reference="docs/x.md", version="1",
                                content_hash="sha256:" + "0" * 64)
    current = ProvenanceRecord(truth_level=TruthLevel.CANONICAL_SPECIFICATION,
                               source_category=SourceCategory.SPECIFICATION,
                               source_reference="docs/x.md", version="2",
                               content_hash="sha256:" + "1" * 64)
    drift = assess_provenance(subject="x", source_kind=SourceKind.STATIC_CANONICAL,
                              expected=expected, current=current)
    assert drift.status is DriftStatus.DRIFTED
    exp = make_experience(experience_type=ExperienceType.MARKET_OBSERVATION, drift=drift)
    assert exp.drift.status is DriftStatus.DRIFTED


def test_d8_58_conflicting_provenance_remains_visible():
    finding = DriftFinding(code=AUTHORITY_CONFLICT, status=DriftStatus.CONFLICTING,
                           reason="incompatible claims")
    drift = build_conflicting_assessment("subject", finding)
    assert drift.status is DriftStatus.CONFLICTING
    exp = make_experience(experience_type=ExperienceType.MARKET_OBSERVATION, drift=drift)
    assert exp.drift.status is DriftStatus.CONFLICTING


def test_d8_59_unavailable_provenance_remains_visible():
    expected = ProvenanceRecord(truth_level=TruthLevel.OBSERVATION_FINDING,
                                source_category=SourceCategory.HISTORY, source_reference="trace")
    drift = assess_provenance(subject="subject", source_kind=SourceKind.HISTORICAL_EVIDENCE,
                              expected=expected, current=None)
    assert drift.status is DriftStatus.UNAVAILABLE
    exp = make_experience(experience_type=ExperienceType.TRADE_RESULT, drift=drift)
    assert exp.drift.status is DriftStatus.UNAVAILABLE


def test_d8_60_drift_not_silently_cleared_by_promotion():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    drift = DriftAssessment(subject="x", source_kind=SourceKind.HISTORICAL_EVIDENCE,
                            status=DriftStatus.DRIFTED)
    vk = promote_to_validated_knowledge(h, validation, review, drift=drift)
    assert vk.drift is not None
    assert "DRIFTED" in vk.drift.stable_json()


# --------------------------------------------------------------------------- #
# Advisor / Supervisor
# --------------------------------------------------------------------------- #


def _finding_and_hypothesis():
    result = run_investigation(
        make_investigation(question="q", criterion=InvestigationFilter(symbol="BTCUSDT")),
        _experiences("win", "loss"),
    )
    finding = build_finding(result, statement="obs")
    hypothesis = propose_hypothesis(statement="h", derived_from_finding_ids=(finding.finding_id,))
    return finding, hypothesis


def test_d8_61_advisor_distinguishes_finding_from_hypothesis():
    finding, hypothesis = _finding_and_hypothesis()
    projection = build_advisor_knowledge_projection([finding, hypothesis])
    labels = {item.label for item in projection.items}
    assert KnowledgeStateLabel.FINDING.value in labels
    assert KnowledgeStateLabel.HYPOTHESIS.value in labels


def test_d8_62_advisor_distinguishes_hypothesis_from_validated_knowledge():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review)
    projection = build_advisor_knowledge_projection([h, vk])
    labels = {item.label for item in projection.items}
    assert KnowledgeStateLabel.HYPOTHESIS.value in labels
    assert KnowledgeStateLabel.VALIDATED_KNOWLEDGE.value in labels


def test_d8_63_advisor_receives_bounded_investigation_context():
    items = [make_experience(experience_type=ExperienceType.MARKET_OBSERVATION, summary=str(i))
             for i in range(30)]
    projection = build_advisor_knowledge_projection(items, limit=5)
    assert isinstance(projection, AdvisorKnowledgeProjection)
    assert len(projection.items) <= 5
    assert projection.truncated is True
    assert projection.omittedCount > 0


def test_d8_64_supervisor_remains_read_only():
    context = build_supervisor_knowledge_context(observations=3, hypotheses=1)
    assert isinstance(context, SupervisorKnowledgeContext)
    assert context.investigation_authority == "NONE"
    assert context.operational_authority == "NONE"


def test_d8_65_supervisor_not_investigation_authority():
    result = run_investigation(
        make_investigation(question="q", criterion=InvestigationFilter(symbol="BTCUSDT")),
        _experiences("win", "loss"),
    )
    summary = investigation_summary(result)
    assert summary["authority"] == "READ_ONLY_ANALYSIS"
    assert summary["evidenceCount"] == 2


# --------------------------------------------------------------------------- #
# Security / Authority / Determinism
# --------------------------------------------------------------------------- #


def test_d8_66_secrets_excluded():
    tid = new_trace_id()
    events = [
        make_event(trace_id=tid, mode="PAPER", stage="STRATEGY", status="BUY", symbol="BTCUSDT",
                   decision_id="d1", metadata={"api_key": "supersecret123"}).to_dict(),
        make_event(trace_id=tid, mode="PAPER", stage="RESULT", status="EXECUTED", symbol="BTCUSDT",
                   decision_id="d1").to_dict(),
    ]
    trace = UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(tid)
    exp = experience_from_trace(trace)
    dumped = json.dumps(exp.to_dict())
    assert "supersecret123" not in dumped
    finding, hypothesis = _finding_and_hypothesis()
    proj = build_advisor_knowledge_projection([finding, hypothesis])
    for item2 in proj.items:
        assert "api_key" not in json.dumps(item2.to_dict())


def test_d8_67_provider_neutrality():
    for module_name in ("openai", "ollama", "anthropic", "deepseek", "byteplus"):
        assert module_name not in sys.modules
    # building the whole lifecycle requires no provider
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review)
    assert vk.statement


def test_d8_68_no_llm_required():
    exps = _experiences("win", "loss")
    inv = run_investigation(make_investigation(question="q", criterion=InvestigationFilter(symbol="BTCUSDT")), exps)
    finding = build_finding(inv, statement="obs")
    assert finding.finding_id
    for module_name in sys.modules:
        assert not module_name.startswith("openai") and not module_name.startswith("anthropic")


def test_d8_69_no_bot_mutation():
    objects = [
        make_experience(experience_type=ExperienceType.TRADE_RESULT),
        run_investigation(
            make_investigation(question="q", criterion=InvestigationFilter(symbol="BTCUSDT")),
            _experiences("win"),
        ),
    ]
    for obj in objects:
        assert mutation_interfaces(obj) == ()


def test_d8_70_no_loop_mutation():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk = promote_to_validated_knowledge(h, validation, review)
    assert mutation_interfaces(vk) == ()
    assert vk.operational_authority.value == "NONE"


def test_d8_71_no_auto_trade_mutation():
    for obj in (make_experience(experience_type=ExperienceType.AUTHORITY_STATE),
                propose_hypothesis(statement="s")):
        assert mutation_interfaces(obj) == ()


def test_d8_72_no_emergency_mutation():
    exp = make_experience(experience_type=ExperienceType.INCIDENT)
    assert mutation_interfaces(exp) == ()
    assert exp.operational_authority.value == "NONE"


def test_d8_73_no_order_mutation():
    objects = [
        make_experience(experience_type=ExperienceType.EXECUTION),
        propose_hypothesis(statement="s"),
    ]
    for obj in objects:
        assert mutation_interfaces(obj) == ()


def test_d8_74_no_mm_mutation():
    exp = make_experience(experience_type=ExperienceType.MONEY_MANAGEMENT_STATE)
    assert mutation_interfaces(exp) == ()


def test_d8_75_no_strategy_mutation():
    h = propose_hypothesis(statement="s")
    assert h.strategy_mutation is False
    assert h.strategy_mutation_authority.value == "NONE"


def test_d8_76_no_canonical_mutation():
    vk = ValidatedKnowledge(
        knowledge_id="knowledge:x", statement="s", origin_hypothesis_id="h",
        validation_references=("v",), human_review_reference="r",
        provenance=ProvenanceRecord(truth_level=TruthLevel.VALIDATED_KNOWLEDGE,
                                    source_category=SourceCategory.CONTRACT,
                                    source_reference="x"),
        version="1.0", created_at="now",
    )
    assert vk.can_write_canonical is False
    assert vk.strategy_mutation_authority.value == "NONE"


def test_d8_77_deterministic_repeated_output():
    h, validation = _promotion_inputs()
    h = advance_hypothesis(h, HypothesisStatus.SUPPORTED)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED,
                                 reviewer="operator", reviewed_at="2026-09-05T10:00:00Z")
    vk1 = promote_to_validated_knowledge(h, validation, review)
    vk2 = promote_to_validated_knowledge(h, validation, review)
    assert vk1.to_dict() == vk2.to_dict()


def test_d8_authority_ladder_constants():
    from backend.knowledge_evolution import (
        ADVISOR_AUTHORITY, CANONICAL_MUTATION_AUTHORITY, EXECUTION_AUTHORITY,
        EXPERIENCE_MEMORY_AUTHORITY, FINDING_AUTHORITY, HYPOTHESIS_AUTHORITY,
        INVESTIGATION_AUTHORITY, KNOWLEDGE_PROMOTION_AUTHORITY,
        MONEY_MANAGEMENT_MUTATION_AUTHORITY, OPERATIONAL_AUTHORITY, PATTERN_AUTHORITY,
        STRATEGY_MUTATION_AUTHORITY, SUPERVISOR_AUTHORITY,
        VALIDATED_KNOWLEDGE_AUTHORITY, VALIDATION_AUTHORITY,
    )
    assert EXPERIENCE_MEMORY_AUTHORITY.value == "EVIDENCE_ONLY"
    assert INVESTIGATION_AUTHORITY.value == "ANALYSIS_ONLY"
    assert PATTERN_AUTHORITY.value == "OBSERVATION_ONLY"
    assert FINDING_AUTHORITY.value == "OBSERVATION_ONLY"
    assert HYPOTHESIS_AUTHORITY.value == "HYPOTHESIS_ONLY"
    assert VALIDATION_AUTHORITY.value == "ANALYSIS_ONLY"
    assert VALIDATED_KNOWLEDGE_AUTHORITY.value == "INFORMATION_ONLY"
    assert KNOWLEDGE_PROMOTION_AUTHORITY.value == "HUMAN_REVIEW_REQUIRED"
    assert ADVISOR_AUTHORITY.value == "READ_ONLY"
    assert SUPERVISOR_AUTHORITY.value == "READ_ONLY_ANALYSIS"
    assert OPERATIONAL_AUTHORITY.value == "NONE"
    assert EXECUTION_AUTHORITY.value == "NONE"
    assert STRATEGY_MUTATION_AUTHORITY.value == "NONE"
    assert MONEY_MANAGEMENT_MUTATION_AUTHORITY.value == "NONE"
    assert CANONICAL_MUTATION_AUTHORITY.value == "NONE"
