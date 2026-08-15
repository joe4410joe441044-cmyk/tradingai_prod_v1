# Historical snapshot moved from .bak_market_data_indent.
from backend.legacy_ai.feature_engine import FeatureEngine
from backend.legacy_ai.trade_brain import TradeBrain
from backend.legacy_ai.lstm_model import LSTMModel
from backend.legacy_ai.llm_engine import LLMEngine


class AIPipeline:

    def __init__(self):
        self.feature_engine = FeatureEngine()
        self.brain = TradeBrain(
            lstm_model=LSTMModel(),
            llm_engine=LLMEngine()
        )

    def decide(self, market):

        runtime_state = market.get("runtime_state")

        # ==================================
        # RuntimeState Mode
        # ==================================
        if runtime_state is not None:

            features = self.feature_engine.build(
                runtime_state
            )

        else:

            candles = market.get("candles", [])

            if len(candles) < 20:
                return None, None

            features = self.feature_engine.build(
                candles
            )

        market_data = {
            "price": market.get("price"),
            "features": features,
            "trend": market.get("trend"),
            "volatility": market.get("volatility"),
            "runtime_state": runtime_state
        }

        signal = self.brain.decide(
            market_data
        )

        return signal, self.brain.get_events(10)
