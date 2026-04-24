class LSTMModel:

    def predict(self, features):

        score = sum(features[-5:]) / 5

        if score > 0.6:
            return "BUY"
        elif score < -0.6:
            return "SELL"

        return "HOLD"