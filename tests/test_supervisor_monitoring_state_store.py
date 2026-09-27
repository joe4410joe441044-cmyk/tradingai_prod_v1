"""Phase 2 append-only journal store, bounded recovery and corruption tests."""
from datetime import timedelta
import json
import threading
import pytest
from backend.supervisor.monitoring_state_models import AnomalyState, StateEvent
from backend.supervisor.monitoring_state_store import (
    AppendOutcome, MonitoringStateStore,
)
from test_supervisor_monitoring_models import NOW
from test_supervisor_monitoring_state import state_payload


def make_state(fingerprint='f' * 64, **changes):
    return AnomalyState.model_validate(state_payload(fingerprint=fingerprint, **changes))


def make_event(fingerprint='f' * 64, *, episode=1, evaluation='eval1', observation='obs1',
               transition='CREATED', occurred=NOW, state=None, eligible=True):
    return StateEvent(
        occurred_at=occurred, fingerprint=fingerprint, episode_number=episode,
        evaluation_id=evaluation, observation_id=observation, transition=transition,
        notification_eligible=eligible, state=state or make_state(fingerprint=fingerprint),
    )


def test_constructor_requires_explicit_path_and_writes_nothing(tmp_path):
    path = tmp_path / 'state.jsonl'
    store = MonitoringStateStore(path)
    assert not path.exists() and store.max_record_bytes > 0
    with pytest.raises(TypeError):
        MonitoringStateStore(None)
    with pytest.raises(TypeError):
        MonitoringStateStore()


def test_explicit_append_writes_one_line(tmp_path):
    path = tmp_path / 'state.jsonl'
    store = MonitoringStateStore(path)
    event = make_event()
    result = store.append(event)
    assert result.written and result.event_id == event.event_id
    lines = path.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])['event_id'] == event.event_id


def test_append_is_idempotent(tmp_path):
    store = MonitoringStateStore(tmp_path / 'state.jsonl')
    event = make_event()
    assert store.append(event).written
    assert store.append(event).outcome is AppendOutcome.DUPLICATE
    assert len(store.path.read_text().splitlines()) == 1


def test_conflicting_append_fails_closed(tmp_path):
    store = MonitoringStateStore(tmp_path / 'state.jsonl')
    warning = make_event(state=make_state(current_severity='WARNING'))
    critical = make_event(state=make_state(current_severity='CRITICAL', highest_severity='CRITICAL'))
    assert warning.event_id == critical.event_id
    assert store.append(warning).written
    result = store.append(critical)
    assert result.outcome is AppendOutcome.CONFLICT
    assert len(store.path.read_text().splitlines()) == 1


def test_restart_recovery_and_determinism(tmp_path):
    path = tmp_path / 'state.jsonl'
    store = MonitoringStateStore(path)
    store.append(make_event('a' * 64, evaluation='e1'))
    store.append(make_event('b' * 64, evaluation='e2'))
    first = MonitoringStateStore(path).recover()
    second = MonitoringStateStore(path).recover()
    assert {s.fingerprint for s in first.states} == {'a' * 64, 'b' * 64}
    assert [s.stable_json() for s in first.states] == [s.stable_json() for s in second.states]
    assert not first.partial and first.corruption_count == 0


def test_truncated_final_record_isolated(tmp_path):
    path = tmp_path / 'state.jsonl'
    store = MonitoringStateStore(path)
    store.append(make_event('a' * 64))
    with path.open('ab') as stream:
        stream.write(b'{"schema_version": "1", "occurred_at"')
    recovery = store.recover()
    assert [s.fingerprint for s in recovery.states] == ['a' * 64]
    assert recovery.corruption_count == 1
    assert recovery.corrupted[0].reason == 'TRUNCATED_FINAL_RECORD'


def test_corrupt_middle_record_isolated(tmp_path):
    path = tmp_path / 'state.jsonl'
    store = MonitoringStateStore(path)
    store.append(make_event('a' * 64, evaluation='e1'))
    with path.open('ab') as stream:
        stream.write(b'this is not json\n')
    store.append(make_event('b' * 64, evaluation='e2'))
    recovery = store.recover()
    assert {s.fingerprint for s in recovery.states} == {'a' * 64, 'b' * 64}
    assert recovery.corruption_count == 1 and recovery.corrupted[0].reason == 'INVALID_JSON'
    assert recovery.records_read == 3


def test_bounded_recovery_records(tmp_path):
    path = tmp_path / 'state.jsonl'
    writer = MonitoringStateStore(path)
    for index in range(3):
        writer.append(make_event(('%064x' % index), evaluation=f'e{index}'))
    store = MonitoringStateStore(path, max_recovery_records=1)
    recovery = store.recover()
    assert recovery.partial and 'RECOVERY_RECORD_BUDGET' in recovery.warnings
    assert len(recovery.states) == 1


def test_bounded_recovery_bytes(tmp_path):
    path = tmp_path / 'state.jsonl'
    writer = MonitoringStateStore(path)
    writer.append(make_event('a' * 64))
    writer.append(make_event('b' * 64, evaluation='e2'))
    store = MonitoringStateStore(path, max_recovery_bytes=10)
    recovery = store.recover()
    assert recovery.partial and 'RECOVERY_BYTE_BUDGET' in recovery.warnings
    assert recovery.bytes_read <= 11


def test_oversized_record_rejected(tmp_path):
    store = MonitoringStateStore(tmp_path / 'state.jsonl', max_record_bytes=100)
    result = store.append(make_event())
    assert result.outcome is AppendOutcome.REJECTED and result.error == 'OVERSIZED_RECORD'
    assert not store.path.exists()


def test_schema_version_rejection(tmp_path):
    store = MonitoringStateStore(tmp_path / 'state.jsonl')
    assert store.append({'schema_version': '2'}).outcome is AppendOutcome.REJECTED
    store.path.write_text('{"schema_version": "2"}\n')
    recovery = store.recover()
    assert recovery.corruption_count == 1
    assert recovery.corrupted[0].reason == 'SCHEMA_VERSION_UNSUPPORTED'


def test_append_never_rewrites_the_whole_file(tmp_path):
    path = tmp_path / 'state.jsonl'
    store = MonitoringStateStore(path)
    store.append(make_event('a' * 64))
    original = path.read_bytes()
    store.append(make_event('b' * 64, evaluation='e2'))
    updated = path.read_bytes()
    assert updated.startswith(original) and len(updated) > len(original)


def test_concurrent_process_local_appends(tmp_path):
    path = tmp_path / 'state.jsonl'
    store = MonitoringStateStore(path)
    results = []
    guard = threading.Lock()

    def worker(index):
        outcome = store.append(make_event('%064x' % index, evaluation=f'e{index}'))
        with guard:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(r.written for r in results)
    recovery = MonitoringStateStore(path).recover()
    assert len(recovery.states) == 12


def test_recovery_does_not_infer_missing_state(tmp_path):
    store = MonitoringStateStore(tmp_path / 'state.jsonl')
    recovery = store.recover()
    assert recovery.states == () and recovery.exists is False
