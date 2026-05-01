# -*- coding: utf-8 -*-

from fastapi import APIRouter, Query
from backend.bot_manager import get_bot_manager

router = APIRouter()

bot_manager = get_bot_manager()


# =========================
# BOT START
# =========================
@router.post("/start")
def start_bot(config: dict):

    print("🔥 START CONFIG RECEIVED:", config)

    engine = bot_manager.get_engine()

    # =========================
    # Engine存在チェック
    # =========================
    if not engine:
        print("🚨 ENGINE NOT FOUND")
        return {"status": "error", "message": "engine not initialized"}

    # =========================
    # 🔥 config反映（最重要）
    # =========================
    try:
        engine.set_config(config)
        print("🔥 ENGINE CONFIG APPLIED")
    except Exception as e:
        print("[CONFIG APPLY ERROR]", e)

    # =========================
    # Riskリセット
    # =========================
    try:
        if hasattr(engine, "risk") and engine.risk:
            engine.risk.reset()
    except Exception as e:
        print("[RISK RESET ERROR]", e)

    # =========================
    # 🔥 WSはBotManagerに任せる
    # =========================
    result = bot_manager.start()

    print("🚀 BOT START COMPLETE")

    return result


# =========================
# BOT STOP
# =========================
@router.post("/stop")
def stop_bot():
    result = bot_manager.stop()
    print("🛑 BOT STOPPED")
    return result


# =========================
# ステータス取得
# =========================
@router.get("/status")
def get_status():
    return bot_manager.get_status()


# =========================
# SYMBOL変更（任意API）
# =========================
@router.post("/set_symbol")
def set_symbol(symbol: str = Query(...)):
    try:
        engine = bot_manager.get_engine()

        if not engine:
            return {"status": "error", "message": "engine not found"}

        engine.symbol = symbol

        if hasattr(engine, "ws_client") and engine.ws_client:
            engine.ws_client.set_symbol(symbol)
            print(f"🔄 WS SYMBOL SWITCH → {symbol}")
        else:
            return {"status": "error", "message": "ws_client not found"}

        print(f"🔄 SYMBOL CHANGED → {symbol}")

        return {
            "status": "ok",
            "symbol": symbol
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }