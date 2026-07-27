import asyncio
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("fastapi"), "FastAPI not installed")
class FastApiMoneyManagementLifecycleTests(unittest.TestCase):
    def setUp(self):
        import backend.main as main

        self.main = main
        if hasattr(main.app.state, "money_management"):
            delattr(main.app.state, "money_management")

    def test_startup_handler_invokes_registration_once(self):
        registration = object()
        with patch.object(
            self.main,
            "startup_money_management_application",
            return_value=registration,
        ) as startup:
            asyncio.run(self.main.startup_event())
        startup.assert_called_once_with(self.main.app, logger=self.main.logger)

    def test_shutdown_preserves_bot_then_money_management_order(self):
        events = []
        bot = Mock()
        bot.shutdown.side_effect = lambda: events.append("bot") or {
            "success": True,
            "completed": True,
            "durablePersisted": True,
            "stateUnknown": False,
        }
        with patch.object(
            self.main, "get_existing_bot_manager", return_value=bot
        ), patch.object(
            self.main,
            "shutdown_money_management_application",
            side_effect=lambda app, logger: events.append("money"),
        ) as shutdown, patch.object(self.main.logger, "info"):
            asyncio.run(self.main.shutdown_event())
        self.assertEqual(events, ["bot", "money"])
        shutdown.assert_called_once_with(self.main.app, logger=self.main.logger)

    def test_shutdown_runs_when_bot_is_unavailable(self):
        with patch.object(
            self.main, "get_existing_bot_manager", return_value=None
        ), patch.object(
            self.main, "shutdown_money_management_application"
        ) as shutdown:
            asyncio.run(self.main.shutdown_event())
        shutdown.assert_called_once_with(self.main.app, logger=self.main.logger)

    def test_default_disabled_cycle_registers_safe_state(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(
            self.main, "get_existing_bot_manager", return_value=None
        ):
            asyncio.run(self.main.startup_event())
            registration = self.main.app.state.money_management
            self.assertFalse(registration.safe_status.runtime_available)
            self.assertFalse(registration.safe_status.new_entry_allowed)
            asyncio.run(self.main.shutdown_event())
        self.assertIsNotNone(registration)

    def test_handlers_remain_registered_on_existing_app(self):
        self.assertIn(self.main.startup_event, self.main.app.router.on_startup)
        self.assertIn(self.main.shutdown_event, self.main.app.router.on_shutdown)


class FastApiSourceIntegrationTests(unittest.TestCase):
    def test_existing_handlers_contain_money_management_boundaries(self):
        source = (
            Path(__file__).resolve().parents[1] / "backend" / "main.py"
        ).read_text(encoding="utf-8")
        self.assertIn('@app.on_event("startup")', source)
        self.assertIn('@app.on_event("shutdown")', source)
        self.assertIn("startup_money_management_application(app, logger=logger)", source)
        self.assertIn("shutdown_money_management_application(app, logger=logger)", source)
        self.assertLess(
            source.index("result = bot_manager.shutdown()"),
            source.rindex("shutdown_money_management_application(app, logger=logger)"),
        )


if __name__ == "__main__":
    unittest.main()
