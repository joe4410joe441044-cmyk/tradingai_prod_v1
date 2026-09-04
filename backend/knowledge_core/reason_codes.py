"""Reason Code Catalog (read-only index).

D-0 found reason codes distributed across existing systems.  D-1 provides a
normalized, READ-ONLY catalog/index.  It does NOT replace existing enums or
constants, does NOT modify runtime emitters, and does NOT rename codes.

Where a meaning is unsupported by source/spec it is recorded as ``UNKNOWN``
with provenance instead of being invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Optional

from ._base import freeze_mapping, stable_json
from .authority import SourceCategory, TruthLevel
from .domain import Domain
from .provenance import ProvenanceRecord

UNKNOWN = "UNKNOWN"

_SRC = SourceCategory.SOURCE_CODE


def _p(path: str, symbol: Optional[str], *, truth: TruthLevel = TruthLevel.CURRENT_SOURCE_RUNTIME,
       category: SourceCategory = _SRC) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=truth,
        source_category=category,
        source_reference=path,
        source_path=path,
        symbol=symbol,
    )


@dataclass(frozen=True)
class ReasonCodeRecord:
    """One indexed reason/decision/status code.

    ``meaning`` is ``UNKNOWN`` when not supported by the source/spec.
    ``domain`` is the describing domain.  ``category`` is an optional
    descriptive class (e.g. DECISION/STATUS/BLOCK).  Duplicate picks within a
    single domain are surfaced by the catalog as conflicts, never merged.
    """

    code: str
    domain: Domain
    category: Optional[str] = None
    meaning: str = UNKNOWN
    producer: Optional[str] = None
    operator_interpretation: str = UNKNOWN
    provenance: ProvenanceRecord = field(default_factory=ProvenanceRecord)


def _r(code: str, domain: Domain, *,
       category: Optional[str] = None,
       meaning: str = UNKNOWN,
       producer: Optional[str] = None,
       operator: str = UNKNOWN,
       provenance: Optional[ProvenanceRecord] = None) -> ReasonCodeRecord:
    return ReasonCodeRecord(
        code=code,
        domain=domain,
        category=category,
        meaning=meaning,
        producer=producer,
        operator_interpretation=operator,
        provenance=provenance or _p("?", None),
    )


_MM = Domain.MONEY_MANAGEMENT
_GOV = Domain.GOVERNANCE
_EMG = Domain.EMERGENCY
_EXE = Domain.EXECUTION
_DEC = Domain.TRADING_DECISION
_RT = Domain.RUNTIME_HEALTH
_MKT = Domain.MARKET
_BOT = Domain.BOT

_RISK_STATE = _p("backend/money_management/enums.py:8", "RiskState",
                 truth=TruthLevel.CANONICAL_SPECIFICATION,
                 category=SourceCategory.SPECIFICATION)
_DECISION_RESULT = _p("backend/money_management/enums.py:10", "DecisionResult",
                      truth=TruthLevel.CANONICAL_SPECIFICATION,
                      category=SourceCategory.SPECIFICATION)
_RISK_BLOCK = _p("backend/money_management/enums.py:12", "RiskBlockReason")
_LIMIT_SEV = _p("backend/money_management/enums.py:14", "LimitSeverity")
_LOSS_REASON = _p("backend/money_management/loss_reason_models.py", "LossReason")
_MM_REASONCODE = _p("backend/money_management/loss_reason_models.py:22", "ReasonCode")
_ACTION_DEC = _p("backend/money_management/loss_models.py:9", "ActionDecision")
_MM_ENTRY_DEC = _p("backend/money_management/loss_execution_guard_models.py:26", "LossExecutionEntryDecision")
_GOV_REASON = _p("backend/runtime/governance_runtime.py:665-725", "GovernanceRuntime.process_governance")
_EMG_STATE = _p("backend/runtime/governance_runtime.py:41-44", "EMERGENCY_*")
_EMG_RESULT = _p("backend/runtime/governance_runtime.py:46-49", "EMERGENCY_RESULT_*")
_EXE_GOV = _p("backend/execution/ExecutionGovernance.py:206-334", "ExecutionGovernance.evaluate_execution_governance")
_EXE_RT = _p("backend/runtime/ExecutionRuntime.py:357-502", "ExecutionRuntime.evaluate_execution_permission")
_EXIT = _p("backend/strategy/MicrostructureEdgeStrategy.py:1159", "ExitReason")
_SUPPR = _p("backend/strategy/MicrostructureEdgeStrategy.py:726-812", "evaluate_execution_suppression")
_COND = _p("backend/strategy/MicrostructureEdgeStrategy.py:1001-1153", "build_entry_readiness")
_STAGES = _p("backend/runtime/trading_trace.py:21", "STAGES")
_TERMINAL = _p("backend/runtime/trading_trace.py:26", "TERMINAL_CLASSIFICATIONS")
_HEALTH = _p("backend/runtime/runtime_health_snapshot.py", "runtime_health_snapshot")
_PAPER = _p("backend/runtime/paper_account_store.py", "paper_account_store")


def _risk_states() -> tuple[ReasonCodeRecord, ...]:
    return tuple(
        _r(value, _MM, category="RISK_STATE", meaning="Documented MM risk state.",
           producer="Money Management (RiskState)", provenance=_RISK_STATE)
        for value in ("NORMAL", "CAUTION", "DEFENSIVE", "LOCKED", "RECOVERY_25", "RECOVERY_50")
    )


def _decision_results() -> tuple[ReasonCodeRecord, ...]:
    return tuple(
        _r(value, _MM, category="DECISION_RESULT", meaning="Documented MM decision outcome.",
           producer="Money Management (DecisionResult)", provenance=_DECISION_RESULT)
        for value in ("APPROVED", "SIZE_REDUCED", "RISK_BLOCKED", "INVALID_INPUT", "INSUFFICIENT_DATA")
    )


REASON_CODE_RECORDS = (
    *_risk_states(),
    *_decision_results(),
    # RiskBlockReason
    *(_r(value, _MM, category="BLOCK_REASON", producer="Money Management (RiskBlockReason)",
         provenance=_RISK_BLOCK)
      for value in ("NONE", "MAXIMUM_DRAWDOWN", "DAILY_LOSS_LIMIT", "WEEKLY_LOSS_LIMIT",
                    "MONTHLY_LOSS_LIMIT", "MAXIMUM_POSITION", "TOTAL_EXPOSURE_LIMIT",
                    "SYMBOL_EXPOSURE_LIMIT", "MAXIMUM_LEVERAGE", "RISK_OF_RUIN_CRITICAL",
                    "CONSECUTIVE_LOSS_LIMIT", "COOLDOWN_ACTIVE", "RECOVERY_LIMIT",
                    "INVALID_EQUITY", "INVALID_ENTRY_PRICE", "INVALID_STOP",
                    "INVALID_COST_ASSUMPTION", "BELOW_MINIMUM_ORDER", "INSUFFICIENT_DATA",
                    "PROFIT_PROTECTION_LIMIT")),
    # LimitSeverity / Cooldown / Recovery
    *(_r(value, _MM, category="SEVERITY", producer="Money Management (LimitSeverity)",
         provenance=_LIMIT_SEV) for value in ("NONE", "SOFT", "HARD")),
    *(_r(value, _MM, category="COOLDOWN_STATE", producer="Money Management (CooldownState)",
         provenance=_LIMIT_SEV) for value in ("INACTIVE", "ACTIVE")),
    *(_r(value, _MM, category="RECOVERY_STATE", producer="Money Management (RecoveryState)",
         provenance=_LIMIT_SEV) for value in ("NOT_REQUIRED", "IN_PROGRESS", "COMPLETED")),
    # Loss Reason / Action / ReasonCode / EntryDecision
    *(_r(value, _MM, category="LOSS_REASON", producer="Money Management (LossReason)",
         provenance=_LOSS_REASON)
      for value in ("NONE", "DAILY_LOSS_WARNING", "DAILY_LOSS_BLOCK", "WEEKLY_LOSS_WARNING",
                    "WEEKLY_LOSS_BLOCK", "MONTHLY_LOSS_WARNING", "MONTHLY_LOSS_BLOCK",
                    "MAX_DRAWDOWN_BLOCK", "NEGATIVE_EQUITY", "DRAWDOWN_PERCENT_UNKNOWN",
                    "CASH_FLOW_ADJUSTMENT_UNRESOLVED", "MULTIPLE_WARNINGS", "BASE_EQUITY_INVALID",
                    "PERIOD_DATA_MISSING", "PERIOD_DATA_MISMATCH", "CURRENCY_MISMATCH",
                    "CONFIG_INVALID", "INPUT_UNKNOWN")),
    *(_r(value, _MM, category="ACTION_DECISION", producer="Money Management (ActionDecision)",
         provenance=_ACTION_DEC) for value in ("ALLOW", "WARN", "BLOCK")),
    *(_r(value, _MM, category="REASON_CODE", producer="Money Management (ReasonCode)",
         provenance=_MM_REASONCODE)
      for value in ("NONE", "DAILY_LOSS_WARNING", "WEEKLY_LOSS_WARNING", "MONTHLY_LOSS_WARNING",
                    "DRAWDOWN_WARNING", "DAILY_LOSS_BLOCK", "WEEKLY_LOSS_BLOCK", "MONTHLY_LOSS_BLOCK",
                    "DRAWDOWN_BLOCK", "NEGATIVE_EQUITY", "DRAWDOWN_PERCENT_UNKNOWN", "CASH_FLOW_DETECTED",
                    "MULTIPLE_LOSS_WARNINGS", "LOSS_LIMIT_DEFENSIVE_STATE")),
    *(_r(value, _MM, category="ENTRY_DECISION", producer="Money Management (LossExecutionEntryDecision)",
         provenance=_MM_ENTRY_DEC) for value in ("ALLOW", "BLOCK", "RECOVERY_REQUIRED", "UNKNOWN")),
    # Governance
    *(_r(value, _GOV, category="REASON", producer="GovernanceRuntime.process_governance",
         provenance=_GOV_REASON)
      for value in ("STRATEGY_STATE_INVALID", "STRATEGY_HOLD", "EMERGENCY_HALT",
                    "EXECUTION_DISABLED", "NO_TRADE_ZONE")),
    *(_r(value, _GOV, category="STATE", producer="governance_state",
         provenance=_GOV_REASON)
      for value in ("PAPER", "SAFE", "BACKEND", "OBSERVING", "ACTIVE", "STABLE")),
    # Emergency
    *(_r(value, _EMG, category="EMERGENCY_STATE", producer="governance_runtime EMERGENCY_*",
         provenance=_EMG_STATE) for value in ("READY", "PROCESSING", "LOCKED", "ACTION_REQUIRED")),
    *(_r(value, _EMG, category="EMERGENCY_RESULT", producer="governance_runtime EMERGENCY_RESULT_*",
         provenance=_EMG_RESULT) for value in ("NONE", "SUCCESS", "PARTIAL", "FAILED")),
    # Execution governance
    *(_r(value, _EXE, category="REASON", producer="ExecutionGovernance.evaluate_execution_governance",
         provenance=_EXE_GOV)
      for value in ("STRATEGY_SUPPRESSED", "EMERGENCY_HALT", "EXECUTION_LOCKED", "EXECUTION_THROTTLE",
                    "COOLDOWN_ACTIVE", "EXPOSURE_LIMIT", "EXECUTION_PACING")),
    *(_r(value, _EXE, category="REASON", producer="ExecutionRuntime.evaluate_execution_permission",
         provenance=_EXE_RT)
      for value in ("GOVERNANCE_REJECTED", "INVALID_DIRECTION", "EXECUTION_DISABLED", "MAX_DRAWDOWN",
                    "LOW_CONFIDENCE", "RUNTIME_UNHEALTHY", "ENGINE_UNAVAILABLE", "ADAPTER_OUTPUT_UNAVAILABLE",
                    "LIVE_NOT_READY", "EXECUTION_HANDOFF_BLOCKED", "MONEY_MANAGEMENT_BLOCKED",
                    "MONEY_MANAGEMENT_UNKNOWN", "GOVERNANCE_UNAVAILABLE", "STRATEGY_INVALID", "TRADING_AI_OFF")),
    # Trading Decision
    *(_r(value, _DEC, category="EXIT_REASON", producer="MicrostructureEdgeStrategy.ExitReason",
         provenance=_EXIT)
      for value in ("STOP_LOSS", "TAKE_PROFIT", "MAX_HOLD", "MICROSTRUCTURE_REVERSAL",
                    "MOMENTUM_DECAY", "LIQUIDITY_DETERIORATION", "SPREAD_DIVERGENCE")),
    *(_r(value, _DEC, category="SUPPRESSION_REASON", producer="evaluate_execution_suppression",
         provenance=_SUPPR)
      for value in ("LIQUIDITY_INSTABILITY", "MOMENTUM_WARMUP", "DIRECTION_CONFLICT",
                    "DIRECTION_NOT_CONFIRMED", "LOW_COMPOSITE_SCORE", "CONFLICTING_MOMENTUM",
                    "WEAK_EDGE", "LOW_CONFIDENCE")),
    *(_r(value, _DEC, category="CONDITION", producer="build_entry_readiness _condition", provenance=_COND)
      for value in ("SPREAD", "SPREAD_VOLATILITY", "LIQUIDITY_QUALITY", "LIQUIDITY_VOLUME",
                    "ABSORPTION", "STAGNANT_FLOW", "FAKE_PRESSURE", "LIQUIDITY_SAFETY", "MOMENTUM",
                    "PRESSURE_ALIGNMENT", "EDGE", "CONFIDENCE")),
    # Runtime trace stages + terminal classifications
    *(_r(value, _RT, category="TRACE_STAGE", producer="trading_trace STAGES", provenance=_STAGES)
      for value in ("MARKET", "DETECTOR", "FEATURE", "STRATEGY", "AI", "MONEY_MANAGEMENT",
                    "GOVERNANCE", "EXECUTION", "POSITION", "RESULT", "HISTORY")),
    *(_r(value, _RT, category="TERMINAL_CLASSIFICATION", producer="trading_trace TERMINAL_CLASSIFICATIONS",
         provenance=_TERMINAL)
      for value in ("COMPLETE_EXECUTED", "COMPLETE_SUPPRESSED", "COMPLETE_BLOCKED",
                    "INCOMPLETE", "FAILED")),
    # Market / Runtime data quality + freshness + health
    *(_r(value, _MKT, category="DATA_QUALITY", producer="documented taxonomy (no single enum)",
         provenance=_p("docs/market_intelligence/02_MARKET_INTELLIGENCE_COMPONENT_SPEC.md", "Data Quality",
                       truth=TruthLevel.CANONICAL_SPECIFICATION, category=SourceCategory.SPECIFICATION))
      for value in ("COMPLETE", "PARTIAL", "STALE", "UNSYNCED", "MISSING", "MALFORMED", "UNSUPPORTED")),
    *(_r(value, _RT, category="FRESHNESS", producer="Supervisor Freshness",
         provenance=_p("backend/supervisor/contracts.py:67", "Freshness"))
      for value in ("FRESH", "STALE", "MISSING", "CONFLICTED", "UNKNOWN")),
    *(_r(value, _RT, category="HEALTH_BLOCK", producer="runtime_health_snapshot", provenance=_HEALTH)
      for value in ("MARKET_DATA_MISSING_OR_STALE", "ORDERBOOK_MISSING_OR_STALE", "RUNTIME_SNAPSHOT_MISSING")),
    # Paper bootstrap
    *(_r(value, _BOT, category="PAPER_BOOTSTRAP", producer="paper_account_store", provenance=_PAPER)
      for value in ("INVALID_PAPER_CAPITAL", "PAPER_ACCOUNT_STATE_CORRUPT", "PAPER_ACCOUNT_SCOPE_INVALID",
                    "PAPER_ACCOUNT_UNAVAILABLE")),
    *(_r(value, _BOT, category="STOPPED_PAPER_RECOVERY", producer="bot_manager stopped-paper recovery",
         provenance=_p("backend/bot_manager/bot_manager.py:6103-6213", "stopped paper recovery"))
      for value in ("DURABLE_SNAPSHOT_MISSING", "SNAPSHOT_SOURCE_UNKNOWN", "SNAPSHOT_UNAVAILABLE",
                    "EMERGENCY_NOT_READY", "REAL_ORDER_ALLOWED", "PENDING_ORDER_REMAINING")),
)


class ReasonCodeCatalog:
    """Immutable reason-code index with explicit conflict surfacing."""

    def __init__(self, records: tuple[ReasonCodeRecord, ...] = REASON_CODE_RECORDS) -> None:
        self._records = tuple(sorted(
            records, key=lambda r: (r.code, r.domain.value, r.provenance.source_reference),
        ))
        self._by_key: dict[str, tuple[ReasonCodeRecord, ...]] = {}
        grouped: dict[str, list[ReasonCodeRecord]] = {}
        for record in self._records:
            key = f"{record.code}::{record.domain.value}"
            grouped.setdefault(key, []).append(record)
        for key in sorted(grouped):
            self._by_key[key] = tuple(grouped[key])
        self._by_key = freeze_mapping(self._by_key)

    @property
    def entries(self) -> tuple[ReasonCodeRecord, ...]:
        return self._records

    @property
    def count(self) -> int:
        return len(self._records)

    def lookup(self, code: str, domain: Domain | str | None = None) -> tuple[ReasonCodeRecord, ...]:
        if domain is None:
            return tuple(r for r in self._records if r.code == code)
        dkey = domain.value if isinstance(domain, Domain) else domain
        return self._by_key.get(f"{code}::{dkey}", ())

    def by_domain(self, domain: Domain | str) -> tuple[ReasonCodeRecord, ...]:
        dkey = domain.value if isinstance(domain, Domain) else domain
        return tuple(r for r in self._records if r.domain.value == dkey)

    @property
    def conflicts(self) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
        """Explicit duplicate-pick findings within a single domain.

        Returns tuples of (code, domain, distinct producers).  Empty when no
        code is claimed by more than one producer within the same domain.
        """
        result = []
        for r in self._records:
            same = [x for x in self._records if x.code == r.code and x.domain == r.domain]
            producers = tuple(sorted({x.provenance.source_reference for x in same}))
            if len(producers) > 1:
                result.append((r.code, r.domain.value, producers))
        seen = pair = set()
        deduped = []
        for item in result:
            key = (item[0], item[1], item[2])
            if key not in seen:
                seen.add(key)
                deduped.append(item)
        return tuple(deduped)

    @property
    def cross_domain_collisions(self) -> tuple[str, ...]:
        """Code strings reused across different domains (finding, not error)."""
        by_code: dict[str, set[str]] = {}
        for r in self._records:
            by_code.setdefault(r.code, set()).add(r.domain.value)
        return tuple(sorted(code for code, domains in by_code.items() if len(domains) > 1))

    @property
    def unknown_means(self) -> int:
        return sum(1 for r in self._records if r.meaning == UNKNOWN)

    def stable_json(self) -> str:
        return stable_json(self._records)
