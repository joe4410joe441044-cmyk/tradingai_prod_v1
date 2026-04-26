from backend.ai.feature_engine import FeatureEngine
from backend.ai.trade_brain import TradeBrain
from backend.ai.lstm_model import LSTMModel
from backend.ai.llm_engine import LLMEngine


class AIPipeline:

    def __init__(self):
        self.feature_engine = FeatureEngine()
        self.brain = TradeBrain(
            lstm_model=LSTMModel(),
            llm_engine=LLMEngine()
        )

    def decide(self, market):

        candles = market.get("candles", [])

        if len(candles) < 20:
            return None, None

        # ① 特徴量
        features = self.feature_engine.build(candles)

        market_data = {
            "price": market.get("price"),
            "features": features,
            "trend": market.get("trend"),
            "volatility": market.get("volatility")
        }

        # ② AI判断
        signal = self.brain.decide(market_data)

        return signal, self.brain.get_events(10)