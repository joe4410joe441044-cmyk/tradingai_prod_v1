# -*- coding: utf-8 -*-
import uvicorn
import webbrowser
import threading
import os
import sys
import asyncio
import subprocess
from typing import Dict

# --------------------------
# パス修正（プロジェクトルート & Bot フォルダ）
# --------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

BOT_DIR = os.path.join(BASE_DIR, "Bot")
if BOT_DIR not in sys.path:
    sys.path.append(BOT_DIR)

# --------------------------
# Bot モジュール import
# --------------------------
from trade_core import TradeCore, StrategyContext
from utils.safety import safe_run  # Bot/utils/safety.py 内関数

# --------------------------
# React サーバー設定
# --------------------------
REACT_DIR = r"C:\trading\react_dashboard"  # React があるパスに変更

def start_react():
    """React (Vite) サーバーを起動"""
    try:
        subprocess.Popen(["npm", "run", "dev"], cwd=REACT_DIR, shell=True)
        print("🌐 React 開始中...")
    except Exception as e:
        print(f"⚠ React 起動失敗: {e}")

# --------------------------
# ブラウザ自動オープン（React デモ用）
# --------------------------
def open_browser():
    url = "http://localhost:5173"  # React デモの URL
    try:
        webbrowser.open(url)
        print(f"🌐 ブラウザ起動: {url}")
    except Exception as e:
        print(f"⚠ ブラウザ起動失敗: {e}")

# --------------------------
# FastAPI 初期化
# --------------------------
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TradingAI Bot Backend Test")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------
# Bot & 状態管理
# --------------------------
bot_core = TradeCore()
bot_task = None
bot_running = False
price_dict: Dict[str, float] = {"BTCUSDT": 65000.0}  # モック価格

# --------------------------
# Bot 自動ループ
# --------------------------
async def bot_loop():
    global bot_running
    print("[BOT] Loop started")
    while bot_running:
        # モック価格を少し動かす
        price_dict["BTCUSDT"] *= 1 + 0.0005

        # StrategyContext 作成（例）
        ctx = StrategyContext(
            strategy_name="FVG_Test",
            trade_type="BUY",
            entry_price=price_dict["BTCUSDT"],
            stop_loss_price=price_dict["BTCUSDT"] - 50,
            take_profit_price=price_dict["BTCUSDT"] + 50,
            volume=0.001,
            fvg_signal=True
        )

        bot_core.try_enter(ctx)
        bot_core.check_orders(price_dict)
        await asyncio.sleep(1)

# --------------------------
# API: Start Bot
# --------------------------
@app.post("/bot/start")
async def start_bot():
    global bot_task, bot_running
    if bot_running:
        return {"status": "already running"}
    bot_running = True
    bot_task = asyncio.create_task(bot_loop())
    return {"status": "running"}

# --------------------------
# API: Stop Bot
# --------------------------
@app.post("/bot/stop")
async def stop_bot():
    global bot_task, bot_running
    if not bot_running:
        return {"status": "already stopped"}
    bot_running = False
    if bot_task:
        await bot_task
    bot_task = None
    return {"status": "stopped"}

# --------------------------
# API: Status
# --------------------------
@app.get("/bot/status")
async def bot_status():
    return {"running": bot_running, "positions": len(bot_core.positions)}

# --------------------------
# API: Summary
# --------------------------
@app.get("/bot/summary")
async def get_summary():
    summary_list = []
    for pos in bot_core.positions:
        current_price = price_dict.get(pos.symbol, pos.entry_price)
        pnl = (pos.close_price - pos.entry_price) * pos.volume if pos.status == "closed" else (current_price - pos.entry_price) * pos.volume
        if pos.trade_type == "SELL":
            pnl *= -1
        summary_list.append({
            "symbol": pos.symbol,
            "side": pos.trade_type,
            "entry": pos.entry_price,
            "current": current_price,
            "volume": pos.volume,
            "status": pos.status,
            "pnl": round(pnl, 6)
        })
    return {"positions": summary_list}

# --------------------------
# React 互換 API 追加（404 回避用）
# --------------------------
@app.get("/positions")
async def positions_alias():
    return await get_summary()

@app.get("/bot_status")
async def bot_status_alias():
    return await bot_status()

@app.get("/logs")
async def logs_alias():
    return {"logs": []}  # 今は空のモック

# --------------------------
# メイン起動（連動テスト用）
# --------------------------
if __name__ == "__main__":
    # 1秒後に React サーバーを起動
    threading.Timer(1.0, start_react).start()
    # 3秒後にブラウザを開く（React サーバー起動待ち）
    threading.Timer(3.0, open_browser).start()

    print("=== FastAPI + Bot + React 統合版（テスト用） 起動中 ===")
    uvicorn.run(
        app,  # 直接 app を渡す
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info"
    )