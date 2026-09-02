# -*- coding: utf-8 -*-

from fastapi import APIRouter, HTTPException
from backend.bot_manager import get_bot_manager

from pydantic import BaseModel, ConfigDict, Field, model_validator
from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional
from backend.utils.log_buffer import runtime_debug

router = APIRouter()


# =========================
# MODE（固定）
# =========================
class Mode(str, Enum):
    paper = "paper"
    live = "live"


class Exchange(str, Enum):
    kucoin = "kucoin"
    binance = "binance"


class SelectionMode(str, Enum):
    manual = "MANUAL"
    auto = "AUTO"


class PaperCapitalSource(str, Enum):
    dashboard_manual = "DASHBOARD_MANUAL"
    real_available_preset = "REAL_AVAILABLE_PRESET"


class PaperCapitalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capital: Decimal = Field(
        ...,
        gt=Decimal("0"),
        le=Decimal("1000000000.00"),
        decimal_places=2,
    )
    source: PaperCapitalSource = PaperCapitalSource.dashboard_manual


class LiveAutoApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approvalIdentity: str = Field(..., min_length=1, max_length=200)
    approvalSource: str = Field("EXPLICIT_OPERATOR_APPROVAL")
    ttlSeconds: int = Field(600, ge=30, le=900)


# =========================
# CONFIG（仕様書）
# =========================
class StartConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., example="BTCUSDT")
    exchange: Exchange = Exchange.kucoin
    risk_percent: float = Field(..., gt=0, le=1)
    position_size: float = Field(0.0, ge=0, le=1000000000)
    max_drawdown_pct: float = Field(5.0, gt=0, le=100)
    sl_percent: float = Field(..., gt=0, le=100)
    leverage: float = Field(..., gt=0, le=100)
    timeframe: str = Field("1m", pattern=r"^(1m|5m|15m|1h)$")
    tp_percent: float = Field(2.0, gt=0, le=100)
    trailing_stop: bool = False
    dry_run: bool = True
    mode: Mode
    selection_mode: SelectionMode = SelectionMode.manual
    loop_on_start: bool = False
    auto_trade_on_start: bool = False

    @model_validator(mode="after")
    def validate_automation_order(self):
        if self.auto_trade_on_start and not self.loop_on_start:
            raise ValueError("AUTO_TRADE_ON_START_REQUIRES_LOOP_ON_START")
        if self.mode is Mode.live and (
            self.loop_on_start or self.auto_trade_on_start
        ):
            raise ValueError("LIVE_DISARMED_REQUIRES_LOOP_AND_AUTO_OFF")
        return self


# =========================
# STATUS RESPONSE（仕様書）
# =========================
class StatusResponse(BaseModel):

    status: str

    timestamp: float

    last_update: float

    price: float

    marketReady: bool

    marketStale: bool

    execution_mode: str

    real_order_allowed: bool

    accountSource: str = "PAPER_SIMULATION"

    balanceSource: str = "PAPER_SIMULATION"

    positionSource: str = "PAPER_SIMULATION"

    realOrderAllowed: bool = False

    liveRuntimeStartAllowed: bool = False

    liveOrderEntryAllowed: bool = False

    executionEntryAllowed: bool = False

    executionMode: str = "SIMULATION"

    dryRun: bool = True

    selectedMode: str = "PAPER"

    safetyReason: str = "DRY_RUN_ACTIVE"

    allowLive: bool = False

    tradeMode: str = "paper"

    paperBootstrapEligible: Optional[bool] = None

    paperBootstrapStatus: Optional[str] = None

    paperBootstrapReasonCodes: List[str] = Field(default_factory=list)

    paperBootstrapEvaluatedAt: Optional[float] = None

    paperBootstrapSource: Optional[str] = None

    exchangeAuth: str = "NOT_VERIFIED"

    realAccountConnected: bool = False

    realBalance: Optional[float] = None

    realEquity: Optional[float] = None

    realAvailableBalance: Optional[float] = None

    realPosition: Optional[Any] = None

    realPositionState: Optional[str] = None

    realAccountLastSync: Optional[float] = None

    realLastSync: Optional[float] = None

    exchangeConnection: str = "NOT_CONNECTED"

    apiKeyStatus: str = "MISSING"

    permission: str = "NOT_VERIFIED"

    accountType: str = "UNKNOWN"

    exchangeAuthReason: Optional[str] = None

    exchangeConnectionReason: Optional[str] = None

    accountReason: Optional[str] = None

    balanceReason: Optional[str] = None

    positionReason: Optional[str] = None

    accountSourceReason: Optional[str] = None

    balanceSourceReason: Optional[str] = None

    positionSourceReason: Optional[str] = None

    accountRuntime: dict = Field(default_factory=dict)


    ws_connected: bool

    position_active: bool

    pendingOrder: bool

    pendingOrderState: dict = Field(default_factory=dict)

    pending_order_state: dict = Field(default_factory=dict)

    balance: float

    equity: float

    availableBalance: Optional[float] = None

    available_balance: Optional[float] = None

    pnl: float

    position_size: Optional[float] = None

    positionSize: Optional[float] = None

    risk_percent: Optional[float] = None

    leverage: Optional[float] = None

    timeframe: Optional[str] = None

    max_drawdown_pct: Optional[float] = None

    maxDd: Optional[float] = None

    tp_percent: Optional[float] = None

    sl_percent: Optional[float] = None

    trailing_stop: Optional[bool] = None

    trailingStop: Optional[bool] = None

    current_drawdown_pct: Optional[float] = None

    risk_block_reason: Optional[str] = None

    risk_config: dict = Field(default_factory=dict)

    risk_state: dict = Field(default_factory=dict)

    trade_settings: dict = Field(default_factory=dict)

    tradeSettings: dict = Field(default_factory=dict)

    liveReadiness: dict = Field(default_factory=dict)

    liveBlockReasons: List[str] = Field(default_factory=list)

    exchangeClientReady: bool = False

    exchangeAuthReady: bool = False

    balanceCheckOk: bool = False

    positionCheckOk: bool = False

    executionEnabled: bool = False

    botState: str = "STOPPED"

    loopEnabled: bool = False

    loopState: str = "STOPPED"

    autoTradeEnabled: bool = False

    emergencyStop: bool = False

    emergencyLocked: bool = False

    emergencyState: str = "UNLOCKED"

    emergency: dict = Field(default_factory=dict)

    emergencyReturnWarnings: List[str] = Field(default_factory=list)

    real_qty: Optional[float] = None

    notional: Optional[float] = None

    active_position_qty: Optional[float] = None

    active_position_contract_qty: Optional[float] = None

    active_position_notional: Optional[float] = None

    active_position_entry_notional: Optional[float] = None

    executionAuthorityScore: int

    authoritativeRuntimeState: str

    runtimeSynchronizationState: str

    runtime_trace: dict = Field(default_factory=dict)

    runtime_metrics: dict = Field(default_factory=dict)

    strategy_state: dict = Field(default_factory=dict)

    execution_state: dict = Field(default_factory=dict)

    ai_state: Optional[dict] = None

    tradingAiMode: str = "OFF"

    tradingAiStatus: str = "NOT_INSTALLED"

    governance_state: Optional[dict] = None

    runtime_health: dict = Field(default_factory=dict)

    tradingDecision: dict = Field(default_factory=dict)

    latestRuntimeResult: Optional[dict] = None

    executionRuntimeReached: bool = False

    signalAdapterReached: bool = False

    normalizedDirection: Optional[str] = None

    adapterOutput: Optional[dict] = None

    symbol: Optional[str] = None

    activeSymbol: Optional[str] = None

    selectionMode: str = "MANUAL"

    autoMarketSelection: dict = Field(default_factory=dict)

    leverageAuthority: dict = Field(default_factory=dict)

    exchange: Optional[str] = None

    orderbookSource: Optional[str] = None

    orderbookSymbol: Optional[str] = None

    position: Optional[Any] = None
    actual_position: Optional[Any] = None


