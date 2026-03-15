# test_full_bot_flow.py
import sys
import os
import time
import logging

# =====================================================
# ルートパス追加（core, engine, wrappers を認識させる）
# =====================================================
root_path = os.path.abspath(os.path.dirname(__file__))
if root_path not in sys.path:
    sys.path.insert(0, root_path)  # 最優先で探索

# =====================================================
# モジュールインポート
# =====================================================
from core.trade_core import TradeCore
from engine.execution_engine import ExecutionEngine
from wrappers.strategy_wrapper import StrategyWrapper

# =====================================================
# ダミー戦略（TestSignalGenerator 代替）
# =====================================================
class DummyStrategy:
    def __init__(self):
        self.name = "DummyStrategy"

    def generate_signal(self):
        # 買いシグナルを返す
        return {"symbol": "BTCUSDT", "type": "BUY", "volume": 0.01}


# =====================================================
# StrategyWrapper 拡張（TradeCore連携）
# =====================================================
class TestStrategyWrapper(StrategyWrapper):
    def on_signal(self, signal):
        # Signal受信 → TradeCoreに委譲
        if hasattr(self, "trade_core"):
            self.trade_core.handle_signal(signal)
        else:
            # 既存 execute_order を呼ぶ場合
            self.execution_engine.execute_order(signal)


# =====================================================
# TradeCore 拡張（最小版）
# =====================================================
class TestTradeCore(TradeCore):
    def __init__(self, execution_engine, max_positions=5):
        self.execution_engine = execution_engine
        self.max_positions = max_positions
        self.positions = []

    def handle_signal(self, signal):
        if len(self.positions) < self.max_positions:
            self.positions.append(signal)
            self.execution_engine.execute_order(signal)
        else:
            logging.info(f"Max positions reached, signal skipped: {signal}")


# =====================================================
# メインテストフロー
# =====================================================
def main():
    # Logger初期化（グローバル）
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')

    # ExecutionEngine 初期化（資金未投入モード）
    exec_engine = ExecutionEngine(live=False)

    # TradeCore 初期化
    trade_core = TestTradeCore(exec_engine)

    # StrategyWrapper 初期化 & TradeCore登録
    wrapper = TestStrategyWrapper(execution_engine=exec_engine)
    wrapper.trade_core = trade_core

    # ダミー戦略登録
    strategy = DummyStrategy()
    wrapper.register_strategy(strategy)

    # フロー確認ループ（3回だけ）
    for i in range(3):
        signal = strategy.generate_signal()
        wrapper.on_signal(signal)
        time.sleep(0.5)  # 遅延でログ観察

    # 最終ポジション確認
    logging.info(f"Final positions: {trade_core.positions}")


if __name__ == "__main__":
    main()