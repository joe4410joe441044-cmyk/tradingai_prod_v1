# H:\マイドライブ\tradingai_prod_v1\backend\main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ★ BotManager追加
from backend.bot_manager import BotManager

# --------------------------
# FastAPI 本体
app = FastAPI(title="TradingAI Backend")

# --------------------------
# CORS 設定（React からアクセス可能）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本番では制限推奨
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------
# ★ BotManager 初期化
bot = BotManager()
bot.start()  # ← ここで起動して仮想ポジション生成開始

# --------------------------
# API（BotManager連動）
# --------------------------

# ポジション取得
@app.get("/positions")
def get_positions():
    return bot.get_positions()


# ログ取得
@app.get("/logs")
def get_logs():
    return bot.get_logs()


# Botステータス
@app.get("/bot_status")
def get_bot_status():
    return bot.get_status()


# Bot起動
@app.post("/bot/start")
def start_bot():
    bot.start()
    return {"status": "RUNNING"}


# Bot停止
@app.post("/bot/stop")
def stop_bot():
    bot.stop()
    return {"status": "STOPPED"}