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
# TEST ENTRY
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
        monitor.log_error("TEST_ENTRY", e)
        return {"status": "error", "error": str(e)}


# =========================
# BOT CONTROL
# =========================
@app.post("/api/bot/start")
def start_bot():
    try:
        result = bot.start()

        monitor.log_event("BOT", {"action": "start"})
        monitor.update_dashboard(
            status="RUNNING",
            connection="ONLINE"
        )

        return result

    except Exception as e:
        monitor.log_error("BOT_START", e)
        return {"status": "error", "error": str(e)}


@app.post("/api/bot/stop")
def stop_bot():
    try:
        result = bot.stop()

        monitor.log_event("BOT", {"action": "stop"})
        monitor.update_dashboard(
            status="STOPPED",
            connection="OFFLINE"
        )

        return result

    except Exception as e:
        monitor.log_error("BOT_STOP", e)
        return {"status": "error", "error": str(e)}


# =========================
# SUMMARY（🔥 完全修正）
# =========================
@app.get("/api/bot/summary")
def get_bot_summary():
    try:
        # 🔥 唯一の表示ソース
        data = monitor.get_dashboard_data()

        # 🔥 状態だけ別管理
        data["status"] = "RUNNING" if bot.is_running() else "STOPPED"

        return data

    except Exception as e:
        monitor.log_error("SUMMARY_API", e)

        return {
            "status": "ERROR",
            "price": 0,
            "balance": 0,
            "pnl": 0,
            "realized_pnl": 0,
            "positions": 0,
            "logs": [str(e)],
            "connection": "ERROR"
        }