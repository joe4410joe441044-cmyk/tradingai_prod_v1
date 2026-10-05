"""C-P6-2 read-only dual account projection contracts.

Offline only: no exchange calls, no production persistence, no orders and no
runtime mode mutation. These tests exercise
``BotManager._build_account_runtime`` directly.
"""
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import Mock, patch

from backend.bot_manager.bot_manager import BotManager
from backend.runtime.trade_history_read import TradeHistoryService

NOW = 1790695880.0


class PaperEngine:
    def __init__(
        self,
        symbol="GRIFFAINUSDT",
        latest_price=0.016195,
        balance=1000.0,
        pnl=0.0,
        unrealized_pnl=0.0,
        actual_position=None,
    ):
        self.mode = "paper"
        self.symbol = symbol
        self.latest_price = latest_price
        self.balance = balance
        self.pnl = pnl
        self.unrealized_pnl = unrealized_pnl
        self.actual_position = actual_position
        self.portfolio = None


class LiveEngine:
    def __init__(
        self,
        symbol="XRPUSDT",
        latest_price=2.0,
        balance=9999.0,
        pnl=222.0,
        unrealized_pnl=111.0,
        actual_position=None,
    ):
        self.mode = "live"
        self.symbol = symbol
        self.latest_price = latest_price
        self.balance = balance
        self.pnl = pnl
        self.unrealized_pnl = unrealized_pnl
        self.actual_position = actual_position
        self.portfolio = None


def paper_position():
    return {
        "symbol": "GRIFFAINUSDT",
        "side": "BUY",
        "qty": 6174000,
        "coin_qty": 6174,
        "multiplier": 0.001,
        "entry_price": 0.016195,
        "entry_time": NOW - 0.643,
        "entry_authority": "MANUAL",
        "runtimeSymbolContext": {"symbol": "GRIFFAINUSDT"},
    }


def paper_snapshot():
    return {
        "available": True,
        "position": paper_position(),
        "positions": [paper_position()],
        "last_update": NOW,
        "unrealizedPnl": 0,
        "balance": 1000,
        "equity": 1000,
        "realizedPnl": 0,
    }


def real_flat_account():  # noqa: E302
    return {"authenticated": True, "lastSync": NOW, "positions": []}


@contextmanager
def patched(service):
    with patch(
        "backend.bot_manager.bot_manager.time.time",
        return_value=NOW,
    ), patch(
        "backend.runtime.trade_history_read.TradeHistoryService",
        return_value=service,
    ):
        yield


def empty_service(tmp_path):
    return TradeHistoryService(base_directory=tmp_path)


def history_record(mode, *, trade_id, symbol, side="BUY", realized=0.0,
                   authoritative=True, exit_ts=NOW):
    return dict(
        schemaVersion=1,
        recordId=trade_id,
        tradeId=trade_id,
        origin="PRODUCTION",
        scope=mode.upper(),
        mode=mode.lower(),
        symbol=symbol,
        side=side,
        quantity=1,
        entryPrice=1.0,
        exitPrice=1.0,
        entryTimestamp=exit_ts - 1,
        exitTimestamp=exit_ts,
        holdingMs=1000,
        realizedPnl=realized,
        realizedPnlAuthoritative=authoritative,
        controlSource="MANUAL",
        exitReason="MOMENTUM_DECAY",
    )


def build(bot, service, selected_mode="PAPER", live=None, paper_source=None):
    with patched(service):
        return bot._build_account_runtime(
            paper_source if paper_source is not None else paper_snapshot(),
            {"realAccount": live if live is not None else real_flat_account()},
            selected_mode,
            selected_mode != "LIVE",
            "LIVE" if selected_mode == "LIVE" else "SIMULATION",
            selected_mode == "LIVE",
        )


# A. both modes present ------------------------------------------------------

