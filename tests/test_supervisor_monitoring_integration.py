"""Phase 2 acknowledgement/resolution, one-shot integration and safety tests."""
import ast
from datetime import timedelta
import inspect
import json
import pytest
from backend.supervisor import (
    drift_evaluator, monitoring_state_models, monitoring_state_service,
    monitoring_state_store, monitoring_state_transitions,
)
from backend.supervisor.drift_evaluator import evaluate
from backend.supervisor.monitoring_policy import EvaluationPolicy
from backend.supervisor.monitoring_state_models import (
    Acknowledgement, AnomalyState, CooldownPolicy, StateEvent,
)
from backend.supervisor.monitoring_state_service import (
    MonitoringStateService, observe, reduce_monitoring_state,
)
from backend.supervisor.monitoring_state_store import MonitoringStateStore
from backend.supervisor.monitoring_state_transitions import apply_acknowledgement, transition
from backend.supervisor.one_shot_monitor import one_shot_monitor
from test_supervisor_monitoring_models import NOW
from test_supervisor_drift_evaluator import POLICY, comparison
from test_supervisor_monitoring_state import GROUPING, warning_item

COOLDOWN = CooldownPolicy()
GROUP = warning_item(NOW).current.grouping


def warning(end=NOW, value=0.5):
    return evaluate(warning_item(end, value), POLICY)


def created_state(end=NOW, value=0.5):
    return transition(None, warning(end, value), evaluated_at=end + timedelta(minutes=3),
                      cooldown=COOLDOWN, grouping=GROUP).state


def ack_for(state, *, at=NOW + timedelta(minutes=5), actor='operator', revision=None, event=None):
    return Acknowledgement(fingerprint=state.fingerprint, acknowledged_at=at, actor=actor,
                           expected_revision=revision if revision is not None else state.state_revision,
                           expected_event_id=event)


def read_events(path):
    events = []
    for line in path.read_text().splitlines():
        data = json.loads(line)
        data.pop('event_id', None)
        events.append(StateEvent.model_validate(data))
    return events


# --- acknowledgement / resolution (57-62) ---------------------------------

def test_idempotent_acknowledgement():
    state = created_state()
    ack = ack_for(state)
    first = apply_acknowledgement(state, ack, evaluated_at=ack.acknowledged_at, cooldown=COOLDOWN)
    second = apply_acknowledgement(first.state, ack, evaluated_at=ack.acknowledged_at,
                                   cooldown=COOLDOWN)
    assert first.transition == 'ACKNOWLEDGED'
    assert second.transition == 'ACK_REPEAT' and second.duplicate
    assert second.state.acknowledged_at == first.state.acknowledged_at


def test_stale_revision_acknowledgement_conflicts():
    state = created_state()
    ack = ack_for(state, revision=999)
    outcome = apply_acknowledgement(state, ack, evaluated_at=ack.acknowledged_at, cooldown=COOLDOWN)
    assert outcome.conflict and outcome.state.acknowledged_at is None


def test_acknowledgement_does_not_resolve_or_change_severity():
    state = created_state()
    outcome = apply_acknowledgement(state, ack_for(state), evaluated_at=NOW + timedelta(minutes=5),
                                    cooldown=COOLDOWN)
    assert outcome.state.active and outcome.state.resolved_at is None
    assert outcome.state.current_severity == state.current_severity == 'WARNING'
    assert outcome.state.highest_severity == state.highest_severity


def test_consecutive_normal_resolution_integration(tmp_path):
    service = MonitoringStateService(store=MonitoringStateStore(tmp_path / 'state.jsonl'))
    service.run([observe(warning(), grouping=GROUP)], evaluated_at=NOW + timedelta(minutes=3))
    for index in range(1, 4):
        stamp = NOW + timedelta(minutes=100 + 10 * index)
        cycle = service.run([observe(evaluate(comparison(0.2, end=stamp), POLICY), grouping=GROUP)],
                            evaluated_at=stamp)
    assert cycle.states and cycle.states[0].lifecycle_state == 'RESOLVED'
    assert not cycle.states[0].active


def test_recurrence_retains_history(tmp_path):
    path = tmp_path / 'state.jsonl'
    service = MonitoringStateService(store=MonitoringStateStore(path))
    service.run([observe(warning(), grouping=GROUP)], evaluated_at=NOW + timedelta(minutes=3))
    for index in range(1, 4):
        stamp = NOW + timedelta(minutes=100 + 10 * index)
        service.run([observe(evaluate(comparison(0.2, end=stamp), POLICY), grouping=GROUP)],
                    evaluated_at=stamp)
    service.run([observe(warning(NOW + timedelta(minutes=200)), grouping=GROUP)],
                evaluated_at=NOW + timedelta(minutes=203))
    events = read_events(path)
    assert any(e.state.lifecycle_state == 'RESOLVED' for e in events)
    assert any(e.state.episode_number == 2 and e.state.active for e in events)
    assert service.store.recover().states[0].episode_number == 2


# --- integration (63-65) --------------------------------------------------

def test_one_shot_integration_returns_full_result():
    cycle = reduce_monitoring_state([observe(warning(), grouping=GROUP)], (),
                                    evaluated_at=NOW + timedelta(minutes=3),
                                    cooldown_policy=COOLDOWN)
    assert len(cycle.states) == 1 and cycle.transitions
    assert cycle.transitions[0].transition == 'CREATED'


def test_integration_returns_persistence_events():
    cycle = reduce_monitoring_state([observe(warning(), grouping=GROUP)], (),
                                    evaluated_at=NOW + timedelta(minutes=3),
                                    cooldown_policy=COOLDOWN)
    assert len(cycle.events) == 1 and cycle.events[0].notification_eligible
    assert cycle.eligible_for_notification == (cycle.events[0].fingerprint,)


def test_persistence_only_when_explicitly_invoked(tmp_path):
    path = tmp_path / 'state.jsonl'
    service = MonitoringStateService(store=MonitoringStateStore(path))
    service.reduce([observe(warning(), grouping=GROUP)], evaluated_at=NOW + timedelta(minutes=3))
    assert not path.exists()
    service.run([observe(warning(), grouping=GROUP)], evaluated_at=NOW + timedelta(minutes=3))
    assert path.exists()


# --- safety (66-74) -------------------------------------------------------

MODULES = (monitoring_state_models, monitoring_state_transitions,
           monitoring_state_service, monitoring_state_store)
FORBIDDEN_IMPORTS = {'sqlite3', 'socket', 'requests', 'httpx', 'urllib', 'urllib3', 'aiohttp',
                     'smtplib', 'celery', 'apscheduler', 'asyncio', 'subprocess', 'pymongo',
                     'psycopg', 'psycopg2', 'redis', 'kafka'}
FORBIDDEN_IMPORT_PREFIXES = ('backend.bot_manager', 'backend.runtime', 'backend.main',
                             'backend.api', 'backend.execution', 'backend.risk_manager')


def _imports(module):
    tree = ast.parse(inspect.getsource(module))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split('.')[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_no_scheduler_or_background_task():
    for module in MODULES:
        imports = _imports(module)
        assert not imports & FORBIDDEN_IMPORTS, module.__name__
        assert not any(i.startswith(FORBIDDEN_IMPORT_PREFIXES) for i in imports)
        source = inspect.getsource(module)
        assert 'create_task' not in source and 'Thread(' not in source
        assert 'APScheduler' not in source and 'BackgroundScheduler' not in source


def test_no_threads_or_async_in_pure_modules():
    for module in (monitoring_state_models, monitoring_state_transitions, monitoring_state_service):
        source = inspect.getsource(module)
        assert 'threading' not in source and 'asyncio' not in source


def test_no_notification_delivery():
    for module in MODULES:
        tree = ast.parse(inspect.getsource(module))
        names = {node.name.lower() for node in ast.walk(tree)
                 if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
        assert not any('notify' in n or 'deliver' in n or 'webhook' in n or 'smtp' in n
                       or 'email' in n or 'slack' in n for n in names), module.__name__
        assert 'smtplib' not in _imports(module)


def test_no_network_or_database():
    for module in MODULES:
        imports = _imports(module)
        assert not imports & {'socket', 'requests', 'httpx', 'urllib', 'urllib3', 'aiohttp'}
        assert not imports & {'sqlite3', 'pymongo', 'psycopg', 'psycopg2', 'redis'}


def test_no_production_path_or_environment():
    for module in MODULES:
        source = inspect.getsource(module)
        assert 'logs/runtime' not in source and 'os.environ' not in source
        assert 'getenv' not in source and 'CYCLE_EVIDENCE_PATH' not in source
    with pytest.raises(TypeError):
        MonitoringStateStore()
    assert inspect.signature(MonitoringStateStore.__init__).parameters['path'].default is inspect.Parameter.empty


def test_no_runtime_or_trading_authority():
    forbidden = {'allow', 'block', 'order', 'execute', 'arm', 'disarm', 'runtime',
                 'tradingRecommendation', 'governance', 'remediate'}
    assert not forbidden & set(monitoring_state_models.AnomalyState.model_fields)
    assert not forbidden & set(drift_evaluator.DriftResult.model_fields)
    for module in MODULES:
        source = inspect.getsource(module)
        assert 'place_order' not in source and 'cancel_order' not in source
        assert 'start_bot' not in source and 'ARM' not in source


def test_phase_1_regression_compatibility():
    assert evaluate(comparison(0.2), POLICY).state == 'NORMAL'
    outcome = one_shot_monitor({}, policy=EvaluationPolicy(), evaluated_at=NOW)
    assert outcome.aggregate_status == 'UNKNOWN' and outcome.partial_result
    state = created_state()
    assert AnomalyState.model_validate(state.model_dump()).stable_json() == state.stable_json()
