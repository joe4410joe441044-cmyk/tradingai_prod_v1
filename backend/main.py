# H:\マイドライブ\tradingai_prod_v1\backend\main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.bot_manager import BotManager

# --------------------------
# FastAPI
# --------------------------
app = FastAPI(title="TradingAI Backend")

# --------------------------
# CORS（本番対応）
# --------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番は後で制限OK
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------
# BotManager
# --------------------------
bot = BotManager()

# --------------------------
# Startup（安全起動）
# --------------------------
@app.on_event("startup")
def startup_event():
    bot.start()

# --------------------------
# API
# --------------------------

# --------------------------
# Logs
# --------------------------
@app.get("/logs")
def get_logs():
    return bot.get_logs()


# --------------------------
# Bot Status（React統一）
# --------------------------
@app.get("/bot_status")
def get_bot_status():
    return {
        "status": "RUNNING" if bot.is_running() else "STOPPED"
    }


# --------------------------
# Positions（直接）
# --------------------------
@app.get("/positions")
def get_positions():
    return bot.get_positions()


# --------------------------
# Summary（React用統合）
# --------------------------
@app.get("/bot/summary")
def get_summary():
    return {
        "positions": bot.get_positions()
    }


# --------------------------
# PnL（重要）
# --------------------------
@app.get("/pnl")
def get_pnl():
    try:
        return {
            "pnl": bot.get_pnl()
        }
    except Exception:
        return {
            "pnl": 0
        }


# --------------------------
# Price（重要）
# --------------------------
@app.get("/price")
def get_price():
    try:
        return {
            "price": bot.get_price()
        }
    except Exception:
        return {
            "price": 0
        }


# --------------------------
# Start Bot
# --------------------------
@app.post("/bot/start")
def start_bot():
    bot.start()
    return {
        "status": "RUNNING"
    }


# --------------------------
# Stop Bot
# --------------------------
@app.post("/bot/stop")
def stop_bot():
    bot.stop()
    return {
        "status": "STOPPED"
    }