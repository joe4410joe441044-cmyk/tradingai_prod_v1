"""Authority-transition regression tests for the MM runtime store."""
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from backend.money_management.enums import RiskState, TradingMode
from backend.money_management.loss_persistence_adapter import (
    LoadStatus,
    SaveStatus,
    load_loss_state,
    save_loss_state,
)
from backend.money_management.loss_persistence_models import (
    AccountingRebaseAuthoritySource,
    PersistedDrawdownState,
)
from backend.money_management.loss_reason_models import (
    BlockReason,
    ReasonCode,
    RecommendedAction,
)
from backend.money_management.loss_runtime_evaluation_bridge import (
    LossRuntimeEvaluationBridge,
    LossRuntimeEvaluationStatus,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
    LossLimitRecoveryRequirement,
    LossLimitRuntimeStartupDecision,
    RuntimeDecisionStatus,
    RuntimeLifecycle,
    SaveTrigger,
    StateSource,
)
from backend.money_management.loss_runtime_store import LossLimitRuntimeStateStore
from backend.money_management.loss_runtime_store_models import (
    LossLimitRuntimeSnapshot,
    LossLimitRuntimeUpdate,
    StoreFailureCode,
    StoreResultStatus,
)
from tests.test_money_management_period_rollover_authority import (
    CUR_DAY,
    _metrics_at,
    _reason,
    _state_at,
)


D = Decimal
PAPER = AccountingRebaseAuthoritySource.PAPER_RUNTIME_EQUITY
LIVE = AccountingRebaseAuthoritySource.REAL_LIVE_ACCOUNT_EQUITY


def _locked_state(authority, equity, high_water_mark):
    reason = _reason(
        CUR_DAY,
        decision_state=RiskState.LOCKED,
        recommended_action=RecommendedAction.BLOCK_EXECUTION,
        primary_reason=ReasonCode.DRAWDOWN_BLOCK,
        block_reasons=(BlockReason.DRAWDOWN_BLOCK,),
    )
    state = _state_at(CUR_DAY, starting_equity=equity, decision=reason)
    drawdown_amount = high_water_mark - equity
    return replace(
        state,
        drawdown_state=PersistedDrawdownState(
            high_water_mark,
            equity,
            drawdown_amount,
            drawdown_amount / high_water_mark * D("100"),
            CUR_DAY,
        ),
        accounting_authority_source=authority,
    )


def _snapshot(state):
    return LossLimitRuntimeSnapshot(
        RuntimeLifecycle.RESTRICTED,
        state,
        StateSource.PERSISTED_STATE,
        GovernanceProjection.BLOCK_EXECUTION,
        LossLimitRecoveryRequirement(False, (), False, False, False, "none"),
        (),
        1,
        1,
        CUR_DAY,
        CUR_DAY,
        "loaded",
    )


def _store(state):
    store = LossLimitRuntimeStateStore()
    decision = LossLimitRuntimeStartupDecision(
        RuntimeDecisionStatus.RESTRICTED,
        RuntimeLifecycle.RESTRICTED,
        state,
        StateSource.PERSISTED_STATE,
        True,
        False,
        False,
        False,
        GovernanceProjection.BLOCK_EXECUTION,
        (),
        (),
        "persisted locked state selected",
    )
    initialized = store.initialize(decision, CUR_DAY)
    assert initialized.status is StoreResultStatus.SUCCEEDED
    return store


def _evaluated_update(source_state, destination_mode, destination_equity):
    metrics_at = CUR_DAY + timedelta(seconds=30)
    authority = LIVE.value if destination_mode is TradingMode.LIVE else PAPER.value
    metrics = _metrics_at(
        metrics_at,
        equity=destination_equity,
        peak_equity=destination_equity,
        drawdown=D("0"),
        authority_source=authority,
    )
    evaluation = LossRuntimeEvaluationBridge(
        trading_mode=destination_mode
    ).evaluate(metrics, _snapshot(source_state), "authority-transition")
    assert evaluation.status is LossRuntimeEvaluationStatus.SUCCEEDED
    context = evaluation.build_context
    return LossLimitRuntimeUpdate(
        context.next_state,
        context.governance_projection,
        context.recovery_requirement,
        context.save_triggers,
        1,
        2,
        metrics_at,
        context.transition_reason,
        context.validated_accounting_rebase_id,
    )


