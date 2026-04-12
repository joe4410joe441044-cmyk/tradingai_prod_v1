# -*- coding: utf-8 -*-
import asyncio
import logging
import os
import traceback
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import uvicorn

from Bot.engine.execution_engine import ExecutionEngine
from Bot.core.trade_core import TradeCore
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.engine.market_engine import MarketEngine

from Bot.control.state_manager import StateManager
from Bot.control.bot_state import BotState
from Bot.exchanges.mock_exchange import MockExchange
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.control.telegram_controller import TelegramController

# -------------------------
# FastAPI統合
# -------------------------
app = FastAPI(title="TradingAI Unified Backend")

# -------------------------
# ログ
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
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

notifier = None
controller = None

if TOKEN and CHAT_ID:
    notifier = TelegramNotifier(token=TOKEN, chat_id=CHAT_ID)
    controller = TelegramController(notifier)
else:
    logging.warning("Telegram未設定")

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

exchange = MockExchange()
state = BotState()
state_manager = StateManager(exchange, state)

# -------------------------
# Bot制御
# -------------------------
bot_running = False


@app.on_event("startup")
async def startup():
    global bot_running
    try:
        state_manager.sync_on_startup()
        bot_running = True

        # 非同期タスク起動
        asyncio.create_task(market_engine.run_websocket())
        asyncio.create_task(monitor_positions())

        logging.info("BOT STARTED")

    except Exception as e:
        logging.error(f"startup error: {e}")
        logging.error(traceback.format_exc())


# -------------------------
# API
# -------------------------
@app.get("/bot_status")
def bot_status():
    try:
        return {
            "status": "RUNNING" if bot_running else "STOPPED"
        }
    except Exception as e:
        return {"status": "ERROR", "detail": str(e)}


@app.get("/positions")
def positions():
    try:
        pos_list = []

        positions = trade_core.positions

        # dict / list 両対応
        if isinstance(positions, dict):
            positions = positions.values()

        for p in positions:
            pos_list.append({
                "pair": getattr(p, "symbol", "UNKNOWN"),
                "side": getattr(p, "trade_type", "UNKNOWN"),
                "entry": getattr(p, "entry_price", 0),
                "current": getattr(p, "close_price", getattr(p, "entry_price", 0)),
                "size": getattr(p, "volume", 0)
            })

        return pos_list

    except Exception as e:
        return {"error": str(e), "data": []}


@app.get("/logs")
def logs():
    return {"message": "logs not migrated yet"}


# -------------------------
# monitor
# -------------------------
async def monitor_positions():
    while True:
        try:
            positions = trade_core.positions

            if isinstance(positions, dict):
                positions = positions.values()

            for pos in positions:
                if getattr(pos, "status", None) == "closed" and not getattr(pos, "notified", False):
                    pos.notified = True

            await asyncio.sleep(1)

        except Exception as e:
            logging.error(f"monitor error: {e}")
            logging.error(traceback.format_exc())


# -------------------------
# 🔥 React配信（最重要）
# -------------------------
app.mount(
    "/",
    StaticFiles(directory="react_dashboard/dist", html=True),
    name="react"
)


# -------------------------
# main entry
# -------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)