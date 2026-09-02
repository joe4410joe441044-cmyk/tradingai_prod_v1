import unittest
from dataclasses import replace
from datetime import timedelta

from backend.money_management.loss_application_registration import (
    MoneyManagementConfigProvider,
    build_default_money_management_config,
)
from backend.money_management.loss_governance_projection_models import (
    LossEntryPermission,
)
from backend.money_management.loss_governance_projection_dispatcher import (
    get_money_management_governance_projection,
)
from backend.money_management.loss_http_api import MoneyManagementHttpBoundary
from backend.money_management.loss_runtime_hook import (
    MoneyManagementRuntimeHook,
    MoneyManagementRuntimeHookRegistration,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
)
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


class Bot:
    def set_money_management_runtime_hook(self, callback):
        return True


class DispatchFailCloseRegressionTests(unittest.TestCase):
    def test_period_mismatch_invalidates_previous_allow_and_recovery_is_not_already_evaluated(self):
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
        dispatcher = LossRuntimeUpdateDispatcher(
            Source([production_metrics(equity=None)])
        )
        hook = MoneyManagementRuntimeHook(
            app, dispatcher, timestamp_source=lambda: now
        )
        app.state.money_management_runtime_hook = (
            MoneyManagementRuntimeHookRegistration(hook, Bot(), now)
        )

        result = hook.handle("BALANCE_UPDATE", "production-period-mismatch")

        self.assertEqual(
            result.runtime_dispatch_status,
            LossRuntimeDispatchStatus.RECOVERY_REQUIRED,
        )
        self.assertEqual(
            hook.last_dispatch_safe_reasons,
            ("period rollover requires authoritative starting equity",),
        )
        public = get_money_management_governance_projection(app)
        self.assertEqual(
            public.projection.entry_permission,
            LossEntryPermission.RECOVERY_REQUIRED,
        )
        self.assertFalse(public.projection.new_entry_allowed)
        self.assertTrue(public.projection.recovery_required)
        self.assertEqual(public.revision, 1)
        self.assertEqual(public.sequence, 1)

        boundary = MoneyManagementHttpBoundary(
            app, dispatcher, timestamp_source=lambda: now
        )
        status = boundary.get_status()
        self.assertFalse(status.execution_entry_allowed)
        self.assertTrue(status.recovery_required)
        self.assertEqual(
            status.safe_reason,
            "period rollover requires authoritative starting equity",
        )
        recovery = boundary.recover()
        self.assertNotEqual(recovery.safe_reason, "ALREADY_EVALUATED")
        self.assertFalse(recovery.execution_entry_allowed)
        after_recovery = boundary.get_status()
        self.assertFalse(after_recovery.execution_entry_allowed)
        self.assertTrue(after_recovery.recovery_required)
        self.assertEqual(
            after_recovery.safe_reason,
            "period rollover requires authoritative starting equity",
        )

    def test_failed_and_unavailable_latest_evaluations_invalidate_allow(self):
        for dispatch_status in (
            LossRuntimeDispatchStatus.FAILED,
            LossRuntimeDispatchStatus.UNAVAILABLE,
            LossRuntimeDispatchStatus.REJECTED,
        ):
            with self.subTest(dispatch_status=dispatch_status):
                lifecycle = Lifecycle()
                app = app_with(lifecycle)
                hook = MoneyManagementRuntimeHook(
                    app,
                    LossRuntimeUpdateDispatcher(Source([production_metrics()])),
                    timestamp_source=lambda: OBSERVED,
                )
                from backend.money_management.loss_runtime_update_dispatcher import (
                    LossRuntimeDispatchResult,
                )
                result = LossRuntimeDispatchResult(
                    dispatch_status, None, None, 1, 1, False,
                    ("latest authority unavailable",), False, False,
                )
                hook._record_dispatch_result(result)
                public = get_money_management_governance_projection(app)
                self.assertEqual(
                    public.projection.entry_permission,
                    LossEntryPermission.UNKNOWN,
                )
                self.assertFalse(public.projection.new_entry_allowed)

    def test_restart_snapshot_allow_is_not_authoritative_before_new_evaluation(self):
        lifecycle = Lifecycle()
        app = app_with(lifecycle)
        app.state.money_management = replace(
            app.state.money_management,
            base_config_provider=MoneyManagementConfigProvider(
                build_default_money_management_config()
            ),
        )
        dispatcher = LossRuntimeUpdateDispatcher(Source([production_metrics()]))
        hook = MoneyManagementRuntimeHook(
            app, dispatcher, timestamp_source=lambda: OBSERVED
        )
        app.state.money_management_runtime_hook = (
            MoneyManagementRuntimeHookRegistration(hook, Bot(), OBSERVED)
        )
        status = MoneyManagementHttpBoundary(
            app, dispatcher, timestamp_source=lambda: OBSERVED
        ).get_status()
        self.assertFalse(status.execution_entry_allowed)
        self.assertFalse(status.recovery_required)
        self.assertEqual(
            status.safe_reason,
            "AUTHORITATIVE_EVALUATION_NOT_ESTABLISHED",
        )


if __name__ == "__main__":
    unittest.main()
