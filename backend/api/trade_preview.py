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
        # 🔧 依存取得
        # =========================
        from backend.core.container import bot
        from backend.core.risk.position_sizing import calculate_qty

        engine = bot.get_engine()
        client = engine.client  # BinanceClient想定

        # =========================
        # 📊 価格取得
        # =========================
        price = client.get_price(symbol)

        if price <= 0:
            return {
                "valid": False,
                "reason": "invalid_price"
            }

        # =========================
        # 🔥 フィルタ取得（Binance準拠）
        # =========================
        filters = client.get_symbol_filters(symbol)

        # =========================
        # 🔥 qty計算（唯一のロジック）
        # =========================
        result = calculate_qty(
            balance=balance,
            risk_percent=risk_percent,
            leverage=leverage,
            price=price,
            min_qty=filters["min_qty"],
            step_size=filters["step_size"]
        )

        if not result["valid"]:
            return result

        qty = result["qty"]
        risk_amount = result["risk_amount"]
        position_size = result["position_size"]

        # =========================
        # 📊 参考情報（UI表示用）
        # =========================
        required_margin = position_size / leverage

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
            "reason": str(e)
        }