#!/usr/bin/env python3
"""Explicitly generate deterministic CC-3H synthetic outcome projections."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from backend.accounts.models import (
    ACCOUNT_IDENTITY_SCHEMA_VERSION, AccountId, AccountIdentity,
    AccountLifecycleState, AccountType, ExecutionMode, ExecutionVenue,
    PropPhase, PropProgram,
)
from backend.prop_trading import (
    ACTIVE_RULES_SELECTION_SCHEMA_VERSION,
    COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION,
    DAILY_BASELINE_SOURCE_SCHEMA_VERSION,
    PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
    PROP_RULE_DEFINITION_SCHEMA_VERSION,
    PROP_RULE_ENGINE_CALCULATION_VERSION,
    REQUIRED_RULE_COVERAGE_SCHEMA_VERSION,
    ActiveRulesSelection, BaselineSourceKind, BreachPolicy,
    CompleteEvaluationBundle, CompleteEvaluationPurpose, Completeness,
    DailyBaselineSource, DataQuality, EquityComponent, EquityComponentState,
    EvaluatorSupportStatus, FreshnessState, GainTreatment, LossModel,
    PropAccountObservation, PropRuleDefinition, RequiredRuleCoverage,
    RuleCoverageItem, RuleCoverageRole, RuleEnginePolicy, RuleOperation,
    RuleProfileStatus, RuleRequirementStatus, RuleType,
    SelectionConfirmationStatus, SelectionPurpose, SelectionSourceKind,
    SnapshotVerificationStatus, ThresholdBoundary, TradingRulesSnapshot,
    ValueBasis, evaluate_complete_bundle,
)
from backend.prop_trading.contracts import SourceKind, VerificationStatus
from backend.prop_trading.outcome_projection import (
    PROP_OUTCOME_READ_ONLY_CONTEXT_SCHEMA_VERSION,
    project_outcome_read_only_context,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
ACCOUNT_ID = AccountId("acc_20000000000040008000000000000002")


def _account() -> AccountIdentity:
    return AccountIdentity(
        schema_version=ACCOUNT_IDENTITY_SCHEMA_VERSION, account_id=ACCOUNT_ID,
        account_type=AccountType.PROP, execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        lifecycle_state=AccountLifecycleState.REGISTERED, revision=3,
        created_at=NOW - timedelta(days=30), updated_at=NOW - timedelta(days=1),
        prop_program=PropProgram.HYROTRADER, prop_phase=PropPhase.CHALLENGE,
    )


def _definition() -> PropRuleDefinition:
    return PropRuleDefinition(
        schema_version=PROP_RULE_DEFINITION_SCHEMA_VERSION,
        rule_set_id="rules-cc-3h-synthetic", rule_set_revision=1,
        prop_program=PropProgram.HYROTRADER,
        program_product="SYNTHETIC-NOT-OFFICIAL", phase=PropPhase.CHALLENGE,
        effective_from=NOW - timedelta(days=20), initial_balance=Decimal("100000"),
        currency="USDT", loss_model=LossModel.STATIC,
        day_boundary_timezone="UTC", day_boundary_local_time="00:00:00",
        equity_components=(
            EquityComponent("UNREALIZED_PNL", EquityComponentState.INCLUDED),
            EquityComponent("FEES", EquityComponentState.INCLUDED),
            EquityComponent("FUNDING", EquityComponentState.INCLUDED),
        ),
        breach_policy=BreachPolicy(0, "SYNTHETIC_BLOCK", ()),
        source_kind=SourceKind.DOCUMENT,
        source_reference="synthetic://cc-3h/rules-not-official",
        source_observed_at=NOW - timedelta(days=2),
        verification_status=VerificationStatus.VERIFIED,
        completeness=Completeness.COMPLETE,
        profit_target_pct=Decimal("10"), daily_loss_limit_pct=Decimal("4"),
        maximum_loss_limit_pct=Decimal("6"), unknown_fields=(),
    )


def _snapshot() -> TradingRulesSnapshot:
    return TradingRulesSnapshot(
        schema_version="tradingai-prop-rules-snapshot/v1",
        snapshot_id="snapshot-cc-3h-synthetic", account_id=ACCOUNT_ID,
        identity_revision=3, execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        prop_program=PropProgram.HYROTRADER, plan_id="SYNTHETIC-NOT-OFFICIAL",
        phase=PropPhase.CHALLENGE, applicable_from=NOW - timedelta(days=10),
        applicable_to=None, rule_definition=_definition(),
        verification_status=SnapshotVerificationStatus.SYNTHETIC,
        verified_at=None, verifier_ref=None,
        source_evidence_refs=("synthetic://cc-3h/rules",),
        unresolved_requirements=(), supersedes_snapshot_id=None,
    )


def _observation(**changes) -> PropAccountObservation:
    values = dict(
        schema_version=PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
        observation_id="observation-cc-3h", account_id=ACCOUNT_ID,
        identity_revision=3, observed_at=NOW - timedelta(seconds=10),
        received_at=NOW - timedelta(seconds=5), source="SYNTHETIC_FIXTURE",
        source_revision="cc-3h-v1", freshness=FreshnessState.FRESH,
        quality=DataQuality.COMPLETE, currency="USDT", balance=Decimal("100000"),
        equity=Decimal("100000"), available_balance=Decimal("90000"),
        realized_pnl=Decimal("0"), unrealized_pnl=Decimal("0"),
        open_position_count=0, open_order_count=0, fees=Decimal("0"),
        funding=Decimal("0"), day_start_equity=Decimal("100000"),
        day_realized_pnl=Decimal("0"), day_profit=Decimal("0"),
        total_margin_used=Decimal("0"), total_notional=Decimal("0"),
        trading_days_count=1, missing_fields=(), warnings=(),
    )
    values.update(changes)
    return PropAccountObservation(**values)


def _baseline(rules: TradingRulesSnapshot) -> DailyBaselineSource:
    return DailyBaselineSource(
        schema_version=DAILY_BASELINE_SOURCE_SCHEMA_VERSION,
        baseline_id="baseline-cc-3h", revision=1, supersedes_baseline_id=None,
        account_id=ACCOUNT_ID, identity_revision=3,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        rules_snapshot_id=rules.snapshot_id, rules_snapshot_digest=rules.content_digest,
        rule_set_id=rules.rule_definition.rule_set_id,
        rule_set_revision=rules.rule_definition.rule_set_revision,
        trading_day=date(2026, 11, 2), timezone_name="UTC",
        day_boundary_local_time="00:00:00", boundary_fold=None,
        effective_at=NOW, observed_at=NOW, captured_at=NOW,
        value_basis=ValueBasis.EQUITY, reference_value=Decimal("100000"),
        currency="USDT", source_kind=BaselineSourceKind.SYNTHETIC_FIXTURE,
        evidence_ref="synthetic://cc-3h/baseline",
        verification_status=SnapshotVerificationStatus.SYNTHETIC,
        completeness=Completeness.COMPLETE, unresolved_requirements=(),
    )


def _policy(required=None, gates=None) -> RuleEnginePolicy:
    return RuleEnginePolicy(
        profile_status=RuleProfileStatus.SYNTHETIC,
        required_rule_codes=required or tuple(item.value for item in RuleType),
        entry_gate_rule_codes=gates if gates is not None else (
            RuleType.STATIC_MAXIMUM_LOSS.value, RuleType.DAILY_LOSS.value),
        observation_max_age=timedelta(minutes=2), future_tolerance=timedelta(seconds=2),
        maximum_loss_basis=ValueBasis.EQUITY, daily_loss_basis=ValueBasis.EQUITY,
        profit_target_basis=ValueBasis.BALANCE,
        loss_boundary=ThresholdBoundary.BREACH_BELOW,
        maximum_loss_gain_treatment=GainTreatment.INCREASES_HEADROOM,
        daily_loss_gain_treatment=GainTreatment.INCREASES_HEADROOM,
    )


def _coverage(rules, *, unsupported=False) -> RequiredRuleCoverage:
    if unsupported:
        items = (RuleCoverageItem(
            "UNSUPPORTED_REQUIRED_RULE", RuleRequirementStatus.UNRESOLVED,
            RuleCoverageRole.ENTRY_RISK_GATE, EvaluatorSupportStatus.UNSUPPORTED,
            ("synthetic://cc-3h/unsupported",), ("RULE_APPLICABILITY_UNRESOLVED",),
        ),)
        completeness = Completeness.PARTIAL
        unresolved = ("REQUIRED_RULE_COVERAGE_INCOMPLETE",)
    else:
        items = tuple(
            RuleCoverageItem(
                code.value, RuleRequirementStatus.CONFIRMED_REQUIRED,
                RuleCoverageRole.PROGRESS_ONLY if code is RuleType.PROFIT_TARGET else RuleCoverageRole.ENTRY_RISK_GATE,
                EvaluatorSupportStatus.SUPPORTED,
                (f"synthetic://cc-3h/{code.value.lower()}",), (),
            ) for code in RuleType
        )
        completeness = Completeness.COMPLETE
        unresolved = ()
    return RequiredRuleCoverage(
        schema_version=REQUIRED_RULE_COVERAGE_SCHEMA_VERSION,
        coverage_id="coverage-cc-3h-unsupported" if unsupported else "coverage-cc-3h",
        account_id=ACCOUNT_ID, identity_revision=3, snapshot_id=rules.snapshot_id,
        snapshot_digest=rules.content_digest, plan_id=rules.plan_id,
        phase=PropPhase.CHALLENGE, evaluator_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
        assessed_at=NOW - timedelta(minutes=2),
        verification_status=SnapshotVerificationStatus.SYNTHETIC,
        completeness=completeness, evidence_refs=("synthetic://cc-3h/coverage",),
        unresolved_requirements=unresolved, items=items,
    )


def _selection(rules) -> ActiveRulesSelection:
    return ActiveRulesSelection(
        schema_version=ACTIVE_RULES_SELECTION_SCHEMA_VERSION,
        selection_id="selection-cc-3h", selection_revision=1,
        supersedes_selection_id=None, account_id=ACCOUNT_ID, identity_revision=3,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        prop_program=PropProgram.HYROTRADER, plan_id=rules.plan_id,
        phase=PropPhase.CHALLENGE, purpose=SelectionPurpose.READ_ONLY_MONITORING,
        snapshot_id=rules.snapshot_id, snapshot_digest=rules.content_digest,
        rule_set_id=rules.rule_definition.rule_set_id,
        rule_set_revision=rules.rule_definition.rule_set_revision,
        effective_from=NOW, effective_to=None, selected_at=NOW - timedelta(minutes=1),
        invalidated_at=None, source_kind=SelectionSourceKind.SYNTHETIC_FIXTURE,
        confirmation_status=SelectionConfirmationStatus.CONFIRMED_FOR_EVALUATION,
        selector_ref="synthetic://cc-3h/selector",
        evidence_refs=("synthetic://cc-3h/selection",), unresolved_requirements=(),
    )


def _bundle(scenario_id, *, observation=None, unsupported=False):
    rules = _snapshot()
    selected_policy = _policy(
        required=("UNSUPPORTED_REQUIRED_RULE",) if unsupported else None,
        gates=("UNSUPPORTED_REQUIRED_RULE",) if unsupported else None,
    )
    return CompleteEvaluationBundle(
        schema_version=COMPLETE_EVALUATION_BUNDLE_SCHEMA_VERSION,
        bundle_id=f"bundle-cc-3h-{scenario_id}",
        purpose=CompleteEvaluationPurpose.HISTORICAL_AS_OF if unsupported else CompleteEvaluationPurpose.READ_ONLY_CURRENT,
        account=_account(), selection=None if unsupported else _selection(rules),
        snapshot=rules, baseline=None if unsupported else _baseline(rules),
        observation=observation or _observation(), policy=selected_policy,
        coverage=_coverage(rules, unsupported=unsupported),
        operation=RuleOperation.ENTRY if unsupported else RuleOperation.READ_ONLY,
        evaluated_at=NOW, knowledge_cutoff_at=NOW,
        evaluator_version=PROP_RULE_ENGINE_CALCULATION_VERSION,
    )


def generate_document() -> dict:
    scenarios = [
        ("calculation_pass", "計算上PASS（取引可能ではない）", _bundle("pass")),
        ("maximum_loss_block", "最大損失BLOCK", _bundle("block", observation=_observation(equity=Decimal("90000")))),
        ("required_information_unknown", "必須情報不足UNKNOWN", _bundle("unknown", observation=_observation(quality=DataQuality.PARTIAL, balance=None, equity=None, missing_fields=("balance", "equity")))),
        ("unsupported_required_rule", "必須ルール未対応", _bundle("unsupported", unsupported=True)),
        ("profit_target_reached", "利益目標到達（Challenge合格ではない）", _bundle("target", observation=_observation(balance=Decimal("111000"), equity=Decimal("111000")))),
    ]
    projected = []
    for scenario_id, label, selected_bundle in scenarios:
        outcome = evaluate_complete_bundle(
            bundle=selected_bundle,
            evaluation_id=f"evaluation-cc-3h-{scenario_id}",
            link_id=f"link-cc-3h-{scenario_id}",
        )
        projected.append({"id": scenario_id, "label": label, "outcome": project_outcome_read_only_context(outcome)})
    projected.append({
        "id": "pre_evaluation_validation_failure",
        "label": "評価前検証失敗（Outcomeなし）",
        "rejection": {
            "stage": "BUNDLE_CONSTRUCTION", "errorCode": "ACCOUNT_SCOPE_MISMATCH",
            "message": "入力scope不一致のため評価前に拒否。Outcomeは生成されません。",
            "outcome": None,
        },
    })
    return {
        "schemaVersion": "tradingai-prop-synthetic-outcome-fixtures/v1",
        "projectionSchemaVersion": PROP_OUTCOME_READ_ONLY_CONTEXT_SCHEMA_VERSION,
        "generatedAt": "2026-11-02T00:00:00Z", "synthetic": True,
        "purpose": "FIXTURE_UI_AND_READ_ONLY_HANDOFF", "scenarios": projected,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = generate_document()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
