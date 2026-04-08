# backend/dashboard.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import subprocess
import os

app = FastAPI(title="TradingAI BOT Dashboard")

LOG_FILE = "/home/joe4410joe/TradingAI_Bot_Prod_v1/logs/bot.log"

# --- BOTステータス ---
@app.get("/status", response_class=HTMLResponse)
def status():
    # systemd サービス状態取得
    result = subprocess.run(
        ["systemctl", "is-active", "tradingbot"],
        stdout=subprocess.PIPE
    )
    status = result.stdout.decode().strip()
    # 最後の注文ログ1行取得
    try:
        last_order = subprocess.check_output(
            f"tail -n 1 {LOG_FILE}", shell=True
        ).decode().strip()
    except:
        last_order = "ログなし"
    html = f"""
    <h2>TradingAI BOT Status</h2>
    <p>Status: <b>{status}</b></p>
    <p>Last Log: {last_order}</p>
    """
    return html

# --- 最新ログ表示 ---
@app.get("/logs", response_class=HTMLResponse)
def logs(lines: int = 50):
    try:
        log_data = subprocess.check_output(
            f"tail -n {lines} {LOG_FILE}", shell=True
        ).decode()
    except:
        log_data = "ログ取得失敗"
    html = f"<h2>Latest Logs</h2><pre>{log_data}</pre>"
    return html

# --- 残高表示 (簡易版) ---
@app.get("/balance", response_class=HTMLResponse)
def balance():
    from backend.binance_client import BinanceClient  # 既存クライアント利用
    client = BinanceClient()
    balances = client.get_balance()  # dict形式 {'USDT': 100.0, 'BTC': 0.01}
    html = "<h2>Account Balance</h2><ul>"
    for coin, amount in balances.items():
        html += f"<li>{coin}: {amount}</li>"
    html += "</ul>"
    return html

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