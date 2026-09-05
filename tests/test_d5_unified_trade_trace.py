"""Focused D-5 tests for the provider-neutral unified trading trace linkage."""

from backend.runtime.trading_trace import (
    TradingTraceStore,
    make_event,
    new_trace_id,
)
from backend.runtime.unified_trace import (
    LinkStrength,
    NoTraceKind,
    SourceSubsystem,
    StaticTraceEvidenceSource,
    TraceCompleteness,
    TraceNodeType,
    TradingTraceStoreSource,
    UnifiedTraceAssembler,
    UnifiedTradingTrace,
    build_default_reason_catalog,
)


def _events(trace_id, *items):
    mapped = []
    for item in items:
        stage, status = item[0], item[1]
        reason = item[2] if len(item) > 2 else None
        meta = item[3] if len(item) > 3 else None
        mode = item[4] if len(item) > 4 else "PAPER"
        mapped.append(
            make_event(
                trace_id=trace_id, mode=mode, stage=stage, status=status,
                symbol="BTCUSDT", runtime_id="runtime-1", decision_id="decision-1",
                reason_code=reason, metadata=meta,
            ).to_dict()
        )
    return mapped


def _assemble(events):
    trace_id = events[0]["traceId"]
    return UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(trace_id)


def test_direct_decision_to_order_linkage():
    trace_id = new_trace_id()
    events = _events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "paper-1"}),
        ("POSITION", "OPEN", None, {"positionId": "position-1", "orderId": "paper-1"}),
        ("RESULT", "EXECUTED", None, {"decision": "BUY", "netPnL": 1.25}),
    )
    trace = _assemble(events)
    assert trace.completeness is TraceCompleteness.COMPLETE
    assert trace.decision.node_type is TraceNodeType.DECISION
    assert [order.identity.get("orderId") for order in trace.orders] == ["paper-1"]
    assert trace.position.identity.get("orderId") == "paper-1"
    order_link = next(link for link in trace.links if link.method == "ORDER_ID")
    assert order_link.strength is LinkStrength.DIRECT_ID


def test_decision_to_no_trade_linkage():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "HOLD", "LIQUIDITY_INSTABILITY"),
        ("RESULT", "SUPPRESSED", "LIQUIDITY_INSTABILITY"),
    ))
    assert trace.completeness is TraceCompleteness.COMPLETE
    assert trace.no_trade is not None
    assert trace.no_trade.node_type is TraceNodeType.NO_TRADE
    assert trace.no_trade.no_trade_kind is NoTraceKind.NO_TRADE_DECISION
    assert trace.decision is None
    assert trace.orders == ()


def test_rejected_entry_linkage():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("MONEY_MANAGEMENT", "BLOCKED", "MAXIMUM_DRAWDOWN"),
        ("RESULT", "BLOCKED", "MAXIMUM_DRAWDOWN"),
    ))
    assert trace.completeness is TraceCompleteness.COMPLETE
    assert trace.rejection is not None
    assert trace.rejection.node_type is TraceNodeType.ENTRY_REJECTION
    assert trace.money_management_evidence
    assert trace.rejection.reason_codes[0].code == "MAXIMUM_DRAWDOWN"


def test_order_to_fill_linkage():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "paper-1", "fillId": "paper-1-fill-1"}),
        ("POSITION", "OPEN", None, {"positionId": "p1", "orderId": "paper-1"}),
        ("RESULT", "EXECUTED"),
    ))
    assert trace.orders
    assert trace.fills
    fill_link = next(link for link in trace.links if link.method == "FILL_ORDER_ID")
    assert fill_link.strength in {LinkStrength.DIRECT_ID, LinkStrength.DERIVED_DETERMINISTIC}


def test_fill_to_position_linkage():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "SELL"),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "o-1"}),
        ("POSITION", "OPEN", None, {"positionId": "p-1", "orderId": "o-1"}),
        ("RESULT", "EXECUTED"),
    ))
    assert trace.position is not None
    fill_to_position = [
        link for link in trace.links
        if link.method in {"FILL_ORDER_ID", "TRACE_ID"}
        and link.target_id == trace.position.node_id
    ]
    assert fill_to_position
    assert all(link.strength in {LinkStrength.DIRECT_ID, LinkStrength.DERIVED_DETERMINISTIC} for link in fill_to_position)


def test_exit_to_trade_result_linkage():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "o-1"}),
        ("POSITION", "OPEN", None, {"positionId": "p-1", "orderId": "o-1"}),
        ("RESULT", "CLOSED", "TAKE_PROFIT", {"netPnL": 3.5, "tradeId": "trade-1"}),
        ("HISTORY", "RECORDED", None, {"tradeId": "trade-1"}),
    ))
    assert trace.exit is not None
    assert trace.trade_result is not None
    assert trace.exit.node_type is TraceNodeType.EXIT
    spine = [link for link in trace.links if link.method == "TRACE_ID"]
    assert spine


def test_missing_evidence_is_partial():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("GOVERNANCE", "ALLOW"),
    ))
    assert trace.completeness is TraceCompleteness.PARTIAL
    assert any("MISSING" in warning or "PARTIAL" in warning.upper() or len(warning) for warning in trace.warnings)


