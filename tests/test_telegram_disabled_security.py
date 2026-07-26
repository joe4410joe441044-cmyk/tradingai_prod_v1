import ast
import asyncio
import importlib
import re
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    ROOT / "Bot/dev_main.py",
    ROOT / "bot_run.py",
    ROOT / "systemd/tradingbot.service",
)
BOT_TOKEN_SHAPE = re.compile(
    r"(?<![A-Za-z0-9_-])[0-9]{8,10}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])"
)


class TelegramDisabledSecurityTest(unittest.TestCase):
    def test_target_files_have_no_bot_token_shape(self):
        for path in TARGETS:
            self.assertIsNone(BOT_TOKEN_SHAPE.search(path.read_text(encoding="utf-8")))

    def test_python_modules_have_no_module_level_token_literal(self):
        for relative in ("Bot/dev_main.py", "bot_run.py"):
            tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
            forbidden_consumers = {
                "TelegramController",
                "TelegramListener",
                "TelegramNotifier",
            }
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = (
                    node.targets if isinstance(node, ast.Assign) else (node.target,)
                )
                names = {
                    target.id for target in targets if isinstance(target, ast.Name)
                }
                if names.intersection({"TOKEN", "TELEGRAM_TOKEN"}):
                    value = node.value
                    self.assertFalse(
                        isinstance(value, ast.Constant) and isinstance(value.value, str)
                    )
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                function_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
                self.assertNotIn(function_name, forbidden_consumers)

    def test_repository_unit_has_no_telegram_token_directive(self):
        unit = (ROOT / "systemd/tradingbot.service").read_text(encoding="utf-8")
        directives = [
            line.strip()
            for line in unit.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", ";"))
        ]
        self.assertFalse(
            any(
                line.startswith("Environment=") and "TELEGRAM_TOKEN" in line
                for line in directives
            )
        )
        self.assertNotIn("LoadCredential=", unit)
        self.assertNotIn("LoadCredentialEncrypted=", unit)

    def test_imports_create_no_telegram_consumer_or_network(self):
        blocked = AssertionError("network access is forbidden")
        with (
            patch.object(socket, "create_connection", side_effect=blocked) as create,
            patch.object(socket, "getaddrinfo", side_effect=blocked) as dns,
            patch.object(socket.socket, "connect", side_effect=blocked) as connect,
        ):
            sys.modules.pop("Bot.dev_main", None)
            sys.modules.pop("bot_run", None)
            dev_main = importlib.import_module("Bot.dev_main")
            bot_run = importlib.import_module("bot_run")

        self.assertFalse(dev_main.TELEGRAM_INTEGRATION_ENABLED)
        self.assertFalse(bot_run.TELEGRAM_INTEGRATION_ENABLED)
        create.assert_not_called()
        dns.assert_not_called()
        connect.assert_not_called()

    def test_disabled_entrypoints_return_without_network(self):
        blocked = AssertionError("network access is forbidden")
        with (
            patch.object(socket, "create_connection", side_effect=blocked) as create,
            patch.object(socket, "getaddrinfo", side_effect=blocked) as dns,
            patch.object(socket.socket, "connect", side_effect=blocked) as connect,
        ):
            dev_main = importlib.import_module("Bot.dev_main")
            bot_run = importlib.import_module("bot_run")
            self.assertEqual(asyncio.run(dev_main.main()), 0)
            self.assertEqual(bot_run.main(), 0)

        create.assert_not_called()
        dns.assert_not_called()
        connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
