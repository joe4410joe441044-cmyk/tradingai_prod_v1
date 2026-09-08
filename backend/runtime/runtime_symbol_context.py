"""Derived symbol identity carried through the live decision pipeline."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional


@dataclass(frozen=True)
class RuntimeSymbolContext:
    symbol: str
    runtime_id: str
    evaluated_at: datetime
    context_key: Optional[str] = None
    runtime_instance_id: Optional[str] = None
    exchange_symbol: Optional[str] = None

    def to_dict(self):
        result = {
            "symbol": self.symbol,
            "runtimeId": self.runtime_id,
            "evaluatedAt": self.evaluated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if self.context_key is not None:
            result["contextKey"] = self.context_key
        if self.runtime_instance_id is not None:
            result["runtimeInstanceId"] = self.runtime_instance_id
        if self.exchange_symbol is not None:
            result["exchangeSymbol"] = self.exchange_symbol
        return result


def build_runtime_symbol_context(
    symbol, runtime_id, *, evaluated_at=None, exchange=None, market_type=None,
    exchange_symbol=None, runtime_instance_id=None,
):
    normalized = str(symbol or "").strip().upper()
    runtime = str(runtime_id or "").strip()
    when = evaluated_at or datetime.now(timezone.utc)
    if not normalized or not runtime or not isinstance(when, datetime) or when.tzinfo is None:
        return None
    normalized_exchange = str(exchange or "").strip().upper()
    normalized_market_type = str(market_type or "").strip().upper()
    normalized_exchange_symbol = str(exchange_symbol or "").strip().upper()
    instance_id = str(runtime_instance_id or runtime).strip()
    context_key = (
        f"{normalized_exchange}:{normalized_market_type}:{normalized_exchange_symbol}"
        if normalized_exchange and normalized_market_type and normalized_exchange_symbol
        else None
    )
    return RuntimeSymbolContext(
        normalized, runtime, when.astimezone(timezone.utc), context_key,
        instance_id if context_key else None,
        normalized_exchange_symbol or None,
    )


def symbol_context_matches(value, authority_symbol, authority_runtime_id=None):
    if isinstance(value, RuntimeSymbolContext):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        return False
    symbol = str(value.get("symbol") or "").strip().upper()
    runtime_id = str(value.get("runtimeId") or "").strip()
    if symbol != str(authority_symbol or "").strip().upper() or not runtime_id:
        return False
    return authority_runtime_id is None or runtime_id == str(authority_runtime_id)
