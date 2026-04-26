import time

def build_summary(bot):

    def safe(fn, default=0):
        try:
            return fn() if callable(fn) else fn
        except:
            return default

    # ===== CORE =====
    price = safe(bot.get_price, 0)
    balance = safe(bot.get_balance, 0)
    pnl = safe(bot.get_pnl, 0)

    # ===== CONNECTION =====
    connection = "OFFLINE"
    if hasattr(bot, "market"):
        connection = "ONLINE" if getattr(bot.market, "connected", False) else "OFFLINE"

    # ===== STATUS =====
    status = "RUNNING" if safe(bot.is_running, False) else "STOPPED"

    # ===== POSITIONS（Execution）=====
    positions = []
    for p in safe(bot.get_positions, []):
        positions.append({
            "symbol": getattr(p, "symbol", ""),
            "side": getattr(p, "side", ""),
            "entry": getattr(p, "entry_price", 0),
            "mark": getattr(p, "mark_price", getattr(p, "entry_price", 0)),
            "size": getattr(p, "size", 0),
            "pnl": getattr(p, "pnl", 0),
            "pnl_percent": getattr(p, "pnl_percent", 0),
            "time": getattr(p, "time", 0),
            "status": getattr(p, "status", "OPEN"),  # ★追加
        })

    # ===== LOGS =====
    logs = []
    if hasattr(bot, "logger"):
        try:
            logs = bot.logger.get_recent_logs()[-50:]
        except:
            logs = []

    # ===== AI =====
    ai_events = []
    if hasattr(bot, "ai"):
        try:
            ai_events = bot.ai.get_events()[-50:]
        except:
            pass

    # ===== RISK =====
    risk = {
        "drawdown": 0,
        "kill_switch": False,
        "loss_streak": 0
    }

    if hasattr(bot, "risk"):
        r = bot.risk
        risk = {
            "drawdown": getattr(r, "drawdown", 0),
            "kill_switch": getattr(r, "kill_active", False),
            "loss_streak": getattr(r, "loss_streak", 0)
        }

    # ===== PORTFOLIO =====
    if hasattr(bot, "portfolio"):
        p = bot.portfolio
        balance = getattr(p, "balance", balance)
        pnl = getattr(p, "pnl", pnl)

    # ===== FINAL =====
    return {
        "price": price,
        "balance": balance,
        "equity": balance + pnl,
        "pnl": pnl,

        "status": status,
        "connection": connection,

        "positions": positions,
        "logs": logs,
        "ai_events": ai_events,
        "risk": risk,

        "meta": {
            "timestamp": int(time.time())
        }
    }