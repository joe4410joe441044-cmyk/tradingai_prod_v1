from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP, localcontext
import inspect
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
    ACTIVE_RULES_SELECTION_SCHEMA_VERSION,
    COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION,
    COMPLETE_EVALUATION_OUTCOME_SCHEMA_VERSION,
    DAILY_BASELINE_SOURCE_SCHEMA_VERSION,
    PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
    PROP_RULE_DEFINITION_SCHEMA_VERSION,
    PROP_RULE_ENGINE_CALCULATION_VERSION,
    REQUIRED_RULE_COVERAGE_SCHEMA_VERSION,
    ActiveRulesSelection,
    BaselineSourceKind,
    BreachPolicy,
    CompleteEvaluationBundle,
    CompleteEvaluationOutcome,
    CompleteEvaluationPurpose,
    Completeness,
    DailyBaselineSource,
    DataQuality,
    EquityComponent,
    EquityComponentState,
    EvaluationState,
    EvaluatorSupportStatus,
    FreshnessState,
    GainTreatment,
    LossModel,
    OperationalCandidateStatus,
    PropAccountObservation,
    PropRuleDefinition,
    RequiredRuleCoverage,
    RuleCoverageItem,
    RuleCoverageRole,
    RuleEnginePolicy,
    RuleEvaluationEvidenceLinkV2,
    RuleOperation,
    RuleProfileStatus,
    RuleRequirementStatus,
    RuleType,
    SelectionConfirmationStatus,
    SelectionPurpose,
    SelectionSourceKind,
    SnapshotVerificationStatus,
    canonical_content_digest,
    ThresholdBoundary,
    TradingRulesSnapshot,
    ValueBasis,
    evaluate_complete_bundle,
    resolve_active_selection,
)
from backend.prop_trading.contracts import SourceKind, VerificationStatus


UTC = timezone.utc
NOW = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
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
        rule_set_id="rules-synthetic-bundle",
        rule_set_revision=4,
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
        source_reference="synthetic://cc-3e/rules",
        source_observed_at=NOW - timedelta(days=2),
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
        observation_id="obs-synthetic-bundle",
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
    selected_definition = changes.pop("rule_definition", None) or definition()
    values = dict(
        schema_version="tradingai-prop-rules-snapshot/v1",
        snapshot_id="snapshot-synthetic-bundle",
        account_id=ACCOUNT_ID,
        identity_revision=3,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        prop_program=PropProgram.HYROTRADER,
        plan_id="SYNTHETIC-ONE-STEP",
        phase=PropPhase.CHALLENGE,
        applicable_from=NOW - timedelta(days=10),
        applicable_to=None,
        rule_definition=selected_definition,
        verification_status=SnapshotVerificationStatus.SYNTHETIC,
        verified_at=None,
        verifier_ref=None,
        source_evidence_refs=("synthetic://cc-3e/rules",),
        unresolved_requirements=(),
        supersedes_snapshot_id=None,
    )
    values.update(changes)
    return TradingRulesSnapshot(**values)


