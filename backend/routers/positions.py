# -*- coding: utf-8 -*-

from fastapi import APIRouter
from pydantic import BaseModel

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


# =========================
# Positions（実データ）
# =========================
@router.get("/positions")
def get_positions():

    if not engine:

        return {

            "positions": [],

            "execution": {

                "status": "STOPPED",

                "execution_mode": "SIMULATION",

                "real_order_allowed": False,

                "ws_connected": False,

                "position_active": False,

                "executionAuthorityScore": 0,

                "authoritativeRuntimeState": "STOPPED",

                "runtimeSynchronizationState": "OFFLINE"
            }
        }

    try:

        result = []

        actual_position = getattr(
            engine,
            "actual_position",
            None
        )

        if actual_position:

            result.append({

                "symbol": (
                    actual_position.get("symbol")
                    or getattr(engine, "symbol", None)
                ),

                "side": actual_position.get(
                    "side"
                ),

                "entry": actual_position.get(
                    "entry_price"
                ),

                "pnl": actual_position.get(
                    "pnl",
                    0
                ),

                "size": actual_position.get(
                    "qty"
                )
            })

        snapshot = engine.get_status()

        return {

            "positions": result,

            "execution": snapshot
        }

    except Exception as e:

        return {

            "positions": [],

            "execution": {

                "status": "ERROR",

                "execution_mode": "ERROR",

                "real_order_allowed": False,

                "ws_connected": False,

                "position_active": False,

                "executionAuthorityScore": 0,

                "authoritativeRuntimeState": "ERROR",

                "runtimeSynchronizationState": "OFFLINE",

                "error": str(e)
            }
        }


# =========================
# Trade History（後で実装）
# =========================
@router.get("/history")
def get_history():
    return []