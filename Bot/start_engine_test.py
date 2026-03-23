# -*- coding: utf-8 -*-

import asyncio
import logging

from Bot.engine.market_engine import MarketEngine
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.core.trade_core import TradeCore


# ------------------------------
# Logger
# ------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BotTest")


# ------------------------------
# ExecutionEngine（ダミー）
# ------------------------------
class TestExecutionEngine:
    def send_signal(self, signal):
        print(f"[ExecutionEngine] Signal received (trading disabled): {signal}")


# ------------------------------
# Strategyラッパー
# ------------------------------
class TestFVGStrategy(FVGStrategy):
    def __init__(self, trade_core, execution_engine):
        super().__init__(trade_core=trade_core)
        self.execution_engine = execution_engine

    async def on_bar(self, market_data):
        print("[TestStrategy] Market data received:", market_data)

        try:
            super().on_bar(market_data)
        except Exception as e:
            logger.exception(f"Error inside FVGStrategy: {e}")

        signal = getattr(self, "latest_signal", None)
        if signal:
            self.execution_engine.send_signal(signal)
            print(f"[TestStrategy] Signal generated: {signal}")


# ------------------------------
# メイン処理
# ------------------------------
async def main():
    trade_core = TradeCore()
    exec_engine = TestExecutionEngine()

    strategy = TestFVGStrategy(
        trade_core=trade_core,
        execution_engine=exec_engine
    )

    # ✅ 最小構成（これが正解）
    engine = MarketEngine(
    strategies=[strategy],
    strategy_callback=strategy.on_bar
)

    print("=== start_engine_test running (Ctrl+C to exit) ===")

    # ------------------------------
    # WebSocket起動（安全分岐）
    # ------------------------------
    try:
        if hasattr(engine, "run_websocket"):
            await engine.run_websocket()

        elif hasattr(engine, "run"):
            await engine.run()

        else:
            raise RuntimeError("MarketEngine has no run method")

    except asyncio.CancelledError:
        print("WebSocket task cancelled. Exiting...")

    except Exception as e:
        logger.exception(f"Unexpected error in main: {e}")


# ------------------------------
# エントリポイント
# ------------------------------
if __name__ == "__main__":
    asyncio.run(main())