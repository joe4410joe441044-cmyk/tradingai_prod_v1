import threading
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from backend.money_management.loss_governance_projection_dispatcher import (
    LossGovernanceProjectionDispatcher,
)
from backend.money_management.enums import RiskState
from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
)
from backend.money_management.loss_application_registration import (
    MoneyManagementConfigProvider,
    build_default_money_management_config,
)
from backend.money_management.loss_http_api import (
    MoneyManagementApiBoundaryException,
    MoneyManagementHttpBoundary,
    register_money_management_http_boundary,
    unregister_money_management_http_boundary,
)
from backend.money_management.loss_runtime_event_models import (
    LossRuntimeEventType,
)
from backend.money_management.loss_runtime_hook import (
    MoneyManagementRuntimeHook,
    MoneyManagementRuntimeHookRegistration,
)
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeDataQuality,
    LossRuntimeMetricsReadResult,
    LossRuntimeMetricsReadStatus,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
)
from backend.money_management.timeline import (
    MoneyManagementTimelineRecorder,
    MoneyManagementTimelineStore,
)
from backend.money_management.loss_reason_models import (
    BlockReason,
    HoldReason,
    LossReasonContract,
    ReasonCode,
    RecommendedAction,
    WarningReason,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
)
from tests.test_money_management_loss_governance_projection_dispatcher import (
    runtime_snapshot,
)
from tests.test_money_management_loss_runtime_update_dispatcher import (
    NOW,
    Lifecycle,
    Source,
    app_with,
    metrics,
    request,
)


class Clock:
    def __init__(self, value=NOW + timedelta(seconds=2)):
        self.value = value
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            self.value += timedelta(microseconds=1)
            return self.value


def ready_boundary(*, publish=True, runtime_metrics=None):
    clock = Clock()
    lifecycle = Lifecycle()
    dispatcher = LossRuntimeUpdateDispatcher(
        Source([runtime_metrics if runtime_metrics is not None else metrics()])
    )
    app = app_with(lifecycle)
    app.state.money_management = replace(
        app.state.money_management,
        base_config_provider=MoneyManagementConfigProvider(
            build_default_money_management_config()
        ),
    )
    applied = dispatcher.dispatch(
        app,
        request(),
        LossRuntimeEventType.BALANCE_UPDATE,
    )
    hook = MoneyManagementRuntimeHook(
        app,
        dispatcher,
        timestamp_source=clock,
    )
    hook.record_evaluation_status(applied.status)
    bot = SimpleNamespace(
        set_money_management_runtime_hook=lambda callback: True
    )
    app.state.money_management_runtime_hook = (
        MoneyManagementRuntimeHookRegistration(hook, bot, clock())
    )
    if publish:
        LossGovernanceProjectionDispatcher(
            timestamp_source=clock
        ).dispatch(app)
    boundary = MoneyManagementHttpBoundary(
        app,
        dispatcher,
        timestamp_source=clock,
    )
    return boundary, app, dispatcher, lifecycle, clock


