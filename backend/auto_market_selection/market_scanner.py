"""AMS-1A deterministic Tier 1 -> Tier 2 market scanner.

The scanner consumes public-market and MM-owned snapshots.  It does not fetch
data, rank markets, select an active symbol, or create orders.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Mapping, Optional, Tuple

from backend.market.kucoin_futures_public import (
    FuturesContractMetadata,
    FuturesTicker,
    MarketUniverseSnapshot,
    canonicalize_futures_symbol,
)
from backend.money_management.capital_eligibility import (
    CapitalEligibilityContract,
    PerMarketEligibilityResult,
)


DEFAULT_SNAPSHOT_MAX_AGE = timedelta(minutes=15)


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


class ScannerRejectionReason(str, Enum):
    UNIVERSE_UNAVAILABLE = "UNIVERSE_UNAVAILABLE"
    UNIVERSE_STALE = "UNIVERSE_STALE"
    TICKER_UNAVAILABLE = "TICKER_UNAVAILABLE"
    TICKER_STALE = "TICKER_STALE"
    NOT_TRADABLE = "NOT_TRADABLE"
    INVALID_BID_ASK = "INVALID_BID_ASK"
    MM_UNAVAILABLE = "MM_UNAVAILABLE"
    MM_STALE = "MM_STALE"
    MM_LOCKED = "MM_LOCKED"
    ELIGIBILITY_UNAVAILABLE = "ELIGIBILITY_UNAVAILABLE"
    ELIGIBILITY_STALE = "ELIGIBILITY_STALE"
    ELIGIBILITY_SNAPSHOT_MISMATCH = "ELIGIBILITY_SNAPSHOT_MISMATCH"
    ELIGIBILITY_SYMBOL_MISMATCH = "ELIGIBILITY_SYMBOL_MISMATCH"
    POSITION_CAPACITY_EXHAUSTED = "POSITION_CAPACITY_EXHAUSTED"
    CAPITAL_INELIGIBLE = "CAPITAL_INELIGIBLE"
    METADATA_INCOMPLETE = "METADATA_INCOMPLETE"


class ScannerStatus(str, Enum):
    CANDIDATES_AVAILABLE = "CANDIDATES_AVAILABLE"
    NO_ELIGIBLE_MARKET = "NO_ELIGIBLE_MARKET"
    AUTO_SELECTION_UNAVAILABLE = "AUTO_SELECTION_UNAVAILABLE"


@dataclass(frozen=True)
class TickerSnapshot:
    tickers: Tuple[FuturesTicker, ...]
    evaluated_at: datetime
    freshness: str


@dataclass(frozen=True)
class ScannerInput:
    universe: Optional[MarketUniverseSnapshot]
    ticker_snapshot: Optional[TickerSnapshot]
    capital: Optional[CapitalEligibilityContract]
    per_market_eligibility: Mapping[str, PerMarketEligibilityResult]
    evaluated_at: datetime
    started_at: Optional[datetime] = None


@dataclass(frozen=True)
class ScannerCandidate:
    symbol: str
    exchange_symbol: str
    universe_eligible: bool
    capital_eligible: bool
    market_data_fresh: bool
    tradable: bool
    last_price: Optional[Decimal]
    best_bid: Optional[Decimal]
    best_ask: Optional[Decimal]
    bid_size: Optional[Decimal]
    ask_size: Optional[Decimal]
    spread: Optional[Decimal]
    spread_percent: Optional[Decimal]
    activity_metric: Optional[Decimal]
    contract_metadata: FuturesContractMetadata
    scanner_eligible: bool
    rejection_reasons: Tuple[ScannerRejectionReason, ...]
    capital_reason_codes: Tuple[str, ...]
    evaluated_at: datetime

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "exchangeSymbol": self.exchange_symbol,
            "universeEligible": self.universe_eligible,
            "capitalEligible": self.capital_eligible,
            "marketDataFresh": self.market_data_fresh,
            "tradable": self.tradable,
            "lastPrice": _encoded(self.last_price),
            "bestBid": _encoded(self.best_bid),
            "bestAsk": _encoded(self.best_ask),
            "bidSize": _encoded(self.bid_size),
            "askSize": _encoded(self.ask_size),
            "spread": _encoded(self.spread),
            "spreadPercent": _encoded(self.spread_percent),
            "activityMetric": _encoded(self.activity_metric),
            "contractMetadata": self.contract_metadata.to_dict(),
            "scannerEligible": self.scanner_eligible,
            "rejectionReasons": _encoded(self.rejection_reasons),
            "capitalReasonCodes": list(self.capital_reason_codes),
            "evaluatedAt": _encoded(self.evaluated_at),
        }


@dataclass(frozen=True)
class ScannerCycleResult:
    scanner_cycle_id: str
    status: ScannerStatus
    started_at: datetime
    evaluated_at: datetime
    universe_count: int
    evaluated_count: int
    eligible_count: int
    rejected_count: int
    candidates: Tuple[ScannerCandidate, ...]
    rejections: Tuple[ScannerCandidate, ...]
    universe_evaluated_at: Optional[datetime]
    ticker_evaluated_at: Optional[datetime]
    mm_evaluated_at: Optional[datetime]
    capital_eligibility_contract: Optional[CapitalEligibilityContract]
    global_rejection_reasons: Tuple[ScannerRejectionReason, ...] = ()

    def to_dict(self):
        return {
            "scannerCycleId": self.scanner_cycle_id,
            "status": self.status.value,
            "startedAt": _encoded(self.started_at),
            "evaluatedAt": _encoded(self.evaluated_at),
            "universeCount": self.universe_count,
            "evaluatedCount": self.evaluated_count,
            "eligibleCount": self.eligible_count,
            "rejectedCount": self.rejected_count,
            "candidates": [item.to_dict() for item in self.candidates],
            "rejections": [item.to_dict() for item in self.rejections],
            "universeEvaluatedAt": _encoded(self.universe_evaluated_at),
            "tickerEvaluatedAt": _encoded(self.ticker_evaluated_at),
            "mmEvaluatedAt": _encoded(self.mm_evaluated_at),
            "capitalEligibilityContract": _encoded(self.capital_eligibility_contract),
            "globalRejectionReasons": _encoded(self.global_rejection_reasons),
        }


class MarketScanner:
    """Pure scanner over supplied snapshots; performs no I/O."""

    def __init__(self, *, maximum_snapshot_age=DEFAULT_SNAPSHOT_MAX_AGE):
        if not isinstance(maximum_snapshot_age, timedelta) or maximum_snapshot_age.total_seconds() <= 0:
            raise ValueError("positive maximum_snapshot_age required")
        self.maximum_snapshot_age = maximum_snapshot_age

    def _fresh(self, timestamp, now):
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            return False
        age = now - _utc(timestamp)
        return timedelta(0) <= age <= self.maximum_snapshot_age

    def scan(self, source: ScannerInput) -> ScannerCycleResult:
        if not isinstance(source, ScannerInput):
            raise TypeError("ScannerInput required")
        now = _utc(source.evaluated_at)
        started = _utc(source.started_at or source.evaluated_at)
        if started > now:
            raise ValueError("started_at cannot follow evaluated_at")

        if source.universe is None:
            return self._result(source, started, now, (),
                                (ScannerRejectionReason.UNIVERSE_UNAVAILABLE,))

        contracts = sorted(source.universe.contracts, key=lambda item: item.canonical_symbol)
        ticker_by_symbol = {
            canonicalize_futures_symbol(item.exchange_symbol): item
            for item in (source.ticker_snapshot.tickers if source.ticker_snapshot else ())
        }
        eligibility_by_symbol = {
            canonicalize_futures_symbol(symbol): value
            for symbol, value in source.per_market_eligibility.items()
        }
        universe_fresh = (
            source.universe.freshness == "FRESH"
            and self._fresh(source.universe.evaluated_at, now)
        )
        ticker_fresh = bool(
            source.ticker_snapshot
            and source.ticker_snapshot.freshness == "FRESH"
            and self._fresh(source.ticker_snapshot.evaluated_at, now)
        )
        mm_fresh = bool(
            source.capital and source.capital.authority_fresh
            and self._fresh(source.capital.evaluated_at, now)
        )

        evaluated = tuple(
            self._evaluate(
                metadata, ticker_by_symbol.get(metadata.canonical_symbol),
                eligibility_by_symbol.get(metadata.canonical_symbol), source.capital,
                now, universe_fresh, ticker_fresh, mm_fresh,
            )
            for metadata in contracts
        )
        return self._result(source, started, now, evaluated, ())

    def _evaluate(self, metadata, ticker, eligibility, capital, now,
                  universe_fresh, ticker_fresh, mm_fresh):
        reasons = []
        if not universe_fresh or not self._fresh(metadata.metadata_evaluated_at, now):
            reasons.append(ScannerRejectionReason.UNIVERSE_STALE)
        if not metadata.is_tradable:
            reasons.append(ScannerRejectionReason.NOT_TRADABLE)
        required_metadata = (
            metadata.exchange_symbol, metadata.contract_multiplier,
            metadata.quantity_step, metadata.minimum_quantity, metadata.tick_size,
        )
        if any(value is None or value == "" for value in required_metadata):
            reasons.append(ScannerRejectionReason.METADATA_INCOMPLETE)

        if ticker is None:
            reasons.append(ScannerRejectionReason.TICKER_UNAVAILABLE)
        elif not ticker_fresh:
            reasons.append(ScannerRejectionReason.TICKER_STALE)
        valid_book = bool(
            ticker and ticker.best_bid is not None and ticker.best_ask is not None
            and ticker.best_bid > 0 and ticker.best_ask > 0
            and ticker.best_ask >= ticker.best_bid
        )
        if ticker is not None and not valid_book:
            reasons.append(ScannerRejectionReason.INVALID_BID_ASK)

        if capital is None:
            reasons.append(ScannerRejectionReason.MM_UNAVAILABLE)
        else:
            if not mm_fresh:
                reasons.append(ScannerRejectionReason.MM_STALE)
            if not capital.execution_entry_allowed:
                reasons.append(ScannerRejectionReason.MM_LOCKED)
            required_capital_values = (
                capital.equity, capital.available_capital, capital.risk_budget,
                capital.max_position_notional, capital.total_exposure_percent,
                capital.max_total_exposure, capital.remaining_exposure,
            )
            valid_capital_values = all(
                isinstance(value, Decimal) and value.is_finite() and value >= 0
                for value in required_capital_values
            )
            valid_capacity = (
                type(capital.remaining_position_capacity) is int
                and capital.remaining_position_capacity > 0
            )
            if capital.remaining_position_capacity == 0:
                reasons.append(ScannerRejectionReason.POSITION_CAPACITY_EXHAUSTED)
            elif not valid_capacity:
                reasons.append(ScannerRejectionReason.CAPITAL_INELIGIBLE)
            if capital.capital_authority != "MONEY_MANAGEMENT" or not valid_capital_values:
                reasons.append(ScannerRejectionReason.CAPITAL_INELIGIBLE)

        capital_reasons = eligibility.reason_codes if eligibility else ()
        if eligibility is None:
            reasons.append(ScannerRejectionReason.ELIGIBILITY_UNAVAILABLE)
        else:
            eligibility_fresh = (
                self._fresh(eligibility.metadata_evaluated_at, now)
                and self._fresh(eligibility.mm_evaluated_at, now)
            )
            if not eligibility_fresh:
                reasons.append(ScannerRejectionReason.ELIGIBILITY_STALE)
            if canonicalize_futures_symbol(eligibility.symbol) != metadata.canonical_symbol:
                reasons.append(ScannerRejectionReason.ELIGIBILITY_SYMBOL_MISMATCH)
            if (
                eligibility.metadata_evaluated_at != metadata.metadata_evaluated_at
                or capital is None
                or eligibility.mm_evaluated_at != capital.evaluated_at
            ):
                reasons.append(ScannerRejectionReason.ELIGIBILITY_SNAPSHOT_MISMATCH)
            if "POSITION_CAPACITY_EXHAUSTED" in capital_reasons:
                reasons.append(ScannerRejectionReason.POSITION_CAPACITY_EXHAUSTED)
            if "MM_ENTRY_LOCKED" in capital_reasons:
                reasons.append(ScannerRejectionReason.MM_LOCKED)
            if not (
                eligibility.eligible
                and eligibility.calculation_allowed
                and eligibility.position_feasible
            ):
                reasons.append(ScannerRejectionReason.CAPITAL_INELIGIBLE)

        reasons = tuple(dict.fromkeys(reasons))
        spread = ticker.best_ask - ticker.best_bid if valid_book else None
        midpoint = ((ticker.best_ask + ticker.best_bid) / Decimal("2")) if valid_book else None
        spread_percent = (spread / midpoint * Decimal("100")) if midpoint else None
        eligible = not reasons
        return ScannerCandidate(
            metadata.canonical_symbol, metadata.exchange_symbol,
            universe_fresh, bool(
                eligibility and eligibility.eligible
                and eligibility.calculation_allowed and eligibility.position_feasible
            ),
            ticker_fresh, metadata.is_tradable,
            ticker.last_price if ticker else None,
            ticker.best_bid if ticker else None, ticker.best_ask if ticker else None,
            ticker.bid_size if ticker else None, ticker.ask_size if ticker else None,
            spread, spread_percent, ticker.volume_activity if ticker else None,
            metadata, eligible, reasons, tuple(capital_reasons), now,
        )

    def _result(self, source, started, now, evaluated, global_reasons):
        candidates = tuple(item for item in evaluated if item.scanner_eligible)
        rejections = tuple(item for item in evaluated if not item.scanner_eligible)
        if global_reasons:
            status = ScannerStatus.AUTO_SELECTION_UNAVAILABLE
        elif candidates:
            status = ScannerStatus.CANDIDATES_AVAILABLE
        else:
            status = ScannerStatus.NO_ELIGIBLE_MARKET
        universe_at = source.universe.evaluated_at if source.universe else None
        ticker_at = source.ticker_snapshot.evaluated_at if source.ticker_snapshot else None
        mm_at = source.capital.evaluated_at if source.capital else None
        identity = "|".join([
            str(_encoded(started) or ""), str(_encoded(now) or ""),
            str(_encoded(universe_at) or ""), str(_encoded(ticker_at) or ""),
            str(_encoded(mm_at) or ""),
            ",".join(item.symbol for item in evaluated),
            ",".join(reason.value for reason in global_reasons),
            json.dumps(
                source.capital.to_dict() if source.capital else None,
                sort_keys=True, separators=(",", ":"), default=_encoded,
            ),
            json.dumps(
                [item.to_dict() for item in evaluated],
                sort_keys=True, separators=(",", ":"), default=_encoded,
            ),
        ])
        return ScannerCycleResult(
            "ams-1a-" + sha256(identity.encode("utf-8")).hexdigest()[:20],
            status, started, now,
            len(source.universe.contracts) if source.universe else 0,
            len(evaluated), len(candidates), len(rejections), candidates, rejections,
            universe_at, ticker_at, mm_at, source.capital, tuple(global_reasons),
        )
