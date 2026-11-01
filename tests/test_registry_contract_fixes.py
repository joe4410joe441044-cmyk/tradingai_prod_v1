from __future__ import annotations

import fcntl
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from backend.accounts import registry_store as registry_store_module
from backend.accounts.models import (
    AccountId,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
)
from backend.accounts.registry_contract import (
    AccountRegistrationDraft,
    RegistryFailureCode,
    RegistryOperationLookupStatus,
    RegistryRegistrationStatus,
)
from backend.accounts.registry_models import (
    REGISTRY_ENVELOPE_SCHEMA_VERSION,
    REGISTRY_EVENT_SCHEMA_VERSION,
    REGISTRY_SCHEMA_VERSION,
)
from backend.accounts.registry_store import (
    AccountRegistryStore,
    DurableAccountRegistry,
    RegistryLoadStatus,
    RegistryMutationStatus,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def draft(request_id: str = "request-1", **changes) -> AccountRegistrationDraft:
    values = {
        "registration_request_id": request_id,
        "account_type": AccountType.PROP,
        "execution_mode": ExecutionMode.EXTERNAL_SIMULATION,
        "execution_venue": ExecutionVenue.BYBIT_DEMO,
        "prop_program": PropProgram.HYROTRADER,
        "prop_phase": PropPhase.CHALLENGE,
        "display_label": "Fabricated challenge account",
    }
    values.update(changes)
    return AccountRegistrationDraft(**values)


def initialized(base: Path, *, lock_timeout: float = 10.0):
    ticks = iter(NOW + timedelta(seconds=i) for i in range(100))
    store = AccountRegistryStore(base, lock_timeout=lock_timeout)
    registry = DurableAccountRegistry(store, clock=lambda: next(ticks))
    assert registry.initialize().status is RegistryMutationStatus.SAVED
    return store, registry


def registered(base: Path, *, lock_timeout: float = 10.0):
    store, registry = initialized(base, lock_timeout=lock_timeout)
    result = registry.register(
        draft(), expected_registry_revision=1, operation_id="op-register"
    )
    assert result.status is RegistryRegistrationStatus.REGISTERED
    return store, registry, result.identity.account_id


def _write_payload(store: AccountRegistryStore, payload: dict) -> None:
    payload_bytes = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    envelope = {
        "schema_version": REGISTRY_ENVELOPE_SCHEMA_VERSION,
        "digest_algorithm": "SHA256",
        "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        "payload": payload,
    }
    store.snapshot_path.write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    )
    os.chmod(store.snapshot_path, 0o600)


def _write_raw_envelope(store: AccountRegistryStore, envelope: dict) -> None:
    store.snapshot_path.write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    )
    os.chmod(store.snapshot_path, 0o600)


# --- F-02: typed lock/storage failures -------------------------------------


def test_symlink_lock_fails_closed_with_typed_storage_error(tmp_path):
    store, registry, account_id = registered(tmp_path)
    store.lock_path.unlink()
    store.lock_path.symlink_to(tmp_path / "missing-lock")
    result = registry.update_label(
        account_id,
        "Blocked",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-lock-symlink",
    )
    assert result.status is RegistryMutationStatus.FAILED
    assert result.failure_code is RegistryFailureCode.UNSAFE_STORAGE
    registration = registry.register(
        draft("other"), expected_registry_revision=2, operation_id="op-register-symlink"
    )
    assert registration.status is RegistryRegistrationStatus.FAILED
    assert registration.failure_code is RegistryFailureCode.UNSAFE_STORAGE


def test_directory_or_non_private_lock_fails_closed(tmp_path):
    store, registry, account_id = registered(tmp_path)
    original_lock_bytes = b""
    store.lock_path.unlink()
    store.lock_path.mkdir()
    directory_result = registry.update_label(
        account_id,
        "Blocked",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-lock-directory",
    )
    assert directory_result.failure_code is RegistryFailureCode.UNSAFE_STORAGE

    store.lock_path.rmdir()
    store.lock_path.write_bytes(original_lock_bytes)
    os.chmod(store.lock_path, 0o644)
    permission_result = registry.update_label(
        account_id,
        "Blocked",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-lock-permission",
    )
    assert permission_result.failure_code is RegistryFailureCode.UNSAFE_STORAGE


