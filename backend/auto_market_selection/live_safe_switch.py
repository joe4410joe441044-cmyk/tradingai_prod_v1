"""AMS-7C one-shot authority for a limited Live symbol switch.

This module grants authority only to the AMS-2B active-symbol/feed transaction.
It never grants order, leverage, margin, cancel, or transfer authority.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from .safe_switch import SafeSymbolSwitch
from .selection_proposal import SelectionProposal
from .live_auto_runtime import LiveActivationBoundaryResult


@dataclass(frozen=True)
class LiveSymbolSwitchPermission:
    enabled: bool
    configuration_version: str
    approval_identity: str
    approval_source: str
    approved_at: str
    expected_active_symbol: str
    expected_runtime_id: str
    proposed_symbol: str
    ranking_cycle_id: str
    observation_id: str
    validation_transaction_id: str
    issued_at: datetime
    expires_at: datetime
    micro_edge_suitability_identity: Optional[str] = None
    micro_edge_suitability_status: Optional[str] = None
    micro_edge_suitability_evaluated_at: Optional[datetime] = None


class _PermissionRuntime:
    """Adds AMS-7C identity/CAS barriers to an AMS-2B runtime."""

    def __init__(self, runtime, permission, state_provider):
        self._runtime = runtime
        self._permission = permission
        self._state_provider = state_provider

    def __getattr__(self, name):
        return getattr(self._runtime, name)

    def _identity_valid(self):
        try:
            state = self._state_provider()
        except Exception:
            return False
        p = self._permission
        return isinstance(state, dict) and all((
            isinstance(p.micro_edge_suitability_identity, str),
            bool(p.micro_edge_suitability_identity.strip())
            if isinstance(p.micro_edge_suitability_identity, str) else False,
            p.micro_edge_suitability_status == "SUITABLE",
            isinstance(p.micro_edge_suitability_evaluated_at, datetime),
            state.get("activeSymbol") == p.expected_active_symbol,
            state.get("activeRuntimeId") == p.expected_runtime_id,
            state.get("rankingCycleId") == p.ranking_cycle_id,
            state.get("observationId") == p.observation_id,
            state.get("configurationVersion") == p.configuration_version,
            state.get("candidateSymbol") == p.proposed_symbol,
            state.get("marketDataFresh") is True,
            state.get("liveAccountFresh") is True,
            state.get("mmFresh") is True,
            state.get("positionState") == "FLAT",
            state.get("pendingOrderState") == "NONE",
            state.get("emergencySafe") is True,
            state.get("governanceAllow") is True,
            state.get("runtimeConsistent") is True,
            state.get("snapshotConsistent") is True,
            state.get("statusConsistent") is True,
            state.get("realOrderAllowed") is False,
            state.get("autoTradeEnabled") is False,
            state.get("executionRealOrderEnabled") is False,
            state.get("microEdgeSuitabilityIdentity")
            == p.micro_edge_suitability_identity,
            state.get("microEdgeSuitabilityStatus") == "SUITABLE",
        ))

    def revalidate_switch(self, proposal):
        state = self._runtime.revalidate_switch(proposal)
        if not self._identity_valid():
            return None
        return state

    def commit_active_symbol(self, expected, proposed, handle, transaction_id):
        p = self._permission
        if (expected != p.expected_active_symbol or proposed != p.proposed_symbol
                or not self._identity_valid()):
            return False
        limited_live_commit = getattr(
            self._runtime, "commit_limited_live_active_symbol", None
        )
        if callable(limited_live_commit):
            return limited_live_commit(
                expected, proposed, handle, transaction_id, p
            )
        return self._runtime.commit_active_symbol(expected, proposed, handle, transaction_id)


class LimitedLiveSafeSwitchAdapter:
    """Consumes one permission and invokes the sole AMS-2B transaction engine."""

    def __init__(self, runtime, *, selection_proposal_provider: Callable,
                 final_state_provider: Callable, clock=None):
        self._runtime = runtime
        self._proposal_provider = selection_proposal_provider
        self._state_provider = final_state_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._consumed = set()

    def invoke(self, permission):
        if not isinstance(permission, LiveSymbolSwitchPermission):
            return self._rejected("LIVE_SWITCH_PERMISSION_REQUIRED")
        identity = permission.validation_transaction_id
        if identity in self._consumed:
            return self._rejected("LIVE_SWITCH_PERMISSION_REUSED")
        # Consume before any external/runtime operation: every attempt is one-shot.
        self._consumed.add(identity)
        now = self._utc(self._clock())
        if permission.enabled is not True:
            return self._rejected("LIVE_SWITCH_PERMISSION_DISABLED")
        if now < self._utc(permission.issued_at) or now > self._utc(permission.expires_at):
            return self._rejected("LIVE_SWITCH_PERMISSION_EXPIRED")
        if permission.configuration_version != "ams-live-auto/v1":
            return self._rejected("CONFIGURATION_VERSION_MISMATCH")
        try:
            proposal = self._proposal_provider(permission)
        except Exception:
            return self._rejected("SELECTION_PROPOSAL_UNAVAILABLE")
        if (not isinstance(proposal, SelectionProposal)
                or proposal.current_active_symbol != permission.expected_active_symbol
                or proposal.proposed_symbol != permission.proposed_symbol
                or proposal.ranking_cycle_id != permission.ranking_cycle_id):
            return self._rejected("SELECTION_PROPOSAL_IDENTITY_MISMATCH")

        guarded = _PermissionRuntime(self._runtime, permission, self._state_provider)
        result = SafeSymbolSwitch(guarded).execute(proposal, started_at=now)
        reason = result.reason_codes[0].value if result.reason_codes else None
        outcome = ("SUCCESS" if result.success else
                   "FAILURE_POST_COMMIT" if result.active_symbol_committed else
                   "FAILURE_PRE_COMMIT")
        return LiveActivationBoundaryResult(
            outcome=outcome, boundary_reached=True,
            committed=result.active_symbol_committed,
            action_required=result.active_symbol_committed and not result.success,
            reason=reason, switch_result=result,
        )

    @staticmethod
    def _rejected(reason):
        return LiveActivationBoundaryResult(
            "FAILURE_PRE_COMMIT", True, reason=reason
        )

    @staticmethod
    def _utc(value):
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError("timezone-aware datetime required")
        return value.astimezone(timezone.utc)
