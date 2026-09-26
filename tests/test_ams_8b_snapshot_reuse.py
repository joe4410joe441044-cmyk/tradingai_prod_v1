from datetime import datetime, timedelta, timezone

import pytest

from backend.auto_market_selection import (
    AutoMarketSelectionRuntime, CandidateRankingEngine, InitialSymbolCommit,
    SafeSymbolSwitch,
)
from backend.auto_market_selection.market_scanner import MarketScanner
from tests.test_ams_8a_reselect_control import (
    LinkingSwitchRuntime, Manager, three_market_source,
)


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class CountingScanner:
    def __init__(self):
        self.inner = MarketScanner()
        self.calls = 0

    def scan(self, source):
        self.calls += 1
        return self.inner.scan(source)


class CountingRanking:
    def __init__(self):
        self.inner = CandidateRankingEngine()
        self.calls = 0

    def rank(self, scanner, *, evaluated_at=None, excluded_symbols=()):
        self.calls += 1
        return self.inner.rank(
            scanner, evaluated_at=evaluated_at, excluded_symbols=excluded_symbols,
        )


def build_runtime(*, active="ETHUSDT", config=None, clock=None, cooldown=300,
                  snapshot_max_age=None):
    manager = Manager(active=active, running=True, config=config)
    source = three_market_source()
    switch_runtime = LinkingSwitchRuntime(manager)
    calls = []
    scanner = CountingScanner()
    ranking = CountingRanking()
    clock = clock or (lambda: NOW)

    def marked(name, value):
        def provider(*args):
            calls.append(name)
            return value
        return provider

    service = AutoMarketSelectionRuntime(
        manager,
        universe_provider=marked("universe", source.universe),
        ticker_provider=marked("ticker", source.ticker_snapshot),
        capital_provider=marked("capital", source.capital),
        eligibility_provider=marked("eligibility", source.per_market_eligibility),
        position_provider=marked("position", "FLAT"),
        pending_order_provider=marked("pending", False),
        emergency_provider=marked("emergency", True),
        scanner=scanner,
        ranking_engine=ranking,
        safe_switch_factory=lambda: SafeSymbolSwitch(switch_runtime),
        initial_commit_factory=lambda: InitialSymbolCommit(switch_runtime),
        clock=clock,
        skip_cooldown_seconds=cooldown,
        snapshot_max_age=snapshot_max_age,
    )
    return service, manager, switch_runtime, calls, scanner, ranking


def test_fresh_snapshot_reuse_skips_full_rescan():
    service, manager, switch_runtime, calls, scanner, ranking = build_runtime()
    observed = service.observe_cycle(started_at=NOW)
    assert observed["accepted"] is True
    assert observed["topCandidateSymbol"] == "BTCUSDT"
    assert manager.activeSymbol == "ETHUSDT"

    calls.clear()
    scanner.calls = 0
    ranking.calls = 0

    result = service.run_cycle(started_at=NOW)
    assert result.status.value == "COMPLETED"
    assert result.proposed_symbol == "BTCUSDT"
    assert manager.activeSymbol == "BTCUSDT"
    # No universe/ticker/capital/eligibility, no scan, no ranking.
    assert "universe" not in calls and "ticker" not in calls
    assert "capital" not in calls and "eligibility" not in calls
    assert scanner.calls == 0 and ranking.calls == 0
    # Proposal authority still runs against current guards.
    assert calls == ["position", "pending", "emergency"]
    assert "commit" in switch_runtime.events


def test_fresh_snapshot_reuse_preserves_canonical_commit_and_preview():
    service, manager, switch_runtime, _, _, _ = build_runtime()
    service.observe_cycle(started_at=NOW)
    # Observe never promotes preview into activeSymbol.
    assert manager.activeSymbol == "ETHUSDT"
    result = service.run_cycle(started_at=NOW)
    assert result.status.value == "COMPLETED"
    assert result.top_candidate_symbol == "BTCUSDT"
    assert result.final_active_symbol == "BTCUSDT"
    assert manager.activeSymbol == "BTCUSDT"
    assert manager.active_runtime_id == result.switch_transaction_id


def test_fresh_snapshot_reuse_creates_no_order():
    service, manager, switch_runtime, _, _, _ = build_runtime()
    service.observe_cycle(started_at=NOW)
    result = service.run_cycle(started_at=NOW)
    assert result.status.value == "COMPLETED"
    observation = manager.auto_market_selection_observation
    assert "paperOrderCreated" not in observation
    assert "realOrderCreated" not in observation
    assert all(event in {"revalidate", "pause", "prepare", "snapshot",
                         "commit", "sync", "old_cleanup", "resume"}
               for event in switch_runtime.events)


def test_missing_snapshot_falls_back_to_full_scan():
    service, manager, switch_runtime, calls, scanner, ranking = build_runtime()
    result = service.run_cycle(started_at=NOW)
    assert result.status.value == "COMPLETED"
    assert manager.activeSymbol == "BTCUSDT"
    assert scanner.calls == 1 and ranking.calls == 1
    assert calls == ["universe", "ticker", "capital", "eligibility",
                     "position", "pending", "emergency"]