def test_lock_wait_is_bounded_and_typed(tmp_path):
    store, registry, account_id = registered(tmp_path, lock_timeout=0.05)
    holder = os.open(store.lock_path, os.O_RDWR)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX)
        result = registry.update_label(
            account_id,
            "Blocked",
            expected_registry_revision=2,
            expected_record_revision=1,
            operation_id="op-lock-timeout",
        )
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)
    assert result.status is RegistryMutationStatus.FAILED
    assert result.failure_code is RegistryFailureCode.LOCK_TIMEOUT
    assert store.load().snapshot.registry_revision == 2


# --- F-03: idempotency ordering / operation recovery ------------------------


def test_completed_operation_is_checked_before_stale_cas(tmp_path):
    store, registry, account_id = registered(tmp_path)
    first = registry.update_label(
        account_id,
        "Committed",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-idempotent",
    )
    assert first.status is RegistryMutationStatus.SAVED
    replay = registry.update_label(
        account_id,
        "Committed",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-idempotent",
    )
    assert replay.status is RegistryMutationStatus.IDEMPOTENT_REPLAY
    assert replay.registry_revision == 3
    assert replay.original_registry_revision == 3
    assert replay.record.display_label == "Committed"
    assert store.load().snapshot.registry_revision == 3


def test_same_operation_id_with_different_request_is_rejected(tmp_path):
    store, registry, account_id = registered(tmp_path)
    first = registry.update_label(
        account_id,
        "Original",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-bound",
    )
    assert first.status is RegistryMutationStatus.SAVED
    conflict = registry.update_label(
        account_id,
        "Different",
        expected_registry_revision=3,
        expected_record_revision=2,
        operation_id="op-bound",
    )
    assert conflict.status is RegistryMutationStatus.CONFLICT
    assert conflict.failure_code is RegistryFailureCode.IDEMPOTENCY_CONFLICT
    assert store.load().snapshot.find(account_id).display_label == "Original"


def test_commit_state_unknown_is_durable_and_recoverable_across_updates(
    tmp_path, monkeypatch
):
    store, registry, account_id = registered(tmp_path)
    original = store._fsync_directory
    calls = 0

    def fail_target_fsync():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected after target replace")
        original()

    monkeypatch.setattr(store, "_fsync_directory", fail_target_fsync)
    first = registry.update_label(
        account_id,
        "Maybe committed",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-ambiguous",
    )
    assert first.status is RegistryMutationStatus.COMMIT_STATE_UNKNOWN

    receipt = registry.find_operation("op-ambiguous")
    assert receipt.status is RegistryOperationLookupStatus.FOUND
    assert receipt.original_registry_revision == 3
    assert receipt.current_registry_revision == 3
    assert receipt.current_record_revision == 2
    assert receipt.occurred_at is not None

    reopened = DurableAccountRegistry(AccountRegistryStore(tmp_path))
    assert reopened.find_operation("op-ambiguous").status is RegistryOperationLookupStatus.FOUND

    replay = reopened.update_label(
        account_id,
        "Maybe committed",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-ambiguous",
    )
    assert replay.status is RegistryMutationStatus.IDEMPOTENT_REPLAY
    assert replay.registry_revision == 3
    assert replay.original_registry_revision == 3
    assert replay.record.display_label == "Maybe committed"
    assert store.load().snapshot.registry_revision == 3

    after = reopened.update_label(
        account_id,
        "After ambiguity",
        expected_registry_revision=3,
        expected_record_revision=2,
        operation_id="op-after",
    )
    assert after.status is RegistryMutationStatus.SAVED
    later_receipt = reopened.find_operation("op-ambiguous")
    assert later_receipt.original_registry_revision == 3
    assert later_receipt.current_registry_revision == 4
    assert later_receipt.current_record_revision == 3

    replay_after_update = reopened.update_label(
        account_id,
        "Maybe committed",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-ambiguous",
    )
    assert replay_after_update.status is RegistryMutationStatus.IDEMPOTENT_REPLAY
    assert replay_after_update.registry_revision == 4
    assert replay_after_update.original_registry_revision == 3
    assert replay_after_update.record.display_label == "After ambiguity"
    assert store.load().snapshot.registry_revision == 4


