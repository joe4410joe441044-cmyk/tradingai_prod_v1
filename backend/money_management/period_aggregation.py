"""Pure Decimal aggregation for daily, weekly and monthly MM periods."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable, Tuple

from .period_models import (
    PERIOD_SCHEMA_VERSION,
    PERIOD_TIMEZONE,
    SETTLEMENT_CURRENCY,
    MoneyManagementEquitySnapshot,
    MoneyManagementPeriod,
    MoneyManagementPeriodAggregate,
    MoneyManagementPnlEvent,
    EquitySource,
    PeriodType,
)


def period_for(occurred_at: datetime, period_type: PeriodType) -> MoneyManagementPeriod:
    if not isinstance(period_type, PeriodType):
        raise TypeError("PeriodType required")
    if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
        raise TypeError("occurred_at must be timezone-aware")
    value = occurred_at.astimezone(timezone.utc)
    midnight = value.replace(hour=0, minute=0, second=0, microsecond=0)
    if period_type is PeriodType.DAILY:
        start = midnight
        end = start + timedelta(days=1)
        key = start.strftime("%Y-%m-%d")
    elif period_type is PeriodType.WEEKLY:
        start = midnight - timedelta(days=midnight.weekday())
        end = start + timedelta(days=7)
        iso_year, iso_week, _ = start.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
    else:
        start = midnight.replace(day=1)
        end = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        key = start.strftime("%Y-%m")
    return MoneyManagementPeriod(
        PERIOD_SCHEMA_VERSION,
        period_type,
        key,
        PERIOD_TIMEZONE,
        start,
        end,
    )


def build_period_aggregate(
    events: Iterable[MoneyManagementPnlEvent],
    period: MoneyManagementPeriod,
    currency: str = SETTLEMENT_CURRENCY,
) -> MoneyManagementPeriodAggregate:
    if not isinstance(period, MoneyManagementPeriod):
        raise TypeError("period required")
    unique = {}
    for event in events:
        if not isinstance(event, MoneyManagementPnlEvent):
            raise TypeError("normalized PnL event required")
        if event.currency != currency:
            raise ValueError("mixed or unsupported currency")
        if not period.contains(event.occurred_at):
            raise ValueError("event outside requested period")
        existing = unique.get(event.event_id)
        if existing is not None and existing != event:
            raise ValueError("conflicting duplicate event")
        unique[event.event_id] = event
    ordered = tuple(sorted(unique.values(), key=lambda item: item.event_id))
    zero = Decimal("0")
    gross = sum((event.gross_realized_pnl for event in ordered), zero)
    fees = sum((event.fees for event in ordered), zero)
    funding = sum((event.funding for event in ordered), zero)
    nets = tuple(event.net_realized_pnl for event in ordered)
    profit = sum((value for value in nets if value > 0), zero)
    loss = sum((-value for value in nets if value < 0), zero)
    occurred = tuple(event.occurred_at for event in ordered)
    recorded = tuple(event.recorded_at for event in ordered)
    sequences = tuple(event.sequence for event in ordered)
    return MoneyManagementPeriodAggregate(
        PERIOD_SCHEMA_VERSION,
        period,
        currency,
        len(ordered),
        gross,
        fees,
        funding,
        gross - fees + funding,
        profit,
        loss,
        sum(value > 0 for value in nets),
        sum(value < 0 for value in nets),
        min(occurred) if occurred else None,
        max(occurred) if occurred else None,
        max(sequences) if sequences else None,
        tuple(event.event_id for event in ordered),
        max(recorded) if recorded else None,
    )


def aggregate_event_into_periods(
    events: Iterable[MoneyManagementPnlEvent],
    occurred_at: datetime,
) -> Tuple[MoneyManagementPeriodAggregate, ...]:
    materialized = tuple(events)
    return tuple(
        build_period_aggregate(materialized, period_for(occurred_at, period_type))
        for period_type in PeriodType
    )


def build_equity_snapshot(
    *,
    captured_at: datetime,
    starting_equity: Decimal,
    current_equity: Decimal,
    previous_high_water_mark: Decimal,
    source: EquitySource,
    currency: str = SETTLEMENT_CURRENCY,
) -> MoneyManagementEquitySnapshot:
    for name, value in (
        ("starting_equity", starting_equity),
        ("current_equity", current_equity),
        ("previous_high_water_mark", previous_high_water_mark),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, Decimal)
            or not value.is_finite()
        ):
            raise TypeError(f"{name} must be finite Decimal")
    if starting_equity < 0 or previous_high_water_mark < 0:
        raise ValueError("starting equity and HWM must be non-negative")
    peak = max(starting_equity, current_equity, previous_high_water_mark)
    drawdown = max(Decimal("0"), peak - current_equity)
    drawdown_percent = None if peak == 0 else drawdown / peak * Decimal("100")
    return MoneyManagementEquitySnapshot(
        PERIOD_SCHEMA_VERSION,
        captured_at,
        currency,
        starting_equity,
        current_equity,
        peak,
        drawdown,
        drawdown_percent,
        source,
    )


def update_equity_snapshot(
    previous: MoneyManagementEquitySnapshot,
    *,
    captured_at: datetime,
    current_equity: Decimal,
    source: EquitySource,
) -> MoneyManagementEquitySnapshot:
    if not isinstance(previous, MoneyManagementEquitySnapshot):
        raise TypeError("previous equity snapshot required")
    if not isinstance(captured_at, datetime) or captured_at.tzinfo is None:
        raise TypeError("captured_at must be timezone-aware")
    if captured_at.astimezone(timezone.utc) <= previous.captured_at:
        raise ValueError("out-of-order equity snapshot")
    return build_equity_snapshot(
        captured_at=captured_at,
        starting_equity=previous.starting_equity,
        current_equity=current_equity,
        previous_high_water_mark=previous.peak_equity,
        source=source,
        currency=previous.currency,
    )
