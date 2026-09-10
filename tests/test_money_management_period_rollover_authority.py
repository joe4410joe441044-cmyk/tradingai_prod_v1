"""Regression for MM period-rollover authority across accounting periods.

Closes the gap proven by PASS_MM_DISPATCH_REJECTION_ROOT_CAUSE_PROVEN: a valid
post-RUNNING baseline handoff was rejected with
``period rollover requires authoritative starting equity`` whenever the
persisted MM state belonged to a previous accounting period.

The fix rolls expired periods forward using the existing accounting-rebase
contract (``build_accounting_rebase_update``) when the current runtime
observation carries the authoritative starting equity required by that
contract. These tests prove the production case now succeeds while every
fail-closed path remains rejected.
"""

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from backend.money_management.enums import RiskState, TradingMode
from backend.money_management.loss_application_registration import (
    MoneyManagementConfigProvider,
    build_default_money_management_config,
)
from backend.money_management.loss_persistence_adapter import (
    load_loss_state,
    save_loss_state,
)
from backend.money_management.loss_persistence_models import (
    PERSISTENCE_SCHEMA_VERSION,
    AccountingRebaseAuthoritySource,
    FreshnessStatus,
    PeriodCode,
    PersistedCashFlowState,
    PersistedDrawdownState,
    PersistedLossPeriodState,
    PersistedLossState,
)
from backend.money_management.loss_reason_models import (
    BlockReason,
    LossReasonContract,
    ReasonCode,
    RecommendedAction,
)
from backend.money_management.loss_runtime_evaluation_bridge import (
    LossRuntimeEvaluationBridge,
    LossRuntimeEvaluationStatus,
)
from backend.money_management.loss_runtime_event_models import LossRuntimeEventType
from backend.money_management.loss_runtime_hook import (
    MoneyManagementRuntimeHook,
    MoneyManagementRuntimeHookRegistration,
    register_money_management_runtime_hook,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    RuntimeLifecycle,
    StateSource,
)
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeDataQuality,
    LossRuntimeMetrics,
    LossRuntimeMetricsReadRequest,
)
from backend.money_management.loss_runtime_store_models import (
    LossLimitRuntimeSnapshot,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
)
from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import PeriodType
from tests.test_money_management_loss_accounting_rebase import (
    OBSERVED,
    production_metrics,
    production_snapshot,
)
from tests.test_money_management_loss_runtime_update_dispatcher import (
    Lifecycle,
    Source,
    app_with,
)
from tests.test_money_management_dispatch_fail_close import Bot

D = Decimal


def _reason(at, decision_state=RiskState.NORMAL,
             recommended_action=RecommendedAction.CONTINUE,
             primary_reason=ReasonCode.NONE, block_reasons=()):
    return LossReasonContract(
        "money-management-loss-reason/v1",
        at,
        decision_state,
        recommended_action,
        primary_reason,
        (),
        (),
        block_reasons,
        (),
        (),
        (),
        False,
    )


def _state_at(at, starting_equity=D("1000"), decision=None,
              daily_pnl=D("0"), weekly_pnl=D("0"), monthly_pnl=D("0")):
    decision = decision if decision is not None else _reason(at)

    def period(code, typ, pnl):
        value = period_for(at, typ)
        loss = max(D("0"), -pnl)
        return PersistedLossPeriodState(
            code, value.period_key, value.start_at, value.end_at,
            starting_equity, pnl, loss, loss / starting_equity * D("100"),
            D("0"), at,
        )

    return PersistedLossState(
        PERSISTENCE_SCHEMA_VERSION, "primary", "USDT",
        period(PeriodCode.DAILY, PeriodType.DAILY, daily_pnl),
        period(PeriodCode.WEEKLY, PeriodType.WEEKLY, weekly_pnl),
        period(PeriodCode.MONTHLY, PeriodType.MONTHLY, monthly_pnl),
        PersistedDrawdownState(starting_equity, starting_equity, D("0"), D("0"), at),
        PersistedCashFlowState(False, (), D("0")),
        decision, at, freshness=FreshnessStatus.VALID,
    )


