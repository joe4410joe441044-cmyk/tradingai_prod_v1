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
    allow_origins=["*"],  # 本番は制限推奨
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

# ==========================
# 🟢 EXISTING API
# ==========================

@app.get("/logs")
def get_logs():
    return bot.get_logs()


@app.get("/bot_status")
def get_bot_status():
    return {
        "status": "RUNNING" if bot.is_running() else "STOPPED"
    }


@app.get("/positions")
def get_positions():
    return bot.get_positions()


@app.get("/bot/summary")
def get_summary():
    return {
        "positions": bot.get_positions()
    }


@app.get("/pnl")
def get_pnl():
    try:
        return {"pnl": bot.get_pnl()}
    except Exception:
        return {"pnl": 0}


@app.get("/price")
def get_price():
    try:
        return {"price": bot.get_price()}
    except Exception:
        return {"price": 0}


@app.post("/bot/start")
def start_bot():
    bot.start()
    return {"status": "RUNNING"}


@app.post("/bot/stop")
def stop_bot():
    bot.stop()
    return {"status": "STOPPED"}


# ==========================
# 🧠 NEW: Asset Dashboard API
# ==========================
@app.get("/api/getAssetSummary")
def get_asset_summary():
    try:
        positions = bot.get_positions()
        pnl = bot.get_pnl()

        # 安全なbalance取得（存在しない場合に備える）
        balance = getattr(bot, "get_balance", lambda: 0)()

        return {
            "balance": balance,
            "pnl": pnl,
            "equity": balance + pnl,
            "open_positions": len(positions) if positions else 0,
            "risk": getattr(bot, "get_risk", lambda: 0.3)()
        }

    except Exception as e:
        return {
            "balance": 0,
            "pnl": 0,
            "equity": 0,
            "open_positions": 0,
            "risk": 0,
            "error": str(e)
        }