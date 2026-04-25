# -*- coding: utf-8 -*-
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.bot_manager import BotManager
from monitoring.system_monitor import SystemMonitor


# =========================
# APP
# =========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# INIT
# =========================
logging.basicConfig(level=logging.INFO)

monitor = SystemMonitor()
bot = BotManager(monitor=monitor)


# =========================
# STARTUP
# =========================
@app.on_event("startup")
async def startup():
    logging.info("🚀 Startup begin")
    monitor.log_event("SYSTEM", {"msg": "backend started"})
    logging.info("✅ Startup complete")


# =========================
# TEST ENTRY（ここに移動）
# =========================
@app.post("/api/bot/test_entry")
def test_entry():
    try:
        engine = bot.get_engine()

        pos = engine.execute_order({
            "symbol": "BTCUSDT",
            "side": "BUY",
            "qty": 0.001
        })

        return {"status": "ok", "position": pos}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# =========================
# BOT CONTROL
# =========================
@app.post("/api/bot/start")
def start_bot():
    try:
        result = bot.start()
        monitor.log_event("BOT", {"action": "start"})
        monitor.update_dashboard(status="RUNNING", connection="ONLINE")
        return result
    except Exception as e:
        monitor.log_error("BOT_START", e)
        return {"status": "error", "error": str(e)}


@app.post("/api/bot/stop")
def stop_bot():
    try:
        result = bot.stop()
        monitor.log_event("BOT", {"action": "stop"})
        monitor.update_dashboard(status="STOPPED", connection="OFFLINE")
        return result
    except Exception as e:
        monitor.log_error("BOT_STOP", e)
        return {"status": "error", "error": str(e)}


# =========================
# SUMMARY
# =========================
@app.get("/api/bot/summary")
def get_bot_summary():
    try:
        data = monitor.get_dashboard_data()

        return {
            "status": "RUNNING" if bot.is_running() else "STOPPED",
            "price": float(data.get("price", 0)),
            "balance": float(data.get("balance", 0)),
            "pnl": float(data.get("pnl", 0)),
            "realized_pnl": float(data.get("realized_pnl", 0)),
            "positions": data.get("positions", []),
            "logs": data.get("logs", [])[-50:],
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
            "realized_pnl": 0,
            "positions": [],
            "logs": [str(e)],
            "connection": "ERROR"
        }