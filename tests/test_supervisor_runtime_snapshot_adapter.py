from copy import deepcopy
from datetime import datetime, timezone

from backend.supervisor.contracts import Freshness
from backend.supervisor.runtime_snapshot_adapter import (
    RuntimeAuthorityReaders,
    RuntimeSnapshotAdapter,
)


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)


def authority_payloads():
    return {
        "bot": {
            "timestamp": NOW,
            "botState": "STOPPED",
            "loopEnabled": False,
            "loopState": "STOPPED",
            "selectedMode": "PAPER",
            "dryRun": True,
            "autoTradeEnabled": False,
            "realOrderAllowed": False,
            "accountSource": "PAPER_SIMULATION",
            "governance_state": {"mode": "PAPER", "execution_enabled": False},
            "emergency": {"locked": False, "state": "READY"},
            "authoritativeRuntimeState": "STOPPED",
            "runtimeSynchronizationState": "OFFLINE",
            "pendingOrderState": "NONE",
            "activeSymbol": "BTC-USDT",
            "marketReady": False,
            "marketStale": True,
            "selectionMode": "AUTO",
            "autoMarketSelection": {"activeSymbol": "BTC-USDT"},
            "tradingDecision": {"status": "HOLD", "evaluatedAt": NOW},
            "apiKeyStatus": "SECRET_VALUE_MUST_NOT_LEAK",
            "arbitrary": {"credential": "SECRET_VALUE_MUST_NOT_LEAK"},
        },
        "governance": {
            "sourceEvaluatedAt": NOW,
            "mode": "PAPER",
            "execution_enabled": False,
            "risk_profile": "SAFE",
            "emergency_stop": False,
            "emergency_state": "READY",
            "last_emergency_result": {"traceback": "SECRET_VALUE_MUST_NOT_LEAK"},
        },
        "moneyManagement": {
            "generatedAt": NOW,
            "capitalEligibility": {
                "capitalAuthority": "MONEY_MANAGEMENT",
                "capitalSource": "PAPER",
                "equity": "1000.123456789123456789",
                "availableCapital": "900.123456789123456789",
                "mmMode": "MANUAL",
                "mmRegime": "NORMAL",
                "riskBudget": "10.000000000000000001",
                "remainingExposure": "75.000000000000000001",
                "remainingPositionCapacity": "1",
                "ruinGuardStatus": "UNAVAILABLE",
                "compoundingEnabled": False,
                "executionEntryAllowed": False,
                "policyVersion": "1.0",
                "evaluatedAt": NOW,
                "authorityFresh": True,
            },
            "metrics": {
                "drawdownPercent": "1.000000000000000001",
                "openExposure": "25.000000000000000001",
                "openPositionState": "NONE",
                "metricsGeneratedAt": NOW,
            },
            "configuration": {"private": "SECRET_VALUE_MUST_NOT_LEAK"},
            "cashFlowAuthority": {"credential": "SECRET_VALUE_MUST_NOT_LEAK"},
        },
        "health": {
            "sourceEvaluatedAt": NOW,
            "status": "ok",
            "runtimeHealthy": True,
            "environment": "SECRET_VALUE_MUST_NOT_LEAK",
        },
    }


def adapter_for(payloads, *, command_calls=None):
    command_calls = command_calls if command_calls is not None else []

    def reader(name):
        def read(_app, _captured_at):
            return payloads[name]
        return read

    readers = RuntimeAuthorityReaders(
        bot=reader("bot"),
        governance=reader("governance"),
        moneyManagement=reader("moneyManagement"),
        health=reader("health"),
    )
    return RuntimeSnapshotAdapter(readers=readers, clock=lambda: NOW)


