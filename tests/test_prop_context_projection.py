from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.accounts import (
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
from backend.prop_trading.context_projection import (
    AuthorityObservation,
    PROP_ACCOUNT_CONTEXT_SCHEMA_VERSION,
    build_prop_account_context,
)
from backend.prop_trading.contracts import (
    PROP_RULE_DEFINITION_SCHEMA_VERSION,
    BreachPolicy,
    Completeness,
    EquityComponent,
    EquityComponentState,
    LossModel,
    PropRuleDefinition,
    PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION,
    PROP_RULE_EVALUATION_SCHEMA_VERSION,
    DataQuality,
    EvaluationState,
    FreshnessState,
    PropAccountObservation,
    PropRuleEvaluation,
    RuleOperation,
    SourceKind,
    VerificationStatus,
    RuleResult,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
A1 = AccountId("acc_00000000000040008000000000000001")
A2 = AccountId("acc_00000000000040008000000000000002")


def identity(account_id=A1):
    return AccountIdentity(
        ACCOUNT_IDENTITY_SCHEMA_VERSION, account_id, AccountType.PROP,
        ExecutionMode.EXTERNAL_SIMULATION, ExecutionVenue.BYBIT_DEMO,
        AccountLifecycleState.REGISTERED, 1, NOW, NOW,
        PropProgram.HYROTRADER, PropPhase.CHALLENGE,
    )


def observation(account_id=A1):
    return PropAccountObservation(
        PROP_ACCOUNT_OBSERVATION_SCHEMA_VERSION, "obs-1", account_id, 1,
        NOW, NOW, "DEMO_READ", "1", FreshnessState.UNKNOWN,
        DataQuality.PARTIAL, "USDT", Decimal("0"), None, None,
        Decimal("-1.25"), Decimal("0"), None, 0,
        missing_fields=(
            "equity", "available_balance", "open_position_count", "fees", "funding",
            "day_start_equity", "day_realized_pnl", "day_profit", "total_margin_used",
            "total_notional", "trading_days_count",
        ),
    )


def evaluation(account_id=A1):
    return PropRuleEvaluation(
        PROP_RULE_EVALUATION_SCHEMA_VERSION, "eval-1", account_id,
        "hyro-unverified", 1, "obs-1", NOW, RuleOperation.ENTRY,
        EvaluationState.UNKNOWN, None,
        (RuleResult("DAILY_LOSS", EvaluationState.UNKNOWN, "PERCENT", None, None, None, "MISSING_RULE"),),
        (), ("DAILY_LOSS",), (), FreshnessState.UNKNOWN, "contract-only-v1",
    )


def authority():
    return AuthorityObservation(False, ("RULE_EVALUATION_UNKNOWN",), "READ_ONLY_PROJECTION")


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key.lower()
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def test_context_rejects_observation_and_evaluation_account_mismatch():
    with pytest.raises(ValueError, match="mismatch"):
        build_prop_account_context(
            identity=identity(), observation=observation(A2),
            evaluation=evaluation(), authority=authority(),
        )
    with pytest.raises(ValueError, match="mismatch"):
        build_prop_account_context(
            identity=identity(), observation=observation(),
            evaluation=evaluation(A2), authority=authority(),
        )


def test_context_preserves_unknown_null_zero_and_negative_values():
    document = build_prop_account_context(
        identity=identity(), observation=observation(),
        evaluation=evaluation(), authority=authority(),
        evidence_refs=("evidence/example-1",),
    ).to_dict()
    assert document["schemaVersion"] == PROP_ACCOUNT_CONTEXT_SCHEMA_VERSION
    assert document["availability"] == "PARTIAL"
    assert document["observation"]["balance"] == "0"
    assert document["observation"]["equity"] is None
    assert document["observation"]["realizedPnl"] == "-1.25"
    assert document["ruleEvaluation"]["overallState"] == "UNKNOWN"
    assert document["ruleEvaluation"]["entryAllowed"] is None


def test_context_is_explicitly_read_only_and_never_grants_authority():
    document = build_prop_account_context(
        identity=identity(), observation=observation(),
        evaluation=evaluation(), authority=authority(),
    ).to_dict()
    assert document["readOnly"] is True
    assert document["authority"]["grantsExecutionAuthority"] is False
    assert document["integrationStatus"] == "CC_CONTRACT_NOT_BB_INTEGRATED"


def test_context_contains_no_secret_or_credential_fields():
    document = build_prop_account_context(
        identity=identity(), observation=observation(),
        evaluation=evaluation(), authority=authority(),
    ).to_dict()
    keys = set(walk_keys(document))
    forbidden = {"apikey", "api_key", "secret", "token", "passphrase", "credential_ref", "external_account_ref"}
    assert forbidden.isdisjoint(keys)


def test_context_rejects_revision_reference_and_freshness_mismatches():
    bad_revision = PropAccountObservation.from_dict({
        **observation().to_dict(), "identity_revision": 2,
    })
    with pytest.raises(ValueError, match="revision"):
        build_prop_account_context(
            identity=identity(), observation=bad_revision,
            evaluation=evaluation(), authority=authority(),
        )
    fresh_evaluation = PropRuleEvaluation.from_dict({
        **evaluation().to_dict(), "freshness_state": "FRESH",
    })
    with pytest.raises(ValueError, match="freshness"):
        build_prop_account_context(
            identity=identity(), observation=observation(),
            evaluation=fresh_evaluation, authority=authority(),
        )


def test_evidence_references_are_opaque_and_safe_shaped():
    with pytest.raises(ValueError, match="evidence_refs"):
        build_prop_account_context(
            identity=identity(), observation=observation(),
            evaluation=evaluation(), authority=authority(),
            evidence_refs=("contains spaces and raw payload",),
        )


def complete_observation():
    return replace(
        observation(),
        freshness=FreshnessState.FRESH,
        quality=DataQuality.COMPLETE,
        equity=Decimal("990"),
        available_balance=Decimal("900"),
        open_position_count=0,
        fees=Decimal("0"),
        funding=Decimal("0"),
        day_start_equity=Decimal("1000"),
        day_realized_pnl=Decimal("0"),
        day_profit=Decimal("0"),
        total_margin_used=Decimal("0"),
        total_notional=Decimal("0"),
        trading_days_count=0,
        missing_fields=(),
    )


def pass_evaluation():
    return PropRuleEvaluation(
        PROP_RULE_EVALUATION_SCHEMA_VERSION, "eval-pass", A1,
        "hyro-verified", 1, "obs-1", NOW, RuleOperation.ENTRY,
        EvaluationState.PASS, True,
        (RuleResult("DAILY_LOSS", EvaluationState.PASS, "PERCENT", Decimal("1"), Decimal("5"), Decimal("4"), None),),
        (), (), (), FreshnessState.FRESH, "contract-only-v1",
    )


def rule_definition(**changes):
    values = dict(
        schema_version=PROP_RULE_DEFINITION_SCHEMA_VERSION,
        rule_set_id="hyro-verified",
        rule_set_revision=1,
        prop_program=PropProgram.HYROTRADER,
        program_product="EXAMPLE_PLAN",
        phase=PropPhase.CHALLENGE,
        effective_from=NOW,
        initial_balance=Decimal("10000"),
        currency="USDT",
        loss_model=LossModel.STATIC,
        day_boundary_timezone="UTC",
        day_boundary_local_time="00:00:00",
        equity_components=(EquityComponent("BALANCE", EquityComponentState.INCLUDED),),
        breach_policy=BreachPolicy(0, "FAIL", ()),
        source_kind=SourceKind.OPERATOR_VERIFIED,
        source_reference="verified-rule-ref",
        source_observed_at=NOW,
        verification_status=VerificationStatus.VERIFIED,
        completeness=Completeness.COMPLETE,
    )
    values.update(changes)
    return PropRuleDefinition(**values)


def test_account_bound_snapshot_is_required_before_projection_can_be_ready():
    verified = build_prop_account_context(
        identity=identity(),
        observation=complete_observation(),
        evaluation=pass_evaluation(),
        authority=AuthorityObservation(True, (), "READ_ONLY_PROJECTION"),
        rule_definition=rule_definition(),
    )
    assert verified.availability == "PARTIAL"
    assert verified.to_dict()["ruleEvaluation"]["evaluationTrust"] == "UNVERIFIED"
    assert verified.to_dict()["rulesSnapshotStatus"] == "RULES_SNAPSHOT_REQUIRED"

    partial = build_prop_account_context(
        identity=identity(),
        observation=complete_observation(),
        evaluation=pass_evaluation(),
        authority=AuthorityObservation(True, (), "READ_ONLY_PROJECTION"),
        rule_definition=rule_definition(
            completeness=Completeness.PARTIAL,
            verification_status=VerificationStatus.UNVERIFIED,
            unknown_fields=("daily_loss_limit_pct",),
        ),
    )
    assert partial.availability == "PARTIAL"
    assert partial.to_dict()["ruleEvaluation"]["evaluationTrust"] == "UNVERIFIED"

    expired = build_prop_account_context(
        identity=identity(),
        observation=complete_observation(),
        evaluation=pass_evaluation(),
        authority=AuthorityObservation(True, (), "READ_ONLY_PROJECTION"),
        rule_definition=rule_definition(
            effective_from=NOW - timedelta(days=2),
            effective_to=NOW - timedelta(days=1),
        ),
    )
    assert expired.availability == "PARTIAL"


def test_f04_projection_omits_observation_warning_text_channel():
    document = build_prop_account_context(
        identity=identity(), observation=observation(),
        evaluation=evaluation(), authority=authority(),
    ).to_dict()
    assert "warnings" not in document["observation"]
    with pytest.raises(ValueError, match="safe typed code"):
        AuthorityObservation(False, ("raw reason with secret",), "READ_ONLY_PROJECTION")
