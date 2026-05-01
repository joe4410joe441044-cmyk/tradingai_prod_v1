from fastapi import APIRouter

router = APIRouter()


@router.get("/result")
def get_result():
    try:
        # 🔥 遅延import（循環回避）
        from backend.main import bot

        engine = bot.get_engine()
        return engine.get_result()

    except Exception as e:
        return {"error": str(e)}