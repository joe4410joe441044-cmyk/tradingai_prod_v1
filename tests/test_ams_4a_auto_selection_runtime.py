from dataclasses import replace
from datetime import datetime, timezone

import pytest

from backend.auto_market_selection import (
    AutoMarketSelectionRuntime, AutoSelectionCycleStatus, InitialSymbolCommit,
    SafeSymbolSwitch,
)
from backend.auto_market_selection.candidate_ranking import (
    CandidateRankingEngine, RankingReason, RankingStatus,
)
from backend.auto_market_selection.market_scanner import ScannerStatus
from tests.test_ams_1a_market_scanner import scanner_input
from tests.test_ams_2b_safe_switch import Runtime as SwitchRuntime


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


class Manager:
    def __init__(self, active="ETHUSDT", config=None):
        self.activeSymbol = active
        self.selection_mode = "MANUAL"
        self.config = config or {"mode": "paper", "dry_run": True}
        self.active_runtime_id = "runtime-old"
        self.auto_market_selection_observation = None

    def get_active_symbol_contract(self):
        return {"activeSymbol": self.activeSymbol, "selectionMode": self.selection_mode}

    def set_auto_market_selection_observation(self, value):
        self.auto_market_selection_observation = value


class LinkingSwitchRuntime(SwitchRuntime):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.active = manager.activeSymbol

    def commit_active_symbol(self, expected, proposed, handle, transaction_id):
        committed = super().commit_active_symbol(expected, proposed, handle, transaction_id)
        if committed:
            self.manager.activeSymbol = proposed
            self.manager.active_runtime_id = transaction_id
        return committed


def runtime(*, manager=None, source=None, position="FLAT", pending=False,
            emergency=True, ranking_engine=None, switch_failure=None, calls=None):
    manager = manager or Manager()
    source = source or scanner_input()
    calls = calls if calls is not None else []
    switch_runtime = LinkingSwitchRuntime(manager)
    switch_runtime.fail = switch_failure

    def marked(name, value):
        def provider(*args):
            calls.append(name)
            return value
        return provider

    return AutoMarketSelectionRuntime(
        manager,
        universe_provider=marked("universe", source.universe),
        ticker_provider=marked("ticker", source.ticker_snapshot),
        capital_provider=marked("capital", source.capital),
        eligibility_provider=marked("eligibility", source.per_market_eligibility),
        position_provider=marked("position", position),
        pending_order_provider=marked("pending", pending),
        emergency_provider=marked("emergency", emergency),
        ranking_engine=ranking_engine,
        safe_switch_factory=lambda: SafeSymbolSwitch(switch_runtime),
        initial_commit_factory=lambda: InitialSymbolCommit(switch_runtime),
        clock=lambda: NOW,
    ), manager, switch_runtime, calls


def test_paper_dry_run_executes_exact_flow_and_confirms_synchronization():
    service, manager, switch_runtime, calls = runtime()
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.COMPLETED
    assert result.current_active_symbol == "ETHUSDT"
    assert result.top_candidate_symbol == result.proposed_symbol == "BTCUSDT"
    assert result.final_active_symbol == manager.activeSymbol == "BTCUSDT"
    assert manager.active_runtime_id == result.switch_transaction_id
    assert all((result.scanner_cycle_id, result.ranking_cycle_id,
                result.audit_event_id, result.selection_proposal_id,
                result.switch_transaction_id))
    assert calls == ["universe", "ticker", "capital", "eligibility",
                     "position", "pending", "emergency"]
    assert switch_runtime.events == ["revalidate", "pause", "prepare", "snapshot",
                                     "revalidate", "commit", "sync", "old_cleanup", "resume"]
    assert service.get_status()["cycle"] == result.to_dict()