def test_both_modes_present(tmp_path):
    bot = BotManager()
    bot.engine = PaperEngine()
    bot.symbol = "GRIFFAINUSDT"
    runtime = build(bot, empty_service(tmp_path), "PAPER")

    assert set(runtime["positionsByMode"]) == {"PAPER", "LIVE"}
    assert runtime["positionsByMode"]["PAPER"]["mode"] == "PAPER"
    assert runtime["positionsByMode"]["LIVE"]["mode"] == "LIVE"
    assert set(runtime["lastPositionEventsByMode"]) == {"PAPER", "LIVE"}
    assert runtime["lastPositionEventsByMode"]["PAPER"]["mode"] == "PAPER"
    assert runtime["lastPositionEventsByMode"]["LIVE"]["mode"] == "LIVE"


# B. selected mode PAPER -----------------------------------------------------

def test_selected_mode_paper_legacy_uses_paper_projection(tmp_path):
    bot = BotManager()
    bot.engine = PaperEngine()
    bot.symbol = "GRIFFAINUSDT"
    runtime = build(bot, empty_service(tmp_path), "PAPER")

    assert runtime["currentPosition"] == runtime["positionsByMode"]["PAPER"]
    assert runtime["lastPositionEvent"] == runtime["lastPositionEventsByMode"]["PAPER"]
    assert runtime["currentPosition"]["mode"] == "PAPER"


# C. selected mode LIVE ------------------------------------------------------

