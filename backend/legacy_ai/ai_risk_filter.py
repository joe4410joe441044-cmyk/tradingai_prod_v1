"""Archived fixed-score risk rule from the dormant development TradeCore."""

class AIRiskFilter:

    def __init__(self):
        pass

    def evaluate(self, features):
        """
        features = {
            execution_latency,
            retry_count,
            state_diff,
            volatility
        }
        """

        score = 0.0

        # execution risk
        score += min(features["execution_latency"] / 500, 0.3)

        # retry risk
        score += min(features["retry_count"] / 5, 0.2)

        # state risk
        score += min(features["state_diff"] * 0.3, 0.3)

        # market volatility
        score += min(features["volatility"] / 100, 0.2)

        return min(score, 1.0)

    def decision(self, score):
        if score < 0.5:
            return "APPROVE"
        else:
            return "BLOCK"
