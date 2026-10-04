"""Phase 3D-2A restart-safe SQLite trigger-idempotency store tests.

Temporary paths only.  No API route, no manual runner, no monitoring execution,
no OS advisory lock, no Production connection.
"""
from __future__ import annotations

import builtins
import inspect
import multiprocessing
import os
import sqlite3
import sys
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from backend.supervisor import monitoring_trigger_idempotency_store as store_module
from backend.supervisor.monitoring_trigger_idempotency_store import (
    SCHEMA_VERSION,
    IdempotencyLimits,
    IdempotencyStoreError,
    MonitoringTriggerIdempotencyStore as Store,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
FP = "a" * 64
FP2 = "b" * 64
OP = "SUPERVISOR_MONITORING_RUN_ONCE"
OP2 = "SUPERVISOR_MONITORING_SWEEP"
SCOPE = "Poperatorscope"
SCOPE2 = "Potherscope"
OWNER = "O" + "1" * 32
SOURCE = inspect.getsource(store_module)


def make_store(tmp_path, name="idem.sqlite3", *, initialize=True, **overrides):
    store = Store(tmp_path / name, **overrides)
    if initialize:
        store.initialize()
    return store


def do_claim(store, **overrides):
    data = dict(
        key="req-1", request_fingerprint=FP, principal_scope=SCOPE,
        operation=OP, now=NOW, owner_id=OWNER,
    )
    data.update(overrides)
    return store.claim(**data)


def do_running(store, *, owner=OWNER, gen=1, key="req-1", scope=SCOPE, op=OP, fp=FP, now=NOW):
    return store.mark_running(
        key=key, operation=op, principal_scope=scope, request_fingerprint=fp,
        expected_generation=gen, owner_id=owner, run_id="run-1", now=now,
    )


def do_complete(store, *, owner=OWNER, gen=1, key="req-1", scope=SCOPE, op=OP, fp=FP,
                response=None, now=NOW):
    return store.complete_success(
        key=key, operation=op, principal_scope=scope, request_fingerprint=fp,
        expected_generation=gen, owner_id=owner, response=response, now=now,
    )


@pytest.fixture
def store(tmp_path):
    return make_store(tmp_path)


# --- import / construction (1, 2, 45, 46, 47, 48) ---------------------------

def test_import_has_no_io(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during import")

    module = types.ModuleType("backend.supervisor._idem_reimport")
    module.__package__ = "backend.supervisor"
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        patch.setattr(sqlite3, "connect", boom)
        patch.setattr(os, "open", boom)
        patch.setitem(sys.modules, module.__name__, module)
        exec(compile(SOURCE, "monitoring_trigger_idempotency_store.py", "exec"), module.__dict__)
    assert callable(module.MonitoringTriggerIdempotencyStore)


def test_constructor_has_no_io_and_creates_nothing(tmp_path, monkeypatch):
    path = tmp_path / "none.sqlite3"

    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during construction")

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", boom)
        store = Store(path)
    assert not path.exists()
    assert store.limits.max_records > 0


def test_explicit_database_path_required():
    with pytest.raises(TypeError):
        Store(None)
    with pytest.raises(TypeError):
        Store()
    assert not hasattr(store_module, "DEFAULT_DB_PATH")
    assert not hasattr(store_module, "DEFAULT_PATH")
    assert not hasattr(store_module, "PRODUCTION_PATH")


def test_no_db_created_by_constructor_and_temp_only(tmp_path):
    path = tmp_path / "idem.sqlite3"
    store = Store(path)
    assert not path.exists()
    assert str(store.path).startswith(str(tmp_path))


def test_explicit_initialization_creates_schema(tmp_path):
    path = tmp_path / "idem.sqlite3"
    store = Store(path)
    assert not path.exists()
    store.initialize()
    assert path.exists()
    with sqlite3.connect(str(path)) as db:
        tables = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert "idempotency_records" in tables
    assert "idempotency_meta" in tables


def test_schema_version_recorded(tmp_path):
    path = tmp_path / "idem.sqlite3"
    make_store(tmp_path)
    with sqlite3.connect(str(path)) as db:
        version = db.execute(
            "SELECT v FROM idempotency_meta WHERE k='schema_version'"
        ).fetchone()[0]
    assert version == SCHEMA_VERSION
    assert SCHEMA_VERSION == "supervisor-trigger-idempotency-v1"


# --- atomic claim (5, 6, 7, 8, 9, 10, 11) -----------------------------------

def test_first_atomic_claim(store):
    result = do_claim(store)
    assert result.decision == "CLAIM_ACQUIRED"
    assert result.generation == 1
    assert result.status == "CLAIMED"


def test_same_request_while_claimed(store):
    do_claim(store)
    assert do_claim(store).decision == "ALREADY_IN_PROGRESS"


def test_same_request_while_in_progress(store):
    do_claim(store)
    do_running(store)
    assert do_claim(store).decision == "ALREADY_IN_PROGRESS"


def test_same_key_same_request_replay(store):
    do_claim(store)
    do_running(store)
    do_complete(store, response={"code": "OK"})
    replay = do_claim(store)
    assert replay.decision == "REPLAY_COMPLETED"
    assert replay.replay is True
    assert replay.response == {"code": "OK"}


def test_same_key_different_request_conflict(store):
    do_claim(store)
    assert do_claim(store, request_fingerprint=FP2).decision == "CONFLICT"


def test_different_principal_cannot_replay(store):
    do_claim(store)
    do_running(store)
    do_complete(store, response={"code": "OK"})
    other = do_claim(store, principal_scope=SCOPE2)
    assert other.decision == "CLAIM_ACQUIRED"
    assert other.generation == 1


def test_different_operation_cannot_replay(store):
    do_claim(store)
    do_running(store)
    do_complete(store, response={"code": "OK"})
    other = do_claim(store, operation=OP2)
    assert other.decision == "CLAIM_ACQUIRED"


def test_generation_allocated_on_new_claim(store):
    assert do_claim(store).generation == 1


# --- transitions and fencing (12, 13, 14, 15, 16, 17) -----------------------

def test_generation_increments_on_expired_reclaim(store):
    do_claim(store, expires_at=datetime(2026, 9, 29, 12, 1, tzinfo=timezone.utc))
    later = datetime(2026, 9, 29, 12, 1, tzinfo=timezone.utc)
    reclaimed = do_claim(store, now=later)
    assert reclaimed.decision == "EXPIRED_RECLAIMED"
    assert reclaimed.generation == 2


def test_stale_generation_rejected(store):
    do_claim(store)
    do_running(store)
    result = do_complete(store, gen=99, response={"code": "OK"})
    assert result.decision == "STALE_GENERATION"
    assert result.applied is False
    assert store.get_record(key="req-1", operation=OP, principal_scope=SCOPE).status == "IN_PROGRESS"


def test_wrong_owner_rejected(store):
    do_claim(store)
    do_running(store)
    result = do_complete(store, owner="O" + "f" * 32, response={"code": "OK"})
    assert result.decision == "WRONG_OWNER"
    assert result.applied is False


def test_mark_running_valid(store):
    do_claim(store)
    result = do_running(store)
    assert result.decision == "APPLIED"
    assert result.status == "IN_PROGRESS"


def test_illegal_mark_running_rejected(store):
    do_claim(store)
    do_running(store)
    result = do_running(store)
    assert result.decision == "ILLEGAL_TRANSITION"
    assert result.applied is False


def test_complete_success(store):
    do_claim(store)
    do_running(store)
    result = do_complete(store, response={"code": "OK", "count": 2})
    assert result.decision == "APPLIED"
    assert result.status == "COMPLETED"
    assert result.response == {"code": "OK", "count": 2}


def test_repeat_identical_completion_is_deterministic(store):
    do_claim(store)
    do_running(store)
    do_complete(store, response={"code": "OK"})
    again = do_complete(store, response={"code": "OK"})
    assert again.decision == "ALREADY_COMPLETED"
    assert again.idempotent is True


def test_conflicting_completion_rejected(store):
    do_claim(store)
    do_running(store)
    do_complete(store, response={"code": "OK"})
    conflict = do_complete(store, response={"code": "DIFFERENT"})
    assert conflict.decision == "CONFLICT"
    assert conflict.applied is False


# --- failure and retry (20, 21, 22, 23) -------------------------------------

def test_retryable_failure(store):
    do_claim(store)
    do_running(store)
    result = store.complete_failure_retryable(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, owner_id=OWNER, error_class="RUNNER_UNAVAILABLE", now=NOW,
    )
    assert result.decision == "APPLIED"
    assert result.status == "FAILED_RETRYABLE"


def test_final_failure(store):
    do_claim(store)
    do_running(store)
    result = store.complete_failure_final(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, owner_id=OWNER, error_class="SCHEMA_INVALID", now=NOW,
    )
    assert result.decision == "APPLIED"
    assert result.status == "FAILED_FINAL"


def test_retry_after_retryable_failure(store):
    do_claim(store)
    do_running(store)
    store.complete_failure_retryable(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, owner_id=OWNER, error_class="RUNNER_UNAVAILABLE", now=NOW,
    )
    retry = do_claim(store)
    assert retry.decision == "RETRY_ALLOWED"
    assert retry.generation == 2
    assert retry.retryable is True


def test_final_failure_blocks_retry(store):
    do_claim(store)
    do_running(store)
    store.complete_failure_final(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, owner_id=OWNER, error_class="SCHEMA_INVALID", now=NOW,
    )
    assert do_claim(store).decision == "CONFLICT"


# --- expiry (24, 25) --------------------------------------------------------

def test_exact_expiry_boundary_is_inclusive(store):
    do_claim(store, expires_at=datetime(2026, 9, 29, 12, 1, tzinfo=timezone.utc))
    at_boundary = do_claim(store, now=datetime(2026, 9, 29, 12, 1, tzinfo=timezone.utc))
    assert at_boundary.decision == "EXPIRED_RECLAIMED"
    before = do_claim(store, now=datetime(2026, 9, 29, 12, 0, 30, tzinfo=timezone.utc))
    assert before.decision == "ALREADY_IN_PROGRESS"


def test_expired_reclaim_advances_generation(store):
    do_claim(store, ttl_seconds=60)
    reclaimed = do_claim(store, now=NOW.replace(minute=1))
    assert reclaimed.decision == "EXPIRED_RECLAIMED"
    assert reclaimed.generation == 2
    assert reclaimed.status == "CLAIMED"
    assert reclaimed.owner_id is not None


# --- recovery (26) ----------------------------------------------------------

def test_ambiguous_recovery_blocked(store):
    do_claim(store)
    assert store.recover_abandoned_claim(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, lock_acquirable=False, lease_expired=True, now=NOW,
    ).decision == "BLOCKED"
    assert store.recover_abandoned_claim(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, lock_acquirable=True, lease_expired=False, now=NOW,
    ).decision == "BLOCKED"
    assert store.recover_abandoned_claim(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, lock_acquirable=True, lease_expired=True,
        process_alive=True, now=NOW,
    ).decision == "NOT_RECLAIMABLE"


def test_deterministic_recovery_reclaims(store):
    do_claim(store)
    result = store.recover_abandoned_claim(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, lock_acquirable=True, lease_expired=True, now=NOW,
        new_owner_id_value="O" + "2" * 32,
    )
    assert result.decision == "RECLAIMED"
    assert result.reclaimed is True
    assert result.generation == 2


def test_recovery_generation_mismatch(store):
    do_claim(store)
    result = store.recover_abandoned_claim(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=5, lock_acquirable=True, lease_expired=True, now=NOW,
    )
    assert result.decision == "GENERATION_MISMATCH"


def test_recovery_terminal_record(store):
    do_claim(store)
    do_running(store)
    do_complete(store, response={"code": "OK"})
    result = store.recover_abandoned_claim(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, lock_acquirable=True, lease_expired=True, now=NOW,
    )
    assert result.decision == "TERMINAL"


# --- persistence / replay after reopen (27, 28) -----------------------------

def test_crash_reopen_persistence(tmp_path):
    first = make_store(tmp_path)
    do_claim(first)
    do_running(first)
    do_complete(first, response={"code": "OK"})
    reopened = make_store(tmp_path)
    record = reopened.get_record(key="req-1", operation=OP, principal_scope=SCOPE)
    assert record is not None
    assert record.status == "COMPLETED"


def test_completed_replay_after_reopen(tmp_path):
    first = make_store(tmp_path)
    do_claim(first)
    do_running(first)
    do_complete(first, response={"code": "OK", "count": 3})
    reopened = make_store(tmp_path)
    replay = do_claim(reopened)
    assert replay.decision == "REPLAY_COMPLETED"
    assert replay.response == {"code": "OK", "count": 3}


# --- response contract (29, 30, 31, 32) -------------------------------------

def test_bounded_response_round_trips(store):
    do_claim(store)
    do_running(store)
    payload = {"code": "OK", "warnings": ["LOW_COVERAGE"], "count": 4}
    assert do_complete(store, response=payload).decision == "APPLIED"
    assert store.read_result(
        key="req-1", operation=OP, principal_scope=SCOPE
    ).response == payload


def test_oversized_response_rejected(store):
    do_claim(store)
    do_running(store)
    payload = {"warnings": ["x" * 400 for _ in range(60)]}
    result = do_complete(store, response=payload)
    assert result.decision == "REJECTED"
    assert result.reason_code == "RESPONSE_TOO_LARGE"
    assert store.get_record(key="req-1", operation=OP, principal_scope=SCOPE).status == "IN_PROGRESS"


def test_secret_response_rejected(store):
    do_claim(store)
    do_running(store)
    for payload in (
        {"api_key": "abc"},
        {"note": "Authorization: Bearer xyz"},
        {"detail": "/home/operator/secret.txt"},
    ):
        result = do_complete(store, response=payload)
        assert result.decision == "REJECTED"
        assert result.reason_code == "RESPONSE_FORBIDDEN"
    assert store.get_record(key="req-1", operation=OP, principal_scope=SCOPE).status == "IN_PROGRESS"


def test_raw_exception_text_not_persisted(store):
    do_claim(store)
    do_running(store)
    rejected = store.complete_failure_retryable(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, owner_id=OWNER,
        error_class="Traceback (most recent call last): boom", now=NOW,
    )
    assert rejected.decision == "REJECTED"
    assert rejected.reason_code == "INPUT_INVALID"
    result = store.complete_failure_retryable(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=1, owner_id=OWNER, error_class="RUNNER_UNAVAILABLE", now=NOW,
    )
    assert result.decision == "APPLIED"
    record = store.get_record(key="req-1", operation=OP, principal_scope=SCOPE)
    assert record.error_class == "RUNNER_UNAVAILABLE"


# --- boundedness (33, 34, 35, 36) -------------------------------------------

def test_bounded_lookup_limit(tmp_path):
    store = make_store(tmp_path, max_query_limit=2)
    for index in range(3):
        do_claim(store, key=f"req-{index}")
    assert len(store.recent_records(limit=100)) == 2
    assert len(store.recent_records(limit=1)) == 1


def test_bounded_recovery_scan(tmp_path):
    store = make_store(tmp_path, limits=IdempotencyLimits(max_recovery_scan=2))
    for index in range(3):
        do_claim(store, key=f"req-{index}")
    assert len(store.recovery_candidates(limit=1000)) == 2


def test_bounded_cleanup_batch(tmp_path):
    store = make_store(tmp_path, max_cleanup_batch=2)
    old = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    for index in range(5):
        do_claim(store, key=f"req-{index}", now=old)
        do_running(store, key=f"req-{index}", now=old)
        do_complete(store, key=f"req-{index}", response={"code": "OK"}, now=old)
    first = store.cleanup(now=NOW, batch=100)
    assert first.scanned <= 2
    assert first.deleted <= 2
    assert len(store.recent_records(limit=100)) <= 5


def test_cleanup_never_deletes_active_claim(store):
    do_claim(store, ttl_seconds=7 * 24 * 60 * 60)
    result = store.cleanup(now=NOW)
    assert result.deleted == 0
    assert store.get_record(key="req-1", operation=OP, principal_scope=SCOPE) is not None


def test_capacity_exhaustion_fails_closed(tmp_path):
    store = make_store(tmp_path, max_records=1)
    assert do_claim(store, key="req-1").decision == "CLAIM_ACQUIRED"
    result = do_claim(store, key="req-2")
    assert result.decision == "AUTHORITY_UNAVAILABLE"
    assert result.reason_code == "CAPACITY_EXHAUSTED"


def test_active_capacity_exhaustion_fails_closed(tmp_path):
    store = make_store(tmp_path, limits=IdempotencyLimits(max_active_claims=1))
    assert do_claim(store, key="req-1").decision == "CLAIM_ACQUIRED"
    result = do_claim(store, key="req-2")
    assert result.decision == "AUTHORITY_UNAVAILABLE"
    assert result.reason_code == "CAPACITY_EXHAUSTED"


# --- database failure isolation (37, 38, 39, 40) ----------------------------

def test_busy_database_fails_safely(tmp_path):
    path = tmp_path / "idem.sqlite3"
    store = make_store(tmp_path, timeout_seconds=0.1)
    blocker = sqlite3.connect(str(path), isolation_level=None, timeout=5.0)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        result = do_claim(store)
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert result.decision == "AUTHORITY_UNAVAILABLE"
    assert result.reason_code in ("DATABASE_BUSY", "DATABASE_UNAVAILABLE")


def test_unsupported_schema_version(tmp_path):
    first = make_store(tmp_path, schema_version=SCHEMA_VERSION)
    first.initialize()
    other = Store(tmp_path / "idem.sqlite3", schema_version="supervisor-trigger-idempotency-v2")
    with pytest.raises(IdempotencyStoreError) as error:
        other.initialize()
    assert error.value.code == "SCHEMA_UNSUPPORTED"
    result = do_claim(other)
    assert result.decision == "AUTHORITY_UNAVAILABLE"
    assert result.reason_code == "SCHEMA_UNSUPPORTED"


def test_corrupt_database_isolated(tmp_path):
    path = tmp_path / "idem.sqlite3"
    path.write_bytes(b"this is not a sqlite database at all")
    store = Store(path)
    result = do_claim(store)
    assert result.decision == "CORRUPT"


class _ExplodingStore(Store):
    @staticmethod
    def _insert_claim(conn, params):
        Store._insert_claim(conn, params)
        raise sqlite3.OperationalError("forced failure")


def test_transaction_rollback_on_failure(tmp_path):
    path = tmp_path / "idem.sqlite3"
    store = _ExplodingStore(path)
    store.initialize()
    result = do_claim(store)
    assert result.decision == "AUTHORITY_UNAVAILABLE"
    with sqlite3.connect(str(path)) as db:
        count = db.execute("SELECT COUNT(*) FROM idempotency_records").fetchone()[0]
    assert count == 0


# --- concurrency and multiprocess (41, 42, 43) -----------------------------

def _mp_claim_worker(path, barrier, queue):
    try:
        store = Store(path, timeout_seconds=10.0)
        barrier.wait(timeout=20)
        result = store.claim(
            key="req-1", request_fingerprint=FP, principal_scope=SCOPE,
            operation=OP, now=NOW, owner_id=OWNER,
        )
        queue.put(result.decision)
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        queue.put("ERROR:" + type(exc).__name__)


def test_concurrent_processes_single_winner(tmp_path):
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork start method unavailable")
    path = tmp_path / "idem.sqlite3"
    Store(path).initialize()
    ctx = multiprocessing.get_context("fork")
    barrier = ctx.Barrier(2)
    queue = ctx.Queue()
    processes = [
        ctx.Process(target=_mp_claim_worker, args=(str(path), barrier, queue))
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    results = [queue.get(timeout=30) for _ in processes]
    for process in processes:
        process.join(timeout=30)
    assert sorted(results) == ["ALREADY_IN_PROGRESS", "CLAIM_ACQUIRED"]


def test_concurrent_same_request_one_winner(tmp_path):
    store = make_store(tmp_path)

    def attempt(_index):
        worker = Store(store.path, timeout_seconds=10.0)
        return do_claim(worker).decision

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert results.count("CLAIM_ACQUIRED") == 1
    assert set(results) <= {"CLAIM_ACQUIRED", "ALREADY_IN_PROGRESS"}


def test_concurrent_conflicting_request_produces_conflict(tmp_path):
    store = make_store(tmp_path)

    def attempt(index):
        worker = Store(store.path, timeout_seconds=10.0)
        fingerprint = FP if index % 2 == 0 else FP2
        return do_claim(worker, request_fingerprint=fingerprint).decision

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert results.count("CLAIM_ACQUIRED") == 1
    assert results.count("CONFLICT") >= 1
    assert set(results) <= {"CLAIM_ACQUIRED", "ALREADY_IN_PROGRESS", "CONFLICT"}


# --- scoping (44) -----------------------------------------------------------

def test_no_cross_principal_leakage(store):
    do_claim(store)
    do_running(store)
    do_complete(store, response={"code": "OK", "count": 7})
    other_read = store.read_result(key="req-1", operation=OP, principal_scope=SCOPE2)
    assert other_read.found is False
    assert other_read.response is None
    own_read = store.read_result(key="req-1", operation=OP, principal_scope=SCOPE)
    assert own_read.found is True
    assert own_read.response == {"code": "OK", "count": 7}


# --- input validation -------------------------------------------------------

def test_invalid_input_rejected(store):
    with pytest.raises(IdempotencyStoreError):
        do_claim(store, key="")
    with pytest.raises(IdempotencyStoreError):
        do_claim(store, key="bad key")
    with pytest.raises(IdempotencyStoreError):
        do_claim(store, principal_scope="P" + "x" * 2000)


# --- static safety (49, 50, 51, 52, 53, 54, 55, 56, 57) ---------------------

def test_no_os_lock_file_or_flock(store, tmp_path):
    do_claim(store)
    do_running(store)
    do_complete(store, response={"code": "OK"})
    assert "flock" not in SOURCE
    assert "fcntl" not in SOURCE
    assert ".lock" not in SOURCE
    assert not list(tmp_path.glob("*.lock"))


def test_no_api_route_added():
    for token in ("APIRouter", "add_api_route", "@router", "include_router", "FastAPI"):
        assert token not in SOURCE


def test_no_manual_runner_invocation():
    for token in ("manual_monitoring_runner", "ManualMonitoringRunner", "run_once", "ManualRunResult"):
        assert token not in SOURCE


def test_no_monitoring_execution_or_composition():
    for token in ("MonitoringStateService", "monitoring_state_service", "supervisor_router",
                  "backend.main", "backend.api.supervisor"):
        assert token not in SOURCE


def test_no_background_scheduler_or_notification():
    for token in ("asyncio", "threading", "concurrent.futures", "Timer", "Scheduler",
                  "scheduler", "notify", "notification"):
        assert token not in SOURCE


def test_no_trading_authority():
    for token in ("bot_manager", "place_order", "governance", "LIVE_ARM", "order_dispatch"):
        assert token not in SOURCE
