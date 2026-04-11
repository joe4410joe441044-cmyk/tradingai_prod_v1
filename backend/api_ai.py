from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS（React接続用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# TradeCoreインスタンス（後で注入）
# =========================
trade_core = None


def set_trade_core(core):
    global trade_core
    trade_core = core


# =========================
# AIステータス
# =========================
@app.get("/api/ai/status")
def ai_status():

    if not trade_core:
        return {"error": "no_trade_core"}

    return {
        "ai_score": trade_core.ai_last_score,
        "ai_decision": trade_core.ai_last_decision,
        "open_positions": len(trade_core.positions)
    }


# =========================
# AIログ（最新100件）
# =========================
@app.get("/api/ai/logs")
def ai_logs():

    if not trade_core:
        return []

    return trade_core.ai_logger.logs[-100:]


# =========================
# ポジション一覧
# =========================
@app.get("/api/positions")
def positions():

    if not trade_core:
        return []

    return [
        {
            "id": p.id,
            "symbol": p.symbol,
            "type": p.trade_type,
            "entry": p.entry_price,
            "sl": p.sl,
            "tp": p.tp,
            "status": p.status
        }
        for p in trade_core.positions.values()
    ]