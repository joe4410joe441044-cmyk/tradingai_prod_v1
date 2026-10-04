"""Pure Phase 1 comparison, with explicit evidence for persistence and anomalies.

A single statistical WARNING candidate is INFO until three supplied consecutive
comparisons qualify. No history is fetched or retained. Critical findings are
separate observations and never inferred from a statistical deviation.
"""
from __future__ import annotations
from datetime import datetime
from math import sqrt
from typing import Literal
from pydantic import Field, field_validator, model_validator
from .baseline_models import Baseline
from .monitoring_models import (
    Availability, Bucket, Contract, Freshness, HEALTH_METRICS, Observation, Provenance,
    Rate, Samples, Severity, SourceReference, State, SUPPORTED_METRICS, Token,
    Window, aware, quality_reasons, quality_state,
)
from .monitoring_policy import EvaluationPolicy


class Comparison(Contract):
    current: Observation
    baseline: Baseline | None


class EvaluationInput(Comparison):
    # Chronological last two consecutive evaluations, including non-candidates.
    # A caller must not filter history down to only successful candidates.
    previous: tuple[Comparison, ...] = Field(default=(), max_length=2)


class Deviation(Contract):
    absolute: float
    relative: float | None
    total_variation: Rate | None = None


class DriftResult(Contract):
    schema_version: Literal['1'] = '1'
    policy_version: Token
    metric_version: Token
    observation_id: Token
    metric: Token
    current_value: Rate | tuple[Bucket, ...] | None
    baseline_value: Rate | tuple[Bucket, ...] | None
    deviation: Deviation | None
    direction: Literal['UP', 'DOWN', 'CHANGED', 'UNCHANGED', 'UNKNOWN']
    state: State
    severity: Severity
    category: Literal['STATISTICAL_DRIFT', 'OPERATIONAL_ANOMALY', 'MISSING_DATA', 'STALE_DATA', 'CORRUPTION', 'PARAMETER_REVISION', 'EXPECTED_REGIME_CHANGE']
    confidence: Literal['HIGH', 'MEDIUM', 'LOW', 'UNKNOWN']
    sample_size: tuple[Samples, ...]
    current_window: Window | None
    baseline_window: Window | None
    sources: tuple[SourceReference, ...]
    provenance: tuple[Provenance, ...]
    freshness: tuple[Freshness, ...]
    availability: tuple[Availability, ...]
    partial_result: bool
    uncertainty: tuple[Token, ...]
    warnings: tuple[Token, ...]
    reason_codes: tuple[Token, ...]
    first_seen_at: datetime
    last_seen_at: datetime
    _aware = field_validator('first_seen_at', 'last_seen_at')(aware)


def _group(observation):
    return {v.key: v.value for v in observation.grouping}


def _contract_reasons(current):
    group = _group(current)
    required = {'source', 'schema', 'producer_epoch'} if current.metric in HEALTH_METRICS else {
        'scope', 'mode', 'effective_revision', 'strategy_contract',
    }
    if current.metric == 'selected_symbol_distribution':
        required.add('selection_mode')
        if 'symbol' in group:
            return {'GROUPING_INVALID'}
    elif current.metric not in HEALTH_METRICS:
        required.add('symbol')
    if current.metric == 'entry_execution_rate':
        required.add('outcome')
        expected = 'PAPER_FILLED' if group.get('mode') == 'PAPER' else 'ORDER_SUBMITTED'
        if group.get('outcome') != expected:
            return {'OUTCOME_UNSUPPORTED'}
    if current.metric == 'rejection_block_rate':
        required.add('stage')
    if current.metric == 'detector_activation_rate':
        required.update(('detector', 'detector_version'))
    if current.metric == 'source_freshness_rate':
        required.add('freshness_policy')
        if not current.sources or any(not s.producer_heartbeat_available for s in current.sources):
            return {'PRODUCER_HEARTBEAT_UNAVAILABLE'}
    if any(group.get(k) in (None, 'UNKNOWN') for k in required):
        return {'GROUPING_UNAVAILABLE'}
    if 'mode' in group and group['mode'] not in ('PAPER', 'LIVE'):
        return {'GROUPING_INVALID'}
    expected_unit = 'DISTRIBUTION' if current.metric == 'selected_symbol_distribution' else 'PROPORTION'
    if current.unit != expected_unit:
        return {'UNIT_UNSUPPORTED'}
    return set()


