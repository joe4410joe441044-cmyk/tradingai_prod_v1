# Bot/control/command_handler.py

from Bot.control.bot_state import BotState


class CommandHandler:
    def __init__(self):
        # BotStateはstatic管理なのでinstance同期はやめる
        self.state = BotState()

    def handle(self, text: str) -> str:
        # 最新状態取得（static → instance）
        self.state.sync_from_class()

        BotState.last_command = text

        if text == "/start":
            BotState.running = True
            BotState.sync_to_class(BotState)
            return "✅ BOT STARTED"

        elif text == "/stop":
            BotState.running = False
            BotState.sync_to_class(BotState)
            return "⛔ BOT STOPPED"

        elif text == "/pause":
            BotState.entry_enabled = False
            BotState.sync_to_class(BotState)
            return "⏸ ENTRY PAUSED"

        elif text == "/resume":
            BotState.entry_enabled = True
            BotState.sync_to_class(BotState)
            return "▶ ENTRY RESUMED"

        elif text == "/status":
            return self.status()

        elif text == "/close_all":
            BotState.close_all_flag = True
            BotState.sync_to_class(BotState)
            return "🚨 CLOSE ALL TRIGGERED"

        else:
            return "❓ Unknown command"

    def status(self) -> str:
        self.state.sync_from_class()

        return (
            f"📊 STATUS\n"
            f"Running: {BotState.running}\n"
            f"Entry Enabled: {BotState.entry_enabled}\n"
            f"Risk: {BotState.risk}\n"
            f"Max Positions: {BotState.max_positions}\n"
            f"Last Command: {BotState.last_command}"
        )