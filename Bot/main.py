# =========================================
# main.py (TradingAI BOT Prod v1)
# =========================================

from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.core.trade_core import TradeCore
from Bot.engine.market_engine import MarketEngine
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.datafeeds.crypto.binance_feed import BinanceDataFeed
from Bot.engine.execution_engine import ExecutionEngine

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
    strategy_wrapper = StrategyWrapper(core=trade_core)
    logger.info("StrategyWrapper initialized")

    # ---------------------------------
    # Strategy 登録
    # ---------------------------------
    fvg_strategy = FVGStrategy(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )

    strategy_wrapper.register_strategy(fvg_strategy)
    logger.info("FVGStrategy registered")

    # ---------------------------------
    # Market Engine
    # ---------------------------------
    engine = MarketEngine(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )

    logger.info("MarketEngine initialized")

    # ---------------------------------
    # Binance DataFeed
    # ---------------------------------
    feed = BinanceDataFeed(
        symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        timeframe="15m",
        market_engine=engine,
        logger=logger
    )

    # ---------------------------------
    # 接続
    # ---------------------------------
    trade_core.strategy_wrapper = strategy_wrapper

    logger.info("BOT initialization completed")

    return feed, logger, notifier


# =========================================
# Main
# =========================================
def main():

    feed, logger, notifier = initialize_bot()

    logger.info("BOT STARTED")
    notifier.bot_started()

    try:

        # WebSocket開始
        feed.start()

        # BOTを停止させないため待機
        while True:
            pass

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
    main()