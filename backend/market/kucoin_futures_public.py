"""Public KuCoin Futures universe authority; never performs private actions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Callable, Mapping, Optional, Tuple

import requests


KUCOIN_FUTURES_BASE_URL = "https://api-futures.kucoin.com"
ACTIVE_CONTRACTS_PATH = "/api/v1/contracts/active"
ALL_TICKERS_PATH = "/api/v1/allTickers"
DEFAULT_METADATA_TTL = timedelta(minutes=15)


class KucoinPublicMarketError(RuntimeError):
    """Safe public-market failure without credential or response leakage."""


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


def _decimal(value, *, positive=False, nonnegative=False):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    if positive and result <= 0:
        return None
    if nonnegative and result < 0:
        return None
    return result


def canonicalize_futures_symbol(symbol):
    """Convert a KuCoin/TradingAI symbol to TradingAI's compact symbol form."""
    value = str(symbol).strip().upper().replace("-", "")
    if value.endswith("M") and (value.endswith("USDTM") or value.endswith("USDM")):
        value = value[:-1]
    if value.startswith("XBT"):
        value = "BTC" + value[3:]
    return value


def to_kucoin_futures_symbol(symbol):
    """Compatibility normalization for linear USDT futures symbols."""
    value = canonicalize_futures_symbol(symbol)
    if value.startswith("BTC"):
        value = "XBT" + value[3:]
    if value.endswith("USDT"):
        return value + "M"
    return str(symbol).strip().upper()


@dataclass(frozen=True)
class FuturesContractMetadata:
    canonical_symbol: str
    exchange_symbol: str
    base_currency: Optional[str]
    quote_currency: Optional[str]
    settle_currency: Optional[str]
    contract_type: Optional[str]
    tradable_status: Optional[str]
    contract_multiplier: Optional[Decimal]
    quantity_step: Optional[Decimal]
    minimum_quantity: Optional[Decimal]
    minimum_notional: Optional[Decimal]
    tick_size: Optional[Decimal]
    maker_fee: Optional[Decimal]
    taker_fee: Optional[Decimal]
    maximum_leverage: Optional[Decimal]
    margin_metadata: Mapping[str, Optional[Decimal]]
    last_price: Optional[Decimal]
    metadata_evaluated_at: datetime

    @property
    def is_tradable(self):
        return self.tradable_status == "Open"

    def to_dict(self):
        def value(item):
            if isinstance(item, Decimal):
                return format(item, "f")
            if isinstance(item, datetime):
                return item.isoformat().replace("+00:00", "Z")
            return item
        return {
            "canonicalSymbol": self.canonical_symbol,
            "exchangeSymbol": self.exchange_symbol,
            "baseCurrency": self.base_currency,
            "quoteCurrency": self.quote_currency,
            "settleCurrency": self.settle_currency,
            "contractType": self.contract_type,
            "tradableStatus": self.tradable_status,
            "contractMultiplier": value(self.contract_multiplier),
            "quantityStep": value(self.quantity_step),
            "minimumQuantity": value(self.minimum_quantity),
            "minimumNotional": value(self.minimum_notional),
            "tickSize": value(self.tick_size),
            "makerFee": value(self.maker_fee),
            "takerFee": value(self.taker_fee),
            "maximumLeverage": value(self.maximum_leverage),
            "marginMetadata": {k: value(v) for k, v in self.margin_metadata.items()},
            "lastPrice": value(self.last_price),
            "metadataEvaluatedAt": value(self.metadata_evaluated_at),
        }


@dataclass(frozen=True)
class MarketUniverseSnapshot:
    contracts: Tuple[FuturesContractMetadata, ...]
    evaluated_at: datetime
    freshness: str

    def find(self, symbol):
        canonical = canonicalize_futures_symbol(symbol)
        return next((item for item in self.contracts if item.canonical_symbol == canonical), None)


@dataclass(frozen=True)
class FuturesTicker:
    exchange_symbol: str
    last_price: Optional[Decimal]
    best_bid: Optional[Decimal]
    best_ask: Optional[Decimal]
    bid_size: Optional[Decimal]
    ask_size: Optional[Decimal]
    volume_activity: Optional[Decimal]
    timestamp: Optional[int]


