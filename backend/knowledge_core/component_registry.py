"""Typed, read-only Component Registry.

Each entry describes an existing runtime/analytics component.  Descriptive
metadata only: it never grants authority and never mutates anything.  Unknown
fields remain ``None`` or empty; no missing contract is invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from ._base import freeze_mapping, stable_json
from .authority import AuthorityClass, SourceCategory, TruthLevel
from .domain import Domain
from .provenance import ProvenanceRecord

_SRC = SourceCategory.SOURCE_CODE
_RUNTIME = TruthLevel.CURRENT_SOURCE_RUNTIME


def _spec(path: str) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.CANONICAL_SPECIFICATION,
        source_category=SourceCategory.SPECIFICATION,
        source_reference=path,
        source_path=path,
        verified=True,
    )


@dataclass(frozen=True)
class ComponentRecord:
    """A single registered component.

    ``inputs`` / ``outputs`` / ``related_components`` / ``knowledge_sources``
    / ``forbidden_assumptions`` are descriptive metadata.  Empty tuple means
    "not enumerated / not known", never a permission.
    """

    component_id: str
    display_name: str
    domain: Domain
    purpose: str
    owner_module: str
    authority_class: AuthorityClass
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    runtime_source: Optional[str] = None
    canonical_api: tuple[str, ...] = ()
    freshness_policy: Optional[str] = None
    related_components: tuple[str, ...] = ()
    knowledge_sources: tuple[str, ...] = ()
    forbidden_assumptions: tuple[str, ...] = ()
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)


COMPONENT_RECORDS = (
    ComponentRecord(
        component_id="bot_manager",
        display_name="Bot Manager",
        domain=Domain.BOT,
        purpose="Manages bot lifecycle, runtime envelope and status aggregation.",
        owner_module="backend/bot_manager/bot_manager.py",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("config", "mode", "loop_state", "market_state"),
        outputs=("botState", "loopEnabled", "selectedMode", "dryRun", "marketReady"),
        runtime_source="backend.bot_manager.bot_manager.BotManager",
        canonical_api=("GET /api/bot/status", "POST /api/bot/loop/start", "POST /api/bot/loop/stop"),
        freshness_policy="DERIVED_SNAPSHOT",
        related_components=("execution_runtime", "governance_runtime", "market_feed"),
        knowledge_sources=("docs/00_CONSTITUTION/00_TradingAI_Constitution.md",),
        forbidden_assumptions=("Derived flags never override governance authority.",),
        provenance=_spec("backend/bot_manager/bot_manager.py"),
    ),
    ComponentRecord(
        component_id="bot_loop",
        display_name="Bot Loop",
        domain=Domain.LOOP,
        purpose="Periodic decision loop execution and running state (STOPPED/STARTING/RUNNING/STOPPING).",
        owner_module="backend/bot_manager/bot_manager.py",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("loopState", "loopEnabled"),
        outputs=("loopEnabled",),
        runtime_source="backend.bot_manager.bot_manager.BotManager",
        canonical_api=("POST /api/bot/loop/start", "POST /api/bot/loop/stop"),
        freshness_policy="DIRECT_STATE",
        related_components=("bot_manager", "execution_runtime", "governance_runtime"),
        provenance=_spec("backend/bot_manager/bot_manager.py"),
    ),
    ComponentRecord(
        component_id="governance_runtime",
        display_name="Governance Runtime",
        domain=Domain.GOVERNANCE,
        purpose="Operator-controlled execution master switch, mode, risk profile and session state.",
        owner_module="backend/runtime/governance_runtime.py",
        authority_class=AuthorityClass.GOVERNANCE_AUTHORITY,
        inputs=("execution_enabled", "mode", "risk_profile", "emergency_stop"),
        outputs=("executionEnabled", "mode", "riskProfile", "emergencyLocked"),
        runtime_source="backend.runtime.governance_runtime.governance_state",
        canonical_api=("GET /api/governance/status", "POST /api/governance/execution",
                       "POST /api/governance/mode", "POST /api/governance/risk-profile"),
        freshness_policy="DIRECT_STATE",
        related_components=("emergency", "execution_governance", "execution_runtime"),
        knowledge_sources=("docs/money_management/01_Money_Management_Master_Specification.md",),
        provenance=_spec("backend/runtime/governance_runtime.py"),
    ),
    ComponentRecord(
        component_id="emergency",
        display_name="Emergency",
        domain=Domain.EMERGENCY,
        purpose="Emergency-stop latch and transition state machine (READY/PROCESSING/LOCKED/ACTION_REQUIRED).",
        owner_module="backend/runtime/governance_runtime.py",
        authority_class=AuthorityClass.GOVERNANCE_AUTHORITY,
        inputs=("emergency_stop", "pending_orders", "position_state"),
        outputs=("emergencyLocked", "emergencyState"),
        runtime_source="backend.runtime.governance_runtime.build_emergency_status",
        canonical_api=("GET /api/governance/status", "POST /api/governance/emergency-stop",
                       "POST /api/governance/emergency/unlock"),
        freshness_policy="DIRECT_STATE",
        related_components=("governance_runtime", "execution_runtime", "orders"),
        provenance=_spec("backend/runtime/governance_runtime.py"),
    ),
    ComponentRecord(
        component_id="execution_runtime",
        display_name="Execution Runtime",
        domain=Domain.EXECUTION,
        purpose="Evaluates permission and executes an allowed decision (simulated or real).",
        owner_module="backend/runtime/ExecutionRuntime.py",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("strategy_decision", "governance_permission", "mm_gate"),
        outputs=("executionStatus", "orderSubmitted", "reasonCode"),
        runtime_source="backend.runtime.ExecutionRuntime.ExecutionRuntime",
        canonical_api=("GET /api/bot/status (nested)", "GET /api/trading-trace/{trace_id}"),
        freshness_policy="PER_DECISION",
        related_components=("execution_governance", "money_management", "strategy", "orders"),
        knowledge_sources=("docs/money_management/01_Money_Management_Master_Specification.md",),
        forbidden_assumptions=("Never executes unless governance + MM allow.",),
        provenance=_spec("backend/runtime/ExecutionRuntime.py"),
    ),
    ComponentRecord(
        component_id="execution_governance",
        display_name="Execution Governance",
        domain=Domain.EXECUTION,
        purpose="Deterministic execution-level gate (strategy suppression, emergency, cooldown, exposure, pacing).",
        owner_module="backend/execution/ExecutionGovernance.py",
        authority_class=AuthorityClass.GOVERNANCE_AUTHORITY,
        inputs=("strategy_state", "cooldown", "exposure", "emergency", "pacing"),
        outputs=("executionAllowed", "reasonCode"),
        runtime_source="backend.execution.ExecutionGovernance.ExecutionGovernance",
        canonical_api=(),
        freshness_policy="PER_DECISION",
        related_components=("execution_runtime", "governance_runtime"),
        provenance=_spec("backend/execution/ExecutionGovernance.py"),
    ),
    ComponentRecord(
        component_id="exchange_trading",
        display_name="Exchange Trading",
        domain=Domain.EXECUTION,
        purpose="Exchange-specific order entry executed only when all authorities permit.",
        owner_module="backend/execution/kucoin_trade.py",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("order_intent", "order_authority"),
        outputs=("orderId", "errorCode"),
        runtime_source="backend.execution.kucoin_trade.KucoinTrade",
        canonical_api=(),
        freshness_policy="PER_ORDER",
        related_components=("orders", "execution_runtime"),
        forbidden_assumptions=("Real order entry requires realOrderAllowed + executionEntryAllowed + liveOrderEntryAllowed.",),
        provenance=_spec("backend/execution/kucoin_trade.py"),
    ),
    ComponentRecord(
        component_id="strategy",
        display_name="Microstructure Edge Strategy",
        domain=Domain.TRADING_DECISION,
        purpose="Produces direction / hold / suppress decision plus hard gate and condition records.",
        owner_module="backend/strategy/MicrostructureEdgeStrategy.py",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("features", "market", "parameters"),
        outputs=("strategyDecision", "hardGateResults", "suppressionReason", "conditionCodes"),
        runtime_source="backend.strategy.MicrostructureEdgeStrategy.MicrostructureEdgeStrategy",
        canonical_api=(),
        freshness_policy="PER_DECISION",
        related_components=("execution_runtime", "money_management", "execution_governance"),
        forbidden_assumptions=("A decision is not an instruction to execute.",),
        provenance=_spec("backend/strategy/MicrostructureEdgeStrategy.py"),
    ),
    ComponentRecord(
        component_id="money_management",
        display_name="Money Management",
        domain=Domain.MONEY_MANAGEMENT,
        purpose="Risk state, capital eligibility and execution entry gating. Approve / size-reduce / block.",
        owner_module="backend/money_management/",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("equity", "loss_state", "position", "periods"),
        outputs=("riskState", "executionEntryAllowed", "blockReasons", "recommendedAction"),
        runtime_source="backend.money_management.loss_http_api.MoneyManagementHttpBoundary",
        canonical_api=("GET /api/money-management/status", "GET /api/money-management/configuration"),
        freshness_policy="PER_DECISION_RUNTIME_METRICS",
        related_components=("execution_runtime", "governance_runtime", "position", "auto_market_selection"),
        knowledge_sources=("docs/money_management/01_Money_Management_Master_Specification.md",
                           "docs/money_management/01_Money_Management_Specification_Additions_v1.1.md"),
        forbidden_assumptions=("MM does not change direction or create entries from HOLD.",),
        provenance=_spec("backend/money_management/loss_http_api.py"),
    ),
    ComponentRecord(
        component_id="mm_loss_runtime",
        display_name="MM Loss Runtime",
        domain=Domain.MONEY_MANAGEMENT,
        purpose="Loss accounting, persistence, governance projection and runtime reconciliation.",
        owner_module="backend/money_management/loss_*.py",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("loss_state", "periods", "cash_flow"),
        outputs=("executionEntryAllowed", "reasonCodes", "recoveryState"),
        runtime_source="backend.money_management.loss_loss_? (see loss_http_api)",
        canonical_api=(),
        freshness_policy="RUNTIME_METRICS",
        related_components=("money_management", "execution_runtime"),
        provenance=ProvenanceRecord(
            truth_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
            source_category=SourceCategory.SOURCE_CODE,
            source_reference="backend/money_management/loss_execution_guard.py",
            source_path="backend/money_management/loss_execution_guard.py",
            notes="Huge loss_* namespace; authoritative entry gate lives here.",
        ),
    ),
    ComponentRecord(
        component_id="market_feed",
        display_name="Market Feed",
        domain=Domain.MARKET,
        purpose="Market data feed, universe and per-market snapshot; data authority only.",
        owner_module="backend/market/",
        authority_class=AuthorityClass.OBSERVATION_READ_ONLY,
        inputs=("exchange", "symbol"),
        outputs=("marketReady", "marketStale", "dataQuality", "syncState"),
        runtime_source="backend.bot_manager.bot_manager.BotManager._build_market_snapshot",
        canonical_api=("GET /api/bot/status (nested)",),
        freshness_policy="DATA_STALENESS",
        related_components=("bot_manager", "runtime_health", "strategy"),
        forbidden_assumptions=("Market data never grants execution authority.",),
        provenance=_spec("backend/market/kucoin_futures_public.py"),
    ),
    ComponentRecord(
        component_id="auto_market_selection",
        display_name="Auto Market Selection",
        domain=Domain.AUTO_TRADE,
        purpose="Candidate scan, ranking, safe switch, live readiness and auto cycle lifecycle.",
        owner_module="backend/auto_market_selection/",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("universe", "mms", "eligibility", "live_readiness"),
        outputs=("switchState", "lifecycleState", "reasonCodes"),
        runtime_source="backend.auto_market_selection.auto_selection_runtime.AutoSelectionCycleStatus",
        canonical_api=("GET /api/bot/status (nested)",),
        freshness_policy="PER_CYCLE",
        related_components=("money_management", "governance_runtime", "strategy", "position"),
        forbidden_assumptions=("Auto switch never bypasses MM / governance / emergency gates.",),
        provenance=_spec("backend/auto_market_selection/lifecycle.py"),
    ),
    ComponentRecord(
        component_id="position",
        display_name="Position",
        domain=Domain.POSITION,
        purpose="Position sizing, risk evaluation and open-position state.",
        owner_module="backend/core/risk/position_sizing.py",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("equity", "stop", "entry", "risk_budget"),
        outputs=("positionState", "size", "reasonCode"),
        runtime_source="backend.core.risk.position_sizing.calculate_qty",
        canonical_api=(),
        freshness_policy="PER_DECISION",
        related_components=("money_management", "orders", "execution_runtime"),
        provenance=_spec("backend/core/risk/position_sizing.py"),
    ),
    ComponentRecord(
        component_id="orders",
        display_name="Orders",
        domain=Domain.ORDERS,
        purpose="Concrete order intents, paper markers and live order state.",
        owner_module="backend/market/paper_execution_markers.py",
        authority_class=AuthorityClass.EXECUTION_AUTHORITY,
        inputs=("order_intent", "marker"),
        outputs=("orderState", "pendingOrderState"),
        runtime_source="backend.market.paper_execution_markers",
        canonical_api=(),
        freshness_policy="PER_ORDER",
        related_components=("execution_runtime", "exchange_trading", "position"),
        provenance=_spec("backend/market/paper_execution_markers.py"),
    ),
    ComponentRecord(
        component_id="runtime_health",
        display_name="Runtime Health",
        domain=Domain.RUNTIME_HEALTH,
        purpose="Read-only health and blocking-stage snapshot of the runtime pipeline.",
        owner_module="backend/runtime/runtime_health_snapshot.py",
        authority_class=AuthorityClass.OBSERVATION_READ_ONLY,
        inputs=("runtime", "market", "orderbook"),
        outputs=("runtimeHealthy", "blockingStage", "reasonCode"),
        runtime_source="backend.runtime.runtime_health_snapshot",
        canonical_api=(),
        freshness_policy="SNAPSHOT",
        related_components=("bot_manager", "market_feed", "trading_trace"),
        forbidden_assumptions=("Health observation never gates trading by itself.",),
        provenance=_spec("backend/runtime/runtime_health_snapshot.py"),
    ),
    ComponentRecord(
        component_id="trading_trace",
        display_name="Trading E2E Trace",
        domain=Domain.TRADING_TRACE,
        purpose="Decision-scoped E2E trace recording; diagnostic only.",
        owner_module="backend/runtime/trading_trace.py",
        authority_class=AuthorityClass.RECORDING_AUTHORITY,
        inputs=("stage_events",),
        outputs=("classification", "primaryReason", "failurePoint"),
        runtime_source="backend.runtime.trading_trace.TradingTraceStore",
        canonical_api=("GET /api/trading-trace/recent", "GET /api/trading-trace/session",
                       "GET /api/trading-trace/{trace_id}"),
        freshness_policy="APPEND_ONLY",
        related_components=("execution_runtime", "strategy", "money_management", "governance_runtime"),
        forbidden_assumptions=("Tracing never affects trading authority and never fails closed the trade path.",),
        provenance=_spec("backend/runtime/trading_trace.py"),
    ),
    ComponentRecord(
        component_id="ai_advisor",
        display_name="AI Advisor",
        domain=Domain.AI_ADVISOR,
        purpose="Research / analysis partner. Read-only; no execution or governance override.",
        owner_module="backend/ai_advisor/",
        authority_class=AuthorityClass.RESEARCH_READ_ONLY,
        inputs=("sanitized_runtime", "approved_specifications"),
        outputs=("analysis", "response"),
        runtime_source="backend.ai_advisor.browser_gateway",
        canonical_api=("GET /api/ai-advisor/runtime", "POST /api/ai-advisor/advice"),
        freshness_policy="READ_ONLY",
        related_components=("supervisor", "money_management", "trading_trace"),
        knowledge_sources=("docs/ai_advisor/01_AI_Advisor_Master_Specification.md",
                           "docs/00_CONSTITUTION/00_TradingAI_Constitution.md"),
        forbidden_assumptions=("AI Advisor does not trade and does not override governance.",),
        provenance=_spec("docs/ai_advisor/01_AI_Advisor_Master_Specification.md"),
    ),
    ComponentRecord(
        component_id="supervisor",
        display_name="Supervisor",
        domain=Domain.SUPERVISOR,
        purpose="Oversight layer (Master + MM). Initially SHADOW; explains, never controls.",
        owner_module="backend/supervisor/",
        authority_class=AuthorityClass.OBSERVATION_READ_ONLY,
        inputs=("runtime_snapshot", "mm_assessment"),
        outputs=("shadowDecision", "shadowAssessment", "posture"),
        runtime_source="backend.supervisor.runtime_snapshot_adapter.ReadOnlySupervisorSnapshot",
        canonical_api=("GET /api/supervisor/snapshot",),
        freshness_policy="SHADOW_READ_ONLY",
        related_components=("ai_advisor", "money_management", "governance_runtime"),
        knowledge_sources=("docs/SUPERVISOR/01_SUPERVISOR_Master_Specification.md",),
        forbidden_assumptions=("Supervisor SHADOW never changes orders/runtime; grantsExecutionAuthority is False.",),
        provenance=_spec("docs/SUPERVISOR/01_SUPERVISOR_Master_Specification.md"),
    ),
    ComponentRecord(
        component_id="market_intelligence",
        display_name="Market Intelligence",
        domain=Domain.MARKET_INTELLIGENCE,
        purpose="Read-only replay / decision-railway presentation layer over MARKET + TRADING_TRACE.",
        owner_module="frontend (market_intelligence) + backend/market + backend/runtime/trading_trace.py",
        authority_class=AuthorityClass.OBSERVATION_READ_ONLY,
        inputs=("market_replay", "decision_railway", "trace"),
        outputs=("view", "dataQuality"),
        runtime_source=None,
        canonical_api=(),
        freshness_policy="READ_ONLY_RENDER",
        related_components=("market_feed", "trading_trace", "strategy"),
        knowledge_sources=("docs/market_intelligence/02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md",),
        forbidden_assumptions=("Market Intelligence is read-only; it holds no trading operation.",),
        provenance=_spec("docs/market_intelligence/02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md"),
    ),
)


class ComponentRegistry:
    """Immutable, read-only registry of described components.

    No mutation or action method exists.  ``consumer`` code may only read.
    """

    def __init__(self, records: tuple[ComponentRecord, ...] = COMPONENT_RECORDS) -> None:
        self._by_id: dict[str, ComponentRecord] = {}
        for record in records:
            if record.component_id in self._by_id:
                raise ValueError(f"duplicate component_id: {record.component_id}")
            self._by_id[record.component_id] = record
        self._by_id = freeze_mapping(self._by_id)
        self._by_domain: dict[str, tuple[ComponentRecord, ...]] = {}
        grouped: dict[str, list[ComponentRecord]] = {}
        for record in records:
            grouped.setdefault(record.domain.value, []).append(record)
        for domain_key in sorted(grouped):
            domain_records = tuple(sorted(grouped[domain_key], key=lambda r: r.component_id))
            self._by_domain[domain_key] = domain_records
        self._by_domain = freeze_mapping(self._by_domain)
        self._records = tuple(sorted(records, key=lambda r: r.component_id))

    @property
    def entries(self) -> tuple[ComponentRecord, ...]:
        return self._records

    def get(self, component_id: str) -> ComponentRecord:
        return self._by_id[component_id]

    def by_domain(self, domain: Domain | str) -> tuple[ComponentRecord, ...]:
        key = domain if isinstance(domain, str) else domain.value
        return self._by_domain[key]

    def __contains__(self, component_id: str) -> bool:
        return component_id in self._by_id

    def stable_json(self) -> str:
        return stable_json(self._records)
