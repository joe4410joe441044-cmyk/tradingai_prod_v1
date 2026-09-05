"""D-5 unified, provider-neutral trading trace linkage and assemblage.

This module is INFORMATION_ONLY.  It links and explains existing evidence.

It deliberately does NOT create a second trading history system.  The
authoritative sources (the existing ``TradingTraceStore`` and the runtime
execution/position paths) remain the source of truth.  A unified trace is a
typed, assembled VIEW of that evidence with explicit completeness, link
strength, provenance and reason-code semantics.

Authority contract:

* Unified Trace Authority      = INFORMATION_ONLY
* Trace Linkage Authority      = INFORMATION_ONLY
* Historical Evidence Authority = EVIDENCE_ONLY
* Operational Authority        = NONE
* Execution Authority          = NONE

Trace assemblage never authorises a trade, toggles Auto Trade, starts a Loop
or BOT, changes PAPER/LIVE mode, overrides execution guards, money management,
emergency, runtime truth or the canonical specification.  It only explains and
links evidence.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence

from backend.runtime.trading_trace import (
    STAGES,
    TradingTraceStore,
    sanitize_metadata,
    trace_store as default_trace_store,
)


class SourceSubsystem(str, Enum):
    """Actual repository subsystems contributing trace evidence."""

    MARKET = "MARKET"
    STRATEGY = "STRATEGY"
    MONEY_MANAGEMENT = "MONEY_MANAGEMENT"
    EXECUTION = "EXECUTION"
    POSITION = "POSITION"
    RUNTIME = "RUNTIME"
    GOVERNANCE = "GOVERNANCE"
    SUPERVISOR = "SUPERVISOR"
    KNOWLEDGE = "KNOWLEDGE"
    UNKNOWN = "UNKNOWN"


class TraceNodeType(str, Enum):
    """Explicit trace node/reference categories."""

    MARKET_OBSERVATION = "MARKET_OBSERVATION"
    DECISION = "DECISION"
    NO_TRADE = "NO_TRADE"
    ENTRY_REJECTION = "ENTRY_REJECTION"
    ENTRY_INTENT = "ENTRY_INTENT"
    EXECUTION_ATTEMPT = "EXECUTION_ATTEMPT"
    ORDER = "ORDER"
    FILL = "FILL"
    POSITION = "POSITION"
    EXIT = "EXIT"
    TRADE_RESULT = "TRADE_RESULT"
    RUNTIME_SNAPSHOT = "RUNTIME_SNAPSHOT"
    AUTHORITY_SNAPSHOT = "AUTHORITY_SNAPSHOT"
    MM_SNAPSHOT = "MM_SNAPSHOT"
    UNKNOWN = "UNKNOWN"


class LinkStrength(str, Enum):
    """How confidently two evidence nodes refer to the same thing.

    Deterministic ID linkage always outranks temporal inference.
    """

    DIRECT_ID = "DIRECT_ID"
    DERIVED_DETERMINISTIC = "DERIVED_DETERMINISTIC"
    TEMPORAL_CORRELATION = "TEMPORAL_CORRELATION"
    AMBIGUOUS = "AMBIGUOUS"
    UNLINKED = "UNLINKED"


class TraceCompleteness(str, Enum):
    """Evidence quality of an assembled trace."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    AMBIGUOUS = "AMBIGUOUS"
    UNAVAILABLE = "UNAVAILABLE"


class NoTraceKind(str, Enum):
    """Why a decision did not result in a fill.  These are NOT interchangeable."""

    NO_TRADE_DECISION = "NO_TRADE_DECISION"
    MISSING_TRACE_DATA = "MISSING_TRACE_DATA"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"


