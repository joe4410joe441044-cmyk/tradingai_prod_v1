"""Disabled-by-default Live AUTO orchestration and read model.

This boundary evaluates whether a future SafeSwitch transaction would be
eligible.  It deliberately owns no switch, symbol, feed, or execution API.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Callable, Optional
from uuid import uuid4
import time

from .live_auto_calibration import (
    LiveAutoActivationApproval,
    LiveAutoSelectionCalibration,
    LiveSwitchEligibilityTracker,
    LiveSwitchObservation,
)
from .micro_edge_suitability import (
    MicroEdgeSuitabilityContract,
    MicroEdgeSuitabilityStatus,
)


class LiveAutoRuntimeState(str, Enum):
    STOPPED = "STOPPED"
    ARMED = "ARMED"
    OBSERVING = "OBSERVING"
    CANDIDATE_PENDING = "CANDIDATE_PENDING"
    SWITCH_ELIGIBLE = "SWITCH_ELIGIBLE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class LiveAutoRuntimeObservation:
    candidate_symbol: Optional[str]
    candidate_score: Optional[Decimal]
    active_market_score: Optional[Decimal]
    selected_mode: str = "LIVE"
    dry_run: bool = False
    market_data_fresh: bool = True
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
    runtime_id: Optional[str] = None
    ranking_cycle_id: Optional[str] = None
    observation_id: Optional[str] = None
    configuration_version: str = "ams-live-auto/v1"
    micro_edge_suitability: Optional[MicroEdgeSuitabilityContract] = None


@dataclass(frozen=True)
class LiveActivationProposal:
    """Immutable Phase-1 compare-and-set identity."""

    validation_transaction_id: str
    expected_active_symbol: Optional[str]
    expected_runtime_id: Optional[str]
    expected_candidate: Optional[str]
    expected_ranking_cycle_id: Optional[str]
    expected_observation_id: Optional[str]
    expected_configuration_version: str
    active_since: float
    last_successful_switch_at: Optional[float]
    expected_micro_edge_suitability_identity: Optional[str] = None


@dataclass(frozen=True)
class LiveActivationBoundaryResult:
    """Normalized future SafeSwitch outcome; validation never commits."""

    outcome: str
    boundary_reached: bool
    committed: bool = False
    action_required: bool = False
    reason: Optional[str] = None
    switch_result: object = None


class ValidationOnlySafeSwitchAdapter:
    """AMS-2B invocation boundary with the Live commit guard kept closed."""

    def invoke(self, proposal):
        # Kept as the AMS-7B closed boundary.  AMS-7C may pass its typed
        # permission, but this adapter can still only reject it.
        if proposal is None:
            raise TypeError("activation authority required")
        return LiveActivationBoundaryResult(
            outcome="FAILURE_PRE_COMMIT", boundary_reached=True,
            committed=False, reason="LIVE_COMMIT_DISABLED",
        )


class LiveAutoSelectionRuntime:
    """Evaluate Live AUTO gates without activating or invoking SafeSwitch."""

    def __init__(
        self,
        *,
        active_symbol_provider: Callable[[], Optional[str]],
        approval: Optional[LiveAutoActivationApproval] = None,
        calibration: Optional[LiveAutoSelectionCalibration] = None,
        clock: Optional[Callable[[], object]] = None,
    ):
        if not callable(active_symbol_provider):
            raise TypeError("active symbol provider required")
        self._active_symbol_provider = active_symbol_provider
        self.calibration = calibration or LiveAutoSelectionCalibration()
        self.approval = approval or LiveAutoActivationApproval.restart_default()
        self._clock = clock or time.time
        self._tracker = LiveSwitchEligibilityTracker(self.calibration)
        self._state = LiveAutoRuntimeState.STOPPED
        self._active_since = self._now()
        self._last_observation_at = None
        self._last_successful_switch_at = None
        self._last_result = None
        self._last_observation = None
        self._top_candidate = None
        self._block_reasons = ("LIVE_AUTO_DISABLED",)
        self._activation_proposal = None
        self._activation_state = "DISABLED"
        self._preflight_passed = False
        self._revalidation_passed = False
        self._activation_result = None
        self._permission_state = "NONE"
        self._last_live_switch_result = None
        self._last_live_switch_at = None
        self._action_required = False

    def observe(self, observation):
        """Consume one authoritative rank observation; never perform a switch."""
        if self.approval.live_auto_enabled is not True:
            self._state = LiveAutoRuntimeState.STOPPED
            self._reset_candidate()
            self._block_reasons = ("LIVE_AUTO_DISABLED",)
            self._clear_activation("DISABLED")
            return self.get_status()
        if not isinstance(observation, LiveAutoRuntimeObservation):
            self._state = LiveAutoRuntimeState.FAILED
            self._reset_candidate()
            self._block_reasons = ("LIVE_AUTO_OBSERVATION_INVALID",)
            return self.get_status()

        now = self._now()
        activation_reasons = self._activation_reasons(observation)
        if activation_reasons:
            self._state = (
                LiveAutoRuntimeState.STOPPED
                if "LIVE_AUTO_DISABLED" in activation_reasons
                else LiveAutoRuntimeState.BLOCKED
            )
            self._reset_candidate()
            self._block_reasons = tuple(activation_reasons)
            self._clear_activation("BLOCKED")
            return self.get_status(now=now)

        reset_required = not all((
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
        if (
            not reset_required
            and
            self._last_observation_at is not None
            and now - self._last_observation_at
            < self.calibration.selection_observation_interval_seconds
        ):
            self._state = LiveAutoRuntimeState.OBSERVING
            self._block_reasons = ("OBSERVATION_INTERVAL_PENDING",)
            return self.get_status(now=now)

        self._last_observation_at = now
        self._last_observation = observation
        active_symbol = self._active_symbol()
        active_duration = max(0, int(now - self._active_since))
        since_switch = (
            None if self._last_successful_switch_at is None
            else max(0, int(now - self._last_successful_switch_at))
        )
        eligibility = self._tracker.evaluate(LiveSwitchObservation(
            candidate_symbol=self._symbol(observation.candidate_symbol),
            candidate_score=self._decimal(observation.candidate_score),
            active_symbol=active_symbol,
            active_market_score=self._decimal(observation.active_market_score),
            active_duration_seconds=active_duration,
            seconds_since_successful_switch=since_switch,
            observation_fresh=(
                observation.observation_fresh and observation.market_data_fresh
            ),
            ranking_valid=observation.ranking_valid,
            snapshot_consistent=observation.snapshot_consistent,
            runtime_authority_consistent=observation.runtime_authority_consistent,
            live_account_fresh=observation.live_account_fresh,
            mm_fresh=observation.mm_fresh,
            position_state=observation.position_state,
            pending_order_state=observation.pending_order_state,
            emergency_safe=observation.emergency_safe,
            governance_allow=observation.governance_allow,
            live_status_consistent=observation.live_status_consistent,
        ))
        self._last_result = eligibility
        self._top_candidate = self._symbol(observation.candidate_symbol)
        self._block_reasons = eligibility.reason_codes
        if eligibility.eligible:
            self._state = LiveAutoRuntimeState.SWITCH_ELIGIBLE
            self._activation_proposal = LiveActivationProposal(
                validation_transaction_id="ams-7b-" + uuid4().hex[:20],
                expected_active_symbol=active_symbol,
                expected_runtime_id=observation.runtime_id,
                expected_candidate=self._top_candidate,
                expected_ranking_cycle_id=observation.ranking_cycle_id,
                expected_observation_id=observation.observation_id,
                expected_configuration_version=self.calibration.version,
                active_since=self._active_since,
                last_successful_switch_at=self._last_successful_switch_at,
                expected_micro_edge_suitability_identity=(
                    observation.micro_edge_suitability.evidence_identity
                    if isinstance(observation.micro_edge_suitability, MicroEdgeSuitabilityContract)
                    else None
                ),
            )
            self._activation_state = "PREFLIGHT_PASSED"
            self._preflight_passed = True
            self._revalidation_passed = False
        elif eligibility.consecutive_wins:
            self._state = LiveAutoRuntimeState.CANDIDATE_PENDING
        else:
            self._state = LiveAutoRuntimeState.BLOCKED
        return self.get_status(now=now)

    def validate_activation(self, observation, safe_switch_adapter=None):
        """Phase-2 revalidation and validation-only AMS-2B boundary invocation."""
        proposal = self._activation_proposal
        reasons = list(self.pre_switch_revalidate(observation)["blockReasons"])
        if proposal is None:
            reasons.append("ACTIVATION_PROPOSAL_MISSING")
        elif isinstance(observation, LiveAutoRuntimeObservation):
            if not all((
                proposal.expected_active_symbol, proposal.expected_runtime_id,
                proposal.expected_candidate, proposal.expected_ranking_cycle_id,
                proposal.expected_observation_id,
                proposal.expected_configuration_version,
            )):
                reasons.append("ACTIVATION_CONTEXT_INCOMPLETE")
            current = (
                self._active_symbol(), observation.runtime_id,
                self._symbol(observation.candidate_symbol),
                observation.ranking_cycle_id, observation.observation_id,
                observation.configuration_version,
            )
            expected = (
                proposal.expected_active_symbol, proposal.expected_runtime_id,
                proposal.expected_candidate, proposal.expected_ranking_cycle_id,
                proposal.expected_observation_id,
                proposal.expected_configuration_version,
            )
            if current != expected:
                reasons.append("ACTIVATION_CONTEXT_CHANGED")
            if (proposal.active_since != self._active_since
                    or proposal.last_successful_switch_at != self._last_successful_switch_at):
                reasons.append("ACTIVATION_TIMING_CONTEXT_CHANGED")
            current_suitability_identity = (
                observation.micro_edge_suitability.evidence_identity
                if isinstance(observation.micro_edge_suitability, MicroEdgeSuitabilityContract)
                else None
            )
            if not proposal.expected_micro_edge_suitability_identity:
                reasons.append("MICRO_EDGE_SUITABILITY_IDENTITY_MISSING")
            elif proposal.expected_micro_edge_suitability_identity != current_suitability_identity:
                reasons.append("MICRO_EDGE_SUITABILITY_IDENTITY_CHANGED")
        reasons = list(dict.fromkeys(reasons))
        if reasons:
            self._activation_state = "ABORTED"
            self._revalidation_passed = False
            self._block_reasons = tuple(reasons)
            response = self._activation_response(reasons=reasons)
            self._clear_approval_after_validation()
            return response
        if safe_switch_adapter is None or not callable(
                getattr(safe_switch_adapter, "invoke", None)):
            self._activation_state = "ABORTED"
            response = self._activation_response(
                reasons=["SAFE_SWITCH_ADAPTER_UNAVAILABLE"]
            )
            self._clear_approval_after_validation()
            return response

        self._revalidation_passed = True
        permission = self._issue_permission(proposal)
        result = safe_switch_adapter.invoke(permission)
        if not isinstance(result, LiveActivationBoundaryResult):
            self._activation_state = "FAILED"
            response = self._activation_response(
                reasons=["SAFE_SWITCH_RESULT_INVALID"]
            )
            self._clear_approval_after_validation()
            return response
        self._activation_result = result
        self._permission_state = "CONSUMED"
        switch_result = result.switch_result
        success = bool(switch_result and switch_result.success)
        effective_committed = bool(result.committed and switch_result is not None)
        self._activation_state = "COMPLETED" if success else (
            "FAILED" if result.committed else
            "VALIDATION_ONLY_REJECTED" if result.reason == "LIVE_COMMIT_DISABLED"
            else "ABORTED"
        )
        self._last_live_switch_result = (
            switch_result.to_dict() if switch_result is not None else None
        )
        self._action_required = result.action_required
        if success:
            self.record_successful_switch(switch_result.committed_symbol)
            self._last_live_switch_at = switch_result.committed_at
        reasons = [result.reason] if result.reason else []
        self._block_reasons = tuple(reasons)
        response = self._activation_response(
            reasons=reasons, boundary_reached=result.boundary_reached,
            outcome=result.outcome, action_required=result.action_required,
            committed=effective_committed,
        )
        self._clear_approval_after_validation()
        return response

    def _activation_response(self, *, reasons, boundary_reached=False,
                             outcome="ABORT", action_required=False,
                             committed=False):
        return {
            "activationValidationState": self._activation_state,
            "preflightPassed": self._preflight_passed,
            "revalidationPassed": self._revalidation_passed,
            "activationBlockReasons": reasons,
            "safeSwitchBoundaryReached": boundary_reached,
            "switchCommitted": committed,
            "activeSymbolMutated": committed,
            "outcome": outcome,
            "actionRequired": action_required,
        }

    def pre_switch_revalidate(self, observation):
        """Fail-closed future commit boundary; does not call SafeSwitch."""
        reasons = list(self._activation_reasons(observation)) if isinstance(
            observation, LiveAutoRuntimeObservation
        ) else ["LIVE_AUTO_OBSERVATION_INVALID"]
        if not reasons and self._state is not LiveAutoRuntimeState.SWITCH_ELIGIBLE:
            reasons.append("PERSISTENCE_REVALIDATION_REQUIRED")
        if not reasons and self._symbol(observation.candidate_symbol) != self._top_candidate:
            reasons.append("CANDIDATE_CHANGED")
        if not reasons:
            suitability = observation.micro_edge_suitability
            if not isinstance(suitability, MicroEdgeSuitabilityContract):
                reasons.append("MICRO_EDGE_SUITABILITY_UNAVAILABLE")
            elif not suitability.suitable:
                reasons.append("MICRO_EDGE_SUITABILITY_REJECTED")
            elif not suitability.evidence_identity:
                reasons.append("MICRO_EDGE_SUITABILITY_IDENTITY_MISSING")
            elif suitability.candidate_symbol is not None and (
                    not isinstance(observation.candidate_symbol, str)
                    or suitability.candidate_symbol.strip().upper()
                    != observation.candidate_symbol.strip().upper()):
                reasons.append("MICRO_EDGE_SUITABILITY_CANDIDATE_MISMATCH")
        if not reasons:
            checks = (
                (observation.observation_fresh, "OBSERVATION_STALE"),
                (observation.ranking_valid, "RANKING_INVALID"),
                (observation.snapshot_consistent, "SNAPSHOT_MISMATCH"),
                (observation.runtime_authority_consistent, "RUNTIME_AUTHORITY_INCONSISTENT"),
                (observation.live_account_fresh, "LIVE_ACCOUNT_STALE"),
                (observation.mm_fresh, "MM_STALE"),
                (observation.position_state == "FLAT", "POSITION_NOT_FLAT"),
                (observation.pending_order_state == "NONE", "PENDING_ORDERS_NOT_NONE"),
                (observation.emergency_safe, "EMERGENCY_UNSAFE"),
                (observation.governance_allow, "GOVERNANCE_BLOCK"),
                (observation.live_status_consistent, "LIVE_STATUS_CONSISTENCY_REQUIRED"),
            )
            reasons.extend(reason for passed, reason in checks if not passed)
            candidate = self._decimal(observation.candidate_score)
            active = self._decimal(observation.active_market_score)
            if (candidate is None or active is None
                    or candidate - active < self.calibration.minimum_score_advantage):
                reasons.append("SCORE_ADVANTAGE_INSUFFICIENT")
        return {
            "switchEligible": not reasons,
            "action": "ELIGIBLE_CONTRACT_ONLY" if not reasons else "ABORT",
            "blockReasons": list(dict.fromkeys(reasons)),
            "safeSwitchInvoked": False,
        }

    def record_successful_switch(self, symbol):
        """Update anti-flapping clocks after a future externally committed switch."""
        if self._symbol(symbol) != self._active_symbol():
            raise ValueError("ACTIVE_SYMBOL_AUTHORITY_MISMATCH")
        now = self._now()
        self._last_successful_switch_at = now
        self._active_since = now
        self._reset_candidate()
        self._state = LiveAutoRuntimeState.ARMED
        self._block_reasons = ("SWITCH_COOLDOWN",)

    def restart(self):
        """Apply process restart semantics: approval and transient state are lost."""
        self.approval = LiveAutoActivationApproval.restart_default()
        self._tracker = LiveSwitchEligibilityTracker(self.calibration)
        self._state = LiveAutoRuntimeState.STOPPED
        self._active_since = self._now()
        self._last_observation_at = None
        self._last_successful_switch_at = None
        self._last_result = None
        self._last_observation = None
        self._top_candidate = None
        self._block_reasons = ("LIVE_AUTO_DISABLED",)
        self._clear_activation("DISABLED")
        self._permission_state = "NONE"
        self._last_live_switch_result = None
        self._last_live_switch_at = None
        self._action_required = False
        return self.get_status()

    def get_status(self, *, now=None):
        current = self._now() if now is None else now
        result = self._last_result
        score = result.score_advantage if result is not None else None
        wins = result.consecutive_wins if result is not None else 0
        cooldown = 0
        if self._last_successful_switch_at is not None:
            cooldown = max(0, self.calibration.switch_cooldown_seconds
                           - int(current - self._last_successful_switch_at))
        active = self._active_symbol()
        return {
            "mode": "AUTO_LIVE",
            "liveAutoEnabled": self.approval.live_auto_enabled is True,
            "runtimeState": self._state.value,
            "activeSymbol": active,
            "topCandidate": self._top_candidate,
            "scoreAdvantage": format(score, "f") if score is not None else None,
            "consecutiveWins": wins,
            "requiredConsecutiveWins": self.calibration.required_consecutive_wins,
            "activeDuration": max(0, int(current - self._active_since)),
            "minimumActiveDuration": self.calibration.minimum_active_duration_seconds,
            "cooldownRemaining": cooldown,
            "selectionObservationIntervalSeconds": self.calibration.selection_observation_interval_seconds,
            "switchEligible": bool(result and result.eligible),
            "blockReasons": list(self._block_reasons),
            "configurationVersion": self.calibration.version,
            "approvedConfigurationVersion": self.approval.configuration_version,
            "approvedAt": self.approval.approved_at,
            "approvalIdentity": self.approval.approval_identity,
            "approvalSource": self.approval.approval_source,
            "approvalExpiresAt": self.approval.expires_at,
            "approvalState": self._approval_state(),
            "calibration": self.calibration.to_dict(),
            "automaticSafetyRecoverySwitchEnabled": False,
            "liveAccountState": (
                "FRESH" if self._last_observation and self._last_observation.live_account_fresh
                else "STALE" if self._last_observation else "UNKNOWN"
            ),
            "mmState": (
                "FRESH" if self._last_observation and self._last_observation.mm_fresh
                else "STALE" if self._last_observation else "UNKNOWN"
            ),
            "safeSwitchInvoked": bool(
                self._activation_result and self._activation_result.boundary_reached
            ),
            "switchCommitted": bool(
                self._activation_result and self._activation_result.committed
                and self._activation_result.switch_result is not None
            ),
            "realOrderCreated": False,
            "readOnly": True,
            "activationValidationState": self._activation_state,
            "preflightPassed": self._preflight_passed,
            "revalidationPassed": self._revalidation_passed,
            "activationBlockReasons": list(self._block_reasons),
            "expectedActiveSymbol": (
                self._activation_proposal.expected_active_symbol
                if self._activation_proposal else None
            ),
            "expectedRuntimeId": (
                self._activation_proposal.expected_runtime_id
                if self._activation_proposal else None
            ),
            "expectedCandidate": (
                self._activation_proposal.expected_candidate
                if self._activation_proposal else None
            ),
            "expectedRankingCycleId": (
                self._activation_proposal.expected_ranking_cycle_id
                if self._activation_proposal else None
            ),
            "expectedObservationId": (
                self._activation_proposal.expected_observation_id
                if self._activation_proposal else None
            ),
            "validationTransactionId": (
                self._activation_proposal.validation_transaction_id
                if self._activation_proposal else None
            ),
            "liveSwitchPermissionState": self._permission_state,
            "liveSwitchTransactionState": self._activation_state,
            "lastLiveSwitchResult": self._last_live_switch_result,
            "lastLiveSwitchAt": (
                self._last_live_switch_at.isoformat().replace("+00:00", "Z")
                if self._last_live_switch_at else None
            ),
            "actionRequired": self._action_required,
            "microEdgeSuitabilityStatus": (
                self._last_observation.micro_edge_suitability.status.value
                if self._last_observation is not None
                and isinstance(
                    getattr(self._last_observation, "micro_edge_suitability", None),
                    MicroEdgeSuitabilityContract,
                )
                else None
            ),
            "microEdgeSuitabilityCandidate": (
                self._last_observation.micro_edge_suitability.candidate_symbol
                if self._last_observation is not None
                and isinstance(
                    getattr(self._last_observation, "micro_edge_suitability", None),
                    MicroEdgeSuitabilityContract,
                )
                else None
            ),
            "microEdgeSuitabilityEvaluatedAt": (
                self._last_observation.micro_edge_suitability.evaluated_at.isoformat().replace("+00:00", "Z")
                if self._last_observation is not None
                and isinstance(
                    getattr(self._last_observation, "micro_edge_suitability", None),
                    MicroEdgeSuitabilityContract,
                )
                and isinstance(
                    getattr(self._last_observation.micro_edge_suitability, "evaluated_at", None),
                    datetime,
                )
                else None
            ),
            "microEdgeSuitabilityReason": (
                ", ".join(r.value for r in self._last_observation.micro_edge_suitability.reason_codes)
                if self._last_observation is not None
                and isinstance(
                    getattr(self._last_observation, "micro_edge_suitability", None),
                    MicroEdgeSuitabilityContract,
                )
                else None
            ),
            "microEdgeSuitabilityFresh": (
                self._last_observation.micro_edge_suitability.suitable
                if self._last_observation is not None
                and isinstance(
                    getattr(self._last_observation, "micro_edge_suitability", None),
                    MicroEdgeSuitabilityContract,
                )
                else False
            ),
            "expectedMicroEdgeSuitabilityIdentity": (
                self._activation_proposal.expected_micro_edge_suitability_identity
                if self._activation_proposal else None
            ),
        }

    def _issue_permission(self, proposal):
        """Mint authority only after the existing Phase-2 validation passed."""
        from .live_safe_switch import LiveSymbolSwitchPermission
        now = datetime.fromtimestamp(self._now(), tz=timezone.utc)
        approval = self.approval
        self._permission_state = "ISSUED"
        suitability = self._last_observation.micro_edge_suitability if self._last_observation else None
        return LiveSymbolSwitchPermission(
            enabled=True,
            configuration_version=proposal.expected_configuration_version,
            approval_identity=approval.approval_identity,
            approval_source=approval.approval_source,
            approved_at=approval.approved_at,
            expected_active_symbol=proposal.expected_active_symbol,
            expected_runtime_id=proposal.expected_runtime_id,
            proposed_symbol=proposal.expected_candidate,
            ranking_cycle_id=proposal.expected_ranking_cycle_id,
            observation_id=proposal.expected_observation_id,
            validation_transaction_id=proposal.validation_transaction_id,
            issued_at=now, expires_at=now + timedelta(seconds=30),
            micro_edge_suitability_identity=(
                suitability.evidence_identity if isinstance(suitability, MicroEdgeSuitabilityContract) else None
            ),
            micro_edge_suitability_status=(
                suitability.status.value if isinstance(suitability, MicroEdgeSuitabilityContract) else None
            ),
            micro_edge_suitability_evaluated_at=(
                suitability.evaluated_at if isinstance(suitability, MicroEdgeSuitabilityContract) else None
            ),
        )

    def _activation_reasons(self, observation):
        reasons = []
        approval = self.approval
        if approval.live_auto_enabled is not True:
            reasons.append("LIVE_AUTO_DISABLED")
        if str(observation.selected_mode).strip().upper() != "LIVE":
            reasons.append("SELECTED_MODE_NOT_LIVE")
        if observation.dry_run is not False:
            reasons.append("DRY_RUN_ACTIVE")
        if approval.configuration_version != self.calibration.version:
            reasons.append("CONFIGURATION_VERSION_MISMATCH")
        if not self._approval_metadata_valid(approval):
            reasons.append("EXPLICIT_OPERATOR_APPROVAL_REQUIRED")
        elif self._approval_expired(approval):
            reasons.append("OPERATOR_APPROVAL_EXPIRED")
        if not observation.market_data_fresh:
            reasons.append("MARKET_DATA_STALE")
        suitability = observation.micro_edge_suitability
        if not isinstance(suitability, MicroEdgeSuitabilityContract):
            reasons.append("MICRO_EDGE_SUITABILITY_UNAVAILABLE")
        elif not suitability.suitable:
            if suitability.status is MicroEdgeSuitabilityStatus.STALE:
                reasons.append("MICRO_EDGE_SUITABILITY_STALE")
            elif suitability.status is MicroEdgeSuitabilityStatus.INVALID:
                reasons.append("MICRO_EDGE_SUITABILITY_INVALID")
            elif suitability.status is MicroEdgeSuitabilityStatus.UNSUITABLE:
                reasons.append("MICRO_EDGE_SUITABILITY_REJECTED")
            else:
                reasons.append("MICRO_EDGE_SUITABILITY_UNAVAILABLE")
        elif not suitability.evidence_identity:
            reasons.append("MICRO_EDGE_SUITABILITY_IDENTITY_MISSING")
        return reasons

    @staticmethod
    def _approval_metadata_valid(approval):
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                approval.approved_at,
                approval.approval_identity,
                approval.approval_source,
            )
        ):
            return False
        try:
            approved_at = datetime.fromisoformat(
                approval.approved_at.strip().replace("Z", "+00:00")
            )
        except ValueError:
            return False
        return approved_at.tzinfo is not None

    def _approval_state(self):
        if self.approval.live_auto_enabled is not True:
            return "NONE"
        if not self._approval_metadata_valid(self.approval):
            return "INVALID"
        return "EXPIRED" if self._approval_expired(self.approval) else "APPROVED"

    def _approval_expired(self, approval):
        value = getattr(approval, "expires_at", None)
        # Legacy in-process callers predate expiry metadata. The production
        # control bridge always supplies a bounded expires_at value.
        if value is None:
            return False
        if not isinstance(value, str) or not value.strip():
            return True
        try:
            expires_at = datetime.fromisoformat(
                value.strip().replace("Z", "+00:00")
            )
        except ValueError:
            return True
        if expires_at.tzinfo is None:
            return True
        return datetime.fromtimestamp(
            self._now(), tz=timezone.utc
        ) > expires_at.astimezone(timezone.utc)

    def _reset_candidate(self):
        self._tracker = LiveSwitchEligibilityTracker(self.calibration)
        self._last_result = None
        self._top_candidate = None

    def _clear_activation(self, state):
        self._activation_proposal = None
        self._activation_state = state
        self._preflight_passed = False
        self._revalidation_passed = False
        self._activation_result = None
        self._permission_state = "NONE"

    def _clear_approval_after_validation(self):
        """Approval and proposal are one-shot; post-commit failure remains FAILED."""
        self.approval = LiveAutoActivationApproval.restart_default()
        self._activation_proposal = None
        self._tracker = LiveSwitchEligibilityTracker(self.calibration)
        self._state = (
            LiveAutoRuntimeState.FAILED if self._action_required
            else LiveAutoRuntimeState.STOPPED
        )

    def _active_symbol(self):
        return self._symbol(self._active_symbol_provider())

    @staticmethod
    def _symbol(value):
        return str(value).strip().upper() if value else None

    @staticmethod
    def _decimal(value):
        if value is None or isinstance(value, bool):
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def _now(self):
        value = self._clock()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise TypeError("timezone-aware clock required")
            return value.timestamp()
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("numeric or timezone-aware clock required")
        return float(value)
