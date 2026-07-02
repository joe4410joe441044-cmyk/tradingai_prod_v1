# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException
from backend.bot_manager import get_bot_manager

from pydantic import BaseModel, Field
from enum import Enum
from typing import Any, Optional
from backend.utils.log_buffer import runtime_debug

router = APIRouter()


# =========================
# MODE（固定）
# =========================
class Mode(str, Enum):
    paper = "paper"
    live = "live"


class Exchange(str, Enum):
    kucoin = "kucoin"
    binance = "binance"


# =========================
# CONFIG（仕様書）
# =========================
class StartConfig(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    exchange: Exchange = Exchange.kucoin
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

    timestamp: float

    last_update: float

    price: float

    marketReady: bool

    marketStale: bool

    execution_mode: str

    real_order_allowed: bool

    ws_connected: bool

    position_active: bool

    pendingOrder: bool

    balance: float

    equity: float

    pnl: float

    executionAuthorityScore: int

    authoritativeRuntimeState: str

    runtimeSynchronizationState: str

    runtime_trace: dict = Field(default_factory=dict)

    runtime_metrics: dict = Field(default_factory=dict)

    strategy_state: dict = Field(default_factory=dict)

    execution_state: dict = Field(default_factory=dict)

    ai_state: Optional[dict] = None

    governance_state: Optional[dict] = None

    latestRuntimeResult: Optional[dict] = None

    executionRuntimeReached: bool = False

    signalAdapterReached: bool = False

    normalizedDirection: Optional[str] = None

    adapterOutput: Optional[dict] = None

    symbol: Optional[str] = None

    exchange: Optional[str] = None

    orderbookSource: Optional[str] = None

    orderbookSymbol: Optional[str] = None

    position: Optional[Any] = None
    actual_position: Optional[Any] = None


# =========================
# BOT START
# =========================
@router.post("/start")
def start_bot(config: StartConfig):

    bot_manager = get_bot_manager()

    config_dict = config.model_dump()
    
    # ===================================
    # FORCE STRING MODE
    # ===================================

    config_dict["mode"] = str(
        config_dict["mode"]
    ).split(".")[-1]

    config_dict["mode"] = (
        config_dict["mode"]
        .replace("'>", "")
        .replace("'", "")
        .strip()
        .lower()
    )

    config_dict["exchange"] = str(
        config_dict["exchange"]
    ).split(".")[-1].lower()

    runtime_debug("Normalized API mode=%s", config_dict["mode"])

    # 🔥 正規化（安全）
    config_dict["symbol"] = config_dict["symbol"].upper()

    runtime_debug(
        "Bot start request manager_id=%s config=%s",
        id(bot_manager),
        config_dict,
    )

    try:
        result = bot_manager.start(config_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


# =========================
# BOT STOP
# =========================
@router.post("/stop")
def stop_bot():

    bot_manager = get_bot_manager()
    runtime_debug("Bot stop request manager_id=%s", id(bot_manager))

    result = bot_manager.stop()

    return result


# =========================
# STATUS
# =========================
@router.get("/status", response_model=StatusResponse)
def get_status():

    bot_manager = get_bot_manager()
    return bot_manager.get_status()
