# backend/routes/mode.py

from fastapi import APIRouter
from pydantic import BaseModel
import backend.config as config

router = APIRouter()

class ModeRequest(BaseModel):
    mode: str


@router.post("/set_mode")
def set_mode(req: ModeRequest):

    if req.mode == "live":
        config.ALLOW_LIVE = True
        config.TRADE_MODE = "live"
        print("🔴 LIVE MODE ENABLED")

    else:
        config.TRADE_MODE = "paper"
        config.ALLOW_LIVE = False
        print("🟡 PAPER MODE")

    return {"success": True, "mode": config.TRADE_MODE}