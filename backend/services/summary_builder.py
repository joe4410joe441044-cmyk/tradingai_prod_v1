# -*- coding: utf-8 -*-
import time


def build_summary(bot):

    # =========================
    # 必須コンポーネントチェック
    # =========================
    if not hasattr(bot, "portfolio"):
        raise Exception("portfolio未接続")

    if not hasattr(bot, "exchange"):
        raise Exception("exchange未接続")

    if not hasattr(bot, "get_price"):
        raise Exception("price取得関数なし")

    # =========================
    # PORTFOLIO（唯一ソース）
    # =========================
    ps = bot.portfolio.summary()

    balance = ps["balance"]
    equity = ps["equity"]
    pnl = ps["unrealized_pnl"]
    realized_pnl = ps["realized_pnl"]
    exposure = ps["exposure_ratio"]

    # =========================
    # PRICE（fail-fast）
    # =========================
    price = bot.get_price()
    if price is None:
        raise Exception("price未取得")

    # =========================
    # STATUS（厳密判定）
    # =========================
    if not bot.is_running():
        status = "STOPPED"
    elif not bot.exchange.is_connected():
        status = "ERROR"
    else:
        status = "RUNNING"

    # =========================
    # CONNECTION（実通信）
    # =========================
    connection = "ONLINE" if bot.exchange.is_connected() else "OFFLINE"

    # =========================
    # POSITIONS（fail-fast）
    # =========================
    positions = []

    raw_positions = bot.portfolio.get_positions()

    if not isinstance(raw_positions, dict):
        raise Exception("positions形式不正")

    for p in raw_positions.values():
        positions.append({
            "symbol": p["symbol"],
            "side": p["side"],
            "entry": p["entry"],
            "size": p["size"],
            "pnl": p["pnl"],
            "pnl_percent": p["pnl_percent"],
            "duration": p["duration"],
            "status": p["status"]
        })

    # =========================
    # LOGS（存在時のみ）
    # =========================
    logs = []
    if hasattr(bot, "logger"):
        logs = bot.logger.get_recent_logs()

    # =========================
    # AI EVENTS（存在時のみ）
    # =========================
    ai_events = []
    if hasattr(bot, "ai"):
        ai_events = bot.ai.get_events()

    # =========================
    # RISK（存在時のみ）
    # =========================
    risk = {
        "drawdown": 0,
        "kill_switch": False,
        "loss_streak": 0,
        "peak_equity": 0
    }

    if hasattr(bot, "risk"):
        risk = bot.risk.get_status()

    # =========================
    # FINAL（完全な真実のみ）
    # =========================
    return {
        "price": price,

        "balance": balance,
        "equity": equity,
        "pnl": pnl,
        "realized_pnl": realized_pnl,
        "exposure": exposure,

        "status": status,
        "connection": connection,

        "positions": positions,
        "logs": logs,
        "ai": ai_events,

        "risk": risk,

        "meta": {
            "timestamp": int(time.time())
        }
    }