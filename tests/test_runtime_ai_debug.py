import unittest
from types import SimpleNamespace

from backend.aggregation.MicrostructureStateBuilder import (
    MicrostructureStateBuilder,
)
from backend.ai.llm_engine import LLMEngine
from backend.ai.runtime_adapter import RuntimeAdapter
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
    def _microstructure_state(**overrides):
        state = {
            "buyPressure": 0.60,
            "sellPressure": 0.40,
            "momentumPersistence": 0.05,
            "spreadVolatility": 0.1,
            "liquidityQuality": 1.0,
            "imbalanceStrength": 1.0,
            "spreadQuality": 1.0,
            "spread": 0.0001,
            "absorptionDetected": False,
            "stagnantHeavyFlow": False,
            "fakePressureDetected": False,
        }
        state.update(overrides)
        return state

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
            momentum_score=0.24,
            imbalance_score=0.0,
        )

        self.assertEqual(
            engine.analyze({"runtime_state": runtime_state}),
            "HOLD",
        )

        expected_reason = (
            "HOLD because directional_bias <= 0.15 for BUY and "
            "directional_bias >= -0.15 for SELL; "
            "momentum_score < 0.25; imbalance_score <= 0"
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
                "momentum_score": 0.24,
                "imbalance_score": 0.0,
            },
        )
        self.assertEqual(
            engine.latest_debug["llmRuleThresholds"],
            {
                "buy_bias_gt": 0.15,
                "sell_bias_lt": -0.15,
                "momentum_gte": 0.25,
                "imbalance_gt": 0,
            },
        )
        self.assertFalse(
            engine.latest_debug["llmFallbackUsed"]
        )

    def test_llm_engine_applies_momentum_threshold_boundary(self):
        engine = LLMEngine()

        below_threshold = self._runtime_state(
            directional_bias=0.16,
            momentum_score=0.24,
            imbalance_score=0.1,
        )
        self.assertEqual(
            engine.analyze({"runtime_state": below_threshold}),
            "HOLD",
        )
        self.assertEqual(
            engine.latest_debug["llmHoldReason"],
            "HOLD because momentum_score < 0.25",
        )
        self.assertEqual(
            engine.latest_debug["llmRuleThresholds"]["momentum_gte"],
            0.25,
        )

        at_threshold = self._runtime_state(
            directional_bias=0.16,
            momentum_score=0.25,
            imbalance_score=0.1,
        )
        self.assertEqual(
            engine.analyze({"runtime_state": at_threshold}),
            "BUY",
        )
        self.assertEqual(
            engine.latest_debug["llmRuleThresholds"]["momentum_gte"],
            0.25,
        )

    def test_runtime_adapter_prefers_ai_momentum_persistence(self):
        runtime_state = RuntimeAdapter().build(
            self._microstructure_state(
                aiMomentumPersistence=0.75,
            )
        )

        self.assertEqual(runtime_state.momentum_score, 0.75)

    def test_runtime_adapter_falls_back_to_strategy_momentum(self):
        runtime_state = RuntimeAdapter().build(
            self._microstructure_state()
        )

        self.assertEqual(runtime_state.momentum_score, 0.05)

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
        self.assertEqual(
            result["momentumTrace"],
            {
                "sourceGenerator": (
                    "MicrostructureStateBuilder."
                    "compute_momentum_persistence"
                ),
                "sourceField": (
                    "microstructure_state.momentumPersistence"
                ),
                "sourcePresent": True,
                "sourceValue": 0.9,
                "sourceComputation": None,
                "priceHistoryGeneration": None,
                "strategyInputValue": 0.9,
                "strategyFallbackUsed": False,
                "strategyFallbackValue": 0.0,
                "strategyOutputPresent": False,
                "strategyOutputValue": None,
                "runtimeAdapterFallbackUsed": True,
                "runtimeStateValue": 0.9,
                "tradeBrainFallbackUsed": False,
                "tradeBrainValue": 0.9,
                "llmEngineFallbackUsed": False,
                "llmEngineValue": 0.9,
                "valueChanged": False,
                "zeroFirstObservedAt": None,
            },
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

    def test_runtime_debug_groups_ai_llm_and_trade_brain_values(self):
        result = TradingRuntime().process_runtime(
            self._microstructure_state(
                momentumPersistence=0.9,
            )
        )
        runtime_debug = result["runtimeDebug"]

        for key in (
            "momentumTrace",
            "aiMomentumTrace",
            "momentumPipelineTrace",
            "priceHistoryTrace",
            "aiRuntimeReached",
            "aiInput",
            "aiOutput",
            "aiDecision",
            "aiReason",
            "aiHoldReason",
            "llmDebug",
            "tradeBrainDebug",
        ):
            self.assertIn(key, runtime_debug)

        self.assertTrue(runtime_debug["aiRuntimeReached"])
        self.assertEqual(
            runtime_debug["aiInput"],
            result["aiInput"],
        )
        self.assertEqual(
            runtime_debug["aiOutput"],
            result["aiOutput"],
        )
        self.assertEqual(
            runtime_debug["aiDecision"],
            result["aiDecision"],
        )
        self.assertEqual(
            runtime_debug["aiHoldReason"],
            result["aiHoldReason"],
        )
        self.assertEqual(
            runtime_debug["aiReason"],
            result["consensusReason"],
        )
        self.assertEqual(
            runtime_debug["llmDebug"],
            {
                "input": result["llmInput"],
                "output": result["llmOutput"],
                "decision": result["llmDecision"],
                "confidence": result["llmConfidence"],
                "reason": result["llmRuleReason"],
                "decisionSource": result["llmDecisionSource"],
                "longCandidate": result["aiLongCandidate"],
                "shortCandidate": result["aiShortCandidate"],
                "rawSignal": result["aiRawSignal"],
            },
        )
        self.assertEqual(
            runtime_debug["tradeBrainDebug"],
            {
                "aiRuntimeReached": result["aiRuntimeReached"],
                "aiInput": result["aiInput"],
                "aiOutput": result["aiOutput"],
                "aiDecision": result["aiDecision"],
                "aiHoldReason": result["aiHoldReason"],
                "llmDecision": result["llmDecision"],
                "llmDecisionSource": result["llmDecisionSource"],
                "consensusReason": result["consensusReason"],
            },
        )

    def test_momentum_trace_proves_zero_exists_at_source(self):
        builder = MicrostructureStateBuilder()
        microstructure_state = builder.build_microstructure_state({
            "buyVolume": 60000.0,
            "sellVolume": 40000.0,
            "bestBid": 1.0,
            "bestAsk": 1.0001,
            "lastPrice": 1.00005,
        })

        self.assertEqual(
            microstructure_state["momentumPersistence"],
            0.0,
        )
        self.assertEqual(
            microstructure_state["momentumPersistenceDebug"],
            {
                "inputReady": True,
                "priceHistoryLength": 0,
                "priceHistoryMinRequired": None,
                "latestPrice": 1.00005,
                "previousPrice": None,
                "priceDelta": None,
                "priceDeltaAbs": None,
                "priceDeltaPct": None,
                "direction": "FLAT",
                "sameDirectionCount": 0,
                "upMoveCount": 0,
                "downMoveCount": 0,
                "flatMoveCount": 1,
                "returnValue": 0.0,
                "returnReason": (
                    "INSUFFICIENT_PRICE_HISTORY"
                ),
            },
        )

        result = TradingRuntime().process_runtime(
            microstructure_state
        )
        trace = result["momentumTrace"]

        self.assertEqual(result["strategyDirection"], "LONG")
        self.assertEqual(result["llmDecision"], "HOLD")
        self.assertEqual(
            result["llmHoldReason"],
            "HOLD because momentum_score < 0.25",
        )
        self.assertEqual(trace["sourceValue"], 0.0)
        self.assertEqual(
            trace["sourceComputation"],
            microstructure_state["momentumPersistenceDebug"],
        )
        self.assertEqual(trace["runtimeStateValue"], 0.0)
        self.assertEqual(trace["tradeBrainValue"], 0.0)
        self.assertEqual(trace["llmEngineValue"], 0.0)
        self.assertFalse(trace["strategyFallbackUsed"])
        self.assertFalse(trace["runtimeAdapterFallbackUsed"])
        self.assertFalse(trace["tradeBrainFallbackUsed"])
        self.assertFalse(trace["llmEngineFallbackUsed"])
        self.assertFalse(trace["valueChanged"])
        self.assertEqual(
            trace["zeroFirstObservedAt"],
            "microstructure_state.momentumPersistence",
        )

    def test_momentum_source_debug_explains_low_value(self):
        builder = MicrostructureStateBuilder()

        builder.compute_momentum_persistence(1.0)

        for _ in range(19):
            builder.compute_momentum_persistence(1.0)

        value = builder.compute_momentum_persistence(1.1)
        debug = builder.momentum_persistence_debug

        self.assertEqual(value, 0.05)
        self.assertEqual(debug["priceHistoryLength"], 20)
        self.assertEqual(debug["previousPrice"], 1.0)
        self.assertEqual(debug["latestPrice"], 1.1)
        self.assertAlmostEqual(debug["priceDelta"], 0.1)
        self.assertEqual(debug["direction"], "UP")
        self.assertEqual(debug["sameDirectionCount"], 1)
        self.assertEqual(debug["upMoveCount"], 1)
        self.assertEqual(debug["downMoveCount"], 0)
        self.assertEqual(debug["flatMoveCount"], 19)
        self.assertEqual(debug["returnValue"], 0.05)
        self.assertEqual(
            debug["returnReason"],
            "DOMINANT_DIRECTION_RATIO",
        )

    @staticmethod
    def _market_tick(price, timestamp):
        return {
            "buyVolume": 10.0,
            "sellVolume": 8.0,
            "bestBid": price - 0.0001,
            "bestAsk": price + 0.0001,
            "lastPrice": price,
            "pricePathDebug": {
                "marketUpdateTime": timestamp,
            },
        }

    def test_fast_twenty_ticks_do_not_fill_ai_momentum_history(self):
        builder = MicrostructureStateBuilder()

        first_state = builder.build_microstructure_state(
            self._market_tick(1.0, 100.0)
        )
        first_trace = first_state["aiMomentumTrace"]

        self.assertEqual(first_trace["deltaCount"], 0)
        self.assertEqual(
            first_trace["comparisonMetrics"]["activeDeltaRatio"],
            0,
        )

        for index in range(1, 20):
            state = builder.build_microstructure_state(
                self._market_tick(
                    1.0 + (index * 0.001),
                    100.0 + (index * 0.01),
                )
            )

        trace = state["aiMomentumTrace"]

        self.assertLess(trace["deltaCount"], 20)
        self.assertEqual(trace["sampleCount"], 2)
        self.assertEqual(trace["deltaCount"], 1)
        self.assertEqual(
            trace["reason"],
            "INSUFFICIENT_AI_PRICE_HISTORY",
        )
        self.assertEqual(len(builder.momentum_window), 19)

    def test_twenty_one_samples_at_100ms_fill_ai_momentum_history(self):
        builder = MicrostructureStateBuilder()

        for index in range(21):
            state = builder.build_microstructure_state(
                self._market_tick(
                    1.0 + (index * 0.001),
                    200.0 + (index * 0.1),
                )
            )

        trace = state["aiMomentumTrace"]

        self.assertEqual(trace["sampleCount"], 21)
        self.assertEqual(trace["deltaCount"], 20)
        self.assertEqual(trace["timeSpanMs"], 2000.0)
        self.assertEqual(trace["minIntervalMs"], 100.0)
        self.assertEqual(trace["maxIntervalMs"], 100.0)
        self.assertEqual(trace["positiveDeltaCount"], 20)
        self.assertEqual(trace["negativeDeltaCount"], 0)
        self.assertEqual(trace["flatDeltaCount"], 0)
        self.assertEqual(trace["dominantDirection"], "UP")
        self.assertEqual(trace["dominantDirectionCount"], 20)
        self.assertEqual(
            trace["samplePrices"],
            [1.0 + (index * 0.001) for index in range(21)],
        )
        self.assertEqual(
            trace["sampleDeltas"],
            [
                newer - older
                for older, newer in zip(
                    trace["samplePrices"],
                    trace["samplePrices"][1:],
                )
            ],
        )
        self.assertEqual(trace["firstPrice"], 1.0)
        self.assertEqual(trace["lastPrice"], 1.02)
        self.assertAlmostEqual(trace["netPriceChange"], 0.02)
        self.assertAlmostEqual(trace["absNetPriceChange"], 0.02)
        self.assertEqual(trace["value"], 1.0)
        self.assertEqual(trace["reason"], "OK")
        self.assertEqual(state["aiMomentumPersistence"], 1.0)

    def test_ai_momentum_trace_distinguishes_mixed_and_flat_deltas(self):
        builder = MicrostructureStateBuilder()
        prices = [100.0, 101.0, 100.0, 100.0, 102.0]

        for index, price in enumerate(prices):
            state = builder.build_microstructure_state(
                self._market_tick(
                    price,
                    250.0 + (index * 0.1),
                )
            )

        trace = state["aiMomentumTrace"]

        self.assertEqual(trace["positiveDeltaCount"], 2)
        self.assertEqual(trace["negativeDeltaCount"], 1)
        self.assertEqual(trace["flatDeltaCount"], 1)
        self.assertEqual(trace["dominantDirection"], "UP")
        self.assertEqual(trace["dominantDirectionCount"], 2)
        self.assertEqual(trace["samplePrices"], prices)
        self.assertEqual(trace["sampleDeltas"], [1.0, -1.0, 0.0, 2.0])
        self.assertEqual(trace["firstPrice"], 100.0)
        self.assertEqual(trace["lastPrice"], 102.0)
        self.assertEqual(trace["netPriceChange"], 2.0)
        self.assertEqual(trace["absNetPriceChange"], 2.0)
        self.assertEqual(trace["value"], 0.5)
        self.assertEqual(
            trace["comparisonMetrics"],
            {
                "currentMomentum": trace["value"],
                "flatExcludedMomentum": 2 / 3,
                "activeDeltaRatio": 3 / 4,
                "netPriceChange": trace["netPriceChange"],
                "absNetPriceChange": trace["absNetPriceChange"],
            },
        )
        self.assertEqual(
            trace["candidateMetrics"],
            {
                "directionPurity": 2 / 3,
                "activityRatio": 3 / 4,
                "priceDirection": "UP",
                "priceMove": 2.0,
                "directionConfirmed": True,
                "activityGatePassed": True,
                "priceMoveGatePassed": True,
                "proposedMomentumScore": 2 / 3,
                "proposedMomentumUsable": True,
            },
        )

    def test_ai_momentum_trace_distinguishes_tie_from_all_flat(self):
        tied_builder = MicrostructureStateBuilder()

        for index, price in enumerate([100.0, 101.0, 100.0]):
            tied_state = tied_builder.build_microstructure_state(
                self._market_tick(
                    price,
                    260.0 + (index * 0.1),
                )
            )

        tied_trace = tied_state["aiMomentumTrace"]

        self.assertEqual(tied_trace["dominantDirection"], "TIE")
        self.assertEqual(tied_trace["dominantDirectionCount"], 1)
        self.assertEqual(tied_trace["netPriceChange"], 0.0)
        self.assertEqual(tied_trace["absNetPriceChange"], 0.0)
        self.assertEqual(
            tied_trace["candidateMetrics"]["priceDirection"],
            "FLAT",
        )
        self.assertFalse(
            tied_trace["candidateMetrics"]["directionConfirmed"]
        )
        self.assertFalse(
            tied_trace["candidateMetrics"]["priceMoveGatePassed"]
        )
        self.assertFalse(
            tied_trace["candidateMetrics"]["proposedMomentumUsable"]
        )

        flat_builder = MicrostructureStateBuilder()

        for index in range(3):
            flat_state = flat_builder.build_microstructure_state(
                self._market_tick(
                    100.0,
                    270.0 + (index * 0.1),
                )
            )

        flat_trace = flat_state["aiMomentumTrace"]

        self.assertEqual(flat_trace["positiveDeltaCount"], 0)
        self.assertEqual(flat_trace["negativeDeltaCount"], 0)
        self.assertEqual(flat_trace["flatDeltaCount"], 2)
        self.assertEqual(flat_trace["dominantDirection"], "FLAT")
        self.assertEqual(flat_trace["dominantDirectionCount"], 0)
        self.assertEqual(
            flat_trace["comparisonMetrics"]["flatExcludedMomentum"],
            0,
        )
        self.assertEqual(
            flat_trace["comparisonMetrics"]["activeDeltaRatio"],
            0.0,
        )
        self.assertEqual(
            flat_trace["candidateMetrics"],
            {
                "directionPurity": 0,
                "activityRatio": 0.0,
                "priceDirection": "FLAT",
                "priceMove": 0.0,
                "directionConfirmed": False,
                "activityGatePassed": False,
                "priceMoveGatePassed": False,
                "proposedMomentumScore": 0,
                "proposedMomentumUsable": False,
            },
        )

    def test_ai_momentum_history_does_not_change_existing_momentum(self):
        builder = MicrostructureStateBuilder()
        momentum_only_builder = MicrostructureStateBuilder()
        prices = [1.0, 1.1, 1.05, 1.2, 1.2]
        expected_values = [
            momentum_only_builder.compute_momentum_persistence(price)
            for price in prices
        ]
        actual_values = []

        for index, price in enumerate(prices):
            state = builder.build_microstructure_state(
                self._market_tick(
                    price,
                    300.0 + (index * 0.01),
                )
            )
            actual_values.append(state["momentumPersistence"])

        self.assertEqual(actual_values, expected_values)
        self.assertEqual(
            builder.momentum_window,
            momentum_only_builder.momentum_window,
        )

    def test_runtime_debug_exposes_ai_momentum_trace(self):
        builder = MicrostructureStateBuilder()
        state = builder.build_microstructure_state(
            self._market_tick(1.0, 400.0)
        )

        runtime_result = TradingRuntime().process_runtime(state)

        self.assertEqual(
            runtime_result["aiMomentumTrace"],
            state["aiMomentumTrace"],
        )
        self.assertEqual(
            runtime_result["runtimeDebug"]["aiMomentumTrace"],
            state["aiMomentumTrace"],
        )
        self.assertEqual(
            set(runtime_result["aiMomentumTrace"]),
            {
                "sampleCount",
                "deltaCount",
                "timeSpanMs",
                "minIntervalMs",
                "maxIntervalMs",
                "positiveDeltaCount",
                "negativeDeltaCount",
                "flatDeltaCount",
                "dominantDirection",
                "dominantDirectionCount",
                "samplePrices",
                "sampleDeltas",
                "firstPrice",
                "lastPrice",
                "netPriceChange",
                "absNetPriceChange",
                "value",
                "reason",
                "comparisonMetrics",
                "candidateMetrics",
            },
        )
        self.assertEqual(
            runtime_result["runtimeDebug"]["aiMomentumTrace"][
                "candidateMetrics"
            ],
            state["aiMomentumTrace"]["candidateMetrics"],
        )

    def test_runtime_debug_exposes_momentum_pipeline_divergence(self):
        microstructure_state = {
            "buyPressure": 0.60,
            "sellPressure": 0.40,
            "momentumPersistence": 0.05,
            "aiMomentumPersistence": 0.30,
            "aiMomentumTrace": {
                "value": 0.30,
                "comparisonMetrics": {
                    "flatExcludedMomentum": 0.75,
                },
                "candidateMetrics": {
                    "proposedMomentumScore": 0.75,
                },
            },
            "spreadVolatility": 0.1,
            "liquidityQuality": 1.0,
            "imbalanceStrength": 1.0,
            "spreadQuality": 1.0,
            "spread": 0.0001,
            "absorptionDetected": False,
            "stagnantHeavyFlow": False,
            "fakePressureDetected": False,
        }

        runtime_result = TradingRuntime().process_runtime(
            microstructure_state
        )
        trace = runtime_result["runtimeDebug"][
            "momentumPipelineTrace"
        ]

        self.assertEqual(
            set(trace),
            {
                "microstructureMomentumPersistence",
                "microstructureAiMomentumPersistence",
                "runtimeAdapterInputMomentum",
                "runtimeAdapterInputAiMomentum",
                "runtimeStateMomentumScore",
                "tradeBrainInputMomentumScore",
                "llmInputMomentumScore",
                "llmRuleInputMomentumScore",
                "aiMomentumTraceValue",
                "aiMomentumFlatExcludedMomentum",
                "aiMomentumProposedMomentumScore",
                "allValuesEqual",
                "mismatchDetected",
                "mismatchReason",
            },
        )
        self.assertEqual(
            trace,
            {
                "microstructureMomentumPersistence": 0.05,
                "microstructureAiMomentumPersistence": 0.30,
                "runtimeAdapterInputMomentum": 0.05,
                "runtimeAdapterInputAiMomentum": 0.30,
                "runtimeStateMomentumScore": 0.30,
                "tradeBrainInputMomentumScore": 0.30,
                "llmInputMomentumScore": 0.30,
                "llmRuleInputMomentumScore": 0.30,
                "aiMomentumTraceValue": 0.30,
                "aiMomentumFlatExcludedMomentum": 0.75,
                "aiMomentumProposedMomentumScore": 0.75,
                "allValuesEqual": False,
                "mismatchDetected": True,
                "mismatchReason": (
                    "PROPOSED_SCORE_DIFFERS_FROM_LLM_INPUT"
                ),
            },
        )
        self.assertEqual(
            runtime_result["runtimeDebug"]["aiMomentumTrace"],
            microstructure_state["aiMomentumTrace"],
        )
        self.assertIn(
            "comparisonMetrics",
            runtime_result["runtimeDebug"]["aiMomentumTrace"],
        )
        self.assertIn(
            "candidateMetrics",
            runtime_result["runtimeDebug"]["aiMomentumTrace"],
        )
        self.assertEqual(
            microstructure_state["momentumPersistence"],
            0.05,
        )
        self.assertEqual(
            runtime_result["llmInput"]["runtime_state"][
                "momentum_score"
            ],
            0.30,
        )
        self.assertEqual(
            runtime_result["llmInput"]["features"][
                "feature_map"
            ]["momentum_score"],
            0.30,
        )
        self.assertEqual(
            runtime_result["llmRuleInput"]["momentum_score"],
            0.30,
        )
        self.assertEqual(runtime_result["llmDecision"], "BUY")

    def test_llm_buy_sell_hold_conditions_use_momentum_threshold(self):
        engine = LLMEngine()

        self.assertEqual(
            engine.RUNTIME_RULE_THRESHOLDS,
            {
                "buy_bias_gt": 0.15,
                "sell_bias_lt": -0.15,
                "momentum_gte": 0.25,
                "imbalance_gt": 0,
            },
        )
        self.assertEqual(
            engine.analyze({
                "runtime_state": self._runtime_state(
                    directional_bias=0.16,
                    momentum_score=0.25,
                    imbalance_score=0.01,
                ),
            }),
            "BUY",
        )
        self.assertEqual(
            engine.analyze({
                "runtime_state": self._runtime_state(
                    directional_bias=-0.16,
                    momentum_score=0.25,
                    imbalance_score=0.01,
                ),
            }),
            "SELL",
        )
        self.assertEqual(
            engine.analyze({
                "runtime_state": self._runtime_state(
                    directional_bias=0.16,
                    momentum_score=0.24,
                    imbalance_score=0.01,
                ),
            }),
            "HOLD",
        )

    def test_runtime_debug_exposes_price_history_generation_path(self):
        builder = MicrostructureStateBuilder()

        first_state = builder.build_microstructure_state({
            "buyVolume": 10.0,
            "sellVolume": 8.0,
            "bestBid": 0.9,
            "bestAsk": 1.1,
            "lastPrice": 1.0,
            "pricePathDebug": {
                "lastWsPrice": 1.0,
                "lastWsReceiveTime": 100.0,
                "wsUpdateCount": 1,
                "marketUpdatePrice": 1.0,
                "marketUpdateTime": 100.1,
                "providerPrice": 1.0,
                "providerPreviousPrice": 0.0,
                "providerUpdateCount": 1,
                "providerTimestamp": 100.1,
                "providerPriceChanged": True,
            },
        })

        second_state = builder.build_microstructure_state({
            "buyVolume": 10.0,
            "sellVolume": 8.0,
            "bestBid": 0.9,
            "bestAsk": 1.1,
            "lastPrice": 1.0,
            "pricePathDebug": {
                "lastWsPrice": 1.0,
                "lastWsReceiveTime": 101.0,
                "wsUpdateCount": 2,
                "marketUpdatePrice": 1.0,
                "marketUpdateTime": 101.1,
                "providerPrice": 1.0,
                "providerPreviousPrice": 1.0,
                "providerUpdateCount": 2,
                "providerTimestamp": 101.1,
                "providerPriceChanged": False,
            },
        })

        runtime_result = TradingRuntime().process_runtime(
            second_state
        )
        trace = runtime_result["priceHistoryTrace"]

        self.assertEqual(
            trace,
            second_state["priceHistoryGenerationDebug"],
        )
        self.assertTrue({
            "lastWsPrice",
            "lastWsReceiveTime",
            "wsUpdateCount",
            "marketUpdatePrice",
            "marketUpdateTime",
            "providerPrice",
            "providerPreviousPrice",
            "providerUpdateCount",
            "providerTimestamp",
            "providerPriceChanged",
            "historyLength",
            "historyCapacity",
            "last20Prices",
            "last20PriceDeltas",
            "last20Timestamps",
            "historyWindowMs",
            "historyWindowSeconds",
            "averageIntervalMs",
            "minIntervalMs",
            "maxIntervalMs",
            "updatesPerSecondEstimate",
            "priceChangeEventsInLast20",
            "ticksUntilPriceChange",
            "samePriceRunLength",
            "latest20TimeRange",
            "duplicatePriceCount",
            "uniquePriceCount",
            "flatPriceCount",
            "newestHistoryPrice",
            "oldestHistoryPrice",
            "historyUpdatedAt",
            "bufferAppendAttempted",
            "bufferAppendExecuted",
            "bufferIgnored",
            "bufferIgnoreReason",
        }.issubset(trace))
        self.assertEqual(trace["lastWsPrice"], 1.0)
        self.assertEqual(trace["wsUpdateCount"], 2)
        self.assertEqual(trace["marketUpdatePrice"], 1.0)
        self.assertEqual(trace["providerPrice"], 1.0)
        self.assertFalse(trace["providerPriceChanged"])
        self.assertEqual(trace["historyLength"], 2)
        self.assertEqual(trace["historyCapacity"], 20)
        self.assertEqual(trace["last20Prices"], [1.0, 1.0])
        self.assertEqual(trace["last20PriceDeltas"], [None, 0.0])
        self.assertEqual(trace["last20Timestamps"], [100.1, 101.1])
        self.assertAlmostEqual(trace["historyWindowMs"], 1000.0)
        self.assertAlmostEqual(trace["historyWindowSeconds"], 1.0)
        self.assertAlmostEqual(trace["averageIntervalMs"], 1000.0)
        self.assertAlmostEqual(trace["minIntervalMs"], 1000.0)
        self.assertAlmostEqual(trace["maxIntervalMs"], 1000.0)
        self.assertAlmostEqual(
            trace["updatesPerSecondEstimate"],
            1.0,
        )
        self.assertEqual(trace["priceChangeEventsInLast20"], 0)
        self.assertIsNone(trace["ticksUntilPriceChange"])
        self.assertEqual(trace["samePriceRunLength"], 2)
        self.assertEqual(
            trace["latest20TimeRange"],
            {
                "oldestTimestamp": 100.1,
                "newestTimestamp": 101.1,
            },
        )
        self.assertEqual(trace["duplicatePriceCount"], 1)
        self.assertEqual(trace["uniquePriceCount"], 1)
        self.assertEqual(trace["flatPriceCount"], 1)
        self.assertEqual(trace["newestHistoryPrice"], 1.0)
        self.assertEqual(trace["oldestHistoryPrice"], 1.0)
        self.assertEqual(trace["historyUpdatedAt"], 101.1)
        self.assertTrue(trace["bufferAppendAttempted"])
        self.assertTrue(trace["bufferAppendExecuted"])
        self.assertFalse(trace["bufferIgnored"])
        self.assertIsNone(trace["bufferIgnoreReason"])
        self.assertEqual(
            runtime_result["runtimeDebug"]["momentumTrace"][
                "priceHistoryGeneration"
            ],
            trace,
        )

        self.assertEqual(
            first_state["priceHistoryGenerationDebug"][
                "historyLength"
            ],
            1,
        )

    def test_price_history_debug_measures_latest_twenty_time_width(self):
        builder = MicrostructureStateBuilder()

        for index in range(20):
            price = 1.0 if index < 3 else 1.1
            state = builder.build_microstructure_state({
                "buyVolume": 10.0,
                "sellVolume": 8.0,
                "bestBid": 0.9,
                "bestAsk": 1.1,
                "lastPrice": price,
                "pricePathDebug": {
                    "marketUpdateTime": 100.0 + (
                        index * 0.01
                    ),
                },
            })

        trace = state["priceHistoryGenerationDebug"]

        self.assertEqual(trace["historyLength"], 20)
        self.assertAlmostEqual(trace["historyWindowMs"], 190.0)
        self.assertAlmostEqual(
            trace["historyWindowSeconds"],
            0.19,
        )
        self.assertAlmostEqual(trace["averageIntervalMs"], 10.0)
        self.assertAlmostEqual(trace["minIntervalMs"], 10.0)
        self.assertAlmostEqual(trace["maxIntervalMs"], 10.0)
        self.assertAlmostEqual(
            trace["updatesPerSecondEstimate"],
            100.0,
        )
        self.assertEqual(trace["priceChangeEventsInLast20"], 1)
        self.assertEqual(trace["ticksUntilPriceChange"], 3)
        self.assertEqual(trace["samePriceRunLength"], 17)
        self.assertEqual(
            trace["latest20TimeRange"],
            {
                "oldestTimestamp": 100.0,
                "newestTimestamp": 100.19,
            },
        )

    def test_trade_brain_exposes_rule_debug_on_event_and_runtime_debug(self):
        engine = LLMEngine()
        brain = TradeBrain(_BuyLSTM(), engine)
        llm_input = {
            "features": [1.0],
            "runtime_state": self._runtime_state(
                directional_bias=0.2,
                momentum_score=0.24,
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
            "HOLD because momentum_score < 0.25",
        )
        self.assertEqual(
            result["llmHoldReason"],
            "HOLD because momentum_score < 0.25",
        )
        self.assertEqual(
            result["llmRuleInput"],
            {
                "directional_bias": 0.2,
                "momentum_score": 0.24,
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
