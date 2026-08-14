import json

from backend.runtime.trading_trace import (
    TradingTraceStore,
    classify_trace,
    make_event,
    new_trace_id,
    sanitize_metadata,
    strategy_decision_snapshot,
)
from backend.aggregation.MicrostructureStateBuilder import MicrostructureStateBuilder
from backend.strategy.MicrostructureEdgeStrategy import MicrostructureEdgeStrategy
from backend.runtime.ExecutionRuntime import ExecutionRuntime
from backend.runtime.trading_trace import trace_store


def event(trace_id, stage, status, *, mode="PAPER", reason=None, metadata=None):
    return make_event(
        trace_id=trace_id, mode=mode, stage=stage, status=status,
        symbol="BTCUSDT", runtime_id="runtime-1", decision_id="decision-1",
        reason_code=reason, metadata=metadata,
    )


def test_trace_id_is_unique_opaque_and_serializable():
    values = {new_trace_id() for _ in range(500)}
    assert len(values) == 500
    assert all(value.startswith("trading-e2e-") for value in values)
    payload = event(next(iter(values)), "STRATEGY", "BUY").to_dict()
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_executed_suppressed_blocked_failed_and_missing_classification():
    executed = new_trace_id()
    assert classify_trace([
        event(executed, "STRATEGY", "BUY").to_dict(),
        event(executed, "GOVERNANCE", "ALLOW").to_dict(),
        event(executed, "EXECUTION", "PAPER_FILLED").to_dict(),
        event(executed, "POSITION", "OPEN").to_dict(),
        event(executed, "RESULT", "EXECUTED").to_dict(),
    ])["classification"] == "COMPLETE_EXECUTED"

    suppressed = new_trace_id()
    assert classify_trace([
        event(suppressed, "STRATEGY", "HOLD").to_dict(),
        event(suppressed, "RESULT", "SUPPRESSED").to_dict(),
    ])["classification"] == "COMPLETE_SUPPRESSED"

    ai_hold = new_trace_id()
    assert classify_trace([
        event(ai_hold, "STRATEGY", "BUY").to_dict(),
        event(ai_hold, "AI", "HOLD").to_dict(),
        event(ai_hold, "RESULT", "SUPPRESSED").to_dict(),
    ])["classification"] == "COMPLETE_SUPPRESSED"

    blocked = new_trace_id()
    assert classify_trace([
        event(blocked, "STRATEGY", "BUY").to_dict(),
        event(blocked, "MONEY_MANAGEMENT", "BLOCKED").to_dict(),
        event(blocked, "RESULT", "BLOCKED").to_dict(),
    ])["classification"] == "COMPLETE_BLOCKED"

    live_failed = new_trace_id()
    assert classify_trace([
        event(live_failed, "STRATEGY", "SELL", mode="LIVE").to_dict(),
        event(live_failed, "EXECUTION", "REJECTED", mode="LIVE", reason="EXCHANGE_REJECTED").to_dict(),
    ])["classification"] == "FAILED"

    missing = new_trace_id()
    result = classify_trace([
        event(missing, "STRATEGY", "BUY").to_dict(),
        event(missing, "GOVERNANCE", "ALLOW").to_dict(),
    ])
    assert result == {
        "classification": "INCOMPLETE",
        "failurePoint": "GOVERNANCE → EXECUTION",
        "primaryReason": "EXPECTED_STAGE_MISSING",
    }


def test_store_read_model_session_aggregation_and_id_propagation(tmp_path):
    store = TradingTraceStore(tmp_path / "trace.jsonl")
    trace_id = new_trace_id()
    for item in (
        event(trace_id, "STRATEGY", "BUY", metadata={"rankingCycleId": "rank-1"}),
        event(trace_id, "GOVERNANCE", "ALLOW"),
        event(trace_id, "EXECUTION", "PAPER_FILLED", metadata={"orderId": "paper-1"}),
        event(trace_id, "POSITION", "OPEN", metadata={"positionId": "position-1"}),
        event(trace_id, "RESULT", "EXECUTED", metadata={"decision": "BUY", "netPnL": 1.25}),
    ):
        store.record(item)
    trace = store.trace(trace_id)
    assert {item["traceId"] for item in trace["events"]} == {trace_id}
    assert trace["finalStatus"] == "COMPLETE_EXECUTED"
    assert trace["orderId"] == "paper-1"
    assert trace["positionId"] == "position-1"
    assert trace["rankingCycleId"] == "rank-1"
    assert trace["netPnL"] == 1.25
    audit = store.session(mode="PAPER", runtime_id="runtime-1")
    assert audit["observedDecisions"] == 1
    assert audit["executedTrades"] == 1
    assert audit["completeTraces"] == 1
    assert len((tmp_path / "trace.jsonl").read_text().splitlines()) == 5


def test_credentials_are_excluded_and_metadata_is_bounded():
    cleaned = sanitize_metadata({
        "apiKey": "no", "secret": "no", "Authorization": "Bearer no",
        "safe": {"passphrase": "no", "reason": "LOW_CONFIDENCE"},
    })
    encoded = json.dumps(cleaned)
    assert "no" not in encoded
    assert cleaned == {"safe": {"reason": "LOW_CONFIDENCE"}}
    assert sanitize_metadata({"large": "x" * 9000})["truncated"] is True


