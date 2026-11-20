import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from backend.money_management.enums import TradingMode
from backend.money_management.loss_accounting_rebase import (
    AccountingRebaseAuthorization,
    AccountingRebaseStatus,
    build_accounting_rebase_update,
)
from backend.money_management.loss_persistence_adapter import (
    LoadStatus,
    SaveStatus,
    load_loss_state,
    save_loss_state,
)
from backend.money_management.loss_persistence_models import (
    AccountingContinuityStatus,
    AccountingRebaseAuditMarker,
    AccountingRebaseAuthoritySource,
    AccountingRebaseAuthorizationState,
    AccountingRebaseReason,
    LossBaselineType,
    PeriodCode,
    PersistedAccountingRebaseRecord,
    PersistedDrawdownState,
    PersistedLossPeriodState,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
)
from backend.money_management.period_aggregation import period_for
from backend.money_management.period_models import PeriodType
from backend.money_management.loss_runtime_evaluation_bridge import (
    LossRuntimeEvaluationBridge,
    LossRuntimeEvaluationStatus,
)
from backend.money_management.loss_runtime_event_models import LossRuntimeEventType
from backend.money_management.loss_runtime_metrics_models import LossRuntimeMetricsReadRequest
from backend.money_management.loss_runtime_update_dispatcher import LossRuntimeDispatchStatus, LossRuntimeUpdateDispatcher
from backend.money_management.enums import RiskState
from backend.money_management.loss_reason_models import BlockReason, ReasonCode, RecommendedAction
from tests.test_money_management_loss_runtime_evaluation_bridge import (
    D,
    metrics,
    snapshot,
    state,
)
from tests.test_money_management_loss_runtime_update_dispatcher import Lifecycle, Source, app_with


OBSERVED = datetime(2026, 8, 22, 7, 54, 26, tzinfo=timezone.utc)
REQUESTED = OBSERVED + timedelta(seconds=10)


def authorization(**changes):
    values = dict(
        rebase_id="paper-rebase-20260822",
        account_scope="primary",
        runtime_instance_id="paper-runtime-1",
        authority_source=AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY,
        reason=AccountingRebaseReason.HISTORICAL_BOUNDARY_CONTINUITY_UNAVAILABLE,
        authorization_state=AccountingRebaseAuthorizationState.EXPLICITLY_AUTHORIZED,
    )
    values.update(changes)
    return AccountingRebaseAuthorization(**values)


def production_metrics(**changes):
    values = dict(
        at=OBSERVED,
        equity=D("100"), balance=D("100"), available_balance=D("100"),
        peak_equity=D("100"), daily_pnl=D("-2"), weekly_pnl=D("-3"),
        monthly_pnl=D("-4"), runtime_instance_id="paper-runtime-1",
    )
    values.update(changes)
    return metrics(**values)


def production_snapshot():
    old = state(datetime(2026, 8, 9, 11, 36, tzinfo=timezone.utc))
    # Monthly remains August while Daily and Weekly are historical.
    return snapshot(old, old.captured_at)


