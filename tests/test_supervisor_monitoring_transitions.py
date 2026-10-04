"""Phase 2 transition engine, deduplication and cooldown behaviour tests."""
from datetime import timedelta
import pytest
from pydantic import ValidationError
from backend.supervisor.drift_evaluator import EvaluationInput, evaluate, evaluate_contradiction
from backend.supervisor.monitoring_models import Dimension
from backend.supervisor.monitoring_policy import EvaluationPolicy
from backend.supervisor.monitoring_state_models import (
    Acknowledgement, CooldownPolicy, build_identity,
)
from backend.supervisor.monitoring_state_transitions import apply_acknowledgement, transition
from test_supervisor_monitoring_models import NOW, raw
from test_supervisor_drift_evaluator import POLICY, comparison, contradiction
from test_supervisor_monitoring_state import (
    GROUPING, escalate, warning_item, warning_result,
)

COOLDOWN = CooldownPolicy()
GROUP = warning_item(NOW).current.grouping


def created(end=NOW, value=0.5):
    return transition(None, warning_result(end, value), evaluated_at=end + timedelta(minutes=3),
                      cooldown=COOLDOWN, grouping=GROUP)


def advance(state, end, value=0.5, *, evaluated=None, cooldown=COOLDOWN, grouping=GROUP):
    return transition(state, warning_result(end, value),
                      evaluated_at=evaluated or end + timedelta(minutes=3),
                      cooldown=cooldown, grouping=grouping)


# --- transitions (15-29) --------------------------------------------------

def test_first_detection_creates_new_state():
    outcome = created()
    assert outcome.transition == 'CREATED' and outcome.state.lifecycle_state == 'NEW'
    assert outcome.state.occurrence_count == 1 and outcome.notification_eligible


def test_repeated_anomaly_increments_occurrence():
    first = created()
    outcome = advance(first.state, NOW + timedelta(minutes=70))
    assert outcome.transition == 'REPEATED' and outcome.state.occurrence_count == 2
    assert outcome.state.lifecycle_state == 'ACTIVE'


def test_escalation_raises_severity_once():
    first = created()
    outcome = transition(first.state, escalate(warning_result(NOW + timedelta(minutes=30))),
                         evaluated_at=NOW + timedelta(minutes=33), cooldown=COOLDOWN, grouping=GROUP)
    assert outcome.transition == 'ESCALATED' and outcome.state.current_severity == 'CRITICAL'
    assert outcome.state.highest_severity == 'CRITICAL' and outcome.state.escalation_version == 1
    assert outcome.notification_eligible


def test_same_severity_inside_cooldown_is_suppressed():
    first = created()
    outcome = advance(first.state, NOW + timedelta(minutes=10))
    assert outcome.transition == 'SUPPRESSED' and not outcome.notification_eligible
    assert outcome.suppression_reason == 'COOLDOWN_ACTIVE'


def test_same_severity_after_cooldown_is_eligible():
    first = created()
    outcome = advance(first.state, NOW + timedelta(minutes=70))
    assert outcome.transition == 'REPEATED' and outcome.notification_eligible


def test_acknowledgement_keeps_anomaly_active():
    first = created()
    ack = Acknowledgement(fingerprint=first.state.fingerprint,
                          acknowledged_at=NOW + timedelta(minutes=5), actor='operator',
                          expected_revision=first.state.state_revision)
    outcome = apply_acknowledgement(first.state, ack, evaluated_at=NOW + timedelta(minutes=5),
                                    cooldown=COOLDOWN)
    assert outcome.transition == 'ACKNOWLEDGED' and outcome.state.lifecycle_state == 'ACKNOWLEDGED'
    assert outcome.state.active and outcome.state.current_severity == 'WARNING'
    assert outcome.state.acknowledged_by == 'operator' and not outcome.notification_eligible


def test_repeated_anomaly_after_acknowledgement():
    first = created()
    ack = Acknowledgement(fingerprint=first.state.fingerprint,
                          acknowledged_at=NOW + timedelta(minutes=5), actor='operator',
                          expected_revision=first.state.state_revision)
    acked = apply_acknowledgement(first.state, ack, evaluated_at=NOW + timedelta(minutes=5),
                                  cooldown=COOLDOWN).state
    outcome = advance(acked, NOW + timedelta(minutes=10))
    assert outcome.transition == 'ACK_REPEAT' and outcome.suppression_reason == 'ACKNOWLEDGED'
    assert not outcome.notification_eligible


def test_consecutive_normal_resolution():
    state = created().state
    previous = None
    for index in range(1, 4):
        stamp = NOW + timedelta(minutes=100 + 10 * index)
        outcome = transition(state, evaluate(comparison(0.2, end=stamp), POLICY),
                             evaluated_at=stamp, cooldown=COOLDOWN, grouping=GROUP)
        state = outcome.state
    assert outcome.transition == 'RESOLVED' and state.lifecycle_state == 'RESOLVED'
    assert not state.active and state.resolved_at is not None


