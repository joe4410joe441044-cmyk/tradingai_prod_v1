"""Synthetic bounded aggregate fixtures; no real data sources."""
from datetime import datetime, timedelta, timezone
import json
import math
import pytest
from pydantic import ValidationError
from backend.supervisor.monitoring_models import Observation, Samples, Window

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def observation(*, value=0.2, n=1000, baseline=False, metric='entry_candidate_rate', end=NOW, **changes):
    health = metric in ('evidence_missing_rate', 'evidence_corruption_rate', 'source_freshness_rate')
    duration = timedelta(hours=24 if health else 168) if baseline else timedelta(minutes=15 if health else 60)
    if baseline:
        end -= timedelta(minutes=15 if health else 60)
    group = dict(source='CYCLE_EVIDENCE', schema='v1', producer_epoch='epoch1') if health else dict(
        scope='test', mode='PAPER', effective_revision='r1', strategy_contract='v1', symbol='BTCUSDT')
    if metric == 'entry_execution_rate':
        group['outcome'] = 'PAPER_FILLED'
    if metric == 'rejection_block_rate':
        group['stage'] = 'STRATEGY'
    if metric == 'detector_activation_rate':
        group.update(detector='test', detector_version='v1')
    if metric == 'selected_symbol_distribution':
        group.pop('symbol')
        group['selection_mode'] = 'AUTO'
    if metric == 'source_freshness_rate':
        group['freshness_policy'] = 'FQ'
    data = dict(metric=metric, value=value, observed_at=end,
        window=dict(start=end-duration, end=end, time_authority='SOURCE_EVENT'),
        sample_size=dict(numerator=round(value*n) if isinstance(value, (int, float)) and math.isfinite(value) else None, denominator=n, eligible=n),
        grouping=[dict(key=k, value=v) for k,v in group.items()],
        sources=[dict(source='CYCLE_EVIDENCE', record_id='population1', revision='rev1', digest='a'*64,
                      availability='AVAILABLE', freshness='FRESH', freshness_policy='FQ',
                      observed_at=end, age_seconds=0, max_age_seconds=3600, freshness_reason='WITHIN_MAX_AGE',
                      integrity='VERIFIED', producer_heartbeat_available=True)],
        provenance=dict(source_schema='v1', scan_id=f'scan-{int(end.timestamp())}', read_method='SYNTHETIC_AGGREGATE', query_digest='b'*64,
            population_digest='c'*64, coverage_proof='complete-interval', eligibility_predicate='reached-evaluations-v1',
            numerator_definition='explicit-eligible-positive-v1', denominator_definition='dedup-reached-v1',
            deduplication='CANONICAL_RECORD_ID', complete=True),
        freshness='FRESH', availability='AVAILABLE')
    data.update(changes)
    return Observation.model_validate(data)


def raw(model):
    # Computed identity is an output, not caller-controlled input.
    if isinstance(model, Observation):
        return model.model_dump(exclude={'observation_id'})
    return model.model_dump(exclude={'current': {'observation_id'}, 'baseline': {'observation': {'observation_id'}},
        'previous': {'__all__': {'current': {'observation_id'}, 'baseline': {'observation': {'observation_id'}}}}})


def test_valid_immutable_observation():
    item = observation()
    assert item.value == 0.2 and len(item.observation_id) == 64
    assert json.loads(item.stable_json())['observation_id'] == item.observation_id
    with pytest.raises(ValidationError):
        item.value = 0.7
    with pytest.raises(ValidationError):
        item.sample_size.denominator = 20


@pytest.mark.parametrize('change', [
    {'window': dict(start=NOW, end=NOW, time_authority='SOURCE_EVENT')},
    {'window': dict(start=NOW, end=NOW-timedelta(seconds=1), time_authority='SOURCE_EVENT')},
    {'observed_at': NOW.replace(tzinfo=None)},
    {'value': float('nan')}, {'value': float('inf')}, {'value': -float('inf')},
    {'sample_size': dict(numerator=1, denominator=-1, eligible=-1)},
    {'provenance': None}, {'sources': []}, {'value': 0.7, 'sample_size': dict(numerator=200, denominator=1000, eligible=1000)},
    {'grouping': [dict(key='mode', value='PAPER')]*2}, {'secret': 'redacted'},
])
def test_invalid_observation(change):
    with pytest.raises(ValidationError):
        observation(**change)


def test_deterministic_order_and_timezone():
    a = observation(warnings=('Z', 'A', 'A'), uncertainty=('U2', 'U1'))
    data = raw(a)
    data['grouping'].reverse() if isinstance(data['grouping'], list) else None
    data['grouping'] = tuple(reversed(data['grouping']))
    data['observed_at'] = NOW.astimezone(timezone(timedelta(hours=9)))
    b = Observation.model_validate(data)
    assert a.stable_json() == b.stable_json()
    assert a.warnings == ('A', 'Z')


@pytest.mark.parametrize('changes', [dict(availability='UNAVAILABLE', value=None, provenance=None, sources=()),
    dict(freshness='STALE'), dict(partial_result=True)])
def test_explicit_data_states(changes):
    assert observation(**changes)


def test_zero_denominator_and_dedup_accounting():
    with pytest.raises(ValidationError):
        observation(n=0, value=0)
    item = observation(n=0, value=None)
    assert item.value is None
    samples = Samples(numerator=1, denominator=2, eligible=2, duplicates_removed=10)
    assert samples.denominator == 2


def test_bounded_and_unique_source_references():
    data = raw(observation())
    data['sources'] = data['sources'] * 2
    with pytest.raises(ValidationError):
        Observation.model_validate(data)
    with pytest.raises(ValidationError):
        observation(warnings=('x',)*33)


def test_complete_requires_proof():
    data = raw(observation())
    data['provenance']['coverage_proof'] = None
    with pytest.raises(ValidationError):
        Observation.model_validate(data)


def test_secrets_urls_and_boolean_values_rejected():
    for change in ({'metric': 'sk-private-value'}, {'metric': 'https://external.example'}, {'value': True}):
        with pytest.raises(ValidationError):
            observation(**change)
