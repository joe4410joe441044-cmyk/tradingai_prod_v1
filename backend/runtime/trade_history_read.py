"""Read-only Trade History service (canonical completed-trade tab).

This service is a thin, read-only projection over the SAME durable canonical
store as Parameter Performance:

- :class:`~backend.runtime.parameter_performance.ParameterPerformanceStore`
  (completed-trade Stage 13 records written by
  :func:`~backend.runtime.parameter_performance.record_completed_trade`).

It creates no independent history store, writes nothing and never changes any
trading authority.  It exposes the completed-trade population with explicit
filters, deterministic sorting, pagination and a factual result classification:

    realizedPnl > 0  -> WIN
    realizedPnl < 0  -> LOSS
    realizedPnl == 0 -> BREAKEVEN
    no numeric PnL   -> UNKNOWN

Only Production-eligible records are exposed (the same provenance/eligibility
rule as Parameter Performance): an explicit ``origin=NON_PRODUCTION`` record and
a legacy record without a provable integer revision are never shown.

Period filtering uses the EXIT time as the single time authority.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from backend.runtime.parameter_performance import (
    CONTROL_SOURCE_BOT,
    CONTROL_SOURCE_MANUAL,
    ParameterPerformanceStore,
    default_parameter_performance_store,
    is_production_eligible,
)
from backend.runtime.parameter_performance_read import compute_metrics

SUPPORTED_SCOPES = ("PAPER", "LIVE")
SUPPORTED_MODES = ("paper", "live")
SUPPORTED_SIDES = ("BUY", "SELL")

RESULT_WIN = "WIN"
RESULT_LOSS = "LOSS"
RESULT_BREAKEVEN = "BREAKEVEN"
RESULT_UNKNOWN = "UNKNOWN"
RESULT_VALUES = (RESULT_WIN, RESULT_LOSS, RESULT_BREAKEVEN, RESULT_UNKNOWN)

CONTROL_SOURCES = (CONTROL_SOURCE_BOT, CONTROL_SOURCE_MANUAL)

# The single period time authority: a completed trade belongs to the period in
# which it EXITED.  Entry time is never used for period membership.
PERIOD_TIME_AUTHORITY = "EXIT_TIME"

SORT_FIELDS = (
    "exitTimestamp",
    "entryTimestamp",
    "realizedPnl",
    "holdingMs",
    "symbol",
    "tradeId",
    "effectiveRevision",
)
SORT_DIRECTIONS = ("asc", "desc")
DEFAULT_SORT_FIELD = "exitTimestamp"
DEFAULT_SORT_DIRECTION = "desc"
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500

RESULT_CLASSIFICATION_RULE = (
    "REALIZED_PNL_GT_0_WIN_LT_0_LOSS_EQ_0_BREAKEVEN"
)

TRADE_HISTORY_SEMANTICS = {
    "periodTimeAuthority": PERIOD_TIME_AUTHORITY,
    "resultClassification": RESULT_CLASSIFICATION_RULE,
    "note": (
        "Trade History is a read-only projection over the canonical "
        "completed-trade store. Period membership is decided by the EXIT time. "
        "Result is a factual classification of the realized PnL and is never a "
        "score, ranking or recommendation."
    ),
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def classify_result(realized_pnl: Any) -> str:
    """Factual result classification from the realized PnL."""

    if not _is_number(realized_pnl):
        return RESULT_UNKNOWN
    value = float(realized_pnl)
    if value > 0:
        return RESULT_WIN
    if value < 0:
        return RESULT_LOSS
    return RESULT_BREAKEVEN


def _coerce_scope(scope: Any) -> Optional[str]:
    if scope is None:
        return None
    if isinstance(scope, str):
        value = scope.strip().upper()
        if value in SUPPORTED_SCOPES:
            return value
    raise ValueError("scope must be PAPER or LIVE")


def _coerce_mode(mode: Any) -> Optional[str]:
    if mode is None:
        return None
    if isinstance(mode, str):
        value = mode.strip().lower()
        if value in SUPPORTED_MODES:
            return value
    raise ValueError("mode must be paper or live")


def _coerce_side(side: Any) -> Optional[str]:
    if side is None:
        return None
    if isinstance(side, str):
        value = side.strip().upper()
        if value in SUPPORTED_SIDES:
            return value
    raise ValueError("side must be BUY or SELL")


def _coerce_result(result: Any) -> Optional[str]:
    if result is None:
        return None
    if isinstance(result, str):
        value = result.strip().upper()
        if value in RESULT_VALUES:
            return value
    raise ValueError("result must be WIN, LOSS, BREAKEVEN or UNKNOWN")


def _coerce_control_source(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in CONTROL_SOURCES or normalized == RESULT_UNKNOWN:
            return normalized
    raise ValueError("controlSource must be BOT, MANUAL or UNKNOWN")


def _record_control_source(record: Mapping[str, Any]) -> str:
    value = record.get("controlSource")
    if isinstance(value, str) and value.strip().upper() in CONTROL_SOURCES:
        return value.strip().upper()
    return "UNKNOWN"


def _project_record(record: Mapping[str, Any]) -> dict:
    """Return a read-only copy of a canonical record plus its classification."""

    projected = dict(record)
    projected["controlSource"] = _record_control_source(record)
    for field in ("realizedPnl", "holdingMs", "entryTimestamp", "exitTimestamp", "entryPrice", "exitPrice", "quantity"):
        if not _is_number(record.get(field)):
            projected[field] = None
    projected["result"] = classify_result(record.get("realizedPnl"))
    return projected


def _sort_value(record: Mapping[str, Any], field: str):
    value = record.get(field)
    if _is_number(value):
        return float(value)
    if isinstance(value, str) and value != "":
        return value
    return None


def _sort_records(records: list, field: str, direction: str) -> list:
    present = [r for r in records if _sort_value(r, field) is not None]
    missing = [r for r in records if _sort_value(r, field) is None]
    present.sort(
        key=lambda record: (
            _sort_value(record, field),
            str(record.get("recordId") or ""),
        ),
        reverse=(direction == "desc"),
    )
    return present + sorted(missing, key=lambda record: str(record.get("recordId") or ""))


class TradeHistoryService:
    """Read-only completed-trade history over the canonical store."""

    def __init__(
        self,
        *,
        store: Optional[ParameterPerformanceStore] = None,
        base_directory=None,
        now=None,
    ):
        if store is None and base_directory is not None:
            store = ParameterPerformanceStore(
                Path(base_directory) / "parameter_performance.jsonl"
            )
        self._store = store
        self._now = now or (lambda: datetime.now(timezone.utc).timestamp())

    @property
    def store(self) -> ParameterPerformanceStore:
        if self._store is None:
            self._store = default_parameter_performance_store()
        return self._store

    def _eligible_records(self, scope: Optional[str]) -> list:
        rows = self.store.history(scope=scope)
        return [_project_record(record) for record in rows if is_production_eligible(record)]

    def _options(self, records: list) -> dict:
        symbols = sorted({
            str(record.get("symbol")).upper()
            for record in records
            if record.get("symbol")
        })
        revisions = sorted({
            record.get("effectiveRevision")
            for record in records
            if isinstance(record.get("effectiveRevision"), int)
            and not isinstance(record.get("effectiveRevision"), bool)
        })
        exit_reasons = sorted({
            str(record.get("exitReason"))
            for record in records
            if record.get("exitReason")
        })
        return {
            "scope": list(SUPPORTED_SCOPES),
            "mode": list(SUPPORTED_MODES),
            "symbol": symbols,
            "side": list(SUPPORTED_SIDES),
            "result": list(RESULT_VALUES),
            "revision": revisions,
            "exitReason": exit_reasons,
            "controlSource": [*CONTROL_SOURCES, RESULT_UNKNOWN],
        }

    def history(
        self,
        *,
        period: str = "all",
        scope: Optional[str] = None,
        mode: Optional[str] = None,
        symbol: Optional[str] = None,
        side: Optional[str] = None,
        result: Optional[str] = None,
        revision: Optional[int] = None,
        exit_reason: Optional[str] = None,
        control_source: Optional[str] = None,
        from_timestamp: Optional[float] = None,
        to_timestamp: Optional[float] = None,
        sort: str = DEFAULT_SORT_FIELD,
        direction: str = DEFAULT_SORT_DIRECTION,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        normalized_scope = _coerce_scope(scope)
        normalized_mode = _coerce_mode(mode)
        normalized_side = _coerce_side(side)
        normalized_result = _coerce_result(result)
        normalized_control = _coerce_control_source(control_source)

        normalized_symbol = (
            symbol.strip().upper() if isinstance(symbol, str) and symbol.strip()
            else None
        )
        normalized_reason = (
            exit_reason.strip()
            if isinstance(exit_reason, str) and exit_reason.strip()
            else None
        )
        normalized_revision = None
        if revision is not None:
            if isinstance(revision, bool) or not isinstance(revision, int):
                raise ValueError("revision must be an integer")
            normalized_revision = revision

        normalized_sort = (
            sort.strip() if isinstance(sort, str) and sort.strip() in SORT_FIELDS
            else DEFAULT_SORT_FIELD
        )
        normalized_direction = (
            direction.strip().lower()
            if isinstance(direction, str)
            and direction.strip().lower() in SORT_DIRECTIONS
            else DEFAULT_SORT_DIRECTION
        )

        try:
            normalized_page = max(1, int(page))
        except (TypeError, ValueError):
            normalized_page = 1
        try:
            normalized_page_size = max(
                1, min(int(page_size), MAX_PAGE_SIZE)
            )
        except (TypeError, ValueError):
            normalized_page_size = DEFAULT_PAGE_SIZE

        from_value = (
            float(from_timestamp) if _is_number(from_timestamp) else None
        )
        to_value = float(to_timestamp) if _is_number(to_timestamp) else None

        if period not in ("today", "7d", "30d", "90d", "all", "custom"):
            raise ValueError("invalid period")
        if period == "custom":
            if from_value is None or to_value is None or from_value > to_value:
                raise ValueError("custom period requires ordered fromTimestamp/toTimestamp")
        elif period != "all":
            now = self._now()
            to_value = now
            if period == "today":
                from_value = datetime.fromtimestamp(now, timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0,
                ).timestamp()
            else:
                from_value = now - int(period[:-1]) * 86400
        if from_value is not None and to_value is not None and from_value > to_value:
            raise ValueError("fromTimestamp must not exceed toTimestamp")
        records = self._eligible_records(normalized_scope)
        options = self._options(records)

        filtered = []
        for record in records:
            if normalized_mode is not None and record.get("mode") != normalized_mode:
                continue
            if normalized_symbol is not None and str(
                record.get("symbol") or ""
            ).upper() != normalized_symbol:
                continue
            if normalized_side is not None and str(
                record.get("side") or ""
            ).upper() != normalized_side:
                continue
            if normalized_revision is not None and record.get(
                "effectiveRevision"
            ) != normalized_revision:
                continue
            if normalized_reason is not None and str(
                record.get("exitReason") or ""
            ) != normalized_reason:
                continue
            if normalized_control is not None:
                record_control = _record_control_source(record)
                if normalized_control == RESULT_UNKNOWN:
                    if record_control != RESULT_UNKNOWN:
                        continue
                elif record_control != normalized_control:
                    continue
            if normalized_result is not None and (
                classify_result(record.get("realizedPnl")) != normalized_result
            ):
                continue
            if from_value is not None or to_value is not None:
                exit_value = record.get("exitTimestamp")
                if not _is_number(exit_value):
                    continue
                if from_value is not None and float(exit_value) < from_value:
                    continue
                if to_value is not None and float(exit_value) > to_value:
                    continue
            filtered.append(record)

        ordered = _sort_records(filtered, normalized_sort, normalized_direction)
        total = len(ordered)
        page_count = (
            (total + normalized_page_size - 1) // normalized_page_size
            if total
            else 0
        )
        normalized_page = min(normalized_page, max(1, page_count))
        start = (normalized_page - 1) * normalized_page_size
        page_records = ordered[start:start + normalized_page_size]

        return {
            "available": total > 0,
            "filters": {
                "period": period,
                "scope": normalized_scope,
                "mode": normalized_mode,
                "symbol": normalized_symbol,
                "side": normalized_side,
                "result": normalized_result,
                "revision": normalized_revision,
                "exitReason": normalized_reason,
                "controlSource": normalized_control,
                "fromTimestamp": from_value,
                "toTimestamp": to_value,
            },
            "sort": {
                "field": normalized_sort,
                "direction": normalized_direction,
            },
            "pagination": {
                "page": normalized_page,
                "pageSize": normalized_page_size,
                "total": total,
                "pageCount": page_count,
                "hasNext": normalized_page < page_count,
                "hasPrevious": normalized_page > 1,
            },
            "options": options,
            "records": [_project_record(record) for record in page_records],
            "metrics": compute_metrics(filtered),
            "periodTimeAuthority": PERIOD_TIME_AUTHORITY,
            "resultClassification": RESULT_CLASSIFICATION_RULE,
            "semantics": TRADE_HISTORY_SEMANTICS,
        }

    def detail(self, record_id: Any) -> Optional[dict]:
        if not isinstance(record_id, str) or not record_id.strip():
            return None
        target = record_id.strip()
        for record in self.store.load():
            if not is_production_eligible(record):
                continue
            if record.get("recordId") == target:
                return _project_record(record)
        return None


def default_trade_history_service() -> TradeHistoryService:
    return TradeHistoryService()