def baseline(rules=None, **changes):
    rules = rules or snapshot()
    values = dict(
        schema_version=DAILY_BASELINE_SOURCE_SCHEMA_VERSION,
        baseline_id="baseline-synthetic-bundle",
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
        trading_day=date(2026, 11, 2),
        timezone_name="UTC",
        day_boundary_local_time="00:00:00",
        boundary_fold=None,
        effective_at=NOW,
        observed_at=NOW,
        captured_at=NOW,
        value_basis=ValueBasis.EQUITY,
        reference_value=Decimal("100000"),
        currency="USDT",
        source_kind=BaselineSourceKind.SYNTHETIC_FIXTURE,
        evidence_ref="synthetic://cc-3e/baseline",
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


def selection(rules=None, **changes):
    rules = rules or snapshot()
    values = dict(
        schema_version=ACTIVE_RULES_SELECTION_SCHEMA_VERSION,
        selection_id="selection-synthetic-bundle",
        selection_revision=1,
        supersedes_selection_id=None,
        account_id=ACCOUNT_ID,
        identity_revision=3,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        prop_program=PropProgram.HYROTRADER,
        plan_id=rules.plan_id,
        phase=PropPhase.CHALLENGE,
        purpose=SelectionPurpose.READ_ONLY_MONITORING,
        snapshot_id=rules.snapshot_id,
        snapshot_digest=rules.content_digest,
        rule_set_id=rules.rule_definition.rule_set_id,
        rule_set_revision=rules.rule_definition.rule_set_revision,
        effective_from=NOW,
        effective_to=None,
        selected_at=NOW - timedelta(minutes=1),
        invalidated_at=None,
        source_kind=SelectionSourceKind.SYNTHETIC_FIXTURE,
        confirmation_status=SelectionConfirmationStatus.CONFIRMED_FOR_EVALUATION,
        selector_ref="synthetic://cc-3e/selector",
        evidence_refs=("synthetic://cc-3e/selection",),
        unresolved_requirements=(),
    )
    values.update(changes)
    return ActiveRulesSelection(**values)


def coverage(rules=None, **changes):
    rules = rules or snapshot()
    values = dict(
        schema_version=REQUIRED_RULE_COVERAGE_SCHEMA_VERSION,
        coverage_id="coverage-synthetic-bundle",
        account_id=ACCOUNT_ID,
        identity_revision=3,
        snapshot_id=rules.snapshot_id,
        snapshot_digest=rules.content_digest,
        plan_id=rules.plan_id,
        phase=PropPhase.CHALLENGE,
        evaluator_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
        assessed_at=NOW - timedelta(minutes=2),
        verification_status=SnapshotVerificationStatus.SYNTHETIC,
        completeness=Completeness.COMPLETE,
        evidence_refs=("synthetic://cc-3e/coverage",),
        unresolved_requirements=(),
        items=(
            RuleCoverageItem(
                RuleType.STATIC_MAXIMUM_LOSS.value,
                RuleRequirementStatus.CONFIRMED_REQUIRED,
                RuleCoverageRole.ENTRY_RISK_GATE,
                EvaluatorSupportStatus.SUPPORTED,
                ("synthetic://cc-3e/max-loss",),
                (),
            ),
            RuleCoverageItem(
                RuleType.DAILY_LOSS.value,
                RuleRequirementStatus.CONFIRMED_REQUIRED,
                RuleCoverageRole.ENTRY_RISK_GATE,
                EvaluatorSupportStatus.SUPPORTED,
                ("synthetic://cc-3e/daily-loss",),
                (),
            ),
            RuleCoverageItem(
                RuleType.PROFIT_TARGET.value,
                RuleRequirementStatus.CONFIRMED_REQUIRED,
                RuleCoverageRole.PROGRESS_ONLY,
                EvaluatorSupportStatus.SUPPORTED,
                ("synthetic://cc-3e/target",),
                (),
            ),
        ),
    )
    values.update(changes)
    return RequiredRuleCoverage(**values)


def bundle(**changes):
    rules = changes.pop("snapshot", None) or snapshot()
    values = dict(
        schema_version=COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION,
        bundle_id="bundle-synthetic-current",
        purpose=CompleteEvaluationPurpose.READ_ONLY_CURRENT,
        account=account(),
        selection=selection(rules),
        snapshot=rules,
        baseline=baseline(rules),
        observation=observation(),
        policy=policy(),
        coverage=coverage(rules),
        operation=RuleOperation.READ_ONLY,
        evaluated_at=NOW,
        knowledge_cutoff_at=NOW,
        evaluator_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
    )
    values.update(changes)
    return CompleteEvaluationBundle(**values)


def outcome(selected_bundle=None):
    return evaluate_complete_bundle(
        bundle=selected_bundle or bundle(),
        evaluation_id="evaluation-synthetic-bundle",
        link_id="link-synthetic-bundle-v2",
    )


def test_complete_wrapper_round_trip_is_deterministic_and_authority_free():
    first = outcome()
    second = outcome()
    assert first == second
    assert first.operational_candidate_status is OperationalCandidateStatus.NOT_APPLICABLE
    assert first.execution_authority_granted is False
    assert first.evidence_link.evaluation_digest
    assert CompleteEvaluationOutcome.from_dict(first.to_dict()) == first
    with pytest.raises(FrozenInstanceError):
        first.bundle.bundle_id = "changed"


@pytest.mark.parametrize("mutation", ["state", "reason", "amount", "entry"])
def test_v2_link_rejects_same_id_result_substitution(mutation):
    original = outcome()
    result = original.evaluation
    items = list(result.rule_results)
    if mutation == "state":
        items[0] = replace(
            items[0], state=EvaluationState.BLOCK, reason_code="FORGED_BLOCK"
        )
        forged = replace(
            result,
            overall_state=EvaluationState.BLOCK,
            entry_allowed=None,
            rule_results=tuple(items),
            blocking_rule_codes=(items[0].rule_code,),
        )
    elif mutation == "reason":
        items[-1] = replace(items[-1], reason_code="FORGED_REASON")
        forged = replace(result, rule_results=tuple(items))
    elif mutation == "amount":
        items[0] = replace(items[0], actual=Decimal("999"))
        forged = replace(result, rule_results=tuple(items))
    else:
        entry_bundle = replace(
            original.bundle,
            bundle_id="bundle-entry-substitution",
            purpose=CompleteEvaluationPurpose.HISTORICAL_AS_OF,
            selection=None,
            operation=RuleOperation.ENTRY,
            content_digest="",
        )
        entry_result = evaluate_complete_bundle(
            bundle=entry_bundle,
            evaluation_id="evaluation-entry-substitution",
            link_id="link-entry-substitution",
        )
        result = entry_result.evaluation
        original = entry_result
        forged = replace(
            result,
            operation=RuleOperation.READ_ONLY,
            entry_allowed=None,
        )
    with pytest.raises(ValueError, match="does not match"):
        original.evidence_link.validate_inputs(
            bundle=original.bundle, evaluation=forged
        )


def test_v1_payload_cannot_be_silently_promoted_to_v2():
    data = outcome().evidence_link.to_dict()
    data["schema_version"] = "tradingai-prop-evaluation-evidence-link/v1"
    with pytest.raises(ValueError, match="v1 evidence link cannot be promoted"):
        RuleEvaluationEvidenceLinkV2.from_dict(data)


def test_result_digest_and_link_digest_detect_serialized_tampering():
    data = outcome().to_dict()
    data["evaluation"]["warnings"].append("FORGED_WARNING")
    with pytest.raises(ValueError, match="does not match|content_digest mismatch"):
        CompleteEvaluationOutcome.from_dict(data)
    link_data = outcome().evidence_link.to_dict()
    link_data["evaluation_digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="content_digest mismatch"):
        RuleEvaluationEvidenceLinkV2.from_dict(link_data)


def test_as_of_rejects_future_baseline_but_retroactive_analysis_accepts_it():
    rules = snapshot()
    later = baseline(
        rules,
        observed_at=NOW + timedelta(hours=1),
        captured_at=NOW + timedelta(hours=1, minutes=1),
    )
    with pytest.raises(ValueError, match="baseline observation was unavailable"):
        bundle(snapshot=rules, baseline=later)
    retro = bundle(
        snapshot=rules,
        bundle_id="bundle-retroactive",
        purpose=CompleteEvaluationPurpose.RETROACTIVE_ANALYSIS,
        selection=None,
        baseline=later,
        operation=RuleOperation.READ_ONLY,
        knowledge_cutoff_at=NOW + timedelta(hours=2),
    )
    result = outcome(retro)
    assert result.evidence_link.purpose is CompleteEvaluationPurpose.RETROACTIVE_ANALYSIS
    assert result.operational_candidate_status is OperationalCandidateStatus.NOT_APPLICABLE


def test_future_snapshot_verification_is_not_available_as_of():
    rules = snapshot(verified_at=NOW + timedelta(hours=1))
    with pytest.raises(ValueError, match="snapshot verification was unavailable"):
        bundle(
            snapshot=rules,
            purpose=CompleteEvaluationPurpose.HISTORICAL_AS_OF,
            selection=None,
        )
    retro = bundle(
        snapshot=rules,
        bundle_id="bundle-retro-verified",
        purpose=CompleteEvaluationPurpose.RETROACTIVE_ANALYSIS,
        selection=None,
        operation=RuleOperation.READ_ONLY,
        knowledge_cutoff_at=NOW + timedelta(hours=2),
    )
    assert retro.snapshot.verified_at == NOW + timedelta(hours=1)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"account_id": AccountId("acc_12345678123446789234567812345679")}, "account"),
        ({"phase": PropPhase.VERIFICATION}, "account, plan, or phase"),
        ({"snapshot_digest": "sha256:" + "0" * 64}, "snapshot reference"),
    ],
)
def test_selection_rejects_account_phase_and_digest_mismatch(changes, message):
    rules = snapshot()
    with pytest.raises(ValueError, match=message):
        bundle(snapshot=rules, selection=selection(rules, **changes))


