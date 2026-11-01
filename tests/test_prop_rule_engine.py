from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP, getcontext, localcontext
import socket

import pytest

from backend.accounts.models import (
    ACCOUNT_IDENTITY_SCHEMA_VERSION,
    AccountId,
    AccountIdentity,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
)
from backend.prop_trading import (
    PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
    PROP_DAILY_BASELINE_SCHEMA_VERSION,
    PROP_RULE_DEFINITION_SCHEMA_VERSION,
    BreachPolicy,
    Completeness,
    DailyBaseline,
    DataQuality,
    EquityComponent,
    EquityComponentState,
    EvaluationState,
    FreshnessState,
    GainTreatment,
    LossModel,
    PropAccountObservation,
    PropRuleDefinition,
    PropRuleEngine,
    PropRuleEvaluation,
    RuleEnginePolicy,
    RuleOperation,
    RuleProfileStatus,
    RuleType,
    ThresholdBoundary,
    ValueBasis,
    trading_day_at,
)
from backend.prop_trading.contracts import SourceKind, VerificationStatus


UTC = timezone.utc
ACCOUNT_ID = AccountId("acc_12345678123446789234567812345678")
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def account(**changes):
    values = dict(
        schema_version=ACCOUNT_IDENTITY_SCHEMA_VERSION,
        account_id=ACCOUNT_ID,
        account_type=AccountType.PROP,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        lifecycle_state=AccountLifecycleState.REGISTERED,
        revision=3,
        created_at=NOW - timedelta(days=30),
        updated_at=NOW - timedelta(days=1),
        prop_program=PropProgram.HYROTRADER,
        prop_phase=PropPhase.CHALLENGE,
    )
    values.update(changes)
    return AccountIdentity(**values)


def definition(**changes):
    values = dict(
        schema_version=PROP_RULE_DEFINITION_SCHEMA_VERSION,
        rule_set_id="SYNTHETIC-FOUNDATION-V1",
        rule_set_revision=1,
        prop_program=PropProgram.HYROTRADER,
        program_product="SYNTHETIC-ONE-STEP",
        phase=PropPhase.CHALLENGE,
        effective_from=NOW - timedelta(days=20),
        initial_balance=Decimal("100000.00"),
        currency="USDT",
        loss_model=LossModel.STATIC,
        day_boundary_timezone="UTC",
        day_boundary_local_time="00:00:00",
        equity_components=(
            EquityComponent("UNREALIZED_PNL", EquityComponentState.INCLUDED),
            EquityComponent("FEES", EquityComponentState.INCLUDED),
            EquityComponent("FUNDING", EquityComponentState.INCLUDED),
        ),
        breach_policy=BreachPolicy(0, "SYNTHETIC_BLOCK", ()),
        source_kind=SourceKind.DOCUMENT,
        source_reference="synthetic://cc-3a/foundation-v1",
        source_observed_at=NOW - timedelta(days=1),
        verification_status=VerificationStatus.VERIFIED,
        completeness=Completeness.COMPLETE,
        profit_target_pct=Decimal("10"),
        daily_loss_limit_pct=Decimal("4"),
        maximum_loss_limit_pct=Decimal("6"),
        unknown_fields=(),
    )
    values.update(changes)
    return PropRuleDefinition(**values)


def observation(**changes):
    values = dict(
        schema_version=PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
        observation_id="obs-synthetic-1",
        account_id=ACCOUNT_ID,
        identity_revision=3,
        observed_at=NOW - timedelta(seconds=10),
        received_at=NOW - timedelta(seconds=5),
        source="SYNTHETIC_FIXTURE",
        source_revision="fixture-v1",
        freshness=FreshnessState.FRESH,
        quality=DataQuality.COMPLETE,
        currency="USDT",
        balance=Decimal("100000"),
        equity=Decimal("100000"),
        available_balance=Decimal("90000"),
        realized_pnl=Decimal("-25.50"),
        unrealized_pnl=Decimal("25.50"),
        open_position_count=1,
        open_order_count=0,
        fees=Decimal("-1.25"),
        funding=Decimal("0"),
        day_start_equity=Decimal("100000"),
        day_realized_pnl=Decimal("-25.50"),
        day_profit=Decimal("0"),
        total_margin_used=Decimal("1000"),
        total_notional=Decimal("5000"),
        trading_days_count=1,
        missing_fields=(),
        warnings=(),
    )
    values.update(changes)
    return PropAccountObservation(**values)