def test_recurrence_after_resolution_creates_new_episode():
    state = created().state
    for index in range(1, 4):
        stamp = NOW + timedelta(minutes=100 + 10 * index)
        state = transition(state, evaluate(comparison(0.2, end=stamp), POLICY),
                           evaluated_at=stamp, cooldown=COOLDOWN, grouping=GROUP).state
    assert state.lifecycle_state == 'RESOLVED'
    outcome = advance(state, NOW + timedelta(minutes=200))
    assert outcome.transition == 'RECURRED' and outcome.state.episode_number == 2
    assert outcome.state.active and outcome.state.occurrence_count == 1
    assert outcome.previous.lifecycle_state == 'RESOLVED'


@pytest.mark.parametrize('change', [dict(freshness='STALE'), dict(partial_result=True)])
def test_degraded_input_does_not_resolve(change):
    first = created()
    degraded = evaluate(comparison(0.5, end=NOW + timedelta(minutes=10), **change), POLICY)
    assert degraded.severity == 'NONE'
    outcome = transition(first.state, degraded, evaluated_at=NOW + timedelta(minutes=13),
                         cooldown=COOLDOWN, grouping=GROUP)
    assert outcome.transition == 'DEGRADED' and outcome.state.active
    assert outcome.state.lifecycle_state == 'UNKNOWN' and outcome.state.resolved_at is None


def test_insufficient_data_does_not_resolve():
    first = created()
    insufficient = evaluate(comparison(0.2, n=50, end=NOW + timedelta(minutes=20)), POLICY)
    assert insufficient.state == 'INSUFFICIENT_DATA'
    outcome = transition(first.state, insufficient, evaluated_at=NOW + timedelta(minutes=23),
                         cooldown=COOLDOWN, grouping=GROUP)
    assert outcome.state.resolved_at is None and outcome.state.active


def test_policy_revision_creates_new_epoch():
    first = created()
    other = EvaluationPolicy(policy_version='monitoring-v2')
    revised = evaluate(warning_item(NOW + timedelta(minutes=30)), other)
    outcome = transition(first.state, revised, evaluated_at=NOW + timedelta(minutes=33),
                         cooldown=COOLDOWN, grouping=GROUP)
    assert outcome.transition == 'POLICY_REVISION' and outcome.state.episode_number == 1
    assert outcome.state.policy_version == 'monitoring-v2'
    assert outcome.state.fingerprint != first.state.fingerprint


def test_source_revision_change_does_not_create_new_alert():
    first = created()
    data = raw(warning_item(NOW + timedelta(minutes=30)))
    for part in (data['current'], data['baseline']['observation']):
        part['sources'][0]['revision'] = 'rev2'
    for part in data['previous']:
        part['current']['sources'][0]['revision'] = 'rev2'
        part['baseline']['observation']['sources'][0]['revision'] = 'rev2'
    revised = evaluate(EvaluationInput.model_validate(data), POLICY)
    outcome = transition(first.state, revised, evaluated_at=NOW + timedelta(minutes=33),
                         cooldown=COOLDOWN, grouping=GROUP)
    assert outcome.transition == 'SOURCE_REVISION' and outcome.state.source_revision == 'rev2'
    assert outcome.state.fingerprint == first.state.fingerprint and not outcome.notification_eligible


def test_transition_does_not_mutate_inputs():
    first = created()
    before_state = first.state.stable_json()
    result = warning_result(NOW + timedelta(minutes=10))
    before_result = result.stable_json()
    transition(first.state, result, evaluated_at=NOW + timedelta(minutes=13),
               cooldown=COOLDOWN, grouping=GROUP)
    assert first.state.stable_json() == before_state
    assert result.stable_json() == before_result


# --- deduplication (30-34) ------------------------------------------------

def test_duplicate_evaluation_replay_is_idempotent():
    first = created()
    result = warning_result(NOW + timedelta(minutes=10))
    once = transition(first.state, result, evaluated_at=NOW + timedelta(minutes=13),
                      cooldown=COOLDOWN, grouping=GROUP)
    twice = transition(once.state, result, evaluated_at=NOW + timedelta(minutes=13),
                       cooldown=COOLDOWN, grouping=GROUP)
    assert twice.transition == 'DUPLICATE' and twice.duplicate and not twice.persistence_required
    assert twice.state.occurrence_count == once.state.occurrence_count


def test_duplicate_observation_replay_is_idempotent():
    first = created()
    result = warning_result(NOW + timedelta(minutes=10))
    once = transition(first.state, result, evaluated_at=NOW + timedelta(minutes=13),
                      cooldown=COOLDOWN, grouping=GROUP)
    replay = result.model_copy(update={'observation_id': 'replayed-evaluation-id'})
    twice = transition(once.state, replay, evaluated_at=NOW + timedelta(minutes=14),
                       cooldown=COOLDOWN, grouping=GROUP)
    assert twice.transition == 'DUPLICATE' and twice.duplicate


