from datetime import datetime, timedelta, timezone

from backend.supervisor.authority_mapping import CRITICAL_DOMAINS, DOMAIN_AUTHORITY
from backend.supervisor.contracts import CapitalSource, Freshness
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.snapshot_builder import build_supervisor_snapshot
from backend.supervisor.snapshot_sources import SnapshotFreshnessPolicy


NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)
POLICY = SnapshotFreshnessPolicy(
    maximumAgeBySource=tuple(
        (source, timedelta(seconds=10))
        for source in ("bot", "governance", "moneyManagement", "health")
    )
)


def payloads():
    bot = {
        "sourceEvaluatedAt": NOW, "botState": "RUNNING", "selectedMode": "PAPER",
        "realOrderAllowed": False, "accountSource": "PAPER_SIMULATION",
        "activeSymbol": "BTC-USDT", "market": {"activeSymbol": "BTC-USDT"},
        "autoMarketSelection": {"activeSymbol": "BTC-USDT"},
        "governance_state": {"mode": "PAPER", "execution_enabled": False},
        "emergency": {"locked": False, "state": "READY"},
    }
    governance = {
        "sourceEvaluatedAt": NOW, "mode": "PAPER", "execution_enabled": False,
        "risk_profile": "SAFE", "emergency_stop": False, "emergency_state": "READY",
    }
    mm = {
        "capitalEligibility": {
            "capitalAuthority": "MONEY_MANAGEMENT", "capitalSource": "PAPER",
            "evaluatedAt": NOW, "authorityFresh": True, "executionEntryAllowed": False,
        },
        "metrics": {"metricsGeneratedAt": NOW},
    }
    health = {"sourceEvaluatedAt": NOW, "status": "OK", "runtimeHealthy": True}
    return bot, governance, mm, health


def build(values):
    return build_supervisor_snapshot(
        bot_status=values[0], governance_status=values[1], money_management_status=values[2],
        health_payload=values[3], captured_at=NOW, freshness_policy=POLICY,
    )


def test_authority_table_and_critical_set_are_explicit_and_stable():
    assert dict(DOMAIN_AUTHORITY)["governance"] == "GOVERNANCE_RUNTIME"
    assert dict(DOMAIN_AUTHORITY)["moneyManagement"] == "MONEY_MANAGEMENT_HTTP_BOUNDARY"
    assert CRITICAL_DOMAINS == ("governance", "emergency", "moneyManagement", "health")


def test_governance_owner_wins_but_conflict_is_not_hidden():
    values = list(payloads())
    values[0]["governance_state"]["mode"] = "LIVE"
    snapshot = build(values)
    assert snapshot.governance.mode == "PAPER"
    assert snapshot.governance.freshness is Freshness.CONFLICTED
    assert snapshot.overallFreshness is Freshness.CONFLICTED


def test_emergency_owner_wins_but_conflict_is_not_hidden():
    values = list(payloads())
    values[0]["emergency"]["locked"] = True
    snapshot = build(values)
    assert snapshot.emergency.locked is False
    assert snapshot.emergency.freshness is Freshness.CONFLICTED


def test_paper_live_capital_conflict_becomes_unknown_and_conflicted():
    values = list(payloads())
    values[0]["accountSource"] = "LIVE_ACCOUNT"
    snapshot = build(values)
    assert snapshot.moneyManagement.capitalSource is CapitalSource.UNKNOWN
    assert snapshot.moneyManagement.freshness is Freshness.CONFLICTED


def test_active_symbol_conflict_is_visible_and_owner_value_is_stable():
    values = list(payloads())
    values[0]["autoMarketSelection"]["activeSymbol"] = "ETH-USDT"
    snapshot = build(values)
    assert snapshot.market.activeSymbol == "BTC-USDT"
    assert snapshot.market.freshness is Freshness.CONFLICTED


def test_real_order_conflict_is_converted_to_false():
    values = list(payloads())
    values[0]["realOrderAllowed"] = True
    snapshot = build(values)
    assert snapshot.trade.realOrderAllowed is False
    assert snapshot.execution.realOrderAllowed is False
    assert snapshot.execution.freshness is Freshness.CONFLICTED
    assert any(
        item.code is SupervisorFailureCode.INPUT_CONFLICTED
        and item.field == "realOrderAllowed"
        for item in snapshot.warnings
    )


def test_warning_order_and_deduplication_are_deterministic():
    values = list(payloads())
    values[0]["governance_state"]["mode"] = "LIVE"
    values[0]["emergency"]["state"] = "LOCKED"
    first = build(values)
    second = build(values)
    assert first.warnings == second.warnings
    keys = [(w.code.value, w.domain, w.field, w.message) for w in first.warnings]
    assert keys == sorted(set(keys))
