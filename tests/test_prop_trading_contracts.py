from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.accounts import AccountId, PropPhase, PropProgram
from backend.prop_trading.contracts import (
    PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
    PROP_RULE_DEFINITION_SCHEMA_VERSION,
    PROP_RULE_EVALUATION_SCHEMA_VERSION,
    BreachPolicy,
    Completeness,
    DataQuality,
    EquityComponent,
    EquityComponentState,
    EvaluationState,
    FreshnessState,
    LossModel,
    PropAccountObservation,
    PropRuleDefinition,
    PropRuleEvaluation,
    RuleOperation,
    RuleResult,
    SourceKind,
    VerificationStatus,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ACCOUNT_ID = AccountId("acc_00000000000040008000000000000001")


def rule(**changes):
    values = dict(
        schema_version=PROP_RULE_DEFINITION_SCHEMA_VERSION,
        rule_set_id="hyro-example",
        rule_set_revision=1,
        prop_program=PropProgram.HYROTRADER,
        program_product="EXAMPLE_PLAN",
        phase=PropPhase.CHALLENGE,
        effective_from=NOW,
        initial_balance=Decimal("10000.00"),
        currency="USDT",
        loss_model=LossModel.UNKNOWN,
        day_boundary_timezone="UTC",
        day_boundary_local_time="00:00:00",
        equity_components=(
            EquityComponent("realized_pnl", EquityComponentState.INCLUDED),
            EquityComponent("funding", EquityComponentState.UNKNOWN),
        ),
        breach_policy=BreachPolicy(None, None, ("failure_transition",)),
        source_kind=SourceKind.DOCUMENT,
        source_reference="example-unverified-source",
        source_observed_at=NOW,
        verification_status=VerificationStatus.UNVERIFIED,
        completeness=Completeness.PARTIAL,
        daily_loss_limit_pct=None,
        unknown_fields=("daily_loss_limit_pct",),
    )
    values.update(changes)
    return PropRuleDefinition(**values)


def observation(**changes):
    values = dict(
        schema_version=PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
        observation_id="obs-1",
        account_id=ACCOUNT_ID,
        identity_revision=1,
        observed_at=NOW,
        received_at=NOW,
        source="DEMO_READ",
        source_revision="1",
        freshness=FreshnessState.FRESH,
        quality=DataQuality.COMPLETE,
        currency="USDT",
        balance=Decimal("1000.00000001"),
        equity=Decimal("990.00000001"),
        available_balance=Decimal("900.00000001"),
        realized_pnl=Decimal("-10.125"),
        unrealized_pnl=Decimal("0"),
        open_position_count=0,
        open_order_count=0,
        fees=Decimal("0"),
        funding=Decimal("0"),
        day_start_equity=Decimal("1000.00000001"),
        day_realized_pnl=Decimal("-10.125"),
        day_profit=Decimal("-10.125"),
        total_margin_used=Decimal("0"),
        total_notional=Decimal("0"),
        trading_days_count=0,
    )
    values.update(changes)
    return PropAccountObservation(**values)


def evaluation(**changes):
    values = dict(
        schema_version=PROP_RULE_EVALUATION_SCHEMA_VERSION,
        evaluation_id="eval-1",
        account_id=ACCOUNT_ID,
        rule_set_id="hyro-example",
        rule_set_revision=1,
        observation_id="obs-1",
        evaluated_at=NOW,
        operation=RuleOperation.ENTRY,
        overall_state=EvaluationState.UNKNOWN,
        entry_allowed=None,
        rule_results=(
            RuleResult("DAILY_LOSS", EvaluationState.UNKNOWN, "PERCENT", None, None, None, "RULE_UNKNOWN"),
        ),
        blocking_rule_codes=(),
        unknown_rule_codes=("DAILY_LOSS",),
        warnings=(),
        freshness_state=FreshnessState.FRESH,
        calculation_version="contract-only-v1",
    )
    values.update(changes)
    return PropRuleEvaluation(**values)


def test_decimal_precision_negative_pnl_null_and_zero_round_trip():
    original = observation()
    document = original.to_dict()
    assert document["balance"] == "1000.00000001"
    assert document["realized_pnl"] == "-10.125"
    assert document["unrealized_pnl"] == "0"
    assert document["fees"] == "0"
    partial = observation(
        fees=None, quality=DataQuality.PARTIAL, missing_fields=("fees",)
    )
    assert partial.to_dict()["fees"] is None
    assert PropAccountObservation.from_dict(partial.to_dict()) == partial
    assert PropAccountObservation.from_dict(document) == original


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_nonfinite_values_are_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        observation(equity=value)
    with pytest.raises(ValueError, match="finite"):
        rule(initial_balance=value)


def test_naive_times_and_unknown_schema_are_rejected():
    with pytest.raises(TypeError, match="timezone-aware"):
        observation(observed_at=datetime(2026, 1, 1))
    with pytest.raises(ValueError, match="unsupported"):
        rule(schema_version="v2")
    document = observation().to_dict()
    document["schema_version"] = "v2"
    with pytest.raises(ValueError, match="unsupported"):
        PropAccountObservation.from_dict(document)


def test_deserialize_rejects_unknown_fields_and_non_string_decimals():
    document = observation().to_dict()
    with pytest.raises(ValueError, match="unknown"):
        PropAccountObservation.from_dict({**document, "secret": "x"})
    document["balance"] = 1000.0
    with pytest.raises(TypeError, match="decimal string"):
        PropAccountObservation.from_dict(document)


def test_nested_values_are_immutable_tuples():
    definition = rule()
    assert isinstance(definition.equity_components, tuple)
    with pytest.raises(FrozenInstanceError):
        definition.equity_components[0].state = EquityComponentState.EXCLUDED
    result = evaluation()
    assert isinstance(result.rule_results, tuple)


def test_missing_core_values_must_be_explicit_and_complete_cannot_be_missing():
    with pytest.raises(ValueError, match="missing_fields"):
        observation(equity=None, quality=DataQuality.PARTIAL)
    partial = observation(
        equity=None, quality=DataQuality.PARTIAL, missing_fields=("equity",)
    )
    assert partial.equity is None
    with pytest.raises(ValueError, match="COMPLETE"):
        observation(equity=None, missing_fields=("equity",))


def test_stale_and_unknown_evaluations_cannot_allow_entry_or_pass():
    with pytest.raises(ValueError, match="cannot declare"):
        evaluation(freshness_state=FreshnessState.STALE, entry_allowed=True)
    with pytest.raises(ValueError, match="cannot PASS"):
        evaluation(
            freshness_state=FreshnessState.UNKNOWN,
            overall_state=EvaluationState.PASS,
            entry_allowed=None,
            rule_results=(
                RuleResult("DAILY_LOSS", EvaluationState.PASS, "PERCENT", Decimal("1"), Decimal("5"), Decimal("4"), None),
            ),
            unknown_rule_codes=(),
        )
    unknown = evaluation(freshness_state=FreshnessState.STALE)
    assert unknown.entry_allowed is None


def test_pass_and_block_require_consistent_reason_sets():
    with pytest.raises(ValueError, match="at least one"):
        evaluation(
            overall_state=EvaluationState.PASS,
            entry_allowed=True,
            rule_results=(),
            unknown_rule_codes=(),
        )
    passed = evaluation(
        overall_state=EvaluationState.PASS,
        entry_allowed=True,
        rule_results=(
            RuleResult("DAILY_LOSS", EvaluationState.PASS, "PERCENT", Decimal("1"), Decimal("5"), Decimal("4"), None),
        ),
        unknown_rule_codes=(),
    )
    assert passed.entry_allowed is True
    with pytest.raises(ValueError, match="blocking"):
        evaluation(overall_state=EvaluationState.BLOCK, entry_allowed=False)


def test_non_entry_evaluation_never_declares_entry_permission():
    protective = evaluation(
        operation=RuleOperation.PROTECTIVE,
        overall_state=EvaluationState.PASS,
        entry_allowed=None,
        rule_results=(
            RuleResult("DAILY_LOSS", EvaluationState.PASS, "PERCENT", Decimal("1"), Decimal("5"), Decimal("4"), None),
        ),
        unknown_rule_codes=(),
    )
    assert protective.entry_allowed is None
    with pytest.raises(ValueError, match="non-ENTRY"):
        evaluation(operation=RuleOperation.CANCEL, entry_allowed=False)


def test_rule_definition_round_trip_preserves_unknowns_and_no_default_threshold():
    original = rule()
    restored = PropRuleDefinition.from_dict(original.to_dict())
    assert restored == original
    assert restored.daily_loss_limit_pct is None
    assert restored.unknown_fields == ("daily_loss_limit_pct",)


def test_evaluation_round_trip_preserves_identity_and_references():
    original = evaluation()
    assert PropRuleEvaluation.from_dict(original.to_dict()) == original


def test_f01_block_result_cannot_be_hidden_by_pass_summary_or_replace():
    blocked = RuleResult(
        "DAILY_LOSS", EvaluationState.BLOCK, "PERCENT",
        Decimal("6"), Decimal("5"), Decimal("-1"), "LIMIT_EXCEEDED",
    )
    with pytest.raises(ValueError, match="exactly match"):
        evaluation(
            overall_state=EvaluationState.PASS,
            entry_allowed=True,
            rule_results=(blocked,),
            blocking_rule_codes=(),
            unknown_rule_codes=(),
        )
    valid_block = evaluation(
        overall_state=EvaluationState.BLOCK,
        entry_allowed=False,
        rule_results=(blocked,),
        blocking_rule_codes=("DAILY_LOSS",),
        unknown_rule_codes=(),
    )
    with pytest.raises(ValueError, match="exactly match"):
        replace(
            valid_block,
            overall_state=EvaluationState.PASS,
            entry_allowed=True,
            blocking_rule_codes=(),
        )


def test_f01_valid_pass_block_and_unknown_states_remain_constructible():
    passed = evaluation(
        overall_state=EvaluationState.PASS,
        entry_allowed=True,
        rule_results=(
            RuleResult("DAILY_LOSS", EvaluationState.PASS, "PERCENT", Decimal("1"), Decimal("5"), Decimal("4"), None),
        ),
        blocking_rule_codes=(),
        unknown_rule_codes=(),
    )
    blocked = evaluation(
        overall_state=EvaluationState.BLOCK,
        entry_allowed=False,
        rule_results=(
            RuleResult("DAILY_LOSS", EvaluationState.BLOCK, "PERCENT", Decimal("6"), Decimal("5"), Decimal("-1"), "LIMIT_EXCEEDED"),
        ),
        blocking_rule_codes=("DAILY_LOSS",),
        unknown_rule_codes=(),
    )
    unknown = evaluation()
    assert (passed.entry_allowed, blocked.entry_allowed, unknown.entry_allowed) == (True, False, None)


def test_f01_deserialize_rejects_contradictory_evaluation():
    document = evaluation().to_dict()
    document.update({
        "overall_state": "PASS",
        "entry_allowed": True,
        "rule_results": [{
            "rule_code": "DAILY_LOSS",
            "state": "BLOCK",
            "unit": "PERCENT",
            "actual": "6",
            "threshold": "5",
            "headroom": "-1",
            "reason_code": "LIMIT_EXCEEDED",
        }],
        "blocking_rule_codes": [],
        "unknown_rule_codes": [],
    })
    with pytest.raises(ValueError, match="exactly match"):
        PropRuleEvaluation.from_dict(document)


@pytest.mark.parametrize("field", ["missing_fields", "warnings"])
def test_f03_observation_deserialize_rejects_string_sequence(field):
    document = observation().to_dict()
    document[field] = "ABC"
    with pytest.raises(TypeError, match="must be a list"):
        PropAccountObservation.from_dict(document)


def test_f03_nested_and_evaluation_deserialize_require_json_lists():
    rule_document = rule().to_dict()
    rule_document["unknown_fields"] = "daily_loss_limit_pct"
    with pytest.raises(TypeError, match="must be a list"):
        PropRuleDefinition.from_dict(rule_document)
    evaluation_document = evaluation().to_dict()
    evaluation_document["rule_results"] = "DAILY_LOSS"
    with pytest.raises(TypeError, match="must be a list"):
        PropRuleEvaluation.from_dict(evaluation_document)


def test_f04_warning_fields_accept_typed_codes_not_free_text():
    assert observation(warnings=("SOURCE_DELAYED",)).warnings == ("SOURCE_DELAYED",)
    with pytest.raises(ValueError, match="safe typed codes"):
        observation(warnings=("raw venue error may contain a secret",))


def test_f07_missing_fields_exactly_match_none_values_and_known_names():
    with pytest.raises(ValueError, match="exactly match"):
        observation(quality=DataQuality.PARTIAL, missing_fields=("balance",))
    with pytest.raises(ValueError, match="unsupported"):
        observation(quality=DataQuality.PARTIAL, missing_fields=("not_a_field",))
    partial = observation(
        equity=None,
        quality=DataQuality.PARTIAL,
        missing_fields=("equity",),
    )
    assert partial.missing_fields == ("equity",)