def test_initial_selection_commits_ranked_candidate_from_null_authority():
    service, manager, switch_runtime, _ = runtime(manager=Manager(active=None))
    manager.selection_mode = "AUTO"
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.COMPLETED
    assert result.current_active_symbol is None
    assert result.proposed_symbol == result.final_active_symbol == "BTCUSDT"
    assert manager.activeSymbol == "BTCUSDT"
    switch = manager.auto_market_selection_observation["switchResult"]
    assert switch["previousSymbol"] is None
    assert switch["committedSymbol"] == "BTCUSDT"
    assert switch_runtime.events == [
        "revalidate", "pause", "prepare", "snapshot", "revalidate",
        "commit", "sync", "old_cleanup", "resume",
    ]


@pytest.mark.parametrize("position,pending,emergency,reason", [
    ("OPEN", False, True, "POSITION_NOT_FLAT"),
    ("FLAT", True, True, "PENDING_ORDER_EXISTS"),
    ("FLAT", None, True, "PENDING_ORDER_UNKNOWN"),
    ("FLAT", False, False, "EMERGENCY_UNSAFE"),
])
def test_initial_selection_remains_fail_closed(position, pending, emergency, reason):
    service, manager, switch_runtime, _ = runtime(
        manager=Manager(active=None), position=position, pending=pending,
        emergency=emergency,
    )
    manager.selection_mode = "AUTO"
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.SWITCH_BLOCKED
    assert reason in result.reason_codes
    assert manager.activeSymbol is None and switch_runtime.events == []


@pytest.mark.parametrize("config,reason", [
    ({"mode": "live", "dry_run": True}, "AUTO_SELECTION_PAPER_ONLY"),
    ({"mode": "paper", "dry_run": False}, "AUTO_SELECTION_DRY_RUN_REQUIRED"),
    ({"mode": "unknown", "dry_run": True}, "AUTO_SELECTION_PAPER_ONLY"),
])
def test_non_paper_or_non_dry_run_fails_before_collecting_inputs(config, reason):
    calls = []
    service, manager, _, _ = runtime(manager=Manager(config=config), calls=calls)
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.FAILED
    assert result.reason_codes == (reason,)
    assert manager.activeSymbol == "ETHUSDT" and calls == []


def test_universe_unavailable_fails_closed_without_switch():
    source = replace(scanner_input(), universe=None)
    service, manager, switch_runtime, _ = runtime(source=source)
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.FAILED
    assert result.reason_codes == ("UNIVERSE_UNAVAILABLE",)
    assert manager.activeSymbol == "ETHUSDT" and switch_runtime.events == []


@pytest.mark.parametrize("source_change,expected_reason", [
    (lambda source: replace(source, universe=replace(source.universe, freshness="STALE")),
     "UNIVERSE_STALE"),
    (lambda source: replace(source, ticker_snapshot=replace(source.ticker_snapshot, freshness="STALE")),
     "TICKER_STALE"),
    (lambda source: replace(source, capital=replace(source.capital, authority_fresh=False)),
     "MM_STALE"),
    (lambda source: replace(source, capital=replace(source.capital, execution_entry_allowed=False)),
     "MM_LOCKED"),
])
def test_stale_or_locked_authority_has_no_eligible_market(source_change, expected_reason):
    source = source_change(scanner_input())
    service, manager, switch_runtime, _ = runtime(source=source)
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.NO_ELIGIBLE_MARKET
    assert expected_reason in result.reason_codes
    assert manager.activeSymbol == "ETHUSDT" and switch_runtime.events == []


def test_no_rankable_market_is_normal_completion_without_switch():
    class NoRanking:
        def rank(self, scanner, evaluated_at=None):
            result = CandidateRankingEngine().rank(scanner, evaluated_at=evaluated_at)
            return replace(
                result, ranked_candidate_count=0, ranked_candidates=(),
                top_candidate=None, status=RankingStatus.NO_RANKABLE_MARKET,
                reason_codes=(RankingReason.NO_RANKABLE_MARKET,),
            )

    service, manager, switch_runtime, _ = runtime(ranking_engine=NoRanking())
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.NO_RANKABLE_MARKET
    assert manager.activeSymbol == "ETHUSDT" and switch_runtime.events == []


