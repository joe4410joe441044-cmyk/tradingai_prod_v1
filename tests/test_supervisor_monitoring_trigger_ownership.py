"""Phase 3D-2B OS advisory ownership lock and fencing tests.

Temporary paths only.  No API route, no manual runner, no monitoring execution,
no Production database, no notification, no scheduler and no background task.
"""
from __future__ import annotations

import builtins
import errno
import inspect
import json
import multiprocessing
import os
import stat as stat_module
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.supervisor import monitoring_trigger_ownership as ownership_module
from backend.supervisor.monitoring_trigger_ownership import (
    DEFAULT_MAX_METADATA_BYTES,
    EXPLICIT_LOCK_PATH_REQUIRED,
    PRODUCTION_DEFAULT_LOCK_PATH,
    MonitoringTriggerOwnership,
    MonitoringTriggerOwnershipCoordinator,
    OwnerMetadata,
    OwnershipLimits,
)

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
INSTANCE = "I" + "a" * 16
OP = "SUPERVISOR_MONITORING_RUN_ONCE"
FP = "a" * 64
SCOPE = "Poperatorscope"
OWNER = "O" + "1" * 32
SOURCE = inspect.getsource(ownership_module)
REPO_ROOT = Path(__file__).resolve().parents[1]

_HAS_FCNTL = getattr(ownership_module, "FCNTL_AVAILABLE", False)


def make_owner(tmp_path, name="trigger.lock", **kwargs):
    kwargs.setdefault("instance_id", INSTANCE)
    kwargs.setdefault("clock", lambda: NOW)
    kwargs.setdefault("process_start_provider", lambda pid: "fixed-start")
    return MonitoringTriggerOwnership(tmp_path / name, **kwargs)


def acquire(owner, *, request="req-1", run="run-1", operation=OP, generation=1, owner_id=None):
    return owner.acquire(request, run, operation, generation, owner_id=owner_id)


@pytest.fixture
def owner(tmp_path):
    instance = make_owner(tmp_path)
    yield instance
    instance.release()


# --- 1, 2: import / construction perform no I/O -----------------------------

def test_import_has_no_io(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during import")

    module = types.ModuleType("backend.supervisor._ownership_reimport")
    module.__package__ = "backend.supervisor"
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", boom)
        patch.setattr(os, "open", boom)
        patch.setitem(sys.modules, module.__name__, module)
        exec(compile(SOURCE, "monitoring_trigger_ownership.py", "exec"), module.__dict__)
    assert callable(module.MonitoringTriggerOwnership)


def test_constructor_has_no_io_and_creates_nothing(tmp_path, monkeypatch):
    path = tmp_path / "none.lock"

    def boom(*_args, **_kwargs):
        raise AssertionError("I/O during construction")

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", boom)
        patch.setattr(builtins, "open", boom)
        instance = MonitoringTriggerOwnership(path, instance_id=INSTANCE)
    assert not path.exists()
    assert instance.current_status().active is False


# --- 3, 4: explicit path authority ------------------------------------------

def test_explicit_lock_path_required(tmp_path):
    with pytest.raises(TypeError):
        MonitoringTriggerOwnership(None)
    with pytest.raises(TypeError):
        MonitoringTriggerOwnership("")
    with pytest.raises(ValueError):
        MonitoringTriggerOwnership("relative.lock")


def test_no_production_default_path():
    assert PRODUCTION_DEFAULT_LOCK_PATH is None
    assert EXPLICIT_LOCK_PATH_REQUIRED is True
    for token in ("DEFAULT_LOCK_PATH", "PRODUCTION_LOCK_PATH", "AI_SUPERVISOR_MONITORING_TRIGGER_LOCK_PATH"):
        assert not hasattr(ownership_module, token)
    assert "logs/runtime" not in SOURCE


# --- 5, 6: parent directory behavior ----------------------------------------

def test_missing_parent_is_not_configured(tmp_path):
    instance = MonitoringTriggerOwnership(
        tmp_path / "missing" / "trigger.lock", instance_id=INSTANCE
    )
    lease = acquire(instance)
    assert lease.state == "NOT_CONFIGURED"
    assert lease.acquired is False


def test_explicit_parent_creation(tmp_path):
    target = tmp_path / "made" / "sub" / "trigger.lock"
    instance = MonitoringTriggerOwnership(
        target, create_parent=True, instance_id=INSTANCE, process_start_provider=lambda p: "s"
    )
    lease = acquire(instance)
    assert lease.state == "ACQUIRED"
    assert target.parent.is_dir()
    instance.release()


# --- 7, 8, 9, 10, 11: secure file open --------------------------------------

def test_restrictive_file_mode(owner, tmp_path):
    lease = acquire(owner)
    assert lease.state == "ACQUIRED"
    assert stat_module.S_IMODE((tmp_path / "trigger.lock").stat().st_mode) == 0o600


def test_regular_file_accepted(tmp_path):
    path = tmp_path / "trigger.lock"
    path.write_text("")
    instance = make_owner(tmp_path)
    lease = acquire(instance)
    assert lease.state == "ACQUIRED"
    instance.release()


def test_symlink_rejected(tmp_path):
    real = tmp_path / "real.target"
    real.write_text("x")
    link = tmp_path / "trigger.lock"
    os.symlink(real, link)
    instance = make_owner(tmp_path)
    assert acquire(instance).state == "UNSAFE_FILE"


def test_directory_rejected(tmp_path):
    os.mkdir(tmp_path / "trigger.lock")
    instance = make_owner(tmp_path)
    assert acquire(instance).state == "UNSAFE_FILE"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="mkfifo unavailable")
