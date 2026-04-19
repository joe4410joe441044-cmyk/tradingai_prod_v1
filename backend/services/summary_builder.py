import time

def build_summary(bot):

    return {
        "price": bot.get_price(),
        "balance": bot.get_balance(),
        "equity": bot.get_balance() + bot.get_pnl(),
        "pnl": bot.get_pnl(),
        "risk": 0.3,

        "status": {
            "running": bot.is_running() if hasattr(bot, "is_running") else True,
            "mode": getattr(bot, "mode", "LIVE"),
            "uptime_sec": getattr(bot, "uptime", lambda: 0)()
        },

        "positions": [
            {
                "symbol": p.symbol,
                "side": p.side,
                "entry": p.entry_price,
                "mark": getattr(p, "mark_price", p.entry_price),
                "size": p.size,
                "pnl": getattr(p, "pnl", 0),
                "pnl_percent": getattr(p, "pnl_percent", 0)
            }
            for p in bot.get_positions()
        ],

        "logs": [
            {
                "time": getattr(l, "time", ""),
                "type": getattr(l, "type", "INFO"),
                "message": getattr(l, "message", "")
            }
            for l in bot.get_logs()
        ],

        "meta": {
            "timestamp": int(time.time()),
            "source": "trading_bot_v1"
        }
    }