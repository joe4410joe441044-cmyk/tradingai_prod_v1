from backend.ai.feature_vector import FeatureVector
from backend.ai.runtime_state import RuntimeState


class FeatureEngine:

    def build(self, input_data):

        # ==================================
        # Candle Compatibility Mode
        # ==================================
        if isinstance(input_data, list):

            numeric_vector = [
                c["close"] - c["open"]
                for c in input_data[-20:]
            ]

            feature_map = {
                f"candle_{i}": value
                for i, value in enumerate(numeric_vector)
            }

            return FeatureVector(
                numeric_vector=numeric_vector,
                feature_map=feature_map
            )

        # ==================================
        # RuntimeState Mode
        # ==================================
        if isinstance(input_data, RuntimeState):

            numeric_vector = [
                input_data.directional_bias,
                input_data.momentum_score,
                input_data.volatility_score,
                input_data.liquidity_score,
                input_data.confidence_score,
                input_data.position_pressure,
                input_data.orderflow_delta,
                input_data.spread_score,
                input_data.imbalance_score,
            ]

            feature_map = {
                "directional_bias": input_data.directional_bias,
                "momentum_score": input_data.momentum_score,
                "volatility_score": input_data.volatility_score,
                "liquidity_score": input_data.liquidity_score,
                "confidence_score": input_data.confidence_score,
                "position_pressure": input_data.position_pressure,
                "orderflow_delta": input_data.orderflow_delta,
                "spread_score": input_data.spread_score,
                "imbalance_score": input_data.imbalance_score,
            }

            feature_map.update(
                input_data.custom_features
            )

            return FeatureVector(
                numeric_vector=numeric_vector,
                feature_map=feature_map
            )

        raise ValueError(
            f"Unsupported input type: {type(input_data)}"
        )