class RuntimeStoreAuthorityTransitionTests(unittest.TestCase):
    def test_production_paper_locked_to_live_normal_is_accepted_and_persisted(self):
        source = _locked_state(PAPER, D("100"), D("100.0805801773"))
        update = _evaluated_update(source, TradingMode.LIVE, D("7.91836966"))

        self.assertIsNotNone(update.validated_accounting_rebase_id)
        self.assertIn(SaveTrigger.ACCOUNTING_REBASE, update.save_triggers)
        result = _store(source).apply_update(update)

        self.assertEqual(result.status, StoreResultStatus.SUCCEEDED)
        destination = result.snapshot.state
        self.assertIs(destination.accounting_authority_source, LIVE)
        self.assertIs(destination.risk_state, RiskState.NORMAL)
        self.assertEqual(destination.drawdown_state.high_water_mark, D("7.91836966"))
        self.assertEqual(destination.drawdown_state.current_equity, D("7.91836966"))
        self.assertEqual(destination.drawdown_state.drawdown_percent, D("0"))
        self.assertEqual(result.snapshot.lifecycle, RuntimeLifecycle.READY)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.assertEqual(save_loss_state(destination, path).status, SaveStatus.SAVED)
            loaded = load_loss_state(path)
        self.assertEqual(loaded.status, LoadStatus.VALID)
        self.assertEqual(loaded.state.daily_state.period_id, destination.daily_state.period_id)
        self.assertEqual(loaded.state.daily_state.starting_equity, D("7.91836966"))
        self.assertEqual(loaded.state.drawdown_state.high_water_mark, D("7.91836966"))
        self.assertEqual(loaded.state.drawdown_state.drawdown_percent, D("0"))
        self.assertIs(loaded.state.accounting_authority_source, LIVE)
        self.assertIs(loaded.state.risk_state, RiskState.NORMAL)

    def test_live_locked_to_paper_normal_is_accepted(self):
        source = _locked_state(LIVE, D("8"), D("10"))
        update = _evaluated_update(source, TradingMode.PAPER, D("125"))

        result = _store(source).apply_update(update)

        self.assertEqual(result.status, StoreResultStatus.SUCCEEDED)
        destination = result.snapshot.state
        self.assertIs(destination.accounting_authority_source, PAPER)
        self.assertIs(destination.risk_state, RiskState.NORMAL)
        self.assertEqual(destination.drawdown_state.high_water_mark, D("125"))
        self.assertEqual(destination.drawdown_state.drawdown_percent, D("0"))

    def test_same_authority_automatic_relaxation_remains_rejected(self):
        for authority, mode, equity in (
            (PAPER, TradingMode.PAPER, D("100")),
            (LIVE, TradingMode.LIVE, D("8")),
        ):
            with self.subTest(authority=authority):
                source = _locked_state(authority, equity, equity)
                normal = replace(
                    _state_at(CUR_DAY + timedelta(seconds=30), starting_equity=equity),
                    accounting_authority_source=authority,
                )
                update = LossLimitRuntimeUpdate(
                    normal,
                    GovernanceProjection.CONTINUE,
                    LossLimitRecoveryRequirement(
                        False, (), False, False, False, "none"
                    ),
                    (SaveTrigger.STATE_TRANSITION,),
                    1,
                    2,
                    CUR_DAY + timedelta(seconds=30),
                    "AUTOMATIC_EVALUATION",
                )

                result = _store(source).apply_update(update)

                self.assertEqual(result.status, StoreResultStatus.FAILED)
                self.assertEqual(
                    result.failure.code,
                    StoreFailureCode.LOSS_RUNTIME_STORE_INVALID_TRANSITION,
                )

    def test_authority_difference_or_unbound_rebase_id_cannot_bypass_guard(self):
        source = _locked_state(PAPER, D("100"), D("100"))
        normal = replace(
            _state_at(CUR_DAY + timedelta(seconds=30), starting_equity=D("8")),
            accounting_authority_source=LIVE,
        )
        for rebase_id, triggers in (
            (None, (SaveTrigger.STATE_TRANSITION,)),
            ("caller-forged", (SaveTrigger.ACCOUNTING_REBASE,)),
        ):
            with self.subTest(rebase_id=rebase_id):
                update = LossLimitRuntimeUpdate(
                    normal,
                    GovernanceProjection.CONTINUE,
                    LossLimitRecoveryRequirement(
                        False, (), False, False, False, "none"
                    ),
                    triggers,
                    1,
                    2,
                    CUR_DAY + timedelta(seconds=30),
                    "ARBITRARY_CROSS_AUTHORITY_UPDATE",
                    rebase_id,
                )

                result = _store(source).apply_update(update)

                self.assertEqual(result.status, StoreResultStatus.FAILED)
                self.assertEqual(
                    result.failure.code,
                    StoreFailureCode.LOSS_RUNTIME_STORE_INVALID_TRANSITION,
                )

    def test_mismatched_rebase_evidence_is_rejected_atomically(self):
        source = _locked_state(PAPER, D("100"), D("100"))
        valid = _evaluated_update(source, TradingMode.LIVE, D("8"))
        invalid = replace(valid, validated_accounting_rebase_id="wrong-rebase")
        store = _store(source)
        before = store.get_snapshot().snapshot.to_dict()

        result = store.apply_update(invalid)

        self.assertEqual(result.status, StoreResultStatus.FAILED)
        self.assertEqual(
            result.failure.code,
            StoreFailureCode.LOSS_RUNTIME_STORE_INVALID_TRANSITION,
        )
        self.assertEqual(store.get_snapshot().snapshot.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
