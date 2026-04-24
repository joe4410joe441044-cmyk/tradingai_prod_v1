# -*- coding: utf-8 -*-

from fastapi import FastAPI, WebSocket
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import logging
import asyncio
import threading
from contextlib import asynccontextmanager
from starlette.websockets import WebSocketDisconnect

from backend.bot_manager import BotManager
from monitoring.system_monitor import SystemMonitor

# =========================
# BOT IMPORT
# =========================
from Bot.engine.market_engine import MarketEngine
from Bot.core.trade_core import TradeCore
from Bot.strategies.fvg_strategy import FVGStrategy
from Bot.engine.execution_engine import ExecutionEngine
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.utils.logger import BotLogger

# =========================
# ENV
# =========================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# =========================
# CONFIG
# =========================
WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
TOKEN = "YOUR_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"
LIVE_MODE = False

# =========================
# CORE
# =========================
bot = BotManager()
monitor = SystemMonitor()

# =========================
# BOT INITIALIZE
# =========================
def initialize_bot():

    logger = BotLogger("logs").get_logger()
    notifier = TelegramNotifier(TOKEN, CHAT_ID)

    execution_engine = ExecutionEngine(
        live=LIVE_MODE,
        logger=logger,
        notifier=notifier
    )

    trade_core = TradeCore(
        execution_engine=execution_engine,
        logger=logger
    )

    execution_engine.trade_core = trade_core

    fvg = FVGStrategy(
        trade_core=trade_core,
        logger=logger,
        notifier=notifier
    )

    wrapper = StrategyWrapper(trade_core)
    wrapper.register_strategy(fvg)

    market_engine = MarketEngine(
        strategy_wrapper=wrapper,
        trade_core=trade_core,
        ws_url=WS_URL,
        debug=False
    )

    return market_engine

# =========================
# BOT RUNNER
# =========================
async def run_bot():

    print("🔥 BOT LOOP START")

    while True:
        try:
            market_engine = initialize_bot()

            if hasattr(market_engine, "set_monitor"):
                market_engine.set_monitor(monitor)

            print("🔥 WS START")
            logging.info("🚀 BOT STARTED")

            await market_engine.run_websocket()

        except Exception as e:
            logging.error(f"[BOT ERROR] restarting: {e}")
            await asyncio.sleep(3)

# =========================
# LIFESPAN
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):

    logging.info("🚀 Startup begin")

    monitor.set_loop(asyncio.get_running_loop())
    monitor.update_status("backend", True)

    logging.info("✅ Startup complete")

    yield

    logging.info("🛑 Shutdown complete")

# =========================
# APP
# =========================
app = FastAPI(title="TradingAI Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# API
# =========================
@app.get("/api/monitor/status")
def monitor_status():
    return monitor.health_check()

@app.get("/api/monitor/logs")
def monitor_logs():
    return {"logs": monitor.get_logs()}

# =========================
# BOT SUMMARY
# =========================
@app.get("/api/bot/summary")
def get_bot_summary():
    try:
        if hasattr(monitor, "get_dashboard_data"):
            data = monitor.get_dashboard_data()
        else:
            data = {}

        def safe(v):
            try:
                return float(v)
            except:
                return 0

        return {
            "status": data.get("status", "RUNNING"),
            "price": safe(data.get("price", 0)),
            "balance": safe(data.get("balance", 0)),
            "pnl": safe(data.get("pnl", 0)),
            "positions": data.get("positions", []),
            "logs": data.get("logs", [])[-20:],
            "connection": data.get("connection", "ONLINE")
        }

    except Exception as e:
        return {
            "status": "ERROR",
            "price": 0,
            "balance": 0,
            "pnl": 0,
            "positions": [],
            "logs": [str(e)],
            "connection": "ERROR"
        }

# =========================
# BOT CONTROL
# =========================
@app.post("/api/bot/start")
async def start_bot():

    def start():
        print("🔥 BOT THREAD START")
        asyncio.run(run_bot())

    threading.Thread(target=start, daemon=True).start()

    monitor.update_status("trade_core", True)

    return {"status": "started"}


@app.post("/api/bot/stop")
def stop_bot():
    return {"status": "not implemented yet"}

# =========================
# WEBSOCKET
# =========================
@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):

    await websocket.accept()
    monitor.register_ws(websocket)
    monitor.update_status("websocket", True)

    logging.info("🔥 WS CONNECTED")

    try:
        while True:
            await asyncio.sleep(10)

    except WebSocketDisconnect:
        monitor.unregister_ws(websocket)

        if len(monitor.ws_clients) == 0:
            monitor.update_status("websocket", False)

        logging.info("❌ WS DISCONNECTED")

    except Exception as e:
        monitor.unregister_ws(websocket)

        if len(monitor.ws_clients) == 0:
            monitor.update_status("websocket", False)

        logging.error(f"⚠ WS ERROR: {e}")

# =========================
# ROOT
# =========================
@app.get("/")
def root():
    return {"status": "TradingAI running"}