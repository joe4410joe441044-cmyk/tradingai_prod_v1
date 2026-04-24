# -*- coding: utf-8 -*-

from fastapi import FastAPI, Request, WebSocket
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse

import os
import logging
import threading
from contextlib import asynccontextmanager

from starlette.websockets import WebSocketDisconnect

from backend.bot_manager import BotManager
from backend.services.summary_builder import build_summary
from backend.websocket_manager import WebSocketManager
from backend.ws.price_ws import price_ws_handler

# =========================
# MONITORING IMPORT ★追加
# =========================
from monitoring.system_monitor import SystemMonitor

# =========================
# ENV LOAD
# =========================
load_dotenv()

# =========================
# LOGGING
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# =========================
# CORE OBJECTS
# =========================
bot = BotManager()
ws_manager = WebSocketManager()

# ★追加：monitor global
monitor = SystemMonitor()

# =========================
# LIFESPAN
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):

    logging.info("🚀 TradingAI startup sequence begin")

    env = os.getenv("ENV", "dev")
    logging.info(f"ENV = {env}")

    logging.info(f"BYBIT KEY LOADED: {bool(os.getenv('BYBIT_API_KEY'))}")

    # =========================
    # WebSocket連携
    # =========================
    if hasattr(bot, "engines"):
        for eng in bot.engines.values():
            eng.ws_manager = ws_manager

    # =========================
    # 🔥 MONITORING INJECTION（ここが重要）
    # =========================
    try:
        # BotManager → coreアクセス前提
        if hasattr(bot, "trade_core") and bot.trade_core:
            bot.trade_core.set_monitor(monitor)

        if hasattr(bot, "risk_manager") and bot.risk_manager:
            bot.risk_manager.set_monitor(monitor)

        if hasattr(bot, "execution_engine") and bot.execution_engine:
            bot.execution_engine.set_monitor(monitor)

        monitor.update_status("backend", True)
        logging.info("✅ SystemMonitor injected")

    except Exception as e:
        logging.error(f"Monitor injection failed: {e}")

    # =========================
    # React build確認
    # =========================
    DIST_PATH = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "react_dashboard", "dist")
    )

    if env == "prod":
        if not os.path.exists(DIST_PATH):
            raise RuntimeError(f"DIST not found: {DIST_PATH}")
        logging.info("✅ React build OK")

    logging.info("✅ Startup complete")

    yield

    logging.info("🛑 Shutdown complete")


# =========================
# APP INIT
# =========================
app = FastAPI(title="TradingAI Backend", lifespan=lifespan)

# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://35.194.104.74",
        "http://35.194.104.74:3000",
        "http://localhost",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# PATH
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DIST_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "..", "react_dashboard", "dist")
)

ASSETS_PATH = os.path.join(DIST_PATH, "assets")

# =========================
# ROUTERS
# =========================
from backend.api.risk_router import router as risk_router
app.include_router(risk_router)

# =========================
# BOT CONTROL
# =========================
@app.post("/api/bot/start")
def start_bot():
    if bot.is_running():
        return {"status": "already running"}

    thread = threading.Thread(target=bot.start, daemon=True)
    thread.start()

    return {"status": "started"}


@app.post("/api/bot/stop")
def stop_bot():
    bot.stop()
    return {"status": "stopped"}


# =========================
# EXCHANGE SWITCH
# =========================
@app.post("/api/set-exchange")
def set_exchange(req: dict):
    exchange = req.get("exchange")

    if not exchange:
        return {"error": "exchange not provided"}

    bot.set_exchange(exchange)
    return {"status": "ok", "exchange": exchange}


# =========================
# API
# =========================
@app.get("/api/bot/status")
def bot_status():
    return bot.get_status()


@app.get("/api/bot/summary")
def bot_summary():
    return build_summary(bot)


@app.get("/api/balance")
def balance():
    return {"balance": bot.get_balance()}


@app.get("/api/positions")
def positions():
    return {"positions": bot.get_positions()}


@app.get("/api/logs")
def logs():
    return {"logs": bot.get_logs()}


@app.get("/api/price")
def price():
    return {"price": bot.get_price()}


@app.get("/api/pnl")
def pnl():
    return {"pnl": bot.get_pnl()}


# =========================
# MONITOR API（追加）
# =========================
@app.get("/api/monitor/status")
def monitor_status():
    return monitor.health_check()


@app.get("/api/monitor/integration")
def monitor_integration():
    return monitor.integration_check()


@app.get("/api/monitor/logs")
def monitor_logs():
    return {"logs": monitor.get_logs()}


# =========================
# WEBSOCKET ① PRICE
# =========================
@app.websocket("/ws/price")
async def ws_price(websocket: WebSocket):
    await price_ws_handler(websocket)


# =========================
# WEBSOCKET ② MARKET INPUT
# =========================
@app.websocket("/ws/market")
async def ws_market(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_json()

            symbol = data.get("symbol")
            price = data.get("price")

            if symbol and price is not None:
                bot.set_price(symbol, float(price))

    except WebSocketDisconnect:
        logging.info("WS market disconnected")

    except Exception as e:
        logging.warning(f"WS market error: {e}")


# =========================
# WEBSOCKET ③ EVENTS
# =========================
@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await ws_manager.connect(websocket)

    try:
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


# =========================
# ERROR HANDLER
# =========================
@app.exception_handler(Exception)
def error_handler(request: Request, exc: Exception):
    logging.error(str(exc))
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)}
    )


# =========================
# SPA
# =========================
def serve_index():
    index_path = os.path.join(DIST_PATH, "index.html")

    if not os.path.exists(index_path):
        return JSONResponse(status_code=500, content={"error": "no build"})

    with open(index_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.get("/")
def root():
    return serve_index()


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith(("api", "ws")):
        return JSONResponse(status_code=404, content={"error": "not found"})
    return serve_index()


# =========================
# STATIC
# =========================
if os.path.exists(ASSETS_PATH):
    app.mount("/assets", StaticFiles(directory=ASSETS_PATH), name="assets")


# =========================
# FAVICON
# =========================
@app.get("/favicon.ico")
def favicon():
    path = os.path.join(DIST_PATH, "favicon.svg")
    if os.path.exists(path):
        return FileResponse(path)
    return JSONResponse(status_code=204, content={})