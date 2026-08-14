from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.auto_market_selection import (
    LiveActivationBoundaryResult,
    LiveAutoActivationApproval,
    LiveAutoRuntimeObservation,
    LiveAutoSelectionRuntime,
    MicroEdgeSuitabilityEvidence,
    ValidationOnlySafeSwitchAdapter,
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
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value


class Authority:
    def __init__(self):
        self.active_symbol = "BTCUSDT"
        self.realOrderAllowed = False
        self.dryRun = False
        self.autoTrade = False
        self.mutations = 0
        self.orders = 0


class RecordingAdapter:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result or LiveActivationBoundaryResult(
            "FAILURE_PRE_COMMIT", True, reason="LIVE_COMMIT_DISABLED"
        )

    def invoke(self, proposal):
        self.calls += 1
        self.proposal = proposal
        return self.result


def approval():
    return LiveAutoActivationApproval(
        True, "ams-live-auto/v1", "2026-08-09T00:00:00Z",
        "operator:test", "synthetic-validation",
    )


def observation(**changes):
    base = LiveAutoRuntimeObservation(
        candidate_symbol="ETHUSDT", candidate_score=Decimal("0.92"),
        active_market_score=Decimal("0.50"), runtime_id="runtime-1",
        ranking_cycle_id="rank-1", observation_id="observation-1",
        micro_edge_suitability=_SUITABLE,
    )
    return replace(base, **changes)


def eligible_runtime(enabled=True):
    authority, clock = Authority(), Clock()
    service = LiveAutoSelectionRuntime(
        active_symbol_provider=lambda: authority.active_symbol,
        approval=approval() if enabled else None, clock=clock,
    )
    clock.value = 60
    for _ in range(5):
        service.observe(observation())
        clock.value += 10
    return service, authority, clock


def test_disabled_never_reaches_boundary():
    service, authority, _ = eligible_runtime(False)
    adapter = RecordingAdapter()
    result = service.validate_activation(observation(), adapter)
    assert result["safeSwitchBoundaryReached"] is False
    assert adapter.calls == authority.mutations == authority.orders == 0


def test_phase_one_identity_and_validation_only_boundary_are_exposed():
    service, authority, _ = eligible_runtime()
    before = (authority.active_symbol, authority.realOrderAllowed,
              authority.dryRun, authority.autoTrade)
    status = service.get_status()
    assert status["preflightPassed"] is True
    assert status["expectedActiveSymbol"] == "BTCUSDT"
    assert status["expectedRuntimeId"] == "runtime-1"
    assert status["expectedCandidate"] == "ETHUSDT"
    assert status["expectedRankingCycleId"] == "rank-1"
    assert status["expectedObservationId"] == "observation-1"
    assert status["validationTransactionId"].startswith("ams-7b-")

    adapter = ValidationOnlySafeSwitchAdapter()
    result = service.validate_activation(observation(), adapter)
    assert result["revalidationPassed"] is True
    assert result["safeSwitchBoundaryReached"] is True
    assert result["activationBlockReasons"] == ["LIVE_COMMIT_DISABLED"]
    assert result["switchCommitted"] is False
    assert (authority.active_symbol, authority.realOrderAllowed,
            authority.dryRun, authority.autoTrade) == before
    assert authority.mutations == authority.orders == 0
    assert service.get_status()["liveAutoEnabled"] is False


@pytest.mark.parametrize("changes,reason", [
    ({"position_state": "OPEN"}, "POSITION_NOT_FLAT"),
    ({"pending_order_state": "EXISTS"}, "PENDING_ORDERS_NOT_NONE"),
    ({"live_account_fresh": False}, "LIVE_ACCOUNT_STALE"),
    ({"mm_fresh": False}, "MM_STALE"),
    ({"emergency_safe": False}, "EMERGENCY_UNSAFE"),
    ({"governance_allow": False}, "GOVERNANCE_BLOCK"),
    ({"candidate_symbol": "SOLUSDT"}, "CANDIDATE_CHANGED"),
    ({"candidate_score": Decimal("0.9199")}, "SCORE_ADVANTAGE_INSUFFICIENT"),
    ({"runtime_id": "runtime-2"}, "ACTIVATION_CONTEXT_CHANGED"),
    ({"ranking_cycle_id": "rank-2"}, "ACTIVATION_CONTEXT_CHANGED"),
    ({"observation_id": "observation-2"}, "ACTIVATION_CONTEXT_CHANGED"),
    ({"configuration_version": "ams-live-auto/v2"}, "ACTIVATION_CONTEXT_CHANGED"),
    ({"live_status_consistent": False}, "LIVE_STATUS_CONSISTENCY_REQUIRED"),
])
def test_phase_two_authority_races_abort_before_boundary(changes, reason):
    service, authority, _ = eligible_runtime()
    adapter = RecordingAdapter()
    result = service.validate_activation(observation(**changes), adapter)
    assert result["outcome"] == "ABORT"
    assert reason in result["activationBlockReasons"]
    assert adapter.calls == authority.mutations == authority.orders == 0


def test_production_shaped_chain_binds_suitability_identity_to_permission():
    service, authority, _ = eligible_runtime()
    adapter = RecordingAdapter()

    result = service.validate_activation(observation(), adapter)

    assert result["revalidationPassed"] is True
    assert adapter.calls == 1
    assert adapter.proposal.micro_edge_suitability_identity == _SUITABLE.evidence_identity
    assert adapter.proposal.micro_edge_suitability_status == "SUITABLE"
    assert adapter.proposal.micro_edge_suitability_evaluated_at == _SUITABLE.evaluated_at
    assert authority.mutations == authority.orders == 0


def test_active_symbol_cas_and_timing_reset_abort():
    service, authority, _ = eligible_runtime()
    adapter = RecordingAdapter()
    authority.active_symbol = "SOLUSDT"
    result = service.validate_activation(observation(), adapter)
    assert "ACTIVATION_CONTEXT_CHANGED" in result["activationBlockReasons"]
    assert adapter.calls == 0


def test_missing_observation_identity_never_issues_permission_or_reaches_boundary():
    authority, clock = Authority(), Clock()
    runtime = LiveAutoSelectionRuntime(
        active_symbol_provider=lambda: authority.active_symbol,
        approval=approval(), clock=clock,
    )
    missing = observation(observation_id=None)
    clock.value = 60
    for _ in range(5):
        runtime.observe(missing)
        clock.value += 10
    adapter = RecordingAdapter()

    result = runtime.validate_activation(missing, adapter)

    assert "ACTIVATION_CONTEXT_INCOMPLETE" in result["activationBlockReasons"]
    assert adapter.calls == authority.mutations == authority.orders == 0
    assert runtime.get_status()["liveSwitchPermissionState"] == "NONE"

    service, authority, _ = eligible_runtime()
    service._active_since += 1
    result = service.validate_activation(observation(), adapter)
    assert "ACTIVATION_TIMING_CONTEXT_CHANGED" in result["activationBlockReasons"]
    assert adapter.calls == 0


def test_candidate_persistence_is_not_transferred():
    service, _, clock = eligible_runtime()
    changed = observation(candidate_symbol="SOLUSDT", candidate_score=Decimal("0.93"))
    clock.value += 10
    status = service.observe(changed)
    assert status["consecutiveWins"] == 1
    assert status["preflightPassed"] is True  # previous proposal remains immutable
    adapter = RecordingAdapter()
    result = service.validate_activation(changed, adapter)
    assert "PERSISTENCE_REVALIDATION_REQUIRED" in result["activationBlockReasons"]
    assert adapter.calls == 0


def test_pre_and_mock_post_commit_results_are_deterministic_without_mutation():
    for boundary_result in (
        LiveActivationBoundaryResult("FAILURE_PRE_COMMIT", True,
                                     reason="PREFLIGHT_FAILED"),
        LiveActivationBoundaryResult("FAILURE_POST_COMMIT", True, committed=True,
                                     action_required=True, reason="SYNC_FAILED"),
    ):
        service, authority, _ = eligible_runtime()
        result = service.validate_activation(observation(), RecordingAdapter(boundary_result))
        assert result["switchCommitted"] is False
        assert authority.active_symbol == "BTCUSDT"
        assert authority.mutations == authority.orders == 0
        if boundary_result.committed:
            assert result["activationValidationState"] == "FAILED"
            assert result["actionRequired"] is True
