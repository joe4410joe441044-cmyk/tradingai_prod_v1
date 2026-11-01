from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from backend.accounts.models import (
    AccountId,
    AccountLifecycleState,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
)
from backend.accounts.registry_contract import (
    AccountRegistrationDraft,
    RegistryRegistrationStatus,
)
from backend.accounts.registry_models import (
    CREDENTIAL_REFERENCE_SCHEMA_VERSION,
    CredentialBundleReference,
    CredentialReferenceSource,
    ExternalAccountBinding,
    ExternalBindingEnvironment,
    ExternalBindingStatus,
)
from backend.accounts.registry_store import (
    AccountRegistryStore,
    DurableAccountRegistry,
    RegistryLoadStatus,
    RegistryMutationStatus,
    deserialize_snapshot,
    serialize_snapshot,
)


NOW = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


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


def initialized(tmp_path: Path):
    ticks = iter(NOW + timedelta(seconds=i) for i in range(50))
    store = AccountRegistryStore(tmp_path)
    registry = DurableAccountRegistry(store, clock=lambda: next(ticks))
    assert registry.initialize().status is RegistryMutationStatus.SAVED
    return store, registry


def registered(tmp_path: Path, **changes):
    store, registry = initialized(tmp_path)
    result = registry.register(
        draft(**changes), expected_registry_revision=1, operation_id="op-register"
    )
    assert result.status is RegistryRegistrationStatus.REGISTERED
    return store, registry, result.identity.account_id


def test_constructor_and_read_have_no_side_effects_and_relative_path_rejected(tmp_path):
    target = tmp_path / "explicit"
    target.mkdir()
    store = AccountRegistryStore(target)
    assert list(target.iterdir()) == []
    assert store.load().status is RegistryLoadStatus.MISSING
    assert list(target.iterdir()) == []
    with pytest.raises(ValueError, match="absolute"):
        AccountRegistryStore(Path("relative"))


def test_explicit_initialization_is_idempotent_and_permissions_are_private(tmp_path):
    store, registry = initialized(tmp_path)
    assert registry.initialize().status is RegistryMutationStatus.ALREADY_INITIALIZED
    snapshot = store.load().snapshot
    assert snapshot.registry_revision == 1
    assert snapshot.records == ()
    assert (store.registry_directory.stat().st_mode & 0o777) == 0o700
    assert (store.snapshot_path.stat().st_mode & 0o777) == 0o600
    assert (store.lock_path.stat().st_mode & 0o777) == 0o600


def test_registration_issues_unrelated_id_and_idempotent_replay(tmp_path):
    store, registry = initialized(tmp_path)
    first = registry.register(draft(), expected_registry_revision=1, operation_id="op-first")
    replay = registry.register(draft(), expected_registry_revision=2, operation_id="op-first")
    assert first.status is RegistryRegistrationStatus.REGISTERED
    assert replay.status is RegistryRegistrationStatus.IDEMPOTENT_REPLAY
    assert replay.identity.account_id == first.identity.account_id
    assert "request-1" not in first.identity.account_id.value
    assert store.load().snapshot.registry_revision == 2


def test_idempotency_conflict_and_id_collision_do_not_overwrite(tmp_path):
    fixed = AccountId.new()
    store = AccountRegistryStore(tmp_path)
    ticks = iter(NOW + timedelta(seconds=i) for i in range(20))
    registry = DurableAccountRegistry(store, clock=lambda: next(ticks), id_factory=lambda: fixed)
    registry.initialize()
    assert (
        registry.register(
            draft(), expected_registry_revision=1, operation_id="op-original"
        ).status
        is RegistryRegistrationStatus.REGISTERED
    )
    conflict = registry.register(
        draft(display_label="Different"),
        expected_registry_revision=2,
        operation_id="op-conflict",
    )
    collision = registry.register(
        draft("request-2"), expected_registry_revision=2, operation_id="op-collision"
    )
    assert conflict.status is RegistryRegistrationStatus.CONFLICT
    assert collision.status is RegistryRegistrationStatus.ALREADY_EXISTS
    assert store.load().snapshot.registry_revision == 2