def test_stale_snapshot_falls_back_to_full_scan():
    clock = MutableClock(NOW)
    service, manager, _, calls, scanner, ranking = build_runtime(
        clock=clock, snapshot_max_age=timedelta(seconds=60),
    )
    service.observe_cycle()
    calls.clear()
    scanner.calls = 0
    ranking.calls = 0
    clock.now = NOW + timedelta(seconds=61)
    service.run_cycle()
    assert scanner.calls == 1 and ranking.calls == 1
    assert "universe" in calls and "eligibility" in calls


def test_incomplete_snapshot_falls_back_to_full_scan():
    # An observation with no top candidate never produces a reusable snapshot.
    from dataclasses import replace
    from backend.auto_market_selection.candidate_ranking import (
        RankingReason, RankingStatus,
    )
    service, manager, _, calls, scanner, ranking = build_runtime()
    calls.clear()
    scanner.calls = 0
    ranking.calls = 0
    # Simulate no rankable market during observation.
    class NoRanking:
        def __init__(self):
            self.inner = CandidateRankingEngine()
            self.calls = 0
        def rank(self, scanner_result, *, evaluated_at=None, excluded_symbols=()):
            self.calls += 1
            result = self.inner.rank(
                scanner_result, evaluated_at=evaluated_at,
                excluded_symbols=excluded_symbols,
            )
            return replace(
                result, ranked_candidate_count=0, ranked_candidates=(),
                top_candidate=None, status=RankingStatus.NO_RANKABLE_MARKET,
                reason_codes=(RankingReason.NO_RANKABLE_MARKET,),
            )
    service.ranking_engine = NoRanking()
    observed = service.observe_cycle(started_at=NOW)
    assert observed["topCandidateSymbol"] is None
    assert service._fresh_snapshot is None
    result = service.run_cycle(started_at=NOW)
    assert result.status.value in {"NO_RANKABLE_MARKET", "NO_ELIGIBLE_MARKET", "COMPLETED"}
    assert service.ranking_engine.calls >= 1


def test_skip_cooldown_is_respected_during_reuse():
    service, manager, switch_runtime, calls, scanner, ranking = build_runtime(
        active="BTCUSDT",
    )
    service.observe_cycle(started_at=NOW)
    assert service._fresh_snapshot.top_candidate_symbol == "BTCUSDT"
    # Skip the observed top candidate; reuse must now be rejected.
    service.record_temporary_skip("BTCUSDT", now=NOW)
    calls.clear()
    scanner.calls = 0
    ranking.calls = 0
    result = service.run_cycle(started_at=NOW)
    # BTCUSDT must not be re-adopted; a full re-evaluation ran and excluded it.
    assert result.status.value in {"COMPLETED", "NO_RANKABLE_MARKET"}
    assert scanner.calls == 1 and ranking.calls == 1


def test_skip_cooldown_reuse_never_readopts_skipped_symbol():
    service, manager, switch_runtime, _, _, _ = build_runtime(active="BTCUSDT")
    service.observe_cycle(started_at=NOW)
    service.record_temporary_skip("BTCUSDT", now=NOW)
    result = service.run_cycle(started_at=NOW)
    if result.status.value == "COMPLETED":
        assert result.final_active_symbol != "BTCUSDT"


def test_guards_position_pending_emergency_preserved_on_reuse():
    from backend.auto_market_selection import AutoSelectionCycleStatus
    # Position open must block the commit even when reusing a fresh snapshot.
    service, manager, switch_runtime, calls, scanner, ranking = build_runtime()
    service.observe_cycle(started_at=NOW)
    calls.clear()
    scanner.calls = 0
    ranking.calls = 0
    service.position_provider = lambda: "OPEN"
    result = service.run_cycle(started_at=NOW)
    assert result.status is AutoSelectionCycleStatus.SWITCH_BLOCKED
    assert "POSITION_NOT_FLAT" in result.reason_codes
    assert manager.activeSymbol == "ETHUSDT"
    assert "commit" not in switch_runtime.events


def test_non_paper_context_rejects_reuse_and_cycle():
    service, manager, _, calls, scanner, ranking = build_runtime(
        config={"mode": "live", "dry_run": True},
    )
    service.observe_cycle(started_at=NOW)
    calls.clear()
    result = service.run_cycle(started_at=NOW)
    assert result.status.value == "FAILED"
    # Canonical LIVE is a disarmed monitoring runtime; dry-run LIVE is rejected
    # with the canonical guard reason rather than the historical paper-only one.
    assert result.reason_codes == ("AUTO_SELECTION_LIVE_DRY_RUN_FORBIDDEN",)
    assert scanner.calls == 0 and ranking.calls == 0


def test_concurrent_cycle_does_not_duplicate_commit():
    service, manager, switch_runtime, _, _, _ = build_runtime()
    service.observe_cycle(started_at=NOW)
    service._cycle_lock.acquire()
    try:
        result = service.run_cycle(started_at=NOW)
    finally:
        service._cycle_lock.release()
    assert result.status.value == "FAILED"
    assert result.reason_codes == ("AUTO_SELECTION_ALREADY_IN_PROGRESS",)
    assert manager.activeSymbol == "ETHUSDT"
    assert switch_runtime.events == []
