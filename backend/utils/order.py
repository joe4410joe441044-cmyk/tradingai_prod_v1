# backend/utils/order.py

from backend.config import (
    TRADE_MODE,
    ALLOW_LIVE
)


def place_order_safe(
    exchange,
    portfolio,
    order
):

    # =========================
    # GUARD
    # =========================

    if order["qty"] <= 0:

        print("❌ INVALID QTY:", order)

        return {
            "success": False,
            "status": "rejected",
            "reason": "invalid_qty"
        }

    # =========================
    # PAPER
    # =========================

    if TRADE_MODE != "live" or not ALLOW_LIVE:

        print("🟡 PAPER ORDER:", order)

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

            print("❌ PAPER ORDER ERROR:", e)

            return {
                "success": False,
                "status": "paper_error",
                "error": str(e)
            }

    # =========================
    # LIVE
    # =========================

    print("🔴 LIVE ORDER:", order)

    try:

        res = exchange.place_order(**order)

        return {
            "success": bool(res),
            "status": "live",
            "raw": res
        }

    except Exception as e:

        print("❌ LIVE ORDER ERROR:", e)

        return {
            "success": False,
            "status": "live_error",
            "error": str(e)
        }