# =========================
# BOT START
# =========================
@router.post("/start")
def start_bot(config: StartConfig):

    bot_manager = get_bot_manager()

    config_dict = config.model_dump()
    
    # ===================================
    # FORCE STRING MODE
    # ===================================

    config_dict["mode"] = str(
        config_dict["mode"]
    ).split(".")[-1]

    config_dict["mode"] = (
        config_dict["mode"]
        .replace("'>", "")
        .replace("'", "")
        .strip()
        .lower()
    )

    config_dict["exchange"] = str(
        config_dict["exchange"]
    ).split(".")[-1].lower()

    config_dict["selection_mode"] = str(
        config_dict["selection_mode"]
    ).split(".")[-1].upper().strip()

    runtime_debug("Normalized API mode=%s", config_dict["mode"])

    # 🔥 正規化（安全）
    config_dict["symbol"] = config_dict["symbol"].upper()

    runtime_debug(
        "Bot start request manager_id=%s config=%s",
        id(bot_manager),
        config_dict,
    )

    try:
        result = bot_manager.start(config_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


# =========================
# BOT STOP
# =========================
@router.post("/stop")
def stop_bot():

    bot_manager = get_bot_manager()
    runtime_debug("Bot stop request manager_id=%s", id(bot_manager))

    result = bot_manager.stop()

    return result


@router.post("/loop/start")
def start_loop():
    result = get_bot_manager().start_loop()
    if result.get("success") is not True:
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/loop/stop")
def stop_loop():
    return get_bot_manager().stop_loop()


@router.post("/live-auto/approve")
def approve_live_auto(request: LiveAutoApprovalRequest):
    result = get_bot_manager().approve_live_auto_control(
        approval_identity=request.approvalIdentity,
        approval_source=request.approvalSource,
        ttl_seconds=request.ttlSeconds,
    )
    if result.get("accepted") is not True:
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/live-auto/start")
def start_live_auto():
    result = get_bot_manager().start_live_auto_control()
    if result.get("accepted") is not True:
        raise HTTPException(status_code=409, detail=result)
    return result


@router.post("/live-auto/stop")
def stop_live_auto():
    return get_bot_manager().stop_live_auto_control()


# =========================
# STATUS
# =========================
@router.get("/status", response_model=StatusResponse)
def get_status():

    bot_manager = get_bot_manager()
    status = bot_manager.get_status()

    if isinstance(status, dict):
        trade_settings = (
            status.get("tradeSettings")
            or status.get("trade_settings")
            or {}
        )
        status["tradeSettings"] = trade_settings
        status["trade_settings"] = trade_settings

    return status


@router.post("/symbol")
def reject_direct_symbol_switch():
    raise HTTPException(
        status_code=409,
        detail="RUNNING_SYMBOL_SWITCH_UNSUPPORTED; set symbol via /api/bot/start",
    )


@router.post("/paper-account/capital")
def reset_paper_capital(request: PaperCapitalRequest):
    bot_manager = get_bot_manager()

    try:
        return bot_manager.reset_paper_capital(
            request.capital,
            request.source.value,
        )
    except ValueError as exc:
        reason = str(exc)
        status_code = 409 if reason in {
            "PAPER_POSITION_OPEN",
            "PAPER_PENDING_ORDER",
            "PAPER_OPEN_ORDER",
        } else 400
        raise HTTPException(status_code=status_code, detail=reason)
