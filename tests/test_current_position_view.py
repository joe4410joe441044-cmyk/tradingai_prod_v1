"""Offline display contracts: no exchange calls or production persistence."""
from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from backend.runtime.current_position_view import (
    current_position, kucoin_position_observation, last_position_event,
)
from backend.runtime.trade_history_read import TradeHistoryService

NOW = 1790695880.0


def paper(side="BUY", **position):
    row = dict(side=side, qty=6174000, coin_qty=6174, multiplier=.001,
               entry_price=.016195, entry_time=NOW-.643,
               entry_authority="MANUAL", runtimeSymbolContext={"symbol": "GRIFFAINUSDT"})
    row.update(position)
    return dict(available=True, positions=[row], positionState="OPEN", lastUpdate=NOW,
                unrealizedPnl=0)


def project(account, mode="PAPER", **kw):
    return current_position(account, mode, now=NOW, **kw)


@pytest.mark.parametrize("side,expected", [("BUY", "LONG"), ("SELL", "SHORT"), ("LONG", "LONG"), ("SHORT", "SHORT")])
def test_paper_direction_quantity_and_no_input_mutation(side, expected):
    account = paper(side)
    before = deepcopy(account)
    view = project(account, symbol="GRIFFAINUSDT", current_price=.016195)
    assert account == before
    assert (view["status"], view["mode"], view["side"]) == ("OPEN", "PAPER", expected)
    assert view["symbol"] == "GRIFFAINUSDT"
    assert view["quantity"] == view["coinQuantity"] == 6174
    assert view["quantityUnit"] == "coin"
    assert view["contractQuantity"] == 6174000
    assert view["entryPrice"] == .016195
    assert view["markPriceSource"] == "SIMULATION_CURRENT_PRICE"
    assert view["positionValue"] == pytest.approx(6174*.016195)
    assert view["unrealizedPnl"] == 0
    assert view["holdingMs"] == pytest.approx(643, abs=.001)
    assert view["leverage"] is view["marginUsed"] is view["liquidationPrice"] is None


@pytest.mark.parametrize("origin,expected", [("MANUAL", "MANUAL"), ("BOT", "BOT"), (None, "UNKNOWN")])
def test_control_is_entry_provenance_only(origin, expected):
    account = paper(entry_authority=origin)
    account["controlAuthority"] = "BOT" if origin == "MANUAL" else "MANUAL"
    assert project(account)["control"] == expected


@pytest.mark.parametrize("account", [{}, {"available": True},
    {"available": True, "positionState": "OPEN", "positions": [], "lastUpdate": NOW},
    {"available": False, "positions": [], "lastUpdate": NOW},
    {"available": True, "positionState": "FLAT", "positions": [], "lastUpdate": NOW-100},
    {"available": True, "positionState": "FLAT", "positions": [], "lastUpdate": NOW, "stale": True}])
def test_unknown_never_flat(account):
    view = project(account)
    assert view["status"] == "UNKNOWN"
    assert view["quantity"] is view["unrealizedPnl"] is None


def test_flat_and_missing_numbers_and_no_price_fallback():
    assert project(dict(available=True, positions=[], positionState="FLAT", lastUpdate=NOW))["status"] == "FLAT"
    view = project(paper(coin_qty=None, multiplier=None), current_price=0)
    assert view["quantity"] == 6174000 and view["quantityUnit"] == "contract"
    assert view["coinQuantity"] is view["markPrice"] is view["positionValue"] is None
    assert project(paper(), symbol="OTHER", current_price=100)["status"] == "UNKNOWN"


def live_observation():
    # Field names match KuCoin Classic Futures Get Position List, not guesses.
    return kucoin_position_observation([
        {"id": "one", "symbol": "XBTUSDTM", "currentQty": 1, "avgEntryPrice": 120000,
         "markPrice": 120009.57, "markValue": 120.00957, "unrealisedPnl": .00957,
         "realLeverage": 6, "posMargin": 20, "liquidationPrice": 100000,
         "openingTimestamp": (NOW-60)*1000},
        {"id": "two", "symbol": "XRPUSDTM", "currentQty": -2, "avgEntryPrice": 2},
    ], NOW)


def test_live_multiple_and_exact_fields():
    account = dict(authenticated=True, lastSync=NOW)
    obs = live_observation()
    view = project(account, "LIVE", observation=obs)
    assert view["status"] == "UNKNOWN" and view["reason"] == "MULTIPLE_POSITIONS"
    assert len(view["positions"]) == 2
    view = project(account, "LIVE", observation=obs, symbol="XBTUSDTM")
    assert view["status"] == "OPEN" and view["side"] == "LONG"
    assert view["quantity"] == 1 and view["quantityUnit"] == "contract"
    assert view["coinQuantity"] is None
    assert view["markPrice"] == 120009.57 and view["leverage"] == 6
    assert view["marginUsed"] == 20 and view["liquidationPrice"] == 100000
    assert view["entryTime"] == NOW-60 and view["holdingMs"] == 60000
    assert view["control"] == "UNKNOWN"
    short = project(account, "LIVE", observation=obs, symbol="XRPUSDTM")
    assert short["side"] == "SHORT" and short["quantity"] == 2
    assert short["markPrice"] is short["leverage"] is short["entryTime"] is None
    obs["positions"].append(deepcopy(obs["positions"][0]))
    assert project(account, "LIVE", observation=obs, symbol="XBTUSDTM")["status"] == "UNKNOWN"


