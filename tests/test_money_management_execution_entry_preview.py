import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.money_management import router
from backend.money_management.enums import RiskState
from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
)
from backend.money_management.loss_application_registration import (
    MoneyManagementConfigProvider,
    build_default_money_management_config,
)
from backend.money_management.loss_execution_integration import (
    APPLICATION_STATE_ATTRIBUTE as EXECUTION_ENTRY_GATE_STATE_ATTRIBUTE,
    MoneyManagementExecutionEntryGate,
    MoneyManagementExecutionEntryGateRegistration,
)
from backend.money_management.loss_governance_projection_dispatcher import (
    APPLICATION_STATE_ATTRIBUTE as PROJECTION_STATE_ATTRIBUTE,
    LossGovernanceProjectionDispatcher,
)
from backend.money_management.loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernanceBoundaryReason,
    LossGovernanceProjection,
    LossGovernanceProjectionDispatchResult,
    LossGovernanceProjectionDispatchStatus,
    LossGovernancePublicSnapshot,
)
from backend.money_management.loss_http_api import MoneyManagementHttpBoundary
from backend.money_management.loss_reason_models import DiagnosticReason
from backend.money_management.loss_runtime_hook import (
    MoneyManagementRuntimeHook,
    MoneyManagementRuntimeHookRegistration,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
)
from backend.money_management.loss_runtime_metrics_models import (
    LossRuntimeMetricsReadResult,
    LossRuntimeMetricsReadStatus,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
)
from backend.supervisor.contracts import Freshness
from backend.supervisor.failure_codes import SupervisorFailureCode
from backend.supervisor.snapshot_builder import build_supervisor_snapshot
from backend.supervisor.snapshot_sources import SnapshotFreshnessPolicy
from tests.test_money_management_loss_runtime_update_dispatcher import (
    Lifecycle as RuntimeLifecycleAdapter,
    Source,
    app_with,
    metrics,
    NOW,
)


D = Decimal


class Clock:
    def __init__(self, value=NOW + timedelta(seconds=2)):
        self.value = value

    def __call__(self):
        self.value += timedelta(microseconds=1)
        return self.value


def _bot():
    engine = SimpleNamespace(
        symbol="XRPUSDTM",
        pending_order=False,
        actual_position=None,
        place_order=Mock(),
    )
    return SimpleNamespace(
        lifecycle_state="RUNNING",
        config={"mode": "paper"},
        engine=engine,
        symbol="XRPUSDTM",
        control_authority="MANUAL",
        execution_admission_reservation=None,
        set_money_management_runtime_hook=lambda callback: True,
        set_money_management_execution_entry_guard=lambda callback: True,
    )


def _public_snapshot(permission, revision, sequence, at, block_reason=None):
    return LossGovernancePublicSnapshot(
        LossGovernanceProjection(
            permission,
            permission is LossEntryPermission.ALLOW,
            block_reason,
            RiskState.NORMAL
            if permission is LossEntryPermission.ALLOW
            else None,
            GovernanceProjection.CONTINUE
            if permission is LossEntryPermission.ALLOW
            else None,
            False,
            (),
            at,
        ),
        revision,
        sequence,
        at,
    )


class _NoPublishProjectionDispatcher(LossGovernanceProjectionDispatcher):
    def dispatch(self, app):
        at = self._timestamp_source()
        snapshot = LossGovernancePublicSnapshot(
            LossGovernanceProjection(
                LossEntryPermission.UNKNOWN,
                False,
                LossGovernanceBoundaryReason.UNKNOWN_STATE,
                None,
                None,
                False,
                (DiagnosticReason.METRIC_UNAVAILABLE,),
                at,
            ),
            None,
            None,
            at,
        )
        return LossGovernanceProjectionDispatchResult(
            LossGovernanceProjectionDispatchStatus.FAIL_CLOSED,
            snapshot,
            True,
            ("simulated projection missing",),
        )