def baseline(**changes):
    values = dict(
        schema_version=PROP_DAILY_BASELINE_SCHEMA_VERSION,
        baseline_id="baseline-synthetic-2026-11-01",
        account_id=ACCOUNT_ID,
        rule_set_id="SYNTHETIC-FOUNDATION-V1",
        rule_set_revision=1,
        trading_day=date(2026, 11, 1),
        timezone_name="UTC",
        day_boundary_local_time="00:00:00",
        effective_at=datetime(2026, 11, 1, 0, 0, tzinfo=UTC),
        value_basis=ValueBasis.EQUITY,
        reference_value=Decimal("100000"),
        currency="USDT",
        source="SYNTHETIC_FIXTURE",
        verification_status=VerificationStatus.VERIFIED,
    )
    values.update(changes)
    return DailyBaseline(**values)


def policy(**changes):
    values = dict(
        profile_status=RuleProfileStatus.SYNTHETIC,
        required_rule_codes=tuple(item.value for item in RuleType),
        entry_gate_rule_codes=(
            RuleType.STATIC_MAXIMUM_LOSS.value,
            RuleType.DAILY_LOSS.value,
        ),
        observation_max_age=timedelta(minutes=2),
        future_tolerance=timedelta(seconds=2),
        maximum_loss_basis=ValueBasis.EQUITY,
        daily_loss_basis=ValueBasis.EQUITY,
        profit_target_basis=ValueBasis.BALANCE,
        loss_boundary=ThresholdBoundary.BREACH_BELOW,
        maximum_loss_gain_treatment=GainTreatment.INCREASES_HEADROOM,
        daily_loss_gain_treatment=GainTreatment.INCREASES_HEADROOM,
    )
    values.update(changes)
    return RuleEnginePolicy(**values)


def evaluate(**changes):
    values = dict(
        evaluation_id="eval-synthetic-1",
        account=account(),
        definition=definition(),
        observation=observation(),
        daily_baseline=baseline(),
        evaluated_at=NOW,
        policy=policy(),
    )
    values.update(changes)
    return PropRuleEngine().evaluate(**values)


def result(evaluation, code):
    return next(item for item in evaluation.rule_results if item.rule_code == code)


@pytest.mark.parametrize(
    ("equity", "expected"),
    [("95000", EvaluationState.PASS), ("94000", EvaluationState.PASS), ("93999.9999", EvaluationState.BLOCK)],
)
def test_static_maximum_loss_normal_boundary_and_breach(equity, expected):
    evaluated = evaluate(observation=observation(equity=Decimal(equity)))
    assert result(evaluated, RuleType.STATIC_MAXIMUM_LOSS.value).state is expected


@pytest.mark.parametrize(
    ("equity", "expected"),
    [("97000", EvaluationState.PASS), ("96000", EvaluationState.PASS), ("95999.9999", EvaluationState.BLOCK)],
)
def test_daily_loss_normal_boundary_and_breach(equity, expected):
    evaluated = evaluate(observation=observation(equity=Decimal(equity)))
    assert result(evaluated, RuleType.DAILY_LOSS.value).state is expected


def test_floor_equality_policy_is_explicit():
    evaluated = evaluate(
        observation=observation(equity=Decimal("96000")),
        policy=policy(loss_boundary=ThresholdBoundary.BREACH_AT_OR_BELOW),
    )
    assert result(evaluated, RuleType.DAILY_LOSS.value).state is EvaluationState.BLOCK


