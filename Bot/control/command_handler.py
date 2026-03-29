# Bot/control/command_handler.py

from Bot.control.bot_state import BotState

class CommandHandler:

    def handle(self, text: str) -> str:
        BotState.last_command = text

        if text == "/start":
            BotState.running = True
            return "✅ BOT STARTED"
        elif text == "/stop":
            BotState.running = False
            return "⛔ BOT STOPPED"
        elif text == "/pause":
            BotState.entry_enabled = False
            return "⏸ ENTRY PAUSED"
        elif text == "/resume":
            BotState.entry_enabled = True
            return "▶ ENTRY RESUMED"
        elif text == "/status":
            return self.status()
        elif text == "/close_all":
            BotState.close_all_flag = True
            return "🚨 CLOSE ALL TRIGGERED"
        else:
            return "❓ Unknown command"

    def status(self) -> str:
        return (
            f"📊 STATUS\n"
            f"Running: {BotState.running}\n"
            f"Entry Enabled: {BotState.entry_enabled}\n"
            f"Risk: {BotState.risk}\n"
            f"Max Positions: {BotState.max_positions}\n"
            f"Last Command: {BotState.last_command}"
        )