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


class AdvisorRuntimeResponse(StrictModel):
    bot: AdvisorBotStatus
    operation: AdvisorOperationStatus
    safety: AdvisorSafetyStatus
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
