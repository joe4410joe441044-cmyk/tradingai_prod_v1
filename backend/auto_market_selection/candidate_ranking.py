"""AMS-1C-R1 deterministic lightweight candidate ranking."""

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Optional, Tuple

from .market_scanner import ScannerCandidate, ScannerCycleResult


SPREAD_WEIGHT = Decimal("0.40")
LIQUIDITY_WEIGHT = Decimal("0.30")
ACTIVITY_WEIGHT = Decimal("0.20")
DATA_QUALITY_WEIGHT = Decimal("0.10")
RANKING_CONTRACT_VERSION = "ams-1c-r1"


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _encoded(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_encoded(item) for item in value]
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _valid_nonnegative(value):
    return isinstance(value, Decimal) and value.is_finite() and value >= 0


def _valid_positive(value):
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def _normalize(value, values, *, inverse=False):
    low, high = min(values), max(values)
    if low == high:
        return Decimal("1")
    if inverse:
        return (high - value) / (high - low)
    return (value - low) / (high - low)


class RankingStatus(str, Enum):
    RANKED_CANDIDATES_AVAILABLE = "RANKED_CANDIDATES_AVAILABLE"
    NO_RANKABLE_MARKET = "NO_RANKABLE_MARKET"


class RankingReason(str, Enum):
    RANKING_DATA_INCOMPLETE = "RANKING_DATA_INCOMPLETE"
    INVALID_RANKING_FEATURE = "INVALID_RANKING_FEATURE"
    NO_RANKABLE_MARKET = "NO_RANKABLE_MARKET"


@dataclass(frozen=True)
class EffectiveWeights:
    spread: Decimal
    liquidity: Decimal
    activity: Optional[Decimal]
    data_quality: Optional[Decimal]

    def to_dict(self):
        return {
            "spread": _encoded(self.spread),
            "liquidity": _encoded(self.liquidity),
            "activity": _encoded(self.activity),
            "dataQuality": _encoded(self.data_quality),
        }


@dataclass(frozen=True)
class RankingFeatures:
    best_bid: Optional[Decimal]
    best_ask: Optional[Decimal]
    bid_size: Optional[Decimal]
    ask_size: Optional[Decimal]
    raw_spread: Optional[Decimal]
    raw_spread_percent: Optional[Decimal]
    spread_score: Optional[Decimal]
    raw_top_book_liquidity: Optional[Decimal]
    liquidity_score: Optional[Decimal]
    raw_activity_metric: Optional[Decimal]
    activity_score: Optional[Decimal]
    data_quality_score: Optional[Decimal]
    effective_weights: Optional[EffectiveWeights]
    capital_eligible: bool

    def to_dict(self):
        return {
            "bestBid": _encoded(self.best_bid),
            "bestAsk": _encoded(self.best_ask),
            "bidSize": _encoded(self.bid_size),
            "askSize": _encoded(self.ask_size),
            "rawSpread": _encoded(self.raw_spread),
            "rawSpreadPercent": _encoded(self.raw_spread_percent),
            "spreadScore": _encoded(self.spread_score),
            "rawTopBookLiquidity": _encoded(self.raw_top_book_liquidity),
            "liquidityScore": _encoded(self.liquidity_score),
            "rawActivityMetric": _encoded(self.raw_activity_metric),
            "activityScore": _encoded(self.activity_score),
            "dataQualityScore": _encoded(self.data_quality_score),
            "effectiveWeights": _encoded(self.effective_weights),
            "capitalEligible": self.capital_eligible,
        }


@dataclass(frozen=True)
class RankingCandidate:
    symbol: str
    scanner_eligible: bool
    ranking_features: RankingFeatures
    ranking_score: Optional[Decimal]
    rank: Optional[int]
    ranking_eligible: bool
    ranking_reason_codes: Tuple[RankingReason, ...]
    evaluated_at: datetime

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "scannerEligible": self.scanner_eligible,
            "rankingFeatures": self.ranking_features.to_dict(),
            "rankingScore": _encoded(self.ranking_score),
            "rank": self.rank,
            "rankingEligible": self.ranking_eligible,
            "rankingReasonCodes": _encoded(self.ranking_reason_codes),
            "evaluatedAt": _encoded(self.evaluated_at),
        }


