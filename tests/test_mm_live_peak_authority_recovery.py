"""Validated recovery of a REAL_LIVE HWM contaminated by PAPER equity.

The contaminated state is produced by the real evaluation bridge and runtime
store: PAPER -> LIVE authority transition (validated epoch at 7.91836966),
then a LIVE evaluation whose peak carried the PAPER equity 10000, which locks
on DRAWDOWN_BLOCK exactly like Production.
"""

import inspect
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from Bot.engine.execution_engine import ExecutionEngine
from backend.money_management.enums import RiskState, TradingMode
from backend.money_management.live_peak_authority_recovery import (
    RECOVERY_OPERATION,
    LivePeakRecoveryEvidence,
    LivePeakRecoveryStatus,
    build_live_peak_authority_recovery,
    live_epoch_rebase_ids,
)
from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
)
from backend.money_management.loss_authoritative_runtime_metrics import (
    AuthoritativeLossRuntimeMetricsState,
)
from backend.money_management.loss_governance_projection_dispatcher import (
    get_money_management_governance_projection,
)
from backend.money_management.loss_governance_projection_models import (
    LossEntryPermission,
)
from backend.money_management.loss_http_api import (
    MoneyManagementApiBoundaryException,
    MoneyManagementHttpBoundary,
)
from backend.money_management.loss_persistence_adapter import (
    LoadStatus,
    SaveStatus,
    load_loss_state,
    save_loss_state,
)
from backend.money_management.loss_persistence_models import (
    AccountingRebaseAuthoritySource,
    AccountingRebaseReason,
    PersistedDrawdownState,
)
from backend.money_management.loss_reason_models import BlockReason
from backend.money_management.loss_runtime_evaluation_bridge import (
    LossRuntimeEvaluationBridge,
    LossRuntimeEvaluationStatus,
)
from backend.money_management.loss_runtime_hook import (
    MoneyManagementRuntimeHook,
    MoneyManagementRuntimeHookRegistration,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
    RuntimeLifecycle,
    StateSource,
)
from backend.money_management.loss_runtime_store_models import (
    LossLimitRuntimeUpdate,
    StoreResultStatus,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeUpdateDispatcher,
)
from backend.portfolio.portfolio_manager import PortfolioManager
from tests.test_money_management_loss_runtime_authority_transition import (
    _locked_state,
    _store,
)
from tests.test_money_management_loss_runtime_update_dispatcher import (
    Lifecycle,
    Source,
    app_with,
)
from tests.test_money_management_period_rollover_authority import (
    CUR_DAY,
    _metrics_at,
)


D = Decimal
PAPER = AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY
LIVE = AccountingRebaseAuthoritySource.REAL_LIVE_ACCOUNT_EQUITY
LIVE_EQUITY = D("7.91836966")
PAPER_EQUITY = D("10000")
LIMIT = D("5.00")
RUNTIME = "runtime-recovery-1"


def _evaluate(store, mode, equity, peak, seconds):
    snapshot = store.get_snapshot().snapshot
    at = CUR_DAY + timedelta(seconds=seconds)
    authority = LIVE.value if mode is TradingMode.LIVE else PAPER.value
    drawdown = (peak - equity) / peak * D("100")
    metrics = _metrics_at(
        at, equity=equity, peak_equity=peak, drawdown=drawdown,
        authority_source=authority, runtime_instance_id=RUNTIME,
    )
    evaluation = LossRuntimeEvaluationBridge(trading_mode=mode).evaluate(
        metrics, snapshot, f"eval-{seconds}"
    )
    assert evaluation.status is LossRuntimeEvaluationStatus.SUCCEEDED, evaluation
    context = evaluation.build_context
    update = LossLimitRuntimeUpdate(
        context.next_state, context.governance_projection,
        context.recovery_requirement, context.save_triggers,
        snapshot.revision, snapshot.sequence + 1, at,
        context.transition_reason, context.validated_accounting_rebase_id,
    )
    result = store.apply_update(update)
    assert result.status is StoreResultStatus.SUCCEEDED, result
    return result.snapshot