def _snapshot_for(state, at=None):
    at = at or state.captured_at
    return LossLimitRuntimeSnapshot(
        RuntimeLifecycle.READY, state, StateSource.CURRENT_RUNTIME_STATE,
        GovernanceProjection.CONTINUE,
        LossLimitRecoveryRequirement(False, (), False, False, False, "none"),
        (), 1, 1, at, at, "ready",
    )


def _metrics_at(at, equity=D("100"), runtime_instance_id="paper-runtime-1",
                daily_pnl=D("0"), weekly_pnl=D("0"), monthly_pnl=D("0"),
                peak_equity=None, drawdown=D("0"), authority_source=None):
    peak = peak_equity if peak_equity is not None else equity
    return LossRuntimeMetrics(
        captured_at=at,
        source_revision=f"account:{at.isoformat()}",
        equity=equity, balance=equity, available_balance=equity,
        realized_pnl=D("0"), unrealized_pnl=D("0"),
        daily_pnl=daily_pnl, weekly_pnl=weekly_pnl, monthly_pnl=monthly_pnl,
        peak_equity=peak, drawdown=drawdown,
        open_exposure=D("0"), position_count=0, trade_count=0,
        source_state="RUNNING",
        data_quality=LossRuntimeDataQuality.COMPLETE,
        runtime_instance_id=runtime_instance_id,
        accounting_authority_source=authority_source,
    )


def _hook_app(lifecycle, metrics_values, now=None):
    app = app_with(lifecycle)
    app.state.money_management = replace(
        app.state.money_management,
        base_config_provider=MoneyManagementConfigProvider(
            build_default_money_management_config()
        ),
    )
    now = now or (OBSERVED + timedelta(seconds=10))
    dispatcher = LossRuntimeUpdateDispatcher(Source(list(metrics_values)))
    hook = MoneyManagementRuntimeHook(app, dispatcher, timestamp_source=lambda: now)
    app.state.money_management_runtime_hook = (
        MoneyManagementRuntimeHookRegistration(hook, Bot(), now)
    )
    return app, hook, dispatcher


PREV_DAY = datetime(2026, 8, 9, 11, 36, tzinfo=timezone.utc)
CUR_DAY = datetime(2026, 8, 22, 7, 54, 26, tzinfo=timezone.utc)