def test_live_invalid_and_stale_coverage_not_flat():
    account = dict(authenticated=True, lastSync=NOW)
    for rows in (None, [{}], [{"currentQty": "nan"}], [{"currentQty": True}]):
        obs = kucoin_position_observation(rows, NOW)
        assert project(account, "LIVE", observation=obs)["status"] == "UNKNOWN"
    obs = kucoin_position_observation([], NOW-100)
    view = project(account, "LIVE", observation=obs)
    assert view["status"] == "UNKNOWN" and view["freshness"] == "STALE"
    assert project(account, "LIVE", observation=kucoin_position_observation([], NOW))["status"] == "FLAT"


def test_live_local_time_and_account_totals_not_position_facts():
    view = project(dict(authenticated=True, lastSync=NOW, unrealizedPnl=999, marginUsed=999,
                        positions=[dict(symbol="XRPUSDTM", qty=1, side="BUY", entry_price=2,
                                        entry_time=NOW, entry_authority="MANUAL")]), "LIVE")
    assert view["status"] == "OPEN"
    assert view["entryTime"] is view["unrealizedPnl"] is view["marginUsed"] is None
    assert view["control"] == "UNKNOWN"


def test_latest_history_mode_separation_643ms_and_authority(tmp_path):
    service = TradeHistoryService(base_directory=tmp_path)
    for mode, closed in (("paper", NOW), ("live", NOW+1)):
        service.store.append(dict(schemaVersion=1, recordId=mode, tradeId=mode, origin="PRODUCTION", scope=mode.upper(),
            mode=mode, symbol="GRIFFAINUSDT", side="BUY", quantity=6174, entryPrice=.016195,
            exitPrice=.016195, entryTimestamp=NOW-.643, exitTimestamp=closed, holdingMs=642.827,
            realizedPnl=0, realizedPnlAuthoritative=mode=="paper", controlSource="MANUAL",
            exitReason="MOMENTUM_DECAY"))
    closed = last_position_event(service, "PAPER")
    assert closed["event"] == "CLOSED" and closed["tradeId"] == "paper"
    assert closed["side"] == "LONG" and closed["quantity"] == 6174
    assert closed["holdingMs"] == 642.827 and closed["realizedPnl"] == 0
    assert closed["control"] == "MANUAL" and closed["exitReason"] == "MOMENTUM_DECAY"
    assert last_position_event(service, "LIVE")["realizedPnl"] is None
    assert project(dict(available=True, positions=[], positionState="FLAT", lastUpdate=NOW))["status"] == "FLAT"
    assert project(paper())["status"] == "OPEN"  # history never overrides current
    assert last_position_event(TradeHistoryService(base_directory=tmp_path/'empty'), "LIVE")["event"] == "UNKNOWN"
    broken = Mock(); broken.history.side_effect = OSError("unavailable")
    assert last_position_event(broken, "PAPER")["realizedPnl"] is None


def test_legacy_kucoin_return_unchanged_and_all_rows_observed():
    from backend.execution.kucoin_trade import KucoinTradeClient
    client = KucoinTradeClient(api_key="k", api_secret="s", passphrase="p")
    rows = live_observation()["positions"]
    client.session.get = Mock()
    client.session.get.return_value.json.return_value = {"code": "200000", "data": rows}
    assert client.get_positions("XRPUSDTM") == dict(symbol="XRPUSDTM", qty=2., side="SELL", entry_price=2.)
    assert len(client.account_position_observation["positions"]) == 2
    assert client.session.get.call_count == 1


