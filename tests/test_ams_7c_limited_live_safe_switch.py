from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.auto_market_selection import (
    BotManagerSwitchRuntime, LimitedLiveSafeSwitchAdapter, LiveAutoActivationApproval,
    LiveAutoRuntimeObservation, LiveAutoSelectionRuntime,
    LiveSymbolSwitchPermission,
    MicroEdgeSuitabilityEvidence,
    evaluate_micro_edge_suitability,
)
from tests.test_ams_2b_safe_switch import NOW, Runtime, eligible_proposal

_MOCK_SUITABILITY_IDENTITY = "micro-edge-evid-test123456789abc"
_MOCK_SUITABILITY = evaluate_micro_edge_suitability(
    MicroEdgeSuitabilityEvidence(
        candidate_symbol="BTCUSDT",
        evaluated_at=NOW,
        calibration_ready=True,
        detector_snapshot={
            "absorption": {"conditionPassed": False},
            "stagnantHeavyFlow": {"conditionPassed": False},
            "fakePressure": {"conditionPassed": False},
        },
    ),
    candidate_symbol="BTCUSDT",
    now=NOW,
    max_age_seconds=300,
)


def permission(**changes):
    base = LiveSymbolSwitchPermission(
        enabled=True, configuration_version="ams-live-auto/v1",
        approval_identity="operator:test", approval_source="test",
        approved_at="2026-08-09T00:00:00Z",
        expected_active_symbol="ETHUSDT", expected_runtime_id="runtime-old",
        proposed_symbol="BTCUSDT", ranking_cycle_id="rank",
        observation_id="observation", validation_transaction_id="validation",
        issued_at=NOW - timedelta(seconds=1), expires_at=NOW + timedelta(seconds=30),
        micro_edge_suitability_identity=_MOCK_SUITABILITY.evidence_identity,
        micro_edge_suitability_status="SUITABLE",
        micro_edge_suitability_evaluated_at=_MOCK_SUITABILITY.evaluated_at,
    )
    return replace(base, **changes)


def final_state(**changes):
    state = {
        "activeSymbol": "ETHUSDT", "activeRuntimeId": "runtime-old",
        "rankingCycleId": "rank", "observationId": "observation",
        "configurationVersion": "ams-live-auto/v1", "candidateSymbol": "BTCUSDT",
        "marketDataFresh": True, "liveAccountFresh": True, "mmFresh": True,
        "positionState": "FLAT", "pendingOrderState": "NONE",
        "emergencySafe": True, "governanceAllow": True,
        "runtimeConsistent": True, "snapshotConsistent": True,
        "statusConsistent": True, "realOrderAllowed": False,
        "autoTradeEnabled": False, "executionRealOrderEnabled": False,
        "microEdgeSuitabilityIdentity": _MOCK_SUITABILITY.evidence_identity,
        "microEdgeSuitabilityStatus": "SUITABLE",
    }
    state.update(changes)
    return state


def adapter(runtime=None, state=None, proposal=None, now=NOW):
    runtime = runtime or Runtime()
    state = state or final_state()
    proposal = proposal or eligible_proposal()
    # The AMS-1C test fixture has a real ranking identity; permission must bind it.
    state["rankingCycleId"] = proposal.ranking_cycle_id
    return LimitedLiveSafeSwitchAdapter(
        runtime, selection_proposal_provider=lambda _: proposal,
        final_state_provider=lambda: state, clock=lambda: now,
    ), runtime, state, replace(permission(), ranking_cycle_id=proposal.ranking_cycle_id)


def test_permission_is_required_expiring_versioned_and_one_shot():
    subject, runtime, _, permit = adapter()
    assert subject.invoke(None).reason == "LIVE_SWITCH_PERMISSION_REQUIRED"
    expired = replace(permit, validation_transaction_id="expired",
                      expires_at=NOW - timedelta(seconds=1))
    assert subject.invoke(expired).reason == "LIVE_SWITCH_PERMISSION_EXPIRED"
    mismatch = replace(permit, validation_transaction_id="version",
                       configuration_version="ams-live-auto/v2")
    assert subject.invoke(mismatch).reason == "CONFIGURATION_VERSION_MISMATCH"
    first = subject.invoke(permit)
    assert first.committed and first.switch_result.success
    assert subject.invoke(permit).reason == "LIVE_SWITCH_PERMISSION_REUSED"
    assert runtime.events.count("commit") == 1


