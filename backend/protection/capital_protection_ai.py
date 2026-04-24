class CapitalProtectionAI:

    def __init__(self):

        self.killed = False
        self.loss_streak = 0
        self.max_streak = 5
        self.max_drawdown = -0.05

    # =====================================================
    # UPDATE
    # =====================================================
    def update(self, pnl: float):

        if pnl < 0:
            self.loss_streak += 1
        else:
            self.loss_streak = 0

        if self.loss_streak >= self.max_streak:
            self.killed = True

    # =====================================================
    # CHECK
    # =====================================================
    def allow_trade(self):

        return not self.killed