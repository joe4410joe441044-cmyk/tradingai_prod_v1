from datetime import datetime, timedelta, timezone

import pytest

from backend.auto_market_selection import (
    BotManagerSwitchRuntime, CandidateRankingEngine, MarketScanner,
    PreparedFeed, SafeSymbolSwitch, SnapshotNotReady, SwitchReason, SwitchState,
    build_selection_audit_event, build_selection_proposal,
)
from tests.test_ams_1a_market_scanner import scanner_input


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


def eligible_proposal():
    source = scanner_input()
    scanner = MarketScanner().scan(source)
    ranking = CandidateRankingEngine().rank(scanner)
    audit = build_selection_audit_event(source.universe, source.capital, scanner, ranking)
    return build_selection_proposal(
        ranking, audit,
        active_symbol_authority={"activeSymbol": "ETHUSDT", "selectionMode": "MANUAL"},
        position_state="FLAT", pending_order_state=False,
        mm_authority=source.capital, emergency_safe=True, proposed_at=NOW,
    )


class Runtime:
    def __init__(self):
        self.active = "ETHUSDT"
        self.position = "FLAT"
        self.pending = False
        self.mm_available = True
        self.mm_fresh = True
        self.emergency = True
        self.events = []
        self.fail = None
        self.old_feed_active = True
        self.clock = NOW
        self.engine_symbol = "ETHUSDT"

    def now(self):
        return self.clock

    def revalidate_switch(self, proposal):
        self.events.append("revalidate")
        return {"activeSymbol": self.active, "positionState": self.position,
                "pendingOrder": self.pending, "mmAvailable": self.mm_available,
                "mmFresh": self.mm_fresh, "emergencySafe": self.emergency}

    def pause_new_entries(self, transaction_id):
        self.events.append("pause")
        return self.fail != "pause"

    def prepare_new_feed(self, symbol, exchange_symbol, transaction_id):
        self.events.append("prepare")
        assert self.old_feed_active
        if self.fail == "subscribe":
            return None
        return {"symbol": symbol, "exchange": exchange_symbol}

    def read_new_snapshot(self, handle):
        self.events.append("snapshot")
        snapshot = {"symbol": handle["symbol"], "exchangeSymbol": handle["exchange"],
                    "timestamp": NOW, "sequence": 12, "sequenceValid": True,
                    "bids": {99.0: 2.0}, "asks": {101.0: 3.0}}
        if self.fail == "invalid": snapshot["bids"] = {}
        if self.fail == "crossed": snapshot["bids"] = {102.0: 2.0}
        if self.fail == "not_ready": return SnapshotNotReady()
        if self.fail == "stale": snapshot["timestamp"] = NOW - timedelta(seconds=6)
        if self.fail == "symbol": snapshot["symbol"] = "SOLUSDT"
        if self.fail == "sequence": snapshot["sequenceValid"] = False
        return snapshot

    def commit_active_symbol(self, expected, proposed, handle, transaction_id):
        self.events.append("commit")
        if self.fail == "commit" or self.active != expected:
            return False
        self.active = proposed
        return True

    def sync_downstream(self, symbol, handle):
        self.events.append("sync")
        if self.fail == "sync": return False
        self.engine_symbol = symbol
        return True

    def cleanup_old_feed(self, handle):
        self.events.append("old_cleanup")
        if self.fail == "cleanup": return False
        self.old_feed_active = False
        return True

    def resume_new_entries(self, transaction_id):
        self.events.append("resume")
        return self.fail != "resume"

    def cleanup_new_feed(self, handle):
        self.events.append("new_cleanup")
        return True


def execute(runtime=None, proposal=None, now=NOW):
    runtime = runtime or Runtime()
    result = SafeSymbolSwitch(runtime).execute(proposal or eligible_proposal(), started_at=now)
    return runtime, result


