"""Framework- and provider-independent Supervisor data contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import json
import math
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .failure_codes import SupervisorFailureCode


class SupervisorAgentId(str, Enum):
    MASTER_SUPERVISOR = "MASTER_SUPERVISOR"
    MM_SUPERVISOR = "MM_SUPERVISOR"


class SupervisorMode(str, Enum):
    SHADOW = "SHADOW"
    ADVISORY = "ADVISORY"
    ACTIVE = "ACTIVE"


class SupervisorState(str, Enum):
    GROWTH = "GROWTH"
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    DEFENSIVE = "DEFENSIVE"
    LOCKED = "LOCKED"
    UNKNOWN = "UNKNOWN"


class HumanAttention(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REVIEW = "REVIEW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    IMMEDIATE_ACTION = "IMMEDIATE_ACTION"


class TradingRecommendation(str, Enum):
    CONTINUE = "CONTINUE"
    CONTINUE_REDUCED = "CONTINUE_REDUCED"
    PAUSE_NEW_ENTRIES = "PAUSE_NEW_ENTRIES"
    STOP = "STOP"
    UNKNOWN = "UNKNOWN"


class RiskDirection(str, Enum):
    INCREASE_WITHIN_POLICY = "INCREASE_WITHIN_POLICY"
    MAINTAIN = "MAINTAIN"
    REDUCE = "REDUCE"
    PAUSE = "PAUSE"
    UNKNOWN = "UNKNOWN"


class CapitalCondition(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    UNKNOWN = "UNKNOWN"


class Freshness(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    CONFLICTED = "CONFLICTED"
    UNKNOWN = "UNKNOWN"


class CapitalSource(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"
    UNKNOWN = "UNKNOWN"


class InputValueState(str, Enum):
    ABSENT = "ABSENT"
    NULL = "NULL"
    UNKNOWN = "UNKNOWN"
    PRESENT = "PRESENT"


class SupervisorContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    def stable_json(self) -> str:
        """Serialize deterministically, preserving Decimal as an exact string."""
        return json.dumps(
            _json_value(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {name: _json_value(getattr(value, name)) for name in type(value).model_fields}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value


def _finite_decimal(value: Decimal | None) -> Decimal | None:
    if value is not None and not value.is_finite():
        raise ValueError("decimal must be finite")
    return value


def _finite_number(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("number must be finite")
    if isinstance(value, Decimal) and not value.is_finite():
        raise ValueError("number must be finite")
    return value


TextItem = str


class FieldValueObservation(SupervisorContract):
    field: str = Field(min_length=1, max_length=100)
    state: InputValueState


class MMRecommendedAction(SupervisorContract):
    riskDirection: RiskDirection
    riskMultiplier: Decimal | None = None

    _finite = field_validator("riskMultiplier")(_finite_decimal)

    @field_validator("riskMultiplier")
    @classmethod
    def non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("riskMultiplier must be non-negative")
        return value


class MMSupervisorAssessment(SupervisorContract):
    schemaVersion: int = Field(default=1, ge=1, le=1)
    agent: SupervisorAgentId = SupervisorAgentId.MM_SUPERVISOR
    mode: SupervisorMode = SupervisorMode.SHADOW
    assessmentState: SupervisorState
    recommendedRiskDirection: RiskDirection
    recommendedRiskMultiplier: Decimal | None = None
    capitalCondition: CapitalCondition
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: tuple[TextItem, ...] = Field(max_length=20)
    uncertainties: tuple[TextItem, ...] = Field(default=(), max_length=20)
    recoveryConditions: tuple[TextItem, ...] = Field(default=(), max_length=20)
    sourceEvaluatedAt: datetime
    assessedAt: datetime

    MAX_TEXT_LENGTH: ClassVar[int] = 500
    grantsExecutionAuthority: ClassVar[bool] = False

    _source_aware = field_validator("sourceEvaluatedAt")(_aware)
    _assessed_aware = field_validator("assessedAt")(_aware)
    _multiplier_finite = field_validator("recommendedRiskMultiplier")(_finite_decimal)

    @field_validator("agent")
    @classmethod
    def fixed_agent(cls, value: SupervisorAgentId) -> SupervisorAgentId:
        if value is not SupervisorAgentId.MM_SUPERVISOR:
            raise ValueError("agent must be MM_SUPERVISOR")
        return value

    @field_validator("mode")
    @classmethod
    def shadow_only(cls, value: SupervisorMode) -> SupervisorMode:
        if value is not SupervisorMode.SHADOW:
            raise ValueError("only SHADOW mode is enabled")
        return value

    @field_validator("recommendedRiskMultiplier")
    @classmethod
    def multiplier_non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("recommendedRiskMultiplier must be non-negative")
        return value

    @field_validator("confidence")
    @classmethod
    def confidence_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("confidence must be finite")
        return value

    @field_validator("reasons", "uncertainties", "recoveryConditions")
    @classmethod
    def bounded_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not value.strip():
                raise ValueError("text items must not be blank")
            if len(value) > cls.MAX_TEXT_LENGTH:
                raise ValueError("text item is too long")
        return values


class DomainSnapshot(SupervisorContract):
    freshness: Freshness
    evaluatedAt: datetime | None = None
    status: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    enabled: bool | None = None
    selectedMode: str | None = Field(default=None, max_length=100)
    dryRun: bool | None = None
    autoTradeEnabled: bool | None = None
    realOrderAllowed: bool | None = None
    mode: str | None = Field(default=None, max_length=100)
    executionEnabled: bool | None = None
    riskProfile: str | None = Field(default=None, max_length=100)
    locked: bool | None = None
    authoritativeRuntimeState: str | None = Field(default=None, max_length=100)
    synchronizationState: str | None = Field(default=None, max_length=100)
    pendingOrderState: str | None = Field(default=None, max_length=100)
    activeSymbol: str | None = Field(default=None, max_length=100)
    marketReady: bool | None = None
    marketStale: bool | None = None
    lastUpdate: datetime | None = None
    selectionMode: str | None = Field(default=None, max_length=100)
    selectionSource: str | None = Field(default=None, max_length=100)
    amsRuntimeState: str | None = Field(default=None, max_length=100)
    selectionCycleId: str | None = Field(default=None, max_length=100)
    safeSwitchState: str | None = Field(default=None, max_length=100)
    suitabilityEvidenceState: str | None = Field(default=None, max_length=100)
    backendStatus: str | None = Field(default=None, max_length=100)
    runtimeHealthy: bool | None = None
    fieldStates: tuple[FieldValueObservation, ...] = Field(default=(), max_length=30)

    @field_validator("evaluatedAt", "lastUpdate")
    @classmethod
    def timestamp_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)


class MoneyManagementSnapshot(SupervisorContract):
    capitalAuthority: str | None = Field(default=None, max_length=100)
    capitalSource: CapitalSource = CapitalSource.UNKNOWN
    equity: Decimal | None = None
    availableCapital: Decimal | None = None
    mmMode: str | None = Field(default=None, max_length=100)
    mmRegime: str | None = Field(default=None, max_length=100)
    riskBudget: Decimal | None = None
    remainingExposure: Decimal | None = None
    remainingPositionCapacity: Decimal | None = None
    ruinGuardStatus: str | None = Field(default=None, max_length=100)
    compoundingEnabled: bool | None = None
    executionEntryAllowed: bool | None = None
    policyVersion: str | None = Field(default=None, max_length=100)
    evaluatedAt: datetime | None = None
    authorityFresh: bool | None = None
    drawdown: Decimal | None = None
    currentExposure: Decimal | None = None
    openPositionState: str | None = Field(default=None, max_length=100)
    reasonCodes: tuple[str, ...] = Field(default=(), max_length=50)
    freshness: Freshness = Freshness.UNKNOWN
    fieldStates: tuple[FieldValueObservation, ...] = Field(default=(), max_length=30)

    @field_validator(
        "equity", "availableCapital", "riskBudget", "remainingExposure",
        "remainingPositionCapacity", "drawdown", "currentExposure", mode="before"
    )
    @classmethod
    def finite_decimals(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("Decimal fields do not accept float input")
        return _finite_number(value)

    @field_validator("evaluatedAt")
    @classmethod
    def timestamp_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)

    @field_validator("reasonCodes")
    @classmethod
    def reason_codes_bounded(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("reason code must be non-blank and at most 100 characters")
        return values


class SnapshotWarning(SupervisorContract):
    code: SupervisorFailureCode
    domain: str = Field(min_length=1, max_length=100)
    field: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=300)
    sourceEvaluatedAt: datetime | None = None

    @field_validator("sourceEvaluatedAt")
    @classmethod
    def timestamp_aware(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _aware(value)


class ReadOnlySupervisorSnapshot(SupervisorContract):
    schemaVersion: int = Field(default=1, ge=1, le=1)
    capturedAt: datetime
    overallFreshness: Freshness
    bot: DomainSnapshot
    loop: DomainSnapshot
    trade: DomainSnapshot
    governance: DomainSnapshot
    emergency: DomainSnapshot
    execution: DomainSnapshot
    market: DomainSnapshot
    decision: DomainSnapshot
    health: DomainSnapshot
    moneyManagement: MoneyManagementSnapshot
    warnings: tuple[SnapshotWarning, ...] = Field(default=(), max_length=50)

    @field_validator("capturedAt")
    @classmethod
    def captured_aware(cls, value: datetime) -> datetime:
        return _aware(value)



class MasterSupervisorDecision(SupervisorContract):
    schemaVersion: int = Field(default=1, ge=1, le=1)
    agent: SupervisorAgentId = SupervisorAgentId.MASTER_SUPERVISOR
    mode: SupervisorMode = SupervisorMode.SHADOW
    overallPosture: SupervisorState
    tradingRecommendation: TradingRecommendation
    mmRecommendation: MMRecommendedAction
    humanAttention: HumanAttention
    summary: str = Field(min_length=1, max_length=300)
    reasons: tuple[str, ...] = Field(max_length=20)
    conflicts: tuple[str, ...] = Field(default=(), max_length=20)
    uncertainties: tuple[str, ...] = Field(default=(), max_length=20)
    nextReviewConditions: tuple[str, ...] = Field(default=(), max_length=20)
    sourceEvaluatedAt: datetime
    decidedAt: datetime

    MAX_SUMMARY_LENGTH: ClassVar[int] = 300
    MAX_TEXT_LENGTH: ClassVar[int] = 500
    grantsExecutionAuthority: ClassVar[bool] = False

    _source_aware = field_validator("sourceEvaluatedAt")(_aware)
    _decided_aware = field_validator("decidedAt")(_aware)

    @field_validator("agent")
    @classmethod
    def fixed_agent(cls, value: SupervisorAgentId) -> SupervisorAgentId:
        if value is not SupervisorAgentId.MASTER_SUPERVISOR:
            raise ValueError("agent must be MASTER_SUPERVISOR")
        return value

    @field_validator("mode")
    @classmethod
    def shadow_only(cls, value: SupervisorMode) -> SupervisorMode:
        if value is not SupervisorMode.SHADOW:
            raise ValueError("only SHADOW mode is enabled")
        return value

    @field_validator("summary")
    @classmethod
    def summary_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value

    @field_validator("reasons", "conflicts", "uncertainties", "nextReviewConditions")
    @classmethod
    def bounded_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > cls.MAX_TEXT_LENGTH for value in values):
            raise ValueError("text item must be non-blank and at most 500 characters")
        return values


class FreshnessPolicy(SupervisorContract):
    """Caller-supplied thresholds; this contract deliberately chooses no defaults."""

    maxAgeSecondsByDomain: tuple[tuple[str, int], ...]

    @field_validator("maxAgeSecondsByDomain")
    @classmethod
    def validate_thresholds(cls, values: tuple[tuple[str, int], ...]) -> tuple[tuple[str, int], ...]:
        domains: set[str] = set()
        for domain, seconds in values:
            if not domain.strip() or domain in domains or seconds <= 0:
                raise ValueError("threshold domains must be unique and seconds positive")
            domains.add(domain)
        return values
