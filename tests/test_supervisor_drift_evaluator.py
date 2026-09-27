from datetime import timedelta
import pytest
from pydantic import ValidationError
from backend.supervisor.baseline_models import Baseline
from backend.supervisor.drift_evaluator import (
    Comparison, Contradiction, EvaluationInput, evaluate, evaluate_contradiction,
)
from backend.supervisor.monitoring_models import Observation, SUPPORTED_METRICS
from backend.supervisor.monitoring_policy import EvaluationPolicy
from test_supervisor_monitoring_models import NOW, observation, raw

POLICY = EvaluationPolicy()


def comparison(value=0.2, *, base=0.2, n=1000, end=NOW, **kwargs):
    return EvaluationInput(current=observation(value=value, n=n, end=end, **kwargs),
        baseline=Baseline(observation=observation(value=base, baseline=True, end=end, **kwargs),
                          minimum_sample_size=500, method='DEDUPLICATED_PROPORTION'))


def persistent(value=0.5, **kwargs):
    item = comparison(value, **kwargs)
    previous = tuple(Comparison(current=(p := comparison(value, end=NOW-timedelta(minutes=m), **kwargs)).current,
                               baseline=p.baseline) for m in (2, 1))
    return EvaluationInput(current=item.current, baseline=item.baseline, previous=previous)


def contradiction():
    source = raw(observation())['sources'][0]
    left = dict(scope='test', mode='PAPER', entity_id='order1', event_version='v1', field='linked_position', value='p1', source=source)
    right = dict(left, value='p2', source=dict(source, record_id='population2', digest='d'*64))
    return Contradiction(left=left, right=right,
        window=dict(start=NOW-timedelta(seconds=1), end=NOW+timedelta(seconds=1), time_authority='SOURCE_EVENT'))


@pytest.mark.parametrize('value,state', [(0.2, 'NORMAL'), (0.249, 'NORMAL'), (0.25, 'INFO'), (0.3, 'INFO'), (0.5, 'INFO')])
def test_thresholds(value, state):
    assert evaluate(comparison(value), POLICY).state == state


def test_warning_needs_three_advancing_observations():
    assert evaluate(persistent(), POLICY).state == 'WARNING'
    item = persistent()
    retry = EvaluationInput(current=item.current, baseline=item.baseline,
        previous=(Comparison(current=item.current, baseline=item.baseline),)*2)
    assert evaluate(retry, POLICY).state == 'INFO'
    normal = comparison()
    broken = EvaluationInput(current=item.current, baseline=item.baseline,
        previous=(Comparison(current=normal.current, baseline=normal.baseline), item.previous[1]))
    assert evaluate(broken, POLICY).state == 'INFO'


def test_critical_is_proven_separate_anomaly():
    result = evaluate_contradiction(contradiction(), POLICY)
    assert (result.state, result.category) == ('CRITICAL', 'OPERATIONAL_ANOMALY')
    assert result.deviation is None
    data = contradiction().model_dump()
    data['right']['event_version'] = 'v2'
    with pytest.raises(ValidationError):
        Contradiction.model_validate(data)


@pytest.mark.parametrize('kwargs,state', [({'availability': 'UNAVAILABLE', 'value': None}, 'UNKNOWN'),
    ({'freshness': 'STALE'}, 'STALE'), ({'partial_result': True}, 'PARTIAL'), ({'n': 50}, 'INSUFFICIENT_DATA')])
def test_quality_precedence(kwargs, state):
    value = kwargs.pop('value', 0.2)
    assert evaluate(comparison(value, **kwargs), POLICY).state == state


def test_direction_and_bounded_confidence():
    for direction in ('HIGHER_IS_WORSE', 'LOWER_IS_WORSE'):
        policy = EvaluationPolicy(direction=direction)
        up = evaluate(comparison(0.5), policy)
        down = evaluate(comparison(0.05), policy)
        assert up.state == ('INFO' if direction == 'HIGHER_IS_WORSE' else 'NORMAL')
        assert down.state == ('INFO' if direction == 'LOWER_IS_WORSE' else 'NORMAL')
        assert up.confidence == 'HIGH'
    item = comparison()
    data = raw(item)
    data['current']['sources'][0]['integrity'] = 'UNKNOWN'
    assert evaluate(EvaluationInput.model_validate(data), POLICY).confidence == 'MEDIUM'


def test_missing_baseline_no_deviation():
    result = evaluate(EvaluationInput(current=observation(), baseline=None), POLICY)
    assert result.state == 'UNKNOWN' and result.deviation is None
    assert result.confidence == 'UNKNOWN'
    assert 'BASELINE_MISSING' in result.reason_codes


def test_zero_baseline_and_deterministic_reasons():
    item = comparison(0.1, base=0)
    result = evaluate(item, POLICY)
    assert result.deviation.relative is None and 'BASELINE_ZERO' in result.reason_codes
    assert tuple(sorted(result.reason_codes)) == result.reason_codes
    assert result.stable_json() == evaluate(item, POLICY).stable_json()
    assert result.first_seen_at == result.last_seen_at == NOW


