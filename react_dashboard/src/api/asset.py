# api/asset.py

from fastapi import APIRouter

router = APIRouter()

# --------------------------
# 繝繝溘・ or BOT騾｣謳ｺ逕ｨ髢｢謨ｰ
# --------------------------
def get_balance():
    return 12000

def get_pnl():
    return 350

def get_equity(balance, pnl):
    return balance + pnl

def get_open_positions():
    return 2

def get_risk():
    return 0.32


# --------------------------
# 邨ｱ蜷・PI・・I逕ｨ・・
# --------------------------
@router.get("/getAssetSummary")
def get_asset_summary():

    balance = get_balance()
    pnl = get_pnl()
    equity = get_equity(balance, pnl)
    open_positions = get_open_positions()
    risk = get_risk()

    return {
        "balance": balance,
        "pnl": pnl,
        "equity": equity,
        "open_positions": open_positions,
        "risk": risk
    }
