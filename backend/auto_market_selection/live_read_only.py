"""Live public-market observation for AMS; contains no action boundary."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from inspect import signature
import json
from typing import Mapping, Optional, Tuple

from backend.market.kucoin_futures_public import (
    KucoinFuturesPublicClient, MarketUniverseSnapshot,
    canonicalize_futures_symbol,
)
from backend.money_management.capital_eligibility import (
    CapitalEligibilityContract, evaluate_market_capital_eligibility,
)
from .candidate_ranking import CandidateRankingEngine, RankingStatus
from .market_scanner import (
    MarketScanner, ScannerInput, ScannerStatus, TickerSnapshot,
)
from .selection_audit import build_selection_audit_event
from .selection_proposal import build_selection_proposal


@dataclass(frozen=True)
class LiveReadOnlyObservation:
    timestamp: str
    universe_count: int
    tradable_count: int
    normalized_count: int
    invalid_count: int
    evaluated_count: int
    eligible_count: int
    rejected_count: int
    top_five: Tuple[Mapping[str, object], ...]
    top_score: Optional[str]
    active_symbol: Optional[str]
    top_candidate: Optional[str]
    proposed_symbol: Optional[str]
    switch_eligible_preview: bool
    reason_codes: Tuple[str, ...]
    top_rejection_reasons: Tuple[Mapping[str, object], ...]
    scanner_cycle_id: str
    ranking_cycle_id: str
    audit_event_id: str
    selection_proposal_id: str
    ranked_candidates: Tuple[Mapping[str, object], ...] = ()
    universe_evaluated_at: Optional[str] = None
    ticker_evaluated_at: Optional[str] = None
    ranking_evaluated_at: Optional[str] = None
    mode: str = "LIVE_READ_ONLY"
    candidate_score: Optional[str] = None
    active_market_score: Optional[str] = None
    observation_id: Optional[str] = None

    def to_dict(self):
        return {
            "mode": self.mode, "timestamp": self.timestamp,
            "universeCount": self.universe_count,
            "tradableCount": self.tradable_count,
            "normalizedCount": self.normalized_count,
            "invalidCount": self.invalid_count,
            "evaluatedCount": self.evaluated_count,
            "eligibleCount": self.eligible_count,
            "rejectedCount": self.rejected_count,
            "topFive": [dict(item) for item in self.top_five],
            "topScore": self.top_score, "activeSymbol": self.active_symbol,
            "topCandidate": self.top_candidate,
            "proposedSymbol": self.proposed_symbol,
            "switchEligiblePreview": self.switch_eligible_preview,
            "reasonCodes": list(self.reason_codes),
            "topRejectionReasons": [dict(item) for item in self.top_rejection_reasons],
            "scannerCycleId": self.scanner_cycle_id,
            "rankingCycleId": self.ranking_cycle_id,
            "auditEventId": self.audit_event_id,
            "selectionProposalId": self.selection_proposal_id,
            "observationId": self.observation_id,
            "candidateScore": self.candidate_score,
            "activeMarketScore": self.active_market_score,
            "rankedCandidates": [dict(item) for item in self.ranked_candidates],
            "universeEvaluatedAt": self.universe_evaluated_at,
            "tickerEvaluatedAt": self.ticker_evaluated_at,
            "rankingEvaluatedAt": self.ranking_evaluated_at,
            "actualSwitch": False, "realOrderCreated": False,
        }


class LiveReadOnlyValidation:
    """Observe live public data through completed AMS preview contracts."""

    def __init__(
        self, public_client, *, capital_provider, active_symbol_provider,
        safety_provider, position_provider, pending_order_provider,
        emergency_provider, stop_loss_percent=Decimal("1"),
        effective_cost_percent=Decimal("0.2"), risk_percent=Decimal("0.5"),
        scanner=None, ranking_engine=None, clock=None,
    ):
        if not isinstance(public_client, KucoinFuturesPublicClient):
            raise TypeError("KucoinFuturesPublicClient required")
        providers = (
            capital_provider, active_symbol_provider, safety_provider,
            position_provider, pending_order_provider, emergency_provider,
        )
        if any(not callable(item) for item in providers):
            raise TypeError("Live read-only authority providers required")
        self.client = public_client
        self.capital_provider = capital_provider
        self.active_symbol_provider = active_symbol_provider
        self.safety_provider = safety_provider
        self.position_provider = position_provider
        self.pending_order_provider = pending_order_provider
        self.emergency_provider = emergency_provider
        self.stop_loss_percent = stop_loss_percent
        self.effective_cost_percent = effective_cost_percent
        self.risk_percent = risk_percent
        self.scanner = scanner or MarketScanner()
        self.ranking = ranking_engine or CandidateRankingEngine()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def observe(self):
        self._preflight()
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise TypeError("timezone-aware clock required")
        now = now.astimezone(timezone.utc)
        contracts = self.client.get_active_contracts(evaluated_at=now)
        tickers = self.client.get_all_tickers()
        universe = MarketUniverseSnapshot(contracts, now, "FRESH")
        ticker_snapshot = TickerSnapshot(tickers, now, "FRESH")
        capital = (
            self.capital_provider(now)
            if len(signature(self.capital_provider).parameters) else self.capital_provider()
        )
        if not isinstance(capital, CapitalEligibilityContract):
            raise RuntimeError("LIVE_READ_ONLY_MM_UNAVAILABLE")
        eligibility = {
            item.canonical_symbol: evaluate_market_capital_eligibility(
                item, capital, stop_loss_percent=self.stop_loss_percent,
                effective_cost_percent=self.effective_cost_percent,
                risk_percent=self.risk_percent,
                evaluated_at=now,
            ) for item in contracts
        }
        scanner = self.scanner.scan(ScannerInput(
            universe, ticker_snapshot, capital, eligibility, now, now,
        ))
        ranking = self.ranking.rank(scanner, evaluated_at=now)
        audit = build_selection_audit_event(universe, capital, scanner, ranking)
        active_source = self._symbol(self.active_symbol_provider())
        active = (
            canonicalize_futures_symbol(active_source)
            if active_source else None
        )
        proposal = build_selection_proposal(
            ranking, audit,
            active_symbol_authority={"activeSymbol": active, "selectionMode": "MANUAL"},
            position_state=self.position_provider(),
            pending_order_state=self.pending_order_provider(),
            mm_authority=capital, emergency_safe=self.emergency_provider(),
            proposed_at=now,
        )
        top_five = tuple({
            "rank": item.rank, "symbol": item.symbol,
            "spreadPercent": item.to_dict()["rankingFeatures"]["rawSpreadPercent"],
            "topBookLiquidity": item.to_dict()["rankingFeatures"]["rawTopBookLiquidity"],
            "activityMetric": item.to_dict()["rankingFeatures"]["rawActivityMetric"],
            "effectiveWeights": item.to_dict()["rankingFeatures"]["effectiveWeights"],
            "rankingScore": item.to_dict()["rankingScore"],
        } for item in ranking.ranked_candidates[:5])
        reasons = tuple(dict.fromkeys(
            [reason.value for reason in scanner.global_rejection_reasons]
            + [reason.value for reason in ranking.reason_codes]
            + [reason.value for reason in proposal.reason_codes]
        ))
        rejection_counts = {}
        for item in scanner.rejections:
            for reason in item.rejection_reasons:
                rejection_counts[reason.value] = rejection_counts.get(reason.value, 0) + 1
            for reason in item.capital_reason_codes:
                rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
        top_rejections = tuple(
            {"reason": reason, "count": count}
            for reason, count in sorted(
                rejection_counts.items(), key=lambda pair: (-pair[1], pair[0])
            )[:10]
        )
        normalized = sum(
            bool(canonicalize_futures_symbol(item.exchange_symbol)) for item in contracts
        )
        top = ranking.top_candidate
        comparison = self.ranking.compare_active_market(scanner, ranking, active)
        active_in_universe = any(
            canonicalize_futures_symbol(item.exchange_symbol) == active
            for item in contracts
        )
        active_scanned = next(
            (item for item in scanner.candidates
             if canonicalize_futures_symbol(item.symbol) == active),
            None,
        )
        active_reason = None
        if active and comparison.active_market_score is None:
            if not active_in_universe:
                active_reason = "ACTIVE_MARKET_NOT_IN_UNIVERSE"
            elif active_scanned is None or not active_scanned.scanner_eligible:
                active_reason = "ACTIVE_MARKET_NOT_SCANNER_ELIGIBLE"
            else:
                active_reason = "ACTIVE_MARKET_NOT_RANKABLE"
        if active_reason and active_reason not in reasons:
            reasons = reasons + (active_reason,)
        ranked_candidates = tuple({
            "symbol": item.symbol, "rank": item.rank,
            "rankingScore": item.to_dict()["rankingScore"],
        } for item in ranking.ranked_candidates)
        evaluated_at = now.isoformat().replace("+00:00", "Z")
        observation_complete = all((
            scanner.status is ScannerStatus.CANDIDATES_AVAILABLE,
            ranking.status is RankingStatus.RANKED_CANDIDATES_AVAILABLE,
            ranking.scanner_cycle_id == scanner.scanner_cycle_id,
            ranking.scanner_evaluated_at == scanner.evaluated_at,
            ranking.top_candidate is not None,
            proposal.scanner_cycle_id == scanner.scanner_cycle_id,
            proposal.ranking_cycle_id == ranking.ranking_cycle_id,
            audit.scanner_cycle_id == scanner.scanner_cycle_id,
            audit.ranking_cycle_id == ranking.ranking_cycle_id,
        ))
        observation_id = None
        if observation_complete:
            observation_identity = json.dumps({
                "activeSymbol": active,
                "auditEventId": audit.event_id,
                "rankingCycleId": ranking.ranking_cycle_id,
                "scannerCycleId": scanner.scanner_cycle_id,
                "selectionProposalId": proposal.selection_proposal_id,
                "timestamp": evaluated_at,
            }, sort_keys=True, separators=(",", ":"))
            observation_id = "ams-observation-" + sha256(
                observation_identity.encode("utf-8")
            ).hexdigest()[:24]
        return LiveReadOnlyObservation(
            now.isoformat().replace("+00:00", "Z"), len(contracts),
            sum(item.is_tradable for item in contracts), normalized,
            len(contracts) - normalized, scanner.evaluated_count,
            scanner.eligible_count, scanner.rejected_count, top_five,
            top.to_dict()["rankingScore"] if top else None, active,
            top.symbol if top else None, proposal.proposed_symbol,
            proposal.switch_eligible, reasons, top_rejections, scanner.scanner_cycle_id,
            ranking.ranking_cycle_id, audit.event_id,
            proposal.selection_proposal_id,
            ranked_candidates, evaluated_at, evaluated_at, evaluated_at,
            candidate_score=(
                format(comparison.candidate_score, "f")
                if comparison.candidate_score is not None else None
            ),
            active_market_score=(
                format(comparison.active_market_score, "f")
                if comparison.active_market_score is not None else None
            ),
            observation_id=observation_id,
        )

    def _preflight(self):
        state = self.safety_provider()
        if not isinstance(state, Mapping):
            raise RuntimeError("LIVE_READ_ONLY_PREFLIGHT_UNAVAILABLE")
        firewall = all((
            state.get("realOrderAllowed") is False,
            state.get("executionRealOrderDisabled") is True,
            state.get("autoTradeDisabled") is True,
            state.get("emergencyAvailable") is True,
            state.get("governanceAvailable") is True,
        ))
        legacy_read_only = (
            state.get("dryRun") is True
            and state.get("liveAutoSwitchDisabled") is True
        )
        selection_only = (
            state.get("dryRun") is False
            and state.get("liveSelectionOnly") is True
        )
        stopped_live_monitoring = (
            state.get("dryRun") is False
            and state.get("stoppedLiveMonitoring") is True
            and state.get("liveAutoSwitchDisabled") is True
        )
        if not firewall or not (
                legacy_read_only or selection_only or stopped_live_monitoring):
            raise RuntimeError("LIVE_READ_ONLY_PREFLIGHT_BLOCKED")

    @staticmethod
    def _symbol(value):
        value = str(value or "").strip().upper()
        return value or None
