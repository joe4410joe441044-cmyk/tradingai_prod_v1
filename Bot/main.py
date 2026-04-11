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
# 🧠 AI FASTAPI INJECTION
# =========================
from backend.api_ai import set_trade_core


WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"
LIVE_MODE = False


# =========================
# INIT
# =========================
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

    # =========================
    # 🧠 STEP4-2 FIX（重要）
    # FastAPIへTradeCoreを注入
    # =========================
    set_trade_core(trade_core)

    # =========================
    # 🧠 STEP5 FIX（追加）
    # ExecutionEngineへTradeCore接続（重要）
    # =========================
    execution_engine.trade_core = trade_core

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
        debug=False
    )

    logger.info("Bot initialization completed")

    return market_engine


# =========================
# MONITOR（改善版）
# =========================
async def monitor_positions(trade_core, logger):

    logger.info("🔥 MONITOR STARTED")

    while True:
        try:
            open_positions = [
                p for p in trade_core.positions.values()
                if p.status == "OPEN"
            ]

            logger.info(f"[MONITOR] open_positions={len(open_positions)}")

            # 異常検知（簡易）
            if len(open_positions) > 5:
                logger.warning("⚠️ TOO MANY POSITIONS!")

        except Exception as e:
            logger.error(f"[MONITOR ERROR] {e}")

        await asyncio.sleep(5)


# =========================
# MAIN LOOP（耐障害化）
# =========================
async def main():

    logger = None  # ← FATALエラー防止用

    while True:
        try:
            market_engine = initialize_bot()

            trade_core = market_engine.trade_core
            logger = market_engine.logger

            logger.info("🚀 BOT STARTED")

            tasks = [
                asyncio.create_task(market_engine.run_websocket()),
                asyncio.create_task(monitor_positions(trade_core, logger))
            ]

            await asyncio.gather(*tasks)

        except Exception as e:
            if logger:
                logger.error(f"[FATAL ERROR] restarting bot: {e}")
            else:
                print(f"[FATAL ERROR] restarting bot: {e}")

            await asyncio.sleep(3)


# =========================
# ENTRY
# =========================
if __name__ == "__main__":
    asyncio.run(main())