def contaminated_store(live_equity_now=LIVE_EQUITY):
    """PAPER(10000) -> LIVE START 7.918 -> LIVE eval with contaminated peak."""
    store = _store(_locked_state(PAPER, PAPER_EQUITY, PAPER_EQUITY + D("1")))
    epoch = _evaluate(store, TradingMode.LIVE, LIVE_EQUITY, LIVE_EQUITY, 30)
    assert epoch.state.accounting_authority_source is LIVE
    assert epoch.state.drawdown_state.high_water_mark == LIVE_EQUITY
    locked = _evaluate(store, TradingMode.LIVE, live_equity_now, PAPER_EQUITY, 60)
    assert locked.state.risk_state is RiskState.LOCKED
    assert tuple(locked.state.last_decision.block_reasons) == (
        BlockReason.DRAWDOWN_BLOCK,
    )
    assert locked.state.drawdown_state.high_water_mark == PAPER_EQUITY
    return store


def legitimately_locked_store():
    """PAPER -> LIVE 7.918 -> real LIVE loss to 7.0 (11.6% drawdown)."""
    store = _store(_locked_state(PAPER, PAPER_EQUITY, PAPER_EQUITY + D("1")))
    _evaluate(store, TradingMode.LIVE, LIVE_EQUITY, LIVE_EQUITY, 30)
    locked = _evaluate(store, TradingMode.LIVE, D("7.0"), LIVE_EQUITY, 60)
    assert locked.state.risk_state is RiskState.LOCKED
    return store


def evidence(**overrides):
    values = dict(
        bot_stopped=True,
        execution_disabled=True,
        emergency_clear=True,
        internal_pending_order=False,
        live_account_ready=True,
        live_capital_authority="REAL_LIVE_ACCOUNT",
        live_open_position_state="FLAT",
        live_pending_order_state="NONE",
        live_equity=LIVE_EQUITY,
        live_evaluated_at=CUR_DAY + timedelta(seconds=110),
        paper_equity=D("10000.00"),
        live_epoch_history_available=True,
        live_epoch_observations=(
            (LIVE_EQUITY, LIVE_EQUITY),
            (LIVE_EQUITY, D("10000.00")),
        ),
    )
    values.update(overrides)
    return LivePeakRecoveryEvidence(**values)


def build(store, requested_seconds=120, **overrides):
    return build_live_peak_authority_recovery(
        store.get_snapshot().snapshot,
        evidence(**overrides),
        requested_at=CUR_DAY + timedelta(seconds=requested_seconds),
        runtime_instance_id=RUNTIME,
        maximum_drawdown_pct=LIMIT,
    )


def restored_metrics(state, runtime=RUNTIME):
    metrics = AuthoritativeLossRuntimeMetricsState(runtime)
    metrics.restore(
        state, StateSource.PERSISTED_STATE,
        CUR_DAY + timedelta(seconds=200), preserve_periods=True,
    )
    return metrics