def test_label_and_credential_rotation_preserve_id_and_identity_revision(tmp_path):
    store, registry, account_id = registered(tmp_path)
    label = registry.update_label(
        account_id,
        "Renamed",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-label",
    )
    reference = CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        "test-bundle-1",
        "HYRO_DEMO",
    )
    rotated = registry.rotate_credential_reference(
        account_id,
        reference,
        expected_registry_revision=3,
        expected_record_revision=2,
        operation_id="op-credential",
    )
    record = store.load().snapshot.find(account_id)
    assert label.status is rotated.status is RegistryMutationStatus.SAVED
    assert record.identity.account_id == account_id
    assert record.identity.revision == 1
    assert record.record_revision == 3
    assert record.credential_reference == reference
    assert "test-bundle-1" not in repr(record)


def test_disable_enable_retire_and_no_revival(tmp_path):
    store, registry, account_id = registered(tmp_path)
    disabled = registry.disable(
        account_id,
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-disable",
    )
    enabled = registry.enable(
        account_id,
        expected_registry_revision=3,
        expected_record_revision=2,
        operation_id="op-enable",
    )
    retired = registry.retire(
        account_id,
        expected_registry_revision=4,
        expected_record_revision=3,
        operation_id="op-retire",
    )
    revival = registry.enable(
        account_id,
        expected_registry_revision=5,
        expected_record_revision=4,
        operation_id="op-revival",
    )
    record = store.load().snapshot.find(account_id)
    assert disabled.status is enabled.status is retired.status is RegistryMutationStatus.SAVED
    assert revival.status is RegistryMutationStatus.INVALID
    assert record.identity.lifecycle_state is AccountLifecycleState.RETIRED
    assert record.identity.revision == 4


def test_registry_and_record_cas_fail_closed(tmp_path):
    store, registry, account_id = registered(tmp_path)
    stale_registry = registry.update_label(
        account_id,
        "No",
        expected_registry_revision=1,
        expected_record_revision=1,
        operation_id="op-stale-registry",
    )
    stale_record = registry.update_label(
        account_id,
        "No",
        expected_registry_revision=2,
        expected_record_revision=9,
        operation_id="op-stale-record",
    )
    assert stale_registry.status is stale_record.status is RegistryMutationStatus.CONFLICT
    assert store.load().snapshot.find(account_id).display_label != "No"


def test_serialization_round_trip_digest_and_unknown_version(tmp_path):
    store, _, _ = registered(tmp_path)
    raw = store.snapshot_path.read_bytes()
    assert serialize_snapshot(deserialize_snapshot(raw)) == raw
    envelope = json.loads(raw)
    envelope["schema_version"] = "future-envelope/v2"
    store.snapshot_path.write_text(json.dumps(envelope))
    os.chmod(store.snapshot_path, 0o600)
    assert store.load().status is RegistryLoadStatus.INCOMPATIBLE_VERSION


