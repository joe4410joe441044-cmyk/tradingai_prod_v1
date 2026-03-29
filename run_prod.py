# -*- coding: utf-8 -*-
import asyncio
import logging
import threading

from Bot.engine.execution_engine import ExecutionEngine
from Bot.core.trade_core import TradeCore
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.engine.market_engine import MarketEngine
from Bot.wrappers.test_signal_generator import TestSignalGenerator

# ▼ Telegram追加
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.control.telegram_controller import TelegramController
from Bot.control.telegram_listener import TelegramListener


# -------------------------
# ログ設定
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# -------------------------
# 設定
# -------------------------
live_mode = False
ws_url = "wss://stream.binance.com:9443/ws/btcusdt@kline_15m"

# -------------------------
# Telegram設定
# -------------------------
TOKEN = "8568714005:AAFlzofjXb1cDZyaM93Awq4TFMcBsFKizYc"
CHAT_ID = "1040943428"

notifier = TelegramNotifier(token=TOKEN, chat_id=CHAT_ID)
controller = TelegramController(notifier)
listener = TelegramListener(token=TOKEN, controller=controller)

# Listener起動
threading.Thread(target=listener.start, daemon=True).start()

# -------------------------
# 初期化
# -------------------------
exec_engine = ExecutionEngine(live=live_mode)
trade_core = TradeCore(exec_engine)

strategy_wrapper = StrategyWrapper(trade_core)

market_engine = MarketEngine(
    strategy_wrapper=strategy_wrapper,
    trade_core=trade_core,
    ws_url=ws_url
)

test_signal_generator = None
if not live_mode:
    test_signal_generator = TestSignalGenerator(strategy_wrapper, interval_sec=10)

# -------------------------
# ENTRY通知フック
# -------------------------
def notify_entry(ctx):
    controller.notify_entry(
        ctx.trade_type,
        ctx.entry_price,
        ctx.stop_loss_price,
        ctx.take_profit_price
    )

strategy_wrapper.on_entry = notify_entry

# -------------------------
# TP / SL 通知監視
# -------------------------
async def monitor_positions():
    print("🔥 monitor_positions STARTED")

    while True:
        print("[MONITOR] running...")

        for pos in trade_core.positions:
            if pos.status == "closed" and not hasattr(pos, "notified"):
                try:
                    if hasattr(pos, "close_price"):

                        if pos.trade_type == "BUY":
                            pnl = pos.close_price - pos.entry_price
                        else:
                            pnl = pos.entry_price - pos.close_price

                        if pnl >= 0:
                            controller.notify_take_profit(pnl)
                        else:
                            controller.notify_stop_loss(abs(pnl))
                    else:
                        logging.warning("close_price が無いので通知スキップ")

                except Exception as e:
                    logging.error(f"通知エラー: {e}")

                pos.notified = True
                print("[MONITOR] detected closed position")

        await asyncio.sleep(1)


# -------------------------
# メイン
# -------------------------
async def main():
    tasks = [
        asyncio.create_task(market_engine.run_websocket()),
        asyncio.create_task(monitor_positions())
    ]

    if test_signal_generator:
        tasks.append(asyncio.create_task(test_signal_generator.run()))

    try:
        await asyncio.gather(*tasks)

    except KeyboardInterrupt:
        logging.info("BOT手動停止 (Ctrl+C)")

    except Exception as e:
        logging.exception(f"BOT例外発生: {e}")

    finally:
        if test_signal_generator:
            test_signal_generator.stop()

        market_engine._running = False
        logging.info("BOT安全停止完了")


# -------------------------
# 実行
# -------------------------
if __name__ == "__main__":
    asyncio.run(main())