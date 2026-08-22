"""AMS-2B fail-closed safe symbol switch transaction orchestration."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import logging
import math
import threading
from typing import Optional, Tuple

from .selection_proposal import ProposalStatus, SelectionProposal


logger = logging.getLogger(__name__)


class SwitchState(str, Enum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    SUBSCRIBING = "SUBSCRIBING"
    VALIDATING = "VALIDATING"
    COMMITTING = "COMMITTING"
    CLEANUP = "CLEANUP"
    COMPLETED = "COMPLETED"
    NOT_READY = "NOT_READY"
    FAILED = "FAILED"


class SwitchReason(str, Enum):
    PROPOSAL_NOT_ELIGIBLE = "PROPOSAL_NOT_ELIGIBLE"
    PROPOSAL_STALE = "PROPOSAL_STALE"
    ACTIVE_SYMBOL_CHANGED_SINCE_PROPOSAL = "ACTIVE_SYMBOL_CHANGED_SINCE_PROPOSAL"
    POSITION_NOT_FLAT = "POSITION_NOT_FLAT"
    POSITION_STATE_UNKNOWN = "POSITION_STATE_UNKNOWN"
    PENDING_ORDER_EXISTS = "PENDING_ORDER_EXISTS"
    PENDING_ORDER_UNKNOWN = "PENDING_ORDER_UNKNOWN"
    MM_UNAVAILABLE = "MM_UNAVAILABLE"
    MM_STALE = "MM_STALE"
    EMERGENCY_UNSAFE = "EMERGENCY_UNSAFE"
    ENTRY_PAUSE_FAILED = "ENTRY_PAUSE_FAILED"
    NEW_FEED_SUBSCRIBE_FAILED = "NEW_FEED_SUBSCRIBE_FAILED"
    NEW_SNAPSHOT_NOT_READY = "NEW_SNAPSHOT_NOT_READY"
    NEW_SNAPSHOT_INVALID = "NEW_SNAPSHOT_INVALID"
    NEW_SNAPSHOT_STALE = "NEW_SNAPSHOT_STALE"
    SYMBOL_MISMATCH = "SYMBOL_MISMATCH"
    SEQUENCE_INVALID = "SEQUENCE_INVALID"
    ACTIVE_SYMBOL_COMMIT_FAILED = "ACTIVE_SYMBOL_COMMIT_FAILED"
    OLD_FEED_CLEANUP_FAILED = "OLD_FEED_CLEANUP_FAILED"
    DOWNSTREAM_SYNC_FAILED = "DOWNSTREAM_SYNC_FAILED"
    PIPELINE_RESUME_FAILED = "PIPELINE_RESUME_FAILED"
    SWITCH_ALREADY_IN_PROGRESS = "SWITCH_ALREADY_IN_PROGRESS"


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _time(value):
    return _utc(value).isoformat().replace("+00:00", "Z") if value else None


@dataclass(frozen=True)
class SwitchResult:
    switch_transaction_id: str
    selection_proposal_id: str
    scanner_cycle_id: str
    ranking_cycle_id: str
    audit_event_id: str
    previous_symbol: Optional[str]
    proposed_symbol: Optional[str]
    committed_symbol: Optional[str]
    started_at: datetime
    committed_at: Optional[datetime]
    completed_at: datetime
    state: SwitchState
    success: bool
    entry_paused: bool
    new_feed_validated: bool
    active_symbol_committed: bool
    old_feed_detached: bool
    pipeline_resumed: bool
    reason_codes: Tuple[SwitchReason, ...]

    def to_dict(self):
        return {
            "switchTransactionId": self.switch_transaction_id,
            "selectionProposalId": self.selection_proposal_id,
            "scannerCycleId": self.scanner_cycle_id,
            "rankingCycleId": self.ranking_cycle_id,
            "auditEventId": self.audit_event_id,
            "previousSymbol": self.previous_symbol,
            "proposedSymbol": self.proposed_symbol,
            "committedSymbol": self.committed_symbol,
            "startedAt": _time(self.started_at),
            "committedAt": _time(self.committed_at),
            "completedAt": _time(self.completed_at),
            "state": self.state.value,
            "success": self.success,
            "entryPaused": self.entry_paused,
            "newFeedValidated": self.new_feed_validated,
            "activeSymbolCommitted": self.active_symbol_committed,
            "oldFeedDetached": self.old_feed_detached,
            "pipelineResumed": self.pipeline_resumed,
            "reasonCodes": [item.value for item in self.reason_codes],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class SnapshotNotReady:
    """Typed evidence that a feed exists but has not published a snapshot."""

    reason: str = "FIRST_SNAPSHOT_TIMEOUT"


class SafeSymbolSwitch:
    """Serial transaction coordinator over an explicit runtime boundary.

    Runtime methods are intentionally small: revalidate_switch, pause_new_entries,
    prepare_new_feed, read_new_snapshot, commit_active_symbol, sync_downstream,
    cleanup_old_feed, resume_new_entries, and cleanup_new_feed.
    """

    def __init__(self, runtime, *, maximum_proposal_age_seconds=300,
                 maximum_snapshot_age_seconds=5):
        self.runtime = runtime
        self.maximum_proposal_age_seconds = maximum_proposal_age_seconds
        self.maximum_snapshot_age_seconds = maximum_snapshot_age_seconds
        self._lock = threading.Lock()
        self.state = SwitchState.IDLE

    def execute(self, proposal, *, started_at):
        started_at = _utc(started_at)
        transaction_id = self._identity(proposal, started_at)
        if not self._lock.acquire(blocking=False):
            return self._result(proposal, transaction_id, started_at, started_at,
                                reasons=(SwitchReason.SWITCH_ALREADY_IN_PROGRESS,))
        try:
            return self._execute_locked(proposal, transaction_id, started_at)
        finally:
            self._lock.release()

    def _execute_locked(self, proposal, transaction_id, started_at):
        reason = self._validate_input(proposal, started_at)
        if reason:
            return self._result(proposal, transaction_id, started_at, started_at,
                                reasons=(reason,))

        self.state = SwitchState.PREPARING
        current = self.runtime.revalidate_switch(proposal)
        reason = self._revalidation_reason(proposal, current, started_at)
        if reason:
            return self._result(proposal, transaction_id, started_at, started_at,
                                reasons=(reason,))

        paused = False
        handle = None
        validated = committed = detached = resumed = False
        committed_at = None
        try:
            if self.runtime.pause_new_entries(transaction_id) is not True:
                return self._result(proposal, transaction_id, started_at, started_at,
                                    reasons=(SwitchReason.ENTRY_PAUSE_FAILED,))
            paused = True
            self.state = SwitchState.SUBSCRIBING
            handle = self.runtime.prepare_new_feed(
                proposal.proposed_symbol, proposal.proposed_exchange_symbol,
                transaction_id,
            )
            if handle is None:
                return self._precommit_failure(
                    proposal, transaction_id, started_at, paused, handle,
                    SwitchReason.NEW_FEED_SUBSCRIBE_FAILED,
                )

            self.state = SwitchState.VALIDATING
            snapshot = self.runtime.read_new_snapshot(handle)
            validation_time = _utc(self.runtime.now())
            reason = self._snapshot_reason(proposal, snapshot, validation_time)
            if reason:
                return self._precommit_failure(
                    proposal, transaction_id, started_at, paused, handle, reason,
                )
            validated = True
            # The full barrier is acquired again immediately before commit.
            reason = self._validate_input(proposal, validation_time)
            if reason:
                return self._precommit_failure(
                    proposal, transaction_id, started_at, paused, handle, reason,
                )
            current = self.runtime.revalidate_switch(proposal)
            reason = self._revalidation_reason(proposal, current, started_at)
            if reason:
                return self._precommit_failure(
                    proposal, transaction_id, started_at, paused, handle, reason,
                )

            self.state = SwitchState.COMMITTING
            if self.runtime.commit_active_symbol(
                    proposal.current_active_symbol, proposal.proposed_symbol,
                    handle, transaction_id) is not True:
                return self._precommit_failure(
                    proposal, transaction_id, started_at, paused, handle,
                    SwitchReason.ACTIVE_SYMBOL_COMMIT_FAILED,
                )
            committed = True
            committed_at = _utc(self.runtime.now())

            if self.runtime.sync_downstream(proposal.proposed_symbol, handle) is not True:
                return self._postcommit_failure(
                    proposal, transaction_id, started_at, committed_at,
                    paused, validated, SwitchReason.DOWNSTREAM_SYNC_FAILED,
                )
            self.state = SwitchState.CLEANUP
            if self.runtime.cleanup_old_feed(handle) is not True:
                return self._postcommit_failure(
                    proposal, transaction_id, started_at, committed_at,
                    paused, validated, SwitchReason.OLD_FEED_CLEANUP_FAILED,
                )
            detached = True
            if self.runtime.resume_new_entries(transaction_id) is not True:
                return self._postcommit_failure(
                    proposal, transaction_id, started_at, committed_at,
                    paused, validated, SwitchReason.PIPELINE_RESUME_FAILED,
                    detached=detached,
                )
            paused = False
            resumed = True
            self.state = SwitchState.COMPLETED
            completed = _utc(self.runtime.now())
            return self._result(
                proposal, transaction_id, started_at, completed,
                committed_at=committed_at, success=True, entry_paused=paused,
                validated=validated, committed=committed, detached=detached,
                resumed=resumed,
            )
        except Exception:
            logger.exception("Safe symbol transaction exception state=%s", self.state.value)
            reason = (SwitchReason.OLD_FEED_CLEANUP_FAILED if committed
                      else SwitchReason.NEW_FEED_SUBSCRIBE_FAILED)
            if committed:
                return self._postcommit_failure(
                    proposal, transaction_id, started_at, committed_at,
                    paused, validated, reason, detached=detached,
                )
            return self._precommit_failure(
                proposal, transaction_id, started_at, paused, handle, reason,
            )

    def _precommit_failure(self, proposal, transaction_id, started_at,
                           paused, handle, reason):
        if handle is not None:
            try:
                self.runtime.cleanup_new_feed(handle)
            except Exception:
                pass
        if paused:
            try:
                paused = self.runtime.resume_new_entries(transaction_id) is not True
            except Exception:
                paused = True
        return self._result(proposal, transaction_id, started_at,
                            _utc(self.runtime.now()), entry_paused=paused,
                            reasons=(reason,))

    def _postcommit_failure(self, proposal, transaction_id, started_at,
                            committed_at, paused, validated, reason, detached=False):
        return self._result(
            proposal, transaction_id, started_at, _utc(self.runtime.now()),
            committed_at=committed_at, entry_paused=True, validated=validated,
            committed=True, detached=detached, reasons=(reason,),
        )

    def _validate_input(self, proposal, now):
        if (not isinstance(proposal, SelectionProposal)
                or proposal.proposal_status is not ProposalStatus.PROPOSED
                or proposal.switch_eligible is not True
                or not proposal.proposed_symbol or not proposal.current_active_symbol
                or proposal.proposed_symbol == proposal.current_active_symbol):
            return SwitchReason.PROPOSAL_NOT_ELIGIBLE
        age = (now - _utc(proposal.proposed_at)).total_seconds()
        if age < 0 or age > self.maximum_proposal_age_seconds:
            return SwitchReason.PROPOSAL_STALE
        return None

    @staticmethod
    def _revalidation_reason(proposal, state, now):
        if not isinstance(state, dict):
            return SwitchReason.POSITION_STATE_UNKNOWN
        if state.get("activeSymbol") != proposal.current_active_symbol:
            return SwitchReason.ACTIVE_SYMBOL_CHANGED_SINCE_PROPOSAL
        position = state.get("positionState")
        if position not in {"FLAT", "OPEN"}:
            return SwitchReason.POSITION_STATE_UNKNOWN
        if position != "FLAT":
            return SwitchReason.POSITION_NOT_FLAT
        pending = state.get("pendingOrder")
        if type(pending) is not bool:
            return SwitchReason.PENDING_ORDER_UNKNOWN
        if pending:
            return SwitchReason.PENDING_ORDER_EXISTS
        if state.get("mmAvailable") is not True:
            return SwitchReason.MM_UNAVAILABLE
        if state.get("mmFresh") is not True:
            return SwitchReason.MM_STALE
        if state.get("emergencySafe") is not True:
            return SwitchReason.EMERGENCY_UNSAFE
        return None

    def _snapshot_reason(self, proposal, snapshot, now):
        if isinstance(snapshot, SnapshotNotReady):
            return SwitchReason.NEW_SNAPSHOT_NOT_READY
        if not isinstance(snapshot, dict):
            return SwitchReason.NEW_SNAPSHOT_INVALID
        if (snapshot.get("symbol") != proposal.proposed_symbol
                or snapshot.get("exchangeSymbol") != proposal.proposed_exchange_symbol):
            return SwitchReason.SYMBOL_MISMATCH
        timestamp = snapshot.get("timestamp")
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            return SwitchReason.NEW_SNAPSHOT_STALE
        age = (now - _utc(timestamp)).total_seconds()
        if age < 0 or age > self.maximum_snapshot_age_seconds:
            return SwitchReason.NEW_SNAPSHOT_STALE
        sequence = snapshot.get("sequence")
        if type(sequence) is not int or sequence < 0 or snapshot.get("sequenceValid") is not True:
            return SwitchReason.SEQUENCE_INVALID
        bids, asks = snapshot.get("bids"), snapshot.get("asks")
        if not isinstance(bids, dict) or not isinstance(asks, dict) or not bids or not asks:
            return SwitchReason.NEW_SNAPSHOT_INVALID
        try:
            best_bid, best_ask = max(map(float, bids)), min(map(float, asks))
        except (TypeError, ValueError):
            return SwitchReason.NEW_SNAPSHOT_INVALID
        if not all(map(math.isfinite, (best_bid, best_ask))) or not 0 < best_bid < best_ask:
            return SwitchReason.NEW_SNAPSHOT_INVALID
        return None

    @staticmethod
    def _identity(proposal, started_at):
        proposal_id = getattr(proposal, "selection_proposal_id", None)
        payload = json.dumps({"proposalId": proposal_id, "startedAt": _time(started_at)},
                             sort_keys=True, separators=(",", ":"))
        return "ams-2b-" + sha256(payload.encode("utf-8")).hexdigest()[:20]

    def _result(self, proposal, transaction_id, started_at, completed_at, *,
                committed_at=None, success=False, entry_paused=False,
                validated=False, committed=False, detached=False, resumed=False,
                reasons=()):
        retryable = (
            not success
            and tuple(reasons) == (SwitchReason.NEW_SNAPSHOT_NOT_READY,)
        )
        self.state = (
            SwitchState.COMPLETED
            if success
            else SwitchState.NOT_READY
            if retryable
            else SwitchState.FAILED
        )
        result = SwitchResult(
            transaction_id, getattr(proposal, "selection_proposal_id", ""),
            getattr(proposal, "scanner_cycle_id", ""),
            getattr(proposal, "ranking_cycle_id", ""),
            getattr(proposal, "audit_event_id", ""),
            getattr(proposal, "current_active_symbol", None),
            getattr(proposal, "proposed_symbol", None),
            getattr(proposal, "proposed_symbol", None) if committed else None,
            started_at, committed_at, completed_at, self.state, success,
            entry_paused, validated, committed, detached, resumed, tuple(reasons),
        )
        publisher = getattr(self.runtime, "publish_switch_result", None)
        if callable(publisher):
            publisher(result)
        return result


class InitialSymbolCommit(SafeSymbolSwitch):
    """Fail-closed transaction for an AUTO initial symbol commit."""

    def _validate_input(self, proposal, now):
        if (not isinstance(proposal, SelectionProposal)
                or proposal.proposal_status is not ProposalStatus.PROPOSED
                or proposal.switch_eligible is not True
                or not proposal.proposed_symbol
                or proposal.current_active_symbol is not None):
            return SwitchReason.PROPOSAL_NOT_ELIGIBLE
        age = (now - _utc(proposal.proposed_at)).total_seconds()
        if age < 0 or age > self.maximum_proposal_age_seconds:
            return SwitchReason.PROPOSAL_STALE
        return None