def test_valid_switch_enforces_order_and_correlations():
    runtime, result = execute()
    assert result.success and result.committed_symbol == "BTCUSDT"
    assert runtime.active == runtime.engine_symbol == "BTCUSDT"
    assert runtime.events == ["revalidate", "pause", "prepare", "snapshot",
                              "revalidate", "commit", "sync", "old_cleanup", "resume"]
    assert result.new_feed_validated and result.active_symbol_committed
    assert result.old_feed_detached and result.pipeline_resumed
    assert not result.entry_paused
    assert result.selection_proposal_id == eligible_proposal().selection_proposal_id
    assert result.scanner_cycle_id and result.ranking_cycle_id and result.audit_event_id


@pytest.mark.parametrize("attribute,value,reason", [
    ("active", "SOLUSDT", SwitchReason.ACTIVE_SYMBOL_CHANGED_SINCE_PROPOSAL),
    ("position", "OPEN", SwitchReason.POSITION_NOT_FLAT),
    ("position", None, SwitchReason.POSITION_STATE_UNKNOWN),
    ("pending", True, SwitchReason.PENDING_ORDER_EXISTS),
    ("pending", None, SwitchReason.PENDING_ORDER_UNKNOWN),
    ("mm_available", False, SwitchReason.MM_UNAVAILABLE),
    ("mm_fresh", False, SwitchReason.MM_STALE),
    ("emergency", False, SwitchReason.EMERGENCY_UNSAFE),
])
def test_revalidation_aborts_before_pause_or_feed(attribute, value, reason):
    runtime = Runtime(); setattr(runtime, attribute, value)
    active_before = runtime.active
    runtime, result = execute(runtime)
    assert not result.success and result.reason_codes == (reason,)
    assert runtime.events == ["revalidate"] and runtime.active == active_before


def test_stale_and_ineligible_proposals_do_not_start_transaction():
    runtime, stale = execute(now=NOW + timedelta(seconds=301))
    assert stale.reason_codes == (SwitchReason.PROPOSAL_STALE,) and runtime.events == []
    proposal = eligible_proposal()
    object.__setattr__(proposal, "switch_eligible", False)
    runtime, invalid = execute(proposal=proposal)
    assert invalid.reason_codes == (SwitchReason.PROPOSAL_NOT_ELIGIBLE,)
    assert runtime.events == []


@pytest.mark.parametrize("failure,reason", [
    ("invalid", SwitchReason.NEW_SNAPSHOT_INVALID),
    ("crossed", SwitchReason.NEW_SNAPSHOT_INVALID),
    ("stale", SwitchReason.NEW_SNAPSHOT_STALE),
    ("symbol", SwitchReason.SYMBOL_MISMATCH),
    ("sequence", SwitchReason.SEQUENCE_INVALID),
])
def test_snapshot_barrier_failure_keeps_old_authority_and_cleans_new(failure, reason):
    runtime = Runtime(); runtime.fail = failure
    runtime, result = execute(runtime)
    assert result.reason_codes == (reason,)
    assert runtime.active == "ETHUSDT" and runtime.old_feed_active
    assert "commit" not in runtime.events
    assert runtime.events[-2:] == ["new_cleanup", "resume"]


def test_first_snapshot_timeout_is_retryable_and_preserves_old_authority():
    runtime = Runtime(); runtime.fail = "not_ready"
    runtime, result = execute(runtime)
    assert not result.success
    assert result.state is SwitchState.NOT_READY
    assert result.reason_codes == (SwitchReason.NEW_SNAPSHOT_NOT_READY,)
    assert runtime.active == "ETHUSDT" and runtime.old_feed_active
    assert "commit" not in runtime.events
    assert runtime.events[-2:] == ["new_cleanup", "resume"]


