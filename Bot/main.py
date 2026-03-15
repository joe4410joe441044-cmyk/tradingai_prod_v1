# =========================================
# main.py (TradingAI BOT Prod v1)
# =========================================

# =========================================
# Imports
# =========================================
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.core.trade_core import TradeCore
from Bot.engine.market_engine import MarketEngine
from Bot.utils.logger import BotLogger
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.strategies.fvg_strategy import FVGStrategy


# =========================================
# 設定
# =========================================
TOKEN = "8568714005:AAFlzofjXb1cDZyaM93Awq4TFMcBsFKizYc"
CHAT_ID = "1040943428"


# =========================================
# 初期化
# =========================================
def initialize_bot():

    # Logger
    logger = BotLogger("logs")
    logger.info("Initializing BOT...")

    # Telegram Notifier
    notifier = TelegramNotifier(TOKEN, CHAT_ID)
    logger.info("Telegram notifier initialized")

    # ---------------------------------
    # Trade Core
    # ---------------------------------
    trade_core = TradeCore()
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
    # 接続
    # ---------------------------------
    trade_core.strategy_wrapper = strategy_wrapper
    engine.trade_core = trade_core

    logger.info("BOT initialization completed")

    return engine, logger, notifier


# =========================================
# Main
# =========================================
def main():

    engine, logger, notifier = initialize_bot()

    logger.info("BOT STARTED")
    notifier.bot_started()

    try:
        engine.run()

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