def test_explicit_selection_rejects_ambiguous_and_stale_candidates():
    rules = snapshot()
    selected = selection(rules)
    with pytest.raises(ValueError, match="missing or ambiguous"):
        resolve_active_selection(
            candidates=(selected, selected),
            selection_id=selected.selection_id,
            account=account(),
            snapshot=rules,
            evaluated_at=NOW,
            expected_purpose=SelectionPurpose.READ_ONLY_MONITORING,
        )
    stale = selection(rules, invalidated_at=NOW)
    with pytest.raises(ValueError, match="stale or invalidated"):
        bundle(snapshot=rules, selection=stale)
    expired = snapshot(verification_status=SnapshotVerificationStatus.EXPIRED)
    with pytest.raises(ValueError, match="synthetic selection"):
        bundle(snapshot=expired)


def test_coverage_cannot_fake_evaluator_support_or_duplicate_rules():
    with pytest.raises(ValueError, match="contradicts evaluator capability"):
        coverage(
            items=(
                RuleCoverageItem(
                    "UNSUPPORTED_RULE",
                    RuleRequirementStatus.CONFIRMED_REQUIRED,
                    RuleCoverageRole.ENTRY_RISK_GATE,
                    EvaluatorSupportStatus.SUPPORTED,
                    ("synthetic://cc-3e/unsupported",),
                    (),
                ),
            )
        )
    duplicate = coverage().items[0]
    with pytest.raises(ValueError, match="duplicate rule"):
        coverage(items=(duplicate, duplicate))


