"""Paper-only orchestration of one deterministic AUTO selection cycle."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import threading
from typing import Optional, Tuple

from .bot_manager_switch_runtime import BotManagerSwitchRuntime
from .candidate_ranking import CandidateRankingEngine
from .market_scanner import MarketScanner, ScannerInput, ScannerStatus
from .safe_switch import SafeSymbolSwitch
from .selection_audit import build_selection_audit_event
from .selection_proposal import build_selection_proposal, snapshot_active_symbol_authority


class AutoSelectionRuntimeMode(str, Enum):
    MANUAL = "MANUAL"
    AUTO_PAPER = "AUTO_PAPER"


class AutoSelectionCycleStatus(str, Enum):
    IDLE = "IDLE"
    EVALUATING = "EVALUATING"
    NO_ELIGIBLE_MARKET = "NO_ELIGIBLE_MARKET"
    NO_RANKABLE_MARKET = "NO_RANKABLE_MARKET"
    NO_SWITCH_REQUIRED = "NO_SWITCH_REQUIRED"
    SWITCH_BLOCKED = "SWITCH_BLOCKED"
    SWITCHING = "SWITCHING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _time(value):
    return _utc(value).isoformat().replace("+00:00", "Z") if value else None


@dataclass(frozen=True)
class AutoSelectionCycleResult:
    auto_selection_cycle_id: str
    started_at: datetime
    evaluated_at: datetime
    mode: AutoSelectionRuntimeMode
    current_active_symbol: Optional[str]
    top_candidate_symbol: Optional[str]
    proposed_symbol: Optional[str]
    final_active_symbol: Optional[str]
    scanner_cycle_id: Optional[str]
    ranking_cycle_id: Optional[str]
    audit_event_id: Optional[str]
    selection_proposal_id: Optional[str]
    switch_transaction_id: Optional[str]
    status: AutoSelectionCycleStatus
    reason_codes: Tuple[str, ...]

    def to_dict(self):
        return {
            "autoSelectionCycleId": self.auto_selection_cycle_id,
            "startedAt": _time(self.started_at),
            "evaluatedAt": _time(self.evaluated_at),
            "mode": self.mode.value,
            "currentActiveSymbol": self.current_active_symbol,
            "topCandidateSymbol": self.top_candidate_symbol,
            "proposedSymbol": self.proposed_symbol,
            "finalActiveSymbol": self.final_active_symbol,
            "scannerCycleId": self.scanner_cycle_id,
            "rankingCycleId": self.ranking_cycle_id,
            "auditEventId": self.audit_event_id,
            "selectionProposalId": self.selection_proposal_id,
            "switchTransactionId": self.switch_transaction_id,
            "status": self.status.value,
            "reasonCodes": list(self.reason_codes),
        }


class AutoMarketSelectionRuntime:
    """Connect existing AMS contracts for exactly one Paper dry-run cycle.

    Providers are authoritative I/O boundaries. This class does not calculate
    MM eligibility, ranking scores, execution decisions, or orders.
    """

    def __init__(
        self, bot_manager, *, universe_provider, ticker_provider, capital_provider,
        eligibility_provider, position_provider, pending_order_provider,
        emergency_provider, scanner=None, ranking_engine=None,
        safe_switch_factory=None, clock=None,
    ):
        providers = (
            universe_provider, ticker_provider, capital_provider,
            eligibility_provider, position_provider, pending_order_provider,
            emergency_provider,
        )
        if any(not callable(provider) for provider in providers):
            raise TypeError("authoritative AUTO selection providers required")
        self.manager = bot_manager
        self.universe_provider = universe_provider
        self.ticker_provider = ticker_provider
        self.capital_provider = capital_provider
        self.eligibility_provider = eligibility_provider
        self.position_provider = position_provider
        self.pending_order_provider = pending_order_provider
        self.emergency_provider = emergency_provider
        self.scanner = scanner or MarketScanner()
        self.ranking_engine = ranking_engine or CandidateRankingEngine()
        self.safe_switch_factory = safe_switch_factory or self._default_safe_switch
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._cycle_lock = threading.Lock()
        self._last_result = None

    def get_status(self):
        if self._last_result is None:
            return {
                "mode": AutoSelectionRuntimeMode.MANUAL.value,
                "status": AutoSelectionCycleStatus.IDLE.value,
                "cycle": None,
                "readOnly": True,
            }
        return {
            "mode": self._last_result.mode.value,
            "status": self._last_result.status.value,
            "cycle": self._last_result.to_dict(),
            "readOnly": True,
        }

    def run_cycle(self, *, started_at=None):
        started = _utc(started_at or self.clock())
        active = self._active_symbol()
        cycle_id = self._cycle_identity(started, active)
        if not self._cycle_lock.acquire(blocking=False):
            return self._result(
                cycle_id, started, AutoSelectionCycleStatus.FAILED,
                ("AUTO_SELECTION_ALREADY_IN_PROGRESS",), active=active,
                publish=False,
            )
        try:
            safety_reason = self._paper_safety_reason()
            if safety_reason:
                return self._finish(self._result(
                    cycle_id, started, AutoSelectionCycleStatus.FAILED,
                    (safety_reason,), active=active,
                    mode=AutoSelectionRuntimeMode.MANUAL,
                ))
            return self._run_locked(cycle_id, started, active)
        except Exception:
            return self._finish(self._result(
                cycle_id, started, AutoSelectionCycleStatus.FAILED,
                ("AUTO_SELECTION_INPUT_UNAVAILABLE",), active=active,
            ))
        finally:
            self._cycle_lock.release()

    def _run_locked(self, cycle_id, started, active):
        universe = self.universe_provider()
        ticker = self.ticker_provider()
        capital = self.capital_provider()
        eligibility = self.eligibility_provider(universe, capital)
        evaluated = _utc(self.clock())
        scanner_result = self.scanner.scan(ScannerInput(
            universe=universe, ticker_snapshot=ticker, capital=capital,
            per_market_eligibility=eligibility, evaluated_at=evaluated,
            started_at=started,
        ))
        if scanner_result.status is ScannerStatus.AUTO_SELECTION_UNAVAILABLE:
            return self._finish(self._result(
                cycle_id, started, AutoSelectionCycleStatus.FAILED,
                tuple(reason.value for reason in scanner_result.global_rejection_reasons),
                active=active, scanner=scanner_result,
            ), scanner=scanner_result)
        if scanner_result.eligible_count == 0:
            reasons = tuple(reason.value for reason in scanner_result.global_rejection_reasons)
            if not reasons:
                reasons = tuple(dict.fromkeys(
                    reason.value for item in scanner_result.rejections
                    for reason in item.rejection_reasons
                ))
            return self._finish(self._result(
                cycle_id, started, AutoSelectionCycleStatus.NO_ELIGIBLE_MARKET,
                reasons, active=active, scanner=scanner_result,
            ), scanner=scanner_result)

        ranking = self.ranking_engine.rank(scanner_result, evaluated_at=evaluated)
        if ranking.top_candidate is None:
            return self._finish(self._result(
                cycle_id, started, AutoSelectionCycleStatus.NO_RANKABLE_MARKET,
                tuple(reason.value for reason in ranking.reason_codes),
                active=active, scanner=scanner_result, ranking=ranking,
            ), scanner=scanner_result, ranking=ranking)

        audit = build_selection_audit_event(universe, capital, scanner_result, ranking)
        position = self.position_provider()
        pending = self.pending_order_provider()
        emergency = self.emergency_provider()
        proposal = build_selection_proposal(
            ranking, audit,
            active_symbol_authority=snapshot_active_symbol_authority(self.manager),
            position_state=position, pending_order_state=pending,
            mm_authority=capital, emergency_safe=emergency,
            proposed_at=evaluated,
        )
        common = dict(active=active, scanner=scanner_result, ranking=ranking,
                      audit=audit, proposal=proposal)
        if proposal.proposed_symbol == active:
            return self._finish(self._result(
                cycle_id, started, AutoSelectionCycleStatus.NO_SWITCH_REQUIRED,
                ("NO_SWITCH_REQUIRED",), **common,
            ), scanner=scanner_result, ranking=ranking, audit=audit, proposal=proposal)
        if not proposal.switch_eligible:
            return self._finish(self._result(
                cycle_id, started, AutoSelectionCycleStatus.SWITCH_BLOCKED,
                tuple(reason.value for reason in proposal.reason_codes), **common,
            ), scanner=scanner_result, ranking=ranking, audit=audit, proposal=proposal)

        switch_result = self.safe_switch_factory().execute(proposal, started_at=evaluated)
        final_active = self._active_symbol()
        synchronized = bool(
            switch_result.success
            and switch_result.new_feed_validated
            and switch_result.active_symbol_committed
            and switch_result.old_feed_detached
            and switch_result.pipeline_resumed
            and final_active == proposal.proposed_symbol
            and getattr(self.manager, "active_runtime_id", None)
        )
        status = (AutoSelectionCycleStatus.COMPLETED if synchronized
                  else AutoSelectionCycleStatus.FAILED)
        reasons = tuple(reason.value for reason in switch_result.reason_codes)
        if switch_result.success and not synchronized:
            reasons = ("MARKET_INTELLIGENCE_SYNCHRONIZATION_UNCONFIRMED",)
        result = self._result(
            cycle_id, started, status, reasons, final_active=final_active,
            switch=switch_result, **common,
        )
        return self._finish(
            result, scanner=scanner_result, ranking=ranking, audit=audit,
            proposal=proposal, switch=switch_result,
        )

    def _default_safe_switch(self):
        adapter = BotManagerSwitchRuntime(
            self.manager, position_provider=self.position_provider,
            mm_provider=self.capital_provider,
            emergency_provider=self.emergency_provider, clock=self.clock,
        )
        return SafeSymbolSwitch(adapter)

    def _paper_safety_reason(self):
        config = getattr(self.manager, "config", None)
        if not isinstance(config, dict):
            return "AUTO_SELECTION_MODE_UNAVAILABLE"
        mode = str(config.get("tradeMode", config.get("mode", ""))).strip().lower()
        if mode != "paper":
            return "AUTO_SELECTION_PAPER_ONLY"
        if config.get("dryRun", config.get("dry_run")) is not True:
            return "AUTO_SELECTION_DRY_RUN_REQUIRED"
        return None

    def _active_symbol(self):
        value = getattr(self.manager, "activeSymbol", None)
        return str(value).strip().upper() if value else None

    def _finish(self, result, **contracts):
        # Lock serialization makes this the newest completed cycle; rejected
        # concurrent callers never enter this publication path.
        self._last_result = result
        observation = deepcopy(
            getattr(self.manager, "auto_market_selection_observation", None)
        ) or {}
        observation["autoSelectionCycle"] = result.to_dict()
        names = {
            "scanner": "scannerResult", "ranking": "rankingResult",
            "audit": "auditEvent", "proposal": "selectionProposal",
            "switch": "switchResult",
        }
        for key, value in contracts.items():
            if value is not None:
                observation[names[key]] = value.to_dict()
        publisher = getattr(self.manager, "set_auto_market_selection_observation", None)
        if callable(publisher):
            publisher(observation)
        return result

    def _result(self, cycle_id, started, status, reasons, *, active,
                scanner=None, ranking=None, audit=None, proposal=None,
                switch=None, final_active=None, mode=AutoSelectionRuntimeMode.AUTO_PAPER,
                publish=True):
        del publish
        return AutoSelectionCycleResult(
            cycle_id, started, _utc(self.clock()), mode, active,
            ranking.top_candidate.symbol if ranking and ranking.top_candidate else None,
            proposal.proposed_symbol if proposal else None,
            final_active if final_active is not None else self._active_symbol(),
            scanner.scanner_cycle_id if scanner else None,
            ranking.ranking_cycle_id if ranking else None,
            audit.event_id if audit else None,
            proposal.selection_proposal_id if proposal else None,
            switch.switch_transaction_id if switch else None,
            status, tuple(reasons),
        )

    @staticmethod
    def _cycle_identity(started, active):
        canonical = json.dumps(
            {"startedAt": _time(started), "currentActiveSymbol": active},
            sort_keys=True, separators=(",", ":"),
        )
        return "ams-4a-" + sha256(canonical.encode("utf-8")).hexdigest()[:20]