def test_account_runtime_additive_and_status_schema(tmp_path):
    from backend.bot_manager.bot_manager import BotManager
    from backend.api.bot_api import StatusResponse
    bot = BotManager()
    bot.engine = Mock(mode="paper", symbol="GRIFFAINUSDT", latest_price=.016195)
    account = paper()
    snapshot = dict(available=True, position=account["positions"][0], last_update=NOW,
                    unrealizedPnl=0, balance=1000)
    real = dict(authenticated=True, lastSync=NOW, positions=[])
    before = deepcopy(real)
    with patch('backend.bot_manager.bot_manager.time.time', return_value=NOW), patch(
        'backend.runtime.trade_history_read.TradeHistoryService', return_value=TradeHistoryService(base_directory=tmp_path)):
        runtime = bot._build_account_runtime(snapshot, {"realAccount": real}, "PAPER", True, "SIMULATION", False)
    assert real == before
    assert {"realAccount", "paperAccount", "execution", "connection"} <= runtime.keys()
    assert runtime["realAccount"] == real
    assert runtime["currentPosition"]["status"] == "OPEN"
    assert runtime["lastPositionEvent"]["event"] == "UNKNOWN"
    assert StatusResponse(accountRuntime=runtime, status="STOPPED", timestamp=NOW,
        last_update=NOW, price=0, marketReady=False, marketStale=True,
        execution_mode="SIMULATION", real_order_allowed=False, ws_connected=False,
        position_active=False, pendingOrder=False, balance=1000, equity=1000, pnl=0,
        executionAuthorityScore=0, authoritativeRuntimeState="STOPPED",
        runtimeSynchronizationState="OFFLINE").model_dump()["accountRuntime"] == runtime


def test_runtime_mode_switch_failure_and_643ms_are_independent(tmp_path):
    from backend.bot_manager.bot_manager import BotManager
    service = TradeHistoryService(base_directory=tmp_path)
    assert service.store.append(dict(schemaVersion=1, recordId="closed", tradeId="closed",
        origin="PRODUCTION", scope="PAPER", mode="paper", symbol="OLDUSDT", side="SELL",
        entryTimestamp=NOW-.643, exitTimestamp=NOW, holdingMs=643, quantity=2,
        realizedPnl=0, controlSource="BOT"))
    bot = BotManager()
    bot.engine = Mock(mode="paper", symbol="NEWUSDT", latest_price=2)
    paper_snapshot = dict(available=True, position=None, last_update=NOW, unrealizedPnl=0)
    real = dict(authenticated=True, lastSync=NOW, positions=[])
    with patch('backend.bot_manager.bot_manager.time.time', return_value=NOW), patch(
        'backend.runtime.trade_history_read.TradeHistoryService', return_value=service):
        runtime = bot._build_account_runtime(paper_snapshot, {"realAccount": real}, "PAPER", True, "SIMULATION", False)
        assert runtime["currentPosition"]["status"] == "FLAT"
        assert runtime["lastPositionEvent"]["event"] == "CLOSED"
        assert runtime["lastPositionEvent"]["symbol"] == "OLDUSDT"
        assert runtime["lastPositionEvent"]["side"] == "SHORT"
        assert runtime["lastPositionEvent"]["holdingMs"] == 643
        live = bot._build_account_runtime(paper_snapshot, {"realAccount": real}, "LIVE", True, "LIVE", False)
        assert live["lastPositionEvent"]["event"] == "UNKNOWN"
        # A failed latest position GET wins over a superficially flat readiness view.
        bot.real_account_snapshot = {**real, "positionObservation": {"positions": None, "sourceUpdatedAt": None}}
        live = bot._build_account_runtime(paper_snapshot, {"realAccount": real}, "LIVE", True, "LIVE", False)
        assert live["currentPosition"]["status"] == "UNKNOWN"
        failed = bot._build_account_runtime({"available": False}, {"realAccount": real}, "PAPER", True, "SIMULATION", False)
        assert failed["currentPosition"]["status"] == "UNKNOWN"
        bot.engine.mode = "live"
        switched = bot._build_account_runtime(paper_snapshot, {"realAccount": real}, "PAPER", True, "SIMULATION", False)
        assert switched["currentPosition"]["status"] == "UNKNOWN"


def test_missing_nonfinite_fields_and_position_side():
    account = dict(authenticated=True, lastSync=NOW)
    obs = kucoin_position_observation([dict(symbol="XRPUSDTM", currentQty=2, positionSide="SHORT",
        avgEntryPrice="nan", markPrice=True, unrealisedPnl="inf", realLeverage="bad",
        posMargin=None, liquidationPrice=None)], NOW)
    view = project(account, "LIVE", observation=obs)
    assert view["side"] == "SHORT"
    for key in ("entryPrice", "markPrice", "unrealizedPnl", "leverage", "marginUsed", "liquidationPrice"):
        assert view[key] is None


def test_observation_failure_does_not_change_execution_reader():
    from backend.execution.kucoin_trade import KucoinTradeClient
    client = KucoinTradeClient(api_key="k", api_secret="s", passphrase="p")
    client.session.get = Mock()
    client.session.get.return_value.json.return_value = {"code": "200000", "data": [
        dict(symbol="XRPUSDTM", currentQty=-2, avgEntryPrice=2)]}
    with patch('backend.runtime.current_position_view.kucoin_position_observation', side_effect=ValueError("observation failed")):
        assert client.get_positions() == dict(symbol="XRPUSDTM", qty=2., side="SELL", entry_price=2.)
    assert client.account_position_observation["positions"] is None