def test_missing_and_unsupported_required_coverage_fail_closed():
    rules = snapshot()
    missing = coverage(rules, items=coverage(rules).items[:2])
    with pytest.raises(ValueError, match="do not match coverage"):
        bundle(snapshot=rules, coverage=missing)
    unsupported_item = RuleCoverageItem(
        "UNSUPPORTED_RULE",
        RuleRequirementStatus.UNRESOLVED,
        RuleCoverageRole.ENTRY_RISK_GATE,
        EvaluatorSupportStatus.UNSUPPORTED,
        ("synthetic://cc-3e/unresolved",),
        ("APPLICABILITY_UNRESOLVED",),
    )
    selected_policy = policy(
        required_rule_codes=("UNSUPPORTED_RULE",),
        entry_gate_rule_codes=("UNSUPPORTED_RULE",),
    )
    selected_coverage = coverage(
        rules,
        completeness=Completeness.PARTIAL,
        unresolved_requirements=("RULE_INVENTORY_INCOMPLETE",),
        items=(unsupported_item,),
    )
    selected_bundle = bundle(
        snapshot=rules,
        bundle_id="bundle-unsupported",
        purpose=CompleteEvaluationPurpose.HISTORICAL_AS_OF,
        selection=None,
        baseline=None,
        policy=selected_policy,
        coverage=selected_coverage,
        operation=RuleOperation.ENTRY,
    )
    evaluated = outcome(selected_bundle)
    assert evaluated.evaluation.overall_state is EvaluationState.UNKNOWN
    assert evaluated.evaluation.entry_allowed is None


def test_bundle_rejects_scope_currency_version_and_baseline_mismatch():
    rules = snapshot()
    with pytest.raises(ValueError, match="currency"):
        bundle(snapshot=rules, observation=observation(currency="USD"))
    with pytest.raises(ValueError, match="evaluator version"):
        replace(bundle(), evaluator_version="unsupported/v1", content_digest="")
    wrong_rules = snapshot(snapshot_id="snapshot-other")
    wrong_baseline = baseline(wrong_rules)
    with pytest.raises(ValueError, match="baseline provenance"):
        bundle(snapshot=rules, baseline=wrong_baseline)


def test_bundle_and_nested_contracts_use_strict_serialization():
    original = bundle()
    assert CompleteEvaluationBundle.from_dict(original.to_dict()) == original
    data = original.to_dict()
    data["unknown"] = True
    with pytest.raises(ValueError, match="fields must exactly match"):
        CompleteEvaluationBundle.from_dict(data)
    data = original.to_dict()
    data["selection"]["selection_revision"] = 2
    with pytest.raises(ValueError, match="content_digest mismatch"):
        CompleteEvaluationBundle.from_dict(data)