@dataclass(frozen=True)
class Provenance:
    """Where a piece of trace evidence came from."""

    source_subsystem: SourceSubsystem
    source_type: str
    source_identifier: str
    timestamp: Optional[str] = None
    linkage_method: str = "EVIDENCE_REFERENCE"
    confidence: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceSubsystem": self.source_subsystem.value,
            "sourceType": self.source_type,
            "sourceIdentifier": self.source_identifier,
            "timestamp": self.timestamp,
            "linkageMethod": self.linkage_method,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class TraceReasonCode:
    """A preserved original reason code plus optional read-only classification.

    Reason codes are never rewritten into free-form language.  The optional
    ``meaning``/``category`` come from the D-1 Knowledge Core read-only catalog
    whenever the code is catalogued; otherwise they remain ``None``.
    """

    code: str
    subsystem: SourceSubsystem
    timestamp: Optional[str] = None
    source_reference: Optional[str] = None
    category: Optional[str] = None
    meaning: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "subsystem": self.subsystem.value,
            "timestamp": self.timestamp,
            "sourceReference": self.source_reference,
            "category": self.category,
            "meaning": self.meaning,
        }


@dataclass(frozen=True)
class TraceNode:
    """A single typed, provenance-bearing piece of trading evidence."""

    node_id: str
    node_type: TraceNodeType
    timestamp: Optional[str]
    symbol: Optional[str]
    mode: Optional[str]
    status: str
    provenance: Provenance
    identity: Mapping[str, Any] = field(default_factory=dict)
    reason_codes: tuple[TraceReasonCode, ...] = field(default_factory=tuple)
    data: Mapping[str, Any] = field(default_factory=dict)
    no_trade_kind: Optional[NoTraceKind] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "nodeType": self.node_type.value,
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "mode": self.mode,
            "status": self.status,
            "provenance": self.provenance.to_dict(),
            "identity": dict(self.identity),
            "reasonCodes": [item.to_dict() for item in self.reason_codes],
            "data": dict(self.data),
            "noTradeKind": self.no_trade_kind.value if self.no_trade_kind else None,
        }


@dataclass(frozen=True)
class TraceLink:
    """A typed link between two trace evidence nodes."""

    source_id: str
    target_id: str
    strength: LinkStrength
    method: str
    confidence: Optional[str] = None
    evidence_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "targetId": self.target_id,
            "strength": self.strength.value,
            "method": self.method,
            "confidence": self.confidence,
            "evidenceId": self.evidence_id,
        }