def test_fifo_rejected(tmp_path):
    os.mkfifo(tmp_path / "trigger.lock")
    instance = make_owner(tmp_path)
    assert acquire(instance).state == "UNSAFE_FILE"


def test_unsupported_platform_fails_closed(tmp_path, monkeypatch):
    instance = make_owner(tmp_path)
    monkeypatch.setattr(ownership_module, "FCNTL_AVAILABLE", False)
    lease = acquire(instance)
    assert lease.state == "UNSUPPORTED"
    assert lease.result.unsupported_platform is True
    assert lease.acquired is False


# --- 13, 14, 15: acquisition ------------------------------------------------

def test_first_acquisition_succeeds(owner):
    lease = acquire(owner)
    assert lease.state == "ACQUIRED"
    assert lease.acquired is True
    assert lease.generation == 1
    assert lease.owner_metadata is not None
    assert lease.result.fencing_state is None


def test_second_manager_same_process_busy(owner, tmp_path):
    assert acquire(owner).state == "ACQUIRED"
    other = make_owner(tmp_path)
    assert acquire(other).state == "BUSY"


@pytest.mark.skipif(not _HAS_FCNTL, reason="fcntl unavailable")
def test_busy_is_non_blocking(owner, tmp_path):
    assert acquire(owner).state == "ACQUIRED"
    other = make_owner(tmp_path)
    start = time.monotonic()
    lease = acquire(other)
    elapsed = time.monotonic() - start
    assert lease.state == "BUSY"
    assert elapsed < 2.0


# --- 16, 17, 18, 19: release and cleanup ------------------------------------

def test_release_permits_reacquisition(owner, tmp_path):
    assert acquire(owner).state == "ACQUIRED"
    owner.release()
    other = make_owner(tmp_path)
    assert acquire(other).state == "ACQUIRED"
    other.release()


def test_repeat_release_is_safe(owner):
    assert acquire(owner).state == "ACQUIRED"
    owner.release()
    owner.release()
    assert owner.current_status().active is False


def test_exception_releases_lock(tmp_path):
    instance = make_owner(tmp_path)
    with pytest.raises(RuntimeError):
        with instance.acquire("req-1", "run-1", OP, 1) as lease:
            assert lease.acquired is True
            raise RuntimeError("caller work failed")
    assert instance.current_status().active is False
    other = make_owner(tmp_path)
    assert acquire(other).state == "ACQUIRED"
    other.release()


