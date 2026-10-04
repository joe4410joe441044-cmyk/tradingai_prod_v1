"""Pure bounded aggregate evidence. Caller supplies canonical deduplicated counts.

No reader, clock, environment, provider or authority capability is accepted.
Coverage is explicit evidence, never inferred from a page or minimum count.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from typing import Annotated, Literal
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

def sanitized_token(value):
    upper = value.upper().replace('-', '_')
    if (any(marker in upper for marker in ('API_KEY', 'APIKEY', 'PASSWORD', 'PRIVATE_KEY', 'SECRET', 'BEARER'))
            or value.startswith(('sk-', 'eyJ'))):
        raise ValueError('secret-like material is not an evidence identifier')
    return value


Token = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$"), AfterValidator(sanitized_token)]
Count = Annotated[int, Field(strict=True, ge=0, le=10**12)]
Rate = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]
State = Literal['NORMAL', 'INFO', 'WARNING', 'CRITICAL', 'UNKNOWN', 'INSUFFICIENT_DATA', 'STALE', 'PARTIAL']
Severity = Literal['NONE', 'INFO', 'WARNING', 'CRITICAL']
Availability = Literal['AVAILABLE', 'UNAVAILABLE', 'NOT_CAPTURED', 'NOT_APPLICABLE', 'INVALID', 'PARTIAL', 'EMPTY', 'NOT_AVAILABLE', 'UNSUPPORTED_FILTER', 'ERROR']
Freshness = Literal['FRESH', 'STALE', 'UNKNOWN', 'NOT_APPLICABLE']
SUPPORTED_METRICS = ('entry_candidate_rate', 'entry_execution_rate', 'rejection_block_rate',
    'detector_activation_rate', 'selected_symbol_distribution', 'evidence_missing_rate',
    'evidence_corruption_rate', 'source_freshness_rate')
HEALTH_METRICS = ('evidence_missing_rate', 'evidence_corruption_rate', 'source_freshness_rate')


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone required')
    return value.astimezone(timezone.utc)


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, allow_inf_nan=False)

    def stable_json(self):
        return json.dumps(self.model_dump(mode='json'), sort_keys=True,
                          separators=(',', ':'), ensure_ascii=False, allow_nan=False)

    def canonical_digest(self):
        return sha256(self.stable_json().encode()).hexdigest()


class Window(Contract):
    start: datetime
    end: datetime
    time_authority: Literal['SOURCE_EVENT', 'SOURCE_OBSERVATION']
    _aware = field_validator('start', 'end')(aware)

    @model_validator(mode='after')
    def ordered(self):
        if self.start >= self.end:
            raise ValueError('empty or reversed half-open UTC window')
        return self


class Dimension(Contract):
    key: Token
    value: Token


class SourceReference(Contract):
    source: Token
    record_id: Token
    revision: Token
    digest: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    availability: Availability
    freshness: Freshness
    freshness_policy: Token
    observed_at: datetime
    age_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    max_age_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    freshness_reason: Token
    integrity: Literal['VERIFIED', 'UNKNOWN', 'CORRUPT']
    producer_heartbeat_available: bool
    unsupported_filters: tuple[Token, ...] = Field(default=(), max_length=32)
    _aware = field_validator('observed_at')(aware)

    @field_validator('unsupported_filters')
    @classmethod
    def ordered(cls, value):
        return tuple(sorted(set(value)))


class Provenance(Contract):
    source_schema: Token
    scan_id: Token
    read_method: Token
    query_digest: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    population_digest: Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]
    coverage_proof: Token | None
    eligibility_predicate: Token
    numerator_definition: Token
    denominator_definition: Token
    deduplication: Literal['CANONICAL_RECORD_ID']
    complete: bool

    @model_validator(mode='after')
    def coverage(self):
        if self.complete and self.coverage_proof is None:
            raise ValueError('complete population requires coverage proof')
        return self


class Samples(Contract):
    numerator: Count | None
    denominator: Count
    eligible: Count
    excluded: Count = 0
    unknown: Count = 0
    duplicates_removed: Count = 0

    @model_validator(mode='after')
    def counts(self):
        if self.eligible != self.denominator:
            raise ValueError('denominator must equal eligible population')
        if self.numerator is not None and self.numerator > self.denominator:
            raise ValueError('numerator exceeds denominator')
        return self


class Bucket(Contract):
    category: Token
    count: Count


class Observation(Contract):
    metric: Token
    metric_version: Token = '1'
    unit: Literal['PROPORTION', 'DISTRIBUTION'] = 'PROPORTION'
    value: Rate | Annotated[tuple[Bucket, ...], Field(max_length=128)] | None
    observed_at: datetime
    window: Window
    sample_size: Samples
    grouping: tuple[Dimension, ...] = Field(max_length=16)
    sources: tuple[SourceReference, ...] = Field(max_length=32)
    provenance: Provenance | None
    freshness: Freshness
    availability: Availability
    partial_result: bool = False
    uncertainty: tuple[Token, ...] = Field(default=(), max_length=32)
    warnings: tuple[Token, ...] = Field(default=(), max_length=32)
    _aware = field_validator('observed_at')(aware)

    @field_validator('warnings', 'uncertainty')
    @classmethod
    def codes(cls, value):
        return tuple(sorted(set(value)))

    @field_validator('grouping')
    @classmethod
    def groups(cls, value):
        if len({v.key for v in value}) != len(value):
            raise ValueError('duplicate grouping key')
        return tuple(sorted(value, key=lambda v: v.key))

    @field_validator('sources')
    @classmethod
    def references(cls, value):
        if len({(v.source, v.record_id) for v in value}) != len(value):
            raise ValueError('duplicate source reference')
        return tuple(sorted(value, key=lambda v: v.stable_json()))

    @field_validator('value')
    @classmethod
    def buckets(cls, value):
        if isinstance(value, tuple):
            if len({v.category for v in value}) != len(value):
                raise ValueError('duplicate distribution category')
            return tuple(sorted(value, key=lambda v: v.category))
        return value

    @model_validator(mode='after')
    def evidence(self):
        if self.observed_at < self.window.end:
            raise ValueError('observation precedes completed window')
        if self.availability == 'EMPTY' and self.sample_size.denominator != 0:
            raise ValueError('empty source cannot contain samples')
        if self.availability == 'AVAILABLE' and (not self.sources or not self.provenance):
            raise ValueError('available evidence requires sources and provenance')
        if any(source.observed_at > self.observed_at for source in self.sources):
            raise ValueError('source observation after aggregate observation')
        if self.value is not None:
            if self.sample_size.denominator == 0:
                raise ValueError('zero denominator cannot supply value')
            if self.unit == 'DISTRIBUTION':
                if not isinstance(self.value, tuple) or sum(b.count for b in self.value) != self.sample_size.denominator:
                    raise ValueError('distribution must cover denominator')
            elif isinstance(self.value, tuple) or self.sample_size.numerator is None or not math.isclose(
                self.value, self.sample_size.numerator / self.sample_size.denominator, rel_tol=0, abs_tol=1e-12,
            ):
                raise ValueError('rate must agree with explicit numerator and denominator')
        return self

    @computed_field
    @property
    def observation_id(self) -> str:
        payload = json.dumps(self.model_dump(mode='json', exclude={'observation_id'}),
                             sort_keys=True, separators=(',', ':'), allow_nan=False)
        return sha256(payload.encode()).hexdigest()

    @property
    def window_start(self):
        return self.window.start

    @property
    def window_end(self):
        return self.window.end


def quality_reasons(observation):
    reasons = set()
    if observation.availability not in ('AVAILABLE', 'PARTIAL', 'EMPTY'):
        reasons.add('AUTHORITY_UNAVAILABLE')
    if observation.value is None and observation.sample_size.denominator:
        reasons.add('VALUE_MISSING')
    if not observation.sources or not observation.provenance:
        reasons.add('PROVENANCE_MISSING')
    if observation.freshness == 'UNKNOWN':
        reasons.add('FRESHNESS_UNKNOWN')
    if observation.freshness == 'STALE':
        reasons.add('SOURCE_STALE')
    if observation.partial_result or observation.availability == 'PARTIAL' or observation.sample_size.unknown:
        reasons.add('COVERAGE_PARTIAL')
    if observation.provenance and not observation.provenance.complete:
        reasons.add('COVERAGE_PARTIAL')
    for source in observation.sources:
        if source.availability not in ('AVAILABLE', 'PARTIAL', 'EMPTY') or source.unsupported_filters:
            reasons.add('AUTHORITY_UNAVAILABLE')
        if source.availability == 'PARTIAL':
            reasons.add('COVERAGE_PARTIAL')
        if (source.freshness == 'STALE' or source.age_seconds > source.max_age_seconds
                or (observation.metric == 'source_freshness_rate' and source.age_seconds > 120)):
            reasons.add('SOURCE_STALE')
        if source.freshness == 'UNKNOWN':
            reasons.add('FRESHNESS_UNKNOWN')
        if source.integrity == 'CORRUPT':
            reasons.add('SOURCE_CORRUPT')
    return tuple(sorted(reasons))


def quality_state(reasons):
    if set(reasons) & {'AUTHORITY_UNAVAILABLE', 'PROVENANCE_MISSING', 'FRESHNESS_UNKNOWN', 'SOURCE_CORRUPT'}:
        return 'UNKNOWN'
    if 'SOURCE_STALE' in reasons:
        return 'STALE'
    if 'COVERAGE_PARTIAL' in reasons:
        return 'PARTIAL'
    if 'VALUE_MISSING' in reasons:
        return 'UNKNOWN'
    return None
