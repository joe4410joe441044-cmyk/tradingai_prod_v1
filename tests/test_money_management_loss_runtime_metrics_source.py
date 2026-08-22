import unittest
import ast
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import threading
from types import MappingProxyType, SimpleNamespace

from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeDataQuality,
    LossRuntimeMetricsReadRequest,
    LossRuntimeMetricsReadStatus,
)
from backend.money_management.loss_runtime_metrics_source import (
    BotManagerLossRuntimeMetricsSource,
)


NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def raw(**overrides):
    values = {
        "capturedAt": NOW,
        "sourceRevision": "account:7",
        "equity": 1000,
        "balance": 1000,
        "availableBalance": 900,
        "realizedPnL": 0,
        "unrealizedPnL": 0,
        "dailyPnL": 0,
        "weeklyPnL": 0,
        "monthlyPnL": 0,
        "peakEquity": 1000,
        "drawdown": 0,
        "openExposure": 0,
        "positionCount": 0,
        "tradeCount": 0,
        "tradeCountDaily": 0,
        "tradeCountWeekly": 0,
        "tradeCountMonthly": 0,
        "runtimeInstanceId": "runtime-1",
        "sessionId": 1,
        "metricsRevision": 7,
        "observationValid": True,
        "pendingOrderCount": 0,
        "marginUsed": 0,
        "cashFlowState": None,
        "sourceState": "RUNNING",
        "available": True,
    }
    values.update(overrides)
    return values


class Reader:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.calls = 0

    def get_runtime_metrics_snapshot(self):
        self.calls += 1
        if self.error:
            raise self.error
        return MappingProxyType(dict(self.value))


def request(at=NOW + timedelta(seconds=1), age=timedelta(minutes=1)):
    return LossRuntimeMetricsReadRequest("bot-manager", at, age)


def source(reader, completed_at=NOW + timedelta(seconds=1)):
    return BotManagerLossRuntimeMetricsSource(
        reader, timestamp_source=lambda: completed_at
    )


