"""Phase 2 state schema, deterministic fingerprint and cooldown policy tests."""
from datetime import datetime, timedelta, timezone
import json
import pytest
from pydantic import ValidationError
from backend.supervisor.drift_evaluator import (
    Comparison, EvaluationInput, evaluate, evaluate_corruption,
)
from backend.supervisor.monitoring_models import Dimension
from backend.supervisor.monitoring_policy import EvaluationPolicy
from backend.supervisor.monitoring_state_models import (
    AnomalyIdentity, AnomalyState, CooldownPolicy, build_identity, normalize_text,
    offending_identity,
)
from test_supervisor_monitoring_models import NOW, raw
from test_supervisor_drift_evaluator import POLICY, comparison

GROUPING = (Dimension(key='mode', value='PAPER'), Dimension(key='symbol', value='BTCUSDT'))


# --- shared helpers -------------------------------------------------------

def result_at(end=NOW, value=0.2, policy=POLICY):
    return evaluate(comparison(value, end=end), policy)


def warning_item(end, value=0.5):
    current = comparison(value, end=end)
    previous = tuple(
        Comparison(current=(p := comparison(value, end=end - timedelta(minutes=m))).current,
                   baseline=p.baseline) for m in (20, 10)
    )
    return EvaluationInput(current=current.current, baseline=current.baseline, previous=previous)


def warning_result(end, value=0.5):
    return evaluate(warning_item(end, value), POLICY)


def escalate(result, evaluation_id='escalation-eval'):
    return result.model_copy(update={'severity': 'CRITICAL', 'state': 'CRITICAL',
                                     'observation_id': evaluation_id})


def state_payload(fingerprint='a' * 64, **changes):
    data = dict(
        fingerprint=fingerprint, episode_key='b' * 64, family='d' * 64, metric='entry_candidate_rate',
        policy_version='monitoring-v1', category='STATISTICAL_DRIFT', lifecycle_state='ACTIVE',
        current_severity='WARNING', highest_severity='WARNING', first_seen_at=NOW,
        last_seen_at=NOW, occurrence_count=1, consecutive_count=1, last_evaluation_id='eval1',
        last_observation_id='obs1', last_content_digest='c' * 64, active=True,
        reason_codes=('WARNING_CANDIDATE',),
    )
    data.update(changes)
    return data


# --- fingerprint (1-7) ----------------------------------------------------

def test_fingerprint_is_deterministic():
    result = result_at()
    assert build_identity(result, grouping=GROUPING) == build_identity(result, grouping=GROUPING)
    assert (build_identity(result, grouping=GROUPING).fingerprint
            == build_identity(result, grouping=GROUPING).fingerprint)


def test_fingerprint_independent_of_dictionary_order():
    result = result_at()
    forward = build_identity(result, grouping=GROUPING).fingerprint
    reverse = build_identity(result, grouping=tuple(reversed(GROUPING))).fingerprint
    assert forward == reverse


def test_fingerprint_independent_of_value_and_timestamp():
    early = build_identity(result_at(NOW, 0.2), grouping=GROUPING).fingerprint
    late = build_identity(result_at(NOW + timedelta(hours=3), 0.9), grouping=GROUPING).fingerprint
    assert early == late


def test_fingerprint_separates_grouping():
    result = result_at()
    btc = build_identity(result, grouping=GROUPING).fingerprint
    eth = build_identity(result, grouping=(Dimension(key='symbol', value='ETHUSDT'),
                                           Dimension(key='mode', value='PAPER'))).fingerprint
    assert btc != eth


def test_fingerprint_separates_policy_version():
    first = build_identity(result_at(policy=POLICY), grouping=GROUPING).fingerprint
    other = EvaluationPolicy(policy_version='monitoring-v2')
    second = build_identity(result_at(policy=other), grouping=GROUPING).fingerprint
    assert first != second


def test_fingerprint_uses_unicode_normalization():
    assert normalize_text('e\u0301') == normalize_text('\u00e9')
    assert normalize_text('  value  ') == 'value'