def test_descriptor_closes(owner):
    lease = acquire(owner)
    assert owner.current_status().descriptor_open is True
    lease.release()
    assert owner.current_status().descriptor_open is False
    assert owner._fd is None


@pytest.mark.skipif(not _HAS_FCNTL, reason="fcntl unavailable")
def test_descriptor_is_cloexec(owner):
    import fcntl

    acquire(owner)
    fd = owner._fd
    assert fd is not None
    assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
    assert os.get_inheritable(fd) is False


def test_release_failure_is_bounded(owner, monkeypatch):
    acquire(owner)

    class FakeFcntl:
        LOCK_EX = object()
        LOCK_NB = object()
        LOCK_UN = object()

        @staticmethod
        def flock(*_args, **_kwargs):
            raise RuntimeError("unlock blew up")

    monkeypatch.setattr(ownership_module, "_fcntl", FakeFcntl)
    owner.release()
    assert owner._fd is None


# --- 14/20: multi-process ---------------------------------------------------

def _mp_hold_worker(path, ready, release_event, results):
    owner = MonitoringTriggerOwnership(path, instance_id=INSTANCE)
    try:
        lease = owner.acquire("req-1", "run-1", OP, 1)
        results.put(lease.state)
        ready.set()
        if lease.acquired:
            release_event.wait(timeout=20)
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        results.put("ERROR:" + type(exc).__name__)
        ready.set()
    finally:
        owner.release()


def _mp_exit_worker(path, ready, results):
    owner = MonitoringTriggerOwnership(path, instance_id=INSTANCE)
    try:
        lease = owner.acquire("req-1", "run-1", OP, 1)
        results.put(lease.state)
    except BaseException as exc:  # noqa: BLE001 - reported to the parent
        results.put("ERROR:" + type(exc).__name__)
    ready.set()
    os._exit(0)


def _fork_context():
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork start method unavailable")
    return multiprocessing.get_context("fork")


def test_second_process_returns_busy(tmp_path):
    ctx = _fork_context()
    path = tmp_path / "trigger.lock"
    ready = ctx.Event()
    release_event = ctx.Event()
    results = ctx.Queue()
    child = ctx.Process(target=_mp_hold_worker, args=(str(path), ready, release_event, results))
    child.start()
    try:
        assert ready.wait(timeout=20)
        assert results.get(timeout=20) == "ACQUIRED"
        parent = make_owner(tmp_path)
        assert acquire(parent).state == "BUSY"
    finally:
        release_event.set()
        child.join(timeout=20)
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)


def test_process_exit_releases_lock(tmp_path):
    ctx = _fork_context()
    path = tmp_path / "trigger.lock"
    ready = ctx.Event()
    results = ctx.Queue()
    child = ctx.Process(target=_mp_exit_worker, args=(str(path), ready, results))
    child.start()
    try:
        assert ready.wait(timeout=20)
        assert results.get(timeout=20) == "ACQUIRED"
        child.join(timeout=20)
        assert not child.is_alive()
        parent = make_owner(tmp_path)
        assert acquire(parent).state == "ACQUIRED"
        parent.release()
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)


# --- 21, 22, 23, 24: owner metadata -----------------------------------------

def test_stale_metadata_does_not_imply_ownership(owner, tmp_path):
    acquire(owner)
    owner.release()
    view = owner.read_owner_metadata()
    assert view.present is True
    assert view.active_owner is False
    assert view.authority == "DIAGNOSTIC_ONLY"
    other = make_owner(tmp_path)
    assert acquire(other).state == "ACQUIRED"
    other.release()


