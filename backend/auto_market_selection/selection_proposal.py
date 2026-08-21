"""AMS-2A read-only boundary between ranking and Active Symbol Authority."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping, Optional, Tuple

from backend.money_management.capital_eligibility import CapitalEligibilityContract
from .candidate_ranking import RankingCycleResult
from .selection_audit import SelectionAuditEvent


class SelectionMode(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"


class PositionState(str, Enum):
    FLAT = "FLAT"
    OPEN = "OPEN"
    UNKNOWN = "UNKNOWN"


class PendingOrderState(str, Enum):
    NONE = "NONE"
    EXISTS = "EXISTS"
    UNKNOWN = "UNKNOWN"


class SelectionProposalReason(str, Enum):
    NO_TOP_CANDIDATE = "NO_TOP_CANDIDATE"
    NO_SWITCH_REQUIRED = "NO_SWITCH_REQUIRED"
    ACTIVE_SYMBOL_UNAVAILABLE = "ACTIVE_SYMBOL_UNAVAILABLE"
    POSITION_NOT_FLAT = "POSITION_NOT_FLAT"
    POSITION_STATE_UNKNOWN = "POSITION_STATE_UNKNOWN"
    PENDING_ORDER_EXISTS = "PENDING_ORDER_EXISTS"
    PENDING_ORDER_UNKNOWN = "PENDING_ORDER_UNKNOWN"
    MM_UNAVAILABLE = "MM_UNAVAILABLE"
    MM_STALE = "MM_STALE"
    EMERGENCY_UNSAFE = "EMERGENCY_UNSAFE"
    PROPOSAL_STALE = "PROPOSAL_STALE"


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _encoded(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encoded(item) for item in value]
    return value


def snapshot_active_symbol_authority(bot_manager):
    """Read BotManager's existing authority without mutating runtime state."""
    getter = getattr(bot_manager, "get_active_symbol_contract", None)
    if not callable(getter):
        return {"activeSymbol": None, "selectionMode": None}
    snapshot = getter()
    if not isinstance(snapshot, Mapping):
        return {"activeSymbol": None, "selectionMode": None}
    return {
        "activeSymbol": snapshot.get("activeSymbol"),
        "selectionMode": snapshot.get("selectionMode"),
    }


