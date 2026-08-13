from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.supervisor.contracts import CapitalSource, Freshness, InputValueState
from backend.supervisor.failure_codes import SupervisorBoundaryError, SupervisorFailureCode
from backend.supervisor.snapshot_builder import build_supervisor_snapshot
from backend.supervisor.snapshot_sources import SnapshotFreshnessPolicy


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)


def policy(maximum=timedelta(seconds=30)):
    return SnapshotFreshnessPolicy(
        maximumAgeBySource=tuple(
            (source, maximum) for source in ("bot", "governance", "moneyManagement", "health")
        ),
        futureTolerance=timedelta(seconds=1),
    )


def sources(*, capital_source="PAPER", selected_mode="PAPER", account_source="PAPER_SIMULATION"):
    bot = {
        "sourceEvaluatedAt": NOW,
        "botState": "RUNNING",
        "loopEnabled": True,
        "loopState": "RUNNING",
        "selectedMode": selected_mode,
        "dryRun": selected_mode == "PAPER",
        "autoTradeEnabled": False,
        "realOrderAllowed": selected_mode == "LIVE",
        "accountSource": account_source,
        "governance_state": {"mode": selected_mode, "execution_enabled": selected_mode == "LIVE"},
        "emergency": {"locked": False, "state": "READY"},
        "authoritativeRuntimeState": "SYNCHRONIZED",
        "runtimeSynchronizationState": "HEALTHY",
        "pendingOrderState": "NONE",
        "activeSymbol": "BTC-USDT",
        "market": {"activeSymbol": "BTC-USDT"},
        "marketReady": True,
        "marketStale": False,
        "lastUpdate": NOW,
        "selectionMode": "MANUAL",
        "autoMarketSelection": {"activeSymbol": "BTC-USDT"},
        "tradingDecision": {"status": "HOLD", "evaluatedAt": NOW},
    }
    governance = {
        "sourceEvaluatedAt": NOW,
        "mode": selected_mode,
        "execution_enabled": selected_mode == "LIVE",
        "risk_profile": "SAFE",
        "emergency_stop": False,
        "emergency_state": "READY",
    }
    mm = {
        "capitalEligibility": {
            "capitalAuthority": "MONEY_MANAGEMENT",
            "capitalSource": capital_source,
            "equity": "1000.123456789",
            "availableCapital": "900.123456789",
            "mmMode": "MANUAL",
            "mmRegime": "NORMAL",
            "riskBudget": "10.123456789",
            "remainingExposure": "75.000000001",
            "remainingPositionCapacity": 1,
            "ruinGuardStatus": "UNAVAILABLE",
            "compoundingEnabled": False,
            "executionEntryAllowed": selected_mode == "LIVE",
            "policyVersion": "1.0",
            "evaluatedAt": NOW,
            "authorityFresh": True,
            "reasonCodes": ["WITHIN_POLICY"],
        },
        "metrics": {
            "drawdownPercent": "1.250000001",
            "openExposure": "25.000000001",
            "openPositionState": "UNKNOWN",
            "metricsGeneratedAt": NOW,
        },
    }
    health = {"sourceEvaluatedAt": NOW, "backendStatus": "OK", "runtimeHealthy": True}
    return bot, governance, mm, health


def build(bot, governance, mm, health, *, captured_at=NOW, freshness_policy=None):
    return build_supervisor_snapshot(
        bot_status=bot,
        governance_status=governance,
        money_management_status=mm,
        health_payload=health,
        captured_at=captured_at,
        freshness_policy=freshness_policy or policy(),
    )


def test_normal_paper_mapping_is_fresh_exact_and_deterministic():
    values = sources()
    original = deepcopy(values)
    first = build(*values)
    second = build(*values)
    assert values == original
    assert first.overallFreshness is Freshness.FRESH
    assert first.moneyManagement.capitalSource is CapitalSource.PAPER
    assert first.moneyManagement.equity == Decimal("1000.123456789")
    assert first.moneyManagement.remainingExposure == Decimal("75.000000001")
    assert first.moneyManagement.openPositionState == "UNKNOWN"
    assert first.moneyManagement.ruinGuardStatus == "UNAVAILABLE"
    assert first.moneyManagement.compoundingEnabled is False
    assert first.stable_json() == second.stable_json()
    assert '"equity":"1000.123456789"' in first.stable_json()


def test_live_snapshot_preserves_live_authority_without_recalculating():
    snapshot = build(*sources(capital_source="LIVE_ACCOUNT", selected_mode="LIVE", account_source="LIVE_ACCOUNT"))
    assert snapshot.moneyManagement.capitalSource is CapitalSource.LIVE
    assert snapshot.trade.selectedMode == "LIVE"
    assert snapshot.trade.realOrderAllowed is True
    assert snapshot.moneyManagement.riskBudget == Decimal("10.123456789")