class AccountingRebaseTests(unittest.TestCase):
    def build(self, auth=None, observed=None, snap=None, **kwargs):
        return build_accounting_rebase_update(
            authorization() if auth is None else auth,
            production_metrics() if observed is None else observed,
            production_snapshot() if snap is None else snap,
            kwargs.pop("requested_at", REQUESTED),
            kwargs.pop("maximum_age", timedelta(seconds=90)),
            kwargs.pop("trading_mode", TradingMode.PAPER),
        )

    def test_production_daily_weekly_rebased_monthly_preserved(self):
        result = self.build()
        self.assertEqual(result.status, AccountingRebaseStatus.ACCEPTED)
        updated = result.update.next_state
        self.assertEqual(updated.daily_state.period_id, "2026-08-22")
        self.assertEqual(updated.weekly_state.period_id, "2026-W34")
        self.assertEqual(updated.monthly_state.to_dict(), production_snapshot().state.monthly_state.to_dict())
        self.assertEqual(updated.daily_state.baseline_type, LossBaselineType.ACCOUNTING_REBASE_BASELINE)
        self.assertEqual(updated.weekly_state.baseline_type, LossBaselineType.ACCOUNTING_REBASE_BASELINE)
        self.assertEqual(updated.daily_state.baseline_observed_at, OBSERVED)
        self.assertNotEqual(updated.daily_state.baseline_observed_at, updated.daily_state.period_start)
        self.assertNotEqual(updated.weekly_state.baseline_observed_at, updated.weekly_state.period_start)

    def test_audit_record_preserves_history_and_continuity_gap(self):
        record = self.build().record
        self.assertEqual(record.previous_period_ids, ("2026-08-09", "2026-W32"))
        self.assertEqual(record.new_period_ids, ("2026-08-22", "2026-W34"))
        self.assertEqual(record.observed_at, OBSERVED)
        self.assertEqual(record.authoritative_equity, D("100"))
        self.assertEqual(record.observed_period_pnl, (D("-2"), D("-3")))

    def test_missing_authorization_rejected(self):
        result = build_accounting_rebase_update(None, production_metrics(), production_snapshot(), REQUESTED)
        self.assertEqual(result.status, AccountingRebaseStatus.REJECTED)

    def test_stale_or_future_observation_rejected(self):
        self.assertEqual(self.build(requested_at=OBSERVED + timedelta(minutes=2)).status, AccountingRebaseStatus.REJECTED)
        self.assertEqual(self.build(requested_at=OBSERVED - timedelta(seconds=1)).status, AccountingRebaseStatus.REJECTED)

    def test_unknown_or_nonpositive_equity_rejected(self):
        self.assertEqual(self.build(observed=production_metrics(equity=None)).status, AccountingRebaseStatus.REJECTED)
        self.assertEqual(self.build(observed=production_metrics(equity=D("0"))).status, AccountingRebaseStatus.REJECTED)
        with self.assertRaises(ValueError):
            production_metrics(equity=D("-1"))

    def test_wrong_account_and_runtime_scope_rejected(self):
        self.assertEqual(self.build(auth=authorization(account_scope="other")).status, AccountingRebaseStatus.REJECTED)
        self.assertEqual(self.build(auth=authorization(runtime_instance_id="other")).status, AccountingRebaseStatus.REJECTED)

    def test_live_authority_cannot_substitute_for_paper(self):
        self.assertEqual(self.build(trading_mode=TradingMode.LIVE).status, AccountingRebaseStatus.REJECTED)

    def test_restart_restores_rebase_provenance(self):
        updated = self.build().update.next_state
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertEqual(save_loss_state(updated, path).status, SaveStatus.SAVED)
            loaded = load_loss_state(path)
        self.assertEqual(loaded.status, LoadStatus.VALID)
        self.assertEqual(loaded.state.to_dict(), updated.to_dict())

    def test_post_rebase_dispatch_uses_epoch_pnl_delta(self):
        updated = self.build().update.next_state
        rebased_snapshot = replace(
            production_snapshot(), state=updated, revision=2, sequence=2,
            updated_at=REQUESTED,
        )
        later = production_metrics(
            at=OBSERVED + timedelta(seconds=20), daily_pnl=D("-3"),
            weekly_pnl=D("-5"), monthly_pnl=D("-5"), equity=D("98"),
            balance=D("98"), available_balance=D("98"), peak_equity=D("100"),
            drawdown=D("2"),
        )
        result = LossRuntimeEvaluationBridge().evaluate(later, rebased_snapshot, "post-rebase")
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        state_after = result.build_context.next_state
        self.assertEqual(state_after.daily_state.net_realized_pnl, D("-1"))
        self.assertEqual(state_after.weekly_state.net_realized_pnl, D("-2"))
        self.assertEqual(state_after.monthly_state.net_realized_pnl, D("-5"))

    def test_rebase_does_not_relax_existing_policy_block(self):
        locked_reason = replace(
            production_snapshot().state.last_decision,
            decision_state=RiskState.LOCKED,
            recommended_action=RecommendedAction.BLOCK_EXECUTION,
            primary_reason=ReasonCode.DAILY_LOSS_BLOCK,
            block_reasons=(BlockReason.DAILY_LOSS_BLOCK,),
        )
        locked = replace(production_snapshot().state, last_decision=locked_reason)
        result = self.build(snap=snapshot(locked, locked.captured_at))
        self.assertEqual(result.update.governance_projection.value, "BLOCK_EXECUTION")

    def test_real_dispatcher_applies_after_rebase_with_revision_and_sequence(self):
        built = self.build()
        lifecycle = Lifecycle()
        lifecycle.snapshot = replace(
            production_snapshot(), state=built.update.next_state,
            revision=2, sequence=2, updated_at=REQUESTED,
        )
        later_at = OBSERVED + timedelta(seconds=20)
        cached = production_metrics()
        later = production_metrics(at=later_at, source_revision="account:9")
        dispatcher = LossRuntimeUpdateDispatcher(Source([cached, later]))
        stale = dispatcher.dispatch(
            app_with(lifecycle),
            LossRuntimeMetricsReadRequest("paper-runtime", REQUESTED, timedelta(minutes=1)),
            LossRuntimeEventType.BALANCE_UPDATE,
        )
        self.assertEqual(stale.status, LossRuntimeDispatchStatus.STALE)
        result = dispatcher.dispatch(
            app_with(lifecycle),
            LossRuntimeMetricsReadRequest("paper-runtime", later_at, timedelta(minutes=1)),
            LossRuntimeEventType.BALANCE_UPDATE,
        )
        self.assertIn(result.status, (LossRuntimeDispatchStatus.APPLIED, LossRuntimeDispatchStatus.IDEMPOTENT))
        self.assertIsNotNone(result.runtime_revision)
        self.assertIsNotNone(result.runtime_sequence)

    def test_existing_rebase_id_is_idempotent_and_creates_no_second_record(self):
        built = self.build()
        rebased_snapshot = replace(
            production_snapshot(), state=built.update.next_state,
            revision=2, sequence=2, updated_at=REQUESTED,
        )
        duplicate = self.build(snap=rebased_snapshot)
        self.assertEqual(duplicate.status, AccountingRebaseStatus.IDEMPOTENT)
        self.assertIsNone(duplicate.update)
        self.assertEqual(len(rebased_snapshot.state.accounting_rebases), 1)


