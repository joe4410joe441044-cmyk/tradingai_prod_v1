# backend/ai/runtime_adapter.py

from backend.ai.runtime_state import RuntimeState


class RuntimeAdapter:

    def build(self, microstructure_state):

        if "aiMomentumPersistence" in microstructure_state:
            momentum_score = (
                microstructure_state["aiMomentumPersistence"]
            )
        else:
            momentum_score = (
                microstructure_state["momentumPersistence"]
            )

        return RuntimeState(
            symbol="XRPUSDT",

            directional_bias=(
                microstructure_state["buyPressure"]
                - microstructure_state["sellPressure"]
            ),

            momentum_score=(
                momentum_score
            ),

            volatility_score=(
                microstructure_state["spreadVolatility"]
            ),

            liquidity_score=(
                microstructure_state["liquidityQuality"]
            ),

            confidence_score=(
                microstructure_state["imbalanceStrength"]
            ),

            position_pressure=(
                microstructure_state["buyPressure"]
                - microstructure_state["sellPressure"]
            ),

            orderflow_delta=(
                microstructure_state["buyPressure"]
                - microstructure_state["sellPressure"]
            ),

            spread_score=(
                microstructure_state["spreadQuality"]
            ),

            imbalance_score=(
                microstructure_state["imbalanceStrength"]
            ),

            custom_features={
                "spread":
                    microstructure_state["spread"],

                "absorptionDetected":
                    microstructure_state["absorptionDetected"],

                "stagnantHeavyFlow":
                    microstructure_state["stagnantHeavyFlow"],

                "fakePressureDetected":
                    microstructure_state["fakePressureDetected"],
            }
        )
