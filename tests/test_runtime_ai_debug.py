import unittest

from backend.ai.trade_brain import TradeBrain
from backend.main import TradingRuntime, _build_llm_debug


class _BuyLSTM:
    def predict(self, features):
        return "BUY"


class _HoldLLM:
    def analyze(self, market_data):
        return "HOLD"


class RuntimeAIDebugTest(unittest.TestCase):

    def test_trading_runtime_connects_actual_llm_and_consensus_values(self):
        microstructure_state = {
            "buyPressure": 0.55,
            "sellPressure": 0.45,
            "momentumPersistence": 0.9,
            "spreadVolatility": 0.1,
            "liquidityQuality": 1.0,
            "imbalanceStrength": 1.0,
            "spreadQuality": 1.0,
            "spread": 0.0001,
            "absorptionDetected": False,
            "stagnantHeavyFlow": False,
            "fakePressureDetected": False,
        }

        result = TradingRuntime().process_runtime(
            microstructure_state
        )

        self.assertTrue(result["aiRuntimeReached"])
        self.assertEqual(
            result["aiRawSignal"],
            {"lstm": "BUY", "llm": "HOLD", "price": None},
        )
        self.assertIsNotNone(result["llmInput"])
        self.assertEqual(result["llmOutput"], "HOLD")
        self.assertEqual(result["llmDecision"], "HOLD")
        self.assertEqual(
            result["llmHoldReason"],
            "LLM returned HOLD without exposed reason",
        )
        self.assertIsNone(result["llmRejectBuyReason"])
        self.assertIsNone(result["llmRejectSellReason"])
        self.assertEqual(
            result["consensusInput"],
            {"lstm": "BUY", "llm": "HOLD"},
        )
        self.assertEqual(
            result["consensusReason"],
            "LSTM=BUY, LLM=HOLD",
        )
        self.assertEqual(result["governanceDecision"], "BLOCK")

    def test_llm_and_consensus_debug_uses_observed_runtime_values(self):
        brain = TradeBrain(_BuyLSTM(), _HoldLLM())
        llm_input = {
            "price": None,
            "features": [1.0],
            "trend": None,
            "volatility": None,
            "runtime_state": {"source": "test"},
        }

        self.assertEqual(brain.decide(llm_input), "HOLD")

        event = brain.get_events(1)[0]
        result = _build_llm_debug(
            event,
            event["data"],
            brain.latest_decision_debug,
        )

        self.assertEqual(result["llmInput"], llm_input)
        self.assertEqual(result["llmOutput"], "HOLD")
        self.assertEqual(result["llmDecision"], "HOLD")
        self.assertEqual(
            result["llmHoldReason"],
            "LLM returned HOLD without exposed reason",
        )
        self.assertIsNone(result["llmRejectBuyReason"])
        self.assertIsNone(result["llmRejectSellReason"])
        self.assertEqual(
            result["consensusInput"],
            {"lstm": "BUY", "llm": "HOLD"},
        )
        self.assertEqual(
            result["consensusReason"],
            "LSTM=BUY, LLM=HOLD",
        )

    def test_decision_debug_is_cleared_when_llm_is_not_reached(self):
        brain = TradeBrain(_BuyLSTM(), _HoldLLM())

        brain.decide({"features": [1.0]})
        self.assertIsNotNone(brain.latest_decision_debug)

        self.assertIsNone(brain.decide({"features": []}))
        self.assertIsNone(brain.latest_decision_debug)


if __name__ == "__main__":
    unittest.main()