def test_metadata_bounded(tmp_path):
    limits = OwnershipLimits(max_metadata_bytes=64)
    instance = make_owner(tmp_path, limits=limits)
    lease = acquire(instance)
    assert lease.state == "ERROR"
    assert lease.result.reason_code == "METADATA_TOO_LARGE"
    assert instance.current_status().active is False
    other = make_owner(tmp_path)
    assert acquire(other).state == "ACQUIRED"
    other.release()


def test_metadata_size_within_bound(tmp_path):
    instance = make_owner(tmp_path)
    acquire(instance)
    raw = instance.read_owner_metadata().metadata.stable_json().encode("utf-8")
    assert 0 < len(raw) <= DEFAULT_MAX_METADATA_BYTES
    instance.release()


def test_secret_like_metadata_rejected(tmp_path):
    with pytest.raises(ValueError):
        MonitoringTriggerOwnership(tmp_path / "trigger.lock", instance_id="PASSWORD123")
    instance = make_owner(tmp_path)
    lease = instance.acquire("API_KEY_1", "run-1", OP, 1)
    assert lease.state == "ERROR"
    assert lease.result.reason_code == "INPUT_INVALID"
    assert instance.current_status().active is False


def test_pid_alone_is_insufficient(owner, tmp_path):
    acquire(owner)
    metadata = owner.read_owner_metadata().metadata
    owner.release()
    assert metadata.process_id > 0
    assert metadata.authority == "ADVISORY_LOCK_NOT_PID"
    view = owner.read_owner_metadata()
    assert view.present is True
    assert view.active_owner is False
    other = make_owner(tmp_path)
    assert acquire(other).state == "ACQUIRED"
    other.release()


def test_process_start_identity_present_or_unavailable(tmp_path):
    available = make_owner(tmp_path, process_start_provider=lambda pid: "raw-start")
    acquire(available)
    meta = available.owner_metadata
    available.release()
    assert meta.process_start_state == "AVAILABLE"
    assert meta.process_start_identity.startswith("PS")

    unavailable = make_owner(
        tmp_path, name="other.lock", process_start_provider=lambda pid: None
    )
    acquire(unavailable)
    meta2 = unavailable.owner_metadata
    unavailable.release()
    assert meta2.process_start_state == "UNAVAILABLE"
    assert meta2.process_start_identity is None


def test_metadata_provider_failure_is_unavailable(tmp_path):
    def explode(_pid):
        raise RuntimeError("provider failed")

    instance = make_owner(tmp_path, process_start_provider=explode)
    acquire(instance)
    assert instance.owner_metadata.process_start_state == "UNAVAILABLE"
    assert instance.owner_metadata.process_start_identity is None
    instance.release()


def test_fixed_clock_determinism(tmp_path):
    first = make_owner(tmp_path)
    acquire(first)
    first_metadata = first.owner_metadata.stable_json()
    first.release()

    second = make_owner(tmp_path)
    acquire(second)
    second_metadata = second.owner_metadata.stable_json()
    second.release()

    assert first_metadata == second_metadata
    assert first.owner_metadata.acquired_at == NOW


def test_owner_id_bounded(tmp_path):
    instance = make_owner(tmp_path)
    bad = instance.acquire("req-1", "run-1", OP, 1, owner_id="O" + "x" * 200)
    assert bad.state == "ERROR"
    assert bad.result.reason_code == "INPUT_INVALID"
    good = instance.acquire("req-1", "run-1", OP, 1, owner_id=OWNER)
    assert good.state == "ACQUIRED"
    assert good.owner_metadata.owner_ref == OWNER
    instance.release()


def test_request_run_operation_bounded(tmp_path):
    instance = make_owner(tmp_path)
    assert instance.acquire("x" * 200, "run-1", OP, 1).result.reason_code == "INPUT_INVALID"
    assert instance.acquire("req-1", "r" * 200, OP, 1).result.reason_code == "INPUT_INVALID"
    assert instance.acquire("req-1", "run-1", "O" * 100, 1).result.reason_code == "INPUT_INVALID"
    assert instance.acquire("req-1", "run-1", OP, 0).result.reason_code == "INPUT_INVALID"
    assert instance.current_status().active is False


