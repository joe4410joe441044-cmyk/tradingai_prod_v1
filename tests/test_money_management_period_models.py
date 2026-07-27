import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import (
    PERIOD_SCHEMA_VERSION,
    MoneyManagementEquitySnapshot,
    MoneyManagementPeriod,
    MoneyManagementPeriodAggregate,
    MoneyManagementPnlEvent,
    EquitySource,
    PeriodType,
    PnlEventType,
    PnlEventSource,
    from_dict,
    validate_timezone_name,
)

D = Decimal
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def event(**overrides):
    values = dict(
        schema_version=PERIOD_SCHEMA_VERSION,
        event_id="event-1",
        occurred_at=NOW,
        recorded_at=NOW + timedelta(seconds=1),
        event_type=PnlEventType.REALIZED_PNL,
        symbol="BTCUSDT",
        gross_realized_pnl=D("10"),
        fees=D("1"),
        funding=D("2"),
        currency="USDT",
        source=PnlEventSource.EXECUTION_NORMALIZED,
        sequence=1,
    )
    values.update(overrides)
    return MoneyManagementPnlEvent(**values)


class PeriodModelTests(unittest.TestCase):
    def test_event_net_formula_profit_loss_and_funding(self):
        self.assertEqual(event().net_realized_pnl, D("11"))
        self.assertEqual(event(funding=D("-2")).net_realized_pnl, D("7"))
        self.assertEqual(
            event(gross_realized_pnl=D("-10"), funding=D("0")).net_realized_pnl,
            D("-11"),
        )
        self.assertEqual(
            event(
                gross_realized_pnl=D("0"), fees=D("0"), funding=D("0")
            ).net_realized_pnl,
            D("0"),
        )

    def test_event_strict_validation(self):
        for overrides in (
            {"event_id": ""},
            {"occurred_at": NOW.replace(tzinfo=None)},
            {"recorded_at": NOW.replace(tzinfo=None)},
            {"fees": D("-1")},
            {"gross_realized_pnl": D("NaN")},
            {"currency": ""},
            {"currency": "USD"},
            {"sequence": True},
            {"sequence": -1},
            {"event_type": "REALIZED_PNL"},
            {"schema_version": "v2"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises((TypeError, ValueError)):
                    event(**overrides)

    def test_timezone_contract(self):
        self.assertEqual(validate_timezone_name("UTC"), "UTC")
        for value in ("", "Mars/Olympus", "Asia/Tokyo"):
            with self.assertRaises(ValueError):
                validate_timezone_name(value)

    def test_period_model_rejects_invalid_range_key_and_extra_on_restore(self):
        daily = period_for(NOW, PeriodType.DAILY)
        with self.assertRaises(ValueError):
            MoneyManagementPeriod(
                PERIOD_SCHEMA_VERSION,
                PeriodType.DAILY,
                "wrong",
                "UTC",
                daily.start_at,
                daily.end_at,
            )
        payload = daily.to_dict()
        payload["secret"] = "x"
        with self.assertRaises(ValueError):
            from_dict(MoneyManagementPeriod, payload)

    def test_event_serialization_round_trip(self):
        original = event()
        restored = from_dict(MoneyManagementPnlEvent, original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(original.to_dict()["gross_realized_pnl"], "10")
        self.assertTrue(original.to_dict()["occurred_at"].endswith("Z"))
        self.assertEqual(original.to_dict()["event_type"], "REALIZED_PNL")

    def test_aggregate_serialization_round_trip(self):
        period = period_for(NOW, PeriodType.DAILY)
        aggregate = MoneyManagementPeriodAggregate.empty(period)
        restored = from_dict(MoneyManagementPeriodAggregate, aggregate.to_dict())
        self.assertEqual(restored, aggregate)

    def test_equity_contract_and_round_trip(self):
        snapshot = MoneyManagementEquitySnapshot(
            PERIOD_SCHEMA_VERSION,
            NOW,
            "USDT",
            D("100"),
            D("95"),
            D("100"),
            D("5"),
            D("5"),
            EquitySource.NORMALIZED_EQUITY,
        )
        self.assertEqual(
            from_dict(MoneyManagementEquitySnapshot, snapshot.to_dict()), snapshot
        )
        with self.assertRaises(ValueError):
            MoneyManagementEquitySnapshot(
                PERIOD_SCHEMA_VERSION,
                NOW,
                "USDT",
                D("100"),
                D("95"),
                D("100"),
                D("4"),
                D("4"),
                EquitySource.NORMALIZED_EQUITY,
            )


if __name__ == "__main__":
    unittest.main()
