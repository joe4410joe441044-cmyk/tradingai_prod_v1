"""Derived symbol identity carried through the live decision pipeline."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional


@dataclass(frozen=True)
class RuntimeSymbolContext:
    symbol: str
    runtime_id: str
    evaluated_at: datetime

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "runtimeId": self.runtime_id,
            "evaluatedAt": self.evaluated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        }


def build_runtime_symbol_context(symbol, runtime_id, *, evaluated_at=None):
    normalized = str(symbol or "").strip().upper()
    runtime = str(runtime_id or "").strip()
    when = evaluated_at or datetime.now(timezone.utc)
    if not normalized or not runtime or not isinstance(when, datetime) or when.tzinfo is None:
        return None
    return RuntimeSymbolContext(normalized, runtime, when.astimezone(timezone.utc))


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