@pytest.mark.parametrize("change", [
    {"activeSymbol": "SOLUSDT"}, {"activeRuntimeId": "runtime-new"},
    {"observationId": "observation-new"},
    {"configurationVersion": "ams-live-auto/v2"},
    {"candidateSymbol": "SOLUSDT"},
    {"positionState": "OPEN"}, {"pendingOrderState": "EXISTS"},
    {"emergencySafe": False}, {"governanceAllow": False},
    {"mmFresh": False}, {"marketDataFresh": False},
    {"runtimeConsistent": False}, {"snapshotConsistent": False},
    {"statusConsistent": False}, {"realOrderAllowed": True},
    {"autoTradeEnabled": True}, {"executionRealOrderEnabled": True},
    {"microEdgeSuitabilityIdentity": "changed-evidence-identity"},
    {"microEdgeSuitabilityIdentity": None},
    {"microEdgeSuitabilityStatus": "STALE"},
])
def test_final_barrier_races_fail_before_commit(change):
    subject, runtime, state, permit = adapter(state=final_state(**change))
    result = subject.invoke(permit)
    assert not result.committed
    assert runtime.active == "ETHUSDT"
    assert "commit" not in runtime.events


@pytest.mark.parametrize("failure", ["subscribe", "invalid", "stale"])
def test_feed_and_snapshot_failures_keep_old_authority(failure):
    runtime = Runtime(); runtime.fail = failure
    subject, runtime, _, permit = adapter(runtime=runtime)
    result = subject.invoke(permit)
    assert not result.committed and runtime.active == "ETHUSDT"


@pytest.mark.parametrize("failure", ["sync", "cleanup", "resume"])
def test_post_commit_failure_never_rolls_back_and_requires_action(failure):
    runtime = Runtime(); runtime.fail = failure
    subject, runtime, _, permit = adapter(runtime=runtime)
    result = subject.invoke(permit)
    assert result.committed and result.action_required
    assert runtime.active == "BTCUSDT"
    assert result.switch_result.entry_paused


def test_live_runtime_success_updates_cooldown_resets_persistence_and_restart():
    runtime = Runtime()
    seconds = [NOW.timestamp()]
    approval = LiveAutoActivationApproval(
        True, "ams-live-auto/v1", "2026-08-09T00:00:00Z", "operator:test", "test"
    )
    service = LiveAutoSelectionRuntime(
        active_symbol_provider=lambda: runtime.active, approval=approval,
        clock=lambda: seconds[0],
    )
    seconds[0] += 60
    proposal = eligible_proposal()
    observation = LiveAutoRuntimeObservation(
        candidate_symbol="BTCUSDT", candidate_score=Decimal("0.92"),
        active_market_score=Decimal("0.50"), runtime_id="runtime-old",
        ranking_cycle_id=proposal.ranking_cycle_id, observation_id="observation",
        micro_edge_suitability=_MOCK_SUITABILITY,
    )
    for _ in range(5):
        service.observe(observation); seconds[0] += 10
    state = final_state(rankingCycleId=proposal.ranking_cycle_id)
    subject = LimitedLiveSafeSwitchAdapter(
        runtime, selection_proposal_provider=lambda _: proposal,
        final_state_provider=lambda: state,
        clock=lambda: datetime.fromtimestamp(seconds[0], tz=timezone.utc),
    )
    result = service.validate_activation(observation, subject)
    assert result["outcome"] == "SUCCESS" and result["switchCommitted"]
    status = service.get_status()
    assert status["cooldownRemaining"] == 120
    assert status["consecutiveWins"] == 0
    assert status["lastLiveSwitchResult"]["success"] is True
    assert status["actionRequired"] is False
    restarted = service.restart()
    assert restarted["liveAutoEnabled"] is False
    assert restarted["liveSwitchPermissionState"] == "NONE"
    assert restarted["consecutiveWins"] == 0


def test_bot_manager_live_commit_requires_typed_permission_and_trade_stays_off():
    class Manager:
        activeSymbol = "ETHUSDT"
        config = {"mode": "live", "dry_run": False, "realOrderAllowed": False,
                  "autoTradeEnabled": False, "executionRealOrderEnabled": False}
        def _commit_active_symbol_for_safe_switch(self, *args):
            self.args = args
            return True
    class Handle:
        feed = object(); runtime_id = "new-runtime"; exchange_symbol = "XBTUSDTM"
    manager = Manager()
    runtime = BotManagerSwitchRuntime(
        manager, position_provider=lambda: "FLAT", mm_provider=lambda: None,
        emergency_provider=lambda: True,
    )
    permit = permission(validation_transaction_id="tx")
    assert runtime.commit_active_symbol("ETHUSDT", "BTCUSDT", Handle(), "tx") is False
    assert runtime.commit_limited_live_active_symbol(
        "ETHUSDT", "BTCUSDT", Handle(), "tx", permit
    ) is True
    assert manager.config["realOrderAllowed"] is False
    assert manager.config["autoTradeEnabled"] is False
