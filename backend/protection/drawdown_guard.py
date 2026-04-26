class DrawdownGuard:

    def check(self, equity, peak):
        if peak == 0:
            return True

        dd = (equity - peak) / peak
        return dd > -0.05