# test_full_bot_flow.py

import sys
import os
import time
import logging

# =====================================================
# ルートパスを追加（Botフォルダを認識させる）
# =====================================================
sys.path.append(os.path.abspath("."))

# =====================================================
# BOTモジュール
# =====================================================
from Bot.core.trade_core import TradeCore
from Bot.engine.execution_engine import ExecutionEngine
from Bot.wrappers.strategy_wrapper import StrategyWrapper


# =====================================================
# ダミーStrategy
# =====================================================
class DummyStrategy:

    def generate_signal(self):

        return {
            "symbol": "BTCUSDT",
            "type": "BUY",
            "volume": 0.01
        }


# =====================================================
# StrategyWrapperテスト用
# =====================================================
class TestStrategyWrapper(StrategyWrapper):

    def on_signal(self, signal):

        print("Signal received:", signal)

        # core に処理を渡す
        self.core.handle_signal(signal)


# =====================================================
# TradeCoreテスト版
# =====================================================
class TestTradeCore(TradeCore):

    def __init__(self, execution_engine):

        self.execution_engine = execution_engine
        self.positions = []
        self.max_positions = 5

    def handle_signal(self, signal):

        print("TradeCore handling signal")

        if len(self.positions) < self.max_positions:

            self.positions.append(signal)

            print("Order sent to ExecutionEngine")

            self.execution_engine.execute_order(signal)

        else:

            print("Max positions reached")


# =====================================================
# MAIN
# =====================================================
def main():

    logging.basicConfig(level=logging.INFO)

    print("")
    print("BOT FLOW TEST START")
    print("")

    # ExecutionEngine
    exec_engine = ExecutionEngine()

    # TradeCore
    trade_core = TestTradeCore(exec_engine)

    # StrategyWrapper
    wrapper = TestStrategyWrapper(core=trade_core)

    # Strategy
    strategy = DummyStrategy()

    # テストループ
    for i in range(3):

        print("")
        print("Loop:", i + 1)

        signal = strategy.generate_signal()

        wrapper.on_signal(signal)

        time.sleep(1)

    print("")
    print("Final Positions")
    print(trade_core.positions)


if __name__ == "__main__":
    main()
