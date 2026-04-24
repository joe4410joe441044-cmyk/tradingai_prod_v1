class LLMEngine:

    def analyze(self, market):

        if market.get("trend") == "up":
            return "BUY"

        if market.get("volatility", 0) > 0.8:
            return "HOLD"

        return "SELL"