# Bot/control/bot_state.py

class BotState:
    def __init__(self):
        self.running = False
        self.entry_enabled = True
        self.close_all_flag = False
        self.risk = 1.0
        self.max_positions = 1
        self.last_command = None

    def load(self):
        """
        旧互換用（状態復元未実装）
        """
        return self

    def save(self):
        """
        将来用（まだ未実装）
        """
        pass