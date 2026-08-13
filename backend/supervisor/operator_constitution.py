"""Immutable and versioned operating constitution for the Master Supervisor."""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator

from .contracts import SupervisorContract


CONSTITUTION_ID = "TRADINGAI_OPERATOR_CONSTITUTION"
CONSTITUTION_VERSION = "1.0"


class OperatorConstitution(SupervisorContract):
    constitutionId: Literal["TRADINGAI_OPERATOR_CONSTITUTION"]
    constitutionVersion: Literal["1.0"]
    longTermSurvivalRequired: Literal[True]
    capitalProtectionRequired: Literal[True]
    profitPursuitAllowed: Literal[True]
    compoundingAllowedWithinPolicy: Literal[True]
    riskContractionOnDegradation: Literal[True]
    hardSafetyAlwaysOverrides: Literal[True]
    governanceAlwaysOverrides: Literal[True]
    agentMayRewriteConstitution: Literal[False]
    effectiveAt: datetime

    @field_validator("effectiveAt")
    @classmethod
    def aware_effective_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("constitution effectiveAt must be timezone-aware")
        return value

    def digest(self) -> str:
        return sha256(self.stable_json().encode("utf-8")).hexdigest()


class ConstitutionIdentity(SupervisorContract):
    constitutionId: Literal["TRADINGAI_OPERATOR_CONSTITUTION"]
    constitutionVersion: Literal["1.0"]
    constitutionDigest: str = Field(pattern=r"^[0-9a-f]{64}$")


def constitution_identity(
    constitution: OperatorConstitution,
) -> ConstitutionIdentity:
    return ConstitutionIdentity(
        constitutionId=constitution.constitutionId,
        constitutionVersion=constitution.constitutionVersion,
        constitutionDigest=constitution.digest(),
    )


TRADINGAI_OPERATOR_CONSTITUTION = OperatorConstitution(
    constitutionId=CONSTITUTION_ID,
    constitutionVersion=CONSTITUTION_VERSION,
    longTermSurvivalRequired=True,
    capitalProtectionRequired=True,
    profitPursuitAllowed=True,
    compoundingAllowedWithinPolicy=True,
    riskContractionOnDegradation=True,
    hardSafetyAlwaysOverrides=True,
    governanceAlwaysOverrides=True,
    agentMayRewriteConstitution=False,
    effectiveAt=datetime(2026, 8, 12, tzinfo=timezone.utc),
)