def test_wrapper_has_no_result_injection_and_reproduces_under_decimal_contexts():
    assert "result" not in inspect.signature(evaluate_complete_bundle).parameters
    outputs = []
    for precision, rounding in ((6, ROUND_DOWN), (50, ROUND_UP)):
        with localcontext() as context:
            context.prec = precision
            context.rounding = rounding
            outputs.append(outcome().to_dict())
    assert outputs[0] == outputs[1]


def test_wrapper_preserves_target_only_entry_fail_closed():
    rules = snapshot()
    target_policy = policy(
        required_rule_codes=(RuleType.PROFIT_TARGET.value,),
        entry_gate_rule_codes=(),
    )
    target_coverage = coverage(
        rules,
        items=(coverage(rules).items[-1],),
    )
    target_bundle = bundle(
        snapshot=rules,
        bundle_id="bundle-target-only",
        purpose=CompleteEvaluationPurpose.HISTORICAL_AS_OF,
        selection=None,
        baseline=None,
        policy=target_policy,
        coverage=target_coverage,
        operation=RuleOperation.ENTRY,
    )
    evaluated = outcome(target_bundle)
    assert evaluated.evaluation.overall_state is EvaluationState.UNKNOWN
    assert evaluated.evaluation.entry_allowed is None


def test_dst_fold_source_remains_fail_closed_in_legacy_engine_projection():
    ny_definition = definition(
        day_boundary_timezone="America/New_York",
        day_boundary_local_time="01:30:00",
    )
    rules = snapshot(
        rule_definition=ny_definition,
        applicable_from=NOW - timedelta(days=10),
    )
    fold_instant = datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    source = baseline(
        rules,
        trading_day=date(2026, 11, 1),
        timezone_name="America/New_York",
        day_boundary_local_time="01:30:00",
        boundary_fold=0,
        effective_at=fold_instant,
        observed_at=fold_instant,
        captured_at=fold_instant,
    )
    observed = observation(
        observed_at=datetime(2026, 11, 1, 6, 59, 50, tzinfo=UTC),
        received_at=datetime(2026, 11, 1, 6, 59, 55, tzinfo=UTC),
    )
    at = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
    selected = CompleteEvaluationBundle(
        schema_version=COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION,
        bundle_id="bundle-dst-fold",
        purpose=CompleteEvaluationPurpose.HISTORICAL_AS_OF,
        account=account(),
        selection=None,
        snapshot=rules,
        baseline=source,
        observation=observed,
        policy=policy(),
        coverage=coverage(rules, assessed_at=at - timedelta(minutes=1)),
        operation=RuleOperation.ENTRY,
        evaluated_at=at,
        knowledge_cutoff_at=at,
        evaluator_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
    )
    evaluated = outcome(selected)
    assert evaluated.evaluation.overall_state is EvaluationState.UNKNOWN
    assert "DAILY_LOSS" in evaluated.evaluation.unknown_rule_codes
    assert evaluated.execution_authority_granted is False


def test_import_and_wrapper_have_no_socket_or_execution_authority(monkeypatch):
    monkeypatch.setattr(
        socket,
        "socket",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("network access is forbidden")
        ),
    )
    evaluated = outcome()
    assert evaluated.execution_authority_granted is False
    assert not hasattr(evaluated, "send_order")

