from types import SimpleNamespace

from backend.legacy_ai.ai_pipeline import AIPipeline
from backend.legacy_ai.llm_engine import LLMEngine
from backend.legacy_ai.lstm_model import LSTMModel
from backend.legacy_ai.runtime_adapter import RuntimeAdapter
from backend.legacy_ai.trade_brain import TradeBrain


def test_archived_lstm_is_reproducible_and_explicitly_heuristic():
    model = LSTMModel()
    decision = model.predict([0.2, 0.1, 0.0, 1.0, 0.2, 0.2, 0.2, 0.98, 0.2])

    assert decision == "HOLD"
    assert model.latest_debug["implementation"] == "DETERMINISTIC_HEURISTIC"
    assert model.latest_debug["modelLoaded"] is False
    assert model.latest_debug["networkInference"] is False


def test_archived_llm_is_reproducible_and_explicitly_rule_based():
    engine = LLMEngine()
    state = SimpleNamespace(
        directional_bias=0.8,
        momentum_score=0.8,
        imbalance_score=0.8,
        orderflow_delta=0.8,
    )

    assert engine.analyze({"runtime_state": state}) == "BUY"
    assert engine.latest_debug["llmDecisionSource"] == "runtime_state_rule"
    assert engine.latest_debug["llmFallbackUsed"] is False


def test_archived_adapter_and_consensus_remain_importable_offline():
    runtime_state = RuntimeAdapter().build({
        "symbol": "BTCUSDT",
        "buyPressure": 0.9,
        "sellPressure": 0.1,
        "momentumPersistence": 0.8,
        "spreadVolatility": 0.1,
        "liquidityQuality": 0.9,
        "imbalanceStrength": 0.8,
        "spreadQuality": 0.9,
        "spread": 0.0001,
        "absorptionDetected": False,
        "stagnantHeavyFlow": False,
        "fakePressureDetected": False,
    })
    pipeline = AIPipeline()
    signal, events = pipeline.decide({"runtime_state": runtime_state})

    assert isinstance(pipeline.brain, TradeBrain)
    assert signal in {"BUY", "SELL", "HOLD"}
    assert isinstance(events, list)