def test_bot_manager_adapter_returns_typed_timeout_without_fabricating_snapshot(
        monkeypatch):
    class Feed:
        def start(self): pass
    class Manager:
        exchange_name = "kucoin"
        ws = None
        active_runtime_id = "old"
    monkeypatch.setattr(
        "backend.market.exchange_factory.ExchangeFactory.create_market_ws",
        lambda **kwargs: Feed(),
    )
    adapter = BotManagerSwitchRuntime(
        Manager(), position_provider=lambda: "FLAT", mm_provider=lambda: None,
        emergency_provider=lambda: True, snapshot_timeout_seconds=0,
    )
    handle = adapter.prepare_new_feed("BTCUSDT", "XBTUSDTM", "tx")
    snapshot = adapter.read_new_snapshot(handle)
    assert handle.snapshot is None and handle.snapshot_timed_out is True
    assert isinstance(snapshot, SnapshotNotReady)


def test_cleanup_failure_after_commit_stays_paused_and_never_rolls_back():
    runtime = Runtime(); runtime.fail = "cleanup"
    runtime, result = execute(runtime)
    assert result.reason_codes == (SwitchReason.OLD_FEED_CLEANUP_FAILED,)
    assert runtime.active == "BTCUSDT"
    assert result.active_symbol_committed and result.entry_paused
    assert not result.pipeline_resumed and "resume" not in runtime.events


def test_downstream_and_resume_failures_are_fail_closed_after_commit():
    for failure, reason in (("sync", SwitchReason.DOWNSTREAM_SYNC_FAILED),
                            ("resume", SwitchReason.PIPELINE_RESUME_FAILED)):
        runtime = Runtime(); runtime.fail = failure
        runtime, result = execute(runtime)
        assert result.reason_codes == (reason,)
        assert runtime.active == "BTCUSDT" and result.entry_paused


def test_second_concurrent_attempt_is_blocked():
    runtime = Runtime(); switch = SafeSymbolSwitch(runtime); proposal = eligible_proposal()
    switch._lock.acquire()
    try:
        result = switch.execute(proposal, started_at=NOW)
    finally:
        switch._lock.release()
    assert result.reason_codes == (SwitchReason.SWITCH_ALREADY_IN_PROGRESS,)
    assert runtime.events == []


def test_same_symbol_is_noop_and_deterministic_serialization():
    proposal = eligible_proposal()
    object.__setattr__(proposal, "proposed_symbol", proposal.current_active_symbol)
    first_runtime, first = execute(proposal=proposal)
    second_runtime, second = execute(proposal=proposal)
    assert first.reason_codes == (SwitchReason.PROPOSAL_NOT_ELIGIBLE,)
    assert first_runtime.events == second_runtime.events == []
    assert first.switch_transaction_id == second.switch_transaction_id
    assert first.to_json() == second.to_json()


def test_bot_manager_adapter_is_paper_only_and_uses_internal_cas():
    class Manager:
        activeSymbol = "ETHUSDT"
        config = {"mode": "paper", "dry_run": True}
        def _commit_active_symbol_for_safe_switch(self, *args):
            self.args = args
            return True
    manager = Manager()
    adapter = BotManagerSwitchRuntime(
        manager, position_provider=lambda: "FLAT", mm_provider=lambda: None,
        emergency_provider=lambda: True,
    )
    handle = PreparedFeed(object(), "tx", object(), "old", "BTCUSDT", "XBTUSDTM")
    assert adapter.commit_active_symbol("ETHUSDT", "BTCUSDT", handle, "tx")
    assert manager.args[:2] == ("ETHUSDT", "BTCUSDT")
    manager.config = {"mode": "live", "dry_run": False}
    assert not adapter.commit_active_symbol("ETHUSDT", "BTCUSDT", handle, "tx")


def test_public_hot_switch_and_live_safety_controls_are_unchanged():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    api = (root / "backend/api/bot_api.py").read_text()
    transaction = (root / "backend/auto_market_selection/safe_switch.py").read_text()
    assert "RUNNING_SYMBOL_SWITCH_UNSUPPORTED; set symbol via /api/bot/start" in api
    assert all(term not in transaction for term in
               ("realOrderAllowed =", "dryRun =", "create_order", "submit_order"))