class KucoinFuturesPublicClient:
    def __init__(self, *, timeout=5.0, session=None, base_url=KUCOIN_FUTURES_BASE_URL):
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")

    def _get_data(self, path):
        try:
            response = self.session.get(self.base_url + path, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise KucoinPublicMarketError("KUCOIN_PUBLIC_MARKET_UNAVAILABLE") from exc
        if not isinstance(payload, dict) or payload.get("code") != "200000":
            raise KucoinPublicMarketError("KUCOIN_PUBLIC_RESPONSE_INVALID")
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise KucoinPublicMarketError("KUCOIN_PUBLIC_DATA_EMPTY")
        return data

    def get_active_contracts(self, *, evaluated_at=None):
        now = _utc(evaluated_at or datetime.now(timezone.utc))
        contracts = []
        for raw in self._get_data(ACTIVE_CONTRACTS_PATH):
            if not isinstance(raw, dict):
                raise KucoinPublicMarketError("KUCOIN_CONTRACT_MALFORMED")
            exchange_symbol = raw.get("symbol")
            if not isinstance(exchange_symbol, str) or not exchange_symbol.strip():
                raise KucoinPublicMarketError("KUCOIN_CONTRACT_SYMBOL_MISSING")
            status = raw.get("status") if isinstance(raw.get("status"), str) else None
            contract = FuturesContractMetadata(
                canonicalize_futures_symbol(exchange_symbol), exchange_symbol.strip().upper(),
                raw.get("baseCurrency") if isinstance(raw.get("baseCurrency"), str) else None,
                raw.get("quoteCurrency") if isinstance(raw.get("quoteCurrency"), str) else None,
                raw.get("settleCurrency") if isinstance(raw.get("settleCurrency"), str) else None,
                raw.get("type") if isinstance(raw.get("type"), str) else None, status,
                _decimal(raw.get("multiplier"), positive=True),
                _decimal(raw.get("lotSize"), positive=True),
                _decimal(raw.get("lotSize"), positive=True), None,
                _decimal(raw.get("tickSize"), positive=True),
                _decimal(raw.get("makerFeeRate"), nonnegative=True),
                _decimal(raw.get("takerFeeRate"), nonnegative=True),
                _decimal(raw.get("maxLeverage"), positive=True),
                {"initialMargin": _decimal(raw.get("initialMargin"), nonnegative=True),
                 "maintainMargin": _decimal(raw.get("maintainMargin"), nonnegative=True)},
                _decimal(raw.get("lastTradePrice"), nonnegative=True), now,
            )
            if contract.is_tradable:
                contracts.append(contract)
        if not contracts:
            raise KucoinPublicMarketError("KUCOIN_TRADABLE_UNIVERSE_EMPTY")
        return tuple(sorted(contracts, key=lambda item: item.exchange_symbol))

    def get_all_tickers(self):
        result = []
        for raw in self._get_data(ALL_TICKERS_PATH):
            if not isinstance(raw, dict) or not isinstance(raw.get("symbol"), str):
                raise KucoinPublicMarketError("KUCOIN_TICKER_MALFORMED")
            result.append(FuturesTicker(
                raw["symbol"].strip().upper(), _decimal(raw.get("price"), nonnegative=True),
                _decimal(raw.get("bestBidPrice"), nonnegative=True),
                _decimal(raw.get("bestAskPrice"), nonnegative=True),
                _decimal(raw.get("bestBidSize"), nonnegative=True),
                _decimal(raw.get("bestAskSize"), nonnegative=True), None,
                raw.get("ts") if type(raw.get("ts")) is int else None,
            ))
        return tuple(result)


class KucoinMarketUniverseCache:
    def __init__(self, client, *, ttl=DEFAULT_METADATA_TTL, clock=None):
        if not isinstance(client, KucoinFuturesPublicClient):
            raise TypeError("KucoinFuturesPublicClient required")
        if not isinstance(ttl, timedelta) or ttl.total_seconds() <= 0:
            raise ValueError("positive ttl required")
        self._client, self._ttl = client, ttl
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last_good, self._lock = None, RLock()

    def get(self):
        with self._lock:
            if self._last_good is None:
                return None
            freshness = "FRESH" if _utc(self._clock()) - self._last_good.evaluated_at <= self._ttl else "STALE"
            return MarketUniverseSnapshot(self._last_good.contracts, self._last_good.evaluated_at, freshness)

    def refresh(self):
        now = _utc(self._clock())
        contracts = self._client.get_active_contracts(evaluated_at=now)
        snapshot = MarketUniverseSnapshot(contracts, now, "FRESH")
        with self._lock:
            self._last_good = snapshot
        return snapshot
