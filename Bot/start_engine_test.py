# -*- coding: utf-8 -*-
from engine.market_engine import MarketEngine
from strategies.fvg_strategy import FVGStrategy

# --- 繝繝溘・ ExecutionEngine・育匱豕ｨ縺ｪ縺暦ｼ・---
class TestExecutionEngine:
    def send_signal(self, signal):
        print(f"[ExecutionEngine] Signal received (trading disabled): {signal}")

# --- Strategy 諡｡蠑ｵ・亥女菫｡繧ｭ繝｣繝ｳ繝峨Ν遒ｺ隱咲畑・・---
class TestFVGStrategy(FVGStrategy):
    def __init__(self, execution_engine, **kwargs):
        super().__init__(**kwargs)
        self.execution_engine = execution_engine

    def on_bar(self, market_data):
        print("[TestStrategy] Market data received:", market_data)
        super().on_bar(market_data)  # 蜈・・謌ｦ逡･蜃ｦ逅・ｂ蜻ｼ縺ｶ

        # 莉ｮ縺ｫ signal 縺後≠繧後・繝繝溘・ ExecutionEngine 縺ｫ騾√ｋ
        signal = getattr(self, "latest_signal", None)
        if signal:
            self.execution_engine.send_signal(signal)
            print(f"[TestStrategy] Signal generated: {signal}")

if __name__ == "__main__":
    exec_engine = TestExecutionEngine()
    strategy = TestFVGStrategy(execution_engine=exec_engine)

    engine = MarketEngine(
        strategies=[strategy],
        debug=True,
        telegram_token=None
    )

    # BTCUSDT 1蛻・ｶｳ
    engine.add_ws_client("BTCUSDT")

    print("=== start_engine_test running ===")
    input("Press Enter to exit...\n")