@pytest.mark.parametrize(
    ("balance", "state", "reason"),
    [("109999.99", EvaluationState.NOT_APPLICABLE, "TARGET_NOT_REACHED"), ("110000", EvaluationState.PASS, "TARGET_REACHED")],
)
def test_profit_target_not_reached_and_reached(balance, state, reason):
    evaluated = evaluate(observation=observation(balance=Decimal(balance)))
    target = result(evaluated, RuleType.PROFIT_TARGET.value)
    assert (target.state, target.reason_code) == (state, reason)
    assert evaluated.warnings == ("RULE_COMPATIBILITY_ONLY_NO_EXECUTION_AUTHORITY",)


@pytest.mark.parametrize("balance", ["100000", "110000"])
def test_target_only_entry_never_grants_permission(balance):
    evaluated = evaluate(
        observation=observation(balance=Decimal(balance)),
        policy=policy(
            required_rule_codes=(RuleType.PROFIT_TARGET.value,),
            entry_gate_rule_codes=(),
        ),
    )
    assert result(evaluated, RuleType.PROFIT_TARGET.value).reason_code in {
        "TARGET_NOT_REACHED", "TARGET_REACHED",
    }
    assert evaluated.overall_state is EvaluationState.UNKNOWN
    assert evaluated.entry_allowed is None
    assert evaluated.unknown_rule_codes == ("ENTRY_RISK_GATE_SET",)


def test_empty_entry_rule_set_never_grants_permission():
    evaluated = evaluate(policy=policy(required_rule_codes=(), entry_gate_rule_codes=()))
    assert evaluated.overall_state is EvaluationState.UNKNOWN
    assert evaluated.entry_allowed is None
    assert evaluated.unknown_rule_codes == ("ENTRY_RISK_GATE_SET",)


def test_empty_read_only_rule_set_is_not_applicable():
    evaluated = evaluate(
        operation=RuleOperation.READ_ONLY,
        policy=policy(required_rule_codes=(), entry_gate_rule_codes=()),
    )
    assert evaluated.overall_state is EvaluationState.NOT_APPLICABLE
    assert evaluated.entry_allowed is None
    assert evaluated.rule_results == ()


def test_target_progress_remains_available_for_read_only_operation():
    reached = evaluate(
        operation=RuleOperation.READ_ONLY,
        observation=observation(balance=Decimal("110000")),
        policy=policy(
            required_rule_codes=(RuleType.PROFIT_TARGET.value,),
            entry_gate_rule_codes=(),
        ),
    )
    not_reached = evaluate(
        operation=RuleOperation.READ_ONLY,
        policy=policy(
            required_rule_codes=(RuleType.PROFIT_TARGET.value,),
            entry_gate_rule_codes=(),
        ),
    )
    assert (reached.overall_state, reached.entry_allowed) == (EvaluationState.PASS, None)
    assert (not_reached.overall_state, not_reached.entry_allowed) == (
        EvaluationState.NOT_APPLICABLE, None,
    )


def test_profit_target_cannot_be_configured_as_entry_gate():
    with pytest.raises(ValueError, match="profit target"):
        policy(
            required_rule_codes=(RuleType.PROFIT_TARGET.value,),
            entry_gate_rule_codes=(RuleType.PROFIT_TARGET.value,),
        )


def test_block_precedes_unknown_and_never_aggregates_to_pass():
    evaluated = evaluate(observation=observation(equity=Decimal("93000")), daily_baseline=None)
    assert evaluated.overall_state is EvaluationState.BLOCK
    assert evaluated.blocking_rule_codes == (RuleType.STATIC_MAXIMUM_LOSS.value,)
    assert evaluated.unknown_rule_codes == (RuleType.DAILY_LOSS.value,)
    assert evaluated.entry_allowed is False


