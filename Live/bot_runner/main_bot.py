# =========================================
# main.py (TradingAI BOT 本番接続版)
# =========================================

import asyncio

from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.core.trade_core import TradeCore
from Bot.engine.market_engine import MarketEngine
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.engine.execution_engine import ExecutionEngine

# =========================
# 設定
# =========================
WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_15m"

TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"


# =========================================
# 初期化
# =========================================
def initialize_bot():

    logger = BotLogger("logs")
    logger.info("Initializing BOT...")

    notifier = TelegramNotifier(TOKEN, CHAT_ID)
    logger.info("Telegram notifier initialized")

    # ---------------------------------
    # Execution Engine（最優先）
    # ---------------------------------
    execution_engine = ExecutionEngine(
        live=False,  # ← 最初は必ずFalse（超重要）
        logger=logger,
        notifier=notifier
    )
    logger.info("ExecutionEngine initialized")

    # ---------------------------------
    # Trade Core（将来使用）
    # ---------------------------------
    trade_core = TradeCore(
        execution_engine=execution_engine,
        logger=logger
    )
    logger.info("TradeCore initialized")

    # ---------------------------------
    # Strategy（FVG本番）
    # ---------------------------------
    fvg_strategy = FVGStrategy(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )

    # ---------------------------------
    # Strategy Wrapper（signal返却型）
    # ---------------------------------
    strategy_wrapper = StrategyWrapper()
    strategy_wrapper.register_strategy(fvg_strategy)

    logger.info("FVGStrategy registered")

    # ---------------------------------
    # Market Engine（Execution接続）
    # ---------------------------------
    market_engine = MarketEngine(
        ws_url=WS_URL,
        strategy_wrapper=strategy_wrapper,
        execution_engine=execution_engine,  # 🔥 これが今回の核心
        debug=True
    )

    logger.info("MarketEngine initialized")
    logger.info("BOT initialization completed")

    return market_engine, logger, notifier


# =========================================
# Main（非同期）
# =========================================
async def main():

    market_engine, logger, notifier = initialize_bot()

    logger.info("BOT STARTED")
    notifier.bot_started()

    try:
        await market_engine.connect()

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