class PeriodRolloverAuthorityRegressionTests(unittest.TestCase):
    """Exact production case: previous-period state + post-RUNNING handoff."""

    def test_production_period_rollover_handoff_accepts_dispatch(self):
        lifecycle = Lifecycle()
        lifecycle.snapshot = production_snapshot()
        app, hook, _ = _hook_app(
            lifecycle, [production_metrics()], now=OBSERVED + timedelta(seconds=10)
        )

        self.assertEqual(
            lifecycle.snapshot.state.daily_state.period_id, "2026-08-09"
        )
        self.assertEqual(production_metrics().open_exposure, D("0"))
        self.assertEqual(production_metrics().position_count, 0)

        result = hook.handle("BALANCE_UPDATE", "production-period-rollover")

        self.assertEqual(
            result.runtime_dispatch_status, LossRuntimeDispatchStatus.APPLIED
        )
        snap = lifecycle.get_snapshot()
        self.assertGreater(snap.revision, 1)
        self.assertGreater(snap.sequence, 1)
        self.assertEqual(snap.state.daily_state.period_id, "2026-08-22")
        self.assertEqual(snap.state.weekly_state.period_id, "2026-W34")
        self.assertEqual(snap.state.monthly_state.period_id, "2026-08")
        self.assertEqual(snap.state.daily_state.starting_equity, D("100"))
        self.assertEqual(snap.state.weekly_state.starting_equity, D("100"))
        self.assertEqual(
            snap.state.monthly_state.starting_equity, D("1000")
        )
        self.assertEqual(snap.state.drawdown_state.current_equity, D("100"))
        self.assertEqual(snap.state.drawdown_state.drawdown_amount, D("0"))
        self.assertEqual(len(snap.state.accounting_rebases), 1)
        record = snap.state.accounting_rebases[0]
        self.assertEqual(record.authoritative_equity, D("100"))
        self.assertTrue(record.rebase_id.startswith("runtime-rollover:"))

    def test_live_rollover_accepts_explicit_live_account_authority(self):
        lifecycle = Lifecycle()
        lifecycle.snapshot = production_snapshot()
        app = app_with(lifecycle)
        app.state.money_management = replace(
            app.state.money_management,
            base_config_provider=MoneyManagementConfigProvider(
                build_default_money_management_config()
            ),
        )
        now = OBSERVED + timedelta(seconds=10)
        bridge = LossRuntimeEvaluationBridge(trading_mode=TradingMode.LIVE)
        dispatcher = LossRuntimeUpdateDispatcher(
            Source([replace(
                production_metrics(),
                accounting_authority_source="REAL_LIVE_ACCOUNT_EQUITY",
            )]), evaluation_bridge=bridge
        )
        hook = MoneyManagementRuntimeHook(app, dispatcher, timestamp_source=lambda: now)
        app.state.money_management_runtime_hook = (
            MoneyManagementRuntimeHookRegistration(hook, Bot(), now)
        )

        result = hook.handle("BALANCE_UPDATE", "live-rollover-authorized")

        self.assertEqual(
            result.runtime_dispatch_status,
            LossRuntimeDispatchStatus.APPLIED,
        )
        self.assertEqual(
            lifecycle.get_snapshot().state.accounting_authority_source.value,
            "REAL_LIVE_ACCOUNT_EQUITY",
        )

    def test_registered_hook_uses_bot_runtime_mode_not_default_mm_mode(self):
        class RuntimeBot(Bot):
            def __init__(self, mode):
                self.config = {"mode": mode}
                self.callback = None

            def initialize_money_management_runtime_metrics(self, *args):
                return True

            def set_money_management_runtime_hook(self, callback):
                self.callback = callback
                return True

            def get_runtime_metrics_snapshot(self):
                return {}

        def registered(mode):
            lifecycle = Lifecycle()
            lifecycle.snapshot = production_snapshot()
            app = app_with(lifecycle)
            bot = RuntimeBot(mode)
            source = Source([replace(
                production_metrics(),
                accounting_authority_source=(
                    "REAL_LIVE_ACCOUNT_EQUITY"
                    if mode == "live" else "PAPER_RUNTIME_EQUITY"
                ),
            )])
            with patch(
                "backend.money_management.loss_runtime_hook."
                "BotManagerLossRuntimeMetricsSource",
                return_value=source,
            ):
                registration = register_money_management_runtime_hook(
                    app,
                    lambda: bot,
                    timestamp_source=lambda: OBSERVED + timedelta(seconds=10),
                )
            self.assertIsNotNone(registration)
            self.assertIsNotNone(bot.callback)
            return bot.callback(
                "BALANCE_UPDATE", f"{mode}-runtime-period-rollover"
            )

        paper = registered("paper")
        live = registered("live")

        self.assertEqual(
            paper.runtime_dispatch_status, LossRuntimeDispatchStatus.APPLIED
        )
        self.assertEqual(
            live.runtime_dispatch_status, LossRuntimeDispatchStatus.APPLIED
        )


