"""Orchestration of one deterministic canonical AUTO selection cycle."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
import threading
from typing import Optional, Tuple

from .bot_manager_switch_runtime import (
    BotManagerSwitchRuntime, InitialBotManagerCommitRuntime,
)
from .candidate_ranking import CandidateRankingEngine
from .market_scanner import (
    DEFAULT_SNAPSHOT_MAX_AGE, MarketScanner, ScannerInput, ScannerStatus,
)
from .safe_switch import InitialSymbolCommit, SafeSymbolSwitch, SwitchState
from .selection_audit import build_selection_audit_event
from .selection_proposal import build_selection_proposal, snapshot_active_symbol_authority


class AutoSelectionRuntimeMode(str, Enum):
    MANUAL = "MANUAL"
    AUTO_PAPER = "AUTO_PAPER"
    AUTO_LIVE = "AUTO_LIVE"


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
class FreshSelectionSnapshot:
    """Immutable completed observation snapshot reused by START.

    Holds the authoritative scan/rank/audit/capital objects produced by the
    read-only observer.  Reuse never promotes topCandidate to activeSymbol;
    the canonical commit authority still runs from this snapshot.
    """

    evaluated_at: datetime
    capital: object
    scanner_result: object
    ranking: object
    audit: object
    top_candidate_symbol: Optional[str]


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
    """Connect existing AMS contracts for exactly one AUTO selection cycle.

    Providers are authoritative I/O boundaries. This class does not calculate
    MM eligibility, ranking scores, execution decisions, or orders.  LIVE is
    admitted only as a disarmed monitoring runtime; selection never grants
    order-entry authority.
    """

    def __init__(
        self, bot_manager, *, universe_provider, ticker_provider, capital_provider,
        eligibility_provider, position_provider, pending_order_provider,
        emergency_provider, scanner=None, ranking_engine=None,
        safe_switch_factory=None, initial_commit_factory=None, clock=None,
        skip_cooldown_seconds=300, snapshot_max_age=None,
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
        self.initial_commit_factory = initial_commit_factory or self._default_initial_commit
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._cycle_lock = threading.Lock()
        self._last_result = None
        self._skip_cooldown_seconds = skip_cooldown_seconds
        self._temporary_skips = {}
        self._skip_lock = threading.Lock()
        self._snapshot_max_age = snapshot_max_age or DEFAULT_SNAPSHOT_MAX_AGE
        self._fresh_snapshot = None

    def record_temporary_skip(self, symbol, *, now=None):
        """Temporarily exclude a symbol from the next selection preview/commit.

        A skip is a bounded cooldown, never a permanent blacklist.  Expired
        skips are dropped lazily on read.
        """
        normalized = str(symbol).strip().upper() if symbol else None
        if not normalized:
            return None
        evaluated = _utc(now or self.clock())
        with self._skip_lock:
            self._temporary_skips[normalized] = evaluated + timedelta(
                seconds=self._skip_cooldown_seconds
            )
        return normalized

    def active_temporary_skips(self, *, now=None):
        evaluated = _utc(now or self.clock())
        with self._skip_lock:
            expired = [
                symbol for symbol, until in self._temporary_skips.items()
                if until <= evaluated
            ]
            for symbol in expired:
                del self._temporary_skips[symbol]
            return frozenset(self._temporary_skips)

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

    def observe_cycle(self, *, started_at=None):
        """Read-only observation refresh.

        Refreshes universe → scanner → ranking → eligibility → top-candidate
        preview and publishes a fresh snapshot.  It never builds a proposal,
        never switches the active symbol, and never creates or commits an
        order, so a STOPPED bot keeps an up-to-date selection preview.
        """
        started = _utc(started_at or self.clock())
        if not self._cycle_lock.acquire(blocking=False):
            return {"accepted": False,
                    "reasonCodes": ["AUTO_SELECTION_ALREADY_IN_PROGRESS"],
                    "topCandidateSymbol": None, "evaluatedAt": None}
        try:
            safety_reason = self._safety_reason()
            if safety_reason:
                self._fresh_snapshot = None
                return {"accepted": False, "reasonCodes": [safety_reason],
                        "topCandidateSymbol": None, "evaluatedAt": None}
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
            update = {
                "scannerResult": scanner_result.to_dict(),
                "selectionObservation": {
                    "evaluatedAt": _time(evaluated),
                    "topCandidateSymbol": None,
                    "readOnly": True,
                },
            }
            self._fresh_snapshot = None
            if scanner_result.status is ScannerStatus.CANDIDATES_AVAILABLE:
                ranking = self._rank(
                    scanner_result, evaluated_at=evaluated,
                    excluded_symbols=self.active_temporary_skips(now=evaluated),
                )
                update["rankingResult"] = ranking.to_dict()
                if ranking.top_candidate is not None:
                    audit = build_selection_audit_event(
                        universe, capital, scanner_result, ranking,
                    )
                    update["auditEvent"] = audit.to_dict()
                    update["selectionObservation"]["topCandidateSymbol"] = (
                        ranking.top_candidate.symbol
                    )
                    self._fresh_snapshot = FreshSelectionSnapshot(
                        evaluated_at=evaluated, capital=capital,
                        scanner_result=scanner_result, ranking=ranking,
                        audit=audit,
                        top_candidate_symbol=ranking.top_candidate.symbol,
                    )
            self._publish_observation(update)
            top = update["selectionObservation"]["topCandidateSymbol"]
            return {"accepted": True, "reasonCodes": [],
                    "topCandidateSymbol": top, "evaluatedAt": _time(evaluated)}
        except Exception:
            self._fresh_snapshot = None
            return {"accepted": False,
                    "reasonCodes": ["AUTO_SELECTION_OBSERVATION_FAILED"],
                    "topCandidateSymbol": None, "evaluatedAt": None}
        finally:
            self._cycle_lock.release()

    def request_skip_and_reselect(self, *, started_at=None):
        """Temporarily skip the active symbol and select the next candidate.

        A running bot commits the next eligible candidate through the existing
        SafeSwitch authority.  A stopped bot only refreshes the read-only
        selection preview (no switch, no order).  The skipped symbol is never
        blacklisted permanently: it is only suppressed for a bounded cooldown.
        """
        started = _utc(started_at or self.clock())
        active = self._active_symbol()
        if active is None:
            return {"accepted": False, "reasonCodes": ["ACTIVE_SYMBOL_UNAVAILABLE"],
                    "skippedSymbol": None, "runtime": self.get_status(), "result": None}
        safety_reason = self._safety_reason()
        if safety_reason:
            return {"accepted": False, "reasonCodes": [safety_reason],
                    "skippedSymbol": active, "runtime": self.get_status(), "result": None}
        skipped = self.record_temporary_skip(active, now=started)
        running = bool(
            getattr(self.manager, "_running", False)
            and getattr(self.manager, "active_runtime_id", None)
        )
        if running:
            result = self.run_cycle(
                started_at=started,
                excluded_symbols=self.active_temporary_skips(now=started),
                reuse_snapshot=False,
            )
            return {"accepted": True, "reasonCodes": list(result.reason_codes),
                    "skippedSymbol": skipped, "runtime": self.get_status(),
                    "result": result.to_dict()}
        observation = self.observe_cycle(started_at=started)
        return {"accepted": observation.get("accepted", False),
                "reasonCodes": list(observation.get("reasonCodes") or []),
                "skippedSymbol": skipped, "runtime": self.get_status(), "result": None}

    def _publish_observation(self, update):
        observation = deepcopy(
            getattr(self.manager, "auto_market_selection_observation", None)
        ) or {}
        observation.update(update)
        publisher = getattr(self.manager, "set_auto_market_selection_observation", None)
        if callable(publisher):
            publisher(observation)

    def run_cycle(self, *, started_at=None, excluded_symbols=None, reuse_snapshot=True):
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
            safety_reason = self._safety_reason()
            if safety_reason:
                return self._finish(self._result(
                    cycle_id, started, AutoSelectionCycleStatus.FAILED,
                    (safety_reason,), active=active,
                    mode=AutoSelectionRuntimeMode.MANUAL,
                ))
            return self._run_locked(
                cycle_id, started, active, excluded_symbols=excluded_symbols,
                reuse_snapshot=reuse_snapshot,
            )
        except Exception:
            return self._finish(self._result(
                cycle_id, started, AutoSelectionCycleStatus.FAILED,
                ("AUTO_SELECTION_INPUT_UNAVAILABLE",), active=active,
            ))
        finally:
            self._cycle_lock.release()

    def _run_locked(self, cycle_id, started, active, *, excluded_symbols=None,
                    reuse_snapshot=True):
        snapshot = self._valid_fresh_snapshot(started) if reuse_snapshot else None
        if snapshot is not None:
            return self._propose_and_commit(
                cycle_id, started, active,
                capital=snapshot.capital,
                scanner_result=snapshot.scanner_result,
                ranking=snapshot.ranking,
                audit=snapshot.audit,
            )

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

        ranking = self._rank(
            scanner_result, evaluated_at=evaluated,
            excluded_symbols=self._merged_exclusions(excluded_symbols, evaluated),
        )
        if ranking.top_candidate is None:
            return self._finish(self._result(
                cycle_id, started, AutoSelectionCycleStatus.NO_RANKABLE_MARKET,
                tuple(reason.value for reason in ranking.reason_codes),
                active=active, scanner=scanner_result, ranking=ranking,
            ), scanner=scanner_result, ranking=ranking)

        audit = build_selection_audit_event(universe, capital, scanner_result, ranking)
        return self._propose_and_commit(
            cycle_id, started, active,
            capital=capital, scanner_result=scanner_result,
            ranking=ranking, audit=audit,
        )

    def _valid_fresh_snapshot(self, now):
        """Return a reusable snapshot only when it is fresh and still valid.

        Reuse is rejected (falling back to a full scan) when the snapshot is
        missing, when its evaluated_at is absent or older than the canonical
        AMS snapshot-max-age, or when its top candidate is currently excluded
        by the temporary-skip cooldown.
        """
        snapshot = self._fresh_snapshot
        if snapshot is None:
            return None
        if snapshot.top_candidate_symbol is None:
            return None
        age = (now - _utc(snapshot.evaluated_at)).total_seconds()
        if age < 0 or age > self._snapshot_max_age.total_seconds():
            return None
        if snapshot.top_candidate_symbol in self.active_temporary_skips(now=now):
            return None
        return snapshot

    def _propose_and_commit(self, cycle_id, started, active, *, capital,
                            scanner_result, ranking, audit):
        evaluated = _utc(self.clock())
        position = self.position_provider()
        pending = self.pending_order_provider()
        emergency = self.emergency_provider()
        proposal = build_selection_proposal(
            ranking, audit,
            active_symbol_authority=snapshot_active_symbol_authority(self.manager),
            position_state=position, pending_order_state=pending,
            mm_authority=capital, emergency_safe=emergency,
            proposed_at=evaluated,
            allow_initial_selection=active is None,
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

        switch = (self.initial_commit_factory() if active is None
                  else self.safe_switch_factory())
        switch_result = switch.execute(proposal, started_at=evaluated)
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
        status = (
            AutoSelectionCycleStatus.COMPLETED
            if synchronized
            else AutoSelectionCycleStatus.SWITCH_BLOCKED
            if switch_result.state is SwitchState.NOT_READY
            else AutoSelectionCycleStatus.FAILED
        )
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

    def _rank(self, scanner_result, *, evaluated_at, excluded_symbols=None):
        excluded = frozenset(
            str(item).strip().upper() for item in (excluded_symbols or ())
            if item is not None and str(item).strip()
        )
        if excluded:
            return self.ranking_engine.rank(
                scanner_result, evaluated_at=evaluated_at,
                excluded_symbols=excluded,
            )
        return self.ranking_engine.rank(scanner_result, evaluated_at=evaluated_at)

    def _merged_exclusions(self, explicit, now):
        excluded = set(
            str(item).strip().upper() for item in (explicit or ())
            if item is not None and str(item).strip()
        )
        excluded.update(self.active_temporary_skips(now=now))
        return frozenset(excluded)

    def _default_safe_switch(self):
        adapter = BotManagerSwitchRuntime(
            self.manager, position_provider=self.position_provider,
            mm_provider=self.capital_provider,
            emergency_provider=self.emergency_provider, clock=self.clock,
            allow_live_monitoring=self._auto_mode() is AutoSelectionRuntimeMode.AUTO_LIVE,
        )
        return SafeSymbolSwitch(adapter)

    def _default_initial_commit(self):
        adapter = InitialBotManagerCommitRuntime(
            self.manager, position_provider=self.position_provider,
            mm_provider=self.capital_provider,
            emergency_provider=self.emergency_provider, clock=self.clock,
            allow_live_monitoring=self._auto_mode() is AutoSelectionRuntimeMode.AUTO_LIVE,
        )
        return InitialSymbolCommit(adapter)

    def _safety_reason(self):
        config = getattr(self.manager, "config", None)
        if not isinstance(config, dict):
            return "AUTO_SELECTION_MODE_UNAVAILABLE"
        mode = str(config.get("mode", config.get("tradeMode", "paper"))).strip().lower()
        dry_run = config.get("dryRun", config.get("dry_run", True))
        if mode == "live":
            if dry_run is not False:
                return "AUTO_SELECTION_LIVE_DRY_RUN_FORBIDDEN"
            if not all((
                config.get("liveOrderEntryAllowed") is False,
                config.get("realOrderAllowed") is False,
                config.get("executionEntryAllowed") is False,
                config.get("autoTradeEnabled", False) is False,
                config.get("executionRealOrderEnabled", False) is False,
            )):
                return "AUTO_SELECTION_LIVE_ENTRY_ARMED"
            return None
        if mode != "paper":
            return "AUTO_SELECTION_MODE_UNSUPPORTED"
        if dry_run is not True:
            return "AUTO_SELECTION_DRY_RUN_REQUIRED"
        return None

    def _auto_mode(self):
        config = getattr(self.manager, "config", None)
        mode = str(config.get("mode", "paper")).strip().lower() if isinstance(
            config, dict
        ) else "paper"
        return (
            AutoSelectionRuntimeMode.AUTO_LIVE
            if mode == "live"
            else AutoSelectionRuntimeMode.AUTO_PAPER
        )

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
                switch=None, final_active=None, mode=None,
                publish=True):
        del publish
        if mode is None:
            mode = self._auto_mode()
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
