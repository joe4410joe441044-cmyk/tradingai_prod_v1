# -*- coding: utf-8 -*-

from fastapi import FastAPI, WebSocket
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import logging
import asyncio
from contextlib import asynccontextmanager
from starlette.websockets import WebSocketDisconnect

from backend.bot_manager import BotManager
from monitoring.system_monitor import SystemMonitor

# =========================
# ENV
# =========================
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# =========================
# CORE
# =========================
monitor = SystemMonitor()
bot = BotManager(monitor=monitor)

# =========================
# LIFESPAN
# =========================
@asynccontextmanager
async def lifespan(app: FastAPI):

    logging.info("🚀 Startup begin")

    try:
        loop = asyncio.get_running_loop()
        monitor.set_loop(loop)

        monitor.update_status("backend", True)
        monitor.log_event("SYSTEM", {"msg": "backend started"})

        logging.info("✅ Startup complete")

    except Exception as e:
        monitor.log_error("STARTUP", e)

    yield

    # =========================
    # SHUTDOWN（重要）
    # =========================
    logging.info("🛑 Shutdown begin")

    try:
        bot.stop()

        monitor.update_status("backend", False)
        monitor.log_event("SYSTEM", {"msg": "backend stopped"})

    except Exception as e:
        monitor.log_error("SHUTDOWN", e)

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
# MONITOR API
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
        data = monitor.get_dashboard_data()

        def safe(v):
            try:
                return float(v)
            except Exception:
                return 0

        return {
            "status": "RUNNING" if bot.is_running() else "STOPPED",
            "price": safe(data.get("price", 0)),
            "balance": safe(data.get("balance", 0)),
            "pnl": safe(data.get("pnl", 0)),
            "positions": data.get("positions", []),
            "logs": data.get("logs", [])[-20:],
            "connection": data.get(
                "connection",
                "ONLINE" if bot.is_running() else "OFFLINE"
            )
        }

    except Exception as e:
        monitor.log_error("SUMMARY_API", e)
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
def start_bot():
    try:
        result = bot.start()
        monitor.update_status("trade_core", True)
        monitor.log_event("BOT", {"action": "start"})
        return result
    except Exception as e:
        monitor.log_error("BOT_START", e)
        return {"status": "error"}


@app.post("/api/bot/stop")
def stop_bot():
    try:
        result = bot.stop()
        monitor.update_status("trade_core", False)
        monitor.log_event("BOT", {"action": "stop"})
        return result
    except Exception as e:
        monitor.log_error("BOT_STOP", e)
        return {"status": "error"}


# =========================
# WEBSOCKET（強化版）
# =========================
@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):

    await websocket.accept()
    monitor.register_ws(websocket)
    monitor.update_status("websocket", True)

    logging.info("🔥 WS CONNECTED")

    # 初回フルデータ
    try:
        data = monitor.get_dashboard_data()
        await websocket.send_json({
            "type": "dashboard_full",
            "data": data
        })
    except Exception as e:
        monitor.log_error("WS_INIT", e)

    try:
        while True:
            try:
                # ping（接続維持）
                await websocket.send_json({"type": "ping"})
                await asyncio.sleep(20)

            except Exception as e:
                monitor.log_error("WS_LOOP", e)
                break

    except WebSocketDisconnect:
        logging.info("❌ WS DISCONNECTED")

    finally:
        monitor.unregister_ws(websocket)

        if len(monitor.ws_clients) == 0:
            monitor.update_status("websocket", False)


# =========================
# ROOT
# =========================
@app.get("/")
def root():
    return {"status": "TradingAI running"}