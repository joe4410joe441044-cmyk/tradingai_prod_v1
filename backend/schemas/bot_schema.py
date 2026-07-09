from pydantic import BaseModel, Field
from typing import List, Optional
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
    position_size: float = Field(0.0, ge=0)
    max_drawdown_pct: float = Field(5.0, gt=0)
    leverage: float = Field(..., gt=0)
    timeframe: str = Field("1m")
    sl_percent: float = Field(..., gt=0)
    tp_percent: float = Field(2.0, gt=0)
    trailing_stop: bool = False
    dry_run: bool = True
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
    risk_percent: Optional[float] = None
    leverage: Optional[float] = None
    timeframe: Optional[str] = None
    position_size: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    current_drawdown_pct: Optional[float] = None
    trailing_stop: Optional[bool] = None
    real_qty: Optional[float] = None
    notional: Optional[float] = None
    active_position_qty: Optional[float] = None
    active_position_contract_qty: Optional[float] = None
    active_position_notional: Optional[float] = None
    active_position_entry_notional: Optional[float] = None
    trade_settings: dict = Field(default_factory=dict)
    tradeSettings: dict = Field(default_factory=dict)
    allowLive: bool = False
    tradeMode: str = "paper"
    liveReadiness: dict = Field(default_factory=dict)
    liveBlockReasons: List[str] = Field(default_factory=list)
    exchangeClientReady: bool = False
    exchangeAuthReady: bool = False
    balanceCheckOk: bool = False
    positionCheckOk: bool = False
    executionEnabled: bool = False
    emergencyStop: bool = False
