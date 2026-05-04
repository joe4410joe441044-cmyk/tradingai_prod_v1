# -*- coding: utf-8 -*-

from fastapi import APIRouter

router = APIRouter()


@router.get("/preview")
def trade_preview(
    symbol: str,
    balance: float,
    risk_percent: float,
    leverage: float
):
    try:
        # =========================
        # 🔧 依存取得（🔥ここが本質修正）
        # =========================
        from backend.core.container import bot, client
        from backend.core.risk.position_sizing import calculate_qty

        engine = bot.get_engine()  # 未使用でもOK（将来用）

        # =========================
        # 📊 価格取得
        # =========================
        price = client.get_price(symbol)

        if price is None or price <= 0:
            return {
                "valid": False,
                "reason": "invalid_price",
                "price": price
            }

        # =========================
        # 🔥 フィルタ取得
        # =========================
        filters = client.get_symbol_filters(symbol)

        if not filters:
            return {
                "valid": False,
                "reason": "no_filters"
            }

        min_qty = filters.get("min_qty")
        step_size = filters.get("step_size")

        if min_qty is None or step_size is None:
            return {
                "valid": False,
                "reason": "invalid_filters",
                "filters": filters
            }

        # =========================
        # 🔥 qty計算（唯一ロジック）
        # =========================
        result = calculate_qty(
            balance=balance,
            risk_percent=risk_percent,
            leverage=leverage,
            price=price,
            min_qty=min_qty,
            step_size=step_size
        )

        if not result["valid"]:
            return result

        qty = result["qty"]
        risk_amount = result["risk_amount"]
        position_size = result["position_size"]

        # =========================
        # 📊 参考情報
        # =========================
        required_margin = position_size / leverage if leverage > 0 else 0

        return {
            "valid": True,
            "symbol": symbol,
            "price": price,
            "qty": qty,
            "risk_amount": round(risk_amount, 2),
            "position_size": round(position_size, 2),
            "required_margin": round(required_margin, 2)
        }

    except Exception as e:
        return {
            "valid": False,
            "reason": str(e),
            "type": type(e).__name__
        }