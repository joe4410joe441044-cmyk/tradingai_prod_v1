import time
import pandas as pd
from Bot.engine.market_engine import MarketEngine
from Bot.core.trade_core import TradeCore
from Bot.strategies.strategy_wrapper import StrategyWrapper
from Bot.strategies.pro_fvg_strategy import ProFVGStrategy
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.utils.logger import BotLogger

# =====================================================
# Telegram通知 + Logger
# =====================================================
telegram = TelegramNotifier(
    token="YOUR_BOT_TOKEN",
    chat_id="YOUR_CHAT_ID"
)
telegram.bot_started()

logger = BotLogger(log_file="logs/bot.log")
logger.info("BOT 起動")

# =====================================================
# BOT起動
# =====================================================
def main():
    trade_core = TradeCore(initial_balance=10000)
    market_engine = MarketEngine(start_price=2000, trade_core=trade_core)
    wrapper = StrategyWrapper(core=trade_core)

    strategy = ProFVGStrategy()
    wrapper.register_strategy(strategy)

    logger.info("BOT監視開始")
    print("=== BOT監視開始 ===")

    while True:
        # ----------------------------
        # Tick生成＋OHLC更新
        # ----------------------------
        market_data = market_engine.get_market_data()

        # ----------------------------
        # 戦略実行 → TradeCoreへシグナル送信
        # ----------------------------
        wrapper.on_bar(market_data)

        # ----------------------------
        # 新規ポジション通知
        # ----------------------------
        for pos in trade_core.positions[-1:]:
            telegram.entry_notification(pos)
            logger.info(f"ENTRY | {pos.trade_type} | Entry: {pos.entry_price} | SL: {pos.sl} | TP: {pos.tp}")

        # ----------------------------
        # 日次・週次DDチェック（TradeCore内部で自動）
        # ----------------------------

        time.sleep(1)

if __name__ == "__main__":
    main()