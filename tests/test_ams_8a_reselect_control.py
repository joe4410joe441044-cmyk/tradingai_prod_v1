from datetime import datetime, timedelta, timezone

import pytest

from backend.auto_market_selection import (
    AutoMarketSelectionRuntime, CandidateRankingEngine, InitialSymbolCommit,
    SafeSymbolSwitch,
)
from backend.auto_market_selection.market_scanner import MarketScanner
from tests.test_ams_1a_market_scanner import metadata, scanner_input, ticker
from tests.test_ams_2b_safe_switch import Runtime as SwitchRuntime


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


class Manager:
    def __init__(self, active="BTCUSDT", config=None, running=False):
        self.activeSymbol = active
        self.selection_mode = "AUTO"
        self.config = config or {"mode": "paper", "dry_run": True}
        self._running = running
        self.active_runtime_id = "runtime-id" if running else None
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


def three_market_source():
    contracts = [
        metadata("BTCUSDT"),
        metadata("ETHUSDT", "ETHUSDTM", base_currency="ETH"),
        metadata("SOLUSDT", "SOLUSDTM", base_currency="SOL"),
    ]
    tickers = [ticker(), ticker("ETHUSDTM"), ticker("SOLUSDTM")]
    return scanner_input(contracts=contracts, tickers=tickers)


def runtime(*, manager=None, source=None, position="FLAT", pending=False,
            emergency=True, calls=None, cooldown=300):
    manager = manager or Manager()
    source = source or three_market_source()
    calls = calls if calls is not None else []
    switch_runtime = LinkingSwitchRuntime(manager)

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
        safe_switch_factory=lambda: SafeSymbolSwitch(switch_runtime),
        initial_commit_factory=lambda: InitialSymbolCommit(switch_runtime),
        clock=lambda: NOW,
        skip_cooldown_seconds=cooldown,
    ), manager, switch_runtime, calls


def test_ranking_excludes_skipped_symbols():
    source = three_market_source()
    scanner = MarketScanner().scan(source)
    full = CandidateRankingEngine().rank(scanner)
    assert full.top_candidate.symbol == "BTCUSDT"
    skipped = CandidateRankingEngine().rank(scanner, excluded_symbols={"BTCUSDT"})
    assert skipped.top_candidate.symbol == "ETHUSDT"


def test_observe_cycle_is_read_only_and_publishes_fresh_preview():
    service, manager, switch_runtime, calls = runtime()
    result = service.observe_cycle(started_at=NOW)
    assert result["accepted"] is True
    assert result["topCandidateSymbol"] == "BTCUSDT"
    assert manager.activeSymbol == "BTCUSDT"
    assert switch_runtime.events == []
    observation = manager.auto_market_selection_observation
    assert observation["scannerResult"]["scannerCycleId"]
    assert observation["rankingResult"]["topCandidate"]["symbol"] == "BTCUSDT"
    assert observation["selectionObservation"]["topCandidateSymbol"] == "BTCUSDT"
    assert observation["selectionObservation"]["readOnly"] is True
    assert "switchResult" not in observation
    assert "selectionProposal" not in observation


def test_observe_cycle_creates_no_order():
    service, manager, switch_runtime, _ = runtime()
    result = service.observe_cycle(started_at=NOW)
    assert result["accepted"] is True
    assert switch_runtime.events == []
    assert "paperOrderCreated" not in manager.auto_market_selection_observation
    assert "switchResult" not in manager.auto_market_selection_observation


def test_running_reselect_skips_active_and_commits_next_candidate():
    service, manager, switch_runtime, _ = runtime(
        manager=Manager(active="BTCUSDT", running=True),
    )
    response = service.request_skip_and_reselect(started_at=NOW)
    assert response["accepted"] is True
    assert response["skippedSymbol"] == "BTCUSDT"
    assert response["result"]["finalActiveSymbol"] == "ETHUSDT"
    assert manager.activeSymbol == "ETHUSDT"


