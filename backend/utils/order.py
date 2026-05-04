# backend/utils/order.py

from backend.config import TRADE_MODE, ALLOW_LIVE

def place_order_safe(exchange, portfolio, order):

    # =========================
    # ガード
    # =========================
    if order["qty"] <= 0:
        print("❌ INVALID QTY:", order)
        return {"status": "rejected"}

    # =========================
    # PAPER
    # =========================
    if TRADE_MODE != "live" or not ALLOW_LIVE:
        print("🟡 PAPER ORDER:", order)

        portfolio.open_position(
            symbol=order["symbol"],
            price=order["price"],
            size=order["qty"],
            side=order["side"]
        )

        return {"status": "paper"}

    # =========================
    # LIVE
    # =========================
    print("🔴 LIVE ORDER:", order)
    return exchange.place_order(**order)