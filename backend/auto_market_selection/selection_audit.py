"""AMS-1D deterministic, read-only selection audit event contract."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping, Optional, Tuple

from backend.market.kucoin_futures_public import MarketUniverseSnapshot
from backend.money_management.capital_eligibility import CapitalEligibilityContract
from .candidate_ranking import RankingCandidate, RankingCycleResult
from .market_scanner import ScannerCandidate, ScannerCycleResult

SELECTION_AUDIT_EVENT_TYPE = "AUTO_MARKET_SELECTION_CYCLE"


def _encoded(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise TypeError("timezone-aware datetime required")
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encoded(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _encoded(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _reasons(values):
    return tuple(item.value if isinstance(item, Enum) else str(item) for item in values)


@dataclass(frozen=True)
class CandidateAuditEntry:
    symbol: str
    exchange_symbol: str
    scanner_eligible: bool
    scanner_rejection_reasons: Tuple[str, ...]
    capital_reason_codes: Tuple[str, ...]
    ranking_eligible: bool
    ranking_reason_codes: Tuple[str, ...]
    ranking_score: Optional[Decimal]
    rank: Optional[int]
    spread_percent: Optional[Decimal]
    top_book_liquidity: Optional[Decimal]
    activity_metric: Optional[Decimal]
    effective_weights: Optional[Mapping[str, object]]
    ranking_features: Optional[Mapping[str, object]]

    def to_dict(self):
        return {
            "symbol": self.symbol, "exchangeSymbol": self.exchange_symbol,
            "scannerEligible": self.scanner_eligible,
            "scannerRejectionReasons": list(self.scanner_rejection_reasons),
            "capitalReasonCodes": list(self.capital_reason_codes),
            "rankingEligible": self.ranking_eligible,
            "rankingReasonCodes": list(self.ranking_reason_codes),
            "rankingScore": _encoded(self.ranking_score), "rank": self.rank,
            "spreadPercent": _encoded(self.spread_percent),
            "topBookLiquidity": _encoded(self.top_book_liquidity),
            "activityMetric": _encoded(self.activity_metric),
            "effectiveWeights": _encoded(self.effective_weights),
            "rankingFeatures": _encoded(self.ranking_features),
        }


@dataclass(frozen=True)
class RejectedCandidateAuditEntry:
    symbol: str
    stage: str
    reason_codes: Tuple[str, ...]
    capital_reason_codes: Tuple[str, ...]

    def to_dict(self):
        return {"symbol": self.symbol, "stage": self.stage,
                "reasonCodes": list(self.reason_codes),
                "capitalReasonCodes": list(self.capital_reason_codes)}


@dataclass(frozen=True)
class SelectionAuditEvent:
    event_id: str
    event_type: str
    scanner_cycle_id: str
    ranking_cycle_id: str
    started_at: datetime
    evaluated_at: datetime
    timestamps: Mapping[str, Optional[datetime]]
    capital_snapshot: Mapping[str, object]
    universe_summary: Mapping[str, object]
    scanner_summary: Mapping[str, object]
    ranking_summary: Mapping[str, object]
    candidates: Tuple[CandidateAuditEntry, ...]
    rejected_candidates: Tuple[RejectedCandidateAuditEntry, ...]
    top_candidate: Optional[Mapping[str, object]]
    selection_committed: bool = False

    def to_dict(self):
        return {
            "eventId": self.event_id, "eventType": self.event_type,
            "scannerCycleId": self.scanner_cycle_id,
            "rankingCycleId": self.ranking_cycle_id,
            "startedAt": _encoded(self.started_at), "evaluatedAt": _encoded(self.evaluated_at),
            "timestamps": _encoded(self.timestamps),
            "capitalSnapshot": _encoded(self.capital_snapshot),
            "universeSummary": _encoded(self.universe_summary),
            "scannerSummary": _encoded(self.scanner_summary),
            "rankingSummary": _encoded(self.ranking_summary),
            "candidates": [item.to_dict() for item in self.candidates],
            "rejectedCandidates": [item.to_dict() for item in self.rejected_candidates],
            "topCandidate": _encoded(self.top_candidate),
            "selectionCommitted": self.selection_committed,
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))


def _candidate_entry(scanner: ScannerCandidate, ranking: Optional[RankingCandidate]):
    features = ranking.ranking_features if ranking else None
    return CandidateAuditEntry(
        scanner.symbol, scanner.exchange_symbol, scanner.scanner_eligible,
        _reasons(scanner.rejection_reasons), tuple(scanner.capital_reason_codes),
        bool(ranking and ranking.ranking_eligible),
        _reasons(ranking.ranking_reason_codes) if ranking else (),
        ranking.ranking_score if ranking else None, ranking.rank if ranking else None,
        features.raw_spread_percent if features else scanner.spread_percent,
        features.raw_top_book_liquidity if features else None,
        features.raw_activity_metric if features else scanner.activity_metric,
        features.effective_weights.to_dict() if features and features.effective_weights else None,
        features.to_dict() if features else None,
    )


def _validate(universe, capital, scanner, ranking):
    if not isinstance(universe, MarketUniverseSnapshot):
        raise TypeError("MarketUniverseSnapshot required")
    if not isinstance(capital, CapitalEligibilityContract):
        raise TypeError("CapitalEligibilityContract required")
    if not isinstance(scanner, ScannerCycleResult):
        raise TypeError("ScannerCycleResult required")
    if not isinstance(ranking, RankingCycleResult):
        raise TypeError("RankingCycleResult required")
    if ranking.scanner_cycle_id != scanner.scanner_cycle_id:
        raise ValueError("ranking scannerCycleId mismatch")
    if ranking.scanner_evaluated_at != scanner.evaluated_at:
        raise ValueError("ranking scanner evaluatedAt mismatch")
    if scanner.capital_eligibility_contract != capital:
        raise ValueError("MM authority snapshot mismatch")
    if scanner.mm_evaluated_at != capital.evaluated_at:
        raise ValueError("MM evaluatedAt mismatch")
    if scanner.universe_evaluated_at != universe.evaluated_at:
        raise ValueError("Universe evaluatedAt mismatch")
    if scanner.universe_count != len(universe.contracts):
        raise ValueError("Universe count mismatch")
    universe_symbols = {item.canonical_symbol for item in universe.contracts}
    scanner_all = scanner.candidates + scanner.rejections
    scanner_symbols = [item.symbol for item in scanner_all]
    if len(scanner_symbols) != len(set(scanner_symbols)) or set(scanner_symbols) != universe_symbols:
        raise ValueError("unexpected scanner candidate symbol")
    if (scanner.evaluated_count != len(scanner_all)
            or scanner.eligible_count != len(scanner.candidates)
            or scanner.rejected_count != len(scanner.rejections)):
        raise ValueError("scanner candidate count mismatch")
    eligible_symbols = {item.symbol for item in scanner.candidates if item.scanner_eligible}
    ranking_symbols = [item.symbol for item in ranking.evaluated_candidates]
    if len(ranking_symbols) != len(set(ranking_symbols)) or set(ranking_symbols) != eligible_symbols:
        raise ValueError("ranking candidate not present in scanner input")
    ranked_symbols = [item.symbol for item in ranking.ranked_candidates]
    if len(ranked_symbols) != len(set(ranked_symbols)) or not set(ranked_symbols) <= set(ranking_symbols):
        raise ValueError("unexpected ranked candidate symbol")
    if (ranking.input_candidate_count != len(ranking.evaluated_candidates)
            or ranking.ranked_candidate_count != len(ranking.ranked_candidates)):
        raise ValueError("ranking candidate count mismatch")
    expected_top = ranking.ranked_candidates[0] if ranking.ranked_candidates else None
    if ranking.top_candidate != expected_top or (expected_top and expected_top.rank != 1):
        raise ValueError("topCandidate inconsistent with rank 1")
    if tuple(item.rank for item in ranking.ranked_candidates) != tuple(range(1, len(ranking.ranked_candidates) + 1)):
        raise ValueError("ranked candidate rank sequence invalid")


def build_selection_audit_event(universe_snapshot, capital_eligibility,
                                scanner_result, ranking_result):
    """Build an informational event from supplied snapshots; performs no I/O."""
    _validate(universe_snapshot, capital_eligibility, scanner_result, ranking_result)
    scanner_by_symbol = {item.symbol: item for item in scanner_result.candidates + scanner_result.rejections}
    ranking_by_symbol = {item.symbol: item for item in ranking_result.evaluated_candidates}
    ranked_symbols = [item.symbol for item in ranking_result.ranked_candidates]
    ranking_rejected = sorted(set(ranking_by_symbol) - set(ranked_symbols))
    scanner_rejected = sorted(item.symbol for item in scanner_result.rejections)
    candidates = tuple(_candidate_entry(scanner_by_symbol[s], ranking_by_symbol.get(s))
                       for s in ranked_symbols + ranking_rejected + scanner_rejected)
    rejected = tuple(
        RejectedCandidateAuditEntry(s, "RANKING", _reasons(ranking_by_symbol[s].ranking_reason_codes),
                                    tuple(scanner_by_symbol[s].capital_reason_codes))
        for s in ranking_rejected
    ) + tuple(
        RejectedCandidateAuditEntry(s, "SCANNER", _reasons(scanner_by_symbol[s].rejection_reasons),
                                    tuple(scanner_by_symbol[s].capital_reason_codes))
        for s in scanner_rejected
    )
    top = None if ranking_result.top_candidate is None else {
        "symbol": ranking_result.top_candidate.symbol,
        "score": _encoded(ranking_result.top_candidate.ranking_score),
        "rank": ranking_result.top_candidate.rank,
    }
    fields = dict(
        event_type=SELECTION_AUDIT_EVENT_TYPE,
        scanner_cycle_id=scanner_result.scanner_cycle_id,
        ranking_cycle_id=ranking_result.ranking_cycle_id,
        started_at=scanner_result.started_at, evaluated_at=ranking_result.evaluated_at,
        timestamps={"universeEvaluatedAt": scanner_result.universe_evaluated_at,
                    "tickerEvaluatedAt": scanner_result.ticker_evaluated_at,
                    "mmEvaluatedAt": scanner_result.mm_evaluated_at,
                    "scannerEvaluatedAt": scanner_result.evaluated_at,
                    "rankingEvaluatedAt": ranking_result.evaluated_at},
        capital_snapshot=capital_eligibility.to_dict(),
        universe_summary={"universeCount": len(universe_snapshot.contracts),
                          "tradableCount": sum(item.is_tradable for item in universe_snapshot.contracts),
                          "universeEvaluatedAt": _encoded(universe_snapshot.evaluated_at),
                          "universeFresh": universe_snapshot.freshness == "FRESH"},
        scanner_summary={"scannerCycleId": scanner_result.scanner_cycle_id,
                         "scannerStatus": scanner_result.status.value,
                         "evaluatedCount": scanner_result.evaluated_count,
                         "eligibleCount": scanner_result.eligible_count,
                         "rejectedCount": scanner_result.rejected_count,
                         "globalRejectionReasons": list(_reasons(scanner_result.global_rejection_reasons))},
        ranking_summary={"rankingCycleId": ranking_result.ranking_cycle_id,
                         "rankingStatus": ranking_result.status.value,
                         "inputCandidateCount": ranking_result.input_candidate_count,
                         "rankedCandidateCount": ranking_result.ranked_candidate_count,
                         "topCandidateSymbol": top["symbol"] if top else None,
                         "topCandidateScore": top["score"] if top else None},
        candidates=candidates, rejected_candidates=rejected, top_candidate=top,
    )
    payload = SelectionAuditEvent(event_id="", **fields).to_dict()
    payload.pop("eventId")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    event_id = "ams-1d-" + sha256(canonical.encode("utf-8")).hexdigest()[:20]
    return SelectionAuditEvent(event_id=event_id, **fields)
