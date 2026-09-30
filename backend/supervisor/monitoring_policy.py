"""V1 engineering screens, not statistical probabilities or trading rules."""
from typing import Literal
from pydantic import Field, model_validator
from .monitoring_models import Contract, Rate, Token


class EvaluationPolicy(Contract):
    policy_version: Token = 'monitoring-v1'
    direction: Literal['TWO_SIDED', 'HIGHER_IS_WORSE', 'LOWER_IS_WORSE'] = 'TWO_SIDED'
    proportion_info: Rate = 0.05
    proportion_warning: Rate = 0.10
    distribution_info: Rate = 0.10
    distribution_warning: Rate = 0.20
    standard_errors: float = Field(default=3, ge=3, allow_inf_nan=False)
    current_minimum: int = Field(default=100, strict=True, ge=100, le=10**12)
    baseline_minimum: int = Field(default=500, strict=True, ge=500, le=10**12)
    health_current_minimum: int = Field(default=10, strict=True, ge=10, le=10**12)
    health_baseline_minimum: int = Field(default=100, strict=True, ge=100, le=10**12)
    maximum_inputs: int = Field(default=128, strict=True, ge=1, le=800)

    @model_validator(mode='after')
    def thresholds(self):
        if not 0 < self.proportion_info < self.proportion_warning:
            raise ValueError('inconsistent proportion thresholds')
        if not 0 < self.distribution_info < self.distribution_warning:
            raise ValueError('inconsistent distribution thresholds')
        return self