@dataclass(frozen=True)
class RankingCycleResult:
    ranking_cycle_id: str
    scanner_cycle_id: str
    scanner_evaluated_at: datetime
    started_at: datetime
    evaluated_at: datetime
    input_candidate_count: int
    ranked_candidate_count: int
    evaluated_candidates: Tuple[RankingCandidate, ...]
    ranked_candidates: Tuple[RankingCandidate, ...]
    top_candidate: Optional[RankingCandidate]
    status: RankingStatus
    reason_codes: Tuple[RankingReason, ...]
    ranking_contract_version: str = RANKING_CONTRACT_VERSION

    def to_dict(self):
        return {
            "rankingCycleId": self.ranking_cycle_id,
            "scannerCycleId": self.scanner_cycle_id,
            "scannerEvaluatedAt": _encoded(self.scanner_evaluated_at),
            "startedAt": _encoded(self.started_at),
            "evaluatedAt": _encoded(self.evaluated_at),
            "inputCandidateCount": self.input_candidate_count,
            "rankedCandidateCount": self.ranked_candidate_count,
            "evaluatedCandidates": [item.to_dict() for item in self.evaluated_candidates],
            "rankedCandidates": [item.to_dict() for item in self.ranked_candidates],
            "topCandidate": _encoded(self.top_candidate),
            "status": self.status.value,
            "reasonCodes": _encoded(self.reason_codes),
            "rankingContractVersion": self.ranking_contract_version,
        }


@dataclass(frozen=True)
class MarketScoreComparison:
    candidate_symbol: Optional[str]
    candidate_score: Optional[Decimal]
    active_symbol: Optional[str]
    active_market_score: Optional[Decimal]
    scanner_cycle_id: Optional[str]
    ranking_cycle_id: Optional[str]
    ranking_contract_version: Optional[str]
    comparison_id: Optional[str]
    unavailable_reason: Optional[str]