def _screen(comparison, policy):
    current, baseline = comparison.current, comparison.baseline
    observations = (current,) if baseline is None else (current, baseline.observation)
    reasons = set().union(*(quality_reasons(o) for o in observations))
    state, severity, category = None, 'NONE', 'STATISTICAL_DRIFT'
    current_min = policy.health_current_minimum if current.metric in HEALTH_METRICS else policy.current_minimum
    baseline_min = policy.health_baseline_minimum if current.metric in HEALTH_METRICS else policy.baseline_minimum
    if (current.sample_size.denominator < current_min or
            (baseline is not None and baseline.observation.sample_size.denominator < max(baseline_min, baseline.minimum_sample_size))):
        reasons.add('MINIMUM_SAMPLE_UNMET')
    unsupported = current.metric not in SUPPORTED_METRICS
    if unsupported:
        reasons.add('METRIC_UNSUPPORTED')
    for observation in observations:
        reasons.update(_contract_reasons(observation))
    if baseline is None:
        reasons.add('BASELINE_MISSING')
    else:
        prior = baseline.observation
        if (prior.metric, prior.metric_version, prior.unit) != (current.metric, current.metric_version, current.unit):
            reasons.add('BASELINE_INCOMPARABLE')
        current_seconds, baseline_seconds = (900, 86400) if current.metric in HEALTH_METRICS else (3600, 604800)
        if ((current.window.end-current.window.start).total_seconds() != current_seconds
                or (prior.window.end-prior.window.start).total_seconds() != baseline_seconds
                or prior.window.end != current.window.start):
            reasons.add('WINDOW_PROFILE_MISMATCH')
        if prior.window.end > current.window.start:
            reasons.add('WINDOW_OVERLAP')
        if prior.window.time_authority != current.window.time_authority:
            reasons.add('TIME_AUTHORITY_MISMATCH')
        if prior.provenance and current.provenance:
            for key in ('source_schema', 'eligibility_predicate', 'numerator_definition', 'denominator_definition'):
                if getattr(prior.provenance, key) != getattr(current.provenance, key):
                    reasons.add('POPULATION_INCOMPARABLE')
        group, old_group = _group(current), _group(prior)
        if group != old_group:
            if {k: v for k, v in group.items() if k != 'effective_revision'} == {k: v for k, v in old_group.items() if k != 'effective_revision'}:
                reasons.add('PARAMETER_REVISION_BOUNDARY')
            else:
                reasons.add('GROUPING_INCOMPARABLE')
    invalid = reasons & {'BASELINE_MISSING', 'METRIC_UNSUPPORTED', 'BASELINE_INCOMPARABLE',
        'PRODUCER_HEARTBEAT_UNAVAILABLE', 'GROUPING_UNAVAILABLE', 'GROUPING_INVALID', 'GROUPING_INCOMPARABLE', 'UNIT_UNSUPPORTED',
        'OUTCOME_UNSUPPORTED', 'WINDOW_PROFILE_MISMATCH', 'WINDOW_OVERLAP', 'TIME_AUTHORITY_MISMATCH', 'POPULATION_INCOMPARABLE'}
    state = 'UNKNOWN' if invalid else quality_state(reasons)
    if state:
        category = 'CORRUPTION' if 'SOURCE_CORRUPT' in reasons else ('STALE_DATA' if state == 'STALE' else 'MISSING_DATA')
        return state, severity, category, reasons, None, 'UNKNOWN', False
    if 'PARAMETER_REVISION_BOUNDARY' in reasons:
        return 'INFO', 'INFO', 'PARAMETER_REVISION', reasons, None, 'UNKNOWN', False
    if 'MINIMUM_SAMPLE_UNMET' in reasons:
        return 'INSUFFICIENT_DATA', 'INFO', 'MISSING_DATA', reasons, None, 'UNKNOWN', False
    prior = baseline.observation
    if current.unit == 'DISTRIBUTION':
        a = {b.category: b.count / current.sample_size.denominator for b in current.value}
        b = {b.category: b.count / prior.sample_size.denominator for b in prior.value}
        delta = 0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in sorted(a.keys() | b.keys()))
        deviation = Deviation(absolute=delta, relative=None, total_variation=delta)
        direction = 'CHANGED' if delta else 'UNCHANGED'
        info = delta + 1e-12 >= policy.distribution_info
        candidate = delta + 1e-12 >= policy.distribution_warning
    else:
        delta = current.value - prior.value
        direction = 'UP' if delta > 0 else ('DOWN' if delta < 0 else 'UNCHANGED')
        deviation = Deviation(absolute=delta, relative=delta / prior.value if prior.value else None)
        if prior.value == 0:
            reasons.add('BASELINE_ZERO')
        adverse = abs(delta) if policy.direction == 'TWO_SIDED' else max(0, delta if policy.direction == 'HIGHER_IS_WORSE' else -delta)
        error = sqrt(current.value * (1-current.value) / current.sample_size.denominator + prior.value * (1-prior.value) / prior.sample_size.denominator)
        info = adverse + 1e-12 >= policy.proportion_info
        candidate = adverse + 1e-12 >= policy.proportion_warning and (error == 0 or adverse + 1e-12 >= policy.standard_errors * error)
    if candidate:
        reasons.add('WARNING_CANDIDATE')
    elif info:
        reasons.add('INFO_THRESHOLD')
    else:
        reasons.add('BELOW_THRESHOLD')
    return ('INFO' if info else 'NORMAL'), ('INFO' if info else 'NONE'), category, reasons, deviation, direction, candidate