def test_selected_mode_live_legacy_uses_live_projection(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine()
    bot.symbol = "XRPUSDT"
    runtime = build(bot, empty_service(tmp_path), "LIVE")

    assert runtime["currentPosition"] == runtime["positionsByMode"]["LIVE"]
    assert runtime["lastPositionEvent"] == runtime["lastPositionEventsByMode"]["LIVE"]
    assert runtime["currentPosition"]["mode"] == "LIVE"


# D. mode independence -------------------------------------------------------

def test_mode_independence_builds_both_projections(tmp_path):
    service = empty_service(tmp_path)
    bot = BotManager()
    bot.engine = PaperEngine()
    bot.symbol = "GRIFFAINUSDT"

    paper_selected = build(bot, service, "PAPER")
    assert paper_selected["positionsByMode"]["PAPER"]["status"] == "OPEN"
    assert paper_selected["positionsByMode"]["LIVE"]["status"] == "FLAT"
    assert paper_selected["currentPosition"]["mode"] == "PAPER"

    live_selected = build(bot, service, "LIVE")
    assert live_selected["positionsByMode"]["PAPER"]["status"] == "OPEN"
    assert live_selected["positionsByMode"]["LIVE"]["status"] == "FLAT"
    assert live_selected["currentPosition"]["mode"] == "LIVE"


# E. PAPER account isolation from a LIVE engine ------------------------------

def test_paper_account_not_contaminated_by_live_engine(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine(
        symbol="XRPUSDT",
        balance=9999.0,
        pnl=222.0,
        unrealized_pnl=111.0,
        actual_position={
            "symbol": "XRPUSDT",
            "side": "BUY",
            "qty": 5,
            "entry_price": 1,
        },
    )
    bot.symbol = "XRPUSDT"
    bot.paper_account_state = bot.paper_account_store.build_state(
        Decimal("1234.56"), "DASHBOARD_MANUAL", NOW,
    )

    live_snapshot = {
        "available": True,
        "balance": 9999.0,
        "equity": 10110.0,
        "realizedPnl": 222.0,
        "unrealizedPnl": 111.0,
        "position": bot.engine.actual_position,
        "positions": [bot.engine.actual_position],
        "last_update": NOW,
    }
    runtime = build(bot, empty_service(tmp_path), "LIVE", paper_source=live_snapshot)

    paper = runtime["paperAccount"]
    assert paper["balance"] == 1234.56
    assert paper["equity"] == 1234.56
    assert paper["balance"] != 9999.0
    assert paper["unrealizedPnl"] == 0.0
    assert paper["positions"] == []
    assert runtime["positionsByMode"]["PAPER"]["status"] == "FLAT"
    assert runtime["positionsByMode"]["LIVE"]["mode"] == "LIVE"


# F. unavailable PAPER state is UNKNOWN, never FLAT --------------------------

def test_unavailable_paper_state_is_unknown_not_flat(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine()
    bot.symbol = "XRPUSDT"
    bot.paper_account_state = bot.paper_account_store.unavailable_state(
        "PAPER_ACCOUNT_STATE_CORRUPT",
    )
    runtime = build(bot, empty_service(tmp_path), "LIVE")

    paper = runtime["paperAccount"]
    assert paper["available"] is False
    assert paper["balance"] is None
    assert paper["equity"] is None
    assert runtime["positionsByMode"]["PAPER"]["status"] == "UNKNOWN"
    assert runtime["positionsByMode"]["PAPER"]["status"] != "FLAT"


# G. stale PAPER state stays STALE/UNKNOWN, never FLAT -----------------------

def test_stale_paper_projection_is_stale_not_flat(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine()
    bot.symbol = "XRPUSDT"
    bot.paper_account_state = bot.paper_account_store.build_state(
        Decimal("1000.00"), "DASHBOARD_MANUAL", NOW - 600,
    )
    runtime = build(bot, empty_service(tmp_path), "LIVE")

    paper_view = runtime["positionsByMode"]["PAPER"]
    assert paper_view["freshness"] == "STALE"
    assert paper_view["status"] == "UNKNOWN"


# H. multiple LIVE positions are never arbitrarily selected ------------------

def test_multiple_live_positions_not_arbitrarily_selected(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine(symbol="SOLUSDT")
    bot.symbol = "SOLUSDT"
    observation = {
        "positions": [
            {
                "id": "one",
                "symbol": "XBTUSDTM",
                "currentQty": 1,
                "avgEntryPrice": 120000,
                "markPrice": 120009.57,
                "markValue": 120.00957,
                "unrealisedPnl": 0.00957,
                "realLeverage": 6,
                "posMargin": 20,
                "liquidationPrice": 100000,
                "openingTimestamp": (NOW - 60) * 1000,
            },
            {"id": "two", "symbol": "XRPUSDTM", "currentQty": -2, "avgEntryPrice": 2},
        ],
        "sourceUpdatedAt": NOW,
    }
    bot.real_account_snapshot = {
        "authenticated": True,
        "lastSync": NOW,
        "positionObservation": observation,
    }
    runtime = build(
        bot,
        empty_service(tmp_path),
        "LIVE",
        live={"authenticated": True, "lastSync": NOW, "positions": []},
    )

    live_view = runtime["positionsByMode"]["LIVE"]
    assert live_view["status"] == "UNKNOWN"
    assert live_view["reason"] == "MULTIPLE_POSITIONS"
    assert len(live_view["positions"]) == 2
    assert runtime["currentPosition"] == live_view


# I. PAPER/LIVE last events are mode separated -------------------------------

def test_last_events_are_mode_separated(tmp_path):
    service = empty_service(tmp_path)
    service.store.append(history_record("paper", trade_id="paper-1", symbol="PAPERUSDT"))
    service.store.append(history_record("live", trade_id="live-1", symbol="LIVEUSDT",
                                        side="SELL", realized=5.5, exit_ts=NOW + 1))
    bot = BotManager()
    bot.engine = PaperEngine()
    bot.symbol = "GRIFFAINUSDT"
    runtime = build(bot, service, "PAPER")

    paper_event = runtime["lastPositionEventsByMode"]["PAPER"]
    live_event = runtime["lastPositionEventsByMode"]["LIVE"]
    assert paper_event["tradeId"] == "paper-1"
    assert paper_event["symbol"] == "PAPERUSDT"
    assert live_event["tradeId"] == "live-1"
    assert live_event["symbol"] == "LIVEUSDT"
    assert paper_event["tradeId"] != live_event["tradeId"]
    assert runtime["lastPositionEvent"] == paper_event


# J. zero realized PnL survives as numeric zero ------------------------------

def test_zero_realized_pnl_preserved(tmp_path):
    service = empty_service(tmp_path)
    service.store.append(history_record("paper", trade_id="zero", symbol="GRIFFAINUSDT",
                                        realized=0.0))
    bot = BotManager()
    bot.engine = PaperEngine()
    bot.symbol = "GRIFFAINUSDT"
    runtime = build(bot, service, "PAPER")

    event = runtime["lastPositionEventsByMode"]["PAPER"]
    assert event["event"] == "CLOSED"
    assert event["realizedPnl"] == 0
    assert event["realizedPnl"] is not None


# K. no history vs read failure ----------------------------------------------

def test_no_history_vs_read_failure(tmp_path):
    bot = BotManager()
    bot.engine = PaperEngine()
    bot.symbol = "GRIFFAINUSDT"

    empty_runtime = build(bot, empty_service(tmp_path), "PAPER")
    assert empty_runtime["lastPositionEventsByMode"]["PAPER"]["event"] == "NONE"

    broken = Mock()
    broken.history.side_effect = OSError("unavailable")
    broken_runtime = build(bot, broken, "PAPER")
    assert broken_runtime["lastPositionEventsByMode"]["PAPER"]["event"] == "UNKNOWN"
    assert broken_runtime["lastPositionEventsByMode"]["LIVE"]["event"] == "UNKNOWN"


# L. REAL-004 loading snapshot retains the last completed observation -------

def retained_observation(rows, updated):
    return {"positions": rows, "sourceUpdatedAt": updated}


def loading_live_snapshot(observation, *, stale=False):
    return {
        "authenticated": True,
        "lastSync": NOW,
        "loading": True,
        "stale": stale,
        "positionObservation": observation,
    }


def test_real004_loading_snapshot_retains_fresh_flat_live_observation(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine(symbol="XRPUSDT")
    bot.symbol = "XRPUSDT"
    bot.real_account_snapshot = loading_live_snapshot(
        retained_observation([], NOW - 29.718657),
    )
    runtime = build(bot, empty_service(tmp_path), "LIVE",
                    live={"authenticated": True, "lastSync": NOW, "positions": []})

    live_view = runtime["positionsByMode"]["LIVE"]
    assert live_view["status"] == "FLAT"
    assert live_view["freshness"] == "FRESH"
    assert live_view["reason"] is None
    assert runtime["currentPosition"] == live_view


def test_real004_loading_snapshot_retains_open_position(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine(symbol="XBTUSDTM")
    bot.symbol = "XBTUSDTM"
    bot.real_account_snapshot = loading_live_snapshot(retained_observation([
        {"id": "one", "symbol": "XBTUSDTM", "currentQty": 1, "avgEntryPrice": 120000,
         "markPrice": 120009.57, "markValue": 120.00957, "unrealisedPnl": .00957,
         "realLeverage": 6, "posMargin": 20, "liquidationPrice": 100000,
         "openingTimestamp": (NOW - 60) * 1000},
    ], NOW))
    runtime = build(bot, empty_service(tmp_path), "LIVE",
                    live={"authenticated": True, "lastSync": NOW, "positions": []})

    live_view = runtime["positionsByMode"]["LIVE"]
    assert live_view["status"] == "OPEN"
    assert live_view["quantity"] == 1


def test_real004_failed_refresh_never_creates_false_flat(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine(symbol="XRPUSDT")
    bot.symbol = "XRPUSDT"
    bot.real_account_snapshot = loading_live_snapshot(
        {"positions": None, "sourceUpdatedAt": None}, stale=True,
    )
    runtime = build(bot, empty_service(tmp_path), "LIVE",
                    live={"authenticated": True, "lastSync": NOW, "positions": []})

    live_view = runtime["positionsByMode"]["LIVE"]
    assert live_view["status"] == "UNKNOWN"
    assert live_view["status"] != "FLAT"


def test_real004_stale_loading_snapshot_not_flat(tmp_path):
    bot = BotManager()
    bot.engine = LiveEngine(symbol="XRPUSDT")
    bot.symbol = "XRPUSDT"
    bot.real_account_snapshot = loading_live_snapshot(
        retained_observation([], NOW - 91),
    )
    runtime = build(bot, empty_service(tmp_path), "LIVE",
                    live={"authenticated": True, "lastSync": NOW, "positions": []})

    live_view = runtime["positionsByMode"]["LIVE"]
    assert live_view["status"] == "UNKNOWN"
    assert live_view["reason"] == "STALE_SOURCE"
