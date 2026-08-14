"""Paper-only AUTO market selection end-to-end coordination boundary."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping, Optional, Tuple

from backend.runtime.runtime_symbol_context import (
    build_runtime_symbol_context, symbol_context_matches,
)
from .auto_selection_runtime import AutoSelectionCycleStatus


class PaperAutoSelectionE2EStatus(str, Enum):
    COMPLETED_NO_SWITCH = "COMPLETED_NO_SWITCH"
    COMPLETED_SWITCHED = "COMPLETED_SWITCHED"
    COMPLETED_HOLD = "COMPLETED_HOLD"
    COMPLETED_BLOCKED = "COMPLETED_BLOCKED"
    FAILED = "FAILED"


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _time(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PaperAutoSelectionE2EResult:
    e2e_cycle_id: str
    auto_selection_cycle_id: Optional[str]
    initial_active_symbol: Optional[str]
    top_candidate_symbol: Optional[str]
    final_active_symbol: Optional[str]
    strategy_decision: Optional[str]
    ai_decision: Optional[str]
    mm_decision: Optional[str]
    governance_decision: Optional[str]
    paper_order_created: bool
    status: PaperAutoSelectionE2EStatus
    reason_codes: Tuple[str, ...]
    started_at: datetime
    completed_at: datetime

    def to_dict(self):
        return {
            "e2eCycleId": self.e2e_cycle_id,
            "autoSelectionCycleId": self.auto_selection_cycle_id,
            "initialActiveSymbol": self.initial_active_symbol,
            "topCandidateSymbol": self.top_candidate_symbol,
            "finalActiveSymbol": self.final_active_symbol,
            "strategyDecision": self.strategy_decision,
            "aiDecision": self.ai_decision,
            "tradingAiMode": "OFF",
            "tradingAiStatus": "NOT_INSTALLED",
            "mmDecision": self.mm_decision,
            "governanceDecision": self.governance_decision,
            "paperOrderCreated": self.paper_order_created,
            "status": self.status.value,
            "reasonCodes": list(self.reason_codes),
            "startedAt": _time(self.started_at),
            "completedAt": _time(self.completed_at),
        }


class PaperAutoSelectionE2E:
    """Connect AMS-4A to existing decision-stage adapters in Paper only."""

    def __init__(self, bot_manager, auto_runtime, *, initial_state_provider,
                 market_intelligence, strategy, ai_review, money_management,
                 governance, paper_execution, clock=None):
        boundaries = (
            initial_state_provider, market_intelligence, strategy, ai_review,
            money_management, governance, paper_execution,
        )
        if any(not callable(item) for item in boundaries):
            raise TypeError("Paper E2E authority boundaries required")
        if not callable(getattr(auto_runtime, "run_cycle", None)):
            raise TypeError("AutoMarketSelectionRuntime required")
        self.manager = bot_manager
        self.auto_runtime = auto_runtime
        self.initial_state_provider = initial_state_provider
        self.market_intelligence = market_intelligence
        self.strategy = strategy
        # Retained only as a constructor compatibility slot. Trading AI is
        # optional, OFF, and not invoked by the authoritative Paper path.
        self.ai_review = None
        self.money_management = money_management
        self.governance = governance
        self.paper_execution = paper_execution
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, started_at=None):
        started = _utc(started_at or self.clock())
        initial = self._active_symbol()
        reason = self._safety_reason()
        if reason:
            return self._result(started, initial, status=PaperAutoSelectionE2EStatus.FAILED,
                                reasons=(reason,))
        if initial is None:
            return self._result(
                started, initial, status=PaperAutoSelectionE2EStatus.FAILED,
                reasons=("PAPER_E2E_ACTIVE_SYMBOL_UNKNOWN",),
            )
        state = self.initial_state_provider()
        reason = self._initial_state_reason(state)
        if reason:
            return self._result(started, initial, status=PaperAutoSelectionE2EStatus.FAILED,
                                reasons=(reason,))

        auto = self.auto_runtime.run_cycle(started_at=started)
        common = dict(auto=auto, initial=initial)
        if auto.status in {
            AutoSelectionCycleStatus.NO_ELIGIBLE_MARKET,
            AutoSelectionCycleStatus.NO_RANKABLE_MARKET,
            AutoSelectionCycleStatus.SWITCH_BLOCKED,
        }:
            return self._result(
                started, status=PaperAutoSelectionE2EStatus.COMPLETED_BLOCKED,
                reasons=auto.reason_codes, **common,
            )
        if auto.status is AutoSelectionCycleStatus.FAILED:
            return self._result(started, status=PaperAutoSelectionE2EStatus.FAILED,
                                reasons=auto.reason_codes, **common)
        if auto.status not in {
            AutoSelectionCycleStatus.COMPLETED,
            AutoSelectionCycleStatus.NO_SWITCH_REQUIRED,
        }:
            return self._result(started, status=PaperAutoSelectionE2EStatus.FAILED,
                                reasons=("AUTO_SELECTION_RESULT_INVALID",), **common)

        symbol = self._active_symbol()
        runtime_id = getattr(self.manager, "active_runtime_id", None)
        context = build_runtime_symbol_context(symbol, runtime_id, evaluated_at=self.clock())
        if context is None or symbol != auto.final_active_symbol:
            return self._result(started, status=PaperAutoSelectionE2EStatus.FAILED,
                                reasons=("ACTIVE_SYMBOL_CONTEXT_INVALID",), **common)
        context_payload = context.to_dict()
        try:
            market = self.market_intelligence(context_payload)
            if not self._stage_matches(market, context_payload):
                raise ValueError("MARKET_INTELLIGENCE_CONTEXT_MISMATCH")
            strategy = self.strategy(market, context_payload)
            if not self._stage_matches(strategy, context_payload):
                raise ValueError("OLD_STRATEGY_DECISION_REJECTED")
            strategy_value = self._decision(strategy)
            if strategy_value == "HOLD":
                return self._result(
                    started, status=PaperAutoSelectionE2EStatus.COMPLETED_HOLD,
                    strategy=strategy_value, reasons=("STRATEGY_HOLD",), **common,
                )
            ai_value = "NOT_REQUIRED"
            mm = self.money_management(strategy, context_payload)
            if not self._stage_matches(mm, context_payload):
                raise ValueError("MM_CONTEXT_MISMATCH")
            mm_value = self._decision(mm)
            if mm.get("allowed") is not True:
                return self._result(
                    started, status=PaperAutoSelectionE2EStatus.COMPLETED_BLOCKED,
                    strategy=strategy_value, ai=ai_value, mm=mm_value,
                    reasons=tuple(mm.get("reasonCodes") or ("MM_BLOCKED",)), **common,
                )
            governance = self.governance(mm, context_payload)
            if not self._stage_matches(governance, context_payload):
                raise ValueError("GOVERNANCE_CONTEXT_MISMATCH")
            governance_value = self._decision(governance)
            if governance.get("allowed") is not True:
                return self._result(
                    started, status=PaperAutoSelectionE2EStatus.COMPLETED_BLOCKED,
                    strategy=strategy_value, ai=ai_value, mm=mm_value,
                    governance=governance_value,
                    reasons=tuple(governance.get("reasonCodes") or ("GOVERNANCE_BLOCKED",)),
                    **common,
                )
            if not symbol_context_matches(
                    context_payload, self._active_symbol(),
                    getattr(self.manager, "active_runtime_id", None)):
                raise ValueError("EXECUTION_SYMBOL_CONTEXT_STALE")
            execution = self.paper_execution(governance, context_payload)
            if not self._stage_matches(execution, context_payload):
                raise ValueError("EXECUTION_CONTEXT_MISMATCH")
            if execution.get("realExchangeCalled") is True:
                raise ValueError("REAL_EXCHANGE_CALL_FORBIDDEN")
            created = execution.get("paperOrderCreated") is True
            final_status = (
                PaperAutoSelectionE2EStatus.COMPLETED_SWITCHED
                if auto.status is AutoSelectionCycleStatus.COMPLETED
                else PaperAutoSelectionE2EStatus.COMPLETED_NO_SWITCH
            )
            return self._result(
                started, status=final_status, strategy=strategy_value,
                ai=ai_value, mm=mm_value, governance=governance_value,
                order=created, **common,
            )
        except ValueError as error:
            return self._result(started, status=PaperAutoSelectionE2EStatus.FAILED,
                                reasons=(str(error),), **common)
        except Exception:
            return self._result(started, status=PaperAutoSelectionE2EStatus.FAILED,
                                reasons=("PAPER_E2E_STAGE_FAILED",), **common)

    def _safety_reason(self):
        config = getattr(self.manager, "config", None)
        if not isinstance(config, Mapping):
            return "PAPER_E2E_MODE_UNAVAILABLE"
        mode = str(config.get("tradeMode", config.get("mode", ""))).lower()
        if mode != "paper":
            return "PAPER_E2E_LIVE_BLOCKED"
        if config.get("dryRun", config.get("dry_run")) is not True:
            return "PAPER_E2E_DRY_RUN_REQUIRED"
        if config.get("realOrderAllowed", config.get("real_order_allowed", False)) is not False:
            return "PAPER_E2E_REAL_ORDER_FORBIDDEN"
        return None

    @staticmethod
    def _initial_state_reason(state):
        if not isinstance(state, Mapping):
            return "PAPER_E2E_INITIAL_STATE_UNKNOWN"
        required = (
            ("activeSymbolKnown", "PAPER_E2E_ACTIVE_SYMBOL_UNKNOWN"),
            ("positionKnown", "PAPER_E2E_POSITION_UNKNOWN"),
            ("pendingOrderKnown", "PAPER_E2E_PENDING_ORDER_UNKNOWN"),
            ("mmAvailable", "PAPER_E2E_MM_UNAVAILABLE"),
            ("emergencySafe", "PAPER_E2E_EMERGENCY_UNSAFE"),
            ("governanceAvailable", "PAPER_E2E_GOVERNANCE_UNAVAILABLE"),
        )
        for key, reason in required:
            if state.get(key) is not True:
                return reason
        return None

    @staticmethod
    def _stage_matches(value, context):
        return (isinstance(value, Mapping)
                and value.get("runtimeSymbolContext") == context)

    @staticmethod
    def _decision(value):
        raw = value.get("decision") if isinstance(value, Mapping) else None
        return str(raw).upper() if raw is not None else None

    def _active_symbol(self):
        value = getattr(self.manager, "activeSymbol", None)
        return str(value).strip().upper() if value else None

    def _result(self, started, initial, *, status, reasons=(), auto=None,
                strategy=None, ai=None, mm=None, governance=None, order=False):
        completed = _utc(self.clock())
        auto_id = getattr(auto, "auto_selection_cycle_id", None)
        identity = json.dumps(
            {"autoSelectionCycleId": auto_id, "startedAt": _time(started)},
            sort_keys=True, separators=(",", ":"),
        )
        return PaperAutoSelectionE2EResult(
            "ams-4b-" + sha256(identity.encode("utf-8")).hexdigest()[:20],
            auto_id, initial, getattr(auto, "top_candidate_symbol", None),
            self._active_symbol(), strategy, ai, mm, governance, bool(order),
            status, tuple(reasons), started, completed,
        )