def test_conflicting_candidates_is_ambiguous():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("STRATEGY", "SELL"),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "o-1"}),
    ))
    assert trace.completeness is TraceCompleteness.AMBIGUOUS
    assert "MULTIPLE_DECISION_CANDIDATES" in trace.warnings


def test_no_evidence_is_unavailable():
    trace = UnifiedTraceAssembler(StaticTraceEvidenceSource([])).assemble(new_trace_id())
    assert trace.completeness is TraceCompleteness.UNAVAILABLE
    assert "NO_AUTHORITATIVE_EVIDENCE" in trace.warnings


def test_execution_failure_is_not_a_no_trade():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "SELL"),
        ("EXECUTION", "REJECTED", "EXCHANGE_REJECTED"),
    ))
    assert trace.no_trade is None
    assert trace.execution_attempt.no_trade_kind is NoTraceKind.EXECUTION_FAILURE
    assert trace.completeness is TraceCompleteness.PARTIAL


def test_temporal_only_is_not_promoted_to_direct_proof():
    trace_id = new_trace_id()
    # A fill that carries no linkage ID (only timestamp proximity to the order).
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("EXECUTION", "PAPER_FILLED"),
        ("RESULT", "EXECUTED"),
    ))
    # Without an order/fill id the assembler must not claim a DIRECT_ID order link.
    order_links = [link for link in trace.links if link.method == "ORDER_ID"]
    assert order_links == []
    for link in trace.links:
        assert link.strength is not LinkStrength.TEMPORAL_CORRELATION
        assert link.strength in {
            LinkStrength.DIRECT_ID, LinkStrength.DERIVED_DETERMINISTIC,
        }


def test_reason_code_preservation():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "HOLD", "STRATEGY_HOLD"),
        ("RESULT", "SUPPRESSED", "STRATEGY_HOLD"),
    ))
    codes = [code.code for code in trace.reason_codes]
    assert "STRATEGY_HOLD" in codes
    assert all(isinstance(code, str) for code in codes)


def test_reason_code_catalog_enrichment():
    trace_id = new_trace_id()
    store = TradingTraceStore()
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="STRATEGY", status="HOLD",
        symbol="BTCUSDT", reason_code="LIQUIDITY_INSTABILITY",
    ))
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="RESULT", status="SUPPRESSED",
        symbol="BTCUSDT",
    ))
    trace = UnifiedTraceAssembler(
        TradingTraceStoreSource(store),
        reason_code_resolver=build_default_reason_catalog(),
    ).assemble(trace_id)
    enriched = next(r for r in trace.reason_codes if r.code == "LIQUIDITY_INSTABILITY")
    assert enriched.subsystem is SourceSubsystem.STRATEGY
    assert enriched.category == "SUPPRESSION_REASON"


def test_provenance_preservation():
    trace_id = new_trace_id()
    trace = _assemble(_events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("RESULT", "EXECUTED"),
    ))
    assert trace.source_references
    for node in trace.nodes:
        assert node.provenance.source_identifier
        assert node.provenance.source_subsystem is not None


def test_deterministic_output():
    trace_id = new_trace_id()
    events = _events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "o-1"}),
        ("RESULT", "EXECUTED"),
    )
    first = _assemble(events).to_dict()
    second = _assemble(events).to_dict()
    assert first == second


def test_input_non_mutation():
    trace_id = new_trace_id()
    events = _events(
        trace_id,
        ("STRATEGY", "BUY"),
        ("EXECUTION", "PAPER_FILLED", None, {"orderId": "o-1"}),
        ("RESULT", "EXECUTED"),
    )
    snapshot = [dict(item) for item in events]
    _assemble(events)
    assert events == snapshot


def test_no_operational_mutation_no_authority():
    trace_id = new_trace_id()
    store = TradingTraceStore()
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="STRATEGY", status="BUY",
        symbol="BTCUSDT", decision_id="d1",
    ))
    store.record(make_event(
        trace_id=trace_id, mode="PAPER", stage="RESULT", status="EXECUTED",
        symbol="BTCUSDT", decision_id="d1",
    ))
    before = len(store.events(trace_id))
    UnifiedTraceAssembler(TradingTraceStoreSource(store)).assemble(trace_id)
    assert len(store.events(trace_id)) == before
    assert store.persistence_errors == 0


def test_provider_neutrality_accepts_any_trace_events():
    trace_id = new_trace_id()
    events = _events(trace_id, ("STRATEGY", "BUY"))
    trace = UnifiedTraceAssembler(StaticTraceEvidenceSource(events)).assemble(trace_id)
    assert trace.trace_id == trace_id
    # A different provider (store-backed) returns the same conceptual trace.
    store = TradingTraceStore()
    for item in events:
        store.record(make_event(
            trace_id=trace_id, mode="PAPER", stage=item["stage"], status=item["status"],
            symbol="BTCUSDT",
        ))
    store_trace = UnifiedTraceAssembler(TradingTraceStoreSource(store)).assemble(trace_id)
    assert store_trace.decision.node_type is TraceNodeType.DECISION


def test_model_is_serializable_and_typed():
    trace_id = new_trace_id()
    trace = _assemble(_events(trace_id, ("STRATEGY", "BUY"), ("RESULT", "EXECUTED")))
    assert isinstance(trace, UnifiedTradingTrace)
    payload = trace.to_dict()
    assert payload["traceId"] == trace_id
    assert payload["completeness"] in {item.value for item in TraceCompleteness}