class RuntimeMetricsSourceTests(unittest.TestCase):
    def test_complete_metrics_are_strictly_normalized_without_raw_objects(self):
        reader = Reader(raw())
        result = source(reader).read_metrics(request())
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.AVAILABLE)
        self.assertEqual(result.metrics.equity, Decimal("1000"))
        self.assertEqual(result.metrics.realized_pnl, Decimal("0"))
        self.assertEqual(result.metrics.position_count, 0)
        self.assertEqual(result.metrics.data_quality, LossRuntimeDataQuality.COMPLETE)
        self.assertNotIn("positions", result.metrics.to_dict())
        with self.assertRaises(FrozenInstanceError):
            result.metrics.equity = Decimal("1")

    def test_zero_is_not_treated_as_unknown(self):
        result = source(Reader(raw())).read_metrics(
            request()
        )
        self.assertEqual(result.metrics.open_exposure, Decimal("0"))
        self.assertEqual(result.metrics.trade_count, 0)

    def test_missing_required_metric_is_partial_and_fail_closed(self):
        result = source(
            Reader(raw(equity=None, drawdown=None))
        ).read_metrics(request())
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.PARTIAL)
        self.assertEqual(result.metrics.data_quality, LossRuntimeDataQuality.PARTIAL)
        self.assertIsNone(result.metrics.equity)

    def test_unavailable_snapshot_has_no_metrics(self):
        result = source(
            Reader(raw(available=False))
        ).read_metrics(request())
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.UNAVAILABLE)
        self.assertIsNone(result.metrics)

    def test_invalid_numeric_types_are_rejected(self):
        for value in ("1000", True, float("nan"), float("inf")):
            with self.subTest(value=value):
                result = source(
                    Reader(raw(equity=value))
                ).read_metrics(request())
                self.assertEqual(
                    result.status, LossRuntimeMetricsReadStatus.INCONSISTENT
                )
                self.assertIsNone(result.metrics)

    def test_runtime_identity_revision_and_period_counts_are_strict(self):
        cases = (
            {"tradeCountDaily": True},
            {"tradeCountWeekly": -1},
            {"tradeCountMonthly": 1.5},
            {"runtimeInstanceId": ""},
            {"sessionId": True},
            {"metricsRevision": -1},
            {"observationValid": False},
        )
        for values in cases:
            with self.subTest(values=values):
                result = source(
                    Reader(raw(**values))
                ).read_metrics(request())
                self.assertEqual(
                    result.status, LossRuntimeMetricsReadStatus.INCONSISTENT
                )

    def test_missing_period_trade_count_is_partial_not_zero(self):
        result = source(
            Reader(raw(tradeCountWeekly=None))
        ).read_metrics(request())
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.PARTIAL)
        self.assertIsNone(result.metrics.trade_count_weekly)

    def test_session_authority_allows_unknown_historical_period_counts(self):
        result = source(
            Reader(raw(
                tradeCountDaily=None,
                tradeCountWeekly=None,
                tradeCountMonthly=None,
                sessionTradeCount=0,
                tradeCountAuthorityScope="RUNTIME_SESSION",
                tradeCountAuthoritySessionId=1,
            ))
        ).read_metrics(request())

        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.AVAILABLE)
        self.assertEqual(result.metrics.trade_count, 0)
        self.assertIsNone(result.metrics.trade_count_daily)

    def test_session_count_without_matching_authority_remains_partial(self):
        result = source(
            Reader(raw(
                tradeCountDaily=None,
                tradeCountWeekly=None,
                tradeCountMonthly=None,
                sessionTradeCount=0,
                tradeCountAuthorityScope="RUNTIME_SESSION",
                tradeCountAuthoritySessionId=2,
            ))
        ).read_metrics(request())

        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.PARTIAL)

    def test_relational_inconsistency_is_reported(self):
        cases = (
            {"availableBalance": 1001},
            {"peakEquity": 999},
            {"drawdown": 1},
            {"openExposure": -1},
            {"equity": 999},
        )
        for values in cases:
            with self.subTest(values=values):
                result = source(
                    Reader(raw(**values))
                ).read_metrics(request())
                self.assertEqual(
                    result.status, LossRuntimeMetricsReadStatus.INCONSISTENT
                )

    def test_stale_and_future_snapshots_are_distinct(self):
        stale = source(
            Reader(raw()), completed_at=NOW + timedelta(minutes=2)
        ).read_metrics(
            request(at=NOW + timedelta(minutes=2), age=timedelta(seconds=30))
        )
        future = source(
            Reader(raw(capturedAt=NOW + timedelta(seconds=2)))
        ).read_metrics(request())
        self.assertEqual(stale.status, LossRuntimeMetricsReadStatus.STALE)
        self.assertEqual(future.status, LossRuntimeMetricsReadStatus.INCONSISTENT)

    def test_observation_created_during_read_is_not_artificial_future(self):
        captured = NOW + timedelta(seconds=1, microseconds=500000)
        result = source(
            Reader(raw(capturedAt=captured)),
            completed_at=NOW + timedelta(seconds=2),
        ).read_metrics(request(at=NOW + timedelta(seconds=1)))
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.AVAILABLE)
        self.assertEqual(result.metrics.captured_at, captured)

    def test_reader_exception_is_sanitized(self):
        result = source(
            Reader(error=RuntimeError("secret /tmp/private"))
        ).read_metrics(request())
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.FAILED)
        self.assertNotIn("secret", repr(result))
        self.assertNotIn("/tmp", repr(result))

    def test_bot_manager_reader_body_is_read_only_and_uses_lifecycle_lock(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "backend"
            / "bot_manager"
            / "bot_manager.py"
        )
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bot_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "BotManager"
        )
        method = next(
            node
            for node in bot_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "get_runtime_metrics_snapshot"
        )
        module = ast.Module(
            body=[
                ast.ImportFrom("copy", [ast.alias("deepcopy")], 0),
                ast.ImportFrom(
                    "datetime",
                    [ast.alias("datetime"), ast.alias("timezone")],
                    0,
                ),
                ast.ImportFrom(
                    "types", [ast.alias("MappingProxyType")], 0
                ),
                ast.Import([ast.alias("math")]),
                ast.ClassDef(
                    "ReaderOnlyBot",
                    [],
                    [],
                    [method],
                    [],
                ),
            ],
            type_ignores=[],
        )
        namespace = {}
        exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)

        class CountingLock:
            def __init__(self):
                self.inner = threading.RLock()
                self.entries = 0

            def __enter__(self):
                self.entries += 1
                return self.inner.__enter__()

            def __exit__(self, *args):
                return self.inner.__exit__(*args)

        bot = namespace["ReaderOnlyBot"]()
        bot.shutdown_lock = CountingLock()
        bot.money_management_runtime_metrics = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                to_runtime_mapping=lambda pending: raw(
                    pendingOrderCount=pending
                )
            )
        )
        bot.pending_order = False
        bot.lifecycle_state = "RUNNING"
        result = bot.get_runtime_metrics_snapshot()
        self.assertEqual(bot.shutdown_lock.entries, 1)
        self.assertEqual(result["dailyPnL"], 0)
        with self.assertRaises(TypeError):
            result["balance"] = 0


if __name__ == "__main__":
    unittest.main()