class _MismatchedProjectionDispatcher(LossGovernanceProjectionDispatcher):
    def dispatch(self, app):
        at = self._timestamp_source()
        setattr(
            getattr(app, "state"),
            PROJECTION_STATE_ATTRIBUTE,
            _public_snapshot(LossEntryPermission.ALLOW, 2, 3, at),
        )
        expected = _public_snapshot(LossEntryPermission.ALLOW, 99, 99, at)
        return LossGovernanceProjectionDispatchResult(
            LossGovernanceProjectionDispatchStatus.PROJECTED,
            expected,
            True,
            (),
        )


def build(
    values=None,
    lifecycle=None,
    prime=False,
    projection_dispatcher=None,
    bot=None,
):
    clock = Clock()
    lifecycle = lifecycle or RuntimeLifecycleAdapter()
    app = app_with(lifecycle)
    app.state.money_management = replace(
        app.state.money_management,
        base_config_provider=MoneyManagementConfigProvider(
            build_default_money_management_config()
        ),
    )
    source = Source(
        values or [metrics(at=NOW + timedelta(seconds=1))]
    )
    dispatcher = LossRuntimeUpdateDispatcher(source)
    bot = bot or _bot()
    hook = MoneyManagementRuntimeHook(
        app,
        dispatcher,
        timestamp_source=clock,
    )
    app.state.money_management_runtime_hook = (
        MoneyManagementRuntimeHookRegistration(hook, bot, clock())
    )
    if prime:
        assert hook.refresh_authority() is True
    gate = MoneyManagementExecutionEntryGate(
        app,
        timestamp_source=clock,
        projection_dispatcher=(
            projection_dispatcher
            or LossGovernanceProjectionDispatcher(timestamp_source=clock)
        ),
    )
    app.state.__dict__[EXECUTION_ENTRY_GATE_STATE_ATTRIBUTE] = (
        MoneyManagementExecutionEntryGateRegistration(gate, bot, clock())
    )
    boundary = MoneyManagementHttpBoundary(
        app,
        dispatcher,
        timestamp_source=clock,
    )
    return SimpleNamespace(
        clock=clock,
        lifecycle=lifecycle,
        app=app,
        source=source,
        dispatcher=dispatcher,
        bot=bot,
        hook=hook,
        gate=gate,
        boundary=boundary,
    )


def build_with_mock_refresh(projection_dispatcher):
    clock = Clock()
    lifecycle = RuntimeLifecycleAdapter()
    app = app_with(lifecycle)
    app.state.money_management = replace(
        app.state.money_management,
        base_config_provider=MoneyManagementConfigProvider(
            build_default_money_management_config()
        ),
    )
    source = Source([metrics(at=NOW + timedelta(seconds=1))])
    dispatcher = LossRuntimeUpdateDispatcher(source)
    bot = _bot()
    hook = MoneyManagementRuntimeHook(
        app,
        dispatcher,
        timestamp_source=clock,
    )
    hook._last_dispatch_status = LossRuntimeDispatchStatus.APPLIED
    hook.refresh_authority = Mock(return_value=True)
    app.state.money_management_runtime_hook = (
        MoneyManagementRuntimeHookRegistration(hook, bot, clock())
    )
    gate = MoneyManagementExecutionEntryGate(
        app,
        timestamp_source=clock,
        projection_dispatcher=projection_dispatcher,
    )
    app.state.__dict__[EXECUTION_ENTRY_GATE_STATE_ATTRIBUTE] = (
        MoneyManagementExecutionEntryGateRegistration(gate, bot, clock())
    )
    boundary = MoneyManagementHttpBoundary(
        app,
        dispatcher,
        timestamp_source=clock,
    )
    return SimpleNamespace(
        app=app,
        lifecycle=lifecycle,
        bot=bot,
        hook=hook,
        boundary=boundary,
    )


