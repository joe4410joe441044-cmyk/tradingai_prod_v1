from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
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
    DAILY_BASELINE_SOURCE_SCHEMA_VERSION,
    PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
    PROP_RULE_DEFINITION_SCHEMA_VERSION,
    RULE_EVALUATION_EVIDENCE_LINK_SCHEMA_VERSION,
    TRADING_RULES_SNAPSHOT_SCHEMA_VERSION,
    BaselineSourceKind,
    BreachPolicy,
    Completeness,
    DailyBaselineSource,
    DataQuality,
    EquityComponent,
    EquityComponentState,
    EvaluationPurpose,
    FreshnessState,
    GainTreatment,
    LossModel,
    PropAccountObservation,
    PropRuleDefinition,
    PropRuleEngine,
    RuleEnginePolicy,
    RuleEvaluationEvidenceLink,
    RuleProfileStatus,
    RuleType,
    SnapshotVerificationStatus,
    ThresholdBoundary,
    TradingRulesSnapshot,
    ValueBasis,
)
from backend.prop_trading.contracts import SourceKind, VerificationStatus


UTC = timezone.utc
NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
ACCOUNT_ID = AccountId("acc_12345678123446789234567812345678")


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
        initial_balance=Decimal("100000"),
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
        source_reference="synthetic://cc-3c/rules",
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
        observation_id="obs-synthetic-provenance-1",
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
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        open_position_count=0,
        open_order_count=0,
        fees=Decimal("0"),
        funding=Decimal("0"),
        day_start_equity=Decimal("100000"),
        day_realized_pnl=Decimal("0"),
        day_profit=Decimal("0"),
        total_margin_used=Decimal("0"),
        total_notional=Decimal("0"),
        trading_days_count=1,
        missing_fields=(),
        warnings=(),
    )
    values.update(changes)
    return PropAccountObservation(**values)


def snapshot(**changes):
    values = dict(
        schema_version=TRADING_RULES_SNAPSHOT_SCHEMA_VERSION,
        snapshot_id="rules-synthetic-cc3c-1",
        account_id=ACCOUNT_ID,
        identity_revision=3,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        prop_program=PropProgram.HYROTRADER,
        plan_id="SYNTHETIC-ONE-STEP",
        phase=PropPhase.CHALLENGE,
        applicable_from=NOW - timedelta(days=10),
        applicable_to=None,
        rule_definition=definition(),
        verification_status=SnapshotVerificationStatus.SYNTHETIC,
        verified_at=None,
        verifier_ref=None,
        source_evidence_refs=("synthetic://cc-3c/rules",),
        unresolved_requirements=(),
        supersedes_snapshot_id=None,
    )
    values.update(changes)
    return TradingRulesSnapshot(**values)


def baseline_source(**changes):
    rules = changes.pop("rules", None) or snapshot()
    values = dict(
        schema_version=DAILY_BASELINE_SOURCE_SCHEMA_VERSION,
        baseline_id="baseline-synthetic-2026-11-01",
        revision=1,
        supersedes_baseline_id=None,
        account_id=ACCOUNT_ID,
        identity_revision=3,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        rules_snapshot_id=rules.snapshot_id,
        rules_snapshot_digest=rules.content_digest,
        rule_set_id=rules.rule_definition.rule_set_id,
        rule_set_revision=rules.rule_definition.rule_set_revision,
        trading_day=date(2026, 11, 1),
        timezone_name="UTC",
        day_boundary_local_time="00:00:00",
        boundary_fold=None,
        effective_at=datetime(2026, 11, 1, 0, 0, tzinfo=UTC),
        observed_at=datetime(2026, 11, 1, 0, 0, tzinfo=UTC),
        captured_at=datetime(2026, 11, 1, 0, 1, tzinfo=UTC),
        value_basis=ValueBasis.EQUITY,
        reference_value=Decimal("100000"),
        currency="USDT",
        source_kind=BaselineSourceKind.SYNTHETIC_FIXTURE,
        evidence_ref="synthetic://cc-3c/baseline",
        verification_status=SnapshotVerificationStatus.SYNTHETIC,
        completeness=Completeness.COMPLETE,
        unresolved_requirements=(),
    )
    values.update(changes)
    return DailyBaselineSource(**values)


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


