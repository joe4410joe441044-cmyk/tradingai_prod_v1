class LossTracker:

    def __init__(self):
        self.losses = []

    def add(self, pnl):
        self.losses.append(pnl)

    def streak(self):
        count = 0

        for p in reversed(self.losses):
            if p < 0:
                count += 1
            else:
                break

        return count