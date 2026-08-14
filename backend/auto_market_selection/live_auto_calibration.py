"""AMS-6C runtime-neutral Live AUTO v1 specification contracts.

This module evaluates eligibility only.  It owns no switch or execution API.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class LiveAutoSelectionCalibration:
    version: str = "ams-live-auto/v1"
    selection_observation_interval_seconds: int = 10
    minimum_score_advantage: Decimal = Decimal("0.42")
    required_consecutive_wins: int = 5
    minimum_active_duration_seconds: int = 60
    switch_cooldown_seconds: int = 120
    automatic_safety_recovery_switch_enabled: bool = False
    max_executable_positions: int = 1
    require_fresh_live_account_authority: bool = True
    require_fresh_mm: bool = True
    require_flat_position: bool = True
    require_no_pending_orders: bool = True
    require_emergency_safe: bool = True
    require_governance_allow: bool = True
    require_live_status_consistency: bool = True

    def __post_init__(self):
        if self.version != "ams-live-auto/v1":
            raise ValueError("unsupported Live AUTO calibration version")
        if self.selection_observation_interval_seconds <= 0:
            raise ValueError("observation interval must be positive")
        if self.minimum_score_advantage < 0:
            raise ValueError("minimum score advantage must be nonnegative")
        if self.required_consecutive_wins <= 0:
            raise ValueError("required consecutive wins must be positive")
        if self.minimum_active_duration_seconds < 0 or self.switch_cooldown_seconds < 0:
            raise ValueError("duration gates must be nonnegative")
        if self.max_executable_positions != 1:
            raise ValueError("Live AUTO v1 max executable positions must be 1")
        required = (
            self.require_fresh_live_account_authority,
            self.require_fresh_mm,
            self.require_flat_position,
            self.require_no_pending_orders,
            self.require_emergency_safe,
            self.require_governance_allow,
            self.require_live_status_consistency,
        )
        if self.automatic_safety_recovery_switch_enabled or not all(required):
            raise ValueError("Live AUTO v1 safety requirements cannot be relaxed")

    def to_dict(self):
        return {
            "version": self.version,
            "selectionObservationIntervalSeconds": self.selection_observation_interval_seconds,
            "minimumScoreAdvantage": format(self.minimum_score_advantage, "f"),
            "requiredConsecutiveWins": self.required_consecutive_wins,
            "minimumActiveDurationSeconds": self.minimum_active_duration_seconds,
            "switchCooldownSeconds": self.switch_cooldown_seconds,
            "automaticSafetyRecoverySwitchEnabled": self.automatic_safety_recovery_switch_enabled,
            "maxExecutablePositions": self.max_executable_positions,
            "requireFreshLiveAccountAuthority": self.require_fresh_live_account_authority,
            "requireFreshMM": self.require_fresh_mm,
            "requireFlatPosition": self.require_flat_position,
            "requireNoPendingOrders": self.require_no_pending_orders,
            "requireEmergencySafe": self.require_emergency_safe,
            "requireGovernanceAllow": self.require_governance_allow,
            "requireLiveStatusConsistency": self.require_live_status_consistency,
        }


@dataclass(frozen=True)
class LiveSwitchObservation:
    candidate_symbol: Optional[str]
    candidate_score: Optional[Decimal]
    active_symbol: Optional[str]
    active_market_score: Optional[Decimal]
    active_duration_seconds: int
    seconds_since_successful_switch: Optional[int]
    observation_fresh: bool = True
    ranking_valid: bool = True
    snapshot_consistent: bool = True
    runtime_authority_consistent: bool = True
    live_account_fresh: bool = True
    mm_fresh: bool = True
    position_state: str = "FLAT"
    pending_order_state: str = "NONE"
    emergency_safe: bool = True
    governance_allow: bool = True
    live_status_consistent: bool = True


@dataclass(frozen=True)
class LiveSwitchEligibility:
    eligible: bool
    consecutive_wins: int
    score_advantage: Optional[Decimal]
    reason_codes: tuple

    def to_dict(self):
        return {
            "eligible": self.eligible,
            "consecutiveWins": self.consecutive_wins,
            "scoreAdvantage": (
                format(self.score_advantage, "f")
                if self.score_advantage is not None else None
            ),
            "reasonCodes": list(self.reason_codes),
            "switchCommitted": False,
            "realOrderCreated": False,
        }


class LiveSwitchEligibilityTracker:
    """Counts only consecutive authoritative wins; never performs a switch."""

    def __init__(self, calibration=None):
        self.calibration = calibration or LiveAutoSelectionCalibration()
        self._candidate = None
        self._wins = 0

    def evaluate(self, observation):
        if not isinstance(observation, LiveSwitchObservation):
            raise TypeError("LiveSwitchObservation required")
        invalid = not all((
            observation.observation_fresh,
            observation.ranking_valid,
            observation.snapshot_consistent,
            observation.runtime_authority_consistent,
            observation.live_account_fresh,
            observation.mm_fresh,
            observation.position_state == "FLAT",
            observation.pending_order_state == "NONE",
            observation.emergency_safe,
            observation.governance_allow,
            observation.live_status_consistent,
        ))
        comparable = bool(
            observation.candidate_symbol
            and observation.active_symbol
            and observation.candidate_score is not None
            and observation.active_market_score is not None
        )
        advantage = (
            observation.candidate_score - observation.active_market_score
            if comparable else None
        )
        score_passes = bool(
            advantage is not None
            and advantage >= self.calibration.minimum_score_advantage
            and observation.candidate_symbol != observation.active_symbol
        )
        if invalid or not comparable or not score_passes:
            self._candidate, self._wins = None, 0
        elif observation.candidate_symbol == self._candidate:
            self._wins += 1
        else:
            self._candidate, self._wins = observation.candidate_symbol, 1

        reasons = []
        checks = (
            (observation.observation_fresh, "OBSERVATION_STALE"),
            (observation.ranking_valid, "RANKING_INVALID"),
            (observation.snapshot_consistent, "SNAPSHOT_MISMATCH"),
            (observation.runtime_authority_consistent, "RUNTIME_AUTHORITY_INCONSISTENT"),
            (comparable, "ACTIVE_MARKET_COMPARISON_UNAVAILABLE"),
            (score_passes, "SCORE_ADVANTAGE_INSUFFICIENT"),
            (self._wins >= self.calibration.required_consecutive_wins, "PERSISTENCE_INSUFFICIENT"),
            (observation.active_duration_seconds >= self.calibration.minimum_active_duration_seconds, "MINIMUM_ACTIVE_DURATION"),
            (observation.seconds_since_successful_switch is None or observation.seconds_since_successful_switch >= self.calibration.switch_cooldown_seconds, "SWITCH_COOLDOWN"),
            (observation.live_account_fresh, "LIVE_ACCOUNT_STALE"),
            (observation.mm_fresh, "MM_STALE"),
            (observation.position_state == "FLAT", "POSITION_NOT_FLAT"),
            (observation.pending_order_state == "NONE", "PENDING_ORDERS_NOT_NONE"),
            (observation.emergency_safe, "EMERGENCY_UNSAFE"),
            (observation.governance_allow, "GOVERNANCE_BLOCK"),
            (observation.live_status_consistent, "LIVE_STATUS_CONSISTENCY_REQUIRED"),
        )
        reasons.extend(reason for passed, reason in checks if not passed)
        return LiveSwitchEligibility(not reasons, self._wins, advantage, tuple(reasons))


@dataclass(frozen=True)
class LiveAutoActivationApproval:
    live_auto_enabled: bool = False
    configuration_version: Optional[str] = None
    approved_at: Optional[str] = None
    approval_identity: Optional[str] = None
    approval_source: Optional[str] = None
    expires_at: Optional[str] = None

    @classmethod
    def restart_default(cls):
        return cls()
