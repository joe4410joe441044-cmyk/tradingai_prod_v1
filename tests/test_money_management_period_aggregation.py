import builtins
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

from backend.money_management.period_aggregation import (
    aggregate_event_into_periods,
    build_equity_snapshot,
    build_period_aggregate,
    period_for,
    update_equity_snapshot,
)
from backend.money_management.period_models import (
    PERIOD_SCHEMA_VERSION,
    MoneyManagementPnlEvent,
    EquitySource,
    PeriodType,
    PnlEventType,
    PnlEventSource,
)

D = Decimal


def event(event_id, occurred_at, net, sequence=1, recorded_at=None):
    return MoneyManagementPnlEvent(
        PERIOD_SCHEMA_VERSION,
        event_id,
        occurred_at,
        recorded_at or occurred_at,
        PnlEventType.REALIZED_PNL,
        "BTCUSDT",
        D(net),
        D("0"),
        D("0"),
        "USDT",
        PnlEventSource.EXECUTION_NORMALIZED,
        sequence,
        trade_id=f"trade-{event_id}",
    )


class BoundaryTests(unittest.TestCase):
    def test_day_half_open_and_year_boundary(self):
        instant = datetime(2026, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
        period = period_for(instant, PeriodType.DAILY)
        self.assertTrue(period.contains(instant))
        self.assertFalse(period.contains(period.end_at))
        next_period = period_for(period.end_at, PeriodType.DAILY)
        self.assertEqual(next_period.period_key, "2027-01-01")

    def test_week_monday_sunday_iso_year_and_week_53(self):
        monday = datetime(2020, 12, 28, tzinfo=timezone.utc)
        period = period_for(monday, PeriodType.WEEKLY)
        self.assertEqual(period.period_key, "2020-W53")
        self.assertEqual(period.start_at.weekday(), 0)
        self.assertTrue(
            period.contains(datetime(2021, 1, 3, 23, 59, tzinfo=timezone.utc))
        )
        self.assertFalse(period.contains(datetime(2021, 1, 4, tzinfo=timezone.utc)))

    def test_month_calendar_lengths_and_year_boundary(self):
        expected = ((2025, 2, 28), (2024, 2, 29), (2026, 4, 30), (2026, 7, 31))
        for year, month, days in expected:
            period = period_for(
                datetime(year, month, 10, tzinfo=timezone.utc), PeriodType.MONTHLY
            )
            self.assertEqual((period.end_at - period.start_at).days, days)
        december = period_for(
            datetime(2026, 12, 1, tzinfo=timezone.utc), PeriodType.MONTHLY
        )
        self.assertEqual(december.end_at, datetime(2027, 1, 1, tzinfo=timezone.utc))

    def test_non_utc_aware_input_normalizes_and_naive_rejected(self):
        plus_nine = timezone(timedelta(hours=9))
        period = period_for(
            datetime(2026, 7, 27, 8, tzinfo=plus_nine), PeriodType.DAILY
        )
        self.assertEqual(period.period_key, "2026-07-26")
        with self.assertRaises(TypeError):
            period_for(datetime(2026, 1, 1), PeriodType.DAILY)


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.when = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        self.period = period_for(self.when, PeriodType.DAILY)

    def test_single_multiple_counts_totals_and_timestamps(self):
        items = (
            event("a", self.when, "10", 1),
            event("b", self.when + timedelta(hours=1), "-4", 2),
            event("c", self.when + timedelta(hours=2), "0", 3),
        )
        result = build_period_aggregate(items, self.period)
        self.assertEqual(result.event_count, 3)
        self.assertEqual(result.profit_total, D("10"))
        self.assertEqual(result.loss_total, D("4"))
        self.assertEqual(result.net_realized_pnl, D("6"))
        self.assertEqual(result.net_loss_amount, D("0"))
        self.assertEqual(result.winning_event_count, 1)
        self.assertEqual(result.losing_event_count, 1)
        self.assertEqual(result.first_event_at, self.when)
        self.assertEqual(result.last_sequence, 3)

    def test_duplicate_idempotent_and_conflict_rejected(self):
        original = event("a", self.when, "10")
        result = build_period_aggregate((original, original), self.period)
        self.assertEqual(result.event_count, 1)
        with self.assertRaises(ValueError):
            build_period_aggregate(
                (original, event("a", self.when, "11")),
                self.period,
            )

    def test_same_trade_different_event_id_counts_separately(self):
        first = event("a", self.when, "1")
        second = replace(event("b", self.when, "1"), trade_id=first.trade_id)
        self.assertEqual(
            build_period_aggregate((first, second), self.period).event_count, 2
        )

    def test_out_of_order_is_deterministic(self):
        older = event("old", self.when, "-2", 1, self.when + timedelta(minutes=10))
        newer = event("new", self.when + timedelta(hours=1), "5", 2)
        left = build_period_aggregate((newer, older), self.period)
        right = build_period_aggregate((older, newer), self.period)
        self.assertEqual(left.to_dict(), right.to_dict())

    def test_event_maps_to_daily_weekly_monthly(self):
        item = event("a", self.when, "1")
        results = aggregate_event_into_periods((item,), self.when)
        self.assertEqual(
            tuple(result.period.period_type for result in results), tuple(PeriodType)
        )
        self.assertTrue(all(result.event_count == 1 for result in results))

    def test_mixed_currency_and_outside_period_rejected(self):
        with self.assertRaises(ValueError):
            build_period_aggregate(
                (event("a", self.when, "1"),),
                self.period,
                currency="USD",
            )
        with self.assertRaises(ValueError):
            build_period_aggregate(
                (event("a", self.period.end_at, "1"),),
                self.period,
            )

    def test_period_reset_creates_new_immutable_aggregate(self):
        old = build_period_aggregate((event("a", self.when, "1"),), self.period)
        next_when = self.period.end_at
        new = build_period_aggregate(
            (event("b", next_when, "2"),),
            period_for(next_when, PeriodType.DAILY),
        )
        self.assertEqual(old.event_count, 1)
        self.assertNotEqual(old.period.period_key, new.period.period_key)


class EquityAndPurityTests(unittest.TestCase):
    def test_peak_below_equal_zero_five_percent_and_large_decimal(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new_peak = build_equity_snapshot(
            captured_at=now,
            starting_equity=D("100"),
            current_equity=D("110"),
            previous_high_water_mark=D("100"),
            source=EquitySource.NORMALIZED_EQUITY,
        )
        self.assertEqual(new_peak.peak_equity, D("110"))
        self.assertEqual(new_peak.drawdown_percent, D("0"))
        below = build_equity_snapshot(
            captured_at=now,
            starting_equity=D("100"),
            current_equity=D("95"),
            previous_high_water_mark=D("100"),
            source=EquitySource.NORMALIZED_EQUITY,
        )
        self.assertEqual(below.drawdown_amount, D("5"))
        self.assertEqual(below.drawdown_percent, D("5"))
        equal = build_equity_snapshot(
            captured_at=now,
            starting_equity=D("100"),
            current_equity=D("100"),
            previous_high_water_mark=D("100"),
            source=EquitySource.NORMALIZED_EQUITY,
        )
        self.assertEqual(equal.drawdown_amount, D("0"))
        zero = build_equity_snapshot(
            captured_at=now,
            starting_equity=D("0"),
            current_equity=D("0"),
            previous_high_water_mark=D("0"),
            source=EquitySource.NORMALIZED_EQUITY,
        )
        self.assertIsNone(zero.drawdown_percent)
        large = build_equity_snapshot(
            captured_at=now,
            starting_equity=D("1E+30"),
            current_equity=D("9.5E+29"),
            previous_high_water_mark=D("1E+30"),
            source=EquitySource.NORMALIZED_EQUITY,
        )
        self.assertEqual(large.drawdown_percent, D("5"))

    def test_equity_update_preserves_global_hwm_and_rejects_out_of_order(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        first = build_equity_snapshot(
            captured_at=now,
            starting_equity=D("100"),
            current_equity=D("110"),
            previous_high_water_mark=D("100"),
            source=EquitySource.NORMALIZED_EQUITY,
        )
        second = update_equity_snapshot(
            first,
            captured_at=now + timedelta(seconds=1),
            current_equity=D("105"),
            source=EquitySource.NORMALIZED_EQUITY,
        )
        self.assertEqual(second.peak_equity, D("110"))
        with self.assertRaises(ValueError):
            update_equity_snapshot(
                second,
                captured_at=now,
                current_equity=D("120"),
                source=EquitySource.NORMALIZED_EQUITY,
            )

    def test_no_file_network_environment_or_runtime_dependency(self):
        item = event("a", datetime(2026, 1, 1, tzinfo=timezone.utc), "1")
        period = period_for(item.occurred_at, PeriodType.DAILY)
        with patch.object(builtins, "open", side_effect=AssertionError("no file")):
            first = build_period_aggregate((item,), period)
            second = build_period_aggregate((item,), period)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
