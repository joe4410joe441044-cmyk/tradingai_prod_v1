# Historical snapshot moved from .bak_hold_runtime; not used by production.
class LLMEngine:

    def analyze(self, market):

        runtime_state = market.get("runtime_state")

        if runtime_state is not None:

            print(
                "AI RUNTIME:",
                runtime_state.directional_bias,
                runtime_state.momentum_score,
                runtime_state.orderflow_delta,
                runtime_state.imbalance_score,
            )

            # RuntimeState配線確認フェーズ
            return "HOLD"

        if market.get("trend") == "up":
            return "BUY"

        volatility = market.get("volatility")

        if volatility is None:
            volatility = 0.0

        if volatility > 0.8:
            return "HOLD"

        return "SELL"
