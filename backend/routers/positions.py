# -*- coding: utf-8 -*-

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from datetime import datetime

router = APIRouter()

# 🔥 Engine参照（外部から注入）
engine = None

def set_engine(e):
    global engine
    engine = e


# =========================
# モデル定義（UI統一）
# =========================
class Position(BaseModel):
    symbol: str
    side: str
    entry: float
    pnl: float
    size: float


class Log(BaseModel):
    id: int
    time: str
    type: str
    message: str


# =========================
# ログ管理
# =========================
logs_data: List[dict] = []
MAX_LOGS = 100


def add_log(log_type: str, message: str):
    log = {
        "id": len(logs_data) + 1,
        "time": datetime.now().strftime("%H:%M:%S"),
        "type": log_type,
        "message": message
    }

    logs_data.append(log)

    if len(logs_data) > MAX_LOGS:
        logs_data.pop(0)


# =========================
# Positions（実データ）
# =========================
@router.get("/positions", response_model=List[Position])
def get_positions():
    if not engine:
        return []

    try:
        positions = engine.state_manager.get_positions()

        result = []

        for p in positions.values():
            result.append({
                "symbol": p.get("symbol"),
                "side": p.get("side"),
                "entry": p.get("entry"),
                "pnl": p.get("pnl", 0),
                "size": p.get("size")
            })

        return result

    except Exception as e:
        return []


# =========================
# Trade History（後で実装）
# =========================
@router.get("/history")
def get_history():
    return []


# =========================
# Logs
# =========================
@router.get("/logs", response_model=List[Log])
def get_logs():
    return logs_data