def test_same_top_candidate_does_not_create_switch_transaction():
    service, manager, switch_runtime, _ = runtime(manager=Manager(active="BTCUSDT"))
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.NO_SWITCH_REQUIRED
    assert result.switch_transaction_id is None
    assert manager.activeSymbol == "BTCUSDT" and switch_runtime.events == []


@pytest.mark.parametrize("position,pending,emergency,reason", [
    ("OPEN", False, True, "POSITION_NOT_FLAT"),
    (None, False, True, "POSITION_STATE_UNKNOWN"),
    ("FLAT", True, True, "PENDING_ORDER_EXISTS"),
    ("FLAT", None, True, "PENDING_ORDER_UNKNOWN"),
    ("FLAT", False, False, "EMERGENCY_UNSAFE"),
    ("FLAT", False, None, "EMERGENCY_UNSAFE"),
])
def test_switch_preconditions_are_blocked_by_existing_proposal_contract(
        position, pending, emergency, reason):
    service, manager, switch_runtime, _ = runtime(
        position=position, pending=pending, emergency=emergency,
    )
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.SWITCH_BLOCKED
    assert reason in result.reason_codes
    assert manager.activeSymbol == "ETHUSDT" and switch_runtime.events == []


def test_precommit_and_postcommit_failures_preserve_safe_switch_semantics():
    pre, pre_manager, _, _ = runtime(switch_failure="subscribe")
    pre_result = pre.run_cycle(started_at=NOW)
    assert pre_result.status is AutoSelectionCycleStatus.FAILED
    assert pre_manager.activeSymbol == "ETHUSDT"

    post, post_manager, post_runtime, _ = runtime(switch_failure="cleanup")
    post_result = post.run_cycle(started_at=NOW)
    assert post_result.status is AutoSelectionCycleStatus.FAILED
    assert post_manager.activeSymbol == "BTCUSDT"
    assert post_runtime.events[-1] == "old_cleanup"


def test_snapshot_warmup_timeout_is_retryable_and_next_cycle_can_commit():
    service, manager, switch_runtime, _ = runtime(switch_failure="not_ready")

    first = service.run_cycle(started_at=NOW)
    assert first.status is AutoSelectionCycleStatus.SWITCH_BLOCKED
    assert first.reason_codes == ("NEW_SNAPSHOT_NOT_READY",)
    assert manager.activeSymbol == "ETHUSDT"
    assert service.get_status()["status"] == "SWITCH_BLOCKED"

    switch_runtime.fail = None
    second = service.run_cycle(started_at=NOW)
    assert second.status is AutoSelectionCycleStatus.COMPLETED
    assert manager.activeSymbol == "BTCUSDT"


def test_repeated_snapshot_warmup_timeouts_do_not_corrupt_runtime():
    service, manager, switch_runtime, _ = runtime(switch_failure="not_ready")
    for _ in range(3):
        result = service.run_cycle(started_at=NOW)
        assert result.status is AutoSelectionCycleStatus.SWITCH_BLOCKED
        assert result.reason_codes == ("NEW_SNAPSHOT_NOT_READY",)
        assert manager.activeSymbol == "ETHUSDT"
        assert switch_runtime.old_feed_active is True


def test_concurrent_cycle_is_rejected_without_overwriting_last_status():
    service, manager, _, calls = runtime()
    service._cycle_lock.acquire()
    try:
        result = service.run_cycle(started_at=NOW)
    finally:
        service._cycle_lock.release()
    assert result.status is AutoSelectionCycleStatus.FAILED
    assert result.reason_codes == ("AUTO_SELECTION_ALREADY_IN_PROGRESS",)
    assert service.get_status()["status"] == "IDLE"
    assert manager.auto_market_selection_observation is None and calls == []


def test_runtime_source_contains_no_direct_symbol_or_trade_authority_mutation():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] /
              "backend/auto_market_selection/auto_selection_runtime.py").read_text()
    assert all(term not in source for term in (
        "._active_symbol =", ".activeSymbol =", "create_order", "submit_order",
        "realOrderAllowed =", "execution_authorization", "governance_bypass",
    ))
