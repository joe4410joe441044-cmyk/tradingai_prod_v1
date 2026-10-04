"""Phase 3D-2C multi-process coordinator / ownership integration tests.

Bounded fork workers only.  Temporary SQLite databases and lock files under the
pytest temporary directory.  Every wait/join has an explicit timeout and every
child is terminated in ``finally``; no Production path is opened.
"""
from __future__ import annotations

import multiprocessing
import os
from datetime import datetime, timezone

import pytest

from backend.supervisor.monitoring_trigger_coordinator import MonitoringTriggerCoordinator
from backend.supervisor.monitoring_trigger_idempotency_store import (
    MonitoringTriggerIdempotencyStore,
)
from backend.supervisor.monitoring_trigger_models import TriggerRequest
from backend.supervisor.monitoring_trigger_ownership import MonitoringTriggerOwnership
from backend.supervisor.monitoring_trigger_security import (
    TRIGGER_CAPABILITY,
    AuthorizationInput,
    evaluate_trigger_flags,
    principal_reference,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
INSTANCE = "I" + "a" * 16


def _authz():
    return AuthorizationInput(
        authenticated=True,
        principal_id="operator",
        capabilities=(TRIGGER_CAPABILITY,),
        capability_source="VERIFIED_ADAPTER",
        source_available=True,
        source_freshness="FRESH",
    )


def _flags():
    return evaluate_trigger_flags(api_raw="1", monitoring_raw="1")


def _coordinator(db_path, lock_path, runner):
    store = MonitoringTriggerIdempotencyStore(db_path)
    store.initialize()
    ownership = MonitoringTriggerOwnership(
        lock_path,
        instance_id=INSTANCE,
        clock=lambda: NOW,
        process_start_provider=lambda pid: "fixed-start",
    )
    return MonitoringTriggerCoordinator(
        ownership=ownership,
        store=store,
        runner=runner,
        clock=lambda: NOW,
        monotonic=lambda: 0.0,
    )


def _holding_worker(db_path, lock_path, request_id, holding, release, executions, results):
    def runner(_request, _context):
        executions.put("EXEC:" + request_id)
        holding.set()
        release.wait(timeout=20)
        return {"status": "SUCCESS", "run_id": "R-" + request_id}

    try:
        coordinator = _coordinator(db_path, lock_path, runner)
        result = coordinator.coordinate(
            request=TriggerRequest(request_id=request_id),
            authorization=_authz(),
            feature_flags=_flags(),
            now=NOW,
        )
        results.put(result.outcome)
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        results.put("ERROR:" + type(exc).__name__)
        holding.set()


def _run_worker(db_path, lock_path, request_id, executions, results):
    def runner(_request, _context):
        executions.put("EXEC:" + request_id)
        return {"status": "SUCCESS", "run_id": "R-" + request_id}

    try:
        coordinator = _coordinator(db_path, lock_path, runner)
        result = coordinator.coordinate(
            request=TriggerRequest(request_id=request_id),
            authorization=_authz(),
            feature_flags=_flags(),
            now=NOW,
        )
        results.put(result.outcome)
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        results.put("ERROR:" + type(exc).__name__)


def _claim_only_worker(db_path, lock_path, request_id, results):
    try:
        coordinator = _coordinator(db_path, lock_path, lambda request, context: None)
        result = coordinator.coordinate(
            request=TriggerRequest(request_id=request_id),
            authorization=_authz(),
            feature_flags=_flags(),
            claim_only=True,
            now=NOW,
        )
        results.put(result.outcome)
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        results.put("ERROR:" + type(exc).__name__)


def _fork_context():
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork start method unavailable")
    return multiprocessing.get_context("fork")


def _drain(queue):
    values = []
    while True:
        try:
            values.append(queue.get_nowait())
        except Exception:  # noqa: BLE001 - empty queue
            return values


def _cleanup(processes, release=None):
    if release is not None:
        release.set()
    for process in processes:
        process.join(timeout=20)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)


# --- 4: concurrent same-key requests execute once ---------------------------