def evaluated(rules=None, baseline=None, observed=None, selected_policy=None):
    rules = rules or snapshot()
    baseline = baseline or baseline_source(rules=rules)
    observed = observed or observation()
    selected_policy = selected_policy or policy()
    result = PropRuleEngine().evaluate(
        evaluation_id="eval-synthetic-provenance-1",
        account=account(),
        definition=rules.rule_definition,
        observation=observed,
        daily_baseline=baseline.to_daily_baseline(),
        evaluated_at=NOW,
        policy=selected_policy,
    )
    return rules, baseline, observed, selected_policy, result


def link(**changes):
    rules, baseline, observed, selected_policy, result = evaluated()
    values = dict(
        link_id="link-synthetic-provenance-1",
        purpose=EvaluationPurpose.HISTORICAL_REPLAY,
        account=account(),
        observation=observed,
        snapshot=rules,
        baseline=baseline,
        policy=selected_policy,
        evaluation=result,
    )
    values.update(changes)
    return RuleEvaluationEvidenceLink.bind(**values)


def test_snapshot_round_trip_is_immutable_and_digest_stable():
    original = snapshot()
    restored = TradingRulesSnapshot.from_dict(original.to_dict())
    assert restored == original
    assert restored.content_digest.startswith("sha256:")
    with pytest.raises(FrozenInstanceError):
        restored.plan_id = "CHANGED"


def test_snapshot_digest_detects_content_change():
    data = snapshot().to_dict()
    data["plan_id"] = "SYNTHETIC-CHANGED"
    data["rule_definition"]["program_product"] = "SYNTHETIC-CHANGED"
    with pytest.raises(ValueError, match="content_digest mismatch"):
        TradingRulesSnapshot.from_dict(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"plan_id": "SYNTHETIC-WRONG"},
        {"phase": PropPhase.FUNDED},
        {"prop_program": "UNKNOWN"},
    ],
)
def test_snapshot_program_plan_and_phase_mismatch_are_rejected(changes):
    with pytest.raises((TypeError, ValueError)):
        snapshot(**changes)


def test_snapshot_schema_and_verification_invariants_are_strict():
    data = snapshot().to_dict()
    data["schema_version"] = "unknown/v1"
    with pytest.raises(ValueError, match="unsupported"):
        TradingRulesSnapshot.from_dict(data)
    data = snapshot().to_dict()
    data["source_evidence_refs"] = "synthetic://not-a-list"
    with pytest.raises(TypeError, match="must be a list"):
        TradingRulesSnapshot.from_dict(data)
    with pytest.raises(ValueError, match="unresolved"):
        snapshot(verification_status=SnapshotVerificationStatus.PARTIALLY_VERIFIED)
    with pytest.raises(ValueError, match="complete account evidence"):
        snapshot(verification_status=SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT)


def test_snapshot_binds_exact_account_mode_venue_revision_and_phase():
    rules = snapshot()
    assert rules.binds(account())
    assert not rules.binds(account(revision=4))
    assert not rules.binds(account(execution_venue=ExecutionVenue.BLOFIN_DEMO))
    assert not rules.binds(account(prop_phase=PropPhase.FUNDED))


def test_baseline_source_round_trip_and_daily_projection():
    source = baseline_source(reference_value=Decimal("100000.00000001"))
    restored = DailyBaselineSource.from_dict(source.to_dict())
    assert restored == source
    daily = restored.to_daily_baseline()
    assert daily.baseline_id == source.baseline_id
    assert daily.reference_value == source.reference_value
    assert daily.verification_status is VerificationStatus.VERIFIED


@pytest.mark.parametrize(
    ("fold", "instant"),
    [
        (0, datetime(2026, 11, 1, 5, 30, tzinfo=UTC)),
        (1, datetime(2026, 11, 1, 6, 30, tzinfo=UTC)),
    ],
)
def test_baseline_source_resolves_explicit_dst_fold(fold, instant):
    source = baseline_source(
        trading_day=date(2026, 11, 1),
        timezone_name="America/New_York",
        day_boundary_local_time="01:30:00",
        boundary_fold=fold,
        effective_at=instant,
        observed_at=instant,
        captured_at=instant + timedelta(minutes=1),
    )
    assert source.boundary_fold == fold
    assert source.effective_at == instant


