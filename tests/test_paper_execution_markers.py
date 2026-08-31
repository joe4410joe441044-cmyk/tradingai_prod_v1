from types import SimpleNamespace

from backend.market.paper_execution_markers import (
    PAPER_MARKER_HISTORY_LIMIT,
    build_paper_execution_markers,
)


CONTEXT = "KUCOIN:FUTURES:XRPUSDTM"
RUNTIME = "runtime-current"


def markers(engine, symbol="XRPUSDT"):
    return build_paper_execution_markers(
        engine, active_symbol=symbol, context_key=CONTEXT,
        runtime_instance_id=RUNTIME,
    )


def fill(**overrides):
    value = {
        "fillId": "fill-1", "orderId": "order-1", "mode": "paper",
        "symbol": "XRPUSDT", "side": "BUY", "qty": 2.0,
        "price": 0.6123, "filledAt": 100.0,
    }
    value.update(overrides)
    return value


def trade(**overrides):
    value = {
        "tradeId": "trade-1", "mode": "paper", "status": "CLOSED",
        "symbol": "XRPUSDT", "side": "BUY", "qty": 2.0,
        "exitPrice": 0.62, "closedAt": 101.0, "reason": "TP",
    }
    value.update(overrides)
    return value


def test_actual_paper_fill_and_closed_trade_map_to_stable_markers():
    engine = SimpleNamespace(mode="paper", paper_fills=[fill()], trade_history=[trade()])
    result = markers(engine)
    assert [item["type"] for item in result] == ["EXIT", "ENTRY"]
    assert [item["id"] for item in result] == ["paper-exit:trade-1", "paper-entry:fill-1"]
    assert all(item["source"] == "PAPER_RUNTIME" for item in result)
    assert all(item["contextKey"] == CONTEXT for item in result)
    assert all(item["runtimeInstanceId"] == RUNTIME for item in result)


def test_non_authority_malformed_duplicate_and_foreign_records_are_rejected():
    engine = SimpleNamespace(mode="paper", paper_fills=[
        fill(), fill(), fill(fillId=None), fill(fillId="btc", symbol="BTCUSDT"),
        fill(fillId="context", contextKey="KUCOIN:FUTURES:BTCUSDTM"),
        fill(fillId="runtime", runtimeInstanceId="runtime-old"),
    ], trade_history=[
        trade(), trade(), trade(tradeId="open", status="OPEN"),
        trade(tradeId="bad", exitPrice=None), trade(tradeId="btc", symbol="BTCUSDT"),
    ])
    assert [item["id"] for item in markers(engine)] == [
        "paper-exit:trade-1", "paper-entry:fill-1",
    ]
    assert [item["id"] for item in markers(engine, symbol="BTCUSDT")] == [
        "paper-exit:btc", "paper-entry:btc",
    ]


def test_live_or_unavailable_engine_fails_closed_without_replay_fallback():
    live = SimpleNamespace(mode="live", paper_fills=[fill()], trade_history=[trade()])
    assert markers(live) == []
    assert markers(None) == []


def test_ordering_is_deterministic_and_history_is_bounded():
    records = [fill(fillId=f"fill-{index}", filledAt=100 + index) for index in range(120)]
    engine = SimpleNamespace(mode="paper", paper_fills=records, trade_history=[])
    result = markers(engine)
    assert len(result) == PAPER_MARKER_HISTORY_LIMIT
    assert result[0]["id"] == "paper-entry:fill-119"
    tied = SimpleNamespace(mode="paper", paper_fills=[
        fill(fillId="z", filledAt=100), fill(fillId="a", filledAt=100),
    ], trade_history=[])
    assert [item["id"] for item in markers(tied)] == ["paper-entry:a", "paper-entry:z"]