class MoneyManagementStatusApiTests(unittest.TestCase):
    def test_status_is_typed_precise_and_matches_entry_projection(self):
        boundary, _, _, _, _ = ready_boundary()
        status = boundary.get_status()
        payload = status.to_dict()
        self.assertTrue(status.available)
        self.assertTrue(status.execution_entry_allowed)
        self.assertEqual(status.risk_state, "NORMAL")
        self.assertEqual(payload["metrics"]["equity"], "1000")
        self.assertEqual(payload["metrics"]["availableCapital"], "900")
        self.assertEqual(payload["metrics"]["exposureLimit"], "20")
        self.assertEqual(payload["metrics"]["exposureUtilization"], "0")
        self.assertEqual(payload["metrics"]["openPositionState"], "FLAT")
        self.assertIsNone(payload["metrics"]["riskUtilization"])
        self.assertIn(
            "RISK_UTILIZATION_UNAVAILABLE",
            payload["diagnosticReasons"],
        )
        self.assertEqual(payload["metrics"]["drawdownPercent"], "0")
        self.assertEqual(payload["revision"], 2)
        self.assertEqual(payload["sequence"], 2)
        self.assertTrue(payload["generatedAt"].endswith("Z"))
        with self.assertRaises(FrozenInstanceError):
            status.available = False

    def test_status_serializes_unknown_available_capital_as_null(self):
        result = LossRuntimeMetricsReadResult(
            LossRuntimeMetricsReadStatus.PARTIAL,
            metrics(available_balance=None, data_quality=LossRuntimeDataQuality.PARTIAL),
            ("runtime metrics incomplete",),
        )
        response = MoneyManagementHttpBoundary._metrics_response(result)

        self.assertIsNone(response.available_capital)
        self.assertIsNone(response.to_dict()["availableCapital"])
        self.assertIsNone(response.exposure_limit)
        self.assertIsNone(response.to_dict()["exposureLimit"])
        self.assertEqual(response.to_dict()["equity"], "1000")

    def test_runtime_metrics_project_exposure_and_open_position_state(self):
        boundary, _, _, _, _ = ready_boundary(
            runtime_metrics=metrics(
                open_exposure=Decimal("50"),
                position_count=2,
            )
        )

        payload = boundary.get_status().to_dict()

        self.assertEqual(payload["metrics"]["exposureUtilization"], "25.00")
        self.assertEqual(payload["metrics"]["openPositionState"], "OPEN")
        self.assertIsNone(payload["metrics"]["riskUtilization"])

    def test_runtime_projects_position_side_and_protective_stop_risk(self):
        boundary, _, _, _, _ = ready_boundary(
            runtime_metrics=metrics(
                open_exposure=Decimal("24"),
                position_count=1,
                position_side="LONG",
                current_risk_amount=Decimal("2"),
                pending_order_count=0,
                reserved_risk_amount=Decimal("0"),
            )
        )

        payload = boundary.get_status().to_dict()

        self.assertEqual(payload["metrics"]["openPositionState"], "LONG")
        self.assertEqual(payload["metrics"]["currentRiskAmount"], "2")
        self.assertEqual(payload["metrics"]["reservedRiskAmount"], "0")
        self.assertEqual(payload["metrics"]["riskBudgetRemaining"], "2.50")
        self.assertEqual(
            payload["metrics"]["riskUtilization"],
            "44.44444444444444444444444444",
        )

    def test_flat_runtime_projects_authoritative_zero_risk_budget(self):
        boundary, _, _, _, _ = ready_boundary(
            runtime_metrics=metrics(pending_order_count=0)
        )

        payload = boundary.get_status().to_dict()

        self.assertEqual(payload["metrics"]["riskLimitAmount"], "4.50")
        self.assertEqual(payload["metrics"]["currentRiskAmount"], "0")
        self.assertEqual(payload["metrics"]["reservedRiskAmount"], "0")
        self.assertEqual(payload["metrics"]["riskBudgetRemaining"], "4.50")
        self.assertEqual(payload["metrics"]["riskUtilization"], "0")
        self.assertNotIn(
            "RISK_UTILIZATION_UNAVAILABLE",
            payload["diagnosticReasons"],
        )

    def test_position_size_preview_is_read_only_and_uses_runtime_limits(self):
        boundary, app, _, lifecycle, _ = ready_boundary(
            runtime_metrics=metrics(pending_order_count=0)
        )
        before = lifecycle.snapshot

        payload = boundary.preview_position_size({
            "symbol": "XRPUSDTM",
            "entryPrice": "0.50",
            "stopLossPercent": "1.00",
            "effectiveCostPercent": "0.20",
            "riskPercent": "0.50",
            "quantityStep": "0.001",
            "contractMultiplier": "1",
        })

        self.assertTrue(payload["calculationAllowed"])
        self.assertEqual(payload["riskAmount"], "4.50")
        self.assertEqual(payload["finalPositionNotional"], "100")
        self.assertEqual(payload["positionQuantity"], "200")
        self.assertEqual(payload["appliedLimits"], [
            "MAXIMUM_POSITION_NOTIONAL",
        ])
        self.assertFalse(payload["orderCreated"])
        self.assertIs(lifecycle.snapshot, before)
        self.assertEqual(
            app.state.money_management.base_config_provider
            .get_config().maximum_position_notional,
            Decimal("100"),
        )

    def test_simulation_is_deterministic_and_runtime_read_only(self):
        boundary, app, _, lifecycle, _ = ready_boundary()
        before_snapshot = lifecycle.snapshot
        before_config = (
            app.state.money_management.base_config_provider.get_config()
        )
        payload = {
            "initialCapital": "1000",
            "numberOfTrades": 20,
            "winRatePercent": "55",
            "averageWinPercent": "1.50",
            "averageLossPercent": "1.00",
            "riskPerTradePercent": "0.50",
            "maximumDrawdownPercent": "5.00",
            "compoundingEnabled": True,
            "feesPercent": "0.06",
            "slippagePercent": "0.02",
            "scenario": "EXPECTED_SEQUENCE",
        }

        first = boundary.simulate(payload)
        second = boundary.simulate(payload)

        self.assertEqual(first, second)
        self.assertTrue(first["calculationAllowed"])
        self.assertEqual(
            [point["tradeNumber"] for point in first["projection"]],
            list(range(1, len(first["projection"]) + 1)),
        )
        self.assertFalse(first["runtimeMutated"])
        self.assertFalse(first["orderCreated"])
        self.assertIs(lifecycle.snapshot, before_snapshot)
        self.assertIs(
            app.state.money_management.base_config_provider.get_config(),
            before_config,
        )

    def test_simulation_validation_and_trade_limit_are_safe(self):
        boundary, _, _, _, _ = ready_boundary()
        invalid = {
            "initialCapital": "NaN",
            "numberOfTrades": 1,
            "winRatePercent": "50",
            "averageWinPercent": "1",
            "averageLossPercent": "1",
            "riskPerTradePercent": "0.50",
            "maximumDrawdownPercent": "5",
            "compoundingEnabled": True,
            "feesPercent": "0",
            "slippagePercent": "0",
            "scenario": "EXPECTED_SEQUENCE",
        }
        with self.assertRaises(MoneyManagementApiBoundaryException) as error:
            boundary.simulate(invalid)
        self.assertEqual(error.exception.error.status_code, 422)
        self.assertEqual(
            error.exception.error.code, "SIMULATION_INPUT_INVALID"
        )

        invalid["initialCapital"] = "1000"
        invalid["numberOfTrades"] = 1001
        with self.assertRaises(MoneyManagementApiBoundaryException) as error:
            boundary.simulate(invalid)
        self.assertEqual(
            error.exception.error.code,
            "SIMULATION_TRADE_LIMIT_EXCEEDED",
        )

    def test_incomplete_runtime_metrics_are_null_unknown(self):
        result = LossRuntimeMetricsReadResult(
            LossRuntimeMetricsReadStatus.PARTIAL,
            metrics(
                open_exposure=None,
                position_count=None,
                data_quality=LossRuntimeDataQuality.PARTIAL,
            ),
            ("runtime metrics incomplete",),
        )

        response = MoneyManagementHttpBoundary._metrics_response(
            result,
            Decimal("20"),
        )

        self.assertIsNone(response.exposure_utilization)
        self.assertEqual(response.open_position_state, "UNKNOWN")
        self.assertIsNone(response.risk_utilization)

    def test_status_without_base_config_is_diagnostic_and_null(self):
        _, app, dispatcher, _, clock = ready_boundary()
        app.state.money_management = replace(
            app.state.money_management,
            base_config_provider=None,
        )
        boundary = MoneyManagementHttpBoundary(
            app,
            dispatcher,
            timestamp_source=clock,
        )
        status = boundary.get_status()

        self.assertFalse(status.available)
        self.assertEqual(status.safe_reason, "INTERNAL_STATE_UNAVAILABLE")
        self.assertIn(
            "INTERNAL_STATE_UNAVAILABLE",
            status.diagnostic_reasons,
        )
        self.assertIn(
            "EXPOSURE_METRICS_INCOMPLETE",
            status.diagnostic_reasons,
        )
        self.assertIsNone(status.to_dict()["metrics"]["exposureLimit"])

    def test_status_without_projection_fails_closed_and_does_not_refresh(self):
        boundary, _, dispatcher, lifecycle, _ = ready_boundary(publish=False)
        before = lifecycle.snapshot
        source_calls = dispatcher._metrics_source.calls
        first = boundary.get_status()
        second = boundary.get_status()
        self.assertFalse(first.available)
        self.assertFalse(first.execution_entry_allowed)
        self.assertEqual(first.risk_state, "UNKNOWN")
        self.assertEqual(first.projection_status, "UNKNOWN")
        self.assertIs(lifecycle.snapshot, before)
        self.assertEqual(dispatcher._metrics_source.calls, source_calls)
        self.assertEqual(first.revision, second.revision)
        self.assertEqual(first.sequence, second.sequence)

    def test_status_never_exposes_raw_runtime_or_secret_fields(self):
        boundary, _, _, _, _ = ready_boundary()
        rendered = repr(boundary.get_status().to_dict())
        for forbidden in (
            "apiKey",
            "credential",
            "rawSnapshot",
            "positionObject",
            "authorization",
            "/home/",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_status_and_simulation_reads_do_not_create_history(self):
        _, app, dispatcher, _, clock = ready_boundary()
        with tempfile.TemporaryDirectory() as directory:
            recorder = MoneyManagementTimelineRecorder(
                MoneyManagementTimelineStore(Path(directory)),
                clock,
            )
            boundary = MoneyManagementHttpBoundary(
                app,
                dispatcher,
                timestamp_source=clock,
                timeline_recorder=recorder,
            )
            boundary.get_status()
            boundary.get_status()
            boundary.simulate({
                "initialCapital": "1000",
                "numberOfTrades": 2,
                "winRatePercent": "50",
                "averageWinPercent": "1",
                "averageLossPercent": "1",
                "riskPerTradePercent": "0.50",
                "maximumDrawdownPercent": "5",
                "compoundingEnabled": True,
                "feesPercent": "0",
                "slippagePercent": "0",
                "scenario": "ALTERNATING",
            })

            self.assertEqual(boundary.get_history().events, ())

    def test_history_query_and_configuration_event_are_read_only(self):
        _, app, dispatcher, lifecycle, clock = ready_boundary()
        with tempfile.TemporaryDirectory() as directory:
            recorder = MoneyManagementTimelineRecorder(
                MoneyManagementTimelineStore(Path(directory)),
                clock,
            )
            boundary = MoneyManagementHttpBoundary(
                app,
                dispatcher,
                timestamp_source=clock,
                timeline_recorder=recorder,
            )
            before = lifecycle.snapshot
            result = boundary.update_configuration({
                "dailyWarningPercent": "0.75",
                "expectedRevision": 1,
            })
            history = boundary.get_history(
                limit=1,
                event_type="CONFIGURATION_UPDATED",
            )

            self.assertTrue(result.applied)
            self.assertEqual(len(history.events), 1)
            self.assertIn(
                "loss.daily_warning_pct",
                history.events[0].changes,
            )
            after_update = lifecycle.snapshot
            boundary.get_history(limit=1)
            self.assertIs(lifecycle.snapshot, after_update)
            self.assertIsNotNone(before)
            with self.assertRaises(
                MoneyManagementApiBoundaryException
            ) as error:
                boundary.get_history(before="../1")
            self.assertEqual(
                error.exception.error.code,
                "HISTORY_QUERY_INVALID",
            )

    def test_status_projects_all_existing_risk_states(self):
        boundary, app, _, lifecycle, clock = ready_boundary()
        cases = (
            (
                RiskState.NORMAL,
                RecommendedAction.CONTINUE,
                (),
                (),
                (),
                GovernanceProjection.CONTINUE,
                True,
            ),
            (
                RiskState.CAUTION,
                RecommendedAction.CONTINUE,
                (WarningReason.DAILY_LOSS_WARNING,),
                (),
                (),
                GovernanceProjection.CONTINUE,
                True,
            ),
            (
                RiskState.DEFENSIVE,
                RecommendedAction.HOLD_NEW_ENTRIES,
                (
                    WarningReason.DAILY_LOSS_WARNING,
                    WarningReason.WEEKLY_LOSS_WARNING,
                ),
                (HoldReason.MULTIPLE_LOSS_WARNINGS,),
                (),
                GovernanceProjection.HOLD_NEW_ENTRIES,
                False,
            ),
            (
                RiskState.LOCKED,
                RecommendedAction.BLOCK_EXECUTION,
                (),
                (),
                (BlockReason.DAILY_LOSS_BLOCK,),
                GovernanceProjection.BLOCK_EXECUTION,
                False,
            ),
        )
        for index, (
            risk,
            action,
            warnings,
            holds,
            blocks,
            projection,
            allowed,
        ) in enumerate(cases, start=10):
            with self.subTest(risk=risk):
                last_reason = LossReasonContract(
                    "money-management-loss-reason/v1",
                    NOW,
                    risk,
                    action,
                    ReasonCode.DAILY_LOSS_BLOCK
                    if risk is RiskState.LOCKED
                    else ReasonCode.MULTIPLE_LOSS_WARNINGS
                    if risk is RiskState.DEFENSIVE
                    else ReasonCode.DAILY_LOSS_WARNING
                    if risk is RiskState.CAUTION
                    else ReasonCode.NONE,
                    warnings,
                    holds,
                    blocks,
                    (),
                    (),
                    (),
                    risk is RiskState.LOCKED,
                )
                lifecycle.snapshot = runtime_snapshot(
                    projection,
                    last_reason=last_reason,
                    revision=index,
                    sequence=index,
                )
                LossGovernanceProjectionDispatcher(
                    timestamp_source=clock
                ).dispatch(app)
                status = boundary.get_status()
                self.assertEqual(status.risk_state, risk.value)
                self.assertEqual(status.recommended_action, action.value)
                self.assertEqual(status.execution_entry_allowed, allowed)

        lifecycle.state = ApplicationLifecycleState.RECOVERY_REQUIRED
        lifecycle.snapshot = runtime_snapshot(
            GovernanceProjection.RECOVERY_REQUIRED,
            recovery=True,
            revision=20,
            sequence=20,
        )
        LossGovernanceProjectionDispatcher(
            timestamp_source=clock
        ).dispatch(app)
        recovery = boundary.get_status()
        self.assertFalse(recovery.execution_entry_allowed)
        self.assertTrue(recovery.recovery_required)
        self.assertEqual(recovery.projection_status, "RECOVERY_REQUIRED")


class MoneyManagementConfigurationApiTests(unittest.TestCase):
    def test_get_preserves_decimal_and_zero_is_not_unknown(self):
        boundary, _, _, _, _ = ready_boundary()
        payload = boundary.get_configuration().to_dict()
        self.assertEqual(payload["dailyWarningPercent"], "1.00")
        self.assertEqual(payload["maximumDrawdownPercent"], "5.00")
        self.assertEqual(payload["totalExposurePercent"], "20")
        self.assertEqual(payload["source"], "DEFAULT")

    def test_atomic_update_rechecks_revision_and_reevaluates(self):
        boundary, _, _, lifecycle, _ = ready_boundary()
        before_sequence = lifecycle.snapshot.sequence
        result = boundary.update_configuration(
            {
                "dailyWarningPercent": "0.50",
                "dailyBlockPercent": "1.25",
                "expectedRevision": 1,
            }
        )
        self.assertTrue(result.applied)
        self.assertTrue(result.reevaluated)
        self.assertEqual(
            result.configuration.daily_warning_percent,
            Decimal("0.50"),
        )
        self.assertEqual(result.configuration.revision, 2)
        self.assertEqual(lifecycle.snapshot.sequence, before_sequence + 1)
        self.assertTrue(result.status.execution_entry_allowed)

    def test_total_exposure_update_uses_same_provider_and_updates_status(self):
        boundary, app, _, _, _ = ready_boundary(
            runtime_metrics=metrics(open_exposure=Decimal("50"))
        )
        provider = app.state.money_management.base_config_provider

        result = boundary.update_configuration(
            {
                "totalExposurePercent": "25.00",
                "expectedRevision": 1,
            }
        )

        self.assertTrue(result.applied)
        self.assertIs(
            app.state.money_management.base_config_provider,
            provider,
        )
        self.assertEqual(
            provider.get_config().total_exposure_pct,
            Decimal("25.00"),
        )
        self.assertEqual(
            result.configuration.total_exposure_percent,
            Decimal("25.00"),
        )
        self.assertEqual(
            result.status.to_dict()["metrics"]["exposureLimit"],
            "25.00",
        )
        self.assertEqual(
            result.status.to_dict()["metrics"]["exposureUtilization"],
            "20.0",
        )
        self.assertEqual(
            boundary.get_configuration().to_dict()["dailyWarningPercent"],
            "1.00",
        )

    def test_position_risk_configuration_fields_update_atomically(self):
        boundary, app, _, _, _ = ready_boundary()

        result = boundary.update_configuration({
            "riskPerTradePercent": "0.40",
            "maximumPositionNotional": "80",
            "singleSymbolExposurePercent": "8",
            "expectedRevision": 1,
        })
        config = app.state.money_management.base_config_provider.get_config()

        self.assertEqual(config.risk_per_trade_pct, Decimal("0.40"))
        self.assertEqual(config.maximum_position_notional, Decimal("80"))
        self.assertEqual(config.single_symbol_exposure_pct, Decimal("8"))
        rendered = result.configuration.to_dict()
        self.assertEqual(rendered["riskPerTradePercent"], "0.40")
        self.assertEqual(rendered["maximumPositionNotional"], "80")
        self.assertEqual(rendered["singleSymbolExposurePercent"], "8")

    def test_invalid_update_never_partially_applies(self):
        boundary, _, _, _, _ = ready_boundary()
        before = boundary.get_configuration()
        cases = (
            {},
            {"unknown": "1"},
            {"enabled": "false"},
            {"dailyWarningPercent": True},
            {"dailyWarningPercent": 1},
            {"dailyWarningPercent": "NaN"},
            {"dailyWarningPercent": "Infinity"},
            {"dailyWarningPercent": "-1"},
            {"dailyWarningPercent": ""},
            {"totalExposurePercent": "NaN"},
            {"totalExposurePercent": "Infinity"},
            {"totalExposurePercent": "0"},
            {"totalExposurePercent": "5"},
            {"totalExposurePercent": "101"},
            {
                "dailyWarningPercent": "4",
                "dailyBlockPercent": "3",
            },
            {"expectedRevision": True},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises(MoneyManagementApiBoundaryException):
                    boundary.update_configuration(payload)
                self.assertEqual(boundary.get_configuration(), before)

    def test_revision_conflict_is_safe_and_non_mutating(self):
        boundary, _, _, _, _ = ready_boundary()
        before = boundary.get_configuration()
        with self.assertRaises(MoneyManagementApiBoundaryException) as raised:
            boundary.update_configuration(
                {
                    "dailyWarningPercent": "0.75",
                    "expectedRevision": 99,
                }
            )
        self.assertEqual(
            raised.exception.error.code,
            "CONFIGURATION_REVISION_CONFLICT",
        )
        self.assertEqual(boundary.get_configuration(), before)

    def test_disabled_is_fail_closed_and_can_be_reenabled(self):
        boundary, _, _, _, _ = ready_boundary()
        disabled = boundary.update_configuration(
            {"enabled": False, "expectedRevision": 1}
        )
        self.assertTrue(disabled.applied)
        self.assertFalse(disabled.status.execution_entry_allowed)
        self.assertEqual(
            disabled.status.safe_reason,
            "MONEY_MANAGEMENT_DISABLED",
        )
        enabled = boundary.update_configuration(
            {"enabled": True, "expectedRevision": 2}
        )
        self.assertTrue(enabled.applied)
        self.assertTrue(enabled.reevaluated)
        self.assertTrue(enabled.status.execution_entry_allowed)

    def test_concurrent_expected_revision_allows_one_atomic_update(self):
        boundary, _, _, _, _ = ready_boundary()
        results = []

        def update(value):
            try:
                results.append(
                    boundary.update_configuration(
                        {
                            "dailyWarningPercent": value,
                            "expectedRevision": 1,
                        }
                    )
                )
            except MoneyManagementApiBoundaryException as error:
                results.append(error.error.code)

        threads = [
            threading.Thread(target=update, args=("0.75",)),
            threading.Thread(target=update, args=("0.80",)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(
            sum(not isinstance(item, str) for item in results),
            1,
        )
        self.assertIn("CONFIGURATION_REVISION_CONFLICT", results)


class MoneyManagementRecoveryApiTests(unittest.TestCase):
    def test_normal_recovery_is_idempotent_without_revision_change(self):
        boundary, _, _, lifecycle, _ = ready_boundary()
        before = (lifecycle.snapshot.revision, lifecycle.snapshot.sequence)
        first = boundary.recover()
        second = boundary.recover()
        self.assertTrue(first.accepted)
        self.assertTrue(first.recovered)
        self.assertEqual(first.safe_reason, "ALREADY_EVALUATED")
        self.assertEqual(
            (lifecycle.snapshot.revision, lifecycle.snapshot.sequence),
            before,
        )
        self.assertEqual(first, second)

    def test_missing_projection_recovers_using_cached_metrics_only(self):
        boundary, _, dispatcher, lifecycle, _ = ready_boundary(publish=False)
        source_calls = dispatcher._metrics_source.calls
        before = lifecycle.snapshot.sequence
        result = boundary.recover()
        self.assertTrue(result.accepted)
        self.assertTrue(result.recovered)
        self.assertTrue(result.execution_entry_allowed)
        self.assertEqual(lifecycle.snapshot.sequence, before + 1)
        self.assertEqual(dispatcher._metrics_source.calls, source_calls)

    def test_partial_metrics_do_not_recover_or_mutate_runtime(self):
        partial = metrics(data_quality=LossRuntimeDataQuality.PARTIAL)
        source = Source(
            [
                LossRuntimeMetricsReadResult(
                    LossRuntimeMetricsReadStatus.PARTIAL,
                    partial,
                    ("required runtime metrics missing",),
                )
            ]
        )
        lifecycle = Lifecycle()
        dispatcher = LossRuntimeUpdateDispatcher(source)
        app = app_with(lifecycle)
        dispatcher.dispatch(
            app, request(), LossRuntimeEventType.BALANCE_UPDATE
        )
        hook = MoneyManagementRuntimeHook(app, dispatcher)
        app.state.money_management_runtime_hook = (
            MoneyManagementRuntimeHookRegistration(
                hook,
                SimpleNamespace(
                    set_money_management_runtime_hook=lambda callback: True
                ),
                NOW,
            )
        )
        boundary = MoneyManagementHttpBoundary(
            app,
            dispatcher,
            timestamp_source=lambda: NOW + timedelta(seconds=2),
        )
        before = lifecycle.snapshot
        result = boundary.recover()
        self.assertTrue(result.accepted)
        self.assertFalse(result.recovered)
        self.assertEqual(
            result.safe_reason,
            "AUTHORITATIVE_METRICS_INCOMPLETE",
        )
        self.assertIs(lifecycle.snapshot, before)

    def test_recovery_never_resets_loss_metrics(self):
        boundary, _, _, lifecycle, _ = ready_boundary(publish=False)
        before = lifecycle.snapshot.state
        boundary.recover()
        after = lifecycle.snapshot.state
        self.assertEqual(
            before.daily_state.net_realized_pnl,
            after.daily_state.net_realized_pnl,
        )
        self.assertEqual(
            before.drawdown_state.high_water_mark,
            after.drawdown_state.high_water_mark,
        )

    def test_concurrent_recovery_is_rejected_without_deadlock(self):
        boundary, _, _, _, _ = ready_boundary(publish=False)
        entered = threading.Event()
        release = threading.Event()
        original = boundary._reevaluate

        def delayed(*args):
            entered.set()
            release.wait(timeout=2)
            return original(*args)

        boundary._reevaluate = delayed
        results = []
        first = threading.Thread(
            target=lambda: results.append(boundary.recover())
        )
        first.start()
        self.assertTrue(entered.wait(timeout=2))
        try:
            boundary.recover()
        except MoneyManagementApiBoundaryException as error:
            results.append(error.error.code)
        release.set()
        first.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertIn("RECOVERY_ALREADY_RUNNING", results)


class MoneyManagementHttpRegistrationTests(unittest.TestCase):
    def test_registration_is_idempotent_and_unregistration_is_safe(self):
        boundary, app, _, _, _ = ready_boundary()
        app.state.money_management_http_boundary = None
        with tempfile.TemporaryDirectory() as directory:
            first = register_money_management_http_boundary(
                app, timeline_directory=Path(directory)
            )
            second = register_money_management_http_boundary(
                app, timeline_directory=Path(directory)
            )
            self.assertIs(first, second)
            self.assertIsNotNone(first)
            self.assertTrue(unregister_money_management_http_boundary(app))
            self.assertFalse(unregister_money_management_http_boundary(app))

    def test_main_registers_exact_routes_and_preserves_global_cors(self):
        root = Path(__file__).resolve().parents[1]
        main_source = (root / "backend" / "main.py").read_text(
            encoding="utf-8"
        )
        router_source = (
            root / "backend" / "api" / "money_management.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "register_money_management_http_boundary(app)",
            main_source,
        )
        self.assertIn(
            "unregister_money_management_http_boundary(app)",
            main_source,
        )
        self.assertIn("money_management_router", main_source)
        self.assertIn(
            'prefix="/api/money-management"',
            router_source,
        )
        for declaration in (
            '@router.get("/status")',
            '@router.get("/configuration")',
            '@router.put("/configuration")',
            '@router.post("/recovery")',
        ):
            self.assertEqual(router_source.count(declaration), 1)
        self.assertNotIn("CORSMiddleware", router_source)


if __name__ == "__main__":
    unittest.main()