# --- 29-34: fencing integration ---------------------------------------------

def _store(tmp_path, name="idem.sqlite3"):
    from backend.supervisor.monitoring_trigger_idempotency_store import (
        MonitoringTriggerIdempotencyStore,
    )

    store = MonitoringTriggerIdempotencyStore(tmp_path / name)
    store.initialize()
    return store


def _claim(store, *, owner_id=None, key="req-1"):
    return store.claim(
        key=key, request_fingerprint=FP, principal_scope=SCOPE,
        operation=OP, now=NOW, owner_id=owner_id,
    )


def _coordinator(tmp_path, store, name="trigger.lock"):
    return MonitoringTriggerOwnershipCoordinator(
        ownership=make_owner(tmp_path, name=name), store=store
    )


def test_correct_generation_accepted(tmp_path):
    store = _store(tmp_path)
    claim = _claim(store)
    coordinator = _coordinator(tmp_path, store)
    lease = coordinator.acquire_for_claim(
        request_id="req-1", run_id=None, operation=OP, principal_scope=SCOPE,
        request_fingerprint=FP, expected_generation=claim.generation,
        expected_owner_id=claim.owner_id,
    )
    assert lease.acquired is True
    assert lease.state == "ACQUIRED"
    assert lease.fencing_state == "VERIFIED"
    assert lease.generation == claim.generation
    lease.release()


def test_stale_generation_rejected(tmp_path):
    store = _store(tmp_path)
    first = _claim(store)
    store.expire_record(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=first.generation, owner_id=first.owner_id, now=NOW,
    )
    second = _claim(store)
    assert second.generation == first.generation + 1
    coordinator = _coordinator(tmp_path, store)
    lease = coordinator.acquire_for_claim(
        request_id="req-1", run_id=None, operation=OP, principal_scope=SCOPE,
        request_fingerprint=FP, expected_generation=first.generation,
        expected_owner_id=first.owner_id,
    )
    assert lease.acquired is False
    assert lease.state == "FENCED"
    assert lease.fencing_state == "STALE_GENERATION"
    assert lease.result.observed_generation == second.generation
    assert coordinator.ownership.current_status().active is False


def test_wrong_owner_rejected(tmp_path):
    store = _store(tmp_path)
    claim = _claim(store, owner_id=OWNER)
    coordinator = _coordinator(tmp_path, store)
    lease = coordinator.acquire_for_claim(
        request_id="req-1", run_id=None, operation=OP, principal_scope=SCOPE,
        request_fingerprint=FP, expected_generation=claim.generation,
        expected_owner_id="O" + "f" * 32,
    )
    assert lease.acquired is False
    assert lease.fencing_state == "WRONG_OWNER"
    assert coordinator.ownership.current_status().active is False


def test_sqlite_generation_remains_authority(tmp_path):
    store = _store(tmp_path)
    first = _claim(store)
    store.expire_record(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=first.generation, owner_id=first.owner_id, now=NOW,
    )
    second = _claim(store)
    coordinator = _coordinator(tmp_path, store)
    assert coordinator.verify_owner(
        request_id="req-1", operation=OP, principal_scope=SCOPE,
        expected_generation=first.generation, expected_owner_id=first.owner_id,
    ).state == "STALE_GENERATION"
    result = store.complete_success(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=first.generation, owner_id=first.owner_id,
        response={"code": "OK"}, now=NOW,
    )
    assert result.decision == "STALE_GENERATION"
    record = store.get_record(key="req-1", operation=OP, principal_scope=SCOPE)
    assert record.generation == second.generation


