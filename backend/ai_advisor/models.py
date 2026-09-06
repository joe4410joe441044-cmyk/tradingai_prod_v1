from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class AdvisorBotStatus(StrictModel):
    state: Literal["NOT_CONNECTED", "STOPPED", "RUNNING", "UNKNOWN"]
    mode: Optional[Literal["PAPER", "LIVE"]]
    exchange: Optional[str]
    symbol: Optional[str]


class AdvisorOperationStatus(StrictModel):
    loopEnabled: bool
    loopState: Literal[
        "NOT_CONNECTED",
        "STOPPED",
        "STARTING",
        "RUNNING",
        "STOPPING",
        "UNKNOWN",
    ]
    autoTradeEnabled: bool
    positionState: Optional[Literal["FLAT", "OPEN", "UNKNOWN"]] = None
    pendingOrderState: Optional[Literal["NONE", "OPEN", "UNKNOWN"]] = None


class AdvisorSafetyStatus(StrictModel):
    emergencyLocked: bool
    emergencyState: Literal[
        "READY",
        "PROCESSING",
        "LOCKED",
        "ACTION_REQUIRED",
        "UNKNOWN",
    ]
    dryRun: bool
    realOrderAllowed: bool


class AdvisorRuntimeMetadata(StrictModel):
    capturedAt: str
    sourceUpdatedAt: Optional[str]
    freshness: Freshness


class AdvisorMoneyManagementRuntimeStatus(StrictModel):
    """Read-only MM-authoritative numeric projection (verbatim, not recalculated)."""

    regime: Optional[str] = None
    equity: Optional[float] = None
    availableCapital: Optional[float] = None
    exposure: Optional[float] = None
    remainingExposure: Optional[float] = None
    positionCapacity: Optional[int] = None
    remainingPositionCapacity: Optional[int] = None
    riskBudget: Optional[float] = None
    drawdownPercent: Optional[float] = None
    ruinGuardStatus: Optional[str] = None
    compoundingEnabled: Optional[bool] = None
    authorityFresh: Optional[bool] = None
    capturedAt: Optional[str] = None


class AdvisorMarketRuntimeStatus(StrictModel):
    """Read-only Market authority projection, kept separate from MM."""

    ready: Optional[bool] = None
    stale: Optional[bool] = None
    symbol: Optional[str] = None


class AdvisorRuntimeResponse(StrictModel):
    bot: AdvisorBotStatus
    operation: AdvisorOperationStatus
    safety: AdvisorSafetyStatus
    runtime: AdvisorRuntimeMetadata
    moneyManagement: Optional[AdvisorMoneyManagementRuntimeStatus] = None
    market: Optional[AdvisorMarketRuntimeStatus] = None
    warnings: List[str]


class AdvisorErrorDetail(StrictModel):
    code: str
    message: str
    retryable: bool
    requestId: str
    occurredAt: str


class AdvisorErrorResponse(StrictModel):
    error: AdvisorErrorDetail
