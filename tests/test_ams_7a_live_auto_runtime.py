from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.auto_market_selection import (
    LiveAutoActivationApproval,
    LiveAutoRuntimeObservation,
    LiveAutoSelectionRuntime,
    MicroEdgeSuitabilityEvidence,
    evaluate_micro_edge_suitability,
)


_SUITABLE = evaluate_micro_edge_suitability(
    MicroEdgeSuitabilityEvidence(
        candidate_symbol="ETHUSDT",
        evaluated_at=datetime.fromtimestamp(60, tz=timezone.utc),
        calibration_ready=True,
        detector_snapshot={
            "absorption": {"conditionPassed": False},
            "stagnantHeavyFlow": {"conditionPassed": False},
            "fakePressure": {"conditionPassed": False},
        },
    ),
    candidate_symbol="ETHUSDT",
    now=datetime.fromtimestamp(100, tz=timezone.utc),
    max_age_seconds=300,
)


class Clock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class Authority:
    def __init__(self):
        self.activeSymbol = "BTCUSDT"
        self.safe_switch_calls = 0
        self.realOrderAllowed = False
        self.dryRun = False


def approved():
    return LiveAutoActivationApproval(
        live_auto_enabled=True,
        configuration_version="ams-live-auto/v1",
        approved_at="2026-08-09T00:00:00Z",
        approval_identity="operator:test",
        approval_source="explicit-test-contract",
    )


def observation(**changes):
    value = LiveAutoRuntimeObservation(
        candidate_symbol="ETHUSDT",
        candidate_score=Decimal("0.92"),
        active_market_score=Decimal("0.50"),
        micro_edge_suitability=_SUITABLE,
    )
    return replace(value, **changes)


def runtime(*, enabled=True):
    authority = Authority()
    clock = Clock()
    service = LiveAutoSelectionRuntime(
        active_symbol_provider=lambda: authority.activeSymbol,
        approval=approved() if enabled else None,
        clock=clock,
    )
    return service, authority, clock


def observe_wins(service, clock, value=None, count=5, start=60):
    clock.value = start
    result = None
    for _ in range(count):
        result = service.observe(value or observation())
        clock.advance(10)
    return result


def test_default_and_restart_are_disabled_and_clear_transient_state():
    service, authority, clock = runtime(enabled=False)
    initial = service.get_status()
    assert initial["liveAutoEnabled"] is False
    assert initial["runtimeState"] == "STOPPED"
    assert initial["configurationVersion"] == "ams-live-auto/v1"
    assert observe_wins(service, clock)["consecutiveWins"] == 0

    enabled, _, enabled_clock = runtime()
    assert observe_wins(enabled, enabled_clock, count=4)["consecutiveWins"] == 4
    restarted = enabled.restart()
    assert restarted["liveAutoEnabled"] is False
    assert restarted["consecutiveWins"] == 0
    assert authority.activeSymbol == "BTCUSDT"


def test_explicit_approval_metadata_and_version_are_validated():
    authority = Authority()
    for approval, reason in (
        (replace(approved(), approved_at="not-a-time"),
         "EXPLICIT_OPERATOR_APPROVAL_REQUIRED"),
        (replace(approved(), approval_identity=" "),
         "EXPLICIT_OPERATOR_APPROVAL_REQUIRED"),
        (replace(approved(), configuration_version="ams-live-auto/v0"),
         "CONFIGURATION_VERSION_MISMATCH"),
    ):
        service = LiveAutoSelectionRuntime(
            active_symbol_provider=lambda: authority.activeSymbol,
            approval=approval,
            clock=lambda: 60,
        )
        assert reason in service.observe(observation())["blockReasons"]


@pytest.mark.parametrize("changes,reason", [
    ({"selected_mode": "PAPER"}, "SELECTED_MODE_NOT_LIVE"),
    ({"dry_run": True}, "DRY_RUN_ACTIVE"),
    ({"market_data_fresh": False}, "MARKET_DATA_STALE"),
    ({"live_status_consistent": False}, "LIVE_STATUS_CONSISTENCY_REQUIRED"),
    ({"live_account_fresh": False}, "LIVE_ACCOUNT_STALE"),
    ({"mm_fresh": False}, "MM_STALE"),
    ({"position_state": "OPEN"}, "POSITION_NOT_FLAT"),
    ({"position_state": "UNKNOWN"}, "POSITION_NOT_FLAT"),
    ({"pending_order_state": "EXISTS"}, "PENDING_ORDERS_NOT_NONE"),
    ({"pending_order_state": "UNKNOWN"}, "PENDING_ORDERS_NOT_NONE"),
    ({"emergency_safe": False}, "EMERGENCY_UNSAFE"),
    ({"governance_allow": False}, "GOVERNANCE_BLOCK"),
])
def test_activation_and_authority_gates_fail_closed(changes, reason):
    service, _, clock = runtime()
    result = observe_wins(service, clock, observation(**changes))
    assert result["switchEligible"] is False
    assert reason in result["blockReasons"]


