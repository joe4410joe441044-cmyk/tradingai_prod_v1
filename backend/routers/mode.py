# backend/routes/mode.py

from fastapi import APIRouter
from pydantic import BaseModel
import backend.config as config
from backend.utils.log_buffer import logger

router = APIRouter()

class ModeRequest(BaseModel):
    mode: str


@router.post("/set_mode")
def set_mode(req: ModeRequest):

    if req.mode == "live":
        config.ALLOW_LIVE = True
        config.TRADE_MODE = "live"
        logger.warning("LIVE MODE ENABLED")

    else:
        config.TRADE_MODE = "paper"
        config.ALLOW_LIVE = False
        logger.info("PAPER MODE ENABLED")

    return {"success": True, "mode": config.TRADE_MODE}
