# -*- coding: utf-8 -*-

from fastapi import APIRouter
from backend.bot_manager import get_bot_manager

router = APIRouter()

# 🔥 シングルトン取得（統一）
bot_manager = get_bot_manager()


@router.post("/symbol")
def set_symbol(data: dict):
    try:
        # =========================
        # 🔥 入力取得
        # =========================
        symbol = data.get("symbol")

        print("🔥 SYMBOL REQUEST:", data)

        if not symbol:
            return {
                "status": "error",
                "reason": "symbol_required"
            }

        # =========================
        # 🔥 正規化
        # =========================
        symbol = symbol.upper()

        print(f"🔁 SYMBOL APPLY → {symbol}")

        # =========================
        # 🔥 Botへ反映（WS含む）
        # =========================
        bot_manager.set_symbol(symbol)

        print(f"✅ SYMBOL APPLIED: {symbol}")

        return {
            "status": "ok",
            "symbol": symbol
        }

    except Exception as e:
        print("❌ SYMBOL ERROR:", e)

        return {
            "status": "error",
            "reason": str(e)
        }