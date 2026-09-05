"""Bounded, typed HISTORICAL_EVIDENCE trace context for the AI Advisor.

This is INFORMATION_ONLY and READ_ONLY evidence infrastructure (D-5).

It reduces assembled ``UnifiedTradingTrace`` objects to a small, allowlisted,
bounded view suitable for prompt injection.  It deliberately:

* never dumps raw databases, event logs or arbitrary request payloads;
* keeps original reason codes and provenance, never converting them to
  free-form language;
* never merges historical evidence with CURRENT RUNTIME context (the prompt
  builder labels this block ``HISTORICAL EVIDENCE`` explicitly);
* bounds every collection and exposes truncation as an explicit fact.
"""

from __future__ import annotations

from typing import Annotated, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from backend.runtime.unified_trace import (
    NoTraceKind,
    Provenance,
    TraceCompleteness,
    TraceNode,
    TraceNodeType,
    TraceReasonCode,
    UnifiedTradingTrace,
    list_unified_traces,
)

MAX_TRACE_EVIDENCE_TRACES = 5
MAX_TRACE_EVIDENCE_NODES_PER_TRACE = 12
MAX_TRACE_EVIDENCE_REASON_CODES = 12
MAX_TRACE_EVIDENCE_SOURCE_REFERENCES = 12
MAX_TRACE_EVIDENCE_IDENTIFIER = 128
MAX_TRACE_EVIDENCE_TEXT = 256

# Allowlisted node types surfaced to the Advisor.  Raw market microstructure
# and deterministic internals are NOT projected into prompts.
_ALLOWED_ADVISOR_NODE_TYPES = {
    TraceNodeType.DECISION,
    TraceNodeType.NO_TRADE,
    TraceNodeType.ENTRY_REJECTION,
    TraceNodeType.ENTRY_INTENT,
    TraceNodeType.EXECUTION_ATTEMPT,
    TraceNodeType.ORDER,
    TraceNodeType.FILL,
    TraceNodeType.POSITION,
    TraceNodeType.EXIT,
    TraceNodeType.TRADE_RESULT,
    TraceNodeType.MARKET_OBSERVATION,
}

_TRACE_ORDER_IDENTITIES = ("orderId", "exchangeOrderId", "positionId", "fillId", "tradeId")


def _bound(value: Optional[str], length: int = MAX_TRACE_EVIDENCE_TEXT) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:length]


class AdvisorTraceReasonCode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: Annotated[str, Field(min_length=1, max_length=128)]
    subsystem: Annotated[str, Field(min_length=1, max_length=64)]
    category: Optional[Annotated[str, Field(min_length=1, max_length=64)]] = None
    meaning: Optional[Annotated[str, Field(min_length=1, max_length=MAX_TRACE_EVIDENCE_TEXT)]] = None


class AdvisorTraceProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sourceSubsystem: Annotated[str, Field(min_length=1, max_length=64)]
    sourceType: Annotated[str, Field(min_length=1, max_length=MAX_TRACE_EVIDENCE_TEXT)]
    sourceIdentifier: Annotated[
        str, Field(min_length=1, max_length=MAX_TRACE_EVIDENCE_IDENTIFIER)
    ]
    timestamp: Optional[
        Annotated[str, Field(min_length=1, max_length=MAX_TRACE_EVIDENCE_IDENTIFIER)]
    ] = None
    linkageMethod: Annotated[str, Field(min_length=1, max_length=64)]
    confidence: Optional[
        Annotated[str, Field(min_length=1, max_length=MAX_TRACE_EVIDENCE_TEXT)]
    ] = None


class AdvisorTraceNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nodeType: Annotated[str, Field(min_length=1, max_length=64)]
    status: Annotated[str, Field(min_length=1, max_length=128)]
    timestamp: Optional[Annotated[str, Field(min_length=1, max_length=128)]] = None
    noTradeKind: Optional[Annotated[str, Field(min_length=1, max_length=64)]] = None
    reasonCodes: Tuple[AdvisorTraceReasonCode, ...] = Field(default_factory=tuple)
    identity: Tuple[str, ...] = Field(default_factory=tuple)
    provenance: Optional[AdvisorTraceProvenance] = None


