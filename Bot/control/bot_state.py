# Bot/control/bot_state.py

class BotState:
    """
    🚨 重要：
    このクラスは
    - staticアクセス（BotState.running）
    - instanceアクセス（state = BotState()）
    の両方に対応するハイブリッド設計
    """

    # =========================
    # static state（旧互換）
    # =========================
    running = False
    entry_enabled = True
    close_all_flag = False
    risk = 1.0
    max_positions = 1
    last_command = None

    def __init__(self):
        """
        instanceモード用
        static状態と同期する
        """
        self.sync_from_class()

    # =========================
    # sync
    # =========================
    def sync_from_class(self):
        self.running = BotState.running
        self.entry_enabled = BotState.entry_enabled
        self.close_all_flag = BotState.close_all_flag
        self.risk = BotState.risk
        self.max_positions = BotState.max_positions
        self.last_command = BotState.last_command

    def sync_to_class(self):
        BotState.running = self.running
        BotState.entry_enabled = self.entry_enabled
        BotState.close_all_flag = self.close_all_flag
        BotState.risk = self.risk
        BotState.max_positions = self.max_positions
        BotState.last_command = self.last_command

    # =========================
    # compatibility methods
    # =========================
    def load(self, data=None):
        """
        互換用復元処理
        dataがあれば反映
        """
        if isinstance(data, dict):
            self.running = data.get("running", False)
            self.entry_enabled = data.get("entry_enabled", True)
            self.close_all_flag = data.get("close_all_flag", False)
            self.risk = data.get("risk", 1.0)
            self.max_positions = data.get("max_positions", 1)
            self.last_command = data.get("last_command", None)

            self.sync_to_class()

        return self

    def save(self):
        """
        状態をdictとして返す（将来の永続化用）
        """
        return {
            "running": self.running,
            "entry_enabled": self.entry_enabled,
            "close_all_flag": self.close_all_flag,
            "risk": self.risk,
            "max_positions": self.max_positions,
            "last_command": self.last_command,
        }

    # =========================
    # utility
    # =========================
    @classmethod
    def reset(cls):
        cls.running = False
        cls.entry_enabled = True
        cls.close_all_flag = False
        cls.risk = 1.0
        cls.max_positions = 1
        cls.last_command = None