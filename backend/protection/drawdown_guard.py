class DrawdownGuard:

    def check(self, equity, peak):

        dd = (equity - peak) / peak

        return dd > -0.05