class CandidateRankingEngine:
    """Pure ranking over the eligible candidates in one scanner cycle."""

    def rank(self, scanner_result: ScannerCycleResult, *, evaluated_at=None):
        if not isinstance(scanner_result, ScannerCycleResult):
            raise TypeError("ScannerCycleResult required")
        now = _utc(evaluated_at or scanner_result.evaluated_at)
        if now < _utc(scanner_result.evaluated_at):
            raise ValueError("ranking evaluated_at cannot precede scanner evaluated_at")

        scanner_eligible = tuple(sorted(
            (item for item in scanner_result.candidates if item.scanner_eligible),
            key=lambda item: item.symbol,
        ))
        extracted = tuple(self._extract(item, now) for item in scanner_eligible)
        rankable = tuple(item for item in extracted if item.ranking_eligible)
        scored = self._score(rankable)
        ordered = tuple(sorted(scored, key=self._sort_key))
        ranked = tuple(replace(item, rank=index) for index, item in enumerate(ordered, 1))
        ranked_by_symbol = {item.symbol: item for item in ranked}
        evaluated = tuple(ranked_by_symbol.get(item.symbol, item) for item in extracted)

        if ranked:
            status = RankingStatus.RANKED_CANDIDATES_AVAILABLE
            reasons = ()
        else:
            status = RankingStatus.NO_RANKABLE_MARKET
            reasons = (RankingReason.NO_RANKABLE_MARKET,)

        payload = {
            "scannerCycleId": scanner_result.scanner_cycle_id,
            "scannerEvaluatedAt": _encoded(scanner_result.evaluated_at),
            "startedAt": _encoded(now),
            "evaluatedAt": _encoded(now),
            "evaluatedCandidates": [item.to_dict() for item in evaluated],
            "rankedCandidates": [item.to_dict() for item in ranked],
            "status": status.value,
            "reasonCodes": _encoded(reasons),
        }
        identity = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        cycle_id = "ams-1c-" + sha256(identity.encode("utf-8")).hexdigest()[:20]
        return RankingCycleResult(
            cycle_id, scanner_result.scanner_cycle_id,
            _utc(scanner_result.evaluated_at), now, now, len(extracted), len(ranked),
            evaluated, ranked, ranked[0] if ranked else None, status, reasons,
        )

    def compare_active_market(self, scanner_result, ranking_result, active_symbol):
        """Score challenger and active from one authoritative observation.

        Challenger eligibility remains owned by ``rank``.  A rejected active
        market may participate only in this comparison population when its
        same-cycle market features are complete and its rejection is limited
        to capital/eligibility gating.
        """
        unavailable = lambda reason: MarketScoreComparison(
            getattr(getattr(ranking_result, "top_candidate", None), "symbol", None),
            None, active_symbol, None,
            getattr(scanner_result, "scanner_cycle_id", None),
            getattr(ranking_result, "ranking_cycle_id", None),
            getattr(ranking_result, "ranking_contract_version", None),
            None, reason,
        )
        if not isinstance(scanner_result, ScannerCycleResult):
            return unavailable("SCANNER_RESULT_UNAVAILABLE")
        if not isinstance(ranking_result, RankingCycleResult):
            return unavailable("RANKING_RESULT_UNAVAILABLE")
        if (
            ranking_result.scanner_cycle_id != scanner_result.scanner_cycle_id
            or ranking_result.scanner_evaluated_at != scanner_result.evaluated_at
        ):
            return unavailable("SCANNER_RANKING_CYCLE_MISMATCH")
        if ranking_result.ranking_contract_version != RANKING_CONTRACT_VERSION:
            return unavailable("RANKING_CONTRACT_MISMATCH")
        if not ranking_result.top_candidate or not active_symbol:
            return unavailable("COMPARISON_SYMBOL_UNAVAILABLE")

        active = str(active_symbol).strip().upper()
        observations = scanner_result.candidates + scanner_result.rejections
        active_observation = next(
            (item for item in observations if item.symbol == active), None,
        )
        if active_observation is None:
            return unavailable("ACTIVE_MARKET_NOT_IN_SCANNER_CYCLE")
        disallowed_rejections = {
            reason for reason in active_observation.rejection_reasons
            if reason.value not in {
                "CAPITAL_INELIGIBLE", "POSITION_CAPACITY_EXHAUSTED",
                "ELIGIBILITY_UNAVAILABLE",
            }
        }
        if disallowed_rejections:
            return unavailable("ACTIVE_MARKET_OBSERVATION_INVALID")
        if active_observation.evaluated_at != scanner_result.evaluated_at:
            return unavailable("ACTIVE_MARKET_OBSERVATION_STALE")

        active_extracted = self._extract(active_observation, ranking_result.evaluated_at)
        if active_extracted.ranking_reason_codes:
            return unavailable("ACTIVE_MARKET_RANKING_DATA_INCOMPLETE")
        reference = tuple(
            item for item in ranking_result.evaluated_candidates
            if item.ranking_eligible and not item.ranking_reason_codes
        )
        if not reference:
            return unavailable("CHALLENGER_SCORE_UNAVAILABLE")
        if any(item.evaluated_at != ranking_result.evaluated_at for item in reference):
            return unavailable("CANDIDATE_OBSERVATION_STALE")
        scanner_candidates = {item.symbol: item for item in scanner_result.candidates}
        for item in reference:
            source = scanner_candidates.get(item.symbol)
            features = item.ranking_features
            if source is None or (
                features.best_bid != source.best_bid
                or features.best_ask != source.best_ask
                or features.bid_size != source.bid_size
                or features.ask_size != source.ask_size
                or features.raw_spread != source.spread
                or features.raw_spread_percent != source.spread_percent
                or features.raw_activity_metric != source.activity_metric
            ):
                return unavailable("CANDIDATE_FEATURE_SNAPSHOT_MISMATCH")

        comparison_population = reference
        if all(item.symbol != active for item in reference):
            comparison_population += (active_extracted,)
        scored = self._score(comparison_population)
        candidate = next(
            (item for item in scored
             if item.symbol == ranking_result.top_candidate.symbol), None,
        )
        active_scored = next((item for item in scored if item.symbol == active), None)
        if not candidate or not active_scored:
            return unavailable("COMPARISON_SCORE_UNAVAILABLE")
        if not all(
            isinstance(item.ranking_score, Decimal)
            and item.ranking_score.is_finite()
            for item in (candidate, active_scored)
        ):
            return unavailable("COMPARISON_SCORE_INVALID")
        identity = json.dumps({
            "activeMarket": active,
            "candidateSymbol": candidate.symbol,
            "candidateScore": _encoded(candidate.ranking_score),
            "activeMarketScore": _encoded(active_scored.ranking_score),
            "scannerCycleId": scanner_result.scanner_cycle_id,
            "rankingCycleId": ranking_result.ranking_cycle_id,
            "rankingContractVersion": RANKING_CONTRACT_VERSION,
        }, sort_keys=True, separators=(",", ":"))
        return MarketScoreComparison(
            candidate.symbol, candidate.ranking_score,
            active, active_scored.ranking_score,
            scanner_result.scanner_cycle_id, ranking_result.ranking_cycle_id,
            RANKING_CONTRACT_VERSION,
            "ams-score-comparison-" + sha256(identity.encode("utf-8")).hexdigest()[:20],
            None,
        )

    @staticmethod
    def _sort_key(item):
        return (
            -item.ranking_score,
            item.ranking_features.raw_spread_percent,
            -item.ranking_features.raw_top_book_liquidity,
            item.symbol,
        )

    def _extract(self, candidate: ScannerCandidate, now: datetime):
        required_valid = (
            _valid_positive(candidate.best_bid)
            and _valid_positive(candidate.best_ask)
            and candidate.best_ask >= candidate.best_bid
            and _valid_nonnegative(candidate.bid_size)
            and _valid_nonnegative(candidate.ask_size)
            and _valid_nonnegative(candidate.spread)
            and _valid_nonnegative(candidate.spread_percent)
        )
        top_liquidity = (
            min(candidate.bid_size, candidate.ask_size) if required_valid else None
        )
        reasons = []
        if not required_valid:
            reasons.append(RankingReason.RANKING_DATA_INCOMPLETE)
        activity = candidate.activity_metric
        if activity is not None and not _valid_nonnegative(activity):
            reasons.append(RankingReason.INVALID_RANKING_FEATURE)
            activity = None
        features = RankingFeatures(
            candidate.best_bid, candidate.best_ask, candidate.bid_size,
            candidate.ask_size, candidate.spread, candidate.spread_percent,
            None, top_liquidity, None, activity, None, None, None,
            candidate.capital_eligible,
        )
        eligible = required_valid and candidate.capital_eligible
        return RankingCandidate(
            candidate.symbol, True, features, None, None, eligible,
            tuple(reasons), now,
        )

    def _score(self, candidates):
        if not candidates:
            return ()
        spread_values = tuple(
            item.ranking_features.raw_spread_percent for item in candidates
        )
        liquidity_values = tuple(
            item.ranking_features.raw_top_book_liquidity for item in candidates
        )
        activity_values = tuple(
            item.ranking_features.raw_activity_metric for item in candidates
            if item.ranking_features.raw_activity_metric is not None
        )
        result = []
        for item in candidates:
            features = item.ranking_features
            spread_score = _normalize(
                features.raw_spread_percent, spread_values, inverse=True,
            )
            liquidity_score = _normalize(
                features.raw_top_book_liquidity, liquidity_values,
            )
            activity_score = (
                _normalize(features.raw_activity_metric, activity_values)
                if features.raw_activity_metric is not None else None
            )
            available_weight = SPREAD_WEIGHT + LIQUIDITY_WEIGHT
            if activity_score is not None:
                available_weight += ACTIVITY_WEIGHT
            weights = EffectiveWeights(
                SPREAD_WEIGHT / available_weight,
                LIQUIDITY_WEIGHT / available_weight,
                ACTIVITY_WEIGHT / available_weight if activity_score is not None else None,
                None,
            )
            score = spread_score * weights.spread + liquidity_score * weights.liquidity
            if activity_score is not None:
                score += activity_score * weights.activity
            # Decimal division of repeating proportional weights can leave the
            # mathematical boundary one ulp below 1. Preserve the specified
            # closed score range and exact equal/single-candidate result.
            if all(value == Decimal("1") for value in (
                spread_score, liquidity_score, activity_score
            ) if value is not None):
                score = Decimal("1")
            updated = replace(
                features, spread_score=spread_score,
                liquidity_score=liquidity_score, activity_score=activity_score,
                effective_weights=weights,
            )
            result.append(replace(item, ranking_features=updated, ranking_score=score))
        return tuple(result)