PROVENANCE_AT = datetime(2026, 11, 20, 10, 11, 33, tzinfo=timezone.utc)
PROVENANCE_EQUITY = D("7.90409697")
LIVE_AUTHORITY = AccountingRebaseAuthoritySource.REAL_LIVE_ACCOUNT_EQUITY
PAPER_AUTHORITY = AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY
LIVE_RAW_MONTHLY_PNL = D("-0.4031999999999414")
CONTAMINATING_PAPER_PNL = D("0.10079999999998535")
INFLATED_MONTHLY_PNL = D("-0.50399999999992675")
INFLATED_LOSS_PERCENT = D("6.376439989449253302872877077")


def provenance_period(code, period_type, pnl=D("0")):
    current = period_for(PROVENANCE_AT, period_type)
    loss = max(D("0"), -pnl)
    return PersistedLossPeriodState(
        code, current.period_key, current.start_at, current.end_at,
        PROVENANCE_EQUITY, pnl, loss,
        loss / PROVENANCE_EQUITY * D("100"), D("0"), PROVENANCE_AT,
    )


def provenance_rebase(authority, observed_monthly, previous_month_id,
                      new_month_id=None, observed_at=PROVENANCE_AT):
    new_month_id = new_month_id or period_for(
        PROVENANCE_AT, PeriodType.MONTHLY
    ).period_key
    return PersistedAccountingRebaseRecord(
        f"provenance-{authority.value}-{observed_at.isoformat()}",
        observed_at,
        PROVENANCE_EQUITY,
        authority,
        "primary",
        "provenance-runtime",
        (PeriodCode.MONTHLY,),
        (previous_month_id,),
        (new_month_id,),
        (observed_monthly,),
        AccountingRebaseReason.HISTORICAL_BOUNDARY_CONTINUITY_UNAVAILABLE,
        AccountingContinuityStatus.UNAVAILABLE_REBASED,
        AccountingRebaseAuthorizationState.EXPLICITLY_AUTHORIZED,
        AccountingRebaseAuditMarker.DURABLE_CHECKPOINT_REQUIRED,
    )


def provenance_state(authority, rebases, monthly_pnl=D("0")):
    return replace(
        state(PROVENANCE_AT),
        daily_state=provenance_period(PeriodCode.DAILY, PeriodType.DAILY),
        weekly_state=provenance_period(PeriodCode.WEEKLY, PeriodType.WEEKLY),
        monthly_state=provenance_period(
            PeriodCode.MONTHLY, PeriodType.MONTHLY, monthly_pnl
        ),
        drawdown_state=PersistedDrawdownState(
            PROVENANCE_EQUITY, PROVENANCE_EQUITY, D("0"), D("0"),
            PROVENANCE_AT,
        ),
        accounting_rebases=tuple(rebases),
        accounting_authority_source=authority,
    )


