import pytest
from pydantic import ValidationError
from backend.supervisor.baseline_models import Baseline
from test_supervisor_monitoring_models import observation


def baseline(**kwargs):
    return Baseline(observation=observation(baseline=True, **kwargs), minimum_sample_size=500,
                    method='DEDUPLICATED_PROPORTION')


@pytest.mark.parametrize('kwargs,state', [({}, 'AVAILABLE'),
    ({'n': 100}, 'INSUFFICIENT_DATA'), ({'n': 500}, 'AVAILABLE'),
    ({'availability': 'UNAVAILABLE', 'value': None}, 'UNAVAILABLE'),
    ({'freshness': 'STALE'}, 'STALE'), ({'partial_result': True}, 'PARTIAL'),
    ({'availability': 'INVALID', 'value': None}, 'INVALID'),
    ({'n': 0, 'value': None}, 'INSUFFICIENT_DATA')])
def test_baseline_states(kwargs, state):
    result = baseline(**kwargs)
    assert result.state == state
    assert (result.baseline_value is not None) == (state == 'AVAILABLE')


@pytest.mark.parametrize('kwargs', [{'value': float('nan')}, {'provenance': None}])
def test_baseline_invalid_evidence(kwargs):
    with pytest.raises(ValidationError):
        baseline(**kwargs)


def test_baseline_method_validation():
    with pytest.raises(ValidationError):
        Baseline(observation=observation(), minimum_sample_size=500, method='DEDUPLICATED_DISTRIBUTION')
