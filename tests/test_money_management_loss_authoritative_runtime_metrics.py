import ast
import math
import threading
import unittest
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

from backend.money_management.enums import RiskState
from backend.money_management.loss_authoritative_runtime_metrics import (
    AuthoritativeLossRuntimeMetrics,
    AuthoritativeLossRuntimeMetricsState,
)
from backend.money_management.loss_persistence_models import (
    PERSISTENCE_SCHEMA_VERSION,
    FreshnessStatus,
    PeriodCode,
    PersistedCashFlowState,
    PersistedDrawdownState,
    PersistedLossPeriodState,
    PersistedLossState,
)
from backend.money_management.loss_reason_models import (
    LossReasonContract,
    ReasonCode,
    RecommendedAction,
)
from backend.money_management.loss_runtime_integration_models import StateSource
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeMetricsReadRequest,
    LossRuntimeMetricsReadStatus,
)
from backend.money_management.loss_runtime_metrics_source import (
    BotManagerLossRuntimeMetricsSource,
)
from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import PeriodType


D = Decimal
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def reason(at):
    return LossReasonContract(
        "money-management-loss-reason/v1",
        at,
        RiskState.NORMAL,
        RecommendedAction.CONTINUE,
        ReasonCode.NONE,
        (),
        (),
        (),
        (),
        (),
        (),
        False,
    )


def period(code, kind, at, pnl):
    current = period_for(at, kind)
    loss = max(D("0"), -pnl)
    return PersistedLossPeriodState(
        code,
        current.period_key,
        current.start_at,
        current.end_at,
        D("1000"),
        pnl,
        loss,
        loss / D("10"),
        D("0"),
        at,
    )


def persisted(at=NOW, pnl=D("0"), peak=D("1000"), equity=D("1000")):
    drawdown = max(peak - equity, D("0"))
    drawdown_pct = drawdown / peak * D("100") if peak > 0 else D("0")
    return PersistedLossState(
        PERSISTENCE_SCHEMA_VERSION,
        "primary",
        "USDT",
        period(PeriodCode.DAILY, PeriodType.DAILY, at, pnl),
        period(PeriodCode.WEEKLY, PeriodType.WEEKLY, at, pnl),
        period(PeriodCode.MONTHLY, PeriodType.MONTHLY, at, pnl),
        PersistedDrawdownState(
            peak, equity, drawdown, drawdown_pct, at
        ),
        PersistedCashFlowState(False, (), D("0")),
        reason(at),
        at,
        freshness=FreshnessStatus.VALID,
    )


def observe(state, at=NOW, **overrides):
    values = {
        "as_of": at,
        "session_id": 1,
        "balance": D("1000"),
        "equity": D("1000"),
        "available_balance": D("1000"),
        "realized_pnl": D("0"),
        "unrealized_pnl": D("0"),
        "position": None,
        "mark_price": D("100"),
        "engine_peak_equity": D("1000"),
        "source_state": "RUNNING",
    }
    values.update(overrides)
    return state.observe(**values)


class Reader:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get_runtime_metrics_snapshot(self):
        return MappingProxyType(self.snapshot.to_runtime_mapping(0))


