import ast
import threading
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.money_management.loss_application_models import (
    ApplicationLifecycleState,
    CompositionReadinessStatus,
    LifecycleOperationStatus,
)
from backend.money_management.loss_application_registration import (
    MoneyManagementApplicationRegistration,
    MoneyManagementSafeApplicationStatus,
)
from backend.money_management.loss_runtime_event_models import LossRuntimeEventType
from backend.money_management.loss_runtime_hook import (
    MoneyManagementRuntimeHook,
    MoneyManagementRuntimeHookRegistration,
    MoneyManagementRuntimeHookStatus,
    register_money_management_runtime_hook,
    unregister_money_management_runtime_hook,
)
from backend.money_management.loss_runtime_metrics_source import (
    LossRuntimeMetricsSource,
)
from backend.money_management.loss_runtime_update_dispatcher import (
    LossRuntimeDispatchResult,
    LossRuntimeDispatchStatus,
    LossRuntimeUpdateDispatcher,
)


NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


class UnusedSource(LossRuntimeMetricsSource):
    def read_metrics(self, request):
        raise AssertionError("patched dispatcher boundary should be used")


def dispatcher():
    return LossRuntimeUpdateDispatcher(UnusedSource())


def registration(state=ApplicationLifecycleState.RUNNING, ready=True):
    composition = (
        CompositionReadinessStatus.READY
        if ready
        else CompositionReadinessStatus.DISABLED
    )
    safe = MoneyManagementSafeApplicationStatus(
        ready,
        composition,
        state if ready else None,
        ready and state is ApplicationLifecycleState.RUNNING,
        "READY" if ready else None,
        False,
        False,
        False,
        2 if ready else None,
        3 if ready else None,
        None,
    )
    return MoneyManagementApplicationRegistration(
        composition,
        object() if ready else None,
        LifecycleOperationStatus.SUCCEEDED if ready else None,
        None,
        safe,
    )


def application(state=ApplicationLifecycleState.RUNNING, ready=True):
    return SimpleNamespace(
        state=SimpleNamespace(money_management=registration(state, ready))
    )


def dispatch_result(status=LossRuntimeDispatchStatus.APPLIED):
    applied = status is LossRuntimeDispatchStatus.APPLIED
    return LossRuntimeDispatchResult(
        status,
        None,
        None,
        2,
        3,
        False,
        (),
        applied,
        False,
    )


class FakeBot:
    def __init__(self):
        self.callbacks = []
        self.snapshot = {
            "available": False,
        }

    def get_runtime_metrics_snapshot(self):
        return dict(self.snapshot)

    def set_money_management_runtime_hook(self, callback):
        self.callbacks.append(callback)
        return True


