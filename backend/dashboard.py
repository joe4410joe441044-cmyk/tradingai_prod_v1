# backend/dashboard.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import subprocess
import os

app = FastAPI(title="TradingAI BOT Dashboard")

# 🔥 CORS対応（最重要）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開発中は全許可
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOG_FILE = "/home/joe4410joe/TradingAI_Bot_Prod_v1/logs/bot.log"

# --- 共通：ログの最後取得 ---
def get_last_log():
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return lines[-1].strip() if lines else "ログなし"
    except:
        return "ログなし"

# --- 共通：ログ複数取得 ---
def get_logs(lines: int):
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines_list = f.readlines()
            return "".join(lines_list[-lines:])
    except:
        return "ログ取得失敗"


# --- BOTステータス（HTML） ---
@app.get("/status", response_class=HTMLResponse)
def status():
    result = subprocess.run(
        ["systemctl", "is-active", "tradingbot"],
        stdout=subprocess.PIPE
    )
    status = result.stdout.decode().strip()

    last_order = get_last_log()

    html = f"""
    <h2>TradingAI BOT Status</h2>
    <p>Status: <b>{status}</b></p>
    <p>Last Log: {last_order}</p>
    """
    return html


# --- BOTステータス（JSON：React用） ---
@app.get("/bot_status")
def bot_status():
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "tradingbot"],
            stdout=subprocess.PIPE
        )
        status = result.stdout.decode().strip()
    except:
        status = "unknown"

    last_order = get_last_log()

    return {
        "status": status,
        "last_log": last_order
    }


# --- ポジション取得（React用・最重要） ---
@app.get("/positions")
def get_positions():
    return [
        {
            "symbol": "BTCUSDT",
            "side": "LONG",
            "size": 0.001,
            "entry_price": 65000,
            "mark_price": 65100,
            "pnl": 1.0
        }
    ]


# 🔥🔥🔥 追加：AIスコアAPI（今回の本体）
@app.get("/ai/scores")
def get_ai_scores(symbol: str):
    return {
        "symbol": symbol,
        "score": 0,
        "confidence": 0
    }


# --- 最新ログ表示 ---
@app.get("/logs", response_class=HTMLResponse)
def logs(lines: int = 50):
    log_data = get_logs(lines)
    html = f"<h2>Latest Logs</h2><pre>{log_data}</pre>"
    return html


# --- 残高表示（HTML） ---
@app.get("/balance", response_class=HTMLResponse)
def balance():
    from backend.binance_client import BinanceClient
    client = BinanceClient()
    balances = client.get_balance()

    html = "<h2>Account Balance</h2><ul>"
    for coin, amount in balances.items():
        html += f"<li>{coin}: {amount}</li>"
    html += "</ul>"

    return html


# --- 残高（JSON：React用） ---
@app.get("/balance_json")
def balance_json():
    try:
        from backend.binance_client import BinanceClient
        client = BinanceClient()
        balances = client.get_balance()
    except:
        balances = {}

    return balances


# --- 緊急停止 ---
@app.get("/stop", response_class=HTMLResponse)
def stop_bot():
    subprocess.run(["sudo", "systemctl", "stop", "tradingbot"])
    return "<p>BOT stopped!</p>"


# --- 再起動 ---
@app.get("/start", response_class=HTMLResponse)
def start_bot():
    subprocess.run(["sudo", "systemctl", "restart", "tradingbot"])
    return "<p>BOT restarted!</p>"