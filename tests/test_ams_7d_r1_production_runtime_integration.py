from collections import UserDict

from backend.auto_market_selection import build_auto_market_selection_status
from backend.money_management.loss_application_settings import (
    resolve_loss_limit_application_configuration,
)


def test_production_mm_settings_accept_os_environ_mapping_shape(tmp_path):
    runtime = tmp_path / "logs" / "runtime"
    runtime.mkdir(parents=True)
    environ = UserDict({
        "MONEY_MANAGEMENT_ENABLED": "true",
        "MONEY_MANAGEMENT_PERSISTENCE_ENABLED": "true",
        "MONEY_MANAGEMENT_PERSISTENCE_PATH": str(runtime),
    })
    config = resolve_loss_limit_application_configuration(
        environ=environ, repository_root=tmp_path,
    )
    assert config.enabled is True
    assert config.persistence_enabled is True
    assert config.persistence_path == runtime


def test_live_production_projection_exposes_account_mm_scanner_and_ranking():
    status = build_auto_market_selection_status(
        active_symbol=None,
        requested_symbol="ETHUSDT",
        live_observation={
            "mode": "LIVE_READ_ONLY",
            "timestamp": "2026-08-09T10:00:00Z",
            "universeCount": 3,
            "evaluatedCount": 3,
            "eligibleCount": 2,
            "rejectedCount": 1,
            "scannerCycleId": "scanner-1",
            "rankingCycleId": "ranking-1",
            "observationId": "ams-observation-production-1",
            "rankingEvaluatedAt": "2026-08-09T10:00:00Z",
            "rankedCandidates": [{"symbol": "BTCUSDT", "rank": 1}],
            "topCandidate": "BTCUSDT",
            "topScore": "0.91",
            "universeEvaluatedAt": "2026-08-09T10:00:00Z",
        },
        live_account_authority={
            "sourceAuthority": "REAL_LIVE_ACCOUNT",
            "pendingOrderState": "NONE",
            "accountEvaluatedAt": "2026-08-09T09:59:59Z",
            "positionEvaluatedAt": "2026-08-09T09:59:59.2Z",
            "pendingOrdersEvaluatedAt": "2026-08-09T09:59:59.4Z",
            "snapshotConsistent": True,
            "authorityFresh": True,
        },
        capital_eligibility={
            "capitalAuthority": "MONEY_MANAGEMENT",
            "capitalSource": "REAL_LIVE_ACCOUNT",
            "inputAuthority": "REAL_LIVE_ACCOUNT",
            "availableCapital": "7.9",
            "riskBudget": "0.0395",
            "remainingExposure": "1.58",
            "remainingPositionCapacity": 1,
            "mmRegime": "CAPITAL_PROTECTION_STANDARD",
            "evaluatedAt": "2026-08-09T10:00:00Z",
            "authorityFresh": True,
            "executionEntryAllowed": True,
        },
        production_integration={"status": "READY", "readOnly": True},
        lifecycle={"amsRuntimeState": "STOPPED", "lifecycleRevision": 10},
        live_auto_runtime={
            "configurationVersion": "ams-live-auto/v1",
            "runtimeCycleId": "2:798",
            "lifecycleRevision": 10,
        },
    )

    assert status["activeSymbol"] is None
    assert status["requestedSymbol"] == "ETHUSDT"
    assert status["scanner"] == {
        "status": "COMPLETED", "universeCount": 3, "evaluatedCount": 3,
        "eligibleCount": 2, "rejectedCount": 1,
        "evaluatedAt": "2026-08-09T10:00:00Z",
    }
    assert status["ranking"]["status"] == "COMPLETED"
    assert status["ranking"]["rankedCount"] == 1
    assert status["topCandidate"]["symbol"] == "BTCUSDT"
    assert status["capitalEligibility"]["capitalSource"] == "REAL_LIVE_ACCOUNT"
    assert status["capitalEligibility"]["remainingPositionCapacity"] == 1
    assert status["liveAccountAuthority"]["pendingOrderState"] == "NONE"
    assert status["liveAccountAuthority"]["snapshotConsistent"] is True
    assert status["productionIntegration"]["readOnly"] is True
    assert status["liveReadOnly"]["observationId"] == (
        "ams-observation-production-1"
    )
    assert status["liveAuto"]["observationId"] == "ams-observation-production-1"
    assert status["liveAuto"]["configurationVersion"] == "ams-live-auto/v1"
    assert status["liveAuto"]["runtimeCycleId"] == "2:798"
    assert status["liveAuto"]["lifecycleRevision"] == 10


def test_missing_authorities_remain_unavailable_and_requested_is_not_active():
    status = build_auto_market_selection_status(
        active_symbol=None, requested_symbol="BTCUSDT",
        production_integration={
            "status": "BLOCKED", "reasonCodes": ["LIVE_MM_CONFIG_UNAVAILABLE"],
            "readOnly": True,
        },
    )
    assert status["activeSymbol"] is None
    assert status["requestedSymbol"] == "BTCUSDT"
    assert status["scanner"]["status"] == "UNAVAILABLE"
    assert status["ranking"]["status"] == "UNAVAILABLE"
    assert status["capitalEligibility"]["status"] == "UNAVAILABLE"
