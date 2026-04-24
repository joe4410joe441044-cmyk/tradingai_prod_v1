# -*- coding: utf-8 -*-
from fastapi import APIRouter

router = APIRouter()

# =========================
# trade_core（main.pyから注入）
# =========================
trade_core = None


def set_trade_core(core):
    """
    main.pyから注入される想定
    """
    global trade_core
    trade_core = core


# =========================
# Risk Status
# =========================
@router.get("/risk/status")
def risk_status():

    if not trade_core:
        return {"error": "no_trade_core"}

    rm = trade_core.risk_manager

    return {
        "kill_switch": rm.kill_switch,
        "equity": rm.equity,
        "daily_pnl": rm.daily_pnl,
        "max_drawdown": rm.max_daily_loss,
        "open_positions": len(trade_core.positions),
        "position_limit": rm.max_positions
    }


# =========================
# Kill Switch ON
# =========================
@router.post("/risk/kill")
def risk_kill():

    if not trade_core:
        return {"error": "no_trade_core"}

    trade_core.risk_manager.kill_switch = True

    # Bot停止連動（重要）
    if hasattr(trade_core, "stop"):
        trade_core.stop()

    return {
        "status": "KILLED",
        "kill_switch": True
    }


# =========================
# Reset Risk State
# =========================
@router.post("/risk/reset")
def risk_reset():

    if not trade_core:
        return {"error": "no_trade_core"}

    rm = trade_core.risk_manager

    rm.kill_switch = False
    rm.daily_pnl = 0.0

    # equityは本来は口座同期推奨
    if hasattr(rm, "reset"):
        rm.reset()

    return {
        "status": "RESET",
        "kill_switch": False
    }


# =========================
# Internal Update Hook（将来用）
# =========================
def update_risk(**kwargs):
    """
    ExecutionEngine / BotManagerから呼ばれる想定
    """
    if not trade_core:
        return

    rm = trade_core.risk_manager

    for k, v in kwargs.items():
        if hasattr(rm, k):
            setattr(rm, k, v)