@dataclass(frozen=True)
class UnifiedTradingTrace:
    """A typed, assembled, provider-neutral representation of one decision span.

    Missing evidence stays explicit: absent nodes are ``None``/empty and
    ``completeness`` reflects the actual evidence quality.
    """

    trace_id: str
    symbol: Optional[str]
    mode: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    completeness: TraceCompleteness
    market_observation: Optional[TraceNode] = None
    decision: Optional[TraceNode] = None
    no_trade: Optional[TraceNode] = None
    rejection: Optional[TraceNode] = None
    execution_attempt: Optional[TraceNode] = None
    orders: tuple[TraceNode, ...] = field(default_factory=tuple)
    fills: tuple[TraceNode, ...] = field(default_factory=tuple)
    position: Optional[TraceNode] = None
    exit: Optional[TraceNode] = None
    trade_result: Optional[TraceNode] = None
    runtime_evidence: tuple[TraceNode, ...] = field(default_factory=tuple)
    authority_evidence: tuple[TraceNode, ...] = field(default_factory=tuple)
    money_management_evidence: tuple[TraceNode, ...] = field(default_factory=tuple)
    reason_codes: tuple[TraceReasonCode, ...] = field(default_factory=tuple)
    source_references: tuple[Provenance, ...] = field(default_factory=tuple)
    nodes: tuple[TraceNode, ...] = field(default_factory=tuple)
    links: tuple[TraceLink, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        def node(value: Optional[TraceNode]) -> Optional[dict[str, Any]]:
            return value.to_dict() if value is not None else None

        return {
            "traceId": self.trace_id,
            "symbol": self.symbol,
            "mode": self.mode,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "completeness": self.completeness.value,
            "marketObservation": node(self.market_observation),
            "decision": node(self.decision),
            "noTrade": node(self.no_trade),
            "rejection": node(self.rejection),
            "executionAttempt": node(self.execution_attempt),
            "orders": [item.to_dict() for item in self.orders],
            "fills": [item.to_dict() for item in self.fills],
            "position": node(self.position),
            "exit": node(self.exit),
            "tradeResult": node(self.trade_result),
            "runtimeEvidence": [item.to_dict() for item in self.runtime_evidence],
            "authorityEvidence": [item.to_dict() for item in self.authority_evidence],
            "moneyManagementEvidence": [
                item.to_dict() for item in self.money_management_evidence
            ],
            "reasonCodes": [item.to_dict() for item in self.reason_codes],
            "sourceReferences": [
                item.to_dict() for item in self.source_references
            ],
            "nodes": [item.to_dict() for item in self.nodes],
            "links": [item.to_dict() for item in self.links],
            "warnings": list(self.warnings),
        }


class TraceEvidenceSource(Protocol):
    """A read-only source of existing authoritative trace events."""

    def events(self, trace_id: str) -> list[dict[str, Any]]:
        ...

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        ...


class TradingTraceStoreSource:
    """Adapt the existing authoritative ``TradingTraceStore`` to the protocol.

    This is a VIEW over the authoritative trace store; it never mutates it and
    never creates a parallel source of truth.
    """

    def __init__(self, store: TradingTraceStore):
        self._store = store

    def events(self, trace_id: str) -> list[dict[str, Any]]:
        return self._store.events(trace_id)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._store.recent(limit)


class StaticTraceEvidenceSource:
    """An in-memory, deterministic evidence source for tests and adapters."""

    def __init__(self, events: Iterable[Mapping[str, Any]]):
        self._events: list[dict[str, Any]] = [
            dict(item) for item in events if item.get("traceId")
        ]

    def events(self, trace_id: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self._events if item["traceId"] == trace_id]

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        raise TypeError("static sources are per-trace")


_TERMINAL_STAGE_INDEX = 99

# Strategy/decision stage statuses that represent a deliberate no-trade.
_HOLD_STATUSES = {"HOLD", "SUPPRESSED", "NO_TRADE", "NEUTRAL"}
# Execution stage statuses that represent a successful fill.
_FILL_STATUSES = {"PAPER_FILLED", "FILLED", "EXECUTED"}
# Statuses represented as an execution failure (NOT a no-trade).
_EXEC_FAILURES = {"FAILED", "REJECTED", "ERROR", "EXCHANGE_REJECTED"}
# Statuses represented as a rejection by an entry gate.
_GATE_BLOCKS = {"BLOCKED", "REJECTED", "DENIED", "FORBIDDEN"}
_GATE_ALLOWS = {"ALLOW", "ALLOWED", "PERMITTED"}

_SUPPRESSION_REASON_CODES = frozenset({
    "LIQUIDITY_INSTABILITY", "MOMENTUM_WARMUP", "DIRECTION_CONFLICT",
    "DIRECTION_NOT_CONFIRMED", "LOW_COMPOSITE_SCORE", "CONFLICTING_MOMENTUM",
    "WEAK_EDGE", "LOW_CONFIDENCE", "STRATEGY_HOLD", "STRATEGY_STATE_INVALID",
})


_SUBSYSTEM_TO_DOMAIN = {
    SourceSubsystem.MARKET: "MARKET",
    SourceSubsystem.STRATEGY: "TRADING_DECISION",
    SourceSubsystem.MONEY_MANAGEMENT: "MONEY_MANAGEMENT",
    SourceSubsystem.EXECUTION: "EXECUTION",
    SourceSubsystem.POSITION: "POSITION",
    SourceSubsystem.RUNTIME: "RUNTIME_HEALTH",
    SourceSubsystem.GOVERNANCE: "GOVERNANCE",
    SourceSubsystem.SUPERVISOR: "SUPERVISOR",
    SourceSubsystem.UNKNOWN: None,
}


def _utc(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _event_subsystem(stage: str) -> SourceSubsystem:
    if stage == "MARKET":
        return SourceSubsystem.MARKET
    if stage == "STRATEGY":
        return SourceSubsystem.STRATEGY
    if stage == "AI":
        return SourceSubsystem.STRATEGY
    if stage in {"MONEY_MANAGEMENT", "MM"}:
        return SourceSubsystem.MONEY_MANAGEMENT
    if stage in {"GOVERNANCE", "AUTHORITY"}:
        return SourceSubsystem.GOVERNANCE
    if stage == "EXECUTION":
        return SourceSubsystem.EXECUTION
    if stage in {"POSITION", "RESULT", "HISTORY"}:
        return SourceSubsystem.POSITION
    return SourceSubsystem.RUNTIME


_IDENTITY_KEYS = (
    "rankingCycleId", "orderId", "exchangeOrderId", "positionId",
    "markerId", "tradeId", "decisionId", "fillId", "netPnL", "grossPnL",
)


def _identity_from_event(event: Mapping[str, Any]) -> dict[str, Any]:
    meta = dict(event.get("metadata") or {})
    return {key: meta[key] for key in _IDENTITY_KEYS if key in meta}


def _bound_metadata(event: Mapping[str, Any]) -> dict[str, Any]:
    meta = dict(event.get("metadata") or {})
    selected = {
        key: meta[key]
        for key in ("decisionInput", "order", "fill", "position", "trade")
        if key in meta
    }
    return sanitize_metadata(selected)


def build_provenance(
    event: Mapping[str, Any],
    *,
    stage: Optional[str] = None,
    linkage_method: str = "EVIDENCE_REFERENCE",
) -> Provenance:
    resolved = stage or str(event.get("stage") or "")
    return Provenance(
        source_subsystem=_event_subsystem(resolved),
        source_type=f"TRACE_EVENT:{resolved}",
        source_identifier=str(event.get("eventId") or ""),
        timestamp=_utc(event.get("timestamp")),
        linkage_method=linkage_method,
    )


class _EventNodeBuilder:
    """Build typed nodes from the existing authoritative decision-scoped events.

    The builder is pure: it never mutates input events and never records new
    evidence.
    """

    def __init__(self, nodes: list[TraceNode], index_counter: list[int]):
        self._nodes = nodes
        self._index_counter = index_counter

    def _next_index(self) -> int:
        value = self._index_counter[0]
        self._index_counter[0] += 1
        return value

    def build(
        self,
        event: Mapping[str, Any],
        node_type: TraceNodeType,
        *,
        no_trade_kind: Optional[NoTraceKind] = None,
    ) -> TraceNode:
        stage = str(event.get("stage") or "")
        index = self._next_index()
        node_id = f"{node_type.value.lower()}:{index}:{event.get('eventId') or index}"
        reason_code_value = event.get("reasonCode")
        reason_codes = ()
        if reason_code_value:
            reason_codes = (
                TraceReasonCode(
                    code=str(reason_code_value),
                    subsystem=_event_subsystem(stage),
                    timestamp=_utc(event.get("timestamp")),
                    source_reference=str(event.get("eventId") or ""),
                ),
            )
        node = TraceNode(
            node_id=node_id,
            node_type=node_type,
            timestamp=_utc(event.get("timestamp")),
            symbol=event.get("symbol"),
            mode=event.get("mode"),
            status=str(event.get("status") or ""),
            provenance=build_provenance(event, stage=stage),
            identity=_identity_from_event(event),
            reason_codes=reason_codes,
            data=_bound_metadata(event),
            no_trade_kind=no_trade_kind,
        )
        self._nodes.append(node)
        return node


class UnifiedTraceAssembler:
    """Assemble typed, provider-neutral unified traces from existing evidence.

    It is execution-neutral (it reads evidence; it does not run execution),
    non-mutating, deterministic and fail-safe: missing sources yield PARTIAL /
    AMBIGUOUS / UNAVAILABLE rather than fabricated evidence.
    """

    def __init__(
        self,
        source: Optional[TraceEvidenceSource] = None,
        *,
        reason_code_resolver: Optional[Any] = None,
    ):
        self._source = source or TradingTraceStoreSource(default_trace_store)
        self._resolver = reason_code_resolver

    def _resolve_reason(
        self, code: str, subsystem: SourceSubsystem
    ) -> tuple[Optional[str], Optional[str]]:
        if self._resolver is None:
            return None, None
        try:
            catalog = self._resolver
            if not callable(getattr(catalog, "lookup", None)):
                return None, None
            domain = _SUBSYSTEM_TO_DOMAIN.get(subsystem)
            records = catalog.lookup(code, domain) if domain else catalog.lookup(code)
            if not records and domain:
                # Fall back to an all-domain match for the same code.
                records = catalog.lookup(code)
            if records:
                first = records[0]
                return first.category, first.meaning
        except Exception:
            return None, None
        return None, None

    def assemble(self, trace_id: str) -> UnifiedTradingTrace:
        try:
            events = self._source.events(trace_id)
        except Exception:
            events = []
        if not events:
            return UnifiedTradingTrace(
                trace_id=trace_id, symbol=None, mode=None,
                started_at=None, ended_at=None,
                completeness=TraceCompleteness.UNAVAILABLE,
                warnings=("NO_AUTHORITATIVE_EVIDENCE",),
            )

        ordered = sorted(events, key=_event_sort_key)
        nodes: list[TraceNode] = []
        counter = [0]
        builder = _EventNodeBuilder(nodes, counter)
        by_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for event in ordered:
            by_stage[str(event.get("stage"))].append(event)

        warnings: list[str] = []

        # Index-stage node production -----------------------------------------
        market_observation = self._build_stage_node(
            by_stage.get("MARKET"), builder, TraceNodeType.MARKET_OBSERVATION
        )
        decision, no_trade, strategy_rejection = self._decision_nodes(
            by_stage.get("STRATEGY"), builder, warnings
        )
        mm_snapshot, mm_rejection = self._gate_nodes(
            by_stage.get("MONEY_MANAGEMENT"), builder,
            TraceNodeType.MM_SNAPSHOT, TraceNodeType.ENTRY_REJECTION,
        )
        authority_snapshot, governance_rejection = self._gate_nodes(
            by_stage.get("GOVERNANCE"), builder,
            TraceNodeType.AUTHORITY_SNAPSHOT, TraceNodeType.ENTRY_REJECTION,
        )
        runtime_snapshot = self._build_stage_node(
            by_stage.get("AI"), builder, TraceNodeType.RUNTIME_SNAPSHOT
        )
        execution_attempt, orders, fills = self._execution_nodes(
            by_stage.get("EXECUTION"), builder, warnings
        )
        position = self._build_stage_node(
            by_stage.get("POSITION"), builder, TraceNodeType.POSITION
        )
        exit_node = self._build_stage_last_node(
            by_stage.get("HISTORY"), builder, TraceNodeType.EXIT
        )
        trade_result = self._build_stage_last_node(
            by_stage.get("RESULT"), builder, TraceNodeType.TRADE_RESULT
        )
        rejection = self._pick_rejection(
            strategy_rejection, mm_rejection, governance_rejection
        )

        # Decision-spine links (all events share one traceId => DIRECT_ID).
        spine = [
            market_observation, decision, no_trade, rejection,
            execution_attempt, position, exit_node, trade_result,
        ]
        links: list[TraceLink] = []
        prior: Optional[TraceNode] = None
        for current in spine:
            if current is None:
                continue
            if prior is not None:
                links.append(
                    TraceLink(
                        source_id=prior.node_id, target_id=current.node_id,
                        strength=LinkStrength.DIRECT_ID, method="TRACE_ID",
                        evidence_id=trace_id,
                    )
                )
            prior = current

        # Order -> fill -> position identity linkage.
        for order in orders:
            target = position if position is not None else trade_result
            links.append(
                TraceLink(
                    source_id=order.node_id,
                    target_id=target.node_id if target is not None else order.node_id,
                    strength=(
                        LinkStrength.DIRECT_ID
                        if order.identity.get("orderId")
                        else LinkStrength.DERIVED_DETERMINISTIC
                    ),
                    method="ORDER_ID", evidence_id=trace_id,
                )
            )
        for fill in fills:
            target = position if position is not None else trade_result
            links.append(
                TraceLink(
                    source_id=fill.node_id,
                    target_id=target.node_id if target is not None else fill.node_id,
                    strength=(
                        LinkStrength.DIRECT_ID
                        if fill.identity.get("orderId") or fill.identity.get("fillId")
                        else LinkStrength.DERIVED_DETERMINISTIC
                    ),
                    method="FILL_ORDER_ID", evidence_id=trace_id,
                )
            )

        reason_codes = self._collect_reason_codes(nodes)
        source_references = _dedupe_provenance(
            node.provenance for node in nodes
        )

        completeness, completeness_warning = self._completeness(
            by_stage, decision, no_trade, rejection,
            execution_attempt, position, trade_result,
        )
        if completeness_warning:
            warnings.append(completeness_warning)

        first_event, last_event = ordered[0], ordered[-1]
        return UnifiedTradingTrace(
            trace_id=trace_id,
            symbol=first_event.get("symbol"),
            mode=first_event.get("mode"),
            started_at=_utc(first_event.get("timestamp")),
            ended_at=_utc(last_event.get("timestamp")),
            completeness=completeness,
            market_observation=market_observation,
            decision=decision,
            no_trade=no_trade,
            rejection=rejection,
            execution_attempt=execution_attempt,
            orders=tuple(orders),
            fills=tuple(fills),
            position=position,
            exit=exit_node,
            trade_result=trade_result,
            runtime_evidence=_optional_node_tuple(runtime_snapshot),
            authority_evidence=tuple(authority_snapshot),
            money_management_evidence=tuple(mm_snapshot),
            reason_codes=tuple(reason_codes),
            source_references=tuple(source_references),
            nodes=tuple(nodes),
            links=tuple(links),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    def _build_stage_node(
        self,
        events: Optional[Sequence[Mapping[str, Any]]],
        builder: _EventNodeBuilder,
        node_type: TraceNodeType,
    ) -> Optional[TraceNode]:
        if not events:
            return None
        return builder.build(events[0], node_type)

    def _build_stage_last_node(
        self,
        events: Optional[Sequence[Mapping[str, Any]]],
        builder: _EventNodeBuilder,
        node_type: TraceNodeType,
    ) -> Optional[TraceNode]:
        if not events:
            return None
        return builder.build(events[-1], node_type)

    def _decision_nodes(
        self,
        events: Sequence[Mapping[str, Any]],
        builder: _EventNodeBuilder,
        warnings: list[str],
    ) -> tuple[Optional[TraceNode], Optional[TraceNode], Optional[TraceNode]]:
        if not events:
            return None, None, None
        terminal = events[-1]
        status = str(terminal.get("status") or "").upper()
        reason = terminal.get("reasonCode")

        if status in _HOLD_STATUSES or (reason and reason in _SUPPRESSION_REASON_CODES):
            no_trade = builder.build(
                terminal, TraceNodeType.NO_TRADE,
                no_trade_kind=NoTraceKind.NO_TRADE_DECISION,
            )
            return None, no_trade, None

        if status in _GATE_BLOCKS:
            intent = builder.build(terminal, TraceNodeType.ENTRY_INTENT)
            return intent, None, intent

        if len(events) > 1:
            warnings.append("MULTIPLE_STRATEGY_EVENTS")
        decision = builder.build(terminal, TraceNodeType.DECISION)
        return decision, None, None

    def _gate_nodes(
        self,
        events: Optional[Sequence[Mapping[str, Any]]],
        builder: _EventNodeBuilder,
        snapshot_type: TraceNodeType,
        rejection_type: TraceNodeType,
    ) -> tuple[list[TraceNode], Optional[TraceNode]]:
        if not events:
            return [], None
        snapshots = [builder.build(item, snapshot_type) for item in events]
        terminal = events[-1]
        status = str(terminal.get("status") or "").upper()
        if status in _GATE_BLOCKS:
            rejection = builder.build(terminal, rejection_type)
            return snapshots, rejection
        return snapshots, None

    def _execution_nodes(
        self,
        events: Optional[Sequence[Mapping[str, Any]]],
        builder: _EventNodeBuilder,
        warnings: list[str],
    ) -> tuple[Optional[TraceNode], list[TraceNode], list[TraceNode]]:
        if not events:
            return None, [], []
        orders: list[TraceNode] = []
        fills: list[TraceNode] = []
        for event in events:
            meta = dict(event.get("metadata") or {})
            if meta.get("orderId") or meta.get("exchangeOrderId"):
                orders.append(builder.build(event, TraceNodeType.ORDER))
            if meta.get("fillId") or str(event.get("status") or "").upper() in _FILL_STATUSES:
                fills.append(builder.build(event, TraceNodeType.FILL))
        terminal = events[-1]
        status = str(terminal.get("status") or "").upper()
        no_trade_kind = (
            NoTraceKind.EXECUTION_FAILURE if status in _EXEC_FAILURES else None
        )
        attempt = builder.build(terminal, TraceNodeType.EXECUTION_ATTEMPT, no_trade_kind=no_trade_kind)
        if status in _EXEC_FAILURES:
            warnings.append("EXECUTION_FAILURE")
        return attempt, orders, fills

    def _pick_rejection(
        self,
        strategy_rejection: Optional[TraceNode],
        mm_rejection: Optional[TraceNode],
        governance_rejection: Optional[TraceNode],
    ) -> Optional[TraceNode]:
        if strategy_rejection is not None:
            return strategy_rejection
        if mm_rejection is not None:
            return mm_rejection
        if governance_rejection is not None:
            return governance_rejection
        return None

    def _collect_reason_codes(self, nodes: Sequence[TraceNode]) -> list[TraceReasonCode]:
        seen: dict[tuple[str, str], TraceReasonCode] = {}
        for node in nodes:
            for code in node.reason_codes:
                key = (code.code, code.subsystem.value)
                category, meaning = code.category, code.meaning
                if category is None or meaning is None:
                    category, meaning = self._resolve_reason(code.code, code.subsystem)
                seen[key] = TraceReasonCode(
                    code=code.code, subsystem=code.subsystem,
                    timestamp=code.timestamp,
                    source_reference=code.source_reference,
                    category=category, meaning=meaning,
                )
        return sorted(seen.values(), key=lambda item: (item.code, item.subsystem.value))

    def _completeness(
        self,
        by_stage: Mapping[str, list[dict[str, Any]]],
        decision: Optional[TraceNode],
        no_trade: Optional[TraceNode],
        rejection: Optional[TraceNode],
        execution_attempt: Optional[TraceNode],
        position: Optional[TraceNode],
        trade_result: Optional[TraceNode],
    ) -> tuple[TraceCompleteness, Optional[str]]:
        if no_trade is not None:
            if "RESULT" in by_stage:
                return TraceCompleteness.COMPLETE, None
            return TraceCompleteness.PARTIAL, "NO_TRADE_RESULT_MISSING"

        # Execution failures are evidence but not a complete trade.
        if (
            execution_attempt is not None
            and execution_attempt.no_trade_kind is NoTraceKind.EXECUTION_FAILURE
        ):
            return TraceCompleteness.PARTIAL, "EXECUTION_FAILURE"

        # Conflicting entry intents within the same decision span are ambiguous:
        # a single downstream order cannot be attributed to one decision.
        strategy_events = by_stage.get("STRATEGY") or []
        entry_directions = {
            str(event.get("status") or "").upper()
            for event in strategy_events
            if str(event.get("status") or "").upper() not in _HOLD_STATUSES
        }
        if len(entry_directions) > 1:
            return TraceCompleteness.AMBIGUOUS, "MULTIPLE_DECISION_CANDIDATES"

        # A clear entry-gate rejection is complete evidence of a block.
        if rejection is not None:
            return TraceCompleteness.COMPLETE, None

        if position is not None and trade_result is not None:
            return TraceCompleteness.COMPLETE, None

        if trade_result is not None:
            if position is None:
                return TraceCompleteness.PARTIAL, "POSITION_MISSING"
            return TraceCompleteness.COMPLETE, None

        if execution_attempt is not None and position is None:
            return TraceCompleteness.PARTIAL, "EXECUTION_TO_POSITION_MISSING"

        if decision is None and execution_attempt is None and position is None:
            return TraceCompleteness.PARTIAL, "EXPECTED_STAGE_MISSING"

        return TraceCompleteness.PARTIAL, "EXPECTED_STAGE_MISSING"


def _optional_node_tuple(node: Optional[TraceNode]) -> tuple[TraceNode, ...]:
    return (node,) if node is not None else ()


def _event_sort_key(event: Mapping[str, Any]) -> tuple[str, str, str]:
    stage_index = _stage_index(str(event.get("stage") or "UNKNOWN"))
    return (
        str(event.get("timestamp") or ""),
        str(stage_index),
        str(event.get("eventId") or ""),
    )


def _stage_index(stage: str) -> str:
    if stage in STAGES:
        return f"{STAGES.index(stage):02d}"
    return f"{_TERMINAL_STAGE_INDEX:02d}"


def _dedupe_provenance(items: Iterable[Provenance]) -> list[Provenance]:
    seen: dict[tuple[str, str, str], Provenance] = {}
    for item in items:
        key = (item.source_subsystem.value, item.source_type, item.source_identifier)
        if key not in seen:
            seen[key] = item
    return sorted(
        seen.values(),
        key=lambda item: (item.source_subsystem.value, item.source_type, item.source_identifier),
    )


def build_default_reason_catalog() -> Optional[Any]:
    """Return the D-1 Knowledge Core reason-code catalog, or None if unavailable.

    The catalog is read-only.  Failures degrade to ``None`` (no classification).
    """
    try:
        from backend.knowledge_core.reason_codes import ReasonCodeCatalog

        return ReasonCodeCatalog()
    except Exception:
        return None


def default_unified_trace_assembler() -> UnifiedTraceAssembler:
    """A provider-neutral assembler over the existing authoritative trace store."""
    return UnifiedTraceAssembler(
        TradingTraceStoreSource(default_trace_store),
        reason_code_resolver=build_default_reason_catalog(),
    )


def find_trace(trace_id: str) -> UnifiedTradingTrace:
    """Convenience read-only lookup of a single unified trace."""
    return default_unified_trace_assembler().assemble(trace_id)


def list_unified_traces(
    source: Optional[TraceEvidenceSource] = None,
    *,
    limit: int = 50,
) -> list[UnifiedTradingTrace]:
    """Bounded list of the most recent assembled unified traces."""
    evidence_source = source or TradingTraceStoreSource(default_trace_store)
    assembled_ids: list[str] = []
    try:
        traces = evidence_source.recent(max(1, min(limit, 200)))
    except Exception:
        traces = []
    for trace in traces:
        trace_id = trace.get("traceId") if isinstance(trace, Mapping) else None
        if trace_id:
            assembled_ids.append(str(trace_id))
    assembler = UnifiedTraceAssembler(evidence_source)
    return [assembler.assemble(trace_id) for trace_id in assembled_ids]