def test_semantically_invalid_record_and_duplicate_id_are_rejected(tmp_path):
    store, _, _ = registered(tmp_path)
    envelope = json.loads(store.snapshot_path.read_bytes())
    envelope["payload"]["records"][0]["record_revision"] = 0
    payload = json.dumps(
        envelope["payload"], sort_keys=True, separators=(",", ":")
    ).encode()
    import hashlib

    envelope["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    store.snapshot_path.write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    )
    os.chmod(store.snapshot_path, 0o600)
    assert store.load().status is RegistryLoadStatus.INVALID

    duplicate_base = tmp_path / "duplicate"
    duplicate_base.mkdir()
    store, _, _ = registered(duplicate_base)
    envelope = json.loads(store.snapshot_path.read_bytes())
    envelope["payload"]["records"].append(envelope["payload"]["records"][0])
    payload = json.dumps(
        envelope["payload"], sort_keys=True, separators=(",", ":")
    ).encode()
    envelope["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    store.snapshot_path.write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    )
    os.chmod(store.snapshot_path, 0o600)
    assert store.load().status is RegistryLoadStatus.INVALID


@pytest.mark.parametrize("raw", [b"{", b'{"a":1,"a":2}', b"not-json"])
def test_corruption_is_not_repaired_or_overwritten(tmp_path, raw):
    store, _ = initialized(tmp_path)
    store.snapshot_path.write_bytes(raw)
    os.chmod(store.snapshot_path, 0o600)
    assert store.load().status is RegistryLoadStatus.CORRUPT
    assert store.snapshot_path.read_bytes() == raw


def test_unsafe_permissions_and_symlink_fail_closed(tmp_path):
    store, _ = initialized(tmp_path)
    os.chmod(store.snapshot_path, 0o644)
    assert store.load().status is RegistryLoadStatus.UNSAFE_FILE
    os.chmod(store.snapshot_path, 0o600)
    store.snapshot_path.unlink()
    store.snapshot_path.symlink_to(tmp_path / "missing")
    assert store.load().status is RegistryLoadStatus.UNSAFE_FILE


def test_pre_replace_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    store, registry, account_id = registered(tmp_path)
    before = store.snapshot_path.read_bytes()
    monkeypatch.setattr(store, "_replace", lambda *_: (_ for _ in ()).throw(OSError("injected")))
    result = registry.update_label(
        account_id,
        "No commit",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-no-commit",
    )
    assert result.status is RegistryMutationStatus.FAILED
    assert store.snapshot_path.read_bytes() == before
    assert not list(store.registry_directory.glob(".*.tmp"))


def test_post_replace_directory_fsync_failure_is_ambiguous_and_reloadable(tmp_path, monkeypatch):
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
    result = registry.update_label(
        account_id,
        "Maybe committed",
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-maybe-committed",
    )
    assert result.status is RegistryMutationStatus.COMMIT_STATE_UNKNOWN
    loaded = store.load()
    assert loaded.status is RegistryLoadStatus.VALID
    assert loaded.snapshot.registry_revision == 3
    assert loaded.snapshot.find(account_id).display_label == "Maybe committed"


def test_external_binding_must_match_scope_and_verification_evidence_is_complete():
    with pytest.raises(ValueError, match="evidence"):
        ExternalAccountBinding(
            ExecutionVenue.BYBIT_DEMO,
            ExternalBindingEnvironment.DEMO,
            ExternalBindingStatus.VERIFIED,
            "external-1",
        )
    binding = ExternalAccountBinding(
        ExecutionVenue.BYBIT_DEMO,
        ExternalBindingEnvironment.DEMO,
        ExternalBindingStatus.UNVERIFIED,
        "external-1",
    )
    assert "external-1" not in repr(binding)


def _initialize_worker(base: str, ready, start, results):
    registry = DurableAccountRegistry(AccountRegistryStore(Path(base)))
    ready.put(True)
    start.wait()
    results.put(registry.initialize().status.value)


def _update_worker(base: str, account_id: str, label: str, ready, start, results):
    registry = DurableAccountRegistry(AccountRegistryStore(Path(base)))
    ready.put(True)
    start.wait()
    result = registry.update_label(
        AccountId(account_id),
        label,
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id=f"op-{label}",
    )
    results.put(result.status.value)


def _run_two(ctx, target, args1, args2):
    ready, start, results = ctx.Queue(), ctx.Event(), ctx.Queue()
    one = ctx.Process(target=target, args=(*args1, ready, start, results))
    two = ctx.Process(target=target, args=(*args2, ready, start, results))
    one.start()
    two.start()
    ready.get(timeout=10)
    ready.get(timeout=10)
    start.set()
    values = [results.get(timeout=10), results.get(timeout=10)]
    one.join(10)
    two.join(10)
    assert one.exitcode == two.exitcode == 0
    return values


def test_process_concurrent_initialize_has_one_creator(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    values = _run_two(ctx, _initialize_worker, (str(tmp_path),), (str(tmp_path),))
    assert sorted(values) == ["ALREADY_INITIALIZED", "SAVED"]
    assert AccountRegistryStore(tmp_path).load().snapshot.registry_revision == 1


def test_process_concurrent_same_cas_has_one_winner(tmp_path):
    store, _, account_id = registered(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    values = _run_two(
        ctx,
        _update_worker,
        (str(tmp_path), account_id.value, "One"),
        (str(tmp_path), account_id.value, "Two"),
    )
    assert sorted(values) == ["CONFLICT", "SAVED"]
    assert store.load().snapshot.registry_revision == 3