def test_required_unknown_and_unsupported_rule_never_pass():
    assert evaluate(daily_baseline=None).overall_state is EvaluationState.UNKNOWN
    unsupported = evaluate(
        policy=policy(required_rule_codes=("CONSISTENCY_RULE",), entry_gate_rule_codes=())
    )
    assert unsupported.overall_state is EvaluationState.UNKNOWN
    assert unsupported.unknown_rule_codes == ("CONSISTENCY_RULE", "ENTRY_RISK_GATE_SET")


def test_decimal_precision_and_gain_treatment_are_explicit():
    precise = evaluate(observation=observation(equity=Decimal("100000.0000000000000000001")))
    assert result(precise, RuleType.STATIC_MAXIMUM_LOSS.value).actual == Decimal("-0.0000000000000000001")
    floored = evaluate(
        observation=observation(equity=Decimal("100001")),
        policy=policy(maximum_loss_gain_treatment=GainTreatment.LOSS_USED_FLOOR_ZERO),
    )
    assert result(floored, RuleType.STATIC_MAXIMUM_LOSS.value).actual == Decimal("0")


def test_decimal_boundary_is_independent_of_ambient_context():
    initial = Decimal("100000.1234567890123456789012345")
    percentage = Decimal("6.7891234567890123456789012345")
    exact_floor = Decimal("93210.9916183661781643194710276848416520042661330879437600975")
    current = exact_floor + Decimal("0.00000000000000000001")
    outcomes = []
    for precision, rounding in ((6, ROUND_DOWN), (12, ROUND_UP), (28, ROUND_DOWN), (50, ROUND_UP)):
        with localcontext() as ambient:
            ambient.prec = precision
            ambient.rounding = rounding
            ambient.clear_flags()
            before = ambient.copy()
            evaluated = evaluate(
                definition=definition(
                    initial_balance=initial,
                    maximum_loss_limit_pct=percentage,
                ),
                observation=observation(equity=current),
                policy=policy(
                    required_rule_codes=(RuleType.STATIC_MAXIMUM_LOSS.value,),
                    entry_gate_rule_codes=(RuleType.STATIC_MAXIMUM_LOSS.value,),
                ),
            )
            outcomes.append(result(evaluated, RuleType.STATIC_MAXIMUM_LOSS.value).state)
            assert ambient.prec == before.prec
            assert ambient.rounding == before.rounding
            assert ambient.flags == before.flags
            assert ambient.traps == before.traps
    assert outcomes == [EvaluationState.PASS] * 4


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (Decimal("1" * 65), "DECIMAL_SIGNIFICANT_DIGITS_EXCEEDED"),
        (Decimal("1E+129"), "DECIMAL_EXPONENT_OUT_OF_RANGE"),
        (Decimal("1E-129"), "DECIMAL_EXPONENT_OUT_OF_RANGE"),
    ],
)
def test_decimal_input_range_fails_closed(value, reason):
    evaluated = evaluate(
        definition=definition(initial_balance=value),
        policy=policy(
            required_rule_codes=(RuleType.STATIC_MAXIMUM_LOSS.value,),
            entry_gate_rule_codes=(RuleType.STATIC_MAXIMUM_LOSS.value,),
        ),
    )
    assert result(evaluated, RuleType.STATIC_MAXIMUM_LOSS.value).reason_code == reason
    assert evaluated.overall_state is EvaluationState.UNKNOWN


def test_currency_and_baseline_basis_mismatch_are_unknown_not_zero():
    currency = evaluate(observation=observation(currency="USD"))
    basis = evaluate(daily_baseline=baseline(value_basis=ValueBasis.BALANCE))
    assert currency.overall_state is EvaluationState.UNKNOWN
    assert result(basis, RuleType.DAILY_LOSS.value).reason_code == "BASELINE_VALUE_BASIS_MISMATCH"


