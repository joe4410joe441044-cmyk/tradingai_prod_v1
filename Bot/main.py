# -*- coding: utf-8 -*-
import asyncio
import logging
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
LIVE_MODE = True  # False: DRY_RUN / True: 実弾（現状は安全）

# =========================================
# Strategy Runner
# =========================================
class StrategyRunner:
    """
    Strategy の on_bar 呼び出しと ExecutionEngine への Signal 送信を管理
    """
    def __init__(self, strategy, trade_core, execution_engine):
        self.strategy = strategy
        self.trade_core = trade_core
        self.execution_engine = execution_engine

    async def on_bar(self, market_data):
        try:
            # Strategy on_bar
            result = self.strategy.on_bar(market_data)
            if asyncio.iscoroutine(result):
                await result

            # 最新 Signal を取得
            signal = getattr(self.strategy, "latest_signal", None)
            if signal:
                # TradeCore で建玉作成 → ExecutionEngine 発注
                self.trade_core.try_enter(signal)

        except Exception as e:
            logging.exception(f"Error in StrategyRunner: {e}")

# =========================================
# 初期化
# =========================================
def initialize_bot():
    # ロガー・通知
    logger = BotLogger("logs").get_logger()
    notifier = TelegramNotifier(TOKEN, CHAT_ID)
    logger.info("Bot initialization started")

    # ExecutionEngine
    execution_engine = ExecutionEngine(
        live=LIVE_MODE,
        logger=logger,
        notifier=notifier
    )

    # TradeCore
    trade_core = TradeCore(
        execution_engine=execution_engine,
        logger=logger
    )

    # Strategy
    strategy = FVGStrategy(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )

    # Runner（MarketEngine に渡さず内部で必要な場合のみ使用）
    runner = StrategyRunner(strategy, trade_core, execution_engine)

    # MarketEngine
    market_engine = MarketEngine(
        ws_url=WS_URL,
        strategies=[strategy]  # strategy_runner は削除
    )

    logger.info("Bot initialization completed")
    return market_engine, logger, notifier

# =========================================
# Main
# =========================================
async def main():
    market_engine, logger, notifier = initialize_bot()
    logger.info("BOT STARTED")
    notifier.bot_started()

    try:
        await market_engine.run_websocket()  # WebSocketからSignalを取得して自動フロー
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