def test_adapter_is_allowlisted_exact_and_does_not_mutate_authorities():
    payloads = authority_payloads()
    before = deepcopy(payloads)
    snapshot = adapter_for(payloads).build(object())
    serialized = snapshot.stable_json()

    assert payloads == before
    assert snapshot.overallFreshness is Freshness.FRESH
    assert snapshot.bot.status == "STOPPED"
    assert snapshot.loop.state == "STOPPED"
    assert snapshot.trade.autoTradeEnabled is False
    assert snapshot.execution.realOrderAllowed is False
    assert snapshot.market.selectionMode == "AUTO"
    assert snapshot.market.amsRuntimeState is None
    assert '"equity":"1000.123456789123456789"' in serialized
    assert "SECRET_VALUE_MUST_NOT_LEAK" not in serialized
    assert "configuration" not in serialized
    assert "cashFlowAuthority" not in serialized


def test_individual_reader_failures_become_missing_partial_snapshot():
    payloads = authority_payloads()

    def failed(_app, _captured_at):
        raise RuntimeError("traceback SECRET_VALUE_MUST_NOT_LEAK")

    readers = RuntimeAuthorityReaders(
        bot=lambda _app, _at: payloads["bot"],
        governance=failed,
        moneyManagement=lambda _app, _at: payloads["moneyManagement"],
        health=failed,
    )
    snapshot = RuntimeSnapshotAdapter(readers=readers, clock=lambda: NOW).build(object())

    assert snapshot.governance.freshness is Freshness.MISSING
    assert snapshot.emergency.freshness is Freshness.MISSING
    assert snapshot.health.freshness is Freshness.MISSING
    assert snapshot.overallFreshness is not Freshness.FRESH
    assert "SECRET_VALUE_MUST_NOT_LEAK" not in snapshot.stable_json()


def test_pending_order_state_mapping_is_normalized_to_bounded_string():
    payloads = authority_payloads()
    payloads["bot"]["pendingOrderState"] = {
        "known": True, "pending": False, "safe": True,
        "reason": "STOPPED_PAPER_AUTHORITATIVE_SAFE",
        "source": "stopped_paper_authoritative",
    }
    snapshot = adapter_for(payloads).build(object())
    assert snapshot.execution.pendingOrderState == "NONE"

    payloads["bot"]["pendingOrderState"] = {"pending": True}
    assert adapter_for(payloads).build(object()).execution.pendingOrderState == "PENDING"

    payloads["bot"]["pendingOrderState"] = {"pending": None}
    assert adapter_for(payloads).build(object()).execution.pendingOrderState == "UNKNOWN"


def test_adapter_surface_contains_only_readers_and_never_invokes_commands():
    payloads = authority_payloads()
    command_calls = []

    def forbidden_command():
        command_calls.append("called")

    payloads["bot"]["command"] = forbidden_command
    payloads["moneyManagement"]["updateConfiguration"] = forbidden_command
    snapshot = adapter_for(payloads, command_calls=command_calls).build(object())

    assert snapshot.schemaVersion == 1
    assert command_calls == []
    assert set(RuntimeAuthorityReaders.__dataclass_fields__) == {
        "bot", "governance", "moneyManagement", "health",
    }


def test_adapter_projects_authoritative_risk_state_to_ruin_guard_status():
    payloads = authority_payloads()
    payloads["moneyManagement"]["riskState"] = "NORMAL"
    snapshot = adapter_for(payloads).build(object())
    assert snapshot.moneyManagement.ruinGuardStatus == "NORMAL"


def test_adapter_risk_state_is_allowlisted_and_non_risk_keys_still_excluded():
    payloads = authority_payloads()
    payloads["moneyManagement"]["riskState"] = "LOCKED"
    payloads["moneyManagement"]["recommendedAction"] = "SECRET_VALUE_MUST_NOT_LEAK"
    snapshot = adapter_for(payloads).build(object())
    serialized = snapshot.stable_json()
    assert snapshot.moneyManagement.ruinGuardStatus == "LOCKED"
    assert "SECRET_VALUE_MUST_NOT_LEAK" not in serialized