def test_unknown_equity_components_are_not_silently_accepted():
    unverified_components = (
        EquityComponent("UNREALIZED_PNL", EquityComponentState.INCLUDED),
        EquityComponent("FEES", EquityComponentState.INCLUDED),
        EquityComponent("FUNDING", EquityComponentState.UNKNOWN),
    )
    evaluated = evaluate(definition=definition(equity_components=unverified_components))
    assert result(evaluated, RuleType.STATIC_MAXIMUM_LOSS.value).reason_code == "EQUITY_COMPONENTS_UNKNOWN"
    assert result(evaluated, RuleType.DAILY_LOSS.value).reason_code == "EQUITY_COMPONENTS_UNKNOWN"


def test_missing_required_equity_is_unknown_while_balance_rule_remains_evaluable():
    evaluated = evaluate(
        observation=observation(
            quality=DataQuality.PARTIAL,
            equity=None,
            missing_fields=("equity",),
        )
    )
    assert result(evaluated, RuleType.STATIC_MAXIMUM_LOSS.value).reason_code == "EQUITY_MISSING"
    assert result(evaluated, RuleType.DAILY_LOSS.value).reason_code == "EQUITY_MISSING"
    assert result(evaluated, RuleType.PROFIT_TARGET.value).state is EvaluationState.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("account_changes", "observation_changes", "definition_changes", "reason"),
    [
        ({}, {"account_id": AccountId("acc_87654321876544318765432187654321")}, {}, "ACCOUNT_SCOPE_MISMATCH"),
        ({}, {"identity_revision": 4}, {}, "IDENTITY_REVISION_MISMATCH"),
        ({"prop_phase": PropPhase.VERIFICATION}, {}, {}, "PROFILE_ACCOUNT_PHASE_MISMATCH"),
    ],
)
def test_account_identity_revision_and_phase_scope_are_fail_closed(
    account_changes, observation_changes, definition_changes, reason
):
    evaluated = evaluate(
        account=account(**account_changes),
        observation=observation(**observation_changes),
        definition=definition(**definition_changes),
    )
    assert evaluated.overall_state is EvaluationState.UNKNOWN
    assert all(item.reason_code == reason for item in evaluated.rule_results)


@pytest.mark.parametrize("invalid", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), True, 1.0])
def test_nan_infinity_bool_and_float_are_rejected(invalid):
    with pytest.raises((TypeError, ValueError)):
        baseline(reference_value=invalid)


def test_negative_pnl_and_positive_profit_are_valid():
    evaluated = evaluate(
        observation=observation(
            balance=Decimal("111000"),
            realized_pnl=Decimal("-500.25"),
            unrealized_pnl=Decimal("11500.25"),
        )
    )
    assert result(evaluated, RuleType.PROFIT_TARGET.value).state is EvaluationState.PASS


def test_balance_and_equity_are_selected_not_substituted():
    observed = observation(balance=Decimal("100000"), equity=Decimal("93000"))
    equity_eval = evaluate(observation=observed)
    balance_eval = evaluate(
        observation=observed,
        policy=policy(maximum_loss_basis=ValueBasis.BALANCE, daily_loss_basis=ValueBasis.BALANCE),
        daily_baseline=baseline(value_basis=ValueBasis.BALANCE),
    )
    assert result(equity_eval, RuleType.STATIC_MAXIMUM_LOSS.value).state is EvaluationState.BLOCK
    assert result(balance_eval, RuleType.STATIC_MAXIMUM_LOSS.value).state is EvaluationState.PASS


