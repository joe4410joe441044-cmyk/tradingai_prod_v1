# -*- coding: utf-8 -*-

print("=== FILE LOADED ===")

import asyncio
import logging
import inspect

from Bot.engine.market_engine import MarketEngine
from Bot.core.trade_core import TradeCore
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.engine.execution_engine import ExecutionEngine
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.utils.logger import BotLogger


# =========================
# 設定
# =========================
WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"

TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"


# =========================================
# Strategy Runner
# =========================================
class StrategyRunner:
    def __init__(self, strategy, execution_engine):
        self.strategy = strategy
        self.execution_engine = execution_engine

    async def on_bar(self, market_data):
        try:
            print("[Runner] on_bar called")

            result = self.strategy.on_bar(market_data)

            if asyncio.iscoroutine(result):
                await result

            signal = getattr(self.strategy, "latest_signal", None)

            if signal:
                print("[Runner] SIGNAL DETECTED:", signal)
                self.execution_engine.send_signal(signal)

        except Exception as e:
            print("[Runner] ERROR:", e)
            logging.exception(e)


# =========================================
# 初期化
# =========================================
def initialize_bot():

    print(">>> INITIALIZE START")

    logger = BotLogger("logs")
    logger.info("Initializing BOT...")

    notifier = TelegramNotifier(TOKEN, CHAT_ID)
    print(">>> Telegram initialized")

    # =========================
    # ExecutionEngine検証（重要）
    # =========================
    print(">>> CHECK ExecutionEngine SIGNATURE")
    print(inspect.getsource(ExecutionEngine.__init__))

    # ExecutionEngine（新設計）
    execution_engine = ExecutionEngine(
        logger=logger,
        notifier=notifier,
        live=False
    )
    print(">>> ExecutionEngine created")

    # TradeCore
    trade_core = TradeCore(
        execution_engine=execution_engine,
        logger=logger
    )
    print(">>> TradeCore created")

    # Strategy
    strategy = FVGStrategy(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )
    print(">>> Strategy created")

    # Runner
    runner = StrategyRunner(strategy, execution_engine)
    print(">>> Runner created")

    # MarketEngine
    market_engine = MarketEngine(
        strategies=[strategy],
        strategy_callback=runner.on_bar
    )
    print(">>> MarketEngine created")

    print(">>> INITIALIZE END")

    return market_engine, logger, notifier


# =========================================
# Main
# =========================================
async def main():

    print(">>> MAIN START")

    market_engine, logger, notifier = initialize_bot()

    print(">>> AFTER INIT")

    logger.info("BOT STARTED")

    try:
        print(">>> BEFORE RUN")
        await market_engine.run_websocket()
        print(">>> AFTER RUN (これは通常出ない)")

    except KeyboardInterrupt:
        print(">>> KEYBOARD INTERRUPT")
        logger.warning("BOT stopped by user")

    except Exception as e:
        print(">>> EXCEPTION:", e)
        logger.error(f"BOT CRASHED: {e}")
        raise


# =========================================
# Entry
# =========================================
if __name__ == "__main__":
    print(">>> ENTRY POINT")
    asyncio.run(main())