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
    allow_origins=[
        "http://34.85.66.137",
        "http://localhost",
        "http://localhost:3000"
    ],
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
    try:
        bot.start()
    except Exception as e:
        print(f"[STARTUP ERROR] {e}")


# ==========================
# 🟢 BASIC API
# ==========================
@app.get("/logs")
def get_logs():
    try:
        return bot.get_logs()
    except Exception as e:
        return {"logs": [], "error": str(e)}


# ==========================
# 🔥 SAFE BOT STATUS（重要）
# ==========================
@app.get("/bot_status")
def get_bot_status():
    try:
        running = False
        thread_alive = False

        try:
            running = getattr(bot, "running", False)
        except:
            running = False

        try:
            thread_alive = (
                bot.thread.is_alive()
                if hasattr(bot, "thread") and bot.thread
                else False
            )
        except:
            thread_alive = False

        return {
            "status": "RUNNING" if running else "STOPPED",
            "running": running,
            "thread_alive": thread_alive
        }

    except Exception as e:
        return {
            "status": "ERROR",
            "running": False,
            "thread_alive": False,
            "detail": str(e)
        }


# ==========================
# POSITIONS
# ==========================
@app.get("/positions")
def get_positions():
    try:
        return bot.get_positions()
    except Exception:
        return []


@app.get("/bot/summary")
def get_summary():
    try:
        return {
            "positions": bot.get_positions()
        }
    except Exception as e:
        return {
            "positions": [],
            "error": str(e)
        }


# ==========================
# PNL
# ==========================
@app.get("/pnl")
def get_pnl():
    try:
        return {"pnl": bot.get_pnl()}
    except Exception:
        return {"pnl": 0}


# ==========================
# PRICE
# ==========================
@app.get("/price")
def get_price():
    try:
        return {"price": bot.get_price()}
    except Exception:
        return {"price": 0}


# ==========================
# CONTROL
# ==========================
@app.post("/bot/start")
def start_bot():
    try:
        bot.start()
        return {"status": "RUNNING"}
    except Exception as e:
        return {"status": "ERROR", "detail": str(e)}


@app.post("/bot/stop")
def stop_bot():
    try:
        bot.stop()
        return {"status": "STOPPED"}
    except Exception as e:
        return {"status": "ERROR", "detail": str(e)}


# ==========================
# 🧠 ASSET SUMMARY
# ==========================
@app.get("/api/getAssetSummary")
def get_asset_summary():
    try:
        positions = bot.get_positions()
        pnl = bot.get_pnl()

        balance = 0
        try:
            balance = getattr(bot, "get_balance", lambda: 0)()
        except:
            balance = 0

        risk = 0.3
        try:
            risk = getattr(bot, "get_risk", lambda: 0.3)()
        except:
            risk = 0.3

        return {
            "balance": balance,
            "pnl": pnl,
            "equity": balance + pnl,
            "open_positions": len(positions) if positions else 0,
            "risk": risk
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


# ==========================
# 🧠 AI SCORE（★今回追加）
# ==========================
@app.get("/api/ai/scores")
def ai_scores(symbol: str):
    return []