def test_new_registration_with_stale_cas_is_rejected(tmp_path):
    store, registry, _ = registered(tmp_path)
    result = registry.register(
        draft("new-request"),
        expected_registry_revision=1,
        operation_id="op-new-stale",
    )
    assert result.status is RegistryRegistrationStatus.CONFLICT
    assert result.failure_code is RegistryFailureCode.REVISION_MISMATCH
    assert store.load().snapshot.registry_revision == 2


def test_registration_recovery_after_ambiguous_commit(tmp_path, monkeypatch):
    store, registry = initialized(tmp_path)
    original = store._fsync_directory
    calls = 0

    def fail_target_fsync():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected after target replace")
        original()

    monkeypatch.setattr(store, "_fsync_directory", fail_target_fsync)
    first = registry.register(
        draft(), expected_registry_revision=1, operation_id="op-register-ambiguous"
    )
    assert first.status is RegistryRegistrationStatus.COMMIT_STATE_UNKNOWN
    committed = store.load().snapshot.records[0]
    reopened = DurableAccountRegistry(AccountRegistryStore(tmp_path))
    assert (
        reopened.find_operation("op-register-ambiguous").status
        is RegistryOperationLookupStatus.FOUND
    )

    replay = registry.register(
        draft(), expected_registry_revision=1, operation_id="op-register-ambiguous"
    )
    assert replay.status is RegistryRegistrationStatus.IDEMPOTENT_REPLAY
    assert replay.identity == committed.identity
    assert replay.registry_revision == 2
    assert replay.original_registry_revision == 2

    conflict = registry.register(
        draft(display_label="Different"),
        expected_registry_revision=1,
        operation_id="op-register-ambiguous",
    )
    assert conflict.status is RegistryRegistrationStatus.CONFLICT
    assert conflict.failure_code is RegistryFailureCode.IDEMPOTENCY_CONFLICT
    assert store.load().snapshot.registry_revision == 2


def test_recovery_read_failure_is_not_guessed(tmp_path):
    store, registry, account_id = registered(tmp_path)
    store.snapshot_path.write_bytes(b"{")
    os.chmod(store.snapshot_path, 0o600)
    receipt = registry.find_operation("op-register")
    assert receipt.status is RegistryOperationLookupStatus.INVALID
    result = registry.update_label(
        account_id,
        "Blocked",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-read-failure",
    )
    assert result.status is RegistryMutationStatus.FAILED
    assert result.failure_code is RegistryFailureCode.INVALID_DOCUMENT
    assert result.original_registry_revision is None


def test_invalid_operation_id_is_rejected_before_mutation(tmp_path):
    store, registry, account_id = registered(tmp_path)
    result = registry.update_label(
        account_id,
        "Blocked",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="contains a space",
    )
    assert result.status is RegistryMutationStatus.INVALID
    assert result.failure_code is RegistryFailureCode.INVALID_DOCUMENT
    assert store.load().snapshot.registry_revision == 2


