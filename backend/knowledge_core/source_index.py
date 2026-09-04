"""Deterministic Source Index.

The Source Index answers questions such as "what produces botState?", "what
is the authoritative source for governance mode?", "where does MM status
originate?" and "what API exposes this information?".  It is a static,
deterministic registry; it does not read source files or runtime state on
demand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from ._base import freeze_mapping, stable_json
from .authority import SourceCategory, TruthLevel

_SOURCE = SourceCategory.SOURCE_CODE
_RUNTIME_CAT = SourceCategory.RUNTIME
_API = SourceCategory.API
_CONTRACT = SourceCategory.CONTRACT
_SPEC = SourceCategory.SPECIFICATION


@dataclass(frozen=True)
class SourceIndexRecord:
    """A single provenance-backed source record for a concept.

    ``concept`` is the question the record answers.  Unknown/missing fields
    remain ``None`` / empty.
    """

    concept: str
    source_type: SourceCategory
    source_reference: str
    symbol: Optional[str] = None
    authority_level: TruthLevel = TruthLevel.CURRENT_SOURCE_RUNTIME
    consumer: Optional[str] = None
    notes: str = ""
    source_path: Optional[str] = None


SOURCE_INDEX_RECORDS = (
    SourceIndexRecord(
        concept="botState",
        source_type=_SOURCE,
        source_reference="backend/bot_manager/bot_manager.py:10468",
        symbol="BotManager.get_result()['botState']",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="AI Advisor runtime_reader / Supervisor snapshot_builder",
        source_path="backend/bot_manager/bot_manager.py",
    ),
    SourceIndexRecord(
        concept="botState",
        source_type=_API,
        source_reference="GET /api/bot/status",
        symbol="StatusResponse.botState",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="browser / Monitor",
    ),
    SourceIndexRecord(
        concept="governance-mode",
        source_type=_RUNTIME_CAT,
        source_reference="backend/runtime/governance_runtime.py:14",
        symbol="governance_state['mode']",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="Supervisor snapshot_builder (mode conflict check)",
        notes="Independent from bot selectedMode and backend.config.TRADE_MODE.",
        source_path="backend/runtime/governance_runtime.py",
    ),
    SourceIndexRecord(
        concept="governance-mode",
        source_type=_API,
        source_reference="GET /api/governance/status",
        symbol="POST /api/governance/mode",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="governance admin UI",
    ),
    SourceIndexRecord(
        concept="execution-enabled",
        source_type=_SOURCE,
        source_reference="backend/runtime/governance_runtime.py:12",
        symbol="governance_state['execution_enabled']",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="ExecutionRuntime.evaluate_execution_permission / bot live readiness",
        notes="Operator-written master switch; blocks EXECUTION_DISABLED.",
        source_path="backend/runtime/governance_runtime.py",
    ),
    SourceIndexRecord(
        concept="execution-entry-allowed (runtime authority)",
        source_type=_SOURCE,
        source_reference="backend/money_management/loss_http_api.py:1199-1354",
        symbol="MoneyManagementStatusResponse.executionEntryAllowed",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="ExecutionRuntime / Supervisor snapshot (moneyManagement.executionEntryAllowed)",
        notes="The authoritative per-decision MM entry gate (ALLOW/BLOCK/RECOVERY_REQUIRED).",
        source_path="backend/money_management/loss_http_api.py",
    ),
    SourceIndexRecord(
        concept="execution-entry-allowed (runtime authority)",
        source_type=_API,
        source_reference="GET /api/money-management/status",
        symbol="MoneyManagementHttpBoundary.get_status()",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="Money Management UI / Supervisor",
    ),
    SourceIndexRecord(
        concept="execution-entry-allowed (config arming flag)",
        source_type=_CONTRACT,
        source_reference="backend/bot_manager/bot_manager.py:546,3177",
        symbol="config['executionEntryAllowed']",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="StatusResponse.executionEntryAllowed",
        notes="Separate, disarmed config flag; NOT the authoritative runtime decision source.",
        source_path="backend/bot_manager/bot_manager.py",
    ),
    SourceIndexRecord(
        concept="live-order-entry-allowed",
        source_type=_CONTRACT,
        source_reference="backend/bot_manager/bot_manager.py:545,3175",
        symbol="config['liveOrderEntryAllowed']",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="set_execution_enabled gate / StatusResponse.liveOrderEntryAllowed",
        notes="Disarmed (False) by the backend; a locked config arming flag.",
        source_path="backend/bot_manager/bot_manager.py",
    ),
    SourceIndexRecord(
        concept="live-order-entry-allowed",
        source_type=_SPEC,
        source_reference="docs/Liveボタンの仕様書TradingAI_LIVE_Usage_Conditions_20260902.md",
        authority_level=TruthLevel.CANONICAL_SPECIFICATION,
        consumer="3 order authorities: realOrderAllowed / executionEntryAllowed / liveOrderEntryAllowed",
        notes="All three default DISARMED and all true only under explicit per-order authority.",
        source_path="docs/Liveボタンの仕様書TradingAI_LIVE_Usage_Conditions_20260902.md",
    ),
    SourceIndexRecord(
        concept="real-order-allowed",
        source_type=_SOURCE,
        source_reference="backend/bot_manager/bot_manager.py:10118-1430",
        symbol="bot_manager.live_readiness['realOrderAllowed']",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="AI Advisor runtime_reader / Supervisor snapshot (attenuated)",
        notes="Never set directly true; fail-closed AND-projection of all gates.",
        source_path="backend/bot_manager/bot_manager.py",
    ),
    SourceIndexRecord(
        concept="real-order-allowed",
        source_type=_SOURCE,
        source_reference="backend/ai_advisor/runtime_reader.py:74-94",
        symbol="runtime_reader._real_order_allowed",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="AI Advisor runtime scalar snapshot",
        notes="Recomputed as AND of mode==LIVE, not dry-run, ALLOW_LIVE, TRADE_MODE live, engine checks.",
        source_path="backend/ai_advisor/runtime_reader.py",
    ),
    SourceIndexRecord(
        concept="mm-status",
        source_type=_SOURCE,
        source_reference="backend/money_management/loss_http_api.py:1017",
        symbol="MoneyManagementHttpBoundary.get_status()",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="GET /api/money-management/status & Supervisor MM snapshot",
        notes="RiskState from backend/money_management/enums.py RiskState.",
        source_path="backend/money_management/loss_http_api.py",
    ),
    SourceIndexRecord(
        concept="mm-risk-state",
        source_type=_CONTRACT,
        source_reference="backend/money_management/enums.py:8",
        symbol="RiskState",
        authority_level=TruthLevel.CANONICAL_SPECIFICATION,
        consumer="MM decision / Supervisor / Advisor",
        notes="NORMAL/CAUTION/DEFENSIVE/LOCKED/RECOVERY_25/RECOVERY_50.",
        source_path="backend/money_management/enums.py",
    ),
    SourceIndexRecord(
        concept="trading-e2e-trace",
        source_type=_SOURCE,
        source_reference="backend/runtime/trading_trace.py:252",
        symbol="TradingTraceStore / safe_record / trace_store",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="Market Intelligence railway + GET /api/trading-trace/*",
        notes="Diagnostic only; never affects trading authority.",
        source_path="backend/runtime/trading_trace.py",
    ),
    SourceIndexRecord(
        concept="trading-e2e-trace",
        source_type=_API,
        source_reference="GET /api/trading-trace/recent|session|{trace_id}",
        symbol="backend/api/trading_trace.py",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="Market Intelligence / monitoring",
    ),
    SourceIndexRecord(
        concept="emergency-state",
        source_type=_SOURCE,
        source_reference="backend/runtime/governance_runtime.py:41-49",
        symbol="build_emergency_status / EMERGENCY_* constants",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="bot status / Supervisor snapshot",
        notes="Values READY/PROCESSING/LOCKED/ACTION_REQUIRED; schema default 'UNLOCKED' is stale.",
        source_path="backend/runtime/governance_runtime.py",
    ),
    SourceIndexRecord(
        concept="paper-bootstrap-status",
        source_type=_SOURCE,
        source_reference="backend/bot_manager/bot_manager.py:10774",
        symbol="bot_manager.paperBootstrapStatus",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="StatusResponse.paperBootstrapStatus",
        notes="UNAVAILABLE/READY/BLOCKED descriptor for stopped-PAPER durable snapshot restart.",
        source_path="backend/bot_manager/bot_manager.py",
    ),
    SourceIndexRecord(
        concept="market-ready",
        source_type=_SOURCE,
        source_reference="backend/bot_manager/bot_manager.py:10356",
        symbol="BotManager.market_ready",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="StatusResponse.marketReady / Supervisor market snapshot",
        source_path="backend/bot_manager/bot_manager.py",
    ),
    SourceIndexRecord(
        concept="market-stale",
        source_type=_SOURCE,
        source_reference="backend/bot_manager/bot_manager.py:10358",
        symbol="BotManager._build_market_snapshot market_stale",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="StatusResponse.marketStale / Supervisor market snapshot",
        source_path="backend/bot_manager/bot_manager.py",
    ),
    SourceIndexRecord(
        concept="supervisor-snapshot",
        source_type=_CONTRACT,
        source_reference="backend/supervisor/contracts.py:312",
        symbol="ReadOnlySupervisorSnapshot",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="Supervisor shadow decision",
        notes="READ-ONLY; grantsExecutionAuthority is False.",
        source_path="backend/supervisor/contracts.py",
    ),
    SourceIndexRecord(
        concept="supervisor-snapshot",
        source_type=_API,
        source_reference="GET /api/supervisor/snapshot",
        symbol="backend/api/supervisor.py",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="Supervisor UI / audit",
    ),
    SourceIndexRecord(
        concept="supervisor-mm-assessment",
        source_type=_CONTRACT,
        source_reference="backend/supervisor/contracts.py:154",
        symbol="MMSupervisorAssessment",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="Master Supervisor decision",
        notes="SHADOW only; grantsExecutionAuthority is False.",
        source_path="backend/supervisor/contracts.py",
    ),
    SourceIndexRecord(
        concept="knowledge-allowlist-advisor",
        source_type=_SOURCE,
        source_reference="backend/ai_advisor/authoritative_knowledge.py",
        symbol="production_knowledge_manifest / load_authoritative_specifications",
        authority_level=TruthLevel.CANONICAL_SPECIFICATION,
        consumer="AI Advisor browser gateway",
        notes="Hash-pinned manifest verifying six approved documents.",
        source_path="backend/ai_advisor/authoritative_knowledge.py",
    ),
    SourceIndexRecord(
        concept="knowledge-registry-advisor",
        source_type=_SOURCE,
        source_reference="backend/ai_advisor/knowledge.py",
        symbol="ApprovedKnowledgeRegistry",
        authority_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        consumer="AI Advisor (dormant)",
        notes="retrievalEnabled=False; not enabled.",
        source_path="backend/ai_advisor/knowledge.py",
    ),
)


class SourceIndex:
    """Immutable, deterministic source index keyed by concept."""

    def __init__(self, records: tuple[SourceIndexRecord, ...] = SOURCE_INDEX_RECORDS) -> None:
        self._records = tuple(sorted(
            records,
            key=lambda r: (r.concept, r.source_type.value, r.source_reference),
        ))
        self._by_concept: dict[str, tuple[SourceIndexRecord, ...]] = {}
        grouped: dict[str, list[SourceIndexRecord]] = {}
        for record in self._records:
            grouped.setdefault(record.concept, []).append(record)
        for concept in sorted(grouped):
            self._by_concept[concept] = tuple(
                sorted(grouped[concept], key=lambda r: (r.source_type.value, r.source_reference))
            )
        self._by_concept = freeze_mapping(self._by_concept)

    @property
    def entries(self) -> tuple[SourceIndexRecord, ...]:
        return self._records

    @property
    def concepts(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_concept))

    def lookup(self, concept: str) -> tuple[SourceIndexRecord, ...]:
        return self._by_concept.get(concept, ())

    def stable_json(self) -> str:
        return stable_json(self._records)