def test_operational_candidate_with_unsupported_coverage_is_unknown_without_authority():
    official_definition = definition(
        rule_set_id="rules-official-like-bundle",
        program_product="ONE_STEP",
        source_reference="fixture://cc-3e/official-like-rules",
    )
    rules = snapshot(
        snapshot_id="snapshot-official-like-bundle",
        rule_definition=official_definition,
        plan_id="ONE_STEP",
        verification_status=SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT,
        verified_at=NOW - timedelta(minutes=3),
        verifier_ref="fixture://cc-3e/verifier",
        source_evidence_refs=("fixture://cc-3e/official-like-evidence",),
    )
    selected = selection(
        rules,
        selection_id="selection-official-like-bundle",
        purpose=SelectionPurpose.OPERATIONAL_CANDIDATE,
        source_kind=SelectionSourceKind.VERIFIED_PROCESS,
        selected_at=NOW - timedelta(minutes=2),
        selector_ref="fixture://cc-3e/verified-selector",
        evidence_refs=("fixture://cc-3e/selection-evidence",),
    )
    unsupported = RuleCoverageItem(
        "UNSUPPORTED_REQUIRED_RULE",
        RuleRequirementStatus.UNRESOLVED,
        RuleCoverageRole.ENTRY_RISK_GATE,
        EvaluatorSupportStatus.UNSUPPORTED,
        ("fixture://cc-3e/coverage-evidence",),
        ("RULE_APPLICABILITY_UNRESOLVED",),
    )
    selected_coverage = coverage(
        rules,
        coverage_id="coverage-official-like-bundle",
        verification_status=SnapshotVerificationStatus.PARTIALLY_VERIFIED,
        completeness=Completeness.PARTIAL,
        unresolved_requirements=("REQUIRED_RULE_COVERAGE_INCOMPLETE",),
        evidence_refs=("fixture://cc-3e/coverage-evidence",),
        items=(unsupported,),
    )
    selected_policy = policy(
        profile_status=RuleProfileStatus.VERIFIED_OFFICIAL,
        required_rule_codes=("UNSUPPORTED_REQUIRED_RULE",),
        entry_gate_rule_codes=("UNSUPPORTED_REQUIRED_RULE",),
    )
    candidate_bundle = CompleteEvaluationBundle(
        schema_version=COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION,
        bundle_id="bundle-official-like-candidate",
        purpose=CompleteEvaluationPurpose.OPERATIONAL_CANDIDATE,
        account=account(),
        selection=selected,
        snapshot=rules,
        baseline=None,
        observation=observation(),
        policy=selected_policy,
        coverage=selected_coverage,
        operation=RuleOperation.ENTRY,
        evaluated_at=NOW,
        knowledge_cutoff_at=NOW,
        evaluator_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
    )
    evaluated = outcome(candidate_bundle)
    assert evaluated.evaluation.overall_state is EvaluationState.UNKNOWN
    assert evaluated.evaluation.entry_allowed is None
    assert (
        evaluated.operational_candidate_status
        is OperationalCandidateStatus.UNKNOWN
    )
    assert evaluated.execution_authority_granted is False

def test_verified_account_coverage_requires_complete_evidence():
    rules = snapshot()
    with pytest.raises(ValueError, match="requires complete evidence"):
        coverage(
            rules,
            verification_status=SnapshotVerificationStatus.VERIFIED_FOR_ACCOUNT,
            evidence_refs=(),
        )


def test_future_coverage_assessment_is_retroactive_only():
    rules = snapshot()
    later_coverage = coverage(
        rules,
        assessed_at=NOW + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="assessment was unavailable"):
        bundle(snapshot=rules, coverage=later_coverage)
    retro = bundle(
        snapshot=rules,
        bundle_id="bundle-retro-coverage",
        purpose=CompleteEvaluationPurpose.RETROACTIVE_ANALYSIS,
        selection=None,
        coverage=later_coverage,
        operation=RuleOperation.READ_ONLY,
        knowledge_cutoff_at=NOW + timedelta(hours=2),
    )
    assert outcome(retro).evidence_link.knowledge_cutoff_at == NOW + timedelta(hours=2)

def test_serialized_entry_permission_tampering_is_rejected():
    historical_entry = replace(
        bundle(),
        bundle_id="bundle-entry-field-tamper",
        purpose=CompleteEvaluationPurpose.HISTORICAL_AS_OF,
        selection=None,
        operation=RuleOperation.ENTRY,
        content_digest="",
    )
    data = outcome(historical_entry).to_dict()
    assert data["evaluation"]["entry_allowed"] is True
    data["evaluation"]["entry_allowed"] = False
    with pytest.raises(ValueError, match="PASS ENTRY evaluation requires"):
        CompleteEvaluationOutcome.from_dict(data)


@pytest.mark.parametrize(
    "changes",
    [
        {"evaluated_at": NOW + timedelta(seconds=1)},
        {"calculation_version": "unsupported/evaluator"},
    ],
)
def test_v2_link_rejects_evaluation_time_or_version_substitution(changes):
    original = outcome()
    forged = replace(original.evaluation, **changes)
    with pytest.raises(ValueError, match="does not match"):
        original.evidence_link.validate_inputs(
            bundle=original.bundle, evaluation=forged
        )

def _redigest_serialized_contract(payload):
    payload["content_digest"] = canonical_content_digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )


def test_as_of_rejects_observation_received_after_knowledge_cutoff():
    late_receipt = observation(received_at=NOW + timedelta(seconds=1))
    with pytest.raises(
        ValueError, match="observation receipt was unavailable at knowledge cutoff"
    ):
        bundle(observation=late_receipt)


