class FeatureEngine:

    def build(self, candles):

        return [
            c["close"] - c["open"]
            for c in candles[-20:]
        ]