@pytest.mark.parametrize("advantage,passes", [
    ("0.4199", False),
    ("0.42", True),
    ("0.4201", True),
])
def test_decimal_score_boundary(advantage, passes):
    service, _, clock = runtime()
    value = observation(candidate_score=Decimal("0.50") + Decimal(advantage))
    result = observe_wins(service, clock, value)
    assert result["switchEligible"] is passes


def test_persistence_candidate_change_and_stale_reset():
    service, _, clock = runtime()
    assert observe_wins(service, clock, count=4)["consecutiveWins"] == 4
    changed = observation(candidate_symbol="SOLUSDT", candidate_score=Decimal("0.93"))
    assert service.observe(changed)["consecutiveWins"] == 1
    clock.advance(1)
    stale = service.observe(replace(changed, observation_fresh=False))
    assert stale["consecutiveWins"] == 0
    assert "OBSERVATION_STALE" in stale["blockReasons"]


def test_active_duration_and_observation_cadence_boundaries():
    service, _, clock = runtime()
    clock.value = 59
    first = service.observe(observation())
    assert "MINIMUM_ACTIVE_DURATION" in first["blockReasons"]
    clock.value = 60
    cadence = service.observe(observation())
    assert cadence["blockReasons"] == ["OBSERVATION_INTERVAL_PENDING"]
    clock.value = 69
    second = service.observe(observation())
    assert second["consecutiveWins"] == 2


def test_five_wins_only_exposes_contract_and_pre_switch_revalidation():
    service, authority, clock = runtime()
    before = observe_wins(service, clock, count=4)
    assert before["switchEligible"] is False
    final = service.observe(observation())
    assert final["switchEligible"] is True
    assert final["runtimeState"] == "SWITCH_ELIGIBLE"
    revalidated = service.pre_switch_revalidate(observation())
    assert revalidated == {
        "switchEligible": True,
        "action": "ELIGIBLE_CONTRACT_ONLY",
        "blockReasons": [],
        "safeSwitchInvoked": False,
    }
    aborted = service.pre_switch_revalidate(observation(position_state="OPEN"))
    assert aborted["action"] == "ABORT"
    assert authority.safe_switch_calls == 0
    assert authority.activeSymbol == "BTCUSDT"


def test_cooldown_contract_uses_injected_clock():
    service, authority, clock = runtime()
    clock.value = 100
    service.record_successful_switch(authority.activeSymbol)
    clock.value = 219
    service._last_observation_at = None
    result = service.observe(observation())
    assert "SWITCH_COOLDOWN" in result["blockReasons"]
    clock.value = 220
    service._last_observation_at = None
    result = service.observe(observation())
    assert "SWITCH_COOLDOWN" not in result["blockReasons"]


def test_disabled_runtime_has_no_side_effects_or_execution_authority_change():
    service, authority, clock = runtime(enabled=False)
    before = (authority.activeSymbol, authority.realOrderAllowed, authority.dryRun)
    for _ in range(10):
        service.observe(observation())
        clock.advance(10)
    status = service.get_status()
    assert (authority.activeSymbol, authority.realOrderAllowed, authority.dryRun) == before
    assert authority.safe_switch_calls == 0
    assert status["safeSwitchInvoked"] is False
    assert status["switchCommitted"] is False
    assert status["realOrderCreated"] is False
    assert status["automaticSafetyRecoverySwitchEnabled"] is False


def test_read_model_is_deterministic_and_separates_symbols():
    service, _, clock = runtime()
    observe_wins(service, clock, count=1)
    first = service.get_status()
    second = service.get_status()
    assert first == second
    assert first["activeSymbol"] == "BTCUSDT"
    assert first["topCandidate"] == "ETHUSDT"
    assert first["liveAccountState"] == "FRESH"
    assert first["mmState"] == "FRESH"
