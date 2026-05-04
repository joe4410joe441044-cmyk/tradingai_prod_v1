from fastapi import APIRouter
from backend.models.reset_request import ResetRequest
from backend.bot_manager import get_bot_manager

router = APIRouter()

@router.post("/reset_portfolio")
def reset_portfolio(req: ResetRequest):

    bot = get_bot_manager()
    portfolio = bot.portfolio

    portfolio.reset(req.balance)

    return {
        "status": "reset",
        "balance": req.balance
    }