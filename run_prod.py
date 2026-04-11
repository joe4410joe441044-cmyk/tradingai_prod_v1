# -*- coding: utf-8 -*-
import asyncio
import logging
import threading
import os
import traceback

from Bot.engine.execution_engine import ExecutionEngine
from Bot.core.trade_core import TradeCore
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.engine.market_engine import MarketEngine

# ▼ State Manager
from Bot.control.state_manager import StateManager
from Bot.control.bot_state import BotState

# ✅ 重要：実体を使う（ここが正解）
from Bot.exchanges.mock_exchange import MockExchange

# ▼ Telegram
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.control.telegram_controller import TelegramController
from Bot.control.telegram_listener import TelegramListener

# -------------------------
# ログ設定
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# -------------------------
# 設定
# -------------------------
live_mode = True
ws_url = "wss://stream.binance.com:9443/ws/btcusdt@kline_15m"

# -------------------------
# Telegram
# -------------------------
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

notifier = TelegramNotifier(token=TOKEN, chat_id=CHAT_ID)
controller = TelegramController(notifier)
listener = TelegramListener(token=TOKEN, controller=controller)

threading.Thread(target=listener.start, daemon=True).start()

# -------------------------
# 例外通知
# -------------------------
def send_telegram_alert(message: str):
    try:
        if TOKEN and CHAT_ID:
            notifier.send_message(message)
        else:
            logging.warning("Telegram環境変数未設定: 通知スキップ")
    except Exception as e:
        logging.error(f"Telegram通知失敗: {e}")

# -------------------------
# コア初期化
# -------------------------
exec_engine = ExecutionEngine(live=live_mode)
trade_core = TradeCore(exec_engine)
strategy_wrapper = StrategyWrapper(trade_core)

market_engine = MarketEngine(
    strategy_wrapper=strategy_wrapper,
    trade_core=trade_core,
    ws_url=ws_url
)

# -------------------------
# 🟢 StateManager（重要）
# -------------------------
exchange = MockExchange()   # ← 必ず実体
state = BotState()

state_manager = StateManager(exchange, state)

# -------------------------
# ログ
# -------------------------
logging.info("===================================")
logging.info(f"🚀 BOT START (LIVE MODE = {live_mode})")
logging.info("===================================")

# -------------------------
# ENTRY通知
# -------------------------
def notify_entry(ctx):
    try:
        controller.notify_entry(
            ctx.trade_type,
            ctx.entry_price,
            ctx.stop_loss_price,
            ctx.take_profit_price
        )
    except Exception as e:
        logging.error(f"ENTRY通知エラー: {e}")
        send_telegram_alert(f"⚠️ ENTRY通知エラー: {e}\n{traceback.format_exc()}")

strategy_wrapper.on_entry = notify_entry

# -------------------------
# ポジション監視
# -------------------------
async def monitor_positions():
    logging.info("🔥 monitor_positions STARTED")

    while True:
        for pos in trade_core.positions:
            if pos.status == "closed" and not getattr(pos, "notified", False):
                try:
                    if hasattr(pos, "close_price"):
                        pnl = (
                            (pos.close_price - pos.entry_price)
                            if pos.trade_type == "BUY"
                            else (pos.entry_price - pos.close_price)
                        )

                        if pnl >= 0:
                            controller.notify_take_profit(pnl)
                        else:
                            controller.notify_stop_loss(abs(pnl))
                    else:
                        logging.warning("close_price が無いので通知スキップ")

                except Exception as e:
                    logging.error(f"通知エラー: {e}")
                    send_telegram_alert(f"⚠️ 監視通知エラー: {e}\n{traceback.format_exc()}")

                pos.notified = True
                logging.info("[MONITOR] closed position detected")

        await asyncio.sleep(1)

# -------------------------
# メイン
# -------------------------
async def main():

    try:
        state_manager.sync_on_startup()
    except Exception as e:
        logging.error(f"State復元失敗: {e}")
        send_telegram_alert(f"⚠️ State復元失敗: {e}\n{traceback.format_exc()}")

    tasks = [
        asyncio.create_task(market_engine.run_websocket()),
        asyncio.create_task(monitor_positions())
    ]

    try:
        await asyncio.gather(*tasks)

    except KeyboardInterrupt:
        logging.info("BOT手動停止 (Ctrl+C)")

    except Exception as e:
        logging.exception(f"BOT例外発生: {e}")
        send_telegram_alert(f"⚠️ BOT例外発生: {e}\n{traceback.format_exc()}")
        raise

    finally:
        market_engine._running = False
        logging.info("BOT安全停止完了")

# -------------------------
# 実行
# -------------------------
if __name__ == "__main__":
    asyncio.run(main())