class LSTMModel:

    def predict(self, features):

        # FeatureVector対応
        if hasattr(features, "numeric_vector"):
            values = features.numeric_vector
        else:
            values = features

        if not values:
            return "HOLD"

        sample = values[-5:]

        score = sum(sample) / len(sample)

        if score > 0.6:
            return "BUY"

        elif score < -0.6:
            return "SELL"

        return "HOLD"