def test_missing_reference_is_unknown_not_current_value_fallback():
    evaluated = evaluate(daily_baseline=None)
    assert result(evaluated, RuleType.DAILY_LOSS.value).reason_code == "DAILY_BASELINE_MISSING"


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"account_id": AccountId("acc_87654321876544318765432187654321")}, "BASELINE_ACCOUNT_MISMATCH"),
        ({"rule_set_revision": 2}, "BASELINE_RULE_VERSION_MISMATCH"),
        (
            {
                "trading_day": date(2026, 10, 31),
                "effective_at": datetime(2026, 10, 31, 0, 0, tzinfo=UTC),
            },
            "BASELINE_TRADING_DAY_MISMATCH",
        ),
        ({"effective_at": NOW + timedelta(seconds=1)}, "BASELINE_FROM_FUTURE"),
        ({"effective_at": datetime(2026, 11, 1, 0, 1, tzinfo=UTC)}, "BASELINE_NOT_AT_DAY_BOUNDARY"),
    ],
)
def test_baseline_scope_version_day_and_future_mismatch(changed, reason):
    evaluated = evaluate(daily_baseline=baseline(**changed))
    assert result(evaluated, RuleType.DAILY_LOSS.value).reason_code == reason


@pytest.mark.parametrize(
    ("changed", "reason"),
    [
        ({"timezone_name": "Asia/Tokyo"}, "BASELINE_TIME_BOUNDARY_MISMATCH"),
        ({"verification_status": VerificationStatus.UNVERIFIED}, "BASELINE_UNVERIFIED"),
        ({"currency": "USD"}, "BASELINE_CURRENCY_MISMATCH"),
    ],
)
def test_baseline_timezone_verification_and_currency_are_fail_closed(changed, reason):
    evaluated = evaluate(daily_baseline=baseline(**changed))
    assert result(evaluated, RuleType.DAILY_LOSS.value).reason_code == reason


def test_daily_reset_before_and_after_requires_a_new_baseline():
    before = datetime(2026, 11, 1, 23, 59, 59, tzinfo=UTC)
    after = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
    before_eval = evaluate(
        evaluated_at=before,
        observation=observation(observed_at=before - timedelta(seconds=1), received_at=before),
    )
    after_eval = evaluate(
        evaluated_at=after,
        observation=observation(observed_at=after - timedelta(seconds=1), received_at=after),
    )
    assert result(before_eval, RuleType.DAILY_LOSS.value).state is EvaluationState.PASS
    assert result(after_eval, RuleType.DAILY_LOSS.value).reason_code == "BASELINE_TRADING_DAY_MISMATCH"


def test_dst_fallback_uses_explicit_iana_trading_day():
    first = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    second = datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert trading_day_at(first, "America/New_York", "00:00:00") == date(2026, 11, 1)
    assert trading_day_at(second, "America/New_York", "00:00:00") == date(2026, 11, 1)


@pytest.mark.parametrize(
    "instant",
    [
        datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
        datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
    ],
)
def test_ambiguous_dst_boundary_is_unknown_for_both_folds(instant):
    evaluated_at = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
    evaluated = evaluate(
        definition=definition(
            day_boundary_timezone="America/New_York",
            day_boundary_local_time="01:30:00",
        ),
        observation=observation(
            observed_at=evaluated_at - timedelta(seconds=10),
            received_at=evaluated_at - timedelta(seconds=5),
        ),
        daily_baseline=baseline(
            timezone_name="America/New_York",
            day_boundary_local_time="01:30:00",
            effective_at=instant,
        ),
        evaluated_at=evaluated_at,
        policy=policy(
            required_rule_codes=(RuleType.DAILY_LOSS.value,),
            entry_gate_rule_codes=(RuleType.DAILY_LOSS.value,),
        ),
    )
    assert result(evaluated, RuleType.DAILY_LOSS.value).reason_code == "BASELINE_BOUNDARY_AMBIGUOUS"
    assert evaluated.entry_allowed is None