class LivePeakAuthorityRecoveryTests(unittest.TestCase):
    def test_contaminated_live_peak_recovers_under_safe_conditions(self):
        # Matrix 6 (+14: MM returns to normal availability).
        store = contaminated_store()
        result = build(store)
        self.assertIs(result.status, LivePeakRecoveryStatus.ACCEPTED, result.safe_reasons)
        self.assertEqual(result.recovered_high_water_mark, LIVE_EQUITY)
        self.assertEqual(result.contaminated_high_water_mark, PAPER_EQUITY)
        record = result.record
        self.assertIs(record.reason,
                      AccountingRebaseReason.LIVE_PEAK_AUTHORITY_CONTAMINATION_RECOVERY)
        self.assertIs(record.authority_source, LIVE)
        applied = store.apply_update(result.update)
        self.assertIs(applied.status, StoreResultStatus.SUCCEEDED, applied)
        state = applied.snapshot.state
        self.assertIs(state.accounting_authority_source, LIVE)
        self.assertIs(state.risk_state, RiskState.NORMAL)
        self.assertFalse(state.last_decision.fail_closed)
        self.assertEqual(state.drawdown_state.high_water_mark, LIVE_EQUITY)
        self.assertEqual(state.drawdown_state.drawdown_percent, D("0"))
        self.assertIs(applied.snapshot.lifecycle, RuntimeLifecycle.READY)
        self.assertIs(applied.snapshot.governance_projection,
                      GovernanceProjection.CONTINUE)
        before = store.get_snapshot().snapshot.state
        for period in ("daily_state", "weekly_state", "monthly_state"):
            self.assertEqual(getattr(state, period), getattr(before, period))

    def test_legitimate_live_drawdown_is_never_relaxed(self):
        # Matrix 5: LEGITIMATE_LIVE_DRAWDOWN_REBASE_BLOCKED.
        store = legitimately_locked_store()
        result = build(store, live_equity=D("7.0"),
                       live_epoch_observations=((LIVE_EQUITY, LIVE_EQUITY),
                                                (D("7.0"), LIVE_EQUITY)))
        self.assertIs(result.status, LivePeakRecoveryStatus.REJECTED)
        self.assertIn("HIGH_WATER_MARK_EXPLAINED_BY_LIVE_BASELINE", result.safe_reasons)
        self.assertIn("LEGITIMATE_LIVE_DRAWDOWN_PRESENT", result.safe_reasons)
        self.assertIsNone(result.update)

    def test_contaminated_peak_with_real_live_loss_beyond_limit_stays_blocked(self):
        # Matrix 5: even with a proven PAPER contamination, a real LIVE
        # drawdown from the last validated LIVE peak beyond 5% is kept.
        store = contaminated_store(live_equity_now=D("7.0"))
        result = build(store, live_equity=D("7.0"),
                       live_epoch_observations=((LIVE_EQUITY, LIVE_EQUITY),
                                                (D("7.0"), PAPER_EQUITY)))
        self.assertIs(result.status, LivePeakRecoveryStatus.REJECTED)
        self.assertEqual(result.safe_reasons, ("LEGITIMATE_LIVE_DRAWDOWN_PRESENT",))

    def test_small_legitimate_live_drawdown_is_preserved_not_erased(self):
        store = contaminated_store(live_equity_now=D("7.8"))
        result = build(store, live_equity=D("7.8"),
                       live_epoch_observations=((LIVE_EQUITY, LIVE_EQUITY),
                                                (D("7.8"), PAPER_EQUITY)))
        self.assertIs(result.status, LivePeakRecoveryStatus.ACCEPTED, result.safe_reasons)
        drawdown = result.update.next_state.drawdown_state
        self.assertEqual(drawdown.high_water_mark, LIVE_EQUITY)
        self.assertEqual(drawdown.current_equity, D("7.8"))
        self.assertEqual(drawdown.drawdown_amount, LIVE_EQUITY - D("7.8"))

    def test_open_position_is_rejected(self):
        # Matrix 7.
        for state in ("LONG", "SHORT", "UNKNOWN", None):
            with self.subTest(state=state):
                result = build(contaminated_store(), live_open_position_state=state)
                self.assertIs(result.status, LivePeakRecoveryStatus.REJECTED)
                self.assertIn("LIVE_POSITION_NOT_FLAT", result.safe_reasons)

    def test_open_or_pending_orders_are_rejected(self):
        # Matrix 8.
        for state in ("PRESENT", "UNKNOWN", None):
            with self.subTest(state=state):
                result = build(contaminated_store(), live_pending_order_state=state)
                self.assertIs(result.status, LivePeakRecoveryStatus.REJECTED)
                self.assertIn("LIVE_PENDING_ORDER_NOT_CLEAR", result.safe_reasons)
        for value in (True, None):
            with self.subTest(internal=value):
                result = build(contaminated_store(), internal_pending_order=value)
                self.assertIs(result.status, LivePeakRecoveryStatus.REJECTED)
                self.assertIn("INTERNAL_PENDING_ORDER_NOT_CLEAR", result.safe_reasons)

    def test_missing_or_stale_real_equity_is_rejected(self):
        # Matrix 9.
        cases = (
            ({"live_equity": None}, "LIVE_EQUITY_UNAVAILABLE"),
            ({"live_equity": D("0")}, "LIVE_EQUITY_UNAVAILABLE"),
            ({"live_evaluated_at": CUR_DAY + timedelta(seconds=60)},
             "LIVE_EQUITY_NOT_FRESH"),
            ({"live_evaluated_at": None}, "LIVE_EQUITY_NOT_FRESH"),
            ({"live_evaluated_at": CUR_DAY + timedelta(seconds=130)},
             "LIVE_EQUITY_NOT_FRESH"),
            ({"live_account_ready": False}, "LIVE_ACCOUNT_AUTHORITY_NOT_READY"),
            ({"live_capital_authority": "UNAVAILABLE"},
             "LIVE_ACCOUNT_AUTHORITY_NOT_READY"),
        )
        for overrides, reason in cases:
            with self.subTest(overrides=overrides):
                result = build(contaminated_store(), **overrides)
                self.assertIs(result.status, LivePeakRecoveryStatus.REJECTED)
                self.assertIn(reason, result.safe_reasons)

    def test_operational_safety_is_required(self):
        for overrides, reason in (
            ({"bot_stopped": False}, "BOT_NOT_STOPPED"),
            ({"execution_disabled": False}, "EXECUTION_NOT_DISABLED"),
            ({"emergency_clear": False}, "EMERGENCY_NOT_CLEAR"),
        ):
            with self.subTest(reason=reason):
                result = build(contaminated_store(), **overrides)
                self.assertIs(result.status, LivePeakRecoveryStatus.REJECTED)
                self.assertIn(reason, result.safe_reasons)

    def test_contamination_signature_is_required(self):
        cases = (
            ({"paper_equity": D("9999")}, "HIGH_WATER_MARK_NOT_PAPER_DOMAIN_VALUE"),
            ({"paper_equity": None}, "PAPER_EQUITY_UNAVAILABLE"),
            ({"live_epoch_history_available": False}, "LIVE_EPOCH_HISTORY_UNAVAILABLE"),
            ({"live_epoch_observations": ()}, "LIVE_EPOCH_HISTORY_UNAVAILABLE"),
            ({"live_epoch_observations": ((LIVE_EQUITY, LIVE_EQUITY),
                                          (PAPER_EQUITY, PAPER_EQUITY))},
             "LIVE_EQUITY_REACHED_HIGH_WATER_MARK"),
            ({"live_epoch_observations": ((LIVE_EQUITY, LIVE_EQUITY),
                                          (LIVE_EQUITY, D("500")))},
             "HIGH_WATER_MARK_EVOLUTION_UNEXPLAINED"),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                result = build(contaminated_store(), **overrides)
                self.assertIs(result.status, LivePeakRecoveryStatus.REJECTED)
                self.assertIn(reason, result.safe_reasons)

    def test_arbitrary_manual_rebase_is_impossible(self):
        # Matrix 10: no caller supplied peak exists anywhere.
        parameters = inspect.signature(build_live_peak_authority_recovery).parameters
        self.assertFalse({name for name in parameters if "peak" in name or "high" in name})
        self.assertNotIn("high_water_mark", LivePeakRecoveryEvidence.__dataclass_fields__)
        store = contaminated_store()
        result = build(store)
        # A tampered update (any other HWM) is rejected by the store.
        tampered_state = result.update.next_state
        for hwm in (D("7.5"), D("9"), D("8.5")):
            with self.subTest(hwm=hwm):
                equity = min(hwm, LIVE_EQUITY)
                amount = hwm - equity
                forged = LossLimitRuntimeUpdate(
                    replace(
                        tampered_state,
                        drawdown_state=PersistedDrawdownState(
                            hwm, equity, amount, amount / hwm * D("100"),
                            tampered_state.captured_at,
                        ),
                    ),
                    result.update.governance_projection,
                    result.update.recovery_requirement,
                    result.update.save_triggers,
                    result.update.expected_revision,
                    result.update.event_sequence,
                    result.update.occurred_at,
                    result.update.transition_reason,
                    result.update.validated_accounting_rebase_id,
                )
                applied = store.apply_update(forged)
                self.assertIs(applied.status, StoreResultStatus.FAILED)
        # A generic same-authority unlock (no recovery record) stays forbidden.
        generic = LossLimitRuntimeUpdate(
            replace(
                tampered_state,
                accounting_rebases=store.get_snapshot().snapshot.state.accounting_rebases,
            ),
            result.update.governance_projection,
            result.update.recovery_requirement,
            result.update.save_triggers,
            result.update.expected_revision,
            result.update.event_sequence,
            result.update.occurred_at,
            result.update.transition_reason,
            None,
        )
        self.assertIs(store.apply_update(generic).status, StoreResultStatus.FAILED)
        self.assertEqual(
            store.get_snapshot().snapshot.state.drawdown_state.high_water_mark,
            PAPER_EQUITY,
        )

    def test_recovery_cannot_replay_or_run_on_a_repaired_state(self):
        store = contaminated_store()
        result = build(store)
        self.assertIs(store.apply_update(result.update).status, StoreResultStatus.SUCCEEDED)
        again = build(store, requested_seconds=125,
                      live_evaluated_at=CUR_DAY + timedelta(seconds=124))
        self.assertIs(again.status, LivePeakRecoveryStatus.REJECTED)
        self.assertIn("STATE_NOT_DRAWDOWN_ONLY_LOCK", again.safe_reasons)

    def test_repaired_peak_persists_restores_and_resists_recontamination(self):
        # Matrix 11, 12 and 13.
        store = contaminated_store()
        applied = store.apply_update(build(store).update)
        state = applied.snapshot.state
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertIs(save_loss_state(state, path).status, SaveStatus.SAVED)
            loaded = load_loss_state(path)
        self.assertIs(loaded.status, LoadStatus.VALID)
        self.assertEqual(loaded.state.drawdown_state.high_water_mark, LIVE_EQUITY)
        self.assertIs(loaded.state.accounting_authority_source, LIVE)
        self.assertIs(loaded.state.risk_state, RiskState.NORMAL)
        self.assertEqual(loaded.state.accounting_rebases, state.accounting_rebases)

        metrics = restored_metrics(loaded.state)
        self.assertEqual(metrics.snapshot().peak_equity, LIVE_EQUITY)
        # Matrix 12: later stopped-PAPER maintenance cannot re-contaminate.
        with self.assertRaises(ValueError):
            metrics.observe_stopped_paper_maintenance(
                as_of=CUR_DAY + timedelta(seconds=210), session_id=0,
                balance=PAPER_EQUITY, equity=PAPER_EQUITY,
                available_balance=PAPER_EQUITY, realized_pnl=D("0"),
                unrealized_pnl=D("0"), position=None, mark_price=None,
            )
        self.assertEqual(metrics.snapshot().peak_equity, LIVE_EQUITY)
        # Matrix 13: next LIVE START keeps authority/peak/drawdown correct.
        metrics.begin_runtime_session(3, CUR_DAY + timedelta(seconds=220))
        live = metrics.observe(
            as_of=CUR_DAY + timedelta(seconds=230), session_id=3,
            balance=LIVE_EQUITY, equity=LIVE_EQUITY,
            available_balance=LIVE_EQUITY, realized_pnl=D("0"),
            unrealized_pnl=D("0"), position=None, mark_price=None,
            accounting_authority_source=LIVE.value, source_state="RUNNING",
        )
        self.assertEqual(live.peak_equity, LIVE_EQUITY)
        self.assertEqual(live.current_drawdown_pct, D("0"))
        self.assertIs(live.accounting_authority_source, LIVE)
        after_start = _evaluate(store, TradingMode.LIVE, LIVE_EQUITY,
                                live.peak_equity, 240)
        self.assertIs(after_start.state.risk_state, RiskState.NORMAL)
        self.assertIs(after_start.lifecycle, RuntimeLifecycle.READY)
        self.assertIs(after_start.state.accounting_authority_source, LIVE)
        self.assertEqual(after_start.state.drawdown_state.high_water_mark, LIVE_EQUITY)

    def test_metrics_mirror_only_lowers_same_authority_peak(self):
        store = contaminated_store()
        contaminated = restored_metrics(store.get_snapshot().snapshot.state)
        self.assertEqual(contaminated.snapshot().peak_equity, PAPER_EQUITY)
        with self.assertRaises(ValueError):
            contaminated.apply_validated_peak_recovery(
                authority_source=PAPER, high_water_mark=LIVE_EQUITY,
                current_equity=LIVE_EQUITY, as_of=CUR_DAY + timedelta(seconds=300),
            )
        with self.assertRaises(ValueError):
            contaminated.apply_validated_peak_recovery(
                authority_source=LIVE, high_water_mark=D("20000"),
                current_equity=LIVE_EQUITY, as_of=CUR_DAY + timedelta(seconds=300),
            )
        snapshot = contaminated.apply_validated_peak_recovery(
            authority_source=LIVE, high_water_mark=LIVE_EQUITY,
            current_equity=LIVE_EQUITY, as_of=CUR_DAY + timedelta(seconds=300),
        )
        self.assertEqual(snapshot.peak_equity, LIVE_EQUITY)


class ExecutionEngineCorrectedSemanticsTests(unittest.TestCase):
    """Matrix 15: the local engine gate follows the corrected MM peak."""

    def engine(self):
        engine = ExecutionEngine(portfolio=PortfolioManager(initial_balance=float(LIVE_EQUITY)))
        engine.mode = "live"
        engine.config["max_drawdown_pct"] = 5.0
        return engine

    def test_engine_gate_blocks_on_contaminated_and_clears_on_recovered_peak(self):
        contaminated = self.engine()
        assert contaminated.apply_live_risk_equity_authority(
            initial_equity=float(LIVE_EQUITY), peak_equity=float(PAPER_EQUITY),
            authority_source=LIVE.value,
        ) is True
        assert contaminated.risk_trading_disabled is True
        assert contaminated.risk_block_reason == "MAX_DRAWDOWN"

        store = contaminated_store()
        state = store.apply_update(build(store).update).snapshot.state
        recovered = self.engine()
        assert recovered.apply_live_risk_equity_authority(
            initial_equity=float(state.drawdown_state.current_equity),
            peak_equity=float(state.drawdown_state.high_water_mark),
            authority_source=state.accounting_authority_source.value,
        ) is True
        assert recovered.current_drawdown_pct == pytest.approx(0)
        assert recovered.risk_trading_disabled is False
        assert recovered.risk_block_reason is None

    def test_engine_gate_still_blocks_legitimate_live_drawdown(self):
        engine = ExecutionEngine(portfolio=PortfolioManager(initial_balance=7.0))
        engine.mode = "live"
        engine.config["max_drawdown_pct"] = 5.0
        assert engine.apply_live_risk_equity_authority(
            initial_equity=float(LIVE_EQUITY), peak_equity=float(LIVE_EQUITY),
            authority_source=LIVE.value,
        ) is True
        assert engine.risk_trading_disabled is True
        assert engine.risk_block_reason == "MAX_DRAWDOWN"


class StoreLifecycle(Lifecycle):
    """Lifecycle double backed by the real runtime store (checkpoint OK)."""

    def __init__(self, store, checkpoint_ok=True):
        self.store = store
        self.checkpoint_ok = checkpoint_ok
        super().__init__()
        self.state = ApplicationLifecycleState.RUNNING

    @property
    def snapshot(self):
        return self.store.get_snapshot().snapshot

    @snapshot.setter
    def snapshot(self, value):
        pass

    def apply_update(self, request):
        self.apply_calls += 1
        result = self.store.apply_update(request)
        ok = result.status is StoreResultStatus.SUCCEEDED and self.checkpoint_ok
        return SimpleNamespace(coordination_result=SimpleNamespace(
            checkpoint_succeeded=ok, durability_pending=not ok,
        ))


class FakeBotManager:
    def __init__(self, metrics, account, **overrides):
        self.runtime_instance_id = RUNTIME
        self.money_management_runtime_metrics = metrics
        self.account = account
        self.overrides = overrides
        self.evidence_calls = 0

    def set_money_management_runtime_hook(self, callback):
        return True

    def live_peak_recovery_evidence(self):
        self.evidence_calls += 1
        values = {
            "botStopped": True, "executionDisabled": True,
            "emergencyClear": True, "internalPendingOrder": False,
            "paperEquity": "10000.00", "liveAccount": self.account,
            "liveAccountFailure": None,
        }
        values.update(self.overrides)
        return values


class TimelineStore:
    def __init__(self, events):
        self.events = events

    def query(self, **query):
        assert query["authority"] == "LIVE"
        assert query["event_type"] == "RUNTIME_METRICS_UPDATED"
        return SimpleNamespace(events=tuple(self.events), has_more=False, next_cursor=None)


class BoundaryRecoveryTests(unittest.TestCase):
    def boundary(self, store, account_equity=LIVE_EQUITY, checkpoint_ok=True, **overrides):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        lifecycle = StoreLifecycle(store, checkpoint_ok)
        app = app_with(lifecycle)
        metrics = restored_metrics(store.get_snapshot().snapshot.state)
        account = SimpleNamespace(
            ready=True, capital_authority="REAL_LIVE_ACCOUNT",
            open_position_state="FLAT", pending_order_state="NONE",
            equity=account_equity, evaluated_at=now - timedelta(seconds=1),
            reason_codes=(),
        )
        bot = FakeBotManager(metrics, account, **overrides)
        dispatcher = LossRuntimeUpdateDispatcher(Source([]))
        hook = MoneyManagementRuntimeHook(app, dispatcher, timestamp_source=lambda: now)
        app.state.money_management_runtime_hook = MoneyManagementRuntimeHookRegistration(
            hook, bot, now
        )
        boundary = MoneyManagementHttpBoundary(app, dispatcher, timestamp_source=lambda: now)
        epoch_ids = live_epoch_rebase_ids(store.get_snapshot().snapshot.state)
        event = lambda equity, peak: SimpleNamespace(
            observation={"accountingRebaseId": epoch_ids[0],
                         "accountingAuthoritySource": LIVE.value,
                         "authority": "LIVE"},
            metrics={"equity": str(equity), "peakEquity": str(peak)},
        )
        self.recorded = []
        boundary._timeline_recorder = SimpleNamespace(
            store=TimelineStore([
                event(LIVE_EQUITY, "10000.00"), event(LIVE_EQUITY, LIVE_EQUITY),
            ]),
            record_recovery=lambda **kwargs: self.recorded.append(kwargs),
        )
        return boundary, app, lifecycle, metrics, bot

    def test_payload_with_any_value_is_rejected_before_any_read(self):
        store = contaminated_store()
        boundary, _, lifecycle, _, bot = self.boundary(store)
        valid = {"operation": RECOVERY_OPERATION, "authorizationState": "EXPLICITLY_AUTHORIZED"}
        for payload in (
            {**valid, "highWaterMark": "7.91836966"},
            {**valid, "peakEquity": "1"},
            {"operation": "UNLOCK", "authorizationState": "EXPLICITLY_AUTHORIZED"},
            {"operation": RECOVERY_OPERATION},
            [], None,
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(MoneyManagementApiBoundaryException) as raised:
                    boundary.recover_live_peak_authority(payload)
                self.assertEqual(raised.exception.error.status_code, 422)
        self.assertEqual(bot.evidence_calls, 0)
        self.assertEqual(lifecycle.apply_calls, 0)

    def test_boundary_recovers_persists_mirrors_and_projects_allow(self):
        store = contaminated_store()
        boundary, app, lifecycle, metrics, _ = self.boundary(store)
        response = boundary.recover_live_peak_authority(
            {"operation": RECOVERY_OPERATION, "authorizationState": "EXPLICITLY_AUTHORIZED"}
        )
        self.assertTrue(response["accepted"], response)
        self.assertTrue(response["persisted"])
        self.assertEqual(response["audit"]["recoveredHighWaterMark"], "7.91836966")
        self.assertEqual(response["audit"]["contaminatedHighWaterMark"], "10000")
        state = store.get_snapshot().snapshot.state
        self.assertEqual(state.drawdown_state.high_water_mark, LIVE_EQUITY)
        self.assertIs(state.risk_state, RiskState.NORMAL)
        self.assertEqual(metrics.snapshot().peak_equity, LIVE_EQUITY)
        projection = get_money_management_governance_projection(app)
        self.assertIs(projection.projection.entry_permission, LossEntryPermission.ALLOW)
        self.assertEqual(len(self.recorded), 1)
        self.assertEqual(self.recorded[0]["previous_state"], "LOCKED")
        self.assertEqual(self.recorded[0]["current_state"], "NORMAL")
        self.assertTrue(self.recorded[0]["correlation_id"].startswith(
            "live-peak-authority-recovery:"))
        self.assertNotIn("timelineRecordFailed", response["audit"])

    def test_boundary_rejects_unsafe_evidence_without_mutation(self):
        for overrides in ({"botStopped": False}, {"internalPendingOrder": True},
                          {"liveAccount": None, "liveAccountFailure": "LIVE_ACCOUNT_READ_PREFLIGHT_BLOCKED"}):
            with self.subTest(overrides=overrides):
                store = contaminated_store()
                boundary, _, lifecycle, metrics, _ = self.boundary(store, **overrides)
                response = boundary.recover_live_peak_authority(
                    {"operation": RECOVERY_OPERATION, "authorizationState": "EXPLICITLY_AUTHORIZED"}
                )
                self.assertFalse(response["accepted"])
                self.assertEqual(lifecycle.apply_calls, 0)
                self.assertEqual(store.get_snapshot().snapshot.state.drawdown_state.high_water_mark,
                                 PAPER_EQUITY)
                self.assertEqual(metrics.snapshot().peak_equity, PAPER_EQUITY)

    def test_boundary_checkpoint_failure_does_not_mirror_metrics(self):
        store = contaminated_store()
        boundary, _, _, metrics, _ = self.boundary(store, checkpoint_ok=False)
        response = boundary.recover_live_peak_authority(
            {"operation": RECOVERY_OPERATION, "authorizationState": "EXPLICITLY_AUTHORIZED"}
        )
        self.assertFalse(response["persisted"])
        self.assertEqual(response["status"], "LIVE_PEAK_RECOVERY_PERSISTENCE_FAILED")
        self.assertEqual(metrics.snapshot().peak_equity, PAPER_EQUITY)


class RouteSecurityTests(unittest.TestCase):
    def test_route_requires_operator_session_and_csrf(self):
        from backend.api import money_management as api
        from backend.auth.dependencies import require_operator_session
        route = next(r for r in api.router.routes
                     if r.path.endswith("/recovery/live-peak-authority"))
        self.assertEqual(route.methods, {"POST"})
        dependencies = [d.call for d in route.dependant.dependencies]
        self.assertIn(require_operator_session, dependencies)
        source = Path(api.__file__).resolve().parents[1].joinpath("main.py").read_text()
        self.assertIn('"/api/money-management/recovery/live-peak-authority"', source)


if __name__ == "__main__":
    unittest.main()
