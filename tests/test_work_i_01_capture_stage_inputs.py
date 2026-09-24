"""WORK I P0 focused tests: canonical 15-stage definitions and resolution."""

import pytest

from backend.runtime.cycle_evidence import EvidenceType, LifecycleStage
from backend.runtime.cycle_evidence_stage_inputs import (
    CANONICAL_STAGE_ORDER,
    STAGE_DEFINITIONS,
    StageMismatchError,
    StageUnknownError,
    allowed_evidence_types,
    is_canonical_order,
    resolve_stage,
    stage_name,
    stage_number,
)

EXPECTED_NAMES = (
    "PARAMETER_CONTEXT",
    "MARKET_SELECTION",
    "MARKET_DATA",
    "FEATURE_BUILDER",
    "MICRO_EDGE_STRATEGY",
    "AI_DECISION_REVIEW",
    "MONEY_MANAGEMENT",
    "GOVERNANCE",
    "EXECUTION",
    "POSITION",
    "EXIT_MONITORING",
    "SETTLEMENT_EXIT_EXECUTION",
    "POSITION_CLOSED",
    "TRADE_PARAMETER_PERFORMANCE",
    "READY_FOR_NEXT_TRADE",
)


def test_canonical_order_is_zero_to_fourteen():
    assert CANONICAL_STAGE_ORDER == tuple(range(15))
    assert is_canonical_order(CANONICAL_STAGE_ORDER) is True
    assert is_canonical_order(reversed(CANONICAL_STAGE_ORDER)) is False
    assert is_canonical_order([0, 1, 3]) is False


def test_stage_definitions_cover_all_stages():
    assert tuple(STAGE_DEFINITIONS) == CANONICAL_STAGE_ORDER
    for number, definition in STAGE_DEFINITIONS.items():
        assert definition.number == number
        assert definition.name == EXPECTED_NAMES[number]
        assert definition.evidence_types
        assert definition.description


def test_resolve_by_number_name_and_enum():
    assert resolve_stage(stage=5).name == "AI_DECISION_REVIEW"
    assert resolve_stage(stage="AI_DECISION_REVIEW").number == 5
    assert resolve_stage(stage=LifecycleStage.EXECUTION).number == 8
    assert resolve_stage(stage_number=13, stage_name="TRADE_PARAMETER_PERFORMANCE").number == 13
    assert resolve_stage(stage=2, stage_name="MARKET_DATA").number == 2


def test_stage_number_name_mismatch_rejected():
    with pytest.raises(StageMismatchError):
        resolve_stage(stage=5, stage_name="EXECUTION")
    with pytest.raises(StageMismatchError):
        resolve_stage(stage_number=0, stage_name="MARKET_DATA")


def test_unknown_stage_rejected():
    with pytest.raises(StageUnknownError):
        resolve_stage(stage=15)
    with pytest.raises(StageUnknownError):
        resolve_stage(stage=-1)
    with pytest.raises(StageUnknownError):
        resolve_stage(stage="NOT_A_STAGE")
    with pytest.raises(StageUnknownError):
        resolve_stage()


def test_stage_name_and_number_helpers():
    assert stage_name(8) == "EXECUTION"
    assert stage_number("execution") == 8
    with pytest.raises(StageUnknownError):
        stage_number("NOPE")
    with pytest.raises(StageUnknownError):
        stage_name(99)


def test_allowed_evidence_types_per_stage():
    assert allowed_evidence_types(2) == frozenset({EvidenceType.MARKET_CONTEXT})
    assert EvidenceType.FILL in allowed_evidence_types(8)
    assert EvidenceType.CLOSE_FILL in allowed_evidence_types(11)
    assert EvidenceType.TRADE_PERFORMANCE in allowed_evidence_types(13)
    assert EvidenceType.CYCLE_READINESS in allowed_evidence_types(14)
    assert EvidenceType.MARKET_CONTEXT not in allowed_evidence_types(5)
