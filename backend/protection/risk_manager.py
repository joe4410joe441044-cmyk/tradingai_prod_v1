# backend/protection/risk_manager.py

class KillSwitch:
    def __init__(self):
        self.active = False
        self.reason = None  # 発動理由

    def trigger(self, reason=""):
        # 多重発火防止
        if self.active:
            return

        self.active = True
        self.reason = reason

        print(f"⛔ KILL SWITCH: {reason}")


class RiskManager:

    def __init__(self, logger=None, max_drawdown_pct=10, max_loss_streak=3):
        self.logger = logger

        self.max_drawdown_pct = max_drawdown_pct
        self.max_loss_streak = max_loss_streak

        self.kill_switch = KillSwitch()

        # 🔴 初期値修正（Noneで管理）
        self.peak_equity = None
        self.current_equity = 0.0

        self.consecutive_losses = 0

    # =========================
    # 🔴 ExecutionEngine対応
    def update_equity(self, equity):
        self.current_equity = equity

        # 🔴 初回のみピーク設定
        if self.peak_equity is None:
            self.peak_equity = equity
            return

        # ピーク更新
        if equity > self.peak_equity:
            self.peak_equity = equity

        self._check_drawdown()

    # =========================
    def record_trade_result(self, pnl):

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        self._check_loss_streak()

    # =========================
    def _check_drawdown(self):

        if self.peak_equity is None:
            return

        dd = (self.peak_equity - self.current_equity) / self.peak_equity * 100

        if dd >= self.max_drawdown_pct:
            self.kill_switch.trigger("MAX DRAWDOWN")

    # =========================
    def _check_loss_streak(self):

        if self.consecutive_losses >= self.max_loss_streak:
            self.kill_switch.trigger("LOSS STREAK")

    # =========================
    def allow_trade(self):
        return not self.kill_switch.active

    # =========================
    def reset(self):
        """🔴 手動復帰（UI・API用）"""
        self.kill_switch = KillSwitch()
        self.consecutive_losses = 0
        self.peak_equity = self.current_equity

    # =========================
    def update_config(self, dd=None, streak=None):
        """🔴 UIから設定変更"""
        if dd is not None:
            self.max_drawdown_pct = dd
        if streak is not None:
            self.max_loss_streak = streak