def test_revision_and_mode_boundaries():
    data = raw(comparison(0.5))
    for d in data['baseline']['observation']['grouping']:
        if d['key'] == 'effective_revision':
            d['value'] = 'old'
    result = evaluate(EvaluationInput.model_validate(data), POLICY)
    assert result.category == 'PARAMETER_REVISION' and result.severity == 'INFO' and result.deviation is None
    for d in data['baseline']['observation']['grouping']:
        if d['key'] == 'mode':
            d['value'] = 'LIVE'
    assert evaluate(EvaluationInput.model_validate(data), POLICY).state == 'UNKNOWN'


@pytest.mark.parametrize('metric', SUPPORTED_METRICS)
def test_supported_explicit_metrics(metric):
    if metric == 'selected_symbol_distribution':
        a = observation(metric=metric, value=({'category':'BTC', 'count':800}, {'category':'ETH', 'count':200}), unit='DISTRIBUTION')
        b = observation(metric=metric, baseline=True, value=({'category':'BTC', 'count':200}, {'category':'ETH', 'count':800}), unit='DISTRIBUTION')
        item = EvaluationInput(current=a, baseline=Baseline(observation=b, minimum_sample_size=500, method='DEDUPLICATED_DISTRIBUTION'))
        result = evaluate(item, POLICY)
        assert result.direction == 'CHANGED' and result.deviation.total_variation == pytest.approx(0.6)
    else:
        assert evaluate(comparison(metric=metric), POLICY).state == 'NORMAL'


@pytest.mark.parametrize('metric', ['mm_rejection_rate', 'governance_rejection_rate', 'execution_ack_rate',
    'execution_reject_rate', 'execution_partial_fill_rate', 'latency', 'fee', 'slippage',
    'exit_distribution', 'realized_performance', 'drawdown'])
def test_optional_metrics_unavailable(metric):
    result = evaluate(comparison(metric=metric), POLICY)
    assert result.state == 'UNKNOWN' and result.deviation is None
    assert 'METRIC_UNSUPPORTED' in result.reason_codes


def test_source_quality_all_reasons_retained():
    data = raw(comparison())
    data['current']['sources'][0].update(integrity='CORRUPT', freshness='STALE', availability='PARTIAL')
    result = evaluate(EvaluationInput.model_validate(data), POLICY)
    assert result.state == 'UNKNOWN' and result.partial_result
    assert {'SOURCE_CORRUPT', 'SOURCE_STALE', 'COVERAGE_PARTIAL'} <= set(result.reason_codes)


def test_policy_rejects_invalid_configuration():
    for change in (dict(proportion_info=0.2), dict(proportion_warning=float('inf')), dict(current_minimum=1)):
        with pytest.raises(ValidationError):
            EvaluationPolicy(**change)


def test_unknown_revision_and_live_fill_not_inferred():
    data = raw(comparison(metric='entry_execution_rate'))
    for d in data['current']['grouping']:
        if d['key'] == 'mode':
            d['value'] = 'LIVE'
    assert 'OUTCOME_UNSUPPORTED' in evaluate(EvaluationInput.model_validate(data), POLICY).reason_codes


def test_stale_persistence_keeps_state_visible():
    result = evaluate(persistent(freshness='STALE'), POLICY)
    assert result.state == 'STALE' and result.severity == 'WARNING'
    assert result.deviation is None


def test_minimum_sample_boundary():
    assert evaluate(comparison(n=100), POLICY).state == 'NORMAL'
    assert evaluate(comparison(n=99, value=0), POLICY).state == 'INSUFFICIENT_DATA'


def test_distribution_exact_threshold_and_zero_denominator():
    def distribution(count, baseline=False):
        return observation(metric='selected_symbol_distribution', baseline=baseline, unit='DISTRIBUTION',
            value=({'category':'BTC', 'count':count}, {'category':'ETH', 'count':1000-count}))
    item = EvaluationInput(current=distribution(300), baseline=Baseline(observation=distribution(200, True),
        minimum_sample_size=500, method='DEDUPLICATED_DISTRIBUTION'))
    assert evaluate(item, POLICY).state == 'INFO'
    assert evaluate(comparison(value=None, n=0), POLICY).state == 'INSUFFICIENT_DATA'


def test_incomplete_large_population_is_not_available():
    data = raw(comparison())
    data['baseline']['observation']['provenance']['complete'] = False
    assert evaluate(EvaluationInput.model_validate(data), POLICY).state == 'PARTIAL'


def test_window_and_definition_boundaries():
    data = raw(comparison())
    data['baseline']['observation']['window']['start'] += timedelta(hours=1)
    assert 'WINDOW_PROFILE_MISMATCH' in evaluate(EvaluationInput.model_validate(data), POLICY).reason_codes
    data = raw(comparison())
    data['baseline']['observation']['provenance']['denominator_definition'] = 'other-population'
    assert evaluate(EvaluationInput.model_validate(data), POLICY).state == 'UNKNOWN'


def test_health_freshness_120_second_boundary():
    data = raw(comparison(metric='source_freshness_rate'))
    data['current']['sources'][0]['age_seconds'] = 120
    assert evaluate(EvaluationInput.model_validate(data), POLICY).state == 'NORMAL'
    data['current']['sources'][0]['age_seconds'] = 121
    assert evaluate(EvaluationInput.model_validate(data), POLICY).state == 'STALE'


def test_lower_priority_quality_reasons_remain_visible():
    result = evaluate(comparison(n=50, freshness='STALE'), POLICY)
    assert result.state == 'STALE'
    assert {'SOURCE_STALE', 'MINIMUM_SAMPLE_UNMET'} <= set(result.reason_codes)
