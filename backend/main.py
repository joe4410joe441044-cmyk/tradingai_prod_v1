# H:\マイドライブ\tradingai_prod_v1\backend\main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 既存の Positions ルーターがある場合
# from routers import positions

# --------------------------
# FastAPI 本体
app = FastAPI(title="TradingAI Backend")

# --------------------------
# CORS 設定（React からアクセス可能）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番では特定オリジンに変更可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------
# Positions ルーター登録（必要な場合コメントアウト解除）
# app.include_router(positions.router, prefix="/positions", tags=["Positions"])

# --------------------------
# 右側UI用ダミーAPI
# --------------------------

# ログ保持用（最初はサンプル）
logs = [
    "2026-04-04 10:00:00 - Bot started",
    "2026-04-04 10:01:00 - Entered BTCUSDT LONG 0.01",
    "2026-04-04 10:02:00 - BTCUSDT PnL updated 200"
]

# ボット状態管理
bot_status = {"status": "STOPPED"}

# --------------------------
# Positions ダミー API
positions = [
    {"id": 1, "pair": "BTCUSDT", "side": "LONG", "entry": 65000, "current": 65200, "pnl": 200, "size": 0.01},
    {"id": 2, "pair": "ETHUSDT", "side": "SHORT", "entry": 1800, "current": 1790, "pnl": 10, "size": 0.05},
]

@app.get("/positions")
def get_positions():
    return positions

# --------------------------
# Logs取得
@app.get("/logs")
def get_logs():
    return logs

# --------------------------
# Botステータス取得
@app.get("/bot_status")
def get_bot_status():
    return bot_status

# --------------------------
# Bot起動
@app.post("/bot/start")
def start_bot():
    bot_status["status"] = "RUNNING"
    logs.append("Bot started")
    return bot_status

# --------------------------
# Bot停止
@app.post("/bot/stop")
def stop_bot():
    bot_status["status"] = "STOPPED"
    logs.append("Bot stopped")
    return bot_status