def test_duplicate_replay_does_not_extend_counters_or_cooldown():
    first = created()
    result = warning_result(NOW + timedelta(minutes=10))
    once = transition(first.state, result, evaluated_at=NOW + timedelta(minutes=13),
                      cooldown=COOLDOWN, grouping=GROUP)
    before = once.state
    twice = transition(before, result, evaluated_at=NOW + timedelta(minutes=20),
                       cooldown=COOLDOWN, grouping=GROUP)
    assert twice.state.occurrence_count == before.occurrence_count
    assert twice.state.consecutive_count == before.consecutive_count
    assert twice.state.cooldown_until == before.cooldown_until
    assert twice.state.state_revision == before.state_revision


def test_same_event_identity_with_different_content_conflicts():
    first = created()
    result = warning_result(NOW + timedelta(minutes=10))
    once = transition(first.state, result, evaluated_at=NOW + timedelta(minutes=13),
                      cooldown=COOLDOWN, grouping=GROUP)
    tampered = result.model_copy(update={'severity': 'CRITICAL', 'state': 'CRITICAL'})
    conflict = transition(once.state, tampered, evaluated_at=NOW + timedelta(minutes=13),
                          cooldown=COOLDOWN, grouping=GROUP)
    assert conflict.transition == 'CONFLICT' and conflict.conflict
    assert conflict.state.occurrence_count == once.state.occurrence_count


def test_independent_fingerprints_remain_independent():
    btc = created()
    other = (Dimension(key='mode', value='PAPER'), Dimension(key='symbol', value='ETHUSDT'))
    eth = transition(None, warning_result(NOW), evaluated_at=NOW + timedelta(minutes=3),
                     cooldown=COOLDOWN, grouping=other)
    assert btc.state.fingerprint != eth.state.fingerprint
    assert btc.state.episode_key != eth.state.episode_key


# --- cooldown behaviour (35-41) -------------------------------------------

def test_info_severity_is_never_eligible():
    info = evaluate(comparison(0.5, end=NOW), POLICY)
    assert info.severity == 'INFO'
    outcome = transition(None, info, evaluated_at=NOW + timedelta(minutes=3),
                         cooldown=COOLDOWN, grouping=GROUP)
    assert outcome.transition == 'CREATED' and not outcome.notification_eligible
    assert outcome.suppression_reason == 'INFO_NOT_ELIGIBLE'


def test_warning_and_critical_are_eligible():
    warning = created()
    critical = transition(None, evaluate_contradiction(contradiction(), POLICY),
                          evaluated_at=NOW + timedelta(minutes=3), cooldown=COOLDOWN)
    assert warning.notification_eligible and critical.notification_eligible
    assert critical.state.current_severity == 'CRITICAL'


def test_exact_cooldown_boundary():
    first = created()
    deadline = first.state.cooldown_until
    inside = advance(first.state, NOW + timedelta(minutes=10), evaluated=deadline - timedelta(seconds=1))
    assert inside.transition == 'SUPPRESSED'
    boundary = advance(first.state, NOW + timedelta(minutes=10), evaluated=deadline)
    assert boundary.transition == 'REPEATED' and boundary.notification_eligible


def test_escalation_bypasses_cooldown():
    first = created()
    inside = advance(first.state, NOW + timedelta(minutes=10))
    assert inside.transition == 'SUPPRESSED'
    outcome = transition(inside.state, escalate(warning_result(NOW + timedelta(minutes=20))),
                         evaluated_at=NOW + timedelta(minutes=23), cooldown=COOLDOWN, grouping=GROUP)
    assert outcome.transition == 'ESCALATED' and outcome.notification_eligible


def test_acknowledgement_suppresses_repeat_notification():
    first = created()
    ack = Acknowledgement(fingerprint=first.state.fingerprint,
                          acknowledged_at=NOW + timedelta(minutes=5), actor='operator',
                          expected_revision=first.state.state_revision)
    acked = apply_acknowledgement(first.state, ack, evaluated_at=NOW + timedelta(minutes=5),
                                  cooldown=COOLDOWN).state
    outcome = advance(acked, NOW + timedelta(minutes=70))
    assert not outcome.notification_eligible and outcome.suppression_reason == 'ACKNOWLEDGED'


def test_cooldown_does_not_hide_active_state():
    first = created()
    outcome = advance(first.state, NOW + timedelta(minutes=10))
    assert outcome.transition == 'SUPPRESSED' and outcome.state.active
    assert outcome.state.current_severity == 'WARNING'
    assert outcome.state.occurrence_count == first.state.occurrence_count + 1
    assert outcome.state.lifecycle_state != 'RESOLVED'
