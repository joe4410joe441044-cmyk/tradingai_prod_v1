from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from datetime import datetime

router = APIRouter()

# =========================
# モデル定義（Swagger用）
# =========================
class Position(BaseModel):
    id: int
    pair: str
    side: str
    entry: float
    current: float
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
logs_data: List[Log] = []
MAX_LOGS = 100  # 最大保持数


def add_log(log_type: str, message: str):
    logs_data.append({
        "id": len(logs_data) + 1,
        "time": datetime.now().strftime("%H:%M:%S"),
        "type": log_type,
        "message": message
    })

    # 古いログを削除
    if len(logs_data) > MAX_LOGS:
        logs_data.pop(0)


# =========================
# Positions
# =========================
@router.get("/positions", response_model=List[Position])
def get_positions():
    return [
        {
            "id": 1,
            "pair": "BTCUSDT",
            "side": "LONG",
            "entry": 65000,
            "current": 65200,
            "pnl": 200,
            "size": 0.01
        }
    ]


# =========================
# Trade History（ダミー）
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