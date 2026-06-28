# backend/schemas/governance.py

from pydantic import BaseModel
from typing import Literal


class ExecutionToggleRequest(BaseModel):
    execution_enabled: bool


class ModeRequest(BaseModel):
    mode: Literal[
        "PAPER",
        "LIVE",
        "DRY_RUN",
    ]


class RiskProfileRequest(BaseModel):
    risk_profile: Literal[
        "SAFE",
        "NORMAL",
        "AGGRESSIVE",
    ]