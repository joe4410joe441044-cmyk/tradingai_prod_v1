# Bot/control/command_handler.py

from Bot.control.bot_state import BotState


class CommandHandler:
    def __init__(self):
        # instance stateを持つ（staticと同期）
        self.state = BotState()
        self.state.sync_from_class()

    def handle(self, text: str) -> str:
        # 最新状態を反映
        self.state.sync_from_class()

        self.state.last_command = text

        if text == "/start":
            self.state.running = True
            self.state.sync_to_class()
            return "✅ BOT STARTED"

        elif text == "/stop":
            self.state.running = False
            self.state.sync_to_class()
            return "⛔ BOT STOPPED"

        elif text == "/pause":
            self.state.entry_enabled = False
            self.state.sync_to_class()
            return "⏸ ENTRY PAUSED"

        elif text == "/resume":
            self.state.entry_enabled = True
            self.state.sync_to_class()
            return "▶ ENTRY RESUMED"

        elif text == "/status":
            return self.status()

        elif text == "/close_all":
            self.state.close_all_flag = True
            self.state.sync_to_class()
            return "🚨 CLOSE ALL TRIGGERED"

        else:
            self.state.sync_to_class()
            return "❓ Unknown command"

    def status(self) -> str:
        self.state.sync_from_class()

        return (
            f"📊 STATUS\n"
            f"Running: {self.state.running}\n"
            f"Entry Enabled: {self.state.entry_enabled}\n"
            f"Risk: {self.state.risk}\n"
            f"Max Positions: {self.state.max_positions}\n"
            f"Last Command: {self.state.last_command}"
        )