class SamePeriodAndFailClosedTests(unittest.TestCase):

    def test_A_same_period_dispatch_unchanged(self):
        at = CUR_DAY
        state = _state_at(at)
        snap = _snapshot_for(state, at=at)
        metrics = _metrics_at(at + timedelta(seconds=30))
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:same-period:BALANCE_UPDATE"
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        next_state = result.build_context.next_state
        self.assertEqual(
            next_state.daily_state.period_id, state.daily_state.period_id
        )
        self.assertEqual(len(next_state.accounting_rebases), 0)

    def test_C_next_day_missing_authoritative_equity_fail_closed(self):
        state = _state_at(PREV_DAY)
        snap = _snapshot_for(state, at=PREV_DAY)
        metrics = _metrics_at(CUR_DAY, equity=None)
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:missing-equity:BALANCE_UPDATE"
        )
        self.assertEqual(
            result.status, LossRuntimeEvaluationStatus.RECOVERY_REQUIRED
        )
        self.assertEqual(
            result.safe_reasons,
            ("period rollover requires authoritative starting equity",),
        )

    def test_C2_nonpositive_equity_fail_closed(self):
        state = _state_at(PREV_DAY)
        snap = _snapshot_for(state, at=PREV_DAY)
        metrics = _metrics_at(CUR_DAY, equity=D("0"), peak_equity=D("0"))
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:zero-equity:BALANCE_UPDATE"
        )
        self.assertEqual(
            result.status, LossRuntimeEvaluationStatus.RECOVERY_REQUIRED
        )

    def test_D_stale_metrics_predating_state_fail_closed(self):
        state = _state_at(CUR_DAY)
        snap = _snapshot_for(state, at=CUR_DAY)
        metrics = _metrics_at(PREV_DAY)
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:stale:BALANCE_UPDATE"
        )
        self.assertEqual(
            result.status, LossRuntimeEvaluationStatus.RECOVERY_REQUIRED
        )
        self.assertEqual(
            result.safe_reasons,
            ("period rollover requires authoritative starting equity",),
        )

    def test_F_missing_runtime_scope_fail_closed(self):
        state = _state_at(PREV_DAY)
        snap = _snapshot_for(state, at=PREV_DAY)
        metrics = _metrics_at(CUR_DAY, runtime_instance_id=None)
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:no-runtime:BALANCE_UPDATE"
        )
        self.assertEqual(
            result.status, LossRuntimeEvaluationStatus.RECOVERY_REQUIRED
        )

    def test_E_flat_zero_exposure_accepted(self):
        state = _state_at(PREV_DAY)
        snap = _snapshot_for(state, at=PREV_DAY)
        metrics = _metrics_at(CUR_DAY, equity=D("100"))
        self.assertEqual(metrics.position_count, 0)
        self.assertEqual(metrics.open_exposure, D("0"))
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:flat:BALANCE_UPDATE"
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        next_state = result.build_context.next_state
        self.assertEqual(
            next_state.daily_state.starting_equity, D("100")
        )
        self.assertEqual(next_state.drawdown_state.current_equity, D("100"))


class IdempotencyTests(unittest.TestCase):

    def test_G_duplicate_idempotent_handoff_is_safe(self):
        lifecycle = Lifecycle()
        lifecycle.snapshot = production_snapshot()
        app, hook, dispatcher = _hook_app(
            lifecycle,
            [production_metrics(), production_metrics()],
            now=OBSERVED + timedelta(seconds=10),
        )

        first = hook.handle("BALANCE_UPDATE", "production-period-rollover")
        self.assertEqual(
            first.runtime_dispatch_status, LossRuntimeDispatchStatus.APPLIED
        )
        snap_after_first = lifecycle.get_snapshot()
        rebases_after_first = len(snap_after_first.state.accounting_rebases)

        second = hook.handle("BALANCE_UPDATE", "production-period-rollover")
        self.assertEqual(second.status.value, "DUPLICATE")
        snap_after_second = lifecycle.get_snapshot()
        self.assertEqual(
            len(snap_after_second.state.accounting_rebases), rebases_after_first
        )
        self.assertEqual(snap_after_second.revision, snap_after_first.revision)
        self.assertEqual(snap_after_second.sequence, snap_after_first.sequence)


