# =========================
# 🧯 DISABLED MODULE（移行中）
# ※ このファイルは現在使用停止
# =========================

from fastapi import FastAPI

app = FastAPI()

# =====================================================
# 🚫 BOT STATUS（無効化）
# =====================================================
@app.get("/api/bot_status")
def bot_status():
    try:
        return {
            "running": False,
            "status": "DISABLED (migrated to backend/main.py)"
        }
    except Exception as e:
        return {
            "running": False,
            "error": str(e)
        }


# =====================================================
# 🚫 POSITIONS（無効化）
# =====================================================
@app.get("/api/positions")
def positions():
    try:
        return []
    except Exception as e:
        return {
            "error": str(e),
            "data": []
        }


# =====================================================
# 🚫 LOGS（無効化）
# =====================================================
@app.get("/api/logs")
def logs():
    try:
        return {
            "logs": [],
            "status": "DISABLED"
        }
    except Exception as e:
        return {
            "logs": [],
            "error": str(e)
        }


# =====================================================
# 🚫 BOT CONTROL（無効化）
# =====================================================
@app.post("/api/bot/start")
def start_bot():
    try:
        return {
            "status": "DISABLED",
            "message": "Bot control moved to backend/main.py"
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/bot/stop")
def stop_bot():
    try:
        return {
            "status": "DISABLED",
            "message": "Bot control moved to backend/main.py"
        }
    except Exception as e:
        return {"error": str(e)}


# =====================================================
# 🚫 AI SCORE（無効化）
# =====================================================
@app.get("/api/ai/scores")
def ai_scores(symbol: str):
    return []