def evaluate(item: EvaluationInput, policy: EvaluationPolicy) -> DriftResult:
    state, severity, category, reasons, deviation, direction, candidate = _screen(item, policy)
    current = item.current
    observations = (current,) if item.baseline is None else (current, item.baseline.observation)
    if candidate or state == 'STALE':
        history = item.previous + (Comparison(current=current, baseline=item.baseline),)
        comparable = len(history) == 3 and all(
            h.current.grouping == current.grouping and h.current.metric == current.metric
            and h.current.metric_version == current.metric_version
            and h.current.provenance is not None
            and all(getattr(h.current.provenance, k) == getattr(current.provenance, k)
                    for k in ('source_schema', 'eligibility_predicate', 'numerator_definition', 'denominator_definition'))
            and h.current.unit == current.unit
            and (_screen(h, policy)[-1] if candidate else _screen(h, policy)[0] == 'STALE') for h in history
        )
        advancing = all(a.current.window.end < b.current.window.end for a, b in zip(history, history[1:]))
        if comparable and advancing and (candidate or (current.window.end-history[0].current.window.end).total_seconds() >= 120):
            severity = 'WARNING'
            if candidate:
                state = 'WARNING'
            reasons.add('THREE_CONSECUTIVE_CANDIDATES' if candidate else 'PERSISTENT_REQUIRED_SOURCE_STALE')
        else:
            reasons.add('PERSISTENCE_UNCONFIRMED')
    sources = tuple(sorted({s.stable_json(): s for o in observations for s in o.sources}.values(), key=lambda s: s.stable_json()))
    provenance = tuple(sorted({o.provenance.stable_json(): o.provenance for o in observations if o.provenance}.values(), key=lambda p: p.stable_json()))
    confidence = 'UNKNOWN' if deviation is None else ('MEDIUM' if any(s.integrity != 'VERIFIED' for s in sources) else 'HIGH')
    # Identity includes current/baseline windows, groups, sources, coverage and policy,
    # as well as bounded supplied persistence evidence; no time-of-call salt.
    identity = ContractIdentity(input=item, policy=policy).canonical_digest()
    return DriftResult(
        policy_version=policy.policy_version, metric_version=current.metric_version,
        observation_id=identity, metric=current.metric,
        current_value=current.value if deviation else None,
        baseline_value=item.baseline.baseline_value if deviation else None,
        deviation=deviation, direction=direction, state=state, severity=severity,
        category=category, confidence=confidence,
        sample_size=tuple(o.sample_size for o in observations), current_window=current.window,
        baseline_window=item.baseline.baseline_window if item.baseline else None,
        sources=sources, provenance=provenance,
        freshness=tuple(sorted({o.freshness for o in observations} | {s.freshness for s in sources})),
        availability=tuple(sorted({o.availability for o in observations} | {s.availability for s in sources} | ({'UNAVAILABLE'} if state == 'UNKNOWN' else set()))),
        partial_result='COVERAGE_PARTIAL' in reasons,
        uncertainty=tuple(sorted({u for o in observations for u in o.uncertainty})),
        warnings=tuple(sorted({w for o in observations for w in o.warnings})),
        reason_codes=tuple(sorted(reasons)), first_seen_at=current.window.end, last_seen_at=current.window.end,
    )


class ContractIdentity(Contract):
    input: EvaluationInput
    policy: EvaluationPolicy


class IdentityAssertion(Contract):
    """Two authoritative assertions expected to agree at one aligned version."""
    scope: Token
    mode: Literal['PAPER', 'LIVE']
    entity_id: Token
    event_version: Token
    field: Literal['linked_position', 'linked_order', 'linked_account', 'effective_revision', 'execution_permission']
    value: Token
    source: SourceReference


