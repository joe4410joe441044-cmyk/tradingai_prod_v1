from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.bot_manager import BotManager

app = FastAPI(title="TradingAI Backend")

# --------------------------
# CORS
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
# BOT CORE
# --------------------------
bot = BotManager()

# --------------------------
# STARTUP
# --------------------------
@app.on_event("startup")
def startup():
    bot.start()

# --------------------------
# STATUS
# --------------------------
@app.get("/api/bot_status")
def bot_status():
    return bot.get_status()

# --------------------------
# POSITIONS
# --------------------------
@app.get("/api/positions")
def positions():
    return bot.get_positions()

# --------------------------
# LOGS
# --------------------------
@app.get("/api/logs")
def logs():
    return {"logs": bot.get_logs()}

# --------------------------
# CONTROL
# --------------------------
@app.post("/api/bot/start")
def start():
    bot.start()
    return {"status": "RUNNING"}

@app.post("/api/bot/stop")
def stop():
    bot.stop()
    return {"status": "STOPPED"}

# --------------------------
# PRICE
# --------------------------
@app.get("/price")
def price():
    return {"price": bot.get_price()}

# --------------------------
# PNL
# --------------------------
@app.get("/pnl")
def pnl():
    return {"pnl": bot.get_pnl()}

# --------------------------
# SUMMARY
# --------------------------
@app.get("/api/getAssetSummary")
def summary():
    positions = bot.get_positions()

    return {
        "balance": 0,
        "pnl": bot.get_pnl(),
        "equity": 0,
        "open_positions": len(positions),
        "risk": 0.3
    }

# --------------------------
# AI SCORE
# --------------------------
@app.get("/api/ai/scores")
def ai_scores(symbol: str):
    return []

# --------------------------
# FRONTEND
# --------------------------
app.mount(
    "/",
    StaticFiles(directory="react_dashboard/dist", html=True),
    name="react"
)

# --------------------------
# MAIN
# --------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)