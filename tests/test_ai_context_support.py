"""Shared, non-production fixtures for the canonical context tests.

This module contains helpers only; it defines no test cases.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from backend.supervisor.snapshot_builder import build_supervisor_snapshot
from backend.supervisor.snapshot_sources import SnapshotFreshnessPolicy

FIXED_NOW = datetime(2026, 10, 25, 0, 0, 0, tzinfo=timezone.utc)

FRESHNESS_POLICY = SnapshotFreshnessPolicy(
    maximumAgeBySource=tuple(
        (source, timedelta(seconds=30))
        for source in ("bot", "governance", "moneyManagement", "health")
    ),
    futureTolerance=timedelta(seconds=1),
)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def bot_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourceEvaluatedAt": _stamp(FIXED_NOW),
        "botState": "RUNNING",
        "status": "RUNNING",
        "loopEnabled": True,
        "loopState": "RUNNING",
        "selectedMode": "MANUAL",
        "dryRun": False,
        "autoTradeEnabled": False,
        "realOrderAllowed": False,
        "activeSymbol": "BTCUSDT",
        "marketReady": True,
        "marketStale": False,
        "last_update": _stamp(FIXED_NOW),
        "selectionMode": "AUTO",
        "autoMarketSelection": {
            "selectionSource": "AMS",
            "amsRuntimeState": "READY",
            "selectionCycleId": "cycle-1",
            "safeSwitchState": "SAFE",
            "suitabilityEvidenceState": "PRESENT",
        },
        "tradingDecision": {
            "status": "HOLD",
            "state": "IDLE",
            "evaluatedAt": _stamp(FIXED_NOW),
        },
        "emergency": {"locked": False, "state": "ARMED"},
        "governance_state": {"mode": "MANUAL", "executionEnabled": True},
    }
    payload.update(overrides)
    return payload


def governance_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourceEvaluatedAt": _stamp(FIXED_NOW),
        "mode": "MANUAL",
        "executionEnabled": True,
        "riskProfile": "NORMAL",
        "locked": False,
        "state": "ARMED",
    }
    payload.update(overrides)
    return payload


def money_management_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourceEvaluatedAt": _stamp(FIXED_NOW),
        "capitalEligibility": {
            "capitalAuthority": "LIVE_ACCOUNT",
            "capitalSource": "LIVE",
            "equity": "1000",
            "availableCapital": "1000",
            "mmMode": "NORMAL",
            "mmRegime": "NORMAL",
            "riskBudget": "10",
            "remainingExposure": "0",
            "remainingPositionCapacity": "1",
            "ruinGuardStatus": "NORMAL",
            "compoundingEnabled": False,
            "executionEntryAllowed": True,
            "policyVersion": "mm-v1",
            "authorityFresh": True,
        },
        "metrics": {
            "equity": "1000",
            "availableCapital": "1000",
            "drawdown": "0",
            "currentExposure": "0",
            "openPositionState": "FLAT",
            "metricsGeneratedAt": _stamp(FIXED_NOW),
        },
    }
    payload.update(overrides)
    return payload


def health_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourceEvaluatedAt": _stamp(FIXED_NOW),
        "status": "ok",
        "backendStatus": "ok",
        "runtimeHealthy": True,
    }
    payload.update(overrides)
    return payload


def make_supervisor_snapshot(
    *,
    bot: Mapping[str, object] | None = ...,
    governance: Mapping[str, object] | None = ...,
    money_management: Mapping[str, object] | None = ...,
    health: Mapping[str, object] | None = ...,
    captured_at: datetime = FIXED_NOW,
):
    return build_supervisor_snapshot(
        bot_status=bot_payload() if bot is ... else bot,
        governance_status=governance_payload() if governance is ... else governance,
        money_management_status=(
            money_management_payload() if money_management is ... else money_management
        ),
        health_payload=health_payload() if health is ... else health,
        captured_at=captured_at,
        freshness_policy=FRESHNESS_POLICY,
    )