class ExecutionEntryPreviewTests(unittest.TestCase):
    def test_paper_manual_flat_allow_is_non_ordering(self):
        harness = build(prime=True)
        payload = harness.boundary.preview_execution_entry().to_dict()

        self.assertTrue(payload["available"])
        self.assertEqual(payload["decision"], "ALLOW")
        self.assertTrue(payload["allowed"])
        self.assertEqual(payload["reason"], "ENTRY_ALLOWED")
        self.assertEqual(payload["reasonDetail"], "ENTRY_ALLOWED")
        self.assertEqual(payload["runtimeMode"], "PAPER")
        self.assertEqual(payload["symbol"], "XRPUSDTM")
        self.assertEqual(payload["entryAuthority"], "MANUAL")
        self.assertEqual(payload["positionState"], "FLAT")
        self.assertEqual(payload["pendingOrderState"], "NONE")
        self.assertEqual(payload["mmLifecycle"], "RUNNING")
        self.assertFalse(payload["executesOrder"])
        self.assertFalse(payload["sideEffects"]["executesOrder"])
        self.assertFalse(payload["sideEffects"]["callsExchange"])
        self.assertFalse(payload["sideEffects"]["mutatesTradingControl"])
        self.assertIsNotNone(payload["projectionRevision"])
        self.assertIsNotNone(payload["projectionSequence"])

    def test_unavailable_and_stale_metrics_never_allow(self):
        unavailable = LossRuntimeMetricsReadResult(
            LossRuntimeMetricsReadStatus.UNAVAILABLE,
            None,
            ("runtime metrics unavailable",),
        )
        fresh = metrics(at=NOW + timedelta(seconds=1))
        stale = metrics(
            revision="stale",
            at=NOW - timedelta(hours=1),
        )
        cases = {
            ("unavailable", "primed"): (
                [fresh, unavailable],
                True,
            ),
            ("unavailable", "first"): ([unavailable], False),
            ("stale", "primed"): ([fresh, stale], True),
            ("stale", "first"): ([stale], False),
        }
        for (name, phase), (values, prime) in cases.items():
            with self.subTest(name=name, phase=phase):
                harness = build(values=values, prime=prime)
                payload = (
                    harness.boundary.preview_execution_entry().to_dict()
                )
                self.assertNotEqual(payload["decision"], "ALLOW")
                self.assertFalse(payload["allowed"])
                self.assertFalse(payload["available"])
                self.assertFalse(payload["metricsFresh"])
                self.assertTrue(
                    payload["reason"]
                    in (
                        "MONEY_MANAGEMENT_UNKNOWN",
                        "BLOCK",
                        "AUTHORITATIVE_METRICS_INCOMPLETE",
                    )
                )

    def test_stopped_mm_lifecycle_fails_closed(self):
        harness = build(
            lifecycle=RuntimeLifecycleAdapter(
                state=ApplicationLifecycleState.STOPPED
            )
        )
        payload = harness.boundary.preview_execution_entry().to_dict()

        self.assertEqual(payload["decision"], "UNKNOWN")
        self.assertFalse(payload["allowed"])
        self.assertFalse(payload["available"])
        self.assertEqual(payload["mmLifecycle"], "STOPPED")

    def test_missing_projection_fails_closed(self):
        clock = Clock()
        harness = build_with_mock_refresh(
            _NoPublishProjectionDispatcher(timestamp_source=clock)
        )
        payload = harness.boundary.preview_execution_entry().to_dict()

        self.assertEqual(payload["decision"], "UNKNOWN")
        self.assertFalse(payload["allowed"])
        self.assertFalse(payload["available"])
        self.assertEqual(payload["projectionStatus"], "UNKNOWN")
        self.assertIsNone(payload["projectionRevision"])
        self.assertIsNone(payload["projectionSequence"])

    def test_projection_revision_mismatch_fails_closed(self):
        clock = Clock()
        harness = build_with_mock_refresh(
            _MismatchedProjectionDispatcher(timestamp_source=clock)
        )
        payload = harness.boundary.preview_execution_entry().to_dict()

        self.assertEqual(payload["decision"], "UNKNOWN")
        self.assertFalse(payload["allowed"])
        self.assertFalse(payload["available"])
        self.assertEqual(payload["reason"], "MONEY_MANAGEMENT_GUARD_INVALID")
        self.assertEqual(payload["reasonDetail"], "PROJECTION_REVISION_MISMATCH")

    def test_preview_performs_no_order_position_account_or_control_mutation(self):
        harness = build(prime=True)
        lifecycle_revision = harness.lifecycle.snapshot.revision
        bot_before = {
            "control_authority": harness.bot.control_authority,
            "execution_admission_reservation": (
                harness.bot.execution_admission_reservation
            ),
            "config": dict(harness.bot.config),
            "pending_order": harness.bot.engine.pending_order,
            "actual_position": harness.bot.engine.actual_position,
        }

        payload = harness.boundary.preview_execution_entry().to_dict()

        self.assertFalse(payload["executesOrder"])
        for key in (
            "executesOrder",
            "reservesOrder",
            "reservesPosition",
            "mutatesOrderState",
            "mutatesPosition",
            "mutatesAccount",
            "mutatesTradingControl",
            "mutatesSettings",
            "callsExchange",
            "startsOrStopsRuntime",
        ):
            self.assertFalse(payload["sideEffects"][key], key)
        self.assertEqual(harness.bot.control_authority, bot_before["control_authority"])
        self.assertEqual(
            harness.bot.execution_admission_reservation,
            bot_before["execution_admission_reservation"],
        )
        self.assertEqual(harness.bot.config, bot_before["config"])
        self.assertEqual(
            harness.bot.engine.pending_order, bot_before["pending_order"]
        )
        self.assertEqual(
            harness.bot.engine.actual_position,
            bot_before["actual_position"],
        )
        harness.bot.engine.place_order.assert_not_called()
        self.assertGreaterEqual(harness.lifecycle.snapshot.revision, lifecycle_revision)

    def test_period_pnl_is_preserved_and_reported(self):
        harness = build(
            values=[
                metrics(
                    at=NOW + timedelta(seconds=1),
                    daily_pnl=D("0"),
                    weekly_pnl=D("0"),
                    monthly_pnl=D("-0.00175"),
                )
            ],
            prime=True,
        )
        payload = harness.boundary.preview_execution_entry().to_dict()

        self.assertEqual(payload["decision"], "ALLOW")
        self.assertEqual(payload["dailyPnl"], "0")
        self.assertEqual(payload["weeklyPnl"], "0")
        self.assertEqual(payload["monthlyPnl"], "-0.00175")
        self.assertTrue(payload["periodPnlKnown"])
        latest = harness.dispatcher.get_last_metrics_result().metrics
        self.assertEqual(latest.monthly_pnl, D("-0.00175"))

    def test_manual_and_bot_authority_are_reported_not_changed(self):
        for authority in ("MANUAL", "BOT"):
            with self.subTest(authority=authority):
                bot = _bot()
                bot.control_authority = authority
                harness = build(prime=True, bot=bot)
                payload = (
                    harness.boundary.preview_execution_entry().to_dict()
                )
                self.assertEqual(payload["entryAuthority"], authority)
                self.assertEqual(harness.bot.control_authority, authority)

    def test_status_uses_canonical_current_authority_when_gate_registered(self):
        harness = build()
        payload = harness.boundary.get_status().to_dict()

        self.assertTrue(payload["available"])
        self.assertTrue(payload["executionEntryAllowed"])
        self.assertEqual(payload["metricsStatus"], "AVAILABLE")
        self.assertNotEqual(
            payload["safeReason"], "AUTHORITATIVE_METRICS_INCOMPLETE"
        )
        self.assertNotIn(
            "TRADING_RUNTIME_METRICS_UNAVAILABLE", payload["blockReasons"]
        )

    def test_preview_route_is_explicit_non_ordering_post(self):
        harness = build(prime=True)
        app = FastAPI()
        app.include_router(router)
        app.state.money_management_http_boundary = harness.boundary
        client = TestClient(app)

        response = client.post("/api/money-management/execution-entry-preview")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["decision"], "ALLOW")
        self.assertFalse(payload["executesOrder"])
        self.assertEqual(
            payload["scope"],
            "MONEY_MANAGEMENT_EXECUTION_ENTRY_AUTHORITY",
        )
        self.assertEqual(
            client.get(
                "/api/money-management/execution-entry-preview"
            ).status_code,
            405,
        )


