"""Archived, unmounted Legacy AI log router."""

from fastapi import APIRouter

router = APIRouter()

# ★STEP5：簡易メモリストア（まずはこれでOK）
AI_LOG_STORE = {}


@router.post("/ai/log")
def save_ai_log(log: dict):

    symbol = log.get("symbol", "UNKNOWN")

    if symbol not in AI_LOG_STORE:
        AI_LOG_STORE[symbol] = []

    AI_LOG_STORE[symbol].append(log)

    return {"status": "ok"}


@router.get("/ai/scores")
def get_ai_scores(symbol: str):

    logs = AI_LOG_STORE.get(symbol, [])

    return [
        {
            "timestamp": l["timestamp"],
            "ai_score": l["ai_score"],
            "risk_score": l["risk_score"],
            "entry_allowed": l["entry_allowed"],
            "position_id": l["position_id"]
        }
        for l in logs
    ]
