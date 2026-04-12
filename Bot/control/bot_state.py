# Bot/control/bot_state.py

class BotState:
    """
    シンプル単一状態管理（static統一）
    """

    # =========================
    # STATE
    # =========================
    running = False
    entry_enabled = True
    close_all_flag = False
    risk = 1.0
    max_positions = 1
    last_command = None

    # =========================
    # COMPAT LAYER
    # =========================
    def load(self, data=None):
        """
        dict or None 両対応
        """
        if isinstance(data, dict):
            BotState.running = data.get("running", False)
            BotState.entry_enabled = data.get("entry_enabled", True)
            BotState.close_all_flag = data.get("close_all_flag", False)
            BotState.risk = data.get("risk", 1.0)
            BotState.max_positions = data.get("max_positions", 1)
            BotState.last_command = data.get("last_command", None)

        return self

    def save(self):
        return {
            "running": BotState.running,
            "entry_enabled": BotState.entry_enabled,
            "close_all_flag": BotState.close_all_flag,
            "risk": BotState.risk,
            "max_positions": BotState.max_positions,
            "last_command": BotState.last_command,
        }

    @classmethod
    def reset(cls):
        cls.running = False
        cls.entry_enabled = True
        cls.close_all_flag = False
        cls.risk = 1.0
        cls.max_positions = 1
        cls.last_command = None