class WeeklyBoundaryTests(unittest.TestCase):

    def test_H_weekly_boundary_correct_period_transition(self):
        prev = datetime(2026, 8, 9, 11, 36, tzinfo=timezone.utc)
        cur = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
        state = _state_at(prev)
        snap = _snapshot_for(state, at=prev)
        metrics = _metrics_at(cur, equity=D("100"))
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:weekly:BALANCE_UPDATE"
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        next_state = result.build_context.next_state
        self.assertEqual(next_state.daily_state.period_id, "2026-08-10")
        self.assertNotEqual(
            next_state.weekly_state.period_id, state.weekly_state.period_id
        )
        self.assertEqual(next_state.weekly_state.starting_equity, D("100"))
        self.assertEqual(
            next_state.monthly_state.period_id, state.monthly_state.period_id
        )
        self.assertEqual(
            next_state.monthly_state.starting_equity, D("1000")
        )


class MonthlyBoundaryTests(unittest.TestCase):

    def test_I_monthly_boundary_correct_period_transition(self):
        prev = datetime(2026, 8, 30, 11, 36, tzinfo=timezone.utc)
        cur = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
        state = _state_at(prev)
        snap = _snapshot_for(state, at=prev)
        metrics = _metrics_at(cur, equity=D("100"))
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:monthly:BALANCE_UPDATE"
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        next_state = result.build_context.next_state
        self.assertEqual(next_state.daily_state.period_id, "2026-09-01")
        self.assertEqual(next_state.monthly_state.period_id, "2026-09")
        self.assertEqual(next_state.monthly_state.starting_equity, D("100"))
        self.assertEqual(next_state.daily_state.starting_equity, D("100"))
        self.assertEqual(len(next_state.accounting_rebases), 1)
        record = next_state.accounting_rebases[0]
        self.assertIn(PeriodCode.MONTHLY, record.affected_periods)