class AuthoritativeRuntimeMetricsTests(unittest.TestCase):
    def new_state(self, at=NOW, source=StateSource.INITIAL_STATE, **kwargs):
        result = AuthoritativeLossRuntimeMetricsState("runtime-1")
        result.restore(persisted(at=at, **kwargs), source, at)
        return result

    @staticmethod
    def observer_bot_type():
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
            and node.name == "_observe_money_management_runtime_metrics"
        )
        module = ast.Module(
            body=[ast.ClassDef("ObserverBot", [], [], [method], [])],
            type_ignores=[],
        )
        namespace = {
            "datetime": datetime,
            "deepcopy": deepcopy,
            "math": math,
            "timezone": timezone,
            "MappingProxyType": MappingProxyType,
        }
        exec(
            compile(ast.fix_missing_locations(module), str(path), "exec"),
            namespace,
        )
        return namespace["ObserverBot"]

    def test_contract_is_typed_frozen_utc_and_serializable(self):
        snapshot = observe(self.new_state())
        self.assertIsInstance(snapshot, AuthoritativeLossRuntimeMetrics)
        self.assertEqual(snapshot.as_of.tzinfo, timezone.utc)
        self.assertEqual(snapshot.to_dict()["current_equity"], "1000")
        with self.assertRaises(FrozenInstanceError):
            snapshot.current_equity = D("1")
        with self.assertRaises(TypeError):
            AuthoritativeLossRuntimeMetrics(
                **{**snapshot.__dict__, "current_equity": True}
            )
        with self.assertRaises(ValueError):
            AuthoritativeLossRuntimeMetrics(
                **{**snapshot.__dict__, "current_equity": D("NaN")}
            )

    def test_restore_rolls_stale_checkpoint_periods_forward(self):
        checkpoint_at = datetime(2026, 7, 19, 12, tzinfo=timezone.utc)
        restore_at = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        state = AuthoritativeLossRuntimeMetricsState("runtime-1")

        snapshot = state.restore(
            persisted(at=checkpoint_at, pnl=D("-25")),
            StateSource.PERSISTED_STATE,
            restore_at,
        )

        self.assertEqual(snapshot.daily_realized_pnl, D("0"))
        self.assertEqual(snapshot.weekly_realized_pnl, D("0"))
        self.assertEqual(snapshot.monthly_realized_pnl, D("-25"))
        self.assertIsNone(snapshot.trade_count_daily)
        self.assertEqual(snapshot.source_state, "RESTORED_PERSISTED_STATE")

    def test_restore_rejects_checkpoint_from_future_period(self):
        checkpoint_at = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)
        restore_at = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        state = AuthoritativeLossRuntimeMetricsState("runtime-1")

        with self.assertRaisesRegex(ValueError, "period boundary mismatch"):
            state.restore(
                persisted(at=checkpoint_at),
                StateSource.PERSISTED_STATE,
                restore_at,
            )

    def test_known_zero_is_complete_and_source_reads_available(self):
        snapshot = observe(self.new_state())
        self.assertTrue(snapshot.available)
        self.assertTrue(snapshot.is_complete)
        self.assertEqual(snapshot.daily_realized_pnl, D("0"))
        self.assertEqual(snapshot.open_exposure, D("0"))
        result = BotManagerLossRuntimeMetricsSource(Reader(snapshot)).read_metrics(
            LossRuntimeMetricsReadRequest(
                "bot-manager", NOW + timedelta(seconds=1), timedelta(minutes=1)
            )
        )
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.AVAILABLE)
        self.assertEqual(result.metrics.trade_count_daily, 0)
        self.assertEqual(result.metrics.trade_count_weekly, 0)
        self.assertEqual(result.metrics.trade_count_monthly, 0)

    def test_bot_adapter_keeps_paper_and_live_authority_separate(self):
        bot_type = self.observer_bot_type()
        paper = bot_type()
        paper.engine = SimpleNamespace(
            mode="paper",
            latest_price=D("100"),
            peak_equity=D("1000"),
        )
        paper.money_management_runtime_metrics = self.new_state()
        paper.session_id = 1
        paper.lifecycle_state = "RUNNING"
        paper._capture_account_snapshot = lambda: {
            "balance": D("1000"),
            "equity": D("1000"),
            "availableBalance": D("1000"),
            "realizedPnl": D("0"),
            "unrealizedPnl": D("0"),
            "position": None,
        }
        self.assertTrue(
            paper._observe_money_management_runtime_metrics(
                {"realizedPnl": D("0")},
                None,
                "paper-observation",
            ).available
        )

        live = bot_type()
        live.engine = SimpleNamespace(mode="live", latest_price=D("100"))
        live.money_management_runtime_metrics = self.new_state()
        live.session_id = 1
        live.lifecycle_state = "RUNNING"
        live.real_account_snapshot = {
            "authenticated": True,
            "stale": False,
            "balance": D("1000"),
            "equity": D("1000"),
            "availableBalance": D("1000"),
            "positions": [],
            "lastSync": NOW.timestamp(),
        }
        live_snapshot = live._observe_money_management_runtime_metrics(
            {"realizedPnl": D("0")},
            "TRADE_CLOSE",
            "live-close-without-confirmed-fill-ledger",
        )
        self.assertIsNone(live_snapshot.realized_pnl)
        self.assertIsNone(live_snapshot.daily_realized_pnl)
        self.assertTrue(live_snapshot.available)

    def test_restart_without_persisted_trade_counts_stays_unknown(self):
        snapshot = observe(
            self.new_state(source=StateSource.PERSISTED_STATE)
        )
        self.assertTrue(snapshot.available)
        self.assertFalse(snapshot.is_complete)
        self.assertIsNone(snapshot.trade_count_daily)
        self.assertEqual(snapshot.daily_realized_pnl, D("0"))
        result = BotManagerLossRuntimeMetricsSource(Reader(snapshot)).read_metrics(
            LossRuntimeMetricsReadRequest(
                "bot-manager", NOW + timedelta(seconds=1), timedelta(minutes=1)
            )
        )
        self.assertEqual(result.status, LossRuntimeMetricsReadStatus.PARTIAL)

    def test_paper_session_baseline_preserves_unknown_period_counts(self):
        state = self.new_state(source=StateSource.PERSISTED_STATE)

        baseline = state.begin_paper_session(7, NOW + timedelta(seconds=1))
        observed = observe(
            state,
            at=NOW + timedelta(seconds=2),
            session_id=7,
        )

        self.assertIsNone(baseline.trade_count_daily)
        self.assertIsNone(baseline.trade_count_weekly)
        self.assertIsNone(baseline.trade_count_monthly)
        self.assertEqual(observed.session_trade_count, 0)
        self.assertEqual(
            observed.trade_count_authority_scope, "RUNTIME_SESSION"
        )
        self.assertEqual(observed.trade_count_authority_session_id, 7)
        self.assertTrue(observed.is_complete)
        mapping = observed.to_runtime_mapping(0)
        self.assertEqual(mapping["tradeCount"], 0)
        self.assertIsNone(mapping["tradeCountDaily"])

    def test_paper_session_close_updates_only_session_count_when_history_unknown(self):
        state = self.new_state(source=StateSource.PERSISTED_STATE)
        state.begin_paper_session(7, NOW)

        closed = observe(
            state,
            at=NOW + timedelta(seconds=1),
            session_id=7,
            realized_pnl=D("5"),
            realized_pnl_before=D("0"),
            close_event_id="session-close-1",
        )

        self.assertEqual(closed.session_trade_count, 1)
        self.assertIsNone(closed.trade_count_daily)
        self.assertIsNone(closed.trade_count_weekly)
        self.assertIsNone(closed.trade_count_monthly)

    def test_callback_reregistration_does_not_reset_runtime_peak_or_counts(self):
        state = self.new_state()
        observe(
            state,
            equity=D("1100"),
            balance=D("1100"),
            available_balance=D("1100"),
            engine_peak_equity=D("1100"),
            realized_pnl=D("10"),
            realized_pnl_before=D("0"),
            close_event_id="close-1",
        )
        state.restore(
            persisted(peak=D("1000")),
            StateSource.INITIAL_STATE,
            NOW,
        )
        snapshot = state.snapshot()
        self.assertEqual(snapshot.peak_equity, D("1100"))
        self.assertEqual(snapshot.daily_realized_pnl, D("10"))
        self.assertEqual(snapshot.trade_count_daily, 1)

    def test_confirmed_close_accumulates_all_periods_once(self):
        state = self.new_state()
        first = observe(
            state,
            balance=D("990"),
            equity=D("990"),
            available_balance=D("990"),
            realized_pnl=D("-10"),
            realized_pnl_before=D("0"),
            close_event_id="close-1",
        )
        duplicate = observe(
            state,
            balance=D("990"),
            equity=D("990"),
            available_balance=D("990"),
            realized_pnl=D("-10"),
            realized_pnl_before=D("0"),
            close_event_id="close-1",
        )
        self.assertEqual(first.daily_realized_pnl, D("-10"))
        self.assertEqual(first.weekly_realized_pnl, D("-10"))
        self.assertEqual(first.monthly_realized_pnl, D("-10"))
        self.assertEqual(first.trade_count_daily, 1)
        self.assertEqual(duplicate.daily_realized_pnl, D("-10"))
        self.assertEqual(duplicate.trade_count_daily, 1)

    def test_partial_and_flatten_close_execution_each_count_once(self):
        state = self.new_state()
        observe(
            state,
            realized_pnl=D("2"),
            realized_pnl_before=D("0"),
            close_event_id="partial-close",
        )
        snapshot = observe(
            state,
            realized_pnl=D("5"),
            realized_pnl_before=D("2"),
            close_event_id="emergency-flatten",
        )
        self.assertEqual(snapshot.daily_realized_pnl, D("5"))
        self.assertEqual(snapshot.trade_count_daily, 2)

    def test_unrealized_and_non_close_observation_do_not_accumulate(self):
        state = self.new_state()
        snapshot = observe(
            state,
            equity=D("1005"),
            unrealized_pnl=D("5"),
            position={"qty": 1, "multiplier": D("1")},
            mark_price=D("100"),
        )
        self.assertEqual(snapshot.daily_realized_pnl, D("0"))
        self.assertEqual(snapshot.trade_count_daily, 0)

    def test_period_rollovers_use_utc_boundaries(self):
        start = datetime(2026, 6, 30, 23, 59, tzinfo=timezone.utc)
        state = self.new_state(at=start, pnl=D("-4"))
        snapshot = observe(
            state,
            at=start + timedelta(minutes=2),
            realized_pnl=D("0"),
        )
        self.assertEqual(snapshot.daily_realized_pnl, D("0"))
        self.assertEqual(snapshot.monthly_realized_pnl, D("0"))
        self.assertEqual(snapshot.trade_count_daily, 0)
        self.assertEqual(snapshot.trade_count_monthly, 0)

    def test_week_rollover_is_monday_utc(self):
        sunday = datetime(2026, 7, 26, 23, 59, tzinfo=timezone.utc)
        state = self.new_state(at=sunday, pnl=D("-4"))
        snapshot = observe(
            state,
            at=sunday + timedelta(minutes=2),
            realized_pnl=D("0"),
        )
        self.assertEqual(snapshot.daily_realized_pnl, D("0"))
        self.assertEqual(snapshot.weekly_realized_pnl, D("0"))
        self.assertEqual(snapshot.monthly_realized_pnl, D("-4"))

    def test_peak_and_drawdown_are_derived_without_zero_fallback(self):
        state = self.new_state(peak=D("1000"))
        lower = observe(
            state,
            balance=D("900"),
            equity=D("900"),
            available_balance=D("900"),
            engine_peak_equity=D("1000"),
        )
        self.assertEqual(lower.peak_equity, D("1000"))
        self.assertEqual(lower.current_drawdown_amount, D("100"))
        self.assertEqual(lower.current_drawdown_pct, D("10"))
        unknown = observe(state, equity=None, engine_peak_equity=None)
        self.assertIsNone(unknown.current_drawdown_pct)
        self.assertTrue(unknown.available)

    def test_exposure_uses_absolute_mark_notional_without_netting(self):
        state = self.new_state()
        snapshot = observe(
            state,
            position=[
                {
                    "side": "BUY",
                    "coin_qty": D("2"),
                    "mark_price": D("10"),
                },
                {
                    "side": "SELL",
                    "coin_qty": D("-3"),
                    "mark_price": D("10"),
                },
            ],
            mark_price=None,
        )
        self.assertEqual(snapshot.open_exposure, D("50"))
        self.assertEqual(snapshot.position_count, 2)
        self.assertEqual(snapshot.position_side, "OPEN")

    def test_paper_position_side_and_protective_stop_are_authoritative(self):
        long = observe(
            self.new_state(),
            position={
                "side": "BUY",
                "coin_qty": D("2"),
                "entry_price": D("10"),
                "sl": D("9"),
            },
            mark_price=D("12"),
        )
        self.assertEqual(long.position_side, "LONG")
        self.assertEqual(long.current_risk_amount, D("2"))

        short = observe(
            self.new_state(),
            position={
                "side": "SELL",
                "qty": D("3"),
                "multiplier": D("2"),
                "entry_price": D("10"),
                "sl": D("11.5"),
            },
            mark_price=D("8"),
        )
        self.assertEqual(short.position_side, "SHORT")
        self.assertEqual(short.current_risk_amount, D("9.0"))

    def test_position_without_valid_protective_stop_keeps_risk_unknown(self):
        for position in (
            {
                "side": "BUY",
                "coin_qty": D("2"),
                "entry_price": D("10"),
            },
            {
                "side": "BUY",
                "coin_qty": D("2"),
                "entry_price": D("10"),
                "sl": D("11"),
            },
        ):
            with self.subTest(position=position):
                snapshot = observe(
                    self.new_state(),
                    position=position,
                    mark_price=D("12"),
                )
                self.assertEqual(snapshot.position_side, "LONG")
                self.assertIsNone(snapshot.current_risk_amount)

    def test_unknown_mark_does_not_fallback_to_entry_price(self):
        snapshot = observe(
            self.new_state(),
            position={"coin_qty": D("2"), "entry_price": D("10")},
            mark_price=None,
        )
        self.assertIsNone(snapshot.open_exposure)
        self.assertTrue(snapshot.available)

    def test_malformed_close_delta_fails_closed_without_zero(self):
        snapshot = observe(
            self.new_state(),
            realized_pnl=True,
            realized_pnl_before=D("0"),
            close_event_id="bad-close",
        )
        self.assertIsNone(snapshot.daily_realized_pnl)
        self.assertIsNone(snapshot.trade_count_daily)
        self.assertTrue(snapshot.available)
        self.assertFalse(snapshot.observation_valid)
        result = BotManagerLossRuntimeMetricsSource(Reader(snapshot)).read_metrics(
            LossRuntimeMetricsReadRequest(
                "bot-manager", NOW + timedelta(seconds=1), timedelta(minutes=1)
            )
        )
        self.assertEqual(
            result.status, LossRuntimeMetricsReadStatus.INCONSISTENT
        )

    def test_concurrent_unique_closes_are_serial_and_deadlock_free(self):
        state = self.new_state()
        threads = [
            threading.Thread(
                target=lambda index=index: observe(
                    state,
                    realized_pnl=D(index + 1),
                    realized_pnl_before=D(index),
                    close_event_id=f"close-{index}",
                )
            )
            for index in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        snapshot = state.snapshot()
        self.assertEqual(snapshot.daily_realized_pnl, D("20"))
        self.assertEqual(snapshot.trade_count_daily, 20)


if __name__ == "__main__":
    unittest.main()