def test_size_limit_preserves_previous_state_and_recovery_reads(tmp_path, monkeypatch):
    store, registry, account_id = registered(tmp_path)
    raw = store.snapshot_path.read_bytes()
    monkeypatch.setattr(registry_store_module, "MAX_REGISTRY_BYTES", len(raw))
    result = registry.update_label(
        account_id,
        "Too large",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-too-large",
    )
    assert result.status is RegistryMutationStatus.FAILED
    assert result.failure_code is RegistryFailureCode.SIZE_LIMIT_EXCEEDED
    assert store.snapshot_path.read_bytes() == raw
    assert store.load().status is RegistryLoadStatus.VALID
    assert registry.find_operation("op-too-large").status is RegistryOperationLookupStatus.NOT_FOUND
    assert registry.find_operation("op-register").status is RegistryOperationLookupStatus.FOUND


# --- F-04 / schema v2: semantic history and compatibility ------------------


def test_complete_operation_ledger_is_durable_through_reload(tmp_path):
    store, registry, account_id = registered(tmp_path)
    registry.update_label(
        account_id,
        "Persisted",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-persisted",
    )
    reopened = DurableAccountRegistry(AccountRegistryStore(tmp_path))
    receipt = reopened.find_operation("op-persisted")
    assert receipt.status is RegistryOperationLookupStatus.FOUND
    assert receipt.event_type.value == "LABEL_UPDATED"
    assert receipt.account_id == account_id
    assert receipt.request_fingerprint is not None
    assert reopened.find_operation("missing-operation").status is RegistryOperationLookupStatus.NOT_FOUND


@pytest.mark.parametrize("version", ["tradingai-account-registry-envelope/v1", "future-envelope/v9"])
def test_previous_or_unknown_envelope_version_is_not_silently_accepted(tmp_path, version):
    store, _, _ = registered(tmp_path)
    envelope = json.loads(store.snapshot_path.read_bytes())
    envelope["schema_version"] = version
    _write_raw_envelope(store, envelope)
    assert store.load().status is RegistryLoadStatus.INCOMPATIBLE_VERSION


def test_previous_payload_and_event_versions_are_not_silently_accepted(tmp_path):
    for version_key, version in [
        ("schema_version", "tradingai-account-registry/v1"),
        ("event_schema_version", "tradingai-account-registry-event/v1"),
    ]:
        base = tmp_path / version_key
        base.mkdir()
        store, _, _ = registered(base)
        envelope = json.loads(store.snapshot_path.read_bytes())
        if version_key == "schema_version":
            envelope["payload"]["schema_version"] = version
        else:
            envelope["payload"]["events"][0]["schema_version"] = version
        _write_payload(store, envelope["payload"])
        assert store.load().status is RegistryLoadStatus.INCOMPATIBLE_VERSION


@pytest.mark.parametrize(
    "case",
    [
        "orphan_event",
        "reordered_events",
        "impossible_record_revision",
        "wrong_changed_fields",
        "unexpected_identity_revision",
        "timestamp_regression",
        "timestamp_boundary",
        "duplicate_operation_id",
    ],
)
def test_corrupt_event_history_is_rejected(tmp_path, case):
    base = tmp_path / case
    base.mkdir()
    store, registry, account_id = registered(base)
    registry.update_label(
        account_id,
        "Renamed",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-history",
    )
    payload = json.loads(store.snapshot_path.read_bytes())["payload"]
    events = payload["events"]
    if case == "orphan_event":
        events[1]["account_id"] = AccountId.new().value
    elif case == "reordered_events":
        events[1], events[2] = events[2], events[1]
    elif case == "impossible_record_revision":
        events[2]["record_revision"] = 9
    elif case == "wrong_changed_fields":
        events[2]["changed_fields"] = ["credential_reference"]
    elif case == "unexpected_identity_revision":
        events[2]["identity_revision"] = 2
    elif case == "timestamp_regression":
        events[2]["occurred_at"] = events[0]["occurred_at"]
    elif case == "timestamp_boundary":
        events[2]["occurred_at"] = events[1]["occurred_at"]
    elif case == "duplicate_operation_id":
        events[2]["operation_id"] = events[1]["operation_id"]
    _write_payload(store, payload)
    assert store.load().status is RegistryLoadStatus.INVALID
