from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.supervisor.contracts import (
    CapitalCondition, HumanAttention, MasterSupervisorDecision, MMRecommendedAction,
    MMSupervisorAssessment, RiskDirection, SupervisorState, TradingRecommendation,
)


NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


def mm_data():
    return {
        "assessmentState": "NORMAL", "recommendedRiskDirection": "MAINTAIN",
        "recommendedRiskMultiplier": "0.75", "capitalCondition": "HEALTHY",
        "confidence": 0.8, "reasons": ["within policy"], "uncertainties": [],
        "recoveryConditions": ["fresh authority"], "sourceEvaluatedAt": NOW,
        "assessedAt": NOW,
    }


def master_data():
    return {
        "overallPosture": "CAUTION", "tradingRecommendation": "CONTINUE_REDUCED",
        "mmRecommendation": {"riskDirection": "REDUCE", "riskMultiplier": "0.5"},
        "humanAttention": "REVIEW", "summary": "Risk remains controlled.",
        "reasons": ["reduced budget"], "conflicts": [], "uncertainties": [],
        "nextReviewConditions": ["authority refresh"], "sourceEvaluatedAt": NOW,
        "decidedAt": NOW,
    }


def test_valid_contracts_are_frozen_and_convert_sequences_to_tuples():
    mm = MMSupervisorAssessment.model_validate(mm_data())
    master = MasterSupervisorDecision.model_validate(master_data())
    assert mm.reasons == ("within policy",)
    assert mm.recommendedRiskMultiplier == Decimal("0.75")
    assert master.mmRecommendation == MMRecommendedAction(
        riskDirection=RiskDirection.REDUCE, riskMultiplier=Decimal("0.5")
    )
    with pytest.raises(ValidationError):
        mm.confidence = 0.1


def test_input_not_mutated_and_serialization_is_stable_and_exact():
    data = mm_data()
    original = deepcopy(data)
    first = MMSupervisorAssessment.model_validate(data)
    second = MMSupervisorAssessment.model_validate(data)
    assert data == original
    assert first.stable_json() == second.stable_json()
    assert '"recommendedRiskMultiplier":"0.75"' in first.stable_json()
    assert first.stable_json().endswith("}")


@pytest.mark.parametrize("change", [
    {"extra": "rejected"}, {"confidence": 1.1}, {"recommendedRiskMultiplier": "-0.1"},
    {"recommendedRiskMultiplier": "NaN"}, {"recommendedRiskMultiplier": "Infinity"},
    {"assessmentState": "NOT_A_STATE"}, {"reasons": [""]},
    {"sourceEvaluatedAt": datetime(2026, 8, 12)},
])
def test_mm_rejects_invalid_input(change):
    data = mm_data()
    data.update(change)
    with pytest.raises(ValidationError):
        MMSupervisorAssessment.model_validate(data)


def test_master_enforces_text_bounds_and_shadow_identity():
    data = master_data()
    data["summary"] = "x" * 301
    with pytest.raises(ValidationError):
        MasterSupervisorDecision.model_validate(data)
    data = master_data()
    data["reasons"] = ["x" * 501]
    with pytest.raises(ValidationError):
        MasterSupervisorDecision.model_validate(data)
    data = master_data()
    data["mode"] = "ACTIVE"
    with pytest.raises(ValidationError):
        MasterSupervisorDecision.model_validate(data)


def test_unknown_is_preserved_without_normalization():
    data = master_data()
    data["overallPosture"] = "UNKNOWN"
    assert MasterSupervisorDecision.model_validate(data).overallPosture is SupervisorState.UNKNOWN
