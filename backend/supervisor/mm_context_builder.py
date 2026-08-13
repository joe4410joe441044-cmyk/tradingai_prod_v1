"""Allow-listed Money Management context for the MM SHADOW provider."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator

from .contracts import (
    CapitalSource,
    FieldValueObservation,
    Freshness,
    ReadOnlySupervisorSnapshot,
    SnapshotWarning,
    SupervisorContract,
)


class MMShadowContext(SupervisorContract):
    snapshotSchemaVersion: int = Field(ge=1)
    snapshotCapturedAt: datetime
    overallFreshness: Freshness
    capitalAuthority: str | None = Field(default=None, max_length=100)
    capitalSource: CapitalSource
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
    mmEvaluatedAt: datetime | None = None
    authorityFresh: bool | None = None
    drawdown: Decimal | None = None
    currentExposure: Decimal | None = None
    openPositionState: str | None = Field(default=None, max_length=100)
    reasonCodes: tuple[str, ...] = Field(default=(), max_length=50)
    mmFreshness: Freshness
    warnings: tuple[SnapshotWarning, ...] = Field(default=(), max_length=50)
    fieldStates: tuple[FieldValueObservation, ...] = Field(default=(), max_length=30)

    @field_validator(
        "equity",
        "availableCapital",
        "riskBudget",
        "remainingExposure",
        "remainingPositionCapacity",
        "drawdown",
        "currentExposure",
        mode="before",
    )
    @classmethod
    def exact_finite_decimals(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("MM context does not accept float input")
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("MM context decimal must be finite")
        return value

    @field_validator("snapshotCapturedAt", "mmEvaluatedAt")
    @classmethod
    def aware_timestamps(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("MM context timestamp must be timezone-aware")
        return value

    @field_validator("reasonCodes")
    @classmethod
    def bounded_reason_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() or len(value) > 100 for value in values):
            raise ValueError("reason code must be non-blank and bounded")
        return values


def build_mm_shadow_context(snapshot: ReadOnlySupervisorSnapshot) -> MMShadowContext:
    """Copy only the typed MM observation; never expose the complete snapshot."""
    mm = snapshot.moneyManagement
    warnings = tuple(
        item for item in snapshot.warnings if item.domain == "moneyManagement"
    )
    return MMShadowContext(
        snapshotSchemaVersion=snapshot.schemaVersion,
        snapshotCapturedAt=snapshot.capturedAt,
        overallFreshness=snapshot.overallFreshness,
        capitalAuthority=mm.capitalAuthority,
        capitalSource=mm.capitalSource,
        equity=mm.equity,
        availableCapital=mm.availableCapital,
        mmMode=mm.mmMode,
        mmRegime=mm.mmRegime,
        riskBudget=mm.riskBudget,
        remainingExposure=mm.remainingExposure,
        remainingPositionCapacity=mm.remainingPositionCapacity,
        ruinGuardStatus=mm.ruinGuardStatus,
        compoundingEnabled=mm.compoundingEnabled,
        executionEntryAllowed=mm.executionEntryAllowed,
        policyVersion=mm.policyVersion,
        mmEvaluatedAt=mm.evaluatedAt,
        authorityFresh=mm.authorityFresh,
        drawdown=mm.drawdown,
        currentExposure=mm.currentExposure,
        openPositionState=mm.openPositionState,
        reasonCodes=mm.reasonCodes,
        mmFreshness=mm.freshness,
        warnings=warnings,
        fieldStates=mm.fieldStates,
    )
