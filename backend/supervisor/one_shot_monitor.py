"""One synchronous, bounded, in-memory evaluation; no I/O or retained state.

Inputs are keyed by caller-supplied sanitized request IDs. Validation failures
are isolated per key. Policy/budget/type errors at the call boundary raise;
they are configuration/programmer errors, not missing evidence.
"""
from datetime import datetime, timedelta
from hashlib import sha256
from pydantic import ValidationError, TypeAdapter
from .drift_evaluator import (
    Contradiction, DriftResult, EvaluationInput, evaluate, evaluate_contradiction, evaluate_corruption,
)
from .monitoring_models import Contract, State, Token, aware
from .monitoring_policy import EvaluationPolicy


_KEY_ADAPTER = TypeAdapter(Token)


class SummaryCount(Contract):
    code: Token
    count: int


class MonitorResult(Contract):
    results: tuple[DriftResult, ...]
    aggregate_status: State
    availability_summary: tuple[SummaryCount, ...]
    freshness_summary: tuple[SummaryCount, ...]
    state_summary: tuple[SummaryCount, ...]
    partial_result: bool
    warnings: tuple[Token, ...]
    requested_count: int
    evaluated_count: int
    invalid_count: int
    result_count: int
    evaluated_at: datetime


def _summary(values):
    counts = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return tuple(SummaryCount(code=k, count=v) for k, v in sorted(counts.items()))


def _bounded_data(value):
    """Bound raw JSON before Pydantic validation; never traverse arbitrary objects."""
    pending = [(value, 0)]
    nodes = characters = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 16000 or depth > 16:
            raise ValueError('INPUT_STRUCTURE_BUDGET')
        if type(item) is dict:
            if len(item) > 256 or any(type(k) is not str for k in item):
                raise ValueError('INPUT_STRUCTURE_BUDGET')
            pending.extend((k, depth+1) for k in item)
            pending.extend((v, depth+1) for v in item.values())
        elif type(item) in (tuple, list):
            if len(item) > 256:
                raise ValueError('INPUT_STRUCTURE_BUDGET')
            pending.extend((v, depth+1) for v in item)
        elif type(item) is str:
            characters += len(item)
            if len(item) > 1024 or characters > 65536:
                raise ValueError('INPUT_TEXT_BUDGET')
        elif item is not None and type(item) not in (int, float, bool, datetime):
            raise TypeError('inputs must contain JSON primitives or explicit datetime values')


def _invalid(key, policy, evaluated_at, code):
    return DriftResult(
        policy_version=policy.policy_version, metric_version='1',
        observation_id=sha256((key + ':' + code).encode()).hexdigest(), metric=key,
        current_value=None, baseline_value=None, deviation=None, direction='UNKNOWN',
        state='UNKNOWN', severity='NONE', category='MISSING_DATA', confidence='UNKNOWN',
        sample_size=(), current_window=None, baseline_window=None, sources=(), provenance=(),
        freshness=('UNKNOWN',), availability=('INVALID',), partial_result=True,
        uncertainty=('INVALID_INPUT',), warnings=(code,), reason_codes=('INVALID_INPUT',),
        first_seen_at=evaluated_at, last_seen_at=evaluated_at,
    )


def one_shot_monitor(inputs: dict, *, policy: EvaluationPolicy, evaluated_at: datetime,
                     contradictions: tuple[Contradiction, ...] = ()) -> MonitorResult:
    if type(inputs) is not dict or type(contradictions) is not tuple:
        raise TypeError('bounded dict and tuple required; iterators are not accepted')
    policy = EvaluationPolicy.model_validate(policy.model_dump())
    evaluated_at = aware(evaluated_at)
    if len(inputs) + len(contradictions) > policy.maximum_inputs:
        raise ValueError('INPUT_COUNT_BUDGET')
    for key in inputs:
        _KEY_ADAPTER.validate_python(key)
    results = []
    invalid = 0
    for key, raw in sorted(inputs.items()):
        if isinstance(raw, EvaluationInput):
            raw = raw.model_dump(exclude={'current': {'observation_id'}, 'baseline': {'observation': {'observation_id'}}, 'previous': {'__all__': {'current': {'observation_id'}, 'baseline': {'observation': {'observation_id'}}}}})
        _budget_code = None
        try:
            _bounded_data(raw)
        except ValueError as error:
            _budget_code = str(error)
        if _budget_code:
            results.append(_invalid(key, policy, evaluated_at, _budget_code))
            invalid += 1
            continue
        try:
            item = EvaluationInput.model_validate(raw)
        except ValidationError:
            # Do not echo input values or exception messages (potential secrets).
            results.append(_invalid(key, policy, evaluated_at, 'MODEL_VALIDATION_FAILED'))
            invalid += 1
            continue
        comparisons = item.previous + (item,)
        evidence = tuple(o for c in comparisons for o in
                         ((c.current,) if c.baseline is None else (c.current, c.baseline.observation)))
        if any(o.observed_at > evaluated_at for o in evidence):
            results.append(_invalid(key, policy, evaluated_at, 'OBSERVATION_AFTER_EVALUATION'))
            invalid += 1
            continue
        cutoff = evaluated_at.replace(second=0, microsecond=0) - timedelta(seconds=120)
        if item.current.window.end > cutoff:
            results.append(_invalid(key, policy, evaluated_at, 'WINDOW_AFTER_COMPLETED_CUTOFF'))
            invalid += 1
            continue
        results.append(evaluate(item, policy))
        results.extend(evaluate_corruption(item, policy))
    for proof in contradictions:
        proof = Contradiction.model_validate(proof.model_dump())
        if proof.window.end > evaluated_at:
            raise ValueError('contradiction after evaluation cutoff')
        results.append(evaluate_contradiction(proof, policy))
    results = tuple(sorted(results, key=lambda r: (r.metric, r.observation_id)))
    # Severity cannot be masked by data-quality precedence. All quality states
    # also remain visible in summaries and the partial flag.
    priority = ('CRITICAL', 'WARNING', 'UNKNOWN', 'STALE', 'PARTIAL', 'INSUFFICIENT_DATA', 'INFO', 'NORMAL')
    states = {r.state for r in results}
    states.update(r.severity for r in results if r.severity != 'NONE')
    aggregate = next((s for s in priority if s in states), 'UNKNOWN')
    partial = not results or any(r.partial_result or r.state in ('UNKNOWN', 'STALE', 'PARTIAL', 'INSUFFICIENT_DATA') for r in results)
    warnings = {w for r in results for w in r.warnings}
    if partial:
        warnings.add('INCOMPLETE_EVALUATION')
    if not results:
        warnings.add('EMPTY_INPUT')
    return MonitorResult(
        results=results, aggregate_status=aggregate,
        availability_summary=_summary(v for r in results for v in r.availability),
        freshness_summary=_summary(v for r in results for v in r.freshness),
        state_summary=_summary(r.state for r in results), partial_result=partial,
        warnings=tuple(sorted(warnings)), requested_count=len(inputs)+len(contradictions),
        evaluated_count=len(inputs)+len(contradictions)-invalid, invalid_count=invalid, result_count=len(results), evaluated_at=evaluated_at,
    )