@pytest.mark.parametrize("missing_index, domain", [
    (0, "bot"), (1, "governance"), (2, "moneyManagement"), (3, "health"),
])
def test_missing_sources_remain_missing(missing_index, domain):
    values = list(sources())
    values[missing_index] = None
    snapshot = build(*values)
    target = snapshot.moneyManagement if domain == "moneyManagement" else getattr(snapshot, domain)
    assert target.freshness is Freshness.MISSING
    if domain in {"governance", "moneyManagement", "health"}:
        assert snapshot.overallFreshness is not Freshness.FRESH


def test_null_and_absent_values_are_not_defaulted_to_safe_values():
    bot, governance, mm, health = sources()
    del bot["activeSymbol"]
    bot["market"] = {}
    bot["autoMarketSelection"] = {}
    mm["capitalEligibility"]["capitalAuthority"] = None
    del mm["capitalEligibility"]["riskBudget"]
    snapshot = build(bot, governance, mm, health)
    assert snapshot.market.activeSymbol is None
    assert snapshot.market.selectionSource is None
    assert snapshot.moneyManagement.capitalAuthority is None
    assert snapshot.moneyManagement.riskBudget is None
    assert snapshot.moneyManagement.openPositionState == "UNKNOWN"
    mm_states = {item.field: item.state for item in snapshot.moneyManagement.fieldStates}
    market_states = {item.field: item.state for item in snapshot.market.fieldStates}
    assert mm_states["capitalAuthority"] is InputValueState.NULL
    assert mm_states["riskBudget"] is InputValueState.ABSENT
    assert mm_states["openPositionState"] is InputValueState.UNKNOWN
    assert market_states["activeSymbol"] is InputValueState.ABSENT


@pytest.mark.parametrize("freshness", ["STALE", "MISSING", "CONFLICTED", "UNKNOWN"])
def test_explicit_nonfresh_critical_source_prevents_fresh_overall(freshness):
    bot, governance, mm, health = sources()
    governance["freshness"] = freshness
    snapshot = build(bot, governance, mm, health)
    assert snapshot.governance.freshness is Freshness(freshness)
    assert snapshot.overallFreshness is not Freshness.FRESH


def test_policy_age_marks_critical_source_stale():
    bot, governance, mm, health = sources()
    governance["sourceEvaluatedAt"] = NOW - timedelta(seconds=31)
    snapshot = build(bot, governance, mm, health)
    assert snapshot.governance.freshness is Freshness.STALE
    assert snapshot.overallFreshness is Freshness.STALE
    assert any(item.code is SupervisorFailureCode.INPUT_STALE for item in snapshot.warnings)


def test_missing_timestamp_is_unknown_not_fresh():
    bot, governance, mm, health = sources()
    del health["sourceEvaluatedAt"]
    snapshot = build(bot, governance, mm, health)
    assert snapshot.health.freshness is Freshness.UNKNOWN
    assert snapshot.overallFreshness is Freshness.UNKNOWN


@pytest.mark.parametrize("timestamp, explicit", [
    (NOW + timedelta(seconds=2), None),
    (NOW + timedelta(seconds=2), "STALE"),
    (datetime(2026, 8, 12, 12), None),
])
def test_future_or_timezone_naive_timestamp_is_rejected(timestamp, explicit):
    bot, governance, mm, health = sources()
    governance["sourceEvaluatedAt"] = timestamp
    if explicit is not None:
        governance["freshness"] = explicit
    with pytest.raises(SupervisorBoundaryError) as caught:
        build(bot, governance, mm, health)
    assert caught.value.code is SupervisorFailureCode.TIMESTAMP_INVALID


def test_negative_policy_threshold_is_rejected():
    with pytest.raises(ValueError, match="maximumAge"):
        policy(timedelta(seconds=-1))


@pytest.mark.parametrize("field, value", [
    ("remainingExposure", "-0.1"),
    ("remainingPositionCapacity", -1),
    ("riskBudget", "NaN"),
    ("equity", "Infinity"),
    ("availableCapital", object()),
])
def test_invalid_money_management_values_fail_closed(field, value):
    bot, governance, mm, health = sources()
    mm["capitalEligibility"][field] = value
    with pytest.raises(SupervisorBoundaryError) as caught:
        build(bot, governance, mm, health)
    assert caught.value.code is SupervisorFailureCode.INPUT_INVALID


def test_auto_and_active_symbol_do_not_invent_ams_runtime_facts_or_order_authority():
    bot, governance, mm, health = sources()
    bot["selectionMode"] = "AUTO"
    bot["autoMarketSelection"] = {"activeSymbol": "BTC-USDT"}
    snapshot = build(bot, governance, mm, health)
    assert snapshot.market.selectionMode == "AUTO"
    assert snapshot.market.selectionSource is None
    assert snapshot.market.amsRuntimeState is None
    assert snapshot.market.safeSwitchState is None
    assert snapshot.trade.realOrderAllowed is False


def test_secret_raw_payload_and_traceback_are_never_exposed():
    bot, governance, mm, health = sources()
    bot["env"] = {"API_KEY": "secret-value"}
    health["credential"] = "secret-value"
    governance["traceback"] = "sensitive traceback"
    serialized = build(bot, governance, mm, health).stable_json()
    assert "secret-value" not in serialized
    assert "traceback" not in serialized.lower()
    assert "API_KEY" not in serialized