class SupervisorAuthorityAlignmentTests(unittest.TestCase):
    @staticmethod
    def _snapshot(mm_generated_at, mm_available=None):
        bot = {
            "sourceEvaluatedAt": NOW,
            "accountSource": "PAPER",
            "activeSymbol": "XRPUSDTM",
            "pendingOrderState": "NONE",
            "realOrderAllowed": False,
        }
        governance = {
            "sourceEvaluatedAt": NOW,
            "mode": "PAPER",
            "execution_enabled": False,
            "emergency_stop": False,
            "emergency_state": "READY",
        }
        mm = {
            "generatedAt": mm_generated_at,
            "available": mm_available,
            "capitalEligibility": {
                "capitalAuthority": "MONEY_MANAGEMENT",
                "capitalSource": "PAPER",
                "equity": "1000",
                "availableCapital": "900",
                "riskBudget": "5",
                "remainingExposure": "100",
                "remainingPositionCapacity": "2",
                "executionEntryAllowed": True,
                "evaluatedAt": mm_generated_at,
                "authorityFresh": True,
            },
            "metrics": {
                "openExposure": "0",
                "openPositionState": "FLAT",
                "metricsGeneratedAt": mm_generated_at,
            },
        }
        health = {
            "sourceEvaluatedAt": NOW,
            "status": "ok",
            "runtimeHealthy": True,
        }
        policy = SnapshotFreshnessPolicy(
            maximumAgeBySource=tuple(
                (source, timedelta(seconds=30))
                for source in ("bot", "governance", "moneyManagement", "health")
            ),
            futureTolerance=timedelta(seconds=1),
        )
        return build_supervisor_snapshot(
            bot_status=bot,
            governance_status=governance,
            money_management_status=mm,
            health_payload=health,
            captured_at=NOW,
            freshness_policy=policy,
        )

    def test_stale_mm_source_cannot_claim_current_authority(self):
        snapshot = self._snapshot(NOW - timedelta(minutes=5))
        mm = snapshot.moneyManagement

        self.assertIs(mm.freshness, Freshness.STALE)
        self.assertIsNot(mm.authorityFresh, True)
        self.assertIsNone(mm.executionEntryAllowed)
        self.assertTrue(
            any(
                item.code is SupervisorFailureCode.INPUT_CONFLICTED
                and item.domain == "moneyManagement"
                and item.field == "authorityFresh"
                for item in snapshot.warnings
            )
        )

    def test_fresh_mm_source_keeps_current_authority(self):
        snapshot = self._snapshot(NOW, mm_available=True)
        mm = snapshot.moneyManagement

        self.assertIs(mm.freshness, Freshness.FRESH)
        self.assertIs(mm.authorityFresh, True)
        self.assertIs(mm.executionEntryAllowed, True)

    def test_unavailable_mm_status_cannot_claim_current_authority(self):
        snapshot = self._snapshot(NOW, mm_available=False)
        mm = snapshot.moneyManagement

        self.assertIsNot(mm.authorityFresh, True)
        self.assertIsNone(mm.executionEntryAllowed)


if __name__ == "__main__":
    unittest.main()
