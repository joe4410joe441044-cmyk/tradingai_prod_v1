from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.bot_manager import BotManager

app = FastAPI(title="TradingAI Backend")

# =========================
# CORS
# =========================
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

# =========================
# BOT CORE
# =========================
bot = BotManager()

# =========================
# STARTUP
# =========================
@app.on_event("startup")
def startup():
    bot.start()

# =========================
# BOT CONTROL（統一API）
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
        "balance": 0,
        "pnl": bot.get_pnl(),
        "equity": 0,
        "open_positions": len(bot.get_positions()),
        "risk": 0.3
    }

# =========================
# DATA API（統一整理）
# =========================

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
# FRONTEND（React配信）
# =========================
app.mount(
    "/",
    StaticFiles(directory="react_dashboard/dist", html=True),
    name="react"
)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)