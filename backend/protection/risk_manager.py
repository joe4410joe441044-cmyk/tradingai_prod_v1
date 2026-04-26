import time

from backend.protection.capital_protection_ai import CapitalProtectionAI
from backend.protection.drawdown_guard import DrawdownGuard
from backend.protection.kill_switch import KillSwitch
from backend.protection.loss_tracker import LossTracker


class RiskManager:

    def __init__(self, logger=None):
        self.logger = logger

        self.capital_ai = CapitalProtectionAI()
        self.drawdown_guard = DrawdownGuard()
        self.kill_switch = KillSwitch()
        self.loss_tracker = LossTracker()

        self.peak_equity = 0
        self.current_drawdown = 0

    # =====================================================
    # UPDATE（毎トレード or 毎tick）
    # =====================================================
    def update(self, equity: float, pnl: float):

        # ===== peak更新 =====
        if equity > self.peak_equity:
            self.peak_equity = equity

        # ===== drawdown =====
        if self.peak_equity > 0:
            self.current_drawdown = (equity - self.peak_equity) / self.peak_equity

        # ===== 損失トラッカー =====
        self.loss_tracker.add(pnl)

        # ===== streak =====
        streak = self.loss_tracker.streak()

        # ===== AI protection =====
        self.capital_ai.update(pnl)

        # ===== kill条件 =====
        if (
            not self.drawdown_guard.check(equity, self.peak_equity)
            or streak >= self.capital_ai.max_streak
        ):
            self.kill_switch.trigger()

            if self.logger:
                self.logger.log({
                    "type": "RISK",
                    "message": "Kill switch triggered"
                })

    # =====================================================
    # CHECK
    # =====================================================
    def allow_trade(self):
        return not self.kill_switch.active

    # =====================================================
    # UI用（超重要）
    # =====================================================
    def get_status(self):
        return {
            "drawdown": self.current_drawdown,
            "kill_switch": self.kill_switch.active,
            "loss_streak": self.loss_tracker.streak(),
            "peak_equity": self.peak_equity
        }