# -*- coding: utf-8 -*-

from fastapi import APIRouter
from backend.bot_manager import get_bot_manager
from backend.utils.log_buffer import logger, runtime_debug

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

        runtime_debug("Symbol request=%s", data)

        if not symbol:
            return {
                "status": "error",
                "reason": "symbol_required"
            }

        # =========================
        # 🔥 正規化
        # =========================
        symbol = symbol.upper()

        runtime_debug("Applying symbol=%s", symbol)

        # =========================
        # 🔥 Botへ反映（WS含む）
        # =========================
        bot_manager.set_symbol(symbol)

        logger.info("Symbol applied=%s", symbol)

        return {
            "status": "ok",
            "symbol": symbol
        }

    except Exception as e:
        logger.error("SYMBOL ERROR: %s", e)

        return {
            "status": "error",
            "reason": str(e)
        }
