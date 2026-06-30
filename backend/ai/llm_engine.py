from backend.utils.log_buffer import runtime_debug


class LLMEngine:

    def analyze(self, market):

        runtime_state = market.get("runtime_state")

        if runtime_state is not None:

            bias = float(
                runtime_state.directional_bias
            )

            momentum = float(
                runtime_state.momentum_score
            )

            imbalance = float(
                runtime_state.imbalance_score
            )

            runtime_debug(
                "AI runtime bias=%s momentum=%s orderflow_delta=%s "
                "imbalance=%s",
                bias,
                momentum,
                runtime_state.orderflow_delta,
                imbalance,
            )

            # ==================================
            # MICROSTRUCTURE EDGE DECISION
            # ==================================

            if (
                bias > 0.15
                and momentum >= 0.50
                and imbalance > 0
            ):
                return "BUY"

            if (
                bias < -0.15
                and momentum >= 0.50
                and imbalance > 0
            ):
                return "SELL"

            return "HOLD"

        if market.get("trend") == "up":
            return "BUY"

        volatility = market.get("volatility")

        if volatility is None:
            volatility = 0.0

        if volatility > 0.8:
            return "HOLD"

        return "SELL"