@dataclass(frozen=True)
class SelectionProposal:
    selection_proposal_id: str
    scanner_cycle_id: str
    ranking_cycle_id: str
    audit_event_id: str
    proposed_symbol: Optional[str]
    proposed_exchange_symbol: Optional[str]
    current_active_symbol: Optional[str]
    selection_mode: SelectionMode
    proposal_status: ProposalStatus
    ranking_score: Optional[Decimal]
    rank: Optional[int]
    proposed_at: datetime
    position_state: PositionState
    pending_order_state: PendingOrderState
    switch_eligible: bool
    switch_block_reasons: Tuple[SelectionProposalReason, ...]
    reason_codes: Tuple[SelectionProposalReason, ...]

    def to_dict(self):
        return {
            "selectionProposalId": self.selection_proposal_id,
            "scannerCycleId": self.scanner_cycle_id,
            "rankingCycleId": self.ranking_cycle_id,
            "auditEventId": self.audit_event_id,
            "proposedSymbol": self.proposed_symbol,
            "proposedExchangeSymbol": self.proposed_exchange_symbol,
            "currentActiveSymbol": self.current_active_symbol,
            "selectionMode": self.selection_mode.value,
            "proposalStatus": self.proposal_status.value,
            "rankingScore": _encoded(self.ranking_score),
            "rank": self.rank,
            "proposedAt": _encoded(self.proposed_at),
            "positionState": self.position_state.value,
            "pendingOrderState": self.pending_order_state.value,
            "switchEligible": self.switch_eligible,
            "switchBlockReasons": _encoded(self.switch_block_reasons),
            "reasonCodes": _encoded(self.reason_codes),
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def _selection_mode(authority):
    raw = authority.get("selectionMode") if isinstance(authority, Mapping) else None
    try:
        return SelectionMode(str(raw).upper())
    except (TypeError, ValueError):
        return SelectionMode.MANUAL


def _active_symbol(authority):
    raw = authority.get("activeSymbol") if isinstance(authority, Mapping) else None
    return str(raw).strip().upper() if raw is not None and str(raw).strip() else None


def _position_state(value):
    if isinstance(value, PositionState):
        return value
    normalized = str(value).strip().upper() if value is not None else "UNKNOWN"
    if normalized in {"OPEN", "REMAINING"}:
        return PositionState.OPEN
    if normalized == "FLAT":
        return PositionState.FLAT
    return PositionState.UNKNOWN


def _pending_state(value):
    if isinstance(value, PendingOrderState):
        return value
    if isinstance(value, Mapping):
        if value.get("known") is not True:
            return PendingOrderState.UNKNOWN
        value = value.get("pending")
    if value is True:
        return PendingOrderState.EXISTS
    if value is False:
        return PendingOrderState.NONE
    normalized = str(value).strip().upper() if value is not None else "UNKNOWN"
    if normalized in {"EXISTS", "REMAINING"}:
        return PendingOrderState.EXISTS
    if normalized in {"NONE", "FLAT"}:
        return PendingOrderState.NONE
    return PendingOrderState.UNKNOWN


def build_selection_proposal(
    ranking_result, audit_event, *, active_symbol_authority,
    position_state, pending_order_state, mm_authority, emergency_safe,
    proposed_at=None, maximum_proposal_age_seconds=300,
    allow_initial_selection=False,
):
    """Build a deterministic proposal. No switch, I/O, or runtime mutation occurs."""
    if not isinstance(ranking_result, RankingCycleResult):
        raise TypeError("RankingCycleResult required")
    if not isinstance(audit_event, SelectionAuditEvent):
        raise TypeError("SelectionAuditEvent required")
    if (audit_event.ranking_cycle_id != ranking_result.ranking_cycle_id
            or audit_event.scanner_cycle_id != ranking_result.scanner_cycle_id):
        raise ValueError("proposal ranking/audit correlation mismatch")
    now = _utc(proposed_at or ranking_result.evaluated_at)
    if maximum_proposal_age_seconds <= 0:
        raise ValueError("maximum_proposal_age_seconds must be positive")

    top = ranking_result.top_candidate
    proposed_symbol = top.symbol if top else None
    exchange_by_symbol = {item.symbol: item.exchange_symbol for item in audit_event.candidates}
    if proposed_symbol is not None and proposed_symbol not in exchange_by_symbol:
        raise ValueError("topCandidate missing from audit event")
    proposed_exchange_symbol = exchange_by_symbol.get(proposed_symbol)
    active_symbol = _active_symbol(active_symbol_authority)
    mode = _selection_mode(active_symbol_authority)
    position = _position_state(position_state)
    pending = _pending_state(pending_order_state)

    reasons = []
    if top is None:
        reasons.append(SelectionProposalReason.NO_TOP_CANDIDATE)
    if active_symbol is None and allow_initial_selection is not True:
        reasons.append(SelectionProposalReason.ACTIVE_SYMBOL_UNAVAILABLE)
    if proposed_symbol is not None and proposed_symbol == active_symbol:
        reasons.append(SelectionProposalReason.NO_SWITCH_REQUIRED)
    if position is PositionState.UNKNOWN:
        reasons.append(SelectionProposalReason.POSITION_STATE_UNKNOWN)
    elif position is PositionState.OPEN:
        reasons.append(SelectionProposalReason.POSITION_NOT_FLAT)
    if pending is PendingOrderState.UNKNOWN:
        reasons.append(SelectionProposalReason.PENDING_ORDER_UNKNOWN)
    elif pending is PendingOrderState.EXISTS:
        reasons.append(SelectionProposalReason.PENDING_ORDER_EXISTS)
    if not isinstance(mm_authority, CapitalEligibilityContract):
        reasons.append(SelectionProposalReason.MM_UNAVAILABLE)
    elif not mm_authority.authority_fresh:
        reasons.append(SelectionProposalReason.MM_STALE)
    if emergency_safe is not True:
        reasons.append(SelectionProposalReason.EMERGENCY_UNSAFE)
    age = (now - _utc(ranking_result.evaluated_at)).total_seconds()
    if age < 0 or age > maximum_proposal_age_seconds:
        reasons.append(SelectionProposalReason.PROPOSAL_STALE)

    # Stable enum declaration order is also the canonical reason order.
    reason_set = set(reasons)
    ordered = tuple(reason for reason in SelectionProposalReason if reason in reason_set)
    switch_eligible = not ordered
    fields = {
        "scannerCycleId": ranking_result.scanner_cycle_id,
        "rankingCycleId": ranking_result.ranking_cycle_id,
        "auditEventId": audit_event.event_id,
        "proposedSymbol": proposed_symbol,
        "proposedExchangeSymbol": proposed_exchange_symbol,
        "currentActiveSymbol": active_symbol,
        "selectionMode": mode.value,
        "proposalStatus": ProposalStatus.PROPOSED.value,
        "rankingScore": _encoded(top.ranking_score) if top else None,
        "rank": top.rank if top else None,
        "proposedAt": _encoded(now),
        "positionState": position.value,
        "pendingOrderState": pending.value,
        "switchEligible": switch_eligible,
        "switchBlockReasons": _encoded(ordered),
        "reasonCodes": _encoded(ordered),
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    proposal_id = "ams-2a-" + sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return SelectionProposal(
        proposal_id, ranking_result.scanner_cycle_id, ranking_result.ranking_cycle_id,
        audit_event.event_id, proposed_symbol, proposed_exchange_symbol, active_symbol,
        mode, ProposalStatus.PROPOSED, top.ranking_score if top else None,
        top.rank if top else None, now, position, pending, switch_eligible,
        ordered, ordered,
    )
