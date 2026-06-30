# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.bot_manager import (
    get_bot_manager
)
from backend.utils.log_buffer import logger, runtime_debug

router = APIRouter()


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

    # =========================
    # GET BOT MANAGER
    # =========================

    bot_manager = get_bot_manager()

    config_dict = config.dict()

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

    runtime_debug("Normalized API mode=%s", config_dict["mode"])

    # =========================
    # SYMBOL NORMALIZE
    # =========================

    config_dict["symbol"] = (
        config_dict["symbol"]
        .upper()
    )

    # =========================
    # MODE VALIDATION
    # =========================

    if config_dict["mode"] not in [
        "paper",
        "live"
    ]:

        raise HTTPException(
            status_code=400,
            detail="invalid mode"
        )

    runtime_debug(
        "Bot start request manager_id=%s config=%s",
        id(bot_manager),
        config_dict,
    )

    return bot_manager.start(
        config_dict
    )


# =========================
# STOP
# =========================

@router.post("/stop")
def stop_bot():

    # =========================
    # GET BOT MANAGER
    # =========================

    bot_manager = get_bot_manager()

    runtime_debug("Bot stop request manager_id=%s", id(bot_manager))

    return bot_manager.stop()


# =========================
# SYMBOL（完全無効）
# =========================

@router.post("/symbol")
def set_symbol(data: dict):

    logger.warning("Symbol API disabled")

    return {
        "status": "error",
        "reason": (
            "symbol must be set "
            "via /start only"
        )
    }