class Contradiction(Contract):
    left: IdentityAssertion
    right: IdentityAssertion
    window: Window

    @model_validator(mode='after')
    def proof(self):
        for name in ('scope', 'mode', 'entity_id', 'event_version', 'field'):
            if getattr(self.left, name) != getattr(self.right, name):
                raise ValueError('contradiction requires aligned authoritative identity')
        if self.left.value == self.right.value:
            raise ValueError('matching assertions are not a contradiction')
        for item in (self.left, self.right):
            if (item.source.availability != 'AVAILABLE' or item.source.freshness != 'FRESH'
                    or item.source.age_seconds > item.source.max_age_seconds
                    or item.source.unsupported_filters or item.source.integrity != 'VERIFIED'):
                raise ValueError('contradiction requires fresh verified authority')
            if not self.window.start <= item.source.observed_at < self.window.end:
                raise ValueError('assertions outside aligned window')
        if self.left.source == self.right.source:
            raise ValueError('distinct assertion evidence required')
        return self


def evaluate_contradiction(proof: Contradiction, policy: EvaluationPolicy):
    sources = tuple(sorted((proof.left.source, proof.right.source), key=lambda s: s.stable_json()))
    return DriftResult(
        policy_version=policy.policy_version, metric_version='1',
        observation_id=ContradictionIdentity(proof=proof, policy=policy).canonical_digest(), metric='identity_contradiction',
        current_value=None, baseline_value=None, deviation=None, direction='UNKNOWN',
        state='CRITICAL', severity='CRITICAL', category='OPERATIONAL_ANOMALY', confidence='HIGH',
        sample_size=(), current_window=proof.window, baseline_window=None,
        sources=sources, provenance=(), freshness=('FRESH',), availability=('AVAILABLE',),
        partial_result=False, uncertainty=(), warnings=(), reason_codes=('PROVEN_IDENTITY_CONTRADICTION',),
        first_seen_at=proof.window.end, last_seen_at=proof.window.end,
    )


class ContradictionIdentity(Contract):
    proof: Contradiction
    policy: EvaluationPolicy


def evaluate_corruption(item: EvaluationInput, policy: EvaluationPolicy) -> tuple[DriftResult, ...]:
    """Separate integrity observations, even when a statistical cohort is partial.

    Persistence requires the same offending record/digest/revision in three
    distinct explicit scan IDs, advancing endpoints spanning at least 120s.
    This is supplied evidence only, not a stateful episode or retained counter.
    """
    observations = (item.current,) if item.baseline is None else (item.current, item.baseline.observation)
    corrupt = {(s.source, s.record_id, s.revision, s.digest): s
               for o in observations for s in o.sources if s.integrity == 'CORRUPT'}
    results = []
    history = item.previous + (Comparison(current=item.current, baseline=item.baseline),)
    for identity, source in sorted(corrupt.items()):
        matching = len(history) == 3 and all(
            h.current.provenance and h.current.grouping == item.current.grouping
            and h.current.metric == item.current.metric
            and any((s.source, s.record_id, s.revision, s.digest) == identity and s.integrity == 'CORRUPT'
                    for s in h.current.sources) for h in history)
        persistent = (matching and len({h.current.provenance.scan_id for h in history}) == 3
            and all(a.current.window.end < b.current.window.end for a, b in zip(history, history[1:]))
            and (item.current.window.end-history[0].current.window.end).total_seconds() >= 120)
        severity = 'CRITICAL' if persistent else 'INFO'
        # Hash includes the comparison/policy and the precise offending identity.
        identity_payload = CorruptionIdentity(input=item, policy=policy, source=source)
        results.append(DriftResult(
            policy_version=policy.policy_version, metric_version='1',
            observation_id=identity_payload.canonical_digest(), metric='source_corruption',
            current_value=None, baseline_value=None, deviation=None, direction='UNKNOWN',
            state=severity, severity=severity, category='CORRUPTION', confidence='HIGH',
            sample_size=(), current_window=item.current.window, baseline_window=None,
            sources=(source,), provenance=tuple(o.provenance for o in observations if o.provenance),
            freshness=(source.freshness,), availability=(source.availability,),
            partial_result=False, uncertainty=(), warnings=(),
            reason_codes=('PERSISTENT_CORRUPTION' if persistent else 'CORRUPTION_OBSERVED',),
            first_seen_at=item.current.window.end, last_seen_at=item.current.window.end,
        ))
    return tuple(results)


class CorruptionIdentity(Contract):
    input: EvaluationInput
    policy: EvaluationPolicy
    source: SourceReference
