# -*- coding: utf-8 -*-

from fastapi import APIRouter
from backend.bot_manager import get_bot_manager
from backend.utils.log_buffer import logger

router = APIRouter()


# =========================
# Risk Quick（UI用）
# =========================
@router.get("/quick")
def risk_quick():
    try:
        bot = get_bot_manager()
        engine = getattr(bot, "engine", None)

        r = getattr(engine, "risk", None)

        if r is None:
            return {
                "kill_switch": False,
                "reason": "",
                "dd_limit": 0,
                "loss_limit": 0,
                "loss_count": 0,
                "peak_equity": 0
            }

        return {
            "kill_switch": getattr(r, "trading_disabled", False),
            "reason": getattr(r, "kill_reason", ""),
            "dd_limit": getattr(r, "max_drawdown_pct", 0),
            "loss_limit": getattr(r, "max_consecutive_losses", 0),
            "loss_count": getattr(r, "consecutive_losses", 0),
            "peak_equity": getattr(r, "peak_equity", 0)
        }

    except Exception as e:
        logger.error("RISK QUICK ERROR: %s", e)
        return {
            "kill_switch": False,
            "reason": str(e),
            "dd_limit": 0,
            "loss_limit": 0,
            "loss_count": 0,
            "peak_equity": 0
        }


# =========================
# SUMMARY（UI本体）
# =========================
@router.get("/bot/summary")
def get_bot_summary():
    try:
        bot = get_bot_manager()
        engine = getattr(bot, "engine", None)

        if engine is None:
            return {
                "status": "STOPPED", "price": 0, "balance": 0,
                "equity": 0, "pnl": 0, "positions": [],
                "risk": {
                    "kill_switch": False, "reason": "", "dd_limit": 0,
                    "loss_limit": 0, "loss_count": 0, "peak_equity": 0,
                },
                "logs": [], "connection": "OFFLINE",
            }

        # =========================
        # Engine結果取得（安全）
        # =========================
        try:
            result = engine.get_result() or {}
        except Exception as e:
            logger.error("SUMMARY RESULT ERROR: %s", e)
            result = {}

        r = getattr(engine, "risk", None)

        # =========================
        # フィールド安全補完
        # =========================
        price = result.get("price") or 0
        balance = result.get("balance") or 0
        equity = result.get("equity") or balance
        pnl = result.get("pnl") or 0
        positions = result.get("positions") or []

        return {
            "status": "RUNNING" if getattr(engine, "active", False) else "STOPPED",
            "price": price,
            "balance": balance,
            "equity": equity,
            "pnl": pnl,
            "positions": positions,

            "risk": {
                "kill_switch": getattr(r, "trading_disabled", False) if r else False,
                "reason": getattr(r, "kill_reason", "") if r else "",
                "dd_limit": getattr(r, "max_drawdown_pct", 0) if r else 0,
                "loss_limit": getattr(r, "max_consecutive_losses", 0) if r else 0,
                "loss_count": getattr(r, "consecutive_losses", 0) if r else 0,
                "peak_equity": getattr(r, "peak_equity", 0) if r else 0
            },

            "logs": [],
            "connection": "ONLINE"
        }

    except Exception as e:
        logger.error("SUMMARY ERROR: %s", e)

        return {
            "status": "ERROR",
            "price": 0,
            "balance": 0,
            "equity": 0,
            "pnl": 0,
            "positions": [],
            "risk": {
                "kill_switch": False,
                "reason": str(e),
                "dd_limit": 0,
                "loss_limit": 0,
                "loss_count": 0,
                "peak_equity": 0
            },
            "logs": [],
            "connection": "ERROR"
        }
