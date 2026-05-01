from fastapi import APIRouter
from backend.bot_manager import get_bot_manager

router = APIRouter()

@router.post("/symbol")
def set_symbol(data: dict):
    try:
        symbol = data.get("symbol")

        if not symbol:
            return {"error": "symbol required"}

        bot = get_bot_manager()
        engine = bot.get_engine()

        print(f"🔁 SYMBOL APPLY: {symbol}")

        engine.set_config({"symbol": symbol})

        return {"status": "ok", "symbol": symbol}

    except Exception as e:
        return {"error": str(e)}