def test_stopped_reselect_observes_without_commit_or_order():
    service, manager, switch_runtime, _ = runtime(
        manager=Manager(active="BTCUSDT", running=False),
    )
    response = service.request_skip_and_reselect(started_at=NOW)
    assert response["accepted"] is True
    assert response["skippedSymbol"] == "BTCUSDT"
    assert manager.activeSymbol == "BTCUSDT"
    assert switch_runtime.events == []
    observation = manager.auto_market_selection_observation
    assert observation["selectionObservation"]["topCandidateSymbol"] == "ETHUSDT"


def test_temporary_skip_expires_after_cooldown():
    service, manager, _, _ = runtime(manager=Manager(active="BTCUSDT"), cooldown=300)
    service.record_temporary_skip("BTCUSDT", now=NOW)
    assert "BTCUSDT" in service.active_temporary_skips(now=NOW)
    assert "BTCUSDT" in service.active_temporary_skips(now=NOW + timedelta(seconds=299))
    assert "BTCUSDT" not in service.active_temporary_skips(now=NOW + timedelta(seconds=301))


def test_immediate_reselection_does_not_readopt_skipped_symbol():
    service, manager, switch_runtime, _ = runtime(
        manager=Manager(active="BTCUSDT", running=True),
    )
    first = service.request_skip_and_reselect(started_at=NOW)
    assert first["result"]["finalActiveSymbol"] == "ETHUSDT"
    switch_runtime.old_feed_active = True
    second = service.request_skip_and_reselect(started_at=NOW)
    assert second["accepted"] is True
    assert second["skippedSymbol"] == "ETHUSDT"
    assert second["result"]["finalActiveSymbol"] == "SOLUSDT"
    assert second["result"]["finalActiveSymbol"] != "BTCUSDT"


def test_reselect_rejects_without_active_symbol():
    service, manager, switch_runtime, _ = runtime(manager=Manager(active=None))
    response = service.request_skip_and_reselect(started_at=NOW)
    assert response["accepted"] is False
    assert response["reasonCodes"] == ["ACTIVE_SYMBOL_UNAVAILABLE"]
    assert switch_runtime.events == []


# Canonical architecture (unlike the historical A1 branch) admits LIVE only as a
# disarmed monitoring runtime.  The unsafe-config rejection reason is therefore
# the canonical LIVE guard reason, not the old paper-only reason.
@pytest.mark.parametrize("config,reason", [
    ({"mode": "live", "dry_run": True}, "AUTO_SELECTION_LIVE_DRY_RUN_FORBIDDEN"),
    ({"mode": "paper", "dry_run": False}, "AUTO_SELECTION_DRY_RUN_REQUIRED"),
])
def test_reselect_blocked_on_unsafe_config(config, reason):
    service, manager, _, _ = runtime(manager=Manager(config=config))
    response = service.request_skip_and_reselect(started_at=NOW)
    assert response["accepted"] is False
    assert response["reasonCodes"] == [reason]


def test_observe_blocked_on_unsafe_config():
    service, manager, _, _ = runtime(
        manager=Manager(config={"mode": "live", "dry_run": True}),
    )
    result = service.observe_cycle(started_at=NOW)
    assert result["accepted"] is False
    assert result["reasonCodes"] == ["AUTO_SELECTION_LIVE_DRY_RUN_FORBIDDEN"]


def test_observe_concurrent_with_running_cycle_is_rejected():
    service, manager, _, _ = runtime()
    service._cycle_lock.acquire()
    try:
        result = service.observe_cycle(started_at=NOW)
    finally:
        service._cycle_lock.release()
    assert result["accepted"] is False
    assert result["reasonCodes"] == ["AUTO_SELECTION_ALREADY_IN_PROGRESS"]


def test_bot_manager_boundary_defaults_safe_without_lifecycle():
    from backend.bot_manager.bot_manager import BotManager

    manager = BotManager.__new__(BotManager)
    manager._active_symbol = "BTCUSDT"
    manager.auto_market_selection_lifecycle = None
    observe = manager.observe_auto_market_selection()
    assert observe["accepted"] is False
    assert observe["reasonCodes"] == ["AUTO_RUNTIME_UNAVAILABLE"]
    reselect = manager.request_auto_market_selection_reselect()
    assert reselect["accepted"] is False
    assert reselect["reasonCodes"] == ["AUTO_RUNTIME_UNAVAILABLE"]