class AdvisorUnifiedTrace(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    traceId: Annotated[str, Field(min_length=1, max_length=MAX_TRACE_EVIDENCE_IDENTIFIER)]
    symbol: Optional[Annotated[str, Field(min_length=1, max_length=64)]] = None
    mode: Optional[Annotated[str, Field(min_length=1, max_length=16)]] = None
    completeness: Annotated[str, Field(min_length=1, max_length=32)]
    startedAt: Optional[Annotated[str, Field(min_length=1, max_length=128)]] = None
    endedAt: Optional[Annotated[str, Field(min_length=1, max_length=128)]] = None
    decision: Optional[AdvisorTraceNode] = None
    noTrade: Optional[AdvisorTraceNode] = None
    rejection: Optional[AdvisorTraceNode] = None
    executionAttempt: Optional[AdvisorTraceNode] = None
    position: Optional[AdvisorTraceNode] = None
    exit: Optional[AdvisorTraceNode] = None
    tradeResult: Optional[AdvisorTraceNode] = None
    orderCount: int = 0
    fillCount: int = 0
    nodes: Tuple[AdvisorTraceNode, ...] = Field(default_factory=tuple)
    reasonCodes: Tuple[AdvisorTraceReasonCode, ...] = Field(default_factory=tuple)
    sourceReferences: Tuple[AdvisorTraceProvenance, ...] = Field(default_factory=tuple)
    sourceReferencesTruncated: bool = False
    nodesTruncated: bool = False
    reasonCodesTruncated: bool = False


class AdvisorTraceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schemaVersion: str = "advisor-historical-trace/v1"
    traces: Tuple[AdvisorUnifiedTrace, ...] = Field(default_factory=tuple)
    truncated: bool = False
    omittedTraceCount: int = 0
    warning: Optional[Annotated[str, Field(min_length=1, max_length=MAX_TRACE_EVIDENCE_TEXT)]] = None

    @property
    def is_empty(self) -> bool:
        return not self.traces


def _project_reason_codes(
    reason_codes: Tuple[TraceReasonCode, ...],
    *,
    limit: int,
) -> tuple[list[AdvisorTraceReasonCode], bool]:
    projected: list[AdvisorTraceReasonCode] = []
    truncated = False
    for item in reason_codes:
        if len(projected) >= limit:
            truncated = True
            break
        projected.append(
            AdvisorTraceReasonCode(
                code=item.code,
                subsystem=item.subsystem.value,
                category=item.category,
                meaning=item.meaning,
            )
        )
    return projected, truncated


def _project_provenance(prov: Provenance) -> AdvisorTraceProvenance:
    return AdvisorTraceProvenance(
        sourceSubsystem=prov.source_subsystem.value,
        sourceType=prov.source_type,
        sourceIdentifier=(
            _bound(prov.source_identifier, MAX_TRACE_EVIDENCE_IDENTIFIER) or "unknown"
        ),
        timestamp=_bound(prov.timestamp, MAX_TRACE_EVIDENCE_IDENTIFIER),
        linkageMethod=prov.linkage_method,
        confidence=_bound(prov.confidence, MAX_TRACE_EVIDENCE_TEXT),
    )


def _project_source_references(
    references: Tuple[Provenance, ...],
    *,
    limit: int,
) -> tuple[list[AdvisorTraceProvenance], bool]:
    projected: list[AdvisorTraceProvenance] = []
    truncated = False
    seen: set[tuple[str, str, str]] = set()
    for reference in references:
        if len(projected) >= limit:
            truncated = True
            break
        key = (
            reference.source_subsystem.value,
            reference.source_type,
            reference.source_identifier,
        )
        if key in seen:
            continue
        seen.add(key)
        projected.append(_project_provenance(reference))
    return projected, truncated


def _project_node(node: Optional[TraceNode]) -> Optional[AdvisorTraceNode]:
    if node is None:
        return None
    reason_codes, _ = _project_reason_codes(
        node.reason_codes, limit=MAX_TRACE_EVIDENCE_REASON_CODES
    )
    identity = tuple(
        str(node.identity[key])
        for key in _TRACE_ORDER_IDENTITIES
        if node.identity.get(key) is not None
    )
    provenance = (
        _project_provenance(node.provenance) if node.provenance is not None else None
    )
    return AdvisorTraceNode(
        nodeType=node.node_type.value,
        status=node.status or "UNKNOWN",
        timestamp=_bound(node.timestamp, MAX_TRACE_EVIDENCE_IDENTIFIER),
        noTradeKind=node.no_trade_kind.value if node.no_trade_kind else None,
        reasonCodes=tuple(reason_codes),
        identity=identity,
        provenance=provenance,
    )


def _filter_node(node: Optional[TraceNode]) -> bool:
    return node is not None and node.node_type in _ALLOWED_ADVISOR_NODE_TYPES


def _project_trace(
    trace: UnifiedTradingTrace,
    *,
    node_limit: int,
) -> AdvisorUnifiedTrace:
    main_nodes = [
        _project_node(node)
        for node in (
            trace.decision,
            trace.no_trade,
            trace.rejection,
            trace.execution_attempt,
            trace.position,
            trace.exit,
            trace.trade_result,
        )
        if _filter_node(node)
    ]
    available_count = len(main_nodes) + len(trace.orders) + len(trace.fills)
    nodes_truncated = available_count > node_limit

    projection_nodes: list[Optional[AdvisorTraceNode]] = list(main_nodes)
    for node in trace.orders:
        if len(projection_nodes) >= node_limit:
            break
        projection_nodes.append(_project_node(node))
    for node in trace.fills:
        if len(projection_nodes) >= node_limit:
            break
        projection_nodes.append(_project_node(node))
    selected_nodes = tuple(
        node for node in projection_nodes[:node_limit] if node is not None
    )

    reason_codes, reason_truncated = _project_reason_codes(
        trace.reason_codes, limit=MAX_TRACE_EVIDENCE_REASON_CODES
    )
    source_references, source_refs_truncated = _project_source_references(
        trace.source_references, limit=MAX_TRACE_EVIDENCE_SOURCE_REFERENCES
    )

    return AdvisorUnifiedTrace(
        traceId=_bound(trace.trace_id, MAX_TRACE_EVIDENCE_IDENTIFIER) or "unknown",
        symbol=_bound(trace.symbol, 64),
        mode=_bound(trace.mode, 16),
        completeness=trace.completeness.value,
        startedAt=_bound(trace.started_at, MAX_TRACE_EVIDENCE_IDENTIFIER),
        endedAt=_bound(trace.ended_at, MAX_TRACE_EVIDENCE_IDENTIFIER),
        decision=next((n for n in selected_nodes if n.nodeType == TraceNodeType.DECISION.value), None),
        noTrade=next((n for n in selected_nodes if n.nodeType == TraceNodeType.NO_TRADE.value), None),
        rejection=next((n for n in selected_nodes if n.nodeType == TraceNodeType.ENTRY_REJECTION.value), None),
        executionAttempt=next((n for n in selected_nodes if n.nodeType == TraceNodeType.EXECUTION_ATTEMPT.value), None),
        position=next((n for n in selected_nodes if n.nodeType == TraceNodeType.POSITION.value), None),
        exit=next((n for n in selected_nodes if n.nodeType == TraceNodeType.EXIT.value), None),
        tradeResult=next((n for n in selected_nodes if n.nodeType == TraceNodeType.TRADE_RESULT.value), None),
        orderCount=len(trace.orders),
        fillCount=len(trace.fills),
        nodes=selected_nodes,
        reasonCodes=tuple(reason_codes),
        sourceReferences=tuple(source_references),
        sourceReferencesTruncated=source_refs_truncated,
        nodesTruncated=nodes_truncated,
        reasonCodesTruncated=reason_truncated,
    )


def build_advisor_trace_evidence(
    traces: Tuple[UnifiedTradingTrace, ...],
    *,
    max_traces: int = MAX_TRACE_EVIDENCE_TRACES,
    max_nodes_per_trace: int = MAX_TRACE_EVIDENCE_NODES_PER_TRACE,
) -> AdvisorTraceEvidence:
    """Build a bounded, allowlisted HISTORICAL_EVIDENCE view of unified traces.

    All inputs must already be assembled unified traces.  This function never
    reads external state and never mutates its inputs.
    """
    if max_traces < 0:
        raise ValueError("max_traces must be non-negative")
    if max_nodes_per_trace < 0:
        raise ValueError("max_nodes_per_trace must be non-negative")

    ordered = list(traces)[: max_traces if max_traces else 0]
    omitted = max(0, len(list(traces)) - len(ordered))
    selected = [
        _project_trace(trace, node_limit=max_nodes_per_trace)
        for trace in ordered
        if isinstance(trace, UnifiedTradingTrace)
    ]
    truncated = bool(omitted) or any(
        trace.nodesTruncated
        or trace.reasonCodesTruncated
        or trace.sourceReferencesTruncated
        for trace in selected
    )
    warning = None
    if truncated:
        reasons = []
        if omitted:
            reasons.append(f"omitted {omitted} older traces")
        if any(trace.nodesTruncated for trace in selected):
            reasons.append("some traces truncated")
        if any(trace.reasonCodesTruncated for trace in selected):
            reasons.append("some reason codes truncated")
        if any(trace.sourceReferencesTruncated for trace in selected):
            reasons.append("some source references truncated")
        warning = "; ".join(reasons)
    return AdvisorTraceEvidence(
        traces=tuple(selected),
        truncated=truncated,
        omittedTraceCount=omitted,
        warning=warning,
    )


def historical_trace_lines(evidence: AdvisorTraceEvidence) -> list[tuple[str, object]]:
    """Return allowlisted (name, value) pairs that the prompt layer can render.

    Only typed, bounded fields are surfaced; raw payloads are never projected.
    """
    if evidence is None:
        return [("status", "NOT_AVAILABLE")]
    lines: list[tuple[str, object]] = [
        ("classification", "HISTORICAL EVIDENCE"),
        ("traceCount", len(evidence.traces)),
    ]
    if evidence.truncated:
        lines.append(("truncated", True))
        lines.append(("omittedTraceCount", evidence.omittedTraceCount))
        if evidence.warning:
            lines.append(("warning", evidence.warning))
    if not evidence.traces:
        lines.append(("status", "NOT_AVAILABLE"))
    for index, trace in enumerate(evidence.traces):
        prefix = f"trace[{index}]"
        lines.append((f"{prefix}.traceId", trace.traceId))
        lines.append((f"{prefix}.symbol", trace.symbol or "null"))
        lines.append((f"{prefix}.mode", trace.mode or "null"))
        lines.append((f"{prefix}.completeness", trace.completeness))
        lines.append((f"{prefix}.orderCount", trace.orderCount))
        lines.append((f"{prefix}.fillCount", trace.fillCount))
        for field_name in ("decision", "noTrade", "rejection", "executionAttempt", "position", "exit", "tradeResult"):
            node = getattr(trace, field_name)
            lines.extend(_node_lines(prefix, field_name, node))
        if trace.reasonCodes:
            codes = ",".join(item.code for item in trace.reasonCodes)
            lines.append((f"{prefix}.reasonCodes", codes))
        if trace.sourceReferencesTruncated:
            lines.append((f"{prefix}.sourceReferencesTruncated", True))
        if trace.nodesTruncated:
            lines.append((f"{prefix}.nodesTruncated", True))
        if trace.reasonCodesTruncated:
            lines.append((f"{prefix}.reasonCodesTruncated", True))
    return lines


def _node_lines(prefix: str, field_name: str, node: Optional[AdvisorTraceNode]) -> list[tuple[str, object]]:
    if node is None:
        return [(f"{prefix}.{field_name}", "null")]
    out = [
        (f"{prefix}.{field_name}.nodeType", node.nodeType),
        (f"{prefix}.{field_name}.status", node.status),
    ]
    if node.timestamp:
        out.append((f"{prefix}.{field_name}.timestamp", node.timestamp))
    if node.noTradeKind:
        out.append((f"{prefix}.{field_name}.noTradeKind", node.noTradeKind))
    if node.identity:
        out.append((f"{prefix}.{field_name}.identity", ",".join(node.identity)))
    for index, code in enumerate(node.reasonCodes):
        out.append((f"{prefix}.{field_name}.reasonCode[{index}]", code.code))
    return out


def render_historical_trace_evidence(evidence: AdvisorTraceEvidence) -> str:
    """Render the bounded historical trace evidence as plain content lines."""
    return "\n".join(
        f"{name}={_render_scalar(value)}" for name, value in historical_trace_lines(evidence)
    )


def _render_scalar(value: object) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def empty_trace_evidence() -> AdvisorTraceEvidence:
    """A default, bounded, empty historical evidence block."""
    return AdvisorTraceEvidence(traces=())


def build_default_historical_trace_evidence(
    *,
    limit: int = MAX_TRACE_EVIDENCE_TRACES,
) -> AdvisorTraceEvidence:
    """Build bounded historical evidence from the authoritative trace store.

    This is the D-5 default wiring for the Advisor read-only composition.  It
    reads the existing authoritative ``TradingTraceStore`` through the bounded
    ``list_unified_traces`` helper and projects it with
    ``build_advisor_trace_evidence``.  It never mutates the store and degrades
    to empty evidence on any failure so that trace availability never affects
    Advisor availability.
    """
    if limit < 0:
        raise ValueError("limit must be non-negative")
    try:
        traces = list_unified_traces(limit=limit)
        return build_advisor_trace_evidence(tuple(traces))
    except Exception:
        return empty_trace_evidence()


__all__ = [
    "AdvisorTraceEvidence",
    "AdvisorUnifiedTrace",
    "AdvisorTraceNode",
    "AdvisorTraceReasonCode",
    "AdvisorTraceProvenance",
    "build_advisor_trace_evidence",
    "build_default_historical_trace_evidence",
    "historical_trace_lines",
    "render_historical_trace_evidence",
    "empty_trace_evidence",
    "MAX_TRACE_EVIDENCE_TRACES",
    "MAX_TRACE_EVIDENCE_NODES_PER_TRACE",
    "MAX_TRACE_EVIDENCE_REASON_CODES",
]
