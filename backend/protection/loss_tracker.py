class LossTracker:

    def __init__(self):
        self.losses = []
        self.max_size = 200

    def add(self, pnl):
        self.losses.append(pnl)

        if len(self.losses) > self.max_size:
            self.losses = self.losses[-self.max_size:]

    def streak(self):
        count = 0

        for p in reversed(self.losses):
            if p < 0:
                count += 1
            else:
                break

        return count