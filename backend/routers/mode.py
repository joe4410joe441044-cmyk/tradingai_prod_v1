# backend/routes/mode.py

from fastapi import APIRouter, Depends
from pydantic import BaseModel
import backend.config as config
from backend.auth.dependencies import require_operator_session
from backend.utils.log_buffer import logger

router = APIRouter()

class ModeRequest(BaseModel):
    mode: str


@router.post("/set_mode")
def set_mode(
    req: ModeRequest,
    _operator: str = Depends(require_operator_session),
):

    if req.mode not in {"live", "paper"}:
        return {"success": False, "mode": config.TRADE_MODE, "reason": "INVALID_MODE"}

    if req.mode == "live":
        config.ALLOW_LIVE = True
        config.TRADE_MODE = "live"
        logger.warning("LIVE MODE ENABLED")

    else:
        config.TRADE_MODE = "paper"
        config.ALLOW_LIVE = False
        logger.info("PAPER MODE ENABLED")

    return {"success": True, "mode": config.TRADE_MODE}