def test_fingerprint_is_secret_free_and_hashed():
    data = raw(comparison())
    data['current']['sources'][0]['integrity'] = 'CORRUPT'
    corruption = evaluate_corruption(EvaluationInput.model_validate(data), POLICY)[0]
    offender = offending_identity(corruption)
    assert offender is not None and len(offender) == 64 and set(offender) <= set('0123456789abcdef')
    fingerprint = build_identity(corruption, grouping=GROUPING).fingerprint
    assert len(fingerprint) == 64 and 'sk-' not in fingerprint
    with pytest.raises(ValidationError):
        AnomalyIdentity(metric='API_KEY', policy_version='v1', category='CORRUPTION')
    assert 'record_id' not in json.dumps(build_identity(corruption, grouping=GROUPING).model_dump())


# --- state (8-14) ---------------------------------------------------------

def test_valid_new_state():
    item = warning_result(NOW)
    identity = build_identity(item, grouping=warning_item(NOW).current.grouping)
    state = AnomalyState.model_validate({
        **state_payload(fingerprint=identity.fingerprint, episode_key=identity.lineage),
        'lifecycle_state': 'NEW', 'occurrence_count': 1,
    })
    assert state.lifecycle_state == 'NEW' and state.active and state.schema_version == '1'
    assert state.reason_codes == ('WARNING_CANDIDATE',)


def test_active_state_validation():
    assert AnomalyState.model_validate(state_payload(lifecycle_state='ACTIVE'))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(lifecycle_state='ACTIVE', active=False))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(lifecycle_state='ACKNOWLEDGED'))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(current_severity='CRITICAL'))


def test_resolved_state_validation():
    resolved = dict(lifecycle_state='RESOLVED', active=False, current_severity='NONE',
                    resolved_at=NOW + timedelta(hours=1), resolution_reason='CONSECUTIVE_NORMAL_VALID')
    assert AnomalyState.model_validate(state_payload(**resolved))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(**{**resolved, 'active': True}))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(lifecycle_state='RESOLVED', active=False,
                                                  current_severity='NONE'))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(resolved_at=NOW + timedelta(hours=1)))


def test_invalid_timestamps_rejected():
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(last_seen_at=NOW - timedelta(seconds=1)))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(acknowledged_at=NOW.replace(tzinfo=None)))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(
            lifecycle_state='ACKNOWLEDGED', acknowledged_at=NOW - timedelta(hours=1),
            acknowledged_by='operator'))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(acknowledged_by='operator'))


def test_invalid_counters_rejected():
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(occurrence_count=-1))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(occurrence_count=1, consecutive_count=2))
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(occurrence_count=0))


def test_deterministic_serialization_and_stable_reasons():
    first = AnomalyState.model_validate(state_payload(reason_codes=('Z', 'A', 'A')))
    second = AnomalyState.model_validate(state_payload(reason_codes=('A', 'Z')))
    assert first.stable_json() == second.stable_json()
    assert first.reason_codes == ('A', 'Z')
    assert json.loads(first.stable_json())['fingerprint'] == 'a' * 64


def test_unknown_is_not_normal():
    state = AnomalyState.model_validate(state_payload(
        lifecycle_state='UNKNOWN', reason_codes=('AUTHORITY_UNAVAILABLE',)))
    assert state.is_normal is False and state.notifiable is False and state.active
    with pytest.raises(ValidationError):
        AnomalyState.model_validate(state_payload(lifecycle_state='UNKNOWN', reason_codes=()))


# --- cooldown policy (policy portion of 35-41) ----------------------------

def test_cooldown_policy_defaults_and_mapping():
    policy = CooldownPolicy()
    assert policy.seconds_for('WARNING') == 3600 and policy.seconds_for('CRITICAL') == 900
    assert policy.seconds_for('INFO') == 0 and policy.escalation_bypass


def test_cooldown_policy_rejects_invalid_values():
    for change in (dict(warning_seconds=-1), dict(critical_seconds=99999),
                   dict(resolution_consecutive_normal=0), dict(info_seconds=-5)):
        with pytest.raises(ValidationError):
            CooldownPolicy(**change)


def test_cooldown_policy_has_no_environment_dependency(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setenv('AI_SUPERVISOR_MONITORING_COOLDOWN', '5')
        assert CooldownPolicy().warning_seconds == 3600