def test_nonexistent_dst_boundary_is_unknown():
    evaluated_at = datetime(2026, 3, 8, 8, 0, tzinfo=UTC)
    evaluated = evaluate(
        definition=definition(
            day_boundary_timezone="America/New_York",
            day_boundary_local_time="02:30:00",
            effective_from=datetime(2026, 2, 1, tzinfo=UTC),
            source_observed_at=datetime(2026, 2, 1, tzinfo=UTC),
        ),
        observation=observation(
            observed_at=evaluated_at - timedelta(seconds=10),
            received_at=evaluated_at - timedelta(seconds=5),
        ),
        daily_baseline=baseline(
            trading_day=date(2026, 3, 8),
            timezone_name="America/New_York",
            day_boundary_local_time="02:30:00",
            effective_at=datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
        ),
        evaluated_at=evaluated_at,
        policy=policy(
            required_rule_codes=(RuleType.DAILY_LOSS.value,),
            entry_gate_rule_codes=(RuleType.DAILY_LOSS.value,),
        ),
    )
    assert result(evaluated, RuleType.DAILY_LOSS.value).reason_code == "BASELINE_BOUNDARY_NONEXISTENT"


@pytest.mark.parametrize(
    ("observed_at", "freshness", "reason"),
    [
        (NOW + timedelta(seconds=3), FreshnessState.FRESH, "OBSERVATION_FROM_FUTURE"),
        (NOW - timedelta(minutes=3), FreshnessState.FRESH, "OBSERVATION_STALE"),
        (NOW - timedelta(seconds=10), FreshnessState.STALE, "OBSERVATION_NOT_FRESH"),
    ],
)
def test_future_and_stale_observation_are_unknown(observed_at, freshness, reason):
    evaluated = evaluate(
        observation=observation(observed_at=observed_at, received_at=min(observed_at, NOW), freshness=freshness)
    )
    assert all(item.reason_code == reason for item in evaluated.rule_results)


def test_observation_receipt_cannot_precede_source_time():
    evaluated = evaluate(
        observation=observation(
            observed_at=NOW - timedelta(seconds=5),
            received_at=NOW - timedelta(seconds=6),
        )
    )
    assert all(item.reason_code == "OBSERVATION_RECEIPT_PRECEDES_SOURCE" for item in evaluated.rule_results)


def test_partial_observation_passes_when_rule_fields_are_present():
    evaluated = evaluate(
        observation=observation(
            quality=DataQuality.PARTIAL,
            available_balance=None,
            missing_fields=("available_balance",),
        )
    )
    assert evaluated.overall_state is EvaluationState.PASS


def test_unverified_profile_is_unknown():
    evaluated = evaluate(policy=policy(profile_status=RuleProfileStatus.UNVERIFIED))
    assert evaluated.overall_state is EvaluationState.UNKNOWN
    assert all(item.reason_code == "PROFILE_UNVERIFIED" for item in evaluated.rule_results)


def test_official_profile_requires_account_bound_snapshot():
    evaluated = evaluate(
        definition=definition(program_product="ONE_STEP"),
        policy=policy(profile_status=RuleProfileStatus.VERIFIED_OFFICIAL),
    )
    assert evaluated.overall_state is EvaluationState.UNKNOWN
    assert all(
        item.reason_code == "ACCOUNT_RULES_SNAPSHOT_REQUIRED"
        for item in evaluated.rule_results
    )
    assert evaluated.entry_allowed is None


def test_baseline_and_evaluation_serialization_round_trip():
    original_baseline = baseline(reference_value=Decimal("100000.00000001"))
    original_evaluation = evaluate()
    assert DailyBaseline.from_dict(original_baseline.to_dict()) == original_baseline
    assert PropRuleEvaluation.from_dict(original_evaluation.to_dict()) == original_evaluation


def test_constructor_and_evaluation_have_no_socket_or_authority_side_effect(monkeypatch):
    monkeypatch.setattr(socket, "socket", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("socket used")))
    engine = PropRuleEngine()
    evaluated = evaluate()
    assert engine.__dict__ == {}
    assert not hasattr(evaluated, "execution_authority")
    assert evaluated.warnings == ("RULE_COMPATIBILITY_ONLY_NO_EXECUTION_AUTHORITY",)
