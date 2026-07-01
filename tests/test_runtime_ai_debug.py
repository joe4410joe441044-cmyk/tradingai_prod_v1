import unittest
from types import SimpleNamespace

from backend.ai.llm_engine import LLMEngine
from backend.ai.trade_brain import TradeBrain
from backend.main import TradingRuntime, _build_llm_debug


class _BuyLSTM:
    def predict(self, features):
        return "BUY"


class _HoldLSTM:
    def predict(self, features):
        return "HOLD"


class _HoldLLM:
    def analyze(self, market_data):
        return "HOLD"


class RuntimeAIDebugTest(unittest.TestCase):

    @staticmethod
    def _runtime_state(
        directional_bias,
        momentum_score,
        imbalance_score,
    ):
        return SimpleNamespace(
            directional_bias=directional_bias,
            momentum_score=momentum_score,
            imbalance_score=imbalance_score,
            orderflow_delta=directional_bias,
        )

    def test_llm_engine_records_specific_runtime_hold_reasons(self):
        engine = LLMEngine()
        runtime_state = self._runtime_state(
            directional_bias=0.0,
            momentum_score=0.4,
            imbalance_score=0.0,
        )

        self.assertEqual(
            engine.analyze({"runtime_state": runtime_state}),
            "HOLD",
        )

        expected_reason = (
            "HOLD because directional_bias <= 0.15 for BUY and "
            "directional_bias >= -0.15 for SELL; "
            "momentum_score < 0.50; imbalance_score <= 0"
        )

        self.assertEqual(
            engine.latest_debug["llmRuleReason"],
            expected_reason,
        )
        self.assertEqual(
            engine.latest_debug["llmHoldReason"],
            expected_reason,
        )
        self.assertEqual(
            engine.latest_debug["llmDecisionSource"],
            "runtime_state_rule",
        )
        self.assertEqual(
            engine.latest_debug["llmRuleInput"],
            {
                "directional_bias": 0.0,
                "momentum_score": 0.4,
                "imbalance_score": 0.0,
            },
        )
        self.assertEqual(
            engine.latest_debug["llmRuleThresholds"],
            {
                "buy_bias_gt": 0.15,
                "sell_bias_lt": -0.15,
                "momentum_gte": 0.50,
                "imbalance_gt": 0,
            },
        )
        self.assertFalse(
            engine.latest_debug["llmFallbackUsed"]
        )

    def test_llm_engine_records_legacy_hold_fallback_reason(self):
        engine = LLMEngine()

        self.assertEqual(
            engine.analyze({
                "trend": "down",
                "volatility": 0.9,
            }),
            "HOLD",
        )
        self.assertEqual(
            engine.latest_debug["llmDecisionSource"],
            "legacy_market_rule",
        )
        self.assertEqual(
            engine.latest_debug["llmHoldReason"],
            "HOLD because legacy volatility > 0.8 and trend is not up",
        )
        self.assertTrue(
            engine.latest_debug["llmFallbackUsed"]
        )
        self.assertEqual(
            engine.latest_debug["llmFallbackReason"],
            "runtime_state missing; used legacy market_data rule",
        )

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
            "HOLD because directional_bias <= 0.15 for BUY and "
            "directional_bias >= -0.15 for SELL",
        )
        self.assertEqual(
            result["llmRuleReason"],
            result["llmHoldReason"],
        )
        self.assertEqual(
            result["llmDecisionSource"],
            "runtime_state_rule",
        )
        self.assertEqual(
            result["llmPromptSummary"],
            "NOT_APPLICABLE_RULE_ENGINE",
        )
        self.assertEqual(result["llmRawOutput"], "HOLD")
        self.assertEqual(result["llmParsedOutput"], "HOLD")
        self.assertEqual(
            result["llmParserResult"],
            "NOT_APPLICABLE_RULE_ENGINE",
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

    def test_trade_brain_exposes_rule_debug_on_event_and_runtime_debug(self):
        engine = LLMEngine()
        brain = TradeBrain(_BuyLSTM(), engine)
        llm_input = {
            "features": [1.0],
            "runtime_state": self._runtime_state(
                directional_bias=0.2,
                momentum_score=0.4,
                imbalance_score=1.0,
            ),
        }

        self.assertEqual(brain.decide(llm_input), "HOLD")

        event = brain.get_events(1)[0]
        result = _build_llm_debug(
            event,
            event["data"],
            brain.latest_decision_debug,
        )

        self.assertEqual(
            event["llmHoldReason"],
            "HOLD because momentum_score < 0.50",
        )
        self.assertEqual(
            result["llmHoldReason"],
            "HOLD because momentum_score < 0.50",
        )
        self.assertEqual(
            result["llmRuleInput"],
            {
                "directional_bias": 0.2,
                "momentum_score": 0.4,
                "imbalance_score": 1.0,
            },
        )
        self.assertEqual(
            result["llmPromptSummary"],
            "NOT_APPLICABLE_RULE_ENGINE",
        )
        self.assertEqual(
            result["llmParserResult"],
            "NOT_APPLICABLE_RULE_ENGINE",
        )

    def test_consensus_hold_remains_distinct_from_llm_hold(self):
        engine = LLMEngine()
        brain = TradeBrain(_HoldLSTM(), engine)
        llm_input = {
            "features": [1.0],
            "runtime_state": self._runtime_state(
                directional_bias=0.2,
                momentum_score=0.9,
                imbalance_score=1.0,
            ),
        }

        self.assertEqual(brain.decide(llm_input), "HOLD")

        event = brain.get_events(1)[0]
        result = _build_llm_debug(
            event,
            event["data"],
            brain.latest_decision_debug,
        )

        self.assertEqual(event["action"], "HOLD")
        self.assertEqual(result["llmDecision"], "BUY")
        self.assertIsNone(result["llmHoldReason"])
        self.assertEqual(
            result["consensusReason"],
            "LSTM=HOLD, LLM=BUY",
        )

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
