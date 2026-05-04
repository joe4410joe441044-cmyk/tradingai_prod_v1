# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.bot_manager import get_bot_manager

router = APIRouter()

bot_manager = get_bot_manager()


# =========================
# CONFIG MODEL
# =========================
class StartConfig(BaseModel):
    symbol: str
    risk_percent: float
    sl_percent: float
    leverage: float
    mode: str


# =========================
# START
# =========================
@router.post("/start")
def start_bot(config: StartConfig):

    config_dict = config.dict()

    # 🔥 symbol正規化（ここで固定）
    config_dict["symbol"] = config_dict["symbol"].upper()

    # 🔥 modeチェック（事故防止）
    if config_dict["mode"] not in ["paper", "live"]:
        raise HTTPException(status_code=400, detail="invalid mode")

    print("===================================")
    print("🔥 START CONFIG RECEIVED:", config_dict)
    print("===================================")

    return bot_manager.start(config_dict)


# =========================
# STOP
# =========================
@router.post("/stop")
def stop_bot():

    print("🛑 STOP REQUEST")

    return bot_manager.stop()


# =========================
# SYMBOL（完全無効）
# =========================
@router.post("/symbol")
def set_symbol(data: dict):

    print("⚠️ SYMBOL API DISABLED")

    return {
        "status": "error",
        "reason": "symbol must be set via /start only"
    }