def test_stale_owner_cannot_mutate_record(tmp_path):
    store = _store(tmp_path)
    first = _claim(store)
    store.expire_record(
        key="req-1", operation=OP, principal_scope=SCOPE, request_fingerprint=FP,
        expected_generation=first.generation, owner_id=first.owner_id, now=NOW,
    )
    second = _claim(store)
    coordinator = _coordinator(tmp_path, store)
    lease = coordinator.acquire_for_claim(
        request_id="req-1", run_id=None, operation=OP, principal_scope=SCOPE,
        request_fingerprint=FP, expected_generation=first.generation,
        expected_owner_id=first.owner_id,
    )
    assert lease.acquired is False
    record = store.get_record(key="req-1", operation=OP, principal_scope=SCOPE)
    assert record.generation == second.generation
    assert record.status == "CLAIMED"
    assert record.owner_id == second.owner_id


def test_valid_owner_permitted_verification(tmp_path):
    store = _store(tmp_path)
    claim = _claim(store, owner_id=OWNER)
    coordinator = _coordinator(tmp_path, store)
    result = coordinator.verify_owner(
        request_id="req-1", operation=OP, principal_scope=SCOPE,
        expected_generation=claim.generation, expected_owner_id=OWNER,
    )
    assert result.state == "VERIFIED"
    assert result.owner_matches is True
    assert result.authority == "SQLITE_IDEMPOTENCY_GENERATION"


def test_missing_record_fails_closed(tmp_path):
    store = _store(tmp_path)
    coordinator = _coordinator(tmp_path, store)
    lease = coordinator.acquire_for_claim(
        request_id="req-1", run_id=None, operation=OP, principal_scope=SCOPE,
        request_fingerprint=FP, expected_generation=1,
    )
    assert lease.acquired is False
    assert lease.fencing_state == "RECORD_NOT_FOUND"
    assert coordinator.ownership.current_status().active is False


def test_idempotency_authority_unavailable(tmp_path):
    class BrokenStore:
        @staticmethod
        def get_record(**_kwargs):
            raise RuntimeError("authority unavailable")

    coordinator = MonitoringTriggerOwnershipCoordinator(
        ownership=make_owner(tmp_path), store=BrokenStore()
    )
    lease = coordinator.acquire_for_claim(
        request_id="req-1", run_id=None, operation=OP, principal_scope=SCOPE,
        request_fingerprint=FP, expected_generation=1,
    )
    assert lease.acquired is False
    assert lease.fencing_state == "AUTHORITY_UNAVAILABLE"
    assert coordinator.ownership.current_status().active is False


# --- 35, 36: independence and unlink safety ---------------------------------

def test_different_paths_independent(owner, tmp_path):
    assert acquire(owner).state == "ACQUIRED"
    other = make_owner(tmp_path, name="other.lock")
    assert acquire(other).state == "ACQUIRED"
    other.release()


def test_no_unsafe_unlink(owner, tmp_path):
    acquire(owner)
    owner.release()
    assert (tmp_path / "trigger.lock").exists()
    assert "os.unlink" not in SOURCE
    assert ".unlink(" not in SOURCE


# --- 37, 38: error isolation ------------------------------------------------

def test_lock_path_absent_from_public_errors(tmp_path):
    real = tmp_path / "real.target"
    real.write_text("x")
    link = tmp_path / "trigger.lock"
    os.symlink(real, link)
    instance = make_owner(tmp_path)
    lease = acquire(instance)
    dumped = lease.result.model_dump_json()
    assert str(link) not in dumped
    assert "trigger.lock" not in dumped
    assert str(tmp_path) not in dumped