def provenance_metrics(monthly_pnl=LIVE_RAW_MONTHLY_PNL,
                       authority="REAL_LIVE_ACCOUNT_EQUITY"):
    return metrics(
        at=PROVENANCE_AT + timedelta(minutes=1),
        equity=PROVENANCE_EQUITY,
        balance=PROVENANCE_EQUITY,
        available_balance=PROVENANCE_EQUITY,
        peak_equity=PROVENANCE_EQUITY,
        drawdown=D("0"),
        monthly_pnl=monthly_pnl,
        runtime_instance_id="provenance-runtime",
        accounting_authority_source=authority,
    )


def provenance_snapshot(state_obj):
    return snapshot(state_obj, PROVENANCE_AT)


class RebaseProvenanceIsolationTests(unittest.TestCase):
    def evaluate(self, state_obj, monthly_pnl=LIVE_RAW_MONTHLY_PNL):
        return LossRuntimeEvaluationBridge(
            trading_mode=TradingMode.LIVE
        ).evaluate(
            provenance_metrics(monthly_pnl),
            provenance_snapshot(state_obj),
            "provenance:isolation",
        )

    def test_case1_paper_observed_pnl_not_subtracted_from_live_monthly(self):
        monthly_key = period_for(PROVENANCE_AT, PeriodType.MONTHLY).period_key
        record = provenance_rebase(
            LIVE_AUTHORITY, CONTAMINATING_PAPER_PNL, monthly_key, monthly_key,
        )
        result = self.evaluate(provenance_state(LIVE_AUTHORITY, [record]))
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        monthly = result.build_context.next_state.monthly_state
        self.assertEqual(monthly.net_realized_pnl, LIVE_RAW_MONTHLY_PNL)
        self.assertNotEqual(monthly.net_realized_pnl, INFLATED_MONTHLY_PNL)

    def test_case1_paper_state_transition_to_live_uses_raw_live_monthly(self):
        paper_state = provenance_state(
            PAPER_AUTHORITY, [], monthly_pnl=CONTAMINATING_PAPER_PNL,
        )
        result = self.evaluate(paper_state)
        self.assertEqual(result.status, LossRuntimeEvaluationStatus.SUCCEEDED)
        monthly = result.build_context.next_state.monthly_state
        self.assertEqual(monthly.net_realized_pnl, LIVE_RAW_MONTHLY_PNL)
        self.assertNotEqual(monthly.net_realized_pnl, INFLATED_MONTHLY_PNL)

    def test_case2_live_to_live_epoch_baseline_is_preserved(self):
        monthly_key = period_for(PROVENANCE_AT, PeriodType.MONTHLY).period_key
        record = provenance_rebase(
            LIVE_AUTHORITY, D("-0.05"), "2026-10", monthly_key,
        )
        result = self.evaluate(provenance_state(LIVE_AUTHORITY, [record]))
        monthly = result.build_context.next_state.monthly_state
        self.assertEqual(
            monthly.net_realized_pnl,
            LIVE_RAW_MONTHLY_PNL - D("-0.05"),
        )

    def test_case3_incompatible_provenance_does_not_offset_live_pnl(self):
        monthly_key = period_for(PROVENANCE_AT, PeriodType.MONTHLY).period_key
        record = provenance_rebase(
            PAPER_AUTHORITY, CONTAMINATING_PAPER_PNL, "2026-10", monthly_key,
        )
        result = self.evaluate(provenance_state(LIVE_AUTHORITY, [record]))
        monthly = result.build_context.next_state.monthly_state
        self.assertEqual(monthly.net_realized_pnl, LIVE_RAW_MONTHLY_PNL)

    def test_case4_production_numeric_regression_and_policy(self):
        monthly_key = period_for(PROVENANCE_AT, PeriodType.MONTHLY).period_key
        record = provenance_rebase(
            LIVE_AUTHORITY, CONTAMINATING_PAPER_PNL, monthly_key, monthly_key,
        )
        result = self.evaluate(provenance_state(LIVE_AUTHORITY, [record]))
        next_state = result.build_context.next_state
        monthly = next_state.monthly_state
        self.assertEqual(monthly.net_realized_pnl, LIVE_RAW_MONTHLY_PNL)
        self.assertNotEqual(monthly.loss_percent, INFLATED_LOSS_PERCENT)
        self.assertAlmostEqual(
            float(monthly.loss_percent), 5.1011519915594026, places=9,
        )
        self.assertEqual(
            result.build_context.governance_projection,
            GovernanceProjection.BLOCK_EXECUTION,
        )
        self.assertEqual(
            next_state.last_decision.primary_reason,
            ReasonCode.MONTHLY_LOSS_BLOCK,
        )


if __name__ == "__main__":
    unittest.main()
