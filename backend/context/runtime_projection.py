"""Normalize already-produced runtime projections into canonical observations.

The functions in this module are pure. They do not call an exchange, open a
socket, read credentials, or mutate trading state. Missing facts stay
``UNKNOWN`` or ``UNAVAILABLE``. A missing number is never replaced with zero,
and ``UNKNOWN`` is never rewritten to ``PASS``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
import math
from typing import Mapping

from backend.runtime.current_position_view import timestamp as unix_timestamp

from .schema import (
    Availability,
    ContextObservation,
    FieldObservation,
    Freshness,
    ProvenanceEntry,
    SectionMeta,
    ValueState,
)

READER = "runtime-truth-reader"
_MISSING = object()
_MARKET_MODES = frozenset({"PAPER", "LIVE"})
_AUTHORITIES = frozenset({"BOT", "MANUAL"})
_AMBIGUOUS_REASONS = frozenset(
    {
        "MULTIPLE_POSITIONS",
        "POSITION_STATE_AMBIGUOUS",
        "SYMBOL_CONTEXT_MISMATCH",
        "POSITION_SOURCE_UNAVAILABLE",
        "POSITION_CONTRADICTION",
        "MODE_UNRESOLVED",
        "INCOMPLETE_OPEN_POSITION",
    }
)
_PAPER_SOURCE_MARKERS = ("PAPER",)
_LIVE_SOURCE_MARKERS = ("LIVE", "KUCOIN", "REAL_ACCOUNT")


def _field(
    name: str,
    *,
    value: str | int | float | bool | None,
    state: ValueState,
    source: str,
    observed_at: datetime | None,
    freshness: Freshness,
) -> FieldObservation:
    return FieldObservation(
        name=name,
        value=value,
        state=state,
        source=source,
        observedAt=observed_at,
        freshness=freshness,
    )


def _observation(
    *,
    source: str,
    observed_at: datetime | None,
    freshness: Freshness,
    availability: Availability,
    detail: str,
    fields: list[FieldObservation],
) -> ContextObservation:
    ordered = tuple(sorted(fields, key=lambda item: item.name))
    return ContextObservation(
        meta=SectionMeta(
            source=source,
            observedAt=observed_at,
            freshness=freshness,
            availability=availability,
            provenance=(
                ProvenanceEntry(
                    source=source,
                    reader=READER,
                    observedAt=observed_at,
                    detail=detail,
                ),
            ),
            detail=detail,
        ),
        fields=ordered,
    )


def parse_producer_time(value: object) -> datetime | None:
    """Parse a producer timestamp. Naive clocks and context time are rejected."""

    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    seconds = unix_timestamp(value)
    if seconds is None:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _token(value: object) -> str | None:
    if isinstance(value, Enum):
        value = value.value
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    return text.upper() if text else None


def _lookup(mapping: Mapping[str, object] | None, keys: tuple[str, ...]) -> object:
    if not isinstance(mapping, Mapping):
        return _MISSING
    for key in keys:
        if key in mapping:
            return mapping[key]
    return _MISSING


def _lookup_path(mapping: Mapping[str, object] | None, path: tuple[str, ...]) -> object:
    current: object = mapping
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _first_present(
    mapping: Mapping[str, object] | None, paths: tuple[tuple[str, ...], ...]
) -> object:
    for path in paths:
        found = _lookup_path(mapping, path)
        if found is not _MISSING:
            return found
    return _MISSING


def _parse_number(value: object) -> str | int | float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return format(value, "f") if value.is_finite() else None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            return None
        return format(parsed, "f") if parsed.is_finite() else None
    return None


def _explicit_freshness(value: object) -> Freshness | None:
    if isinstance(value, Mapping):
        value = value.get("state")
    token = _token(value)
    if token == "FRESH":
        return Freshness.FRESH
    if token == "STALE":
        return Freshness.STALE
    if token in {"UNKNOWN", "MISSING", "CONFLICTED"}:
        return Freshness.UNKNOWN
    return None


def _clock(
    mapping: Mapping[str, object] | None,
    time_keys: tuple[str, ...],
    *,
    historical: bool = False,
) -> tuple[datetime | None, Freshness, Availability]:
    raw_time = _lookup(mapping, time_keys)
    observed_at = None if raw_time is _MISSING else parse_producer_time(raw_time)
    claimed = _explicit_freshness(_lookup(mapping, ("freshness",)))
    if historical:
        if observed_at is None and claimed is None:
            return None, Freshness.UNKNOWN, Availability.UNKNOWN
        return observed_at, Freshness.STALE, Availability.STALE
    if claimed is Freshness.STALE:
        return observed_at, Freshness.STALE, Availability.STALE
    if claimed is Freshness.FRESH and observed_at is not None:
        return observed_at, Freshness.FRESH, Availability.AVAILABLE
    return observed_at, Freshness.UNKNOWN, Availability.UNKNOWN


def _number_field(
    name: str,
    raw: object,
    *,
    source: str,
    observed_at: datetime | None,
    freshness: Freshness,
) -> FieldObservation:
    if raw is _MISSING:
        state = ValueState.UNAVAILABLE
        value = None
    elif raw is None:
        state = ValueState.NULL
        value = None
    else:
        value = _parse_number(raw)
        state = ValueState.PRESENT if value is not None else ValueState.UNKNOWN
        if state is not ValueState.PRESENT:
            value = None
    return _field(
        name,
        value=value,
        state=state,
        source=source,
        observed_at=observed_at,
        freshness=freshness,
    )


def _text_field(
    name: str,
    raw: object,
    *,
    source: str,
    observed_at: datetime | None,
    freshness: Freshness,
    vocabulary: frozenset[str] | None = None,
    normalize: bool = False,
) -> FieldObservation:
    if raw is _MISSING:
        return _field(
            name,
            value=None,
            state=ValueState.UNAVAILABLE,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
    if raw is None:
        return _field(
            name,
            value=None,
            state=ValueState.NULL,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
    if isinstance(raw, bool):
        return _field(
            name,
            value=None,
            state=ValueState.UNKNOWN,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
    text = str(raw).strip()
    if not text:
        return _field(
            name,
            value=None,
            state=ValueState.UNKNOWN,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
    token = text.upper()
    use_token = normalize or vocabulary is not None
    stored = token if use_token else text
    if token == "UNKNOWN":
        state = ValueState.UNKNOWN
    elif token == "UNAVAILABLE":
        state = ValueState.UNAVAILABLE
    elif vocabulary is not None and token not in vocabulary:
        state = ValueState.UNKNOWN
    else:
        state = ValueState.PRESENT
    return _field(
        name,
        value=stored if state is ValueState.PRESENT else token,
        state=state,
        source=source,
        observed_at=observed_at,
        freshness=freshness,
    )


def _json_text(value: object) -> str:
    def convert(item: object) -> object:
        if isinstance(item, datetime):
            return (
                item.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            )
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, Enum):
            return item.value
        return str(item)

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=convert,
    )


def _structured_field(
    name: str,
    raw: object,
    *,
    source: str,
    observed_at: datetime | None,
    freshness: Freshness,
) -> FieldObservation:
    if raw is _MISSING:
        state = ValueState.UNAVAILABLE
        value = None
    elif raw is None:
        state = ValueState.NULL
        value = None
    elif isinstance(raw, (str, int, float, bool)):
        if isinstance(raw, float) and not math.isfinite(raw):
            state = ValueState.UNKNOWN
            value = None
        else:
            token = _token(raw) if isinstance(raw, str) else None
            if token == "UNKNOWN":
                state = ValueState.UNKNOWN
                value = "UNKNOWN"
            elif token == "UNAVAILABLE":
                state = ValueState.UNAVAILABLE
                value = "UNAVAILABLE"
            else:
                state = ValueState.PRESENT
                value = raw if not isinstance(raw, str) else raw
    elif isinstance(raw, (Mapping, list, tuple)):
        state = ValueState.PRESENT
        value = _json_text(raw)
    else:
        state = ValueState.PRESENT
        value = _token(raw) or _json_text(str(raw))
    return _field(
        name,
        value=value,
        state=state,
        source=source,
        observed_at=observed_at,
        freshness=freshness,
    )


def _source_family(source: object) -> str | None:
    token = _token(source)
    if token is None:
        return None
    if any(marker in token for marker in _PAPER_SOURCE_MARKERS):
        return "PAPER"
    if any(marker in token for marker in _LIVE_SOURCE_MARKERS):
        return "LIVE"
    return None


def _explicit_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token == "true":
            return True
        if token == "false":
            return False
    return None


def _position_ambiguity(view: Mapping[str, object]) -> str | None:
    reason = _token(view.get("reason"))
    if reason in _AMBIGUOUS_REASONS:
        return reason
    positions = view.get("positions")
    status = _token(view.get("status")) or "UNKNOWN"
    if not isinstance(positions, list) or len(positions) <= 1:
        return None
    if status != "OPEN":
        return "MULTIPLE_POSITIONS"
    symbol = view.get("symbol")
    side = _token(view.get("side"))
    matches = [
        item
        for item in positions
        if isinstance(item, Mapping)
        and item.get("symbol") == symbol
        and _token(item.get("side")) == side
    ]
    if len(matches) != 1:
        return "MULTIPLE_POSITIONS"
    return None


def project_position(view: Mapping[str, object]) -> ContextObservation:
    """Normalize one ``current_position`` view without selecting a new position."""

    source = _token(view.get("source")) or "RUNTIME_POSITION_READER"
    if source == "UNKNOWN":
        source = "RUNTIME_POSITION_READER"
    observed_at, freshness, availability = _clock(
        view, ("sourceUpdatedAt", "observedAt", "evaluatedAt")
    )
    reason = _token(view.get("reason"))
    if reason == "STALE_SOURCE":
        freshness = Freshness.STALE
        availability = Availability.STALE
    ambiguity = _position_ambiguity(view)
    reported_status = _token(view.get("status")) or "UNKNOWN"
    mode = _token(view.get("mode"))
    status = reported_status
    if ambiguity is not None or mode not in _MARKET_MODES:
        status = "UNKNOWN"
        if ambiguity is None and reported_status in {"OPEN", "FLAT"}:
            ambiguity = "MODE_UNRESOLVED"
    side = _token(view.get("side"))
    quantity = _lookup(view, ("quantity",))
    if status == "OPEN" and (
        side not in {"LONG", "SHORT"} or _parse_number(quantity) is None
    ):
        status = "UNKNOWN"
        ambiguity = ambiguity or "INCOMPLETE_OPEN_POSITION"
    if status == "UNKNOWN":
        side_raw: object = _MISSING
        quantity_raw: object = _MISSING
        contract_raw: object = _MISSING
        coin_raw: object = _MISSING
        symbol_raw: object = _MISSING
    else:
        side_raw = side if side is not None else _lookup(view, ("side",))
        quantity_raw = quantity
        contract_raw = _lookup(view, ("contractQuantity",))
        coin_raw = _lookup(view, ("coinQuantity",))
        symbol_raw = _lookup(view, ("symbol",))
    if freshness is Freshness.FRESH and status in {"OPEN", "FLAT"}:
        scope = "CURRENT"
    elif freshness is Freshness.STALE:
        scope = "NOT_CURRENT"
    else:
        scope = "UNKNOWN"
    positions = view.get("positions")
    if isinstance(positions, list) and positions:
        position_count: object = len(positions)
    elif ambiguity == "MULTIPLE_POSITIONS":
        # PAPER projections report the reason without retaining the rows.
        position_count = _MISSING
    else:
        position_count = len(positions) if isinstance(positions, list) else _MISSING
    holding = _lookup(view, ("durationSeconds", "holdingMs"))
    duration: object
    if "durationSeconds" in view:
        duration = view.get("durationSeconds")
    elif "holdingMs" in view and _parse_number(view.get("holdingMs")) is not None:
        duration = float(view["holdingMs"]) / 1000.0
    else:
        duration = holding
    fields = [
        _text_field(
            "status",
            status,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=frozenset({"OPEN", "FLAT", "UNKNOWN"}),
        ),
        _text_field(
            "reportedStatus",
            reported_status,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _text_field(
            "symbol",
            symbol_raw,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _text_field(
            "mode",
            mode if mode in _MARKET_MODES else ("UNKNOWN" if mode else _lookup(view, ("mode",))),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=_MARKET_MODES,
        ),
        _text_field(
            "side",
            side_raw,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=frozenset({"LONG", "SHORT"}),
        ),
        _number_field(
            "quantity",
            quantity_raw,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "contractQuantity",
            contract_raw,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "coinQuantity",
            coin_raw,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "avgEntry",
            _MISSING if status == "UNKNOWN" else _first_present(view, (("avgEntry",), ("entryPrice",))),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "avgExit",
            _MISSING if status == "UNKNOWN" else _first_present(view, (("avgExit",), ("exitPrice",))),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _structured_field(
            "entryTime",
            _MISSING if status == "UNKNOWN" else _time_value(_lookup(view, ("entryTime",))),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _structured_field(
            "exitTime",
            _MISSING if status == "UNKNOWN" else _time_value(_lookup(view, ("exitTime",))),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "pnlUsdt",
            _MISSING if status == "UNKNOWN" else _first_present(view, (("pnlUsdt",), ("unrealizedPnl",))),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "pnlPercent",
            _MISSING if status == "UNKNOWN" else _lookup(view, ("pnlPercent",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "durationSeconds",
            _MISSING if status == "UNKNOWN" else duration,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "leverage",
            _MISSING if status == "UNKNOWN" else _lookup(view, ("leverage",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "riskPercent",
            _lookup(view, ("riskPercent",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "stopLossPercent",
            _lookup(view, ("stopLossPercent",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "takeProfitPercent",
            _lookup(view, ("takeProfitPercent",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "trailingPercent",
            _lookup(view, ("trailingPercent",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "timeExitSeconds",
            _lookup(view, ("timeExitSeconds",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _text_field(
            "ambiguity",
            ambiguity if ambiguity is not None else _MISSING,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "positionCount",
            position_count,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _text_field(
            "observationScope",
            scope,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=frozenset({"CURRENT", "NOT_CURRENT", "UNKNOWN"}),
        ),
    ]
    return _observation(
        source=source if source != "UNKNOWN" else "RUNTIME_POSITION_READER",
        observed_at=observed_at,
        freshness=freshness,
        availability=availability,
        detail="normalized injected current-position projection",
        fields=fields,
    )


def _time_value(raw: object) -> object:
    if raw is _MISSING or raw is None:
        return raw
    parsed = parse_producer_time(raw)
    if parsed is None:
        return raw if isinstance(raw, (str, int, float)) and not isinstance(raw, bool) else _MISSING
    return parsed.isoformat().replace("+00:00", "Z")


def _prefixed(prefix: str, name: str) -> str:
    if not prefix:
        return name
    return prefix + name[:1].upper() + name[1:]


def _account_numbers(
    bucket: Mapping[str, object], prefix: str, *, source: str, observed_at, freshness
) -> list[FieldObservation]:
    specs = (
        ("balance", ("balance",)),
        ("equity", ("equity",)),
        ("available", ("availableBalance", "available")),
        ("unrealizedPnl", ("unrealizedPnl",)),
        ("realizedPnl", ("realizedPnl",)),
        ("marginUsed", ("marginUsed",)),
    )
    fields: list[FieldObservation] = []
    for name, keys in specs:
        raw = _lookup(bucket, keys)
        if name == "available" and isinstance(raw, bool):
            raw = _MISSING
            for key in keys:
                if key in bucket and not isinstance(bucket.get(key), bool):
                    raw = bucket.get(key)
                    break
        fields.append(
            _number_field(
                _prefixed(prefix, name),
                raw,
                source=source,
                observed_at=observed_at,
                freshness=freshness,
            )
        )
    currency = _lookup(bucket, ("currency", "currencyCode", "settleCurrency"))
    fields.append(
        _text_field(
            _prefixed(prefix, "currency"),
            currency,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
    )
    return fields


def _bucket_conflict(mode: str | None, source: object) -> bool:
    family = _source_family(source)
    return family is not None and mode in _MARKET_MODES and family != mode


def project_account(projection: Mapping[str, object]) -> ContextObservation:
    """Project PAPER and LIVE balances into separate fields."""

    paper_raw = _first_present(
        projection, (("paperAccount",), ("paper",))
    )
    live_raw = _first_present(
        projection, (("realAccount",), ("liveAccount",), ("live",))
    )
    dual = paper_raw is not _MISSING or live_raw is not _MISSING
    selected = _token(_first_present(projection, (("mode",), ("selectedMode",))))
    if not dual:
        mode = selected if selected in _MARKET_MODES else None
        source_name = _token(projection.get("source")) or "ACCOUNT_STATUS"
        observed_at, freshness, availability = _clock(
            projection, ("observedAt", "sourceUpdatedAt", "lastUpdate", "lastSync", "updatedAt")
        )
        conflict = _bucket_conflict(mode, projection.get("source"))
        fields = [
            _text_field(
                "mode",
                mode or _MISSING,
                source=source_name,
                observed_at=observed_at,
                freshness=freshness,
                vocabulary=_MARKET_MODES,
            )
        ]
        if conflict:
            freshness = Freshness.UNKNOWN
            availability = Availability.UNKNOWN
            fields.extend(
                _withheld_account_fields("", source_name, observed_at, freshness)
            )
            fields.append(
                _text_field(
                    "modeSourceConflict",
                    "TRUE",
                    source=source_name,
                    observed_at=observed_at,
                    freshness=freshness,
                )
            )
        else:
            fields.extend(
                _account_numbers(
                    projection,
                    "",
                    source=source_name,
                    observed_at=observed_at,
                    freshness=freshness,
                )
            )
            fields.append(
                _text_field(
                    "modeSourceConflict",
                    "FALSE" if mode in _MARKET_MODES else _MISSING,
                    source=source_name,
                    observed_at=observed_at,
                    freshness=freshness,
                    vocabulary=frozenset({"TRUE", "FALSE"}),
                )
            )
        fields.extend(
            _absent_namespaced_account(
                "paper", source_name, observed_at, freshness
            )
            if mode != "PAPER"
            else _account_numbers(
                projection,
                "paper",
                source=source_name,
                observed_at=observed_at,
                freshness=freshness,
            )
        )
        fields.extend(
            _absent_namespaced_account("live", source_name, observed_at, freshness)
            if mode != "LIVE"
            else _account_numbers(
                projection,
                "live",
                source=source_name,
                observed_at=observed_at,
                freshness=freshness,
            )
        )
        scope = _account_scope(mode, conflict, freshness)
        fields.append(
            _text_field(
                "observationScope",
                scope,
                source=source_name,
                observed_at=observed_at,
                freshness=freshness,
                vocabulary=frozenset({"CURRENT", "NOT_CURRENT", "UNKNOWN"}),
            )
        )
        return _observation(
            source=source_name,
            observed_at=observed_at,
            freshness=freshness,
            availability=availability,
            detail="normalized injected account projection",
            fields=fields,
        )

    paper = paper_raw if isinstance(paper_raw, Mapping) else None
    live = live_raw if isinstance(live_raw, Mapping) else None
    paper_source = _token((paper or {}).get("source")) or "PAPER_ACCOUNT"
    live_source = _token((live or {}).get("source")) or "LIVE_ACCOUNT"
    paper_time, paper_fresh, _ = _clock(
        paper, ("observedAt", "sourceUpdatedAt", "lastUpdate", "lastSync", "updatedAt")
    )
    live_time, live_fresh, _ = _clock(
        live, ("observedAt", "sourceUpdatedAt", "lastUpdate", "lastSync", "updatedAt")
    )
    paper_conflict = _bucket_conflict("PAPER", (paper or {}).get("source"))
    live_conflict = _bucket_conflict("LIVE", (live or {}).get("source"))
    selected_mode = selected if selected in _MARKET_MODES else None
    if selected_mode == "PAPER":
        observed_at, freshness = paper_time, paper_fresh
        source_name = paper_source
    elif selected_mode == "LIVE":
        observed_at, freshness = live_time, live_fresh
        source_name = live_source
    else:
        observed_at, freshness = None, Freshness.UNKNOWN
        source_name = "ACCOUNT_STATUS"
    conflict = (selected_mode == "PAPER" and paper_conflict) or (
        selected_mode == "LIVE" and live_conflict
    )
    if conflict or selected_mode is None:
        freshness = Freshness.UNKNOWN
    availability = (
        Availability.AVAILABLE
        if freshness is Freshness.FRESH
        else Availability.STALE
        if freshness is Freshness.STALE
        else Availability.UNKNOWN
    )
    fields = [
        _text_field(
            "mode",
            selected_mode or _MISSING,
            source=source_name,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=_MARKET_MODES,
        ),
        _text_field(
            "modeSourceConflict",
            "TRUE" if paper_conflict or live_conflict else "FALSE",
            source=source_name,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=frozenset({"TRUE", "FALSE"}),
        ),
    ]
    fields.extend(
        _project_bucket(
            paper,
            "paper",
            mode="PAPER",
            conflict=paper_conflict,
            source=paper_source,
            observed_at=paper_time,
            freshness=paper_fresh if not paper_conflict else Freshness.UNKNOWN,
            selected=selected_mode == "PAPER",
            unqualified_source=source_name,
            unqualified_time=observed_at,
            unqualified_freshness=freshness,
        )
    )
    fields.extend(
        _project_bucket(
            live,
            "live",
            mode="LIVE",
            conflict=live_conflict,
            source=live_source,
            observed_at=live_time,
            freshness=live_fresh if not live_conflict else Freshness.UNKNOWN,
            selected=selected_mode == "LIVE",
            unqualified_source=source_name,
            unqualified_time=observed_at,
            unqualified_freshness=freshness,
        )
    )
    if selected_mode is None:
        fields.extend(
            _withheld_account_fields(
                "", source_name, observed_at, Freshness.UNKNOWN
            )
        )
    fields.append(
        _text_field(
            "observationScope",
            _account_scope(selected_mode, conflict, freshness),
            source=source_name,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=frozenset({"CURRENT", "NOT_CURRENT", "UNKNOWN"}),
        )
    )
    return _observation(
        source=source_name,
        observed_at=observed_at,
        freshness=freshness,
        availability=availability,
        detail="normalized injected paper and live account projections",
        fields=fields,
    )


def _account_scope(
    mode: str | None, conflict: bool, freshness: Freshness
) -> str:
    if conflict or mode not in _MARKET_MODES:
        return "UNKNOWN"
    if freshness is Freshness.FRESH:
        return "CURRENT"
    if freshness is Freshness.STALE:
        return "NOT_CURRENT"
    return "UNKNOWN"


_ACCOUNT_NAMES = (
    "balance",
    "equity",
    "available",
    "unrealizedPnl",
    "realizedPnl",
    "marginUsed",
    "currency",
)


def _blank_account_fields(prefix, source, observed_at, freshness, *, missing: bool):
    raw = _MISSING if missing else None
    fields = []
    for name in _ACCOUNT_NAMES:
        if name == "currency":
            fields.append(
                _text_field(
                    _prefixed(prefix, name),
                    _MISSING,
                    source=source,
                    observed_at=observed_at,
                    freshness=freshness,
                )
            )
        else:
            fields.append(
                _number_field(
                    _prefixed(prefix, name),
                    raw,
                    source=source,
                    observed_at=observed_at,
                    freshness=freshness,
                )
            )
    return fields


def _absent_namespaced_account(prefix, source, observed_at, freshness):
    return _blank_account_fields(
        prefix, source, observed_at, freshness, missing=True
    )


def _withheld_account_fields(prefix, source, observed_at, freshness):
    return _blank_account_fields(
        prefix, source, observed_at, freshness, missing=True
    )


def _project_bucket(
    bucket,
    prefix,
    *,
    mode,
    conflict,
    source,
    observed_at,
    freshness,
    selected,
    unqualified_source,
    unqualified_time,
    unqualified_freshness,
):
    del mode
    if not isinstance(bucket, Mapping) or conflict:
        fields = _withheld_account_fields(prefix, source, observed_at, freshness)
        if selected:
            fields.extend(
                _withheld_account_fields(
                    "",
                    unqualified_source,
                    unqualified_time,
                    unqualified_freshness,
                )
            )
        return fields
    fields = _account_numbers(
        bucket, prefix, source=source, observed_at=observed_at, freshness=freshness
    )
    if selected:
        fields.extend(
            _account_numbers(
                bucket,
                "",
                source=unqualified_source,
                observed_at=unqualified_time,
                freshness=unqualified_freshness,
            )
        )
    return fields


def project_small_account(projection: Mapping[str, object]) -> ContextObservation:
    """Copy an existing MM projection. No new risk figure is calculated."""

    source = _token(projection.get("source")) or "MONEY_MANAGEMENT_RUNTIME"
    if source == "UNKNOWN":
        source = "MONEY_MANAGEMENT_RUNTIME"
    observed_at, freshness, availability = _clock(
        projection,
        ("sourceUpdatedAt", "evaluatedAt", "sourceEvaluatedAt", "observedAt"),
    )
    paths = {
        "availableCapital": (
            ("availableCapital",),
            ("capitalEligibility", "availableCapital"),
            ("metrics", "availableCapital"),
        ),
        "riskBudget": (
            ("riskBudget",),
            ("capitalEligibility", "riskBudget"),
            ("metrics", "riskBudget"),
        ),
        "riskPercent": (
            ("riskPercent",),
            ("executabilitySettings", "riskPercent"),
        ),
        "leverage": (
            ("leverage",),
            ("effectiveLeverage",),
            ("executabilitySettings", "effectiveLeverage"),
        ),
        "stopLossPercent": (
            ("stopLossPercent",),
            ("executabilitySettings", "stopLossPercent"),
        ),
        "takeProfitPercent": (("takeProfitPercent",),),
        "trailingPercent": (("trailingPercent",),),
        "timeExitSeconds": (("timeExitSeconds",),),
        "marginMode": (("marginMode",),),
        "parameterRevision": (
            ("parameterRevision",),
            ("policyVersion",),
            ("configRevision",),
            ("capitalEligibility", "policyVersion"),
        ),
        "mmStatus": (
            ("mmStatus",),
            ("mmMode",),
            ("ruinGuardStatus",),
            ("capitalEligibility", "mmMode"),
            ("capitalEligibility", "ruinGuardStatus"),
        ),
    }
    fields = [
        _number_field(
            name,
            _first_present(projection, path),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
        if name
        not in {"marginMode", "parameterRevision", "mmStatus"}
        else _text_field(
            name,
            _first_present(projection, path),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
        for name, path in paths.items()
    ]
    blockers = _first_present(
        projection, (("blockers",), ("reasonCodes",), ("blockReasons",))
    )
    fields.append(
        _structured_field(
            "blockers",
            blockers,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
    )
    stamped = _lookup(
        projection, ("sourceUpdatedAt", "evaluatedAt", "sourceEvaluatedAt", "observedAt")
    )
    fields.append(
        _structured_field(
            "sourceUpdatedAt",
            _time_value(stamped),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
    )
    return _observation(
        source=source,
        observed_at=observed_at,
        freshness=freshness,
        availability=availability,
        detail="normalized injected money-management projection",
        fields=fields,
    )


def _diagnostic_scope(diagnostics: Mapping[str, object]) -> str:
    provenance = diagnostics.get("evaluationProvenance")
    if isinstance(provenance, Mapping):
        token = _token(provenance.get("provenance"))
    else:
        token = _token(diagnostics.get("provenance"))
    if token in {"CURRENT", "HISTORICAL", "UNKNOWN"}:
        return token
    return "UNKNOWN"


def _step_provenance(step: Mapping[str, object], scope: str) -> object:
    raw = step.get("provenance")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, Mapping) and "provenance" in raw:
        return raw.get("provenance")
    return scope


def _step_freshness_token(step: Mapping[str, object]) -> object:
    raw = step.get("freshness", _MISSING)
    if raw is _MISSING:
        return _MISSING
    if isinstance(raw, Mapping):
        return raw.get("state", _MISSING)
    return raw


def project_trading_cycle(diagnostics: Mapping[str, object]) -> ContextObservation:
    """Attach STEP 0–14 diagnostics without changing their status vocabulary."""

    raw_source = diagnostics.get("source")
    source = (
        raw_source.strip()
        if isinstance(raw_source, str) and raw_source.strip()
        else "backend.runtime.cycle_diagnostics"
    )
    scope = _diagnostic_scope(diagnostics)
    observed_at, freshness, availability = _clock(
        diagnostics,
        ("diagnosticsGeneratedAt", "evaluatedAt", "sourceUpdatedAt"),
        historical=scope == "HISTORICAL",
    )
    if scope != "CURRENT":
        if scope == "HISTORICAL" and observed_at is not None:
            freshness = Freshness.STALE
            availability = Availability.STALE
        else:
            freshness = Freshness.UNKNOWN
            availability = Availability.UNKNOWN
    elif freshness is Freshness.FRESH:
        availability = Availability.AVAILABLE
    fields: list[FieldObservation] = [
        _text_field(
            "diagnosticScope",
            scope,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=frozenset({"CURRENT", "HISTORICAL", "UNKNOWN"}),
        ),
        _text_field(
            "cycleState",
            _lookup(diagnostics, ("cycleState",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _structured_field(
            "rootBlocker",
            _root_blocker_value(diagnostics.get("rootBlocker", _MISSING)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _number_field(
            "rootBlockerStep",
            _root_blocker_step(diagnostics),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _structured_field(
            "diagnosticsGeneratedAt",
            _time_value(_lookup(diagnostics, ("diagnosticsGeneratedAt",))),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _structured_field(
            "sourceUpdatedAt",
            _time_value(
                _first_present(
                    diagnostics,
                    (
                        ("sourceUpdatedAt",),
                        ("evaluationProvenance", "sourceUpdatedAt"),
                    ),
                )
            ),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
    ]
    steps = diagnostics.get("steps")
    by_index: dict[int, Mapping[str, object]] = {}
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, Mapping) and isinstance(step.get("index"), int):
                by_index[step["index"]] = step
    fields.append(
        _number_field(
            "stepCount",
            len(by_index),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        )
    )
    for index in range(15):
        step = by_index.get(index)
        prefix = f"step.{index}."
        if step is None:
            for suffix in (
                "index",
                "name",
                "status",
                "current",
                "required",
                "blocker",
                "blockerType",
                "userActionRequired",
                "evaluatedAt",
                "provenance",
                "freshness",
            ):
                raw: object = index if suffix == "index" else "UNKNOWN"
                if suffix == "index":
                    fields.append(
                        _number_field(
                            prefix + suffix,
                            index,
                            source=source,
                            observed_at=None,
                            freshness=Freshness.UNKNOWN,
                        )
                    )
                else:
                    fields.append(
                        _text_field(
                            prefix + suffix,
                            raw,
                            source=source,
                            observed_at=None,
                            freshness=Freshness.UNKNOWN,
                        )
                    )
            continue
        step_time = parse_producer_time(step.get("evaluatedAt"))
        step_freshness = _explicit_freshness(_step_freshness_token(step)) or Freshness.UNKNOWN
        if step_freshness is Freshness.FRESH and step_time is None:
            step_freshness = Freshness.UNKNOWN
        fields.extend(
            [
                _number_field(
                    prefix + "index",
                    step.get("index", _MISSING),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                ),
                _text_field(
                    prefix + "name",
                    step.get("name", _MISSING),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                ),
                _text_field(
                    prefix + "status",
                    step.get("status", _MISSING),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                ),
                _structured_field(
                    prefix + "current",
                    step.get("current", _MISSING),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                ),
                _structured_field(
                    prefix + "required",
                    step.get("required", _MISSING),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                ),
                _text_field(
                    prefix + "blocker",
                    step.get("reasonCode", _MISSING),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                ),
                _text_field(
                    prefix + "blockerType",
                    step.get("blockerType", _MISSING),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                ),
                _text_field(
                    prefix + "userActionRequired",
                    step.get("actionable", _MISSING),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                    vocabulary=frozenset({"YES", "NO", "CONDITIONAL", "UNKNOWN"}),
                ),
                _structured_field(
                    prefix + "evaluatedAt",
                    _time_value(step.get("evaluatedAt", _MISSING)),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                ),
                _text_field(
                    prefix + "provenance",
                    _step_provenance(step, scope),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                    vocabulary=frozenset({"CURRENT", "HISTORICAL", "UNKNOWN"}),
                ),
                _text_field(
                    prefix + "freshness",
                    _step_freshness_token(step),
                    source=source,
                    observed_at=step_time,
                    freshness=step_freshness,
                    vocabulary=frozenset({"FRESH", "STALE", "UNKNOWN"}),
                ),
            ]
        )
    return _observation(
        source=source,
        observed_at=observed_at,
        freshness=freshness,
        availability=availability,
        detail="normalized injected trading-cycle diagnostics",
        fields=fields,
    )


def _root_blocker_value(raw: object) -> object:
    if raw is _MISSING or raw is None or isinstance(raw, (str, int, float, bool)):
        return raw
    if isinstance(raw, Mapping):
        if "reasonCode" in raw and raw.get("reasonCode") is not None:
            return raw.get("reasonCode")
        return _json_text(raw)
    return _json_text(str(raw))


def _root_blocker_step(diagnostics: Mapping[str, object]) -> object:
    if "rootBlockerStep" in diagnostics:
        return diagnostics.get("rootBlockerStep")
    root = diagnostics.get("rootBlocker")
    if isinstance(root, Mapping) and "step" in root:
        return root.get("step")
    return _MISSING


def _nested_mapping(mapping: Mapping[str, object], key: str) -> Mapping[str, object] | None:
    value = mapping.get(key)
    return value if isinstance(value, Mapping) else None


def _execution_lookup(
    projection: Mapping[str, object], keys: tuple[str, ...]
) -> object:
    containers: list[Mapping[str, object]] = [projection]
    for key in ("execution", "tradeSettings", "governance_state", "emergency"):
        nested = _nested_mapping(projection, key)
        if nested is not None:
            containers.append(nested)
    for container in containers:
        found = _lookup(container, keys)
        if found is not _MISSING:
            return found
    return _MISSING


def project_execution_control(projection: Mapping[str, object]) -> ContextObservation:
    """Normalize authority flags. ``realOrderAllowed`` is true only when explicit."""

    source = _token(projection.get("source")) or "BOT_MANAGER_STATUS"
    observed_at, freshness, availability = _clock(
        projection,
        ("sourceEvaluatedAt", "evaluatedAt", "observedAt", "timestamp"),
    )
    selected = _execution_lookup(projection, ("selectedMode", "savedMode"))
    trade_mode = _execution_lookup(projection, ("tradeMode", "tradeModeCapability"))
    selected_token = None if selected is _MISSING else _token(selected)
    trade_token = None if trade_mode is _MISSING else _token(trade_mode)
    if selected_token is not None and trade_token is not None:
        mismatch: object = selected_token != trade_token
    else:
        mismatch = _MISSING
    allowed_raw = _execution_lookup(
        projection, ("realOrderAllowed", "real_order_allowed")
    )
    explicit = None if allowed_raw is _MISSING else _explicit_bool(allowed_raw)
    if explicit is True:
        allowed_value: object = True
        allowed_state = ValueState.PRESENT
        evidence = "EXPLICIT_TRUE"
    elif explicit is False:
        allowed_value = False
        allowed_state = ValueState.PRESENT
        evidence = "EXPLICIT_FALSE"
    else:
        allowed_value = False
        allowed_state = ValueState.UNKNOWN
        evidence = "FAIL_CLOSED"
    authority = _execution_lookup(projection, ("controlAuthority", "control"))
    if authority is _MISSING:
        nested_gov = _nested_mapping(projection, "governance_state")
        authority = _lookup(nested_gov, ("mode",))
        if authority is not _MISSING and _token(authority) not in _AUTHORITIES:
            authority = _MISSING
    entry = _execution_lookup(projection, ("entryAuthority", "entry_authority"))
    if entry is _MISSING:
        position = _nested_mapping(projection, "currentPosition")
        entry = _lookup(position, ("entryAuthority", "entry_authority", "control"))
    fields = [
        _text_field(
            "selectedMode",
            selected,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            normalize=True,
        ),
        _text_field(
            "tradeMode",
            trade_mode,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            normalize=True,
        ),
        _text_field(
            "executionMode",
            _execution_lookup(projection, ("executionMode", "execution_mode")),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            normalize=True,
        ),
        _text_field(
            "controlAuthority",
            authority,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=_AUTHORITIES,
        ),
        _text_field(
            "entryAuthority",
            entry,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=_AUTHORITIES,
        ),
        _field(
            "realOrderAllowed",
            value=allowed_value if isinstance(allowed_value, bool) else False,
            state=allowed_state,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _text_field(
            "realOrderAllowedEvidence",
            evidence,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
        ),
        _text_field(
            "botState",
            _execution_lookup(projection, ("botState", "status")),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            normalize=True,
        ),
        _text_field(
            "loopState",
            _execution_lookup(projection, ("loopState",)),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            normalize=True,
        ),
        _text_field(
            "emergencyState",
            _execution_lookup(projection, ("emergencyState", "state")),
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            normalize=True,
        ),
        _text_field(
            "modeMismatch",
            "TRUE" if mismatch is True else "FALSE" if mismatch is False else _MISSING,
            source=source,
            observed_at=observed_at,
            freshness=freshness,
            vocabulary=frozenset({"TRUE", "FALSE"}),
        ),
    ]
    return _observation(
        source=source,
        observed_at=observed_at,
        freshness=freshness,
        availability=availability,
        detail="normalized injected execution-control projection",
        fields=fields,
    )
