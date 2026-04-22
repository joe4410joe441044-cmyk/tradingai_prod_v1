from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse

import os
import logging
import asyncio

from backend.bot_manager import BotManager
from backend.services.summary_builder import build_summary

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
        "http://35.194.104.74:3000",
        "http://localhost",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# CORE
# =========================

bot = BotManager()

# =========================
# FRONTEND PATH
# =========================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DIST_PATH = os.path.abspath(
    os.path.join(BASE_DIR, "..", "react_dashboard", "dist")
)

ASSETS_PATH = os.path.join(DIST_PATH, "assets")

# =========================
# STARTUP
# =========================

@app.on_event("startup")
def startup():

    logging.info("🚀 TradingAI startup sequence begin")

    env = os.getenv("ENV", "dev")
    logging.info(f"ENV = {env}")

    if env == "prod":
        logging.info("🧠 Checking React build...")

        if not os.path.exists(DIST_PATH):
            error_msg = f"""
🚨 FRONTEND BUILD MISSING

DIST_PATH = {DIST_PATH}

Fix:
1. cd react_dashboard
2. npm install
3. npm run build
4. restart backend
"""
            logging.error(error_msg)
            raise RuntimeError(error_msg)

        logging.info("✅ React build OK")

    try:
        bot.start()
        logging.info("✅ Bot started successfully")
    except Exception as e:
        logging.error(f"BOT START ERROR: {e}")
        raise


# =========================
# API
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
    return build_summary(bot)

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

@app.get("/api/ai/scores")
def ai_scores(symbol: str):
    return []


# =========================
# WEBSOCKET (FIXED + STABLE)
# =========================

@app.websocket("/ws/price")
async def ws_price(websocket: WebSocket):

    # 🔥 重要：403対策（明示的accept）
    await websocket.accept()

    logging.info(f"📡 WebSocket connected: /ws/price | origin={websocket.headers.get('origin')}")

    try:
        while True:
            await websocket.send_json({
                "price": bot.get_price()
            })
            await asyncio.sleep(1)

    except Exception as e:
        logging.warning(f"WS disconnected: {e}")


# =========================
# GLOBAL ERROR HANDLER
# =========================

@app.exception_handler(Exception)
def global_error_handler(request: Request, exc: Exception):

    logging.error(f"RUNTIME ERROR: {exc}")

    return JSONResponse(
        status_code=500,
        content={
            "error_code": "BACKEND_RUNTIME_ERROR",
            "message": str(exc),
            "hint": "Bot / API internal error",
        }
    )


# =========================
# FRONTEND ROUTE
# =========================

@app.get("/")
def serve_frontend():

    index_path = os.path.join(DIST_PATH, "index.html")

    if not os.path.exists(index_path):
        return JSONResponse(
            status_code=500,
            content={
                "error": "index.html not found",
                "path": index_path
            }
        )

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    return HTMLResponse(content=html)


# =========================
# STATIC ASSETS
# =========================

try:
    if os.path.exists(ASSETS_PATH):
        app.mount(
            "/assets",
            StaticFiles(directory=ASSETS_PATH),
            name="assets"
        )
        logging.info("✅ Static assets mounted")
except Exception as e:
    logging.warning(f"Static mount skipped: {e}")


# =========================
# FAVICON
# =========================

@app.get("/favicon.ico")
def favicon():
    ico_path = os.path.join(DIST_PATH, "favicon.svg")
    if os.path.exists(ico_path):
        return FileResponse(ico_path)
    return JSONResponse(status_code=204, content={})


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)