def test_open_failure_has_no_raw_exception(tmp_path, monkeypatch):
    instance = make_owner(tmp_path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("raw-secret-detail")

    monkeypatch.setattr(os, "open", boom)
    lease = acquire(instance)
    assert lease.state == "ERROR"
    assert lease.result.reason_code == "OPEN_FAILED"
    assert "raw-secret-detail" not in lease.result.model_dump_json()


def test_flock_failure_is_bounded(tmp_path, monkeypatch):
    instance = make_owner(tmp_path)

    class FakeFcntl:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        @staticmethod
        def flock(*_args, **_kwargs):
            raise OSError(errno.EIO, "io error")

    monkeypatch.setattr(ownership_module, "_fcntl", FakeFcntl)
    lease = acquire(instance)
    assert lease.state == "ERROR"
    assert lease.result.reason_code == "LOCK_FAILED"
    assert instance.current_status().descriptor_open is False


def test_metadata_write_failure_releases_lock(tmp_path, monkeypatch):
    instance = make_owner(tmp_path)

    def boom(*_args, **_kwargs):
        raise OSError(errno.EIO, "write failed")

    with monkeypatch.context() as patch:
        patch.setattr(os, "pwrite", boom)
        lease = acquire(instance)
    assert lease.state == "ERROR"
    assert lease.result.reason_code == "METADATA_WRITE_FAILED"
    assert instance.current_status().active is False
    other = make_owner(tmp_path)
    assert acquire(other).state == "ACQUIRED"
    other.release()


def test_metadata_serialization_failure_releases_lock(tmp_path):
    class BadMetadataOwner(MonitoringTriggerOwnership):
        def _build_metadata(self, **_kwargs):
            class Bad:
                @staticmethod
                def stable_json():
                    raise RuntimeError("cannot serialize")

            return Bad(), "OK"

    instance = BadMetadataOwner(
        tmp_path / "trigger.lock", instance_id=INSTANCE,
        process_start_provider=lambda p: "s",
    )
    lease = acquire(instance)
    assert lease.state == "ERROR"
    assert lease.result.reason_code == "METADATA_SERIALIZATION_FAILED"
    assert instance.current_status().active is False
    other = make_owner(tmp_path)
    assert acquire(other).state == "ACQUIRED"
    other.release()


# --- 39-41: artifact containment --------------------------------------------

def test_lock_file_only_under_tmp_path(owner, tmp_path):
    acquire(owner)
    lock_files = list(tmp_path.glob("*.lock"))
    assert lock_files, "expected a lock file under tmp_path"
    for path in lock_files:
        assert str(path).startswith(str(tmp_path))
    owner.release()


def test_no_repo_or_runtime_lock_artifact(owner):
    assert not list(REPO_ROOT.glob("*.lock"))
    assert "logs/runtime" not in SOURCE
    assert "supervisor_monitoring_trigger.lock" not in SOURCE


def test_no_production_database():
    assert "sqlite3" not in SOURCE
    assert ".sqlite3" not in SOURCE
    assert ".db" not in SOURCE


# --- 42-48: static safety ---------------------------------------------------

def test_no_api_route():
    for token in ("FastAPI", "APIRouter", "add_api_route", "@router", "include_router"):
        assert token not in SOURCE


def test_no_manual_runner_invocation():
    for token in ("manual_monitoring_runner", "ManualMonitoringRunner", "run_once", "ManualRunResult"):
        assert token not in SOURCE


def test_no_monitoring_execution():
    for token in ("MonitoringStateService", "monitoring_state_service", "one_shot_monitor",
                  "MonitoringReadService", "monitoring_read_service"):
        assert token not in SOURCE


def test_no_scheduler_or_background_task():
    for token in ("asyncio", "threading", "concurrent.futures", "Timer", "Scheduler", "scheduler"):
        assert token not in SOURCE


def test_no_notification():
    for token in ("notify", "notification", "alert_emit", "webhook"):
        assert token not in SOURCE


def test_no_trading_authority():
    for token in ("bot_manager", "place_order", "governance", "LIVE_ARM", "order_dispatch"):
        assert token not in SOURCE


def test_no_production_trace_access():
    for token in ("TRADING_E2E_TRACE", "trading_e2e_trace", "cycle_evidence_store",
                  "replay_service", "runtime_snapshot_adapter"):
        assert token not in SOURCE


def test_import_and_constructor_are_side_effect_free(owner):
    assert owner.current_status().active is False
    assert owner._fd is None
    assert json.loads(owner.current_status().model_dump_json())["production_default_path"] is None
