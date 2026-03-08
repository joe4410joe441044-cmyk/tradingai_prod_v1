class SafeModeController:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def validate_order(self):
        if self.enabled:
            raise Exception("SAFE_MODE ENABLED: 注文は実行されません")
