from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

import os
import logging

from backend.bot_manager import BotManager

# =========================
# APP INIT
# =========================

app = FastAPI(title="TradingAI Backend")

# =========================
# LOGGING
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://35.194.104.74",
        "http://localhost",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# CORE
# =========================

bot = BotManager()

# ✔ 安全なパス（backendから見た相対位置）
DIST_PATH = os.path.join(
    os.path.dirname(__file__),
    "../react_dashboard/dist"
)

# =========================
# STARTUP（唯一の起動制御）
# =========================

@app.on_event("startup")
def startup():

    logging.info("🚀 TradingAI startup sequence begin")

    # -------------------------
    # ENV CHECK
    # -------------------------

    env = os.getenv("ENV", "dev")
    logging.info(f"ENV = {env}")

    # -------------------------
    # FRONTEND BUILD CHECK
    # -------------------------

    if env == "prod":
        logging.info("🧠 Checking React build...")

        if not os.path.exists(DIST_PATH):
            error_msg = """
🚨 [ERROR_CODE: FRONT_DIST_MISSING]

■ 問題
react_dashboard/dist が存在しません

■ 影響
- UI表示不可
- APIは起動停止
- ERR_CONNECTION_REFUSED

■ 原因
- VPSでnpm run build未実行
- git pull後の反映漏れ

■ 対応
1. git pull origin main
2. cd react_dashboard
3. npm install
4. npm run build
5. systemctl restart tradingbot.service
"""
            logging.error(error_msg)
            raise RuntimeError(error_msg)

        logging.info("✅ React build OK")

    # -------------------------
    # BOT START
    # -------------------------

    try:
        bot.start()
        logging.info("✅ Bot started successfully")

    except Exception as e:
        logging.error(f"BOT START ERROR: {e}")
        raise

# =========================
# BOT API
# =========================

@app.post("/api/bot/start")
def start_bot():
    return bot.start()

@app.post("/api/bot/stop")
def stop_bot():
    return bot.stop()

@app.get("/api/bot/status")
def bot_status():
    return bot.get_status()

@app.get("/api/bot/summary")
def bot_summary():
    return {
        "balance": bot.get_balance(),
        "pnl": bot.get_pnl(),
        "equity": bot.get_balance(),
        "open_positions": len(bot.get_positions()),
        "risk": 0.3
    }

# =========================
# DATA API
# =========================

@app.get("/api/balance")
def get_balance():
    return {"balance": bot.get_balance()}

@app.get("/api/positions")
def positions():
    return bot.get_positions()

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
# AI SCORE
# =========================

@app.get("/api/ai/scores")
def ai_scores(symbol: str):
    return []

# =========================
# GLOBAL ERROR HANDLER（500統一）
# =========================

@app.exception_handler(Exception)
def global_error_handler(request: Request, exc: Exception):

    logging.error(f"RUNTIME ERROR: {exc}")

    return JSONResponse(
        status_code=500,
        content={
            "error_code": "BACKEND_RUNTIME_ERROR",
            "message": str(exc),
            "hint": "Bot / API内部エラー",
            "fix": [
                "systemctl status tradingbot.service",
                "journalctl -u tradingbot.service -n 50",
                "BotManagerログ確認"
            ]
        }
    )

# =========================
# 404統一
# =========================

@app.middleware("http")
async def handle_404(request: Request, call_next):

    response = await call_next(request)

    if response.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={
                "error_code": "API_NOT_FOUND",
                "path": str(request.url),
                "hint": "APIルート確認",
                "fix": [
                    "FastAPIルート確認",
                    "React fetch URL確認"
                ]
            }
        )

    return response

# =========================
# FRONTEND
# =========================

app.mount(
    "/",
    StaticFiles(directory=DIST_PATH, html=True),
    name="react"
)

# =========================
# MAIN ENTRY
# =========================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)