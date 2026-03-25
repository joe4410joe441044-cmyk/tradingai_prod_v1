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
LIVE_MODE = False  # ←最初は必ずFalse


# =========================================
# 初期化
# =========================================
def initialize_bot():

    # --------------------------
    # Logger / Notifier
    # --------------------------
    logger = BotLogger("logs").get_logger()
    notifier = TelegramNotifier(TOKEN, CHAT_ID)

    logger.info("Bot initialization started")

    # --------------------------
    # ExecutionEngine
    # --------------------------
    execution_engine = ExecutionEngine(
        live=LIVE_MODE,
        logger=logger,
        notifier=notifier
    )

    # --------------------------
    # TradeCore
    # --------------------------
    trade_core = TradeCore(
        execution_engine=execution_engine,
        logger=logger
    )

    # --------------------------
    # Strategy
    # --------------------------
    fvg = FVGStrategy(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )

    # --------------------------
    # StrategyWrapper（←重要）
    # --------------------------
    wrapper = StrategyWrapper()
    wrapper.register_strategy(fvg)

    # --------------------------
    # MarketEngine（←ここが中核）
    # --------------------------
    market_engine = MarketEngine(
        strategy_wrapper=wrapper,
        trade_core=trade_core,
        ws_url=WS_URL,
        debug=True
    )

    logger.info("Bot initialization completed")

    return market_engine, logger, notifier


# =========================================
# Main
# =========================================
async def main():
    market_engine, logger, notifier = initialize_bot()

    logger.info("BOT STARTED")

    try:
        await market_engine.run_websocket()

    except KeyboardInterrupt:
        logger.warning("BOT stopped by user")
        notifier.send("BOT stopped (KeyboardInterrupt)")

    except Exception as e:
        logger.error(f"BOT CRASHED: {e}")
        notifier.send(f"BOT crashed: {e}")
        raise


# =========================================
# Entry
# =========================================
if __name__ == "__main__":
    asyncio.run(main())