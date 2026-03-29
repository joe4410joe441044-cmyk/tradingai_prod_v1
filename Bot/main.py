# -*- coding: utf-8 -*-
import asyncio

from Bot.engine.market_engine import MarketEngine
from Bot.core.trade_core import TradeCore
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.engine.execution_engine import ExecutionEngine
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.utils.logger import BotLogger


# =========================
# 設定
# =========================
WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"
LIVE_MODE = False


# =========================================
# 初期化
# =========================================
def initialize_bot():

    logger = BotLogger("logs").get_logger()
    notifier = TelegramNotifier(TOKEN, CHAT_ID)

    logger.info("Bot initialization started")

    execution_engine = ExecutionEngine(
        live=LIVE_MODE,
        logger=logger,
        notifier=notifier
    )

    trade_core = TradeCore(
        execution_engine=execution_engine,
        logger=logger
    )

    fvg = FVGStrategy(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )

    wrapper = StrategyWrapper()
    wrapper.register_strategy(fvg)

    market_engine = MarketEngine(
        strategy_wrapper=wrapper,
        trade_core=trade_core,
        ws_url=WS_URL,
        debug=True
    )

    logger.info("Bot initialization completed")

    return market_engine


# =========================================
# monitor
# =========================================
async def monitor_positions(trade_core, logger):
    logger.info("🔥 monitor_positions STARTED")

    while True:
        logger.info("[MONITOR] running...")
        await asyncio.sleep(1)


# =========================================
# Main
# =========================================
async def main():
    market_engine = initialize_bot()

    trade_core = market_engine.trade_core
    logger = market_engine.logger

    logger.info("BOT STARTED")

    tasks = [
        asyncio.create_task(market_engine.run_websocket()),
        asyncio.create_task(monitor_positions(trade_core, logger))
    ]

    await asyncio.gather(*tasks)


# =========================================
# Entry
# =========================================
if __name__ == "__main__":
    asyncio.run(main())