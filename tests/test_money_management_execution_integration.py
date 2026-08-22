import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from Bot.engine.execution_engine import ExecutionEngine
from backend.money_management.enums import RiskState
from backend.money_management.loss_execution_guard import (
    LossExecutionEntryGuardDispatcher,
)
from backend.money_management.loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionGuardResult,
    LossExecutionOperation,
)
from backend.money_management.loss_execution_integration import (
    LossExecutionAdmissionReason,
    LossExecutionAdmissionResult,
    LossExecutionIntent,
    MoneyManagementExecutionEntryGate,
    MoneyManagementExecutionEntryGateRegistration,
    classify_loss_execution_operation,
    register_money_management_execution_entry_gate,
    unregister_money_management_execution_entry_gate,
)
from backend.money_management.loss_governance_projection_dispatcher import (
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
from backend.money_management.loss_reason_models import (
    BlockReason,
    ReasonCode,
    RecommendedAction,
)
from backend.money_management.loss_runtime_hook import (
    MoneyManagementRuntimeHook,
    MoneyManagementRuntimeHookRegistration,
)
from backend.money_management.loss_runtime_metrics_source import (
    LossRuntimeMetricsSource,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
)
from tests.test_money_management_loss_governance_projection_dispatcher import (
    Lifecycle,
    application,
    reason,
    runtime_snapshot,
)
from tests.test_money_management_loss_runtime_update_dispatcher import (
    Source as RuntimeMetricsSource,
    app_with as runtime_application,
    metrics as runtime_metrics,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
)


D = Decimal
NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


class UnusedSource(LossRuntimeMetricsSource):
    def read_metrics(self, request):
        raise AssertionError("runtime source must not be read by entry gate")


def attach_runtime_health(app, status=LossRuntimeDispatchStatus.APPLIED):
    hook = MoneyManagementRuntimeHook(
        app,
        LossRuntimeUpdateDispatcher(UnusedSource()),
        timestamp_source=lambda: NOW,
    )
    hook._last_dispatch_status = status
    app.state.money_management_runtime_hook = (
        MoneyManagementRuntimeHookRegistration(
            hook,
            SimpleNamespace(
                set_money_management_runtime_hook=lambda callback: True
            ),
            NOW,
        )
    )
    return hook


def gate(app, **kwargs):
    attach_runtime_health(app)
    return MoneyManagementExecutionEntryGate(
        app,
        timestamp_source=lambda: NOW + timedelta(seconds=1),
        projection_dispatcher=LossGovernanceProjectionDispatcher(
            timestamp_source=lambda: NOW
        ),
        **kwargs,
    )


def intent(side="BUY", **kwargs):
    values = {
        "requested_side": side,
        "requested_quantity": D("1"),
        "has_position": False,
    }
    values.update(kwargs)
    return LossExecutionIntent(**values)


def admission(
    operation=LossExecutionOperation.NEW_BUY,
    decision=LossExecutionEntryDecision.ALLOW,
    revision=2,
    sequence=3,
):
    allowed = decision is LossExecutionEntryDecision.ALLOW
    reason = {
        LossExecutionEntryDecision.ALLOW:
            LossExecutionAdmissionReason.ENTRY_ALLOWED,
        LossExecutionEntryDecision.BLOCK:
            LossExecutionAdmissionReason.MONEY_MANAGEMENT_BLOCKED,
        LossExecutionEntryDecision.RECOVERY_REQUIRED:
            LossExecutionAdmissionReason.MONEY_MANAGEMENT_RECOVERY_REQUIRED,
        LossExecutionEntryDecision.UNKNOWN:
            LossExecutionAdmissionReason.MONEY_MANAGEMENT_UNKNOWN,
    }[decision]
    return LossExecutionAdmissionResult(
        operation,
        decision,
        allowed,
        reason,
        datetime.now(timezone.utc),
        revision,
        sequence,
        accepted=allowed,
    )


def ready_engine(mode="paper"):
    portfolio = SimpleNamespace(initial_balance=1000, balance=1000)
    exchange = Mock()
    exchange.get_symbol_rules.return_value = {"multiplier": 1}
    exchange.place_order.return_value = {"success": True}
    exchange.get_positions.return_value = {
        "state": "OPEN",
        "side": "BUY",
        "qty": 1,
    }
    engine = ExecutionEngine(exchange=exchange, portfolio=portfolio)
    engine.mode = mode
    engine.symbol = "XRPUSDT"
    engine.status = "RUNNING"
    engine.price_ready = True
    engine.last_market_update = time.time()
    engine.latest_price = 100
    engine.config["dry_run"] = False
    engine.get_price = lambda: 100
    engine.update_drawdown_state = lambda *args: {
        "riskTradingDisabled": False
    }
    engine.get_result = lambda: {
        "preview": {"qty": 1, "valid": True}
    }
    engine.refresh_balance = lambda: None
    engine._live_order_allowed = lambda: True
    return engine, exchange, portfolio


class OperationClassificationTests(unittest.TestCase):
    def test_new_buy_and_sell_require_no_position(self):
        self.assertIs(
            classify_loss_execution_operation(intent("BUY")),
            LossExecutionOperation.NEW_BUY,
        )
        self.assertIs(
            classify_loss_execution_operation(intent("SELL")),
            LossExecutionOperation.NEW_SELL,
        )

    def test_reduce_close_partial_flatten_emergency_and_cancel_are_explicit(self):
        reduce_long = intent(
            "SELL",
            has_position=True,
            position_side="BUY",
            position_quantity=D("2"),
            reduce_only=True,
        )
        reduce_short = intent(
            "BUY",
            has_position=True,
            position_side="SELL",
            position_quantity=D("2"),
            reduce_only=True,
        )
        self.assertIs(
            classify_loss_execution_operation(reduce_long),
            LossExecutionOperation.REDUCE_ONLY,
        )
        self.assertIs(
            classify_loss_execution_operation(reduce_short),
            LossExecutionOperation.REDUCE_ONLY,
        )
        for operation in (
            LossExecutionOperation.POSITION_CLOSE,
            LossExecutionOperation.PARTIAL_CLOSE,
            LossExecutionOperation.FLATTEN,
            LossExecutionOperation.EMERGENCY_FLATTEN,
            LossExecutionOperation.CANCEL,
        ):
            with self.subTest(operation=operation):
                value = LossExecutionIntent(
                    None,
                    None,
                    operation
                    in (
                        LossExecutionOperation.POSITION_CLOSE,
                        LossExecutionOperation.PARTIAL_CLOSE,
                    ),
                    explicit_operation=operation,
                )
                self.assertIs(
                    classify_loss_execution_operation(value),
                    operation,
                )

    def test_unknown_or_inconsistent_intent_is_not_treated_as_entry(self):
        cases = (
            intent("BUY", has_position=True, position_side="BUY"),
            intent(
                "BUY",
                has_position=True,
                position_side="BUY",
                reduce_only=True,
            ),
            LossExecutionIntent(None, None, False),
            intent(
                "BUY",
                explicit_operation=LossExecutionOperation.NEW_SELL,
            ),
        )
        self.assertTrue(
            all(classify_loss_execution_operation(value) is None for value in cases)
        )
        with self.assertRaises(TypeError):
            LossExecutionIntent("BUY", D("1"), False, reduce_only=1)


class ApplicationEntryGateTests(unittest.TestCase):
    def test_existing_non_authoritative_hook_recovers_by_real_dispatch(self):
        app = runtime_application()
        source = RuntimeMetricsSource([runtime_metrics()])
        hook = MoneyManagementRuntimeHook(
            app,
            LossRuntimeUpdateDispatcher(source),
            timestamp_source=lambda: NOW + timedelta(seconds=2),
        )
        bot = SimpleNamespace(
            set_money_management_runtime_hook=lambda callback: True
        )
        registration = MoneyManagementRuntimeHookRegistration(hook, bot, NOW)
        app.state.money_management_runtime_hook = registration

        result = MoneyManagementExecutionEntryGate(
            app,
            timestamp_source=lambda: NOW + timedelta(seconds=2),
            projection_dispatcher=LossGovernanceProjectionDispatcher(
                timestamp_source=lambda: NOW + timedelta(seconds=2)
            ),
        ).evaluate(intent())

        self.assertIs(app.state.money_management_runtime_hook, registration)
        self.assertEqual(source.calls, 1)
        self.assertIs(
            hook.last_dispatch_status,
            LossRuntimeDispatchStatus.APPLIED,
        )
        self.assertTrue(result.allowed)
        self.assertIs(result.decision, LossExecutionEntryDecision.ALLOW)
        self.assertIsNotNone(result.revision)
        self.assertIsNotNone(result.sequence)

    def test_runtime_hook_recovery_failure_remains_unknown(self):
        app = runtime_application()
        source = RuntimeMetricsSource([RuntimeError("unavailable")])
        hook = MoneyManagementRuntimeHook(
            app,
            LossRuntimeUpdateDispatcher(source),
            timestamp_source=lambda: NOW + timedelta(seconds=2),
        )
        app.state.money_management_runtime_hook = (
            MoneyManagementRuntimeHookRegistration(
                hook,
                SimpleNamespace(
                    set_money_management_runtime_hook=lambda callback: True
                ),
                NOW,
            )
        )

        result = MoneyManagementExecutionEntryGate(
            app,
            timestamp_source=lambda: NOW + timedelta(seconds=2),
        ).evaluate(intent())

        self.assertEqual(source.calls, 1)
        self.assertIs(
            hook.last_dispatch_status,
            LossRuntimeDispatchStatus.FAILED,
        )
        self.assertFalse(result.allowed)
        self.assertIs(result.decision, LossExecutionEntryDecision.UNKNOWN)
        self.assertIs(
            result.reason,
            LossExecutionAdmissionReason.MONEY_MANAGEMENT_UNKNOWN,
        )
        self.assertIsNone(result.revision)
        self.assertIsNone(result.sequence)

    def test_allow_buy_and_sell_with_revision_sequence(self):
        app, _ = application()
        entry_gate = gate(app)
        for side, operation in (
            ("BUY", LossExecutionOperation.NEW_BUY),
            ("SELL", LossExecutionOperation.NEW_SELL),
        ):
            with self.subTest(side=side):
                result = entry_gate.evaluate(intent(side))
                self.assertTrue(result.allowed)
                self.assertIs(result.operation, operation)
                self.assertEqual((result.revision, result.sequence), (2, 3))

    def test_block_recovery_unknown_and_runtime_failure_fail_closed(self):
        locked = reason(
            RiskState.LOCKED,
            RecommendedAction.BLOCK_EXECUTION,
            ReasonCode.DAILY_LOSS_BLOCK,
            (BlockReason.DAILY_LOSS_BLOCK,),
        )
        blocked_app, _ = application(
            Lifecycle(
                snapshot=runtime_snapshot(
                    GovernanceProjection.BLOCK_EXECUTION,
                    last_reason=locked,
                )
            )
        )
        blocked = gate(blocked_app).evaluate(intent())
        self.assertFalse(blocked.allowed)
        self.assertIs(blocked.decision, LossExecutionEntryDecision.BLOCK)

        failed_app, _ = application()
        attach_runtime_health(
            failed_app, LossRuntimeDispatchStatus.UNAVAILABLE
        )
        failed = MoneyManagementExecutionEntryGate(
            failed_app,
            timestamp_source=lambda: NOW,
        ).evaluate(intent())
        self.assertFalse(failed.allowed)
        self.assertIs(failed.decision, LossExecutionEntryDecision.UNKNOWN)

        missing = SimpleNamespace(state=SimpleNamespace())
        self.assertFalse(
            MoneyManagementExecutionEntryGate(
                missing, timestamp_source=lambda: NOW
            ).evaluate(intent()).allowed
        )

    def test_non_entry_operations_bypass_projection_and_runtime_hook(self):
        app = SimpleNamespace(state=SimpleNamespace())
        entry_gate = MoneyManagementExecutionEntryGate(
            app,
            timestamp_source=lambda: NOW,
        )
        for operation in (
            LossExecutionOperation.POSITION_CLOSE,
            LossExecutionOperation.REDUCE_ONLY,
            LossExecutionOperation.PARTIAL_CLOSE,
            LossExecutionOperation.FLATTEN,
            LossExecutionOperation.EMERGENCY_FLATTEN,
            LossExecutionOperation.CANCEL,
        ):
            with self.subTest(operation=operation):
                result = entry_gate.evaluate(
                    LossExecutionIntent(
                        None,
                        None,
                        False,
                        explicit_operation=operation,
                    )
                )
                self.assertTrue(result.allowed)
                self.assertIs(
                    result.reason,
                    LossExecutionAdmissionReason.OPERATION_NOT_GUARDED,
                )
                self.assertIsNone(result.revision)

    def test_stale_projection_is_rejected(self):
        app, _ = application()
        attach_runtime_health(app)
        result = MoneyManagementExecutionEntryGate(
            app,
            timestamp_source=lambda: NOW + timedelta(minutes=3),
            projection_dispatcher=LossGovernanceProjectionDispatcher(
                timestamp_source=lambda: NOW
            ),
            maximum_projection_age=timedelta(seconds=30),
        ).evaluate(intent())
        self.assertFalse(result.allowed)
        self.assertIs(result.decision, LossExecutionEntryDecision.UNKNOWN)

    def test_malformed_exception_and_revision_race_fail_closed(self):
        class BrokenGuard(LossExecutionEntryGuardDispatcher):
            def __init__(self, value):
                super().__init__()
                self.value = value

            def dispatch(self, app, request):
                if isinstance(self.value, Exception):
                    raise self.value
                return self.value

        app, _ = application()
        attach_runtime_health(app)
        malformed = MoneyManagementExecutionEntryGate(
            app,
            guard_dispatcher=BrokenGuard({"allowed": True}),
            projection_dispatcher=LossGovernanceProjectionDispatcher(
                timestamp_source=lambda: NOW
            ),
            timestamp_source=lambda: NOW + timedelta(seconds=1),
        ).evaluate(intent())
        self.assertFalse(malformed.allowed)

        raced = MoneyManagementExecutionEntryGate(
            app,
            guard_dispatcher=BrokenGuard(
                LossExecutionGuardResult(
                    LossExecutionOperation.NEW_BUY,
                    LossExecutionEntryDecision.ALLOW,
                    True,
                    "ENTRY_ALLOWED",
                    NOW + timedelta(seconds=1),
                    9,
                    9,
                )
            ),
            projection_dispatcher=LossGovernanceProjectionDispatcher(
                timestamp_source=lambda: NOW
            ),
            timestamp_source=lambda: NOW + timedelta(seconds=1),
        ).evaluate(intent())
        self.assertFalse(raced.allowed)
        self.assertIs(
            raced.reason,
            LossExecutionAdmissionReason.MONEY_MANAGEMENT_GUARD_INVALID,
        )

        raised = MoneyManagementExecutionEntryGate(
            app,
            guard_dispatcher=BrokenGuard(RuntimeError("secret /private")),
            timestamp_source=lambda: NOW,
        ).evaluate(intent())
        self.assertFalse(raised.allowed)
        self.assertNotIn("secret", repr(raised))
        self.assertNotIn("/private", repr(raised))

    def test_registration_is_idempotent_and_unregistration_fails_closed(self):
        app, _ = application()
        bot = SimpleNamespace(
            callbacks=[],
            set_money_management_execution_entry_guard=lambda callback: (
                bot.callbacks.append(callback) or True
            ),
        )
        first = register_money_management_execution_entry_gate(
            app, lambda: bot, timestamp_source=lambda: NOW
        )
        second = register_money_management_execution_entry_gate(
            app, lambda: bot, timestamp_source=lambda: NOW
        )
        self.assertIsInstance(
            first, MoneyManagementExecutionEntryGateRegistration
        )
        self.assertIs(first, second)
        self.assertEqual(len(bot.callbacks), 1)
        self.assertTrue(unregister_money_management_execution_entry_gate(app))
        self.assertIsNone(bot.callbacks[-1])


class SharedExecutionBoundaryTests(unittest.TestCase):
    def test_live_governance_preflight_precedes_mm_and_submit(self):
        engine, exchange, _ = ready_engine("live")
        calls = []
        engine._live_order_allowed = lambda: (
            calls.append("governance") or True
        )
        engine.set_execution_entry_guard(
            lambda value: (calls.append("money-management") or admission())
        )
        exchange.place_order.side_effect = lambda **kwargs: (
            calls.append("submit") or {"success": True}
        )
        engine.try_entry({"id": "ordered", "side": "BUY"})
        self.assertEqual(
            calls,
            ["governance", "money-management", "submit"],
        )

    def test_paper_and_live_allow_submit_once(self):
        for mode in ("paper", "live"):
            with self.subTest(mode=mode):
                engine, exchange, _ = ready_engine(mode)
                engine.set_execution_entry_guard(
                    lambda value: admission()
                )
                with patch(
                    "Bot.engine.execution_engine.place_order_safe",
                    return_value={"success": True},
                ) as paper_submit:
                    result = engine.try_entry(
                        {"id": f"{mode}-1", "side": "BUY"}
                    )
                if mode == "paper":
                    paper_submit.assert_called_once()
                    exchange.place_order.assert_not_called()
                else:
                    paper_submit.assert_not_called()
                    exchange.place_order.assert_called_once()
                self.assertIsNone(result)
                self.assertEqual(
                    engine.last_money_management_guard["revision"], 2
                )

    def test_reject_never_calls_provider_or_mutates_account(self):
        for mode in ("paper", "live"):
            for decision in (
                LossExecutionEntryDecision.BLOCK,
                LossExecutionEntryDecision.RECOVERY_REQUIRED,
                LossExecutionEntryDecision.UNKNOWN,
            ):
                with self.subTest(mode=mode, decision=decision):
                    engine, exchange, portfolio = ready_engine(mode)
                    engine.set_execution_entry_guard(
                        lambda value, decision=decision: admission(
                            decision=decision,
                            revision=(
                                None
                                if decision is LossExecutionEntryDecision.UNKNOWN
                                else 2
                            ),
                            sequence=(
                                None
                                if decision is LossExecutionEntryDecision.UNKNOWN
                                else 3
                            ),
                        )
                    )
                    before_balance = portfolio.balance
                    with patch(
                        "Bot.engine.execution_engine.place_order_safe"
                    ) as paper_submit:
                        result = engine.try_entry(
                            {"id": f"{mode}-{decision.value}", "side": "BUY"}
                        )
                    self.assertFalse(result["submitted"])
                    self.assertFalse(result["providerCall"])
                    self.assertFalse(result["exchangeCall"])
                    paper_submit.assert_not_called()
                    exchange.place_order.assert_not_called()
                    self.assertIsNone(engine.actual_position)
                    self.assertEqual(portfolio.balance, before_balance)
                    self.assertFalse(engine.pending_order)

    def test_missing_exception_or_malformed_guard_fails_closed(self):
        callbacks = (
            None,
            lambda value: (_ for _ in ()).throw(
                RuntimeError("secret /private/path")
            ),
            lambda value: {"allowed": True},
        )
        for callback in callbacks:
            with self.subTest(callback=callback):
                engine, exchange, _ = ready_engine("live")
                if callback is not None:
                    engine.set_execution_entry_guard(callback)
                result = engine.try_entry({"id": "bad", "side": "BUY"})
                self.assertFalse(result["accepted"])
                exchange.place_order.assert_not_called()
                self.assertNotIn("secret", repr(result))
                self.assertNotIn("/private", repr(result))

    def test_position_change_after_allow_is_rechecked_before_submit(self):
        engine, exchange, _ = ready_engine("live")

        def changing_guard(value):
            engine.actual_position = {
                "state": "OPEN",
                "side": "SELL",
                "qty": 1,
            }
            return admission()

        engine.set_execution_entry_guard(changing_guard)
        result = engine.try_entry({"id": "race", "side": "BUY"})
        self.assertEqual(result["reason"], "EXECUTION_STATE_CHANGED")
        exchange.place_order.assert_not_called()
        self.assertFalse(engine.pending_order)

    def test_concurrent_entries_submit_only_once_without_deadlock(self):
        engine, _, _ = ready_engine("paper")
        entered = threading.Event()
        release = threading.Event()

        def delayed_guard(value):
            entered.set()
            release.wait(timeout=2)
            return admission()

        engine.set_execution_entry_guard(delayed_guard)
        results = []
        with patch(
            "Bot.engine.execution_engine.place_order_safe",
            return_value={"success": True},
        ) as submit:
            first = threading.Thread(
                target=lambda: results.append(
                    engine.try_entry({"id": "one", "side": "BUY"})
                )
            )
            second = threading.Thread(
                target=lambda: results.append(
                    engine.try_entry({"id": "two", "side": "SELL"})
                )
            )
            first.start()
            self.assertTrue(entered.wait(timeout=2))
            second.start()
            second.join(timeout=2)
            release.set()
            first.join(timeout=2)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
        self.assertEqual(submit.call_count, 1)
        self.assertTrue(
            any(
                isinstance(value, dict)
                and value.get("reason") == "EXECUTION_ENTRY_IN_PROGRESS"
                for value in results
            )
        )

    def test_main_registers_and_unregisters_gate_without_http_surface(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            "register_money_management_execution_entry_gate(",
            source,
        )
        self.assertIn(
            "unregister_money_management_execution_entry_gate(app)",
            source,
        )
        self.assertLess(
            source.index("register_money_management_runtime_hook("),
            source.index(
                "register_money_management_execution_entry_gate("
            ),
        )
        self.assertLess(
            source.index(
                "unregister_money_management_execution_entry_gate(app)"
            ),
            source.index(
                "unregister_money_management_runtime_hook(app, logger=logger)"
            ),
        )
        self.assertNotIn(
            "dispatch_money_management_execution_entry_guard(",
            source,
        )


if __name__ == "__main__":
    unittest.main()
