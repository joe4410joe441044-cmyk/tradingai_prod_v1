# backend/utils/order.py

from backend.config import (
    TRADE_MODE,
    ALLOW_LIVE
)
from backend.utils.log_buffer import add_log


def place_paper_order(portfolio, order):
    """Execute only against the in-memory paper portfolio.

    This function deliberately has no exchange argument and does not consult
    live configuration.  A caller that has already selected paper mode must
    not be able to fall through to an exchange because of process-wide config.
    """
    if order["qty"] <= 0:
        add_log(f"❌ PAPER ORDER REJECTED invalid quantity: {order}", "error")
        return {
            "success": False,
            "status": "rejected",
            "reason": "invalid_qty",
        }

    if portfolio is None:
        add_log("❌ PAPER ORDER ERROR: portfolio unavailable", "error")
        return {
            "success": False,
            "status": "paper_error",
            "error": "portfolio_unavailable",
        }

    add_log(f"🟡 PAPER ORDER: {order}")
    try:
        portfolio.open_position(
            symbol=order["symbol"],
            price=order["price"],
            size=order["qty"],
            side=order["side"],
        )
        return {
            "success": True,
            "status": "paper",
            "order": order,
        }
    except Exception as exc:
        add_log(f"❌ PAPER ORDER ERROR: {exc}", "error")
        return {
            "success": False,
            "status": "paper_error",
            "error": str(exc),
        }


def place_order_safe(
    exchange,
    portfolio,
    order
):

    # =========================
    # GUARD
    # =========================

    if order["qty"] <= 0:

        add_log(f"❌ ORDER REJECTED invalid quantity: {order}", "error")

        return {
            "success": False,
            "status": "rejected",
            "reason": "invalid_qty"
        }

    # =========================
    # PAPER
    # =========================

    if TRADE_MODE != "live" or not ALLOW_LIVE:

        add_log(f"🟡 PAPER ORDER: {order}")

        try:

            portfolio.open_position(
                symbol=order["symbol"],
                price=order["price"],
                size=order["qty"],
                side=order["side"]
            )

            return {
                "success": True,
                "status": "paper",
                "order": order
            }

        except Exception as e:

            add_log(f"❌ PAPER ORDER ERROR: {e}", "error")

            return {
                "success": False,
                "status": "paper_error",
                "error": str(e)
            }

    # =========================
    # LIVE
    # =========================

    add_log(f"🔴 LIVE ORDER: {order}")

    try:

        res = exchange.place_order(**order)

        return {
            "success": bool(res),
            "status": "live",
            "raw": res
        }

    except Exception as e:

        add_log(f"❌ LIVE ORDER ERROR: {e}", "error")

        return {
            "success": False,
            "status": "live_error",
            "error": str(e)
        }
