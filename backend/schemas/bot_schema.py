from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


# =========================
# Mode固定
# =========================
class Mode(str, Enum):
    paper = "paper"
    live = "live"


class Exchange(str, Enum):
    kucoin = "kucoin"
    binance = "binance"


# =========================
# BOT START REQUEST
# =========================
class BotStartRequest(BaseModel):
    symbol: str = Field(..., example="BTCUSDT")
    exchange: Exchange = Exchange.kucoin
    risk_percent: float = Field(..., gt=0)
    leverage: float = Field(..., gt=0)
    sl_percent: float = Field(..., gt=0)
    tp_percent: float = Field(2.0, gt=0)
    mode: Mode


# =========================
# BOT STATUS RESPONSE
# =========================
class BotStatusResponse(BaseModel):
    status: str
    price: float
    pnl: float
    balance: float
    equity: float
    symbol: Optional[str]
