from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class AdvisorExecutionEntryState(str, Enum):
    """Tri-state representation of an execution-entry permission.

    Distinct from a plain boolean: UNKNOWN/UNAVAILABLE must never collapse into
    a False "not allowed" when the permission simply could not be determined.
    """

    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


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
    openPosState: Optional[Literal["FLAT", "OPEN", "UNKNOWN"]] = None
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


class AdvisorMarketStatus(StrictModel):
    selectionMode: Optional[Literal["MANUAL", "AUTO"]]
    marketReady: bool
    marketStale: bool


class AdvisorAuthorityStatus(StrictModel):
    liveOrderEntryState: AdvisorExecutionEntryState
    finalExecutionEntryState: AdvisorExecutionEntryState
    mmExecutionEntryState: AdvisorExecutionEntryState


class AdvisorMoneyManagementStatus(StrictModel):
    state: Optional[str]
    riskState: Optional[str]
    recommendedAction: Optional[str]
    executionEntryState: AdvisorExecutionEntryState
    mmRegime: Optional[str] = None
    equity: Optional[float] = None
    availableCapital: Optional[float] = None
    openExposure: Optional[float] = None
    remainingExposure: Optional[float] = None
    openPositionCapacity: Optional[int] = None
    remainingOpenPositionCapacity: Optional[int] = None
    riskBudget: Optional[float] = None
    drawdownPercent: Optional[float] = None
    ruinGuardStatus: Optional[str] = None
    compoundingEnabled: Optional[bool] = None
    authorityFresh: Optional[bool] = None
    mmCapturedAt: Optional[str] = None


class AdvisorHealthStatus(StrictModel):
    healthState: Literal["HEALTHY", "DEGRADED", "STOPPED", "UNKNOWN"]


class AdvisorRuntimeMetadata(StrictModel):
    capturedAt: str
    sourceUpdatedAt: Optional[str]
    freshness: Freshness


class AdvisorRuntimeResponse(StrictModel):
    bot: AdvisorBotStatus
    operation: AdvisorOperationStatus
    safety: AdvisorSafetyStatus
    market: Optional[AdvisorMarketStatus] = None
    authority: Optional[AdvisorAuthorityStatus] = None
    moneyManagement: Optional[AdvisorMoneyManagementStatus] = None
    health: Optional[AdvisorHealthStatus] = None
    runtime: AdvisorRuntimeMetadata
    warnings: List[str]


class AdvisorErrorDetail(StrictModel):
    code: str
    message: str
    retryable: bool
    requestId: str
    occurredAt: str


class AdvisorErrorResponse(StrictModel):
    error: AdvisorErrorDetail
