# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException
from backend.bot_manager import get_bot_manager

from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional

router = APIRouter()


# =========================
# MODE（固定）
# =========================
class Mode(str, Enum):
    paper = "paper"
    live = "live"


# =========================
# CONFIG（仕様書）
# =========================
class StartConfig(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    risk_percent: float = Field(..., gt=0)
    sl_percent: float = Field(..., gt=0)
    leverage: float = Field(..., gt=0)
    tp_percent: float = Field(2.0, gt=0)
    mode: Mode


# =========================
# STATUS RESPONSE（仕様書）
# =========================
class StatusResponse(BaseModel):
    status: str
    price: float
    pnl: float
    balance: float
    equity: float
    symbol: Optional[str]


# =========================
# BOT START
# =========================
@router.post("/start")
def start_bot(config: StartConfig):

    bot_manager = get_bot_manager()

    config_dict = config.dict()

    # 🔥 正規化（安全）
    config_dict["symbol"] = config_dict["symbol"].upper()

    print("START BOT ID:", id(bot_manager))
    print("🔥 START CONFIG RECEIVED:", config_dict)

    try:
        result = bot_manager.start(config_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    print("🚀 BOT START COMPLETE")

    return result


# =========================
# BOT STOP
# =========================
@router.post("/stop")
def stop_bot():

    bot_manager = get_bot_manager()
    print("STOP BOT ID:", id(bot_manager))

    result = bot_manager.stop()

    print("🛑 BOT STOPPED")

    return result


# =========================
# STATUS
# =========================
@router.get("/status", response_model=StatusResponse)
def get_status():

    bot_manager = get_bot_manager()
    return bot_manager.get_status()