def test_persistence_failure_is_non_blocking(tmp_path):
    store = TradingTraceStore(tmp_path)  # directory cannot be opened as a file
    trace_id = new_trace_id()
    store.record(event(trace_id, "STRATEGY", "HOLD"))
    assert store.events(trace_id)
    assert store.persistence_errors == 1


def test_strategy_trace_snapshot_contains_existing_detector_inputs():
    builder = MicrostructureStateBuilder()
    state = builder.build_microstructure_state({
        "orderbookBids": {0.1000: 30000, 0.0999: 25000},
        "orderbookAsks": {0.1001: 20000, 0.1002: 15000},
        "bestBid": 0.1000, "bestAsk": 0.1001, "lastPrice": 0.10005,
    })
    strategy = MicrostructureEdgeStrategy().process_microstructure_strategy(state)["strategy"]
    snapshot = strategy_decision_snapshot(strategy)

    assert snapshot["market"]["midPrice"] == 0.10005
    assert snapshot["market"]["spreadPct"] is not None
    assert snapshot["orderbook"] == {
        "aggregationDepth": 20, "aggregationMode": "TOP_N",
        "bidDepth": 55000.0, "askDepth": 35000.0, "totalVolume": 90000.0,
    }
    assert snapshot["pressure"]["pressureImbalance"] == state["liquidityInstabilityDebug"]["pressureDiff"]
    absorption = snapshot["detectors"]["details"]["absorption"]
    assert absorption["thresholdTotalVolume"] == builder.ABSORPTION_VOLUME_THRESHOLD
    assert absorption["thresholdAbsPriceDelta"] == builder.ABSORPTION_ABS_PRICE_DELTA_THRESHOLD
    assert absorption["conditionPassed"] is True
    assert snapshot["parameterAuthority"] == {
        "source": "MicrostructureStateBuilder", "kind": "classConstant"
    }
    assert len(json.dumps(snapshot).encode()) < 8192


def test_strategy_trace_snapshot_handles_missing_optional_fields():
    snapshot = strategy_decision_snapshot({
        "confidence": 0.2, "executionAllowed": False,
        "suppressionReason": "LIQUIDITY_INSTABILITY",
    })
    assert snapshot["market"]["bestBid"] is None
    assert snapshot["detectors"]["details"] is None
    assert snapshot["strategy"]["confidence"] == 0.2


def test_detector_boundary_semantics_are_unchanged():
    builder = MicrostructureStateBuilder()
    assert builder.detect_absorption(25000, 25000, 0.0) is False
    assert builder.detect_absorption(25000.1, 25000, 0.0) is True
    assert builder.detect_absorption(30000, 30000, 0.0001) is False
    assert builder.detect_stagnant_heavy_flow(75000, 0.001) is False
    assert builder.detect_stagnant_heavy_flow(75000.1, 0.0003) is False
    assert builder.detect_fake_pressure(0.85, 0.15, 0.0) is False
    assert builder.detect_fake_pressure(0.851, 0.149, 0.0) is True


def test_execution_runtime_strategy_event_includes_decision_snapshot():
    state = MicrostructureStateBuilder().build_microstructure_state({
        "buyVolume": 90000.0, "sellVolume": 1000.0,
        "bestBid": 0.1, "bestAsk": 0.1004, "lastPrice": 0.1002,
    })
    strategy = MicrostructureEdgeStrategy().process_microstructure_strategy(state)["strategy"]
    strategy["symbol"] = "MOVEUSDT"
    result = ExecutionRuntime().process_execution_runtime(strategy)
    strategy_event = trace_store.events(result["traceId"])[0]
    snapshot = strategy_event["metadata"]["decisionInput"]
    assert snapshot["market"]["bestBid"] == 0.1
    assert snapshot["detectors"]["absorptionDetected"] is True
    assert snapshot["strategy"]["finalDecision"] == "HOLD"
    assert strategy_event["reasonCode"] == "LIQUIDITY_INSTABILITY"


def test_execution_runtime_ai_event_is_explicitly_disabled_without_fallback():
    state = MicrostructureStateBuilder().build_microstructure_state({
        "buyVolume": 90000.0, "sellVolume": 1000.0,
        "bestBid": 0.1, "bestAsk": 0.1004, "lastPrice": 0.1002,
    })
    strategy = MicrostructureEdgeStrategy().process_microstructure_strategy(
        state
    )["strategy"]
    result = ExecutionRuntime().process_execution_runtime(strategy)
    ai_event = next(
        item for item in trace_store.events(result["traceId"])
        if item["stage"] == "AI"
    )

    assert ai_event["status"] == "DISABLED"
    assert ai_event["reasonCode"] == "TRADING_AI_OFF"
    assert ai_event["metadata"] == {
        "mode": "OFF",
        "implementationStatus": "NOT_INSTALLED",
        "required": False,
        "fallback": None,
    }
