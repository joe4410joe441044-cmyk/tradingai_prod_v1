from dataclasses import replace
from decimal import Decimal

import pytest

from backend.auto_market_selection import (
    LiveAutoActivationApproval, LiveAutoSelectionCalibration,
    LiveSwitchEligibilityTracker, LiveSwitchObservation,
)


def observation(**changes):
    value = LiveSwitchObservation(
        "ETHUSDT", Decimal("0.92"), "BTCUSDT", Decimal("0.50"),
        60, 120,
    )
    return replace(value, **changes)


def win(tracker, value=None, count=5):
    result = None
    for _ in range(count):
        result = tracker.evaluate(value or observation())
    return result


def test_v1_values_and_deterministic_decimal_serialization():
    value = LiveAutoSelectionCalibration()
    assert value.to_dict() == value.to_dict()
    assert value.to_dict()["minimumScoreAdvantage"] == "0.42"
    assert (value.selection_observation_interval_seconds,
            value.required_consecutive_wins,
            value.minimum_active_duration_seconds,
            value.switch_cooldown_seconds) == (10, 5, 60, 120)
    assert value.automatic_safety_recovery_switch_enabled is False


def test_all_four_boundaries_are_inclusive_and_independent():
    exact = observation(candidate_score=Decimal("0.92"), active_market_score=Decimal("0.50"))
    tracker = LiveSwitchEligibilityTracker()
    assert not win(tracker, exact, 4).eligible
    assert tracker.evaluate(exact).eligible
    assert "MINIMUM_ACTIVE_DURATION" in win(
        LiveSwitchEligibilityTracker(), replace(exact, active_duration_seconds=59)
    ).reason_codes
    assert "SWITCH_COOLDOWN" in win(
        LiveSwitchEligibilityTracker(), replace(exact, seconds_since_successful_switch=119)
    ).reason_codes
    assert "SCORE_ADVANTAGE_INSUFFICIENT" in win(
        LiveSwitchEligibilityTracker(), replace(exact, candidate_score=Decimal("0.9199"))
    ).reason_codes


def test_stale_or_different_candidate_resets_persistence():
    tracker = LiveSwitchEligibilityTracker()
    win(tracker, count=4)
    assert tracker.evaluate(observation(observation_fresh=False)).consecutive_wins == 0
    win(tracker, count=4)
    changed = observation(candidate_symbol="SOLUSDT", candidate_score=Decimal("0.93"))
    assert tracker.evaluate(changed).consecutive_wins == 1


@pytest.mark.parametrize("changes,reason", [
    ({"live_account_fresh": False}, "LIVE_ACCOUNT_STALE"),
    ({"mm_fresh": False}, "MM_STALE"),
    ({"position_state": "OPEN"}, "POSITION_NOT_FLAT"),
    ({"position_state": "UNKNOWN"}, "POSITION_NOT_FLAT"),
    ({"pending_order_state": "EXISTS"}, "PENDING_ORDERS_NOT_NONE"),
    ({"pending_order_state": "UNKNOWN"}, "PENDING_ORDERS_NOT_NONE"),
    ({"emergency_safe": False}, "EMERGENCY_UNSAFE"),
    ({"governance_allow": False}, "GOVERNANCE_BLOCK"),
    ({"live_status_consistent": False}, "LIVE_STATUS_CONSISTENCY_REQUIRED"),
    ({"snapshot_consistent": False}, "SNAPSHOT_MISMATCH"),
    ({"runtime_authority_consistent": False}, "RUNTIME_AUTHORITY_INCONSISTENT"),
])
def test_unknown_stale_and_inconsistent_authorities_block(changes, reason):
    result = win(LiveSwitchEligibilityTracker(), observation(**changes))
    assert not result.eligible
    assert reason in result.reason_codes


def test_current_active_market_must_be_comparable_in_same_observation():
    result = win(
        LiveSwitchEligibilityTracker(), observation(active_market_score=None)
    )
    assert not result.eligible
    assert result.score_advantage is None
    assert "ACTIVE_MARKET_COMPARISON_UNAVAILABLE" in result.reason_codes


def test_restart_is_off_and_does_not_grant_execution_permission():
    state = LiveAutoActivationApproval.restart_default()
    assert state.live_auto_enabled is False
    assert not hasattr(state, "real_order_allowed")
    serialized = win(LiveSwitchEligibilityTracker()).to_dict()
    assert serialized["switchCommitted"] is False
    assert serialized["realOrderCreated"] is False
