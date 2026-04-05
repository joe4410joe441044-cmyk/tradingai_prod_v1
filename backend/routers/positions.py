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

class BotStatus(BaseModel):
    running: bool

# =========================
# Bot 状態管理
# =========================
class BotState:
    def __init__(self):
        self.running = False

bot_state = BotState()

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
# Logs（改善版）
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

@router.get("/logs", response_model=List[Log])
def get_logs():
    return logs_data

# =========================
# Bot Control（強化版）
# =========================
@router.post("/bot/start")
def start_bot():
    if bot_state.running:
        add_log("WARN", "Bot already running")
        return {"status": "already_running"}

    bot_state.running = True
    add_log("INFO", "Bot started")
    return {"status": "started"}

@router.post("/bot/stop")
def stop_bot():
    if not bot_state.running:
        add_log("WARN", "Bot already stopped")
        return {"status": "already_stopped"}

    bot_state.running = False
    add_log("INFO", "Bot stopped")
    return {"status": "stopped"}

@router.get("/bot/status", response_model=BotStatus)
def get_status():
    return {"running": bot_state.running}