class RestrictiveGovernanceTests(unittest.TestCase):

    def test_J_monthly_loss_block_preserved_across_daily_weekly_rollover(self):
        prev = datetime(2026, 8, 9, 11, 36, tzinfo=timezone.utc)
        cur = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)
        locked_reason = _reason(
            prev,
            decision_state=RiskState.LOCKED,
            recommended_action=RecommendedAction.BLOCK_EXECUTION,
            primary_reason=ReasonCode.MONTHLY_LOSS_BLOCK,
            block_reasons=(BlockReason.MONTHLY_LOSS_BLOCK,),
        )
        state = _state_at(
            prev, starting_equity=D("1000"), decision=locked_reason,
            monthly_pnl=D("-50"),
        )
        snap = _snapshot_for(state, at=prev)
        metrics = _metrics_at(
            cur, equity=D("950"), peak_equity=D("1000"), drawdown=D("5"),
            monthly_pnl=D("-50"),
        )
        result = LossRuntimeEvaluationBridge().evaluate(
            metrics, snap, "bot:restrictive:BALANCE_UPDATE"
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        next_state = result.build_context.next_state
        self.assertEqual(next_state.risk_state, RiskState.LOCKED)
        self.assertEqual(
            result.build_context.governance_projection,
            GovernanceProjection.BLOCK_EXECUTION,
        )
        self.assertEqual(next_state.monthly_state.period_id, "2026-08")
        self.assertEqual(
            next_state.monthly_state.net_realized_pnl, D("-50")
        )


class LiveModeIsolationTests(unittest.TestCase):

    LIVE = AccountingRebaseAuthoritySource.REAL_LIVE_ACCOUNT_EQUITY

    def live_metrics(self, at, **kwargs):
        kwargs["authority_source"] = self.LIVE.value
        return _metrics_at(at, **kwargs)

    def test_exact_production_paper_hwm_is_not_reused_for_live(self):
        paper_hwm = D("100.0805801773")
        live_equity = D("7.91836966")
        state = _state_at(CUR_DAY, starting_equity=D("100"))
        state = replace(
            state,
            drawdown_state=PersistedDrawdownState(
                paper_hwm, D("100"), paper_hwm - D("100"),
                (paper_hwm - D("100")) / paper_hwm * D("100"), CUR_DAY,
            ),
        )
        false_drawdown = (
            (paper_hwm - live_equity) / paper_hwm * D("100")
        )
        result = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            self.live_metrics(
                CUR_DAY + timedelta(seconds=30),
                equity=live_equity,
                peak_equity=paper_hwm,
                drawdown=false_drawdown,
            ),
            _snapshot_for(state),
            "live:production-drawdown-authority-reset",
        )

        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        next_state = result.build_context.next_state
        self.assertEqual(next_state.drawdown_state.high_water_mark, live_equity)
        self.assertEqual(next_state.drawdown_state.current_equity, live_equity)
        self.assertEqual(next_state.drawdown_state.drawdown_percent, D("0"))
        self.assertNotIn(
            BlockReason.DRAWDOWN_BLOCK,
            next_state.last_decision.block_reasons,
        )
        self.assertEqual(next_state.risk_state, RiskState.NORMAL)

    def test_same_live_authority_restart_preserves_hwm_and_real_block(self):
        state = replace(
            _state_at(CUR_DAY, starting_equity=D("8")),
            drawdown_state=PersistedDrawdownState(
                D("10"), D("10"), D("0"), D("0"), CUR_DAY,
            ),
            accounting_authority_source=self.LIVE,
        )
        result = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            self.live_metrics(
                CUR_DAY + timedelta(seconds=30),
                equity=D("9"), peak_equity=D("10"), drawdown=D("10"),
            ),
            _snapshot_for(state),
            "live:same-authority-real-drawdown",
        )

        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        next_state = result.build_context.next_state
        self.assertEqual(next_state.drawdown_state.high_water_mark, D("10"))
        self.assertEqual(next_state.drawdown_state.drawdown_percent, D("10"))
        self.assertIn(
            BlockReason.DRAWDOWN_BLOCK,
            next_state.last_decision.block_reasons,
        )

    def test_cross_mode_persistence_restart_remains_authority_consistent(self):
        state = _state_at(CUR_DAY, starting_equity=D("100"))
        first = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            self.live_metrics(
                CUR_DAY + timedelta(seconds=30),
                equity=D("8"), peak_equity=D("100"), drawdown=D("92"),
            ),
            _snapshot_for(state),
            "live:persist-authority-reset",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertEqual(
                save_loss_state(first.build_context.next_state, path).status.value,
                "SAVED",
            )
            loaded = load_loss_state(path).state

        self.assertIs(loaded.accounting_authority_source, self.LIVE)
        self.assertEqual(loaded.drawdown_state.high_water_mark, D("8"))
        restarted = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            self.live_metrics(
                CUR_DAY + timedelta(seconds=60),
                equity=D("7"), peak_equity=D("8"), drawdown=D("12.5"),
            ),
            _snapshot_for(loaded),
            "live:restart-preserves-hwm",
        )
        self.assertEqual(
            restarted.build_context.next_state.drawdown_state.high_water_mark,
            D("8"),
        )

    def test_paper_previous_period_rebases_from_live_equity(self):
        state = _state_at(PREV_DAY, starting_equity=D("100"))
        result = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            self.live_metrics(CUR_DAY, equity=D("7.91836966")),
            _snapshot_for(state), "live:paper-to-live",
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        next_state = result.build_context.next_state
        self.assertEqual(next_state.daily_state.starting_equity, D("7.91836966"))
        self.assertNotEqual(next_state.daily_state.starting_equity, D("100"))
        self.assertIs(next_state.accounting_authority_source, self.LIVE)
        self.assertIs(next_state.accounting_rebases[-1].authority_source, self.LIVE)

    def test_same_period_paper_state_is_not_reused_for_live(self):
        state = _state_at(CUR_DAY, starting_equity=D("100"))
        result = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            self.live_metrics(CUR_DAY + timedelta(seconds=30), equity=D("8")),
            _snapshot_for(state), "live:same-period-mode-switch",
        )
        next_state = result.build_context.next_state
        self.assertEqual(next_state.daily_state.starting_equity, D("8"))
        self.assertEqual(len(next_state.accounting_rebases), 1)

    def test_live_to_paper_rebases_without_live_contamination(self):
        state = replace(
            _state_at(CUR_DAY, starting_equity=D("8")),
            drawdown_state=PersistedDrawdownState(
                D("200"), D("8"), D("192"), D("96"), CUR_DAY,
            ),
            accounting_authority_source=self.LIVE,
        )
        result = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.PAPER
        ).evaluate(
            _metrics_at(
                CUR_DAY + timedelta(seconds=30), equity=D("125"),
                peak_equity=D("200"), drawdown=D("37.5"),
            ),
            _snapshot_for(state), "paper:live-to-paper",
        )
        next_state = result.build_context.next_state
        self.assertEqual(next_state.daily_state.starting_equity, D("125"))
        self.assertEqual(next_state.drawdown_state.high_water_mark, D("125"))
        self.assertEqual(next_state.drawdown_state.drawdown_percent, D("0"))
        self.assertIs(
            next_state.accounting_authority_source,
            AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY,
        )

    def test_same_period_valid_live_state_is_reused(self):
        state = replace(
            _state_at(CUR_DAY, starting_equity=D("8")),
            accounting_authority_source=self.LIVE,
        )
        result = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            self.live_metrics(CUR_DAY + timedelta(seconds=30), equity=D("8")),
            _snapshot_for(state), "live:same-period-restart",
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        self.assertEqual(len(result.build_context.next_state.accounting_rebases), 0)
        self.assertEqual(
            result.build_context.next_state.daily_state.starting_equity, D("8")
        )

    def test_live_new_period_uses_new_live_equity(self):
        state = replace(
            _state_at(PREV_DAY, starting_equity=D("8")),
            drawdown_state=PersistedDrawdownState(
                D("10"), D("8"), D("2"), D("20"), PREV_DAY,
            ),
            accounting_authority_source=self.LIVE,
        )
        result = LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            self.live_metrics(
                CUR_DAY, equity=D("9"), peak_equity=D("10"),
                drawdown=D("10"),
            ),
            _snapshot_for(state), "live:new-period",
        )
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        self.assertEqual(
            result.build_context.next_state.daily_state.starting_equity, D("9")
        )
        self.assertEqual(
            result.build_context.next_state.drawdown_state.high_water_mark,
            D("10"),
        )

    def test_live_missing_or_wrong_runtime_authority_fails_closed(self):
        state = _state_at(PREV_DAY)
        bridge = LossRuntimeEvaluationBridge(trading_mode=TradingMode.LIVE)
        for authority in (None, "PAPER_RUNTIME_EQUITY"):
            with self.subTest(authority=authority):
                result = bridge.evaluate(
                    _metrics_at(CUR_DAY, authority_source=authority),
                    _snapshot_for(state), f"live:bad-authority:{authority}",
                )
                self.assertEqual(
                    result.status, LossRuntimeEvaluationStatus.RECOVERY_REQUIRED
                )

    def test_live_missing_zero_and_nonfinite_equity_fail_closed(self):
        state = _state_at(PREV_DAY)
        bridge = LossRuntimeEvaluationBridge(trading_mode=TradingMode.LIVE)
        for equity, peak in ((None, D("100")), (D("0"), D("0"))):
            with self.subTest(equity=equity):
                result = bridge.evaluate(
                    self.live_metrics(CUR_DAY, equity=equity, peak_equity=peak),
                    _snapshot_for(state), f"live:bad-equity:{equity}",
                )
                self.assertEqual(
                    result.status, LossRuntimeEvaluationStatus.RECOVERY_REQUIRED
                )
        with self.assertRaises(ValueError):
            self.live_metrics(CUR_DAY, equity=D("NaN"))


if __name__ == "__main__":
    unittest.main()