def test_concurrent_same_key_executes_once(tmp_path):
    ctx = _fork_context()
    db_path = str(tmp_path / "idem.sqlite3")
    lock_path = str(tmp_path / "trigger.lock")
    holding = ctx.Event()
    release = ctx.Event()
    executions = ctx.Queue()
    results = ctx.Queue()

    first = ctx.Process(
        target=_holding_worker,
        args=(db_path, lock_path, "req-shared", holding, release, executions, results),
    )
    second = ctx.Process(
        target=_run_worker,
        args=(db_path, lock_path, "req-shared", executions, results),
    )
    first.start()
    try:
        assert holding.wait(timeout=20)
        assert executions.get(timeout=20) == "EXEC:req-shared"
        second.start()
        outcome = results.get(timeout=20)
        assert outcome in ("IN_PROGRESS", "OWNERSHIP_BUSY", "REPLAYED")
        assert _drain(executions) == []
    finally:
        second.join(timeout=20)
        _cleanup([first, second], release=release)

    assert not first.is_alive()
    assert not second.is_alive()

    # The single execution is durably recorded by one owner.
    store = MonitoringTriggerIdempotencyStore(db_path)
    store.initialize()
    assert len(store.recent_records()) == 1


# --- 5: different keys cannot run simultaneously under one OS lock ----------

def test_different_keys_share_one_lock(tmp_path):
    ctx = _fork_context()
    db_path = str(tmp_path / "idem.sqlite3")
    lock_path = str(tmp_path / "trigger.lock")
    holding = ctx.Event()
    release = ctx.Event()
    executions = ctx.Queue()
    results = ctx.Queue()

    first = ctx.Process(
        target=_holding_worker,
        args=(db_path, lock_path, "req-a", holding, release, executions, results),
    )
    second = ctx.Process(
        target=_run_worker,
        args=(db_path, lock_path, "req-b", executions, results),
    )
    first.start()
    try:
        assert holding.wait(timeout=20)
        assert executions.get(timeout=20) == "EXEC:req-a"
        second.start()
        outcome = results.get(timeout=20)
        assert outcome == "OWNERSHIP_BUSY"
        assert _drain(executions) == []
    finally:
        second.join(timeout=20)
        _cleanup([first, second], release=release)


# --- 7: process crash releases the OS lock ----------------------------------

def test_process_crash_releases_lock(tmp_path):
    ctx = _fork_context()
    db_path = str(tmp_path / "idem.sqlite3")
    lock_path = str(tmp_path / "trigger.lock")
    holding = ctx.Event()
    release = ctx.Event()
    executions = ctx.Queue()
    results = ctx.Queue()

    child = ctx.Process(
        target=_holding_worker,
        args=(db_path, lock_path, "req-crash", holding, release, executions, results),
    )
    child.start()
    try:
        assert holding.wait(timeout=20)
        assert executions.get(timeout=20) == "EXEC:req-crash"
        child.kill()
        child.join(timeout=20)
        assert not child.is_alive()
    finally:
        _cleanup([child])

    # The kernel released the advisory lock with the process; a new owner can run.
    def runner(_request, _context):
        return {"status": "SUCCESS", "run_id": "R-parent"}

    parent = _coordinator(db_path, lock_path, runner)
    result = parent.coordinate(
        request=TriggerRequest(request_id="req-after-crash"),
        authorization=_authz(),
        feature_flags=_flags(),
        now=NOW,
    )
    assert result.outcome == "RUNNER_SUCCEEDED"
    assert parent.ownership.current_status().active is False


# --- 8: the SQLite claim survives a process restart -------------------------

def test_sqlite_claim_survives_restart(tmp_path):
    ctx = _fork_context()
    db_path = str(tmp_path / "idem.sqlite3")
    lock_path = str(tmp_path / "trigger.lock")
    results = ctx.Queue()

    child = ctx.Process(
        target=_claim_only_worker,
        args=(db_path, lock_path, "req-persist", results),
    )
    child.start()
    try:
        assert results.get(timeout=20) == "CLAIMED"
        child.join(timeout=20)
        assert not child.is_alive()
    finally:
        _cleanup([child])

    store = MonitoringTriggerIdempotencyStore(db_path)
    store.initialize()
    record = store.get_record(
        key="req-persist",
        operation="SUPERVISOR_MONITORING_RUN_ONCE",
        principal_scope=principal_reference("operator"),
    )
    assert record is not None
    assert record.status in ("CLAIMED", "IN_PROGRESS")
    assert record.generation == 1