class RuntimeHookTests(unittest.TestCase):
    def test_runtime_event_success_uses_dispatcher_boundary_once(self):
        app = application()
        runtime_dispatcher = dispatcher()
        hook = MoneyManagementRuntimeHook(
            app,
            runtime_dispatcher,
            timestamp_source=lambda: NOW,
        )
        with patch(
            "backend.money_management.loss_runtime_hook."
            "dispatch_money_management_runtime_update",
            return_value=dispatch_result(),
        ) as dispatch:
            result = hook.handle("TRADE_CLOSE", "session:1:close")
        self.assertEqual(result.status, MoneyManagementRuntimeHookStatus.DISPATCHED)
        dispatch.assert_called_once()
        args = dispatch.call_args.args
        self.assertIs(args[0], app)
        self.assertIs(args[1], runtime_dispatcher)
        self.assertEqual(args[3], LossRuntimeEventType.TRADE_CLOSE)

    def test_duplicate_event_dispatches_once(self):
        hook = MoneyManagementRuntimeHook(
            application(), dispatcher(), timestamp_source=lambda: NOW
        )
        with patch(
            "backend.money_management.loss_runtime_hook."
            "dispatch_money_management_runtime_update",
            return_value=dispatch_result(),
        ) as dispatch:
            first = hook.handle("POSITION_UPDATE", "same")
            second = hook.handle("POSITION_UPDATE", "same")
        self.assertEqual(first.status, MoneyManagementRuntimeHookStatus.DISPATCHED)
        self.assertEqual(second.status, MoneyManagementRuntimeHookStatus.DUPLICATE)
        self.assertEqual(dispatch.call_count, 1)

    def test_shutdown_and_lifecycle_stop_skip_dispatch(self):
        stopped_hook = MoneyManagementRuntimeHook(
            application(), dispatcher(), timestamp_source=lambda: NOW
        )
        stopped_hook.stop()
        lifecycle_hook = MoneyManagementRuntimeHook(
            application(ApplicationLifecycleState.STOPPING),
            dispatcher(),
            timestamp_source=lambda: NOW,
        )
        with patch(
            "backend.money_management.loss_runtime_hook."
            "dispatch_money_management_runtime_update"
        ) as dispatch:
            stopped = stopped_hook.handle("BALANCE_UPDATE", "stopped")
            lifecycle = lifecycle_hook.handle("BALANCE_UPDATE", "lifecycle")
        self.assertEqual(stopped.status, MoneyManagementRuntimeHookStatus.SKIPPED)
        self.assertEqual(lifecycle.status, MoneyManagementRuntimeHookStatus.SKIPPED)
        self.assertEqual(dispatch.call_count, 0)

    def test_dispatcher_failure_or_exception_never_raises(self):
        hook = MoneyManagementRuntimeHook(
            application(), dispatcher(), timestamp_source=lambda: NOW
        )
        with patch(
            "backend.money_management.loss_runtime_hook."
            "dispatch_money_management_runtime_update",
            return_value=dispatch_result(LossRuntimeDispatchStatus.FAILED),
        ):
            failed = hook.handle("TRADE_CLOSE", "failed")
        second = MoneyManagementRuntimeHook(
            application(), dispatcher(), timestamp_source=lambda: NOW
        )
        with patch(
            "backend.money_management.loss_runtime_hook."
            "dispatch_money_management_runtime_update",
            side_effect=RuntimeError("secret /private/path"),
        ):
            raised = second.handle("TRADE_CLOSE", "raised")
        self.assertEqual(failed.status, MoneyManagementRuntimeHookStatus.FAILED)
        self.assertEqual(raised.status, MoneyManagementRuntimeHookStatus.FAILED)
        self.assertNotIn("secret", repr(raised))
        self.assertNotIn("/private", repr(raised))

    def test_concurrent_duplicate_hook_is_serial_and_deadlock_free(self):
        hook = MoneyManagementRuntimeHook(
            application(), dispatcher(), timestamp_source=lambda: NOW
        )
        results = []
        with patch(
            "backend.money_management.loss_runtime_hook."
            "dispatch_money_management_runtime_update",
            return_value=dispatch_result(),
        ) as dispatch:
            threads = [
                threading.Thread(
                    target=lambda: results.append(
                        hook.handle("POSITION_UPDATE", "concurrent")
                    )
                )
                for _ in range(12)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
        self.assertEqual(dispatch.call_count, 1)
        self.assertEqual(
            sum(
                item.status is MoneyManagementRuntimeHookStatus.DISPATCHED
                for item in results
            ),
            1,
        )
        self.assertEqual(
            sum(
                item.status is MoneyManagementRuntimeHookStatus.DUPLICATE
                for item in results
            ),
            11,
        )

    def test_shutdown_waits_for_inflight_dispatch_then_blocks_new_hook(self):
        hook = MoneyManagementRuntimeHook(
            application(), dispatcher(), timestamp_source=lambda: NOW
        )
        entered = threading.Event()
        release = threading.Event()

        def delayed_dispatch(*args):
            entered.set()
            release.wait(timeout=2)
            return dispatch_result()

        with patch(
            "backend.money_management.loss_runtime_hook."
            "dispatch_money_management_runtime_update",
            side_effect=delayed_dispatch,
        ):
            dispatch_thread = threading.Thread(
                target=lambda: hook.handle("TRADE_CLOSE", "inflight")
            )
            stop_thread = threading.Thread(target=hook.stop)
            dispatch_thread.start()
            self.assertTrue(entered.wait(timeout=2))
            stop_thread.start()
            release.set()
            dispatch_thread.join(timeout=2)
            stop_thread.join(timeout=2)
            self.assertFalse(dispatch_thread.is_alive())
            self.assertFalse(stop_thread.is_alive())
            skipped = hook.handle("TRADE_CLOSE", "after-stop")
        self.assertEqual(skipped.status, MoneyManagementRuntimeHookStatus.SKIPPED)

    def test_registration_is_idempotent_and_unregisters_before_shutdown(self):
        app = application()
        bot = FakeBot()
        first = register_money_management_runtime_hook(
            app, lambda: bot, timestamp_source=lambda: NOW
        )
        second = register_money_management_runtime_hook(
            app, lambda: bot, timestamp_source=lambda: NOW
        )
        self.assertIsInstance(first, MoneyManagementRuntimeHookRegistration)
        self.assertIs(first, second)
        self.assertEqual(len(bot.callbacks), 1)
        self.assertTrue(callable(bot.callbacks[0]))
        self.assertTrue(unregister_money_management_runtime_hook(app))
        self.assertFalse(first.hook.active)
        self.assertIsNone(bot.callbacks[-1])
        self.assertIsNone(app.state.money_management_runtime_hook)

    def test_disabled_registration_does_not_create_bot(self):
        app = application(ready=False)
        factory = Mock()
        result = register_money_management_runtime_hook(
            app, factory, timestamp_source=lambda: NOW
        )
        self.assertIsNone(result)
        factory.assert_not_called()

    def test_hook_result_is_immutable_and_secret_safe(self):
        hook = MoneyManagementRuntimeHook(
            application(), dispatcher(), timestamp_source=lambda: NOW
        )
        result = hook.handle("UNKNOWN_EVENT", "secret-key")
        before = result.to_dict()
        with self.assertRaises(Exception):
            result.status = MoneyManagementRuntimeHookStatus.DISPATCHED
        self.assertEqual(result.to_dict(), before)
        self.assertNotIn("BotManager", repr(result))
        self.assertNotIn("runtime snapshot", repr(result).lower())


class BotRuntimeHookBoundaryTests(unittest.TestCase):
    @staticmethod
    def _reader_only_bot_class():
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
        names = {
            "set_money_management_runtime_hook",
            "_notify_money_management_runtime_event",
            "_money_management_runtime_event_signature",
            "_classify_money_management_runtime_event",
        }
        methods = [
            node
            for node in bot_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in names
        ]
        module = ast.Module(
            body=[
                ast.ImportFrom("copy", [ast.alias("deepcopy")], 0),
                ast.Import([ast.alias("threading")]),
                ast.Assign(
                    [ast.Name("logger", ast.Store())],
                    ast.Call(ast.Name("Mock", ast.Load()), [], []),
                ),
                ast.ClassDef("ReaderOnlyBot", [], [], methods, []),
            ],
            type_ignores=[],
        )
        namespace = {"Mock": Mock}
        exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
        return namespace["ReaderOnlyBot"]

    def test_bot_event_classification(self):
        bot_type = self._reader_only_bot_class()
        classify = bot_type._classify_money_management_runtime_event
        position = {"side": "BUY", "qty": 1}
        self.assertEqual(
            classify(
                {"balance": 100, "realizedPnl": 0, "position": position},
                {"balance": 101, "realizedPnl": 1, "position": None},
            ),
            "TRADE_CLOSE",
        )
        self.assertEqual(
            classify(
                {"balance": 100, "realizedPnl": 0, "position": position},
                {
                    "balance": 100,
                    "realizedPnl": 0,
                    "position": {**position, "sl": 90},
                },
            ),
            "POSITION_UPDATE",
        )
        self.assertEqual(
            classify(
                {"balance": 100, "realizedPnl": 0, "position": None},
                {"balance": 101, "realizedPnl": 1, "position": None},
            ),
            "BALANCE_UPDATE",
        )
        bot = bot_type()
        bot.engine = SimpleNamespace(
            balance=100,
            pnl=0,
            actual_position={"side": "BUY", "qty": 1},
        )
        captured = bot._money_management_runtime_event_signature()
        captured["position"]["qty"] = 99
        self.assertEqual(bot.engine.actual_position["qty"], 1)

    def test_bot_callback_is_shutdown_safe_and_reentrant(self):
        bot_type = self._reader_only_bot_class()
        bot = bot_type()
        bot.money_management_runtime_hook_lock = threading.RLock()
        bot.money_management_runtime_hook = None
        bot.lifecycle_state = "RUNNING"
        calls = []

        def callback(event_type, event_key):
            calls.append((event_type, event_key))
            bot.set_money_management_runtime_hook(callback)
            return "ok"

        self.assertTrue(bot.set_money_management_runtime_hook(callback))
        thread = threading.Thread(
            target=lambda: bot._notify_money_management_runtime_event(
                "TRADE_CLOSE", "event-1"
            )
        )
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(calls, [("TRADE_CLOSE", "event-1")])
        bot.lifecycle_state = "STOPPING"
        bot._notify_money_management_runtime_event("TRADE_CLOSE", "event-2")
        self.assertEqual(len(calls), 1)

    def test_source_registers_only_existing_runtime_event_boundary(self):
        root = Path(__file__).resolve().parents[1]
        bot_source = (
            root / "backend" / "bot_manager" / "bot_manager.py"
        ).read_text(encoding="utf-8")
        main_source = (root / "backend" / "main.py").read_text(encoding="utf-8")
        self.assertIn("self.engine.on_price(", bot_source)
        self.assertIn(
            "self._notify_money_management_runtime_event(",
            bot_source,
        )
        self.assertIn(
            "register_money_management_runtime_hook(",
            main_source,
        )
        self.assertIn(
            "unregister_money_management_runtime_hook(app, logger=logger)",
            main_source,
        )
        self.assertLess(
            main_source.index(
                "unregister_money_management_runtime_hook(app, logger=logger)"
            ),
            main_source.index("bot_manager = get_existing_bot_manager()"),
        )
        self.assertNotIn(
            "dispatch_money_management_execution_entry_guard",
            main_source,
        )


if __name__ == "__main__":
    unittest.main()
