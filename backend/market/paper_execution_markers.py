"""Normalize PAPER execution authority for the Market Intelligence payload."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


PAPER_MARKER_HISTORY_LIMIT = 100


def paper_marker_authority_available(engine: Any) -> bool:
    return (
        engine is not None
        and str(getattr(engine, "mode", "")).strip().upper() == "PAPER"
        and isinstance(getattr(engine, "paper_fills", None), list)
        and isinstance(getattr(engine, "trade_history", None), list)
    )


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value > 0 else None


def _timestamp(value: Any) -> tuple[str, int] | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value <= 0:
        return None
    moment = datetime.fromtimestamp(value, tz=timezone.utc)
    return moment.isoformat().replace("+00:00", "Z"), int(value * 1000)


def _same_symbol(candidate: Any, active_symbol: str) -> bool:
    symbol = _text(candidate)
    return symbol is not None and symbol.upper() == active_symbol.upper()


def _identity_matches(record: Mapping[str, Any], context_key: str,
                      runtime_instance_id: str) -> bool:
    record_context = _text(record.get("contextKey"))
    record_runtime = _text(record.get("runtimeInstanceId"))
    return (record_context is None or record_context == context_key) and (
        record_runtime is None or record_runtime == runtime_instance_id
    )


def _base_marker(*, marker_id: str, marker_type: str, timestamp: str,
                 sequence: int, price: float, quantity: float, side: str,
                 symbol: str, context_key: str, runtime_instance_id: str,
                 order_id: str | None, trade_id: str | None,
                 reason: str | None) -> dict[str, Any]:
    return {
        "id": marker_id, "markerId": marker_id, "type": marker_type,
        "timestamp": timestamp, "sequence": sequence, "price": price,
        "quantity": quantity, "side": side, "reason": reason,
        "orderId": order_id, "tradeId": trade_id,
        "reduceOnly": marker_type == "EXIT", "flatten": marker_type == "EXIT",
        "blocked": False, "failed": False, "source": "PAPER_RUNTIME",
        "eventType": "POSITION_OPENED" if marker_type == "ENTRY" else "POSITION_CLOSED",
        "dataQuality": "VALID", "symbol": symbol, "contextKey": context_key,
        "runtimeInstanceId": runtime_instance_id,
    }


def build_paper_execution_markers(engine: Any, *, active_symbol: Any,
                                  context_key: Any,
                                  runtime_instance_id: Any) -> list[dict[str, Any]]:
    """Return current-context PAPER fills/closes as a deterministic snapshot."""
    symbol = _text(active_symbol)
    context = _text(context_key)
    runtime_id = _text(runtime_instance_id)
    if (not paper_marker_authority_available(engine) or symbol is None
            or context is None or runtime_id is None):
        return []

    markers: dict[str, dict[str, Any]] = {}
    fills = getattr(engine, "paper_fills", None)
    if isinstance(fills, list):
        for record in fills:
            if not isinstance(record, Mapping) or str(record.get("mode", "")).upper() != "PAPER":
                continue
            fill_id = _text(record.get("fillId")); stamp = _timestamp(record.get("filledAt"))
            price = _positive_number(record.get("price")); quantity = _positive_number(record.get("qty"))
            side = str(record.get("side", "")).upper()
            if (fill_id is None or stamp is None or price is None or quantity is None
                    or side not in {"BUY", "SELL"} or not _same_symbol(record.get("symbol"), symbol)
                    or not _identity_matches(record, context, runtime_id)):
                continue
            marker_id = f"paper-entry:{fill_id}"
            markers[marker_id] = _base_marker(
                marker_id=marker_id, marker_type="ENTRY", timestamp=stamp[0], sequence=stamp[1],
                price=price, quantity=quantity, side=side, symbol=symbol, context_key=context,
                runtime_instance_id=runtime_id, order_id=_text(record.get("orderId")),
                trade_id=None, reason=None,
            )

    history = getattr(engine, "trade_history", None)
    if isinstance(history, list):
        for record in history:
            if (not isinstance(record, Mapping) or str(record.get("mode", "")).upper() != "PAPER"
                    or str(record.get("status", "")).upper() != "CLOSED"):
                continue
            trade_id = _text(record.get("tradeId")); stamp = _timestamp(record.get("closedAt"))
            price = _positive_number(record.get("exitPrice")); quantity = _positive_number(record.get("qty"))
            side = str(record.get("side", "")).upper()
            if (trade_id is None or stamp is None or price is None or quantity is None
                    or side not in {"BUY", "SELL"} or not _same_symbol(record.get("symbol"), symbol)
                    or not _identity_matches(record, context, runtime_id)):
                continue
            marker_id = f"paper-exit:{trade_id}"
            markers[marker_id] = _base_marker(
                marker_id=marker_id, marker_type="EXIT", timestamp=stamp[0], sequence=stamp[1],
                price=price, quantity=quantity, side=side, symbol=symbol, context_key=context,
                runtime_instance_id=runtime_id, order_id=None, trade_id=trade_id,
                reason=_text(record.get("reason")),
            )

    ordered = sorted(markers.values(), key=lambda marker: (-marker["sequence"], marker["id"]))
    return ordered[:PAPER_MARKER_HISTORY_LIMIT]
