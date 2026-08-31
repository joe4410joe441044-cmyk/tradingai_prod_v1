"""Bounded, validated market-trade window for browser telemetry."""

from copy import deepcopy
import math
import threading
import time


def normalize_exchange_timestamp(value, *, now=None):
    if isinstance(value, bool):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp) or timestamp <= 0:
        return None
    if timestamp >= 1e18:
        timestamp /= 1e9
    elif timestamp >= 1e15:
        timestamp /= 1e6
    elif timestamp >= 1e12:
        timestamp /= 1e3
    current = time.time() if now is None else now
    if timestamp < 946684800 or timestamp > current + 300:
        return None
    return timestamp


class RecentMarketTrades:
    """Newest-first window with stable identity and symbol isolation."""

    def __init__(self, *, symbol, exchange_symbol, context_key, maximum=100):
        if not isinstance(maximum, int) or maximum <= 0:
            raise ValueError("positive maximum required")
        self.symbol = symbol
        self.exchange_symbol = exchange_symbol
        self.context_key = context_key
        self.maximum = maximum
        self._rows = []
        self._trade_ids = set()
        self._lock = threading.Lock()
        self.ready = False

    def mark_ready(self):
        with self._lock:
            self.ready = True

    def reset(self):
        with self._lock:
            self.ready = False
            self._rows = []
            self._trade_ids = set()

    def append(self, payload, *, now=None):
        if not isinstance(payload, dict):
            return False
        trade_id = payload.get("tradeId")
        side = str(payload.get("side") or "").upper()
        if not isinstance(trade_id, str) or not trade_id.strip():
            return False
        if payload.get("symbol") != self.exchange_symbol or side not in {"BUY", "SELL"}:
            return False
        try:
            price = float(payload.get("price"))
            quantity = float(payload.get("size"))
        except (TypeError, ValueError):
            return False
        timestamp = normalize_exchange_timestamp(
            payload.get("ts", payload.get("time")), now=now
        )
        if (not math.isfinite(price) or price <= 0
                or not math.isfinite(quantity) or quantity <= 0
                or timestamp is None):
            return False
        sequence = payload.get("sequence")
        try:
            sequence = int(sequence) if not isinstance(sequence, bool) else None
        except (TypeError, ValueError):
            sequence = None
        if sequence is not None and not 0 <= sequence <= 9007199254740991:
            sequence = None
        row = {
            "symbol": self.symbol,
            "exchangeSymbol": self.exchange_symbol,
            "contextKey": self.context_key,
            "tradeId": trade_id.strip(),
            "timestamp": timestamp,
            "price": price,
            "quantity": quantity,
            "side": side,
            "sequence": sequence,
        }
        with self._lock:
            self.ready = True
            if row["tradeId"] in self._trade_ids:
                return False
            self._rows.append(row)
            self._rows.sort(key=lambda item: (
                -item["timestamp"],
                -(item["sequence"] if item["sequence"] is not None else -1),
                item["tradeId"],
            ))
            self._rows = self._rows[:self.maximum]
            self._trade_ids = {item["tradeId"] for item in self._rows}
        return True

    def snapshot(self):
        with self._lock:
            return {
                "ready": self.ready,
                "rows": deepcopy(self._rows),
            }
