"""Validated baseline aggregates; no persistence or source lookup."""
from typing import Literal
from pydantic import Field, model_validator
from .monitoring_models import Contract, Observation, quality_reasons, quality_state


class Baseline(Contract):
    observation: Observation
    minimum_sample_size: int = Field(strict=True, ge=1, le=10**12)
    method: Literal['DEDUPLICATED_PROPORTION', 'DEDUPLICATED_DISTRIBUTION']

    @model_validator(mode='after')
    def compatible_method(self):
        if self.method != 'DEDUPLICATED_' + self.observation.unit:
            raise ValueError('baseline method and unit differ')
        return self

    @property
    def state(self):
        reasons = quality_reasons(self.observation)
        if 'SOURCE_CORRUPT' in reasons or self.observation.availability == 'INVALID':
            return 'INVALID'
        state = quality_state(reasons)
        if state:
            return 'UNAVAILABLE' if state == 'UNKNOWN' else state
        if self.observation.sample_size.denominator < self.minimum_sample_size:
            return 'INSUFFICIENT_DATA'
        return 'AVAILABLE'

    @property
    def baseline_value(self):
        return self.observation.value if self.state == 'AVAILABLE' else None

    @property
    def baseline_window(self):
        return self.observation.window