def test_observation_receipt_equal_to_cutoff_is_accepted():
    at_cutoff = observation(observed_at=NOW, received_at=NOW)
    evaluated = outcome(bundle(observation=at_cutoff))
    assert evaluated.evaluation.overall_state is EvaluationState.PASS


def test_aggregate_observation_uses_last_required_page_receipt():
    last_page_late = observation(
        source_revision="aggregate-pages-1-3:last-required-page",
        received_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(
        ValueError, match="observation receipt was unavailable at knowledge cutoff"
    ):
        bundle(observation=last_page_late)


def test_serialized_observation_cannot_omit_receipt_time():
    data = observation().to_dict()
    data.pop("received_at")
    with pytest.raises(ValueError, match="missing PROP account observation fields"):
        PropAccountObservation.from_dict(data)


def test_as_of_rejects_future_observation_source_timestamp():
    future = observation(
        observed_at=NOW + timedelta(seconds=1),
        received_at=NOW + timedelta(seconds=1),
    )
    with pytest.raises(
        ValueError, match="observation source time was unavailable at knowledge cutoff"
    ):
        bundle(observation=future)


def test_retroactive_analysis_accepts_later_receipt_with_explicit_cutoff():
    late_receipt = observation(received_at=NOW + timedelta(seconds=1))
    retro = bundle(
        bundle_id="bundle-retro-observation-receipt",
        purpose=CompleteEvaluationPurpose.RETROACTIVE_ANALYSIS,
        selection=None,
        observation=late_receipt,
        operation=RuleOperation.READ_ONLY,
        knowledge_cutoff_at=NOW + timedelta(seconds=1),
    )
    evaluated = outcome(retro)
    assert evaluated.evaluation.overall_state is EvaluationState.PASS
    assert (
        evaluated.operational_candidate_status
        is OperationalCandidateStatus.NOT_APPLICABLE
    )


def test_recomputed_outcome_digest_cannot_forge_candidate_status():
    data = outcome().to_dict()
    data["operational_candidate_status"] = "CANDIDATE_COMPATIBLE"
    _redigest_serialized_contract(data)
    with pytest.raises(
        ValueError,
        match="operational candidate status does not match bundle/evaluation",
    ):
        CompleteEvaluationOutcome.from_dict(data)


def test_outcome_constructor_rederives_candidate_status():
    original = outcome()
    with pytest.raises(
        ValueError,
        match="operational candidate status does not match bundle/evaluation",
    ):
        replace(
            original,
            operational_candidate_status=OperationalCandidateStatus.CANDIDATE_COMPATIBLE,
            content_digest="",
        )


def test_nested_coverage_completeness_tampering_is_rejected():
    data = outcome().to_dict()
    data["bundle"]["coverage"]["completeness"] = "PARTIAL"
    with pytest.raises(ValueError, match="content_digest mismatch"):
        CompleteEvaluationOutcome.from_dict(data)


def test_recomputed_synthetic_to_operational_payload_is_rejected():
    data = outcome().to_dict()
    serialized_bundle = data["bundle"]
    serialized_bundle["purpose"] = "OPERATIONAL_CANDIDATE"
    serialized_bundle["operation"] = "ENTRY"
    _redigest_serialized_contract(serialized_bundle)
    serialized_link = data["evidence_link"]
    serialized_link["purpose"] = "OPERATIONAL_CANDIDATE"
    serialized_link["bundle_digest"] = serialized_bundle["content_digest"]
    _redigest_serialized_contract(serialized_link)
    _redigest_serialized_contract(data)
    with pytest.raises(ValueError, match="selection purpose mismatch"):
        CompleteEvaluationOutcome.from_dict(data)


def test_wrapper_and_round_trip_preserve_pass_block_and_unknown():
    passing = outcome()
    blocked = outcome(
        bundle(
            bundle_id="bundle-blocked-regression",
            observation=observation(equity=Decimal("90000")),
        )
    )
    unknown = outcome(
        bundle(
            bundle_id="bundle-unknown-regression",
            observation=observation(freshness=FreshnessState.STALE),
        )
    )
    assert passing.evaluation.overall_state is EvaluationState.PASS
    assert blocked.evaluation.overall_state is EvaluationState.BLOCK
    assert unknown.evaluation.overall_state is EvaluationState.UNKNOWN
    for evaluated in (passing, blocked, unknown):
        assert CompleteEvaluationOutcome.from_dict(evaluated.to_dict()) == evaluated
        assert evaluated.execution_authority_granted is False
