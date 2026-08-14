# -*- coding: utf-8 -*-

from fastapi import APIRouter
from fastapi import HTTPException

router = APIRouter()

@router.post("/symbol")
def set_symbol():
    raise HTTPException(
        status_code=409,
        detail="RUNNING_SYMBOL_SWITCH_UNSUPPORTED; set symbol via /api/bot/start",
    )