def test_baseline_source_rejects_ambiguous_or_nonexistent_boundary_without_resolution():
    with pytest.raises(ValueError, match="requires fold"):
        baseline_source(
            timezone_name="America/New_York",
            day_boundary_local_time="01:30:00",
            effective_at=datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
            observed_at=datetime(2026, 11, 1, 5, 30, tzinfo=UTC),
            captured_at=datetime(2026, 11, 1, 5, 31, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="requires fold"):
        baseline_source(
            timezone_name="America/New_York",
            day_boundary_local_time="01:30:00",
            boundary_fold=True,
            effective_at=datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
            observed_at=datetime(2026, 11, 1, 6, 30, tzinfo=UTC),
            captured_at=datetime(2026, 11, 1, 6, 31, tzinfo=UTC),
        )
    with pytest.raises(ValueError, match="nonexistent"):
        baseline_source(
            trading_day=date(2026, 3, 8),
            timezone_name="America/New_York",
            day_boundary_local_time="02:30:00",
            effective_at=datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
            observed_at=datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
            captured_at=datetime(2026, 3, 8, 7, 31, tzinfo=UTC),
        )


def test_baseline_source_digest_and_strict_schema_detect_tampering():
    data = baseline_source().to_dict()
    data["reference_value"] = "99999"
    with pytest.raises(ValueError, match="content_digest mismatch"):
        DailyBaselineSource.from_dict(data)
    data = baseline_source().to_dict()
    data["unexpected"] = True
    with pytest.raises(ValueError, match="exactly match"):
        DailyBaselineSource.from_dict(data)


def test_synthetic_source_name_never_promotes_baseline_to_verified_account():
    source = baseline_source()
    assert source.verification_status is SnapshotVerificationStatus.SYNTHETIC
    with pytest.raises(ValueError, match="non-synthetic"):
        baseline_source(
            verification_status=SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT
        )


def test_historical_evaluation_link_retains_and_validates_all_references():
    rules, baseline, observed, selected_policy, result = evaluated()
    evidence = RuleEvaluationEvidenceLink.bind(
        link_id="link-synthetic-provenance-1",
        purpose=EvaluationPurpose.HISTORICAL_REPLAY,
        account=account(),
        observation=observed,
        snapshot=rules,
        baseline=baseline,
        policy=selected_policy,
        evaluation=result,
    )
    restored = RuleEvaluationEvidenceLink.from_dict(evidence.to_dict())
    assert restored == evidence
    assert restored.rules_snapshot_id == rules.snapshot_id
    assert restored.rules_snapshot_digest == rules.content_digest
    assert restored.baseline_id == baseline.baseline_id
    assert restored.baseline_digest == baseline.content_digest
    assert restored.observation_id == observed.observation_id
    restored.validate_inputs(
        account=account(),
        observation=observed,
        snapshot=rules,
        baseline=baseline,
        policy=selected_policy,
        evaluation=result,
    )


def test_evaluation_link_detects_digest_tampering():
    data = link().to_dict()
    data["baseline_revision"] = 2
    with pytest.raises(ValueError, match="content_digest mismatch"):
        RuleEvaluationEvidenceLink.from_dict(data)


def test_evaluation_link_rejects_snapshot_account_and_baseline_mismatch():
    rules, baseline, observed, selected_policy, result = evaluated()
    with pytest.raises(ValueError, match="snapshot account binding"):
        RuleEvaluationEvidenceLink.bind(
            link_id="link-mismatch-account",
            purpose=EvaluationPurpose.HISTORICAL_REPLAY,
            account=account(revision=4),
            observation=observed,
            snapshot=rules,
            baseline=baseline,
            policy=selected_policy,
            evaluation=result,
        )
    wrong_baseline = baseline_source(
        rules=rules,
        rules_snapshot_id="rules-synthetic-other",
    )
    with pytest.raises(ValueError, match="baseline provenance"):
        RuleEvaluationEvidenceLink.bind(
            link_id="link-mismatch-baseline",
            purpose=EvaluationPurpose.HISTORICAL_REPLAY,
            account=account(),
            observation=observed,
            snapshot=rules,
            baseline=wrong_baseline,
            policy=selected_policy,
            evaluation=result,
        )


def test_evaluation_link_rejects_inapplicable_snapshot_and_unknown_evaluator():
    rules, baseline, observed, selected_policy, result = evaluated()
    future_rules = snapshot(applicable_from=NOW + timedelta(seconds=1))
    future_baseline = baseline_source(rules=future_rules)
    future_result = PropRuleEngine().evaluate(
        evaluation_id="eval-future-snapshot",
        account=account(),
        definition=future_rules.rule_definition,
        observation=observed,
        daily_baseline=future_baseline.to_daily_baseline(),
        evaluated_at=NOW,
        policy=selected_policy,
    )
    with pytest.raises(ValueError, match="not applicable"):
        RuleEvaluationEvidenceLink.bind(
            link_id="link-inapplicable-snapshot",
            purpose=EvaluationPurpose.HISTORICAL_REPLAY,
            account=account(),
            observation=observed,
            snapshot=future_rules,
            baseline=future_baseline,
            policy=selected_policy,
            evaluation=future_result,
        )
    with pytest.raises(ValueError, match="evaluator version"):
        RuleEvaluationEvidenceLink.bind(
            link_id="link-unsupported-evaluator",
            purpose=EvaluationPurpose.HISTORICAL_REPLAY,
            account=account(),
            observation=observed,
            snapshot=rules,
            baseline=baseline,
            policy=selected_policy,
            evaluation=replace(result, calculation_version="unsupported/v1"),
        )


def test_evaluation_link_rejects_baseline_basis_or_reset_mismatch():
    rules, baseline, observed, selected_policy, result = evaluated()
    wrong_basis = baseline_source(rules=rules, value_basis=ValueBasis.BALANCE)
    with pytest.raises(ValueError, match="baseline provenance"):
        RuleEvaluationEvidenceLink.bind(
            link_id="link-wrong-baseline-basis",
            purpose=EvaluationPurpose.HISTORICAL_REPLAY,
            account=account(),
            observation=observed,
            snapshot=rules,
            baseline=wrong_basis,
            policy=selected_policy,
            evaluation=result,
        )


def test_evaluation_link_requires_baseline_exactly_when_daily_rule_is_selected():
    rules, baseline, observed, selected_policy, result = evaluated()
    with pytest.raises(ValueError, match="requires baseline"):
        RuleEvaluationEvidenceLink.bind(
            link_id="link-missing-baseline",
            purpose=EvaluationPurpose.HISTORICAL_REPLAY,
            account=account(),
            observation=observed,
            snapshot=rules,
            baseline=None,
            policy=selected_policy,
            evaluation=result,
        )
    no_daily_policy = policy(
        required_rule_codes=(RuleType.STATIC_MAXIMUM_LOSS.value,),
        entry_gate_rule_codes=(RuleType.STATIC_MAXIMUM_LOSS.value,),
    )
    no_daily_result = PropRuleEngine().evaluate(
        evaluation_id="eval-no-daily",
        account=account(),
        definition=rules.rule_definition,
        observation=observed,
        daily_baseline=None,
        evaluated_at=NOW,
        policy=no_daily_policy,
    )
    with pytest.raises(ValueError, match="unexpected"):
        RuleEvaluationEvidenceLink.bind(
            link_id="link-unexpected-baseline",
            purpose=EvaluationPurpose.HISTORICAL_REPLAY,
            account=account(),
            observation=observed,
            snapshot=rules,
            baseline=baseline,
            policy=no_daily_policy,
            evaluation=no_daily_result,
        )


@pytest.mark.parametrize(
    "status",
    [
        SnapshotVerificationStatus.SYNTHETIC,
        SnapshotVerificationStatus.UNVERIFIED,
        SnapshotVerificationStatus.SUPERSEDED,
        SnapshotVerificationStatus.EXPIRED,
    ],
)
def test_non_operational_snapshot_states_cannot_create_current_entry_link(status):
    rules = snapshot(verification_status=status)
    baseline = baseline_source(rules=rules)
    observed = observation()
    selected_policy = policy()
    result = PropRuleEngine().evaluate(
        evaluation_id="eval-current-rejected",
        account=account(),
        definition=rules.rule_definition,
        observation=observed,
        daily_baseline=baseline.to_daily_baseline(),
        evaluated_at=NOW,
        policy=selected_policy,
    )
    with pytest.raises(ValueError, match="not eligible"):
        RuleEvaluationEvidenceLink.bind(
            link_id="link-current-rejected",
            purpose=EvaluationPurpose.CURRENT_ENTRY,
            account=account(),
            observation=observed,
            snapshot=rules,
            baseline=baseline,
            policy=selected_policy,
            evaluation=result,
        )


def test_contract_import_and_construction_have_no_socket_or_authority_side_effect(monkeypatch):
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("socket used")),
    )
    rules = snapshot()
    baseline = baseline_source(rules=rules)
    evidence = link()
    assert rules.verification_status is SnapshotVerificationStatus.SYNTHETIC
    assert baseline.source_kind is BaselineSourceKind.SYNTHETIC_FIXTURE
    assert not hasattr(evidence, "execution_authority")
