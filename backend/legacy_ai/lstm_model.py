class LSTMModel:

    BUY_THRESHOLD = 0.6
    SELL_THRESHOLD = -0.6

    def __init__(self):

        # Observation only.  This class does not load a learned model; expose
        # the exact heuristic inputs and score used by the latest decision.
        self.latest_debug = None

    def predict(self, features):

        self.latest_debug = None

        # FeatureVector対応
        if hasattr(features, "numeric_vector"):
            values = features.numeric_vector
        else:
            values = features

        if not values:
            self.latest_debug = {
                "schemaVersion": 1,
                "implementation": "DETERMINISTIC_HEURISTIC",
                "modelLoaded": False,
                "networkInference": False,
                "inputVector": [],
                "scoreSample": [],
                "scoreFormula": "mean(last_5_features)",
                "rawScore": None,
                "normalizedScore": None,
                "thresholds": {
                    "buyGt": self.BUY_THRESHOLD,
                    "sellLt": self.SELL_THRESHOLD,
                },
                "decision": "HOLD",
                "reason": "EMPTY_FEATURE_VECTOR",
            }
            return "HOLD"

        sample = values[-5:]

        score = sum(sample) / len(sample)

        if score > self.BUY_THRESHOLD:
            decision = "BUY"
            reason = "RAW_SCORE_ABOVE_BUY_THRESHOLD"

        elif score < self.SELL_THRESHOLD:
            decision = "SELL"
            reason = "RAW_SCORE_BELOW_SELL_THRESHOLD"

        else:
            decision = "HOLD"
            reason = "RAW_SCORE_WITHIN_HOLD_BAND"

        self.latest_debug = {
            "schemaVersion": 1,
            "implementation": "DETERMINISTIC_HEURISTIC",
            "modelLoaded": False,
            "networkInference": False,
            "inputVector": list(values),
            "scoreSample": list(sample),
            "scoreFormula": "mean(last_5_features)",
            "rawScore": score,
            "normalizedScore": None,
            "thresholds": {
                "buyGt": self.BUY_THRESHOLD,
                "sellLt": self.SELL_THRESHOLD,
            },
            "decision": decision,
            "reason": reason,
        }

        return decision
