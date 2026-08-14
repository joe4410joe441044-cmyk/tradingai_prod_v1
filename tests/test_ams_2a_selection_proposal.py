from dataclasses import replace
from datetime import timedelta
import inspect

import pytest

from backend.auto_market_selection import (
    CandidateRankingEngine, MarketScanner, PendingOrderState, PositionState,
    ProposalStatus, SelectionProposalReason, build_selection_audit_event,
    build_selection_proposal, snapshot_active_symbol_authority,
)
from tests.test_ams_1a_market_scanner import scanner_input


def inputs(*, no_candidate=False):
    source = scanner_input(contracts=[], tickers=[], eligibility_map={}) if no_candidate else scanner_input()
    scanner = MarketScanner().scan(source)
    ranking = CandidateRankingEngine().rank(scanner)
    audit = build_selection_audit_event(source.universe, source.capital, scanner, ranking)
    return source, ranking, audit


def proposal(*, active="ETHUSDT", position=PositionState.FLAT,
             pending=PendingOrderState.NONE, mm="default", emergency=True,
             no_candidate=False, proposed_at=None):
    source, ranking, audit = inputs(no_candidate=no_candidate)
    authority = {"activeSymbol": active, "selectionMode": "MANUAL"}
    mm_authority = source.capital if mm == "default" else mm
    result = build_selection_proposal(
        ranking, audit, active_symbol_authority=authority,
        position_state=position, pending_order_state=pending,
        mm_authority=mm_authority, emergency_safe=emergency,
        proposed_at=proposed_at,
    )
    return source, ranking, audit, result


def reasons(result):
    return set(result.reason_codes)


def test_top_candidate_becomes_proposal_and_correlation_is_preserved():
    _, ranking, audit, result = proposal()
    assert result.proposal_status is ProposalStatus.PROPOSED
    assert result.proposed_symbol == ranking.top_candidate.symbol
    assert result.proposed_exchange_symbol == "XBTUSDTM"
    assert result.ranking_score == ranking.top_candidate.ranking_score
    assert result.rank == 1
    assert result.scanner_cycle_id == ranking.scanner_cycle_id
    assert result.ranking_cycle_id == ranking.ranking_cycle_id
    assert result.audit_event_id == audit.event_id
    assert result.selection_mode.value == "MANUAL"
    assert result.switch_eligible is True


def test_no_top_candidate_fails_closed():
    *_, result = proposal(no_candidate=True)
    assert result.proposed_symbol is None
    assert SelectionProposalReason.NO_TOP_CANDIDATE in reasons(result)
    assert result.switch_eligible is False


def test_same_symbol_requires_no_switch_and_remains_a_proposal():
    source, ranking, audit = inputs()
    result = build_selection_proposal(
        ranking, audit,
        active_symbol_authority={"activeSymbol": ranking.top_candidate.symbol,
                                 "selectionMode": "MANUAL"},
        position_state="FLAT", pending_order_state=False,
        mm_authority=source.capital, emergency_safe=True,
    )
    assert result.reason_codes == (SelectionProposalReason.NO_SWITCH_REQUIRED,)
    assert result.switch_eligible is False
    assert result.proposal_status is ProposalStatus.PROPOSED


@pytest.mark.parametrize("position,reason", [
    ("OPEN", SelectionProposalReason.POSITION_NOT_FLAT),
    (None, SelectionProposalReason.POSITION_STATE_UNKNOWN),
])
def test_position_authority_blocks_non_flat_and_unknown(position, reason):
    *_, result = proposal(position=position)
    assert reason in reasons(result) and result.switch_eligible is False


@pytest.mark.parametrize("pending,reason", [
    (True, SelectionProposalReason.PENDING_ORDER_EXISTS),
    (None, SelectionProposalReason.PENDING_ORDER_UNKNOWN),
    ({"known": False, "pending": None}, SelectionProposalReason.PENDING_ORDER_UNKNOWN),
])
def test_existing_pending_authority_shape_fails_closed(pending, reason):
    *_, result = proposal(pending=pending)
    assert reason in reasons(result) and result.switch_eligible is False


def test_mm_unavailable_and_stale_fail_closed():
    *_, unavailable = proposal(mm=None)
    assert SelectionProposalReason.MM_UNAVAILABLE in reasons(unavailable)
    source, ranking, audit = inputs()
    stale = build_selection_proposal(
        ranking, audit, active_symbol_authority={"activeSymbol": "ETHUSDT",
                                                  "selectionMode": "MANUAL"},
        position_state="FLAT", pending_order_state=False,
        mm_authority=replace(source.capital, authority_fresh=False), emergency_safe=True,
    )
    assert SelectionProposalReason.MM_STALE in reasons(stale)


def test_emergency_active_symbol_and_freshness_fail_closed():
    *_, emergency = proposal(emergency=False)
    assert SelectionProposalReason.EMERGENCY_UNSAFE in reasons(emergency)
    *_, unknown_symbol = proposal(active=None)
    assert SelectionProposalReason.ACTIVE_SYMBOL_UNAVAILABLE in reasons(unknown_symbol)
    _, ranking, _ = inputs()
    *_, stale = proposal(proposed_at=ranking.evaluated_at + timedelta(seconds=301))
    assert SelectionProposalReason.PROPOSAL_STALE in reasons(stale)


def test_same_input_has_same_identity_and_serialization():
    source, ranking, audit = inputs()
    kwargs = dict(active_symbol_authority={"activeSymbol": "ETHUSDT", "selectionMode": "MANUAL"},
                  position_state="FLAT", pending_order_state=False,
                  mm_authority=source.capital, emergency_safe=True)
    first = build_selection_proposal(ranking, audit, **kwargs)
    second = build_selection_proposal(ranking, audit, **kwargs)
    assert first == second
    assert first.selection_proposal_id == second.selection_proposal_id
    assert first.to_dict() == second.to_dict()
    assert first.to_json() == second.to_json()


def test_bot_manager_snapshot_is_read_only_and_active_symbol_unchanged():
    class Manager:
        def __init__(self):
            self.active = "BTCUSDT"
        def get_active_symbol_contract(self):
            return {"activeSymbol": self.active, "selectionMode": "MANUAL"}
    manager = Manager()
    snapshot = snapshot_active_symbol_authority(manager)
    source, ranking, audit = inputs()
    build_selection_proposal(
        ranking, audit, active_symbol_authority=snapshot,
        position_state="FLAT", pending_order_state=False,
        mm_authority=source.capital, emergency_safe=True,
    )
    assert manager.active == "BTCUSDT"


def test_correlation_mismatch_rejected_and_no_forbidden_runtime_actions():
    source, ranking, audit = inputs()
    with pytest.raises(ValueError, match="correlation"):
        build_selection_proposal(
            ranking, replace(audit, ranking_cycle_id="wrong"),
            active_symbol_authority={}, position_state=None,
            pending_order_state=None, mm_authority=source.capital,
            emergency_safe=None,
        )
    from backend.auto_market_selection import selection_proposal
    source_text = inspect.getsource(selection_proposal)
    forbidden = ("_set_active_symbol_for_start", "create_market_ws", "subscribe",
                 "create_order", "submit_order", "Strategy", "backend.ai")
    assert all(term not in source_text for term in forbidden)
