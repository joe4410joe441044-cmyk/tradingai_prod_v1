# =========================================
# main.py (TradingAI BOT 最終版)
# =========================================

import asyncio

from wrappers.strategy_wrapper import StrategyWrapper
from core.trade_core import TradeCore
from engine.market_engine import MarketEngine
from utils.logger import BotLogger
from utils.telegram_notifier import TelegramNotifier
from strategies.fvg_strategy import FVGStrategy
from engine.execution_engine import ExecutionEngine
# =========================
# 設定
# =========================
WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"

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
    # Execution Engine
    # ---------------------------------
    execution_engine = ExecutionEngine(
        live=False,  # ← 安全のため必ずFalse
        logger=logger,
        notifier=notifier
    )
    logger.info("ExecutionEngine initialized")

    # ---------------------------------
    # Trade Core
    # ---------------------------------
    trade_core = TradeCore(
        execution_engine=execution_engine,
        logger=logger
    )
    logger.info("TradeCore initialized")

    # ---------------------------------
    # Strategy Wrapper
    # ---------------------------------
    strategy_wrapper = StrategyWrapper()
    logger.info("StrategyWrapper initialized")

    # ---------------------------------
    # Strategy
    # ---------------------------------
    fvg_strategy = FVGStrategy(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )

    strategy_wrapper.register_strategy(fvg_strategy)
    logger.info("FVGStrategy registered")

    # ---------------------------------
    # Market Engine（🔥ここが最重要修正）
    # ---------------------------------
    market_engine = MarketEngine(
        ws_url=WS_URL,
        strategy_wrapper=strategy_wrapper,
        execution_engine=execution_engine,  # ← 追加
        debug=True  # ← デバッグON
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