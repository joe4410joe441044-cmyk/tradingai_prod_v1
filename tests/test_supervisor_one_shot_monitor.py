import ast
import asyncio
import builtins
from datetime import timedelta
import inspect
import os
from pathlib import Path
import socket
import sqlite3
import threading
import time
import pytest
from backend.supervisor import baseline_models, drift_evaluator, monitoring_models, monitoring_policy, one_shot_monitor as monitor_module
from backend.supervisor.drift_evaluator import EvaluationInput
from backend.supervisor.monitoring_policy import EvaluationPolicy
from backend.supervisor.one_shot_monitor import one_shot_monitor
from test_supervisor_monitoring_models import NOW, raw
from test_supervisor_drift_evaluator import POLICY, comparison, contradiction, persistent


def run(inputs, **kwargs):
    return one_shot_monitor(inputs, policy=POLICY, evaluated_at=NOW+timedelta(minutes=3), **kwargs)


def test_multiple_metrics_order_and_repeatability():
    a, b = comparison(), comparison(metric='entry_execution_rate')
    first = run({'b': b, 'a': a})
    second = run({'a': a, 'b': b})
    assert first.stable_json() == second.stable_json()
    assert first.aggregate_status == 'NORMAL'
    assert first.evaluated_count == 2 and first.invalid_count == 0
    assert [r.metric for r in first.results] == sorted(r.metric for r in first.results)


@pytest.mark.parametrize('critical', [False, True])
def test_aggregate_preserves_severity(critical):
    result = run({'normal': comparison(), 'warning': persistent(), 'stale': comparison(freshness='STALE')},
                 contradictions=(contradiction(),) if critical else ())
    assert result.aggregate_status == ('CRITICAL' if critical else 'WARNING')
    assert result.partial_result
    assert 'STALE' in {s.code for s in result.state_summary}


def test_empty_and_all_unavailable_not_healthy():
    assert run({}).aggregate_status == 'UNKNOWN'
    result = run({'missing': EvaluationInput(current=comparison().current, baseline=None)})
    assert result.aggregate_status == 'UNKNOWN' and result.partial_result


def test_invalid_metric_isolation_no_secret_echo():
    bad = raw(comparison())
    bad['current']['value'] = float('nan')
    bad['current']['secret'] = 'api-key-do-not-echo'
    result = run({'bad': bad, 'good': comparison()})
    assert result.invalid_count == 1 and result.evaluated_count == 1
    assert {r.state for r in result.results} == {'UNKNOWN', 'NORMAL'}
    assert result.partial_result and 'api-key-do-not-echo' not in result.stable_json()


def test_partial_isolated_from_independent_normal():
    result = run({'partial': comparison(partial_result=True), 'normal': comparison()})
    assert result.aggregate_status == 'PARTIAL' and result.partial_result
    assert {r.state for r in result.results} == {'PARTIAL', 'NORMAL'}


def test_input_count_and_structure_budget():
    with pytest.raises(ValueError, match='INPUT_COUNT_BUDGET'):
        one_shot_monitor({'a': comparison(), 'b': comparison()}, policy=EvaluationPolicy(maximum_inputs=1), evaluated_at=NOW)
    result = run({'oversized': {'padding': 'x'*1025}, 'ok': comparison()})
    assert result.invalid_count == 1
    with pytest.raises(TypeError):
        run(iter(()))
    with pytest.raises(TypeError):
        run({'bad': object()})


def test_timestamp_invalid_is_isolated():
    result = one_shot_monitor({'future': comparison()}, policy=POLICY, evaluated_at=NOW-timedelta(seconds=1))
    assert result.invalid_count == 1


def test_pure_evaluation_has_no_side_effect_capabilities(monkeypatch):
    inputs = {'good': persistent(), 'partial': comparison(partial_result=True)}
    proof = contradiction()
    before = {k: v.stable_json() for k,v in inputs.items()}
    def forbidden(*args, **kwargs):
        raise AssertionError('side effect attempted')
    with monkeypatch.context() as patch:
        for owner, name in ((builtins, 'open'), (Path, 'open'), (Path, 'read_text'), (Path, 'write_text'),
            (socket, 'socket'), (socket, 'create_connection'), (sqlite3, 'connect'),
            (threading.Thread, 'start'), (asyncio, 'create_task'), (time, 'sleep'),
            (os, 'getenv'), (os, 'putenv')):
            patch.setattr(owner, name, forbidden)
        result = run(inputs, contradictions=(proof,))
        serialized = result.stable_json()
    assert {k: v.stable_json() for k,v in inputs.items()} == before
    assert result.aggregate_status == 'CRITICAL'
    assert 'realOrderAllowed' not in serialized


def test_modules_only_import_pure_dependencies_and_have_no_authority_fields():
    allowed = {'__future__', 'datetime', 'hashlib', 'json', 'math', 'typing', 'pydantic',
               'monitoring_models', 'baseline_models', 'monitoring_policy', 'drift_evaluator'}
    for module in (monitoring_models, baseline_models, monitoring_policy, drift_evaluator, monitor_module):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name in allowed for a in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.module in allowed
            assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await))
    keys = set(drift_evaluator.DriftResult.model_fields)
    assert not keys & {'allow', 'block', 'order', 'runtime', 'notification', 'provider', 'store', 'arm', 'tradingRecommendation'}


def test_corruption_is_separate_and_not_hidden_by_partial():
    data = raw(persistent())
    for part in (data, *data['previous']):
        part['current']['sources'][0]['integrity'] = 'CORRUPT'
        part['current']['partial_result'] = True
    result = run({'corruption': data, 'normal': comparison()})
    assert result.aggregate_status == 'CRITICAL' and result.partial_result
    assert result.result_count == 3 and result.evaluated_count == 2
    assert {r.category for r in result.results} >= {'CORRUPTION', 'STATISTICAL_DRIFT'}
    assert any(r.metric == 'source_corruption' and r.severity == 'CRITICAL' for r in result.results)
    # Retrying the same scan does not prove three distinct scans.
    for part in data['previous']:
        part['current']['provenance']['scan_id'] = data['current']['provenance']['scan_id']
    result = run({'corruption': data})
    assert not any(r.severity == 'CRITICAL' for r in result.results)


def test_completed_minute_with_120_second_delay():
    result = one_shot_monitor({'current': comparison()}, policy=POLICY, evaluated_at=NOW+timedelta(seconds=119))
    assert result.invalid_count == 1
    result = one_shot_monitor({'current': comparison()}, policy=POLICY, evaluated_at=NOW+timedelta(seconds=120))
    assert result.aggregate_status == 'NORMAL'
