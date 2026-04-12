# -*- coding: utf-8 -*-
import asyncio
import logging
import threading
import os
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from Bot.engine.execution_engine import ExecutionEngine
from Bot.core.trade_core import TradeCore
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.engine.market_engine import MarketEngine

from Bot.control.state_manager import StateManager
from Bot.control.bot_state import BotState

from Bot.exchanges.mock_exchange import MockExchange

from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.control.telegram_controller import TelegramController

# =========================
# LOG CONFIG
# =========================
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

# =========================
# CONFIG
# =========================
live_mode = True
ws_url = "wss://stream.binance.com:9443/ws/btcusdt@kline_15m"

# =========================
# TELEGRAM
# =========================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

notifier = None
controller = None

if TOKEN and CHAT_ID:
    notifier = TelegramNotifier(token=TOKEN, chat_id=CHAT_ID)
    controller = TelegramController(notifier)
else:
    logging.warning("Telegram未設定（無効）")


def send_telegram_alert(message: str):
    try:
        if notifier:
            notifier.send(message)
    except Exception as e:
        logging.error(f"Telegram error: {e}")


# =========================
# CORE INIT
# =========================
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

# =========================
# ENTRY NOTIFY
# =========================
def notify_entry(ctx):
    try:
        if not controller:
            return

        controller.notify_entry(
            ctx.trade_type,
            ctx.entry_price,
            ctx.stop_loss_price,
            ctx.take_profit_price
        )
    except Exception as e:
        logging.error(f"ENTRY error: {e}")
        send_telegram_alert(str(e))


strategy_wrapper.on_entry = notify_entry

# =========================
# POSITION MONITOR
# =========================
async def monitor_positions():
    logging.info("monitor_positions STARTED")

    while True:
        try:
            positions = getattr(trade_core, "positions", {})

            if not isinstance(positions, dict):
                await asyncio.sleep(1)
                continue

            for pos in list(positions.values()):
                try:
                    if getattr(pos, "status", None) != "closed":
                        continue

                    if getattr(pos, "notified", False):
                        continue

                    entry = getattr(pos, "entry_price", 0)
                    close = getattr(pos, "close_price", entry)
                    side = getattr(pos, "trade_type", "BUY")

                    pnl = (
                        (close - entry) if side == "BUY"
                        else (entry - close)
                    )

                    if controller:
                        if pnl >= 0:
                            controller.notify_take_profit(pnl)
                        else:
                            controller.notify_stop_loss(abs(pnl))

                    pos.notified = True
                    logging.info(f"[MONITOR] closed position pnl={pnl}")

                except Exception as e:
                    logging.error(f"Position error: {e}")
                    send_telegram_alert(str(e))

        except Exception as e:
            logging.error(f"monitor_positions crash: {e}")
            send_telegram_alert(str(e))

        await asyncio.sleep(1)


# =========================
# FASTAPI APP
# =========================
app = FastAPI(title="TradingAI Unified Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# BOT CONTROL
# =========================
bot_thread = None


def start_bot():
    global bot_thread

    if bot_thread and bot_thread.is_alive():
        return

    async def runner():
        try:
            state_manager.sync_on_startup()

            await asyncio.gather(
                market_engine.run_websocket(),
                monitor_positions()
            )

        except Exception as e:
            logging.error(f"BOT ERROR: {e}")
            send_telegram_alert(str(e))

        finally:
            market_engine._running = False

    bot_thread = threading.Thread(
        target=lambda: asyncio.run(runner()),
        daemon=True
    )
    bot_thread.start()


@app.on_event("startup")
def startup():
    start_bot()


# =========================
# API ENDPOINTS
# =========================
@app.get("/bot_status")
def bot_status():
    try:
        return {
            "running": True,
            "thread_alive": bot_thread.is_alive() if bot_thread else False
        }
    except:
        return {"running": False, "thread_alive": False}


@app.get("/positions")
def positions():
    try:
        return [
            {
                "pair": p.symbol,
                "side": p.trade_type,
                "entry": p.entry_price,
                "current": getattr(p, "close_price", p.entry_price),
                "pnl": 0,
                "size": p.volume
            }
            for p in trade_core.positions.values()
        ]
    except:
        return []


@app.get("/logs")
def logs():
    return []


@app.get("/pnl")
def pnl():
    try:
        return {"pnl": 0}
    except:
        return {"pnl": 0}


@app.get("/price")
def price():
    try:
        return {"price": 0}
    except:
        return {"price": 0}


@app.post("/bot/start")
def start():
    start_bot()
    return {"status": "RUNNING"}


@app.post("/bot/stop")
def stop():
    market_engine._running = False
    return {"status": "STOPPED"}


@app.get("/api/getAssetSummary")
def asset_summary():
    try:
        return {
            "balance": 0,
            "pnl": 0,
            "equity": 0,
            "open_positions": len(trade_core.positions)
        }
    except:
        return {
            "balance": 0,
            "pnl": 0,
            "equity": 0,
            "open_positions": 0
        }