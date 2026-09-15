"""Persistence tests for StrategyParameterStore (E-PARAM-1)."""

import dataclasses
import hashlib
import json
import os
from pathlib import Path

import pytest

from backend.strategy.parameters import (
    ENVELOPE_VERSION,
    INTEGRITY_ALGORITHM,
    LIVE_CLASS_CONSTANT_BASELINE,
    PAPER_MIGRATION_BASELINE,
    ParameterScope,
    StoreFailureCode,
    StoreLoadStatus,
    StoreSaveStatus,
    StrategyParameterStore,
    materialize_parameter_set,
    serialize_parameter_envelope,
)


def _paper():
    return materialize_parameter_set(PAPER_MIGRATION_BASELINE)


def _live():
    return materialize_parameter_set(LIVE_CLASS_CONSTANT_BASELINE)


def _digest(payload):
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def test_round_trip(tmp_path):
    store = StrategyParameterStore(tmp_path)
    parameter_set = _paper()
    assert store.save(parameter_set).status is StoreSaveStatus.SAVED
    loaded = store.load(ParameterScope.PAPER)
    assert loaded.status is StoreLoadStatus.VALID
    assert loaded.parameter_set.to_dict() == parameter_set.to_dict()


def test_file_permissions_and_no_temp_left(tmp_path):
    store = StrategyParameterStore(tmp_path)
    store.save(_paper())
    target = store.path_for(ParameterScope.PAPER)
    assert target.stat().st_mode & 0o777 == 0o600
    assert not (
        target.parent / ".strategy-params__PAPER.json.tmp"
    ).exists()


def test_missing_file(tmp_path):
    store = StrategyParameterStore(tmp_path)
    result = store.load(ParameterScope.PAPER)
    assert result.status is StoreLoadStatus.MISSING
    assert result.failure_code == "MISSING"


def test_corrupt_json(tmp_path):
    store = StrategyParameterStore(tmp_path)
    target = store.path_for(ParameterScope.PAPER)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"this is not json")
    os.chmod(target, 0o600)
    assert store.load(ParameterScope.PAPER).status is StoreLoadStatus.CORRUPT


def test_integrity_mismatch(tmp_path):
    store = StrategyParameterStore(tmp_path)
    store.save(_paper())
    target = store.path_for(ParameterScope.PAPER)
    envelope = json.loads(target.read_bytes())
    envelope["payload"]["parameters"]["minimumCompositeScore"] = 0.99
    target.write_bytes(json.dumps(envelope).encode("utf-8"))
    assert store.load(ParameterScope.PAPER).status is StoreLoadStatus.CORRUPT


def test_invalid_schema(tmp_path):
    store = StrategyParameterStore(tmp_path)
    store.save(_paper())
    target = store.path_for(ParameterScope.PAPER)
    envelope = json.loads(target.read_bytes())
    envelope["payload"]["parameters"]["minimumCompositeScore"] = 5.0
    envelope["integrityDigest"] = _digest(envelope["payload"])
    target.write_bytes(json.dumps(envelope).encode("utf-8"))
    result = store.load(ParameterScope.PAPER)
    assert result.status is StoreLoadStatus.INVALID
    assert result.failure_code == "INVALID_SCHEMA"


def test_unsupported_scope(tmp_path):
    store = StrategyParameterStore(tmp_path)
    assert store.load(ParameterScope.BOTH).status is StoreLoadStatus.INVALID
    both = dataclasses.replace(_paper(), scope=ParameterScope.BOTH)
    result = store.save(both)
    assert result.status is StoreSaveStatus.FAILED
    assert result.failure_code is StoreFailureCode.UNSUPPORTED_SCOPE


def test_symlink_rejected(tmp_path):
    store = StrategyParameterStore(tmp_path)
    target = store.path_for(ParameterScope.PAPER)
    target.parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("x")
    os.symlink(outside, target)
    assert store.load(ParameterScope.PAPER).status is StoreLoadStatus.INVALID
    result = store.save(_paper())
    assert result.status is StoreSaveStatus.FAILED
    assert result.failure_code is StoreFailureCode.UNSAFE_FILE


def test_non_regular_file_rejected(tmp_path):
    store = StrategyParameterStore(tmp_path)
    target = store.path_for(ParameterScope.PAPER)
    target.mkdir(parents=True)
    assert store.load(ParameterScope.PAPER).status is StoreLoadStatus.INVALID
    result = store.save(_paper())
    assert result.status is StoreSaveStatus.FAILED
    assert result.failure_code is StoreFailureCode.UNSAFE_FILE


def test_temporary_file_collision(tmp_path):
    store = StrategyParameterStore(tmp_path)
    target = store.path_for(ParameterScope.PAPER)
    target.parent.mkdir(parents=True)
    (target.parent / ".strategy-params__PAPER.json.tmp").write_text("x")
    result = store.save(_paper())
    assert result.status is StoreSaveStatus.FAILED
    assert result.failure_code is StoreFailureCode.TEMPORARY_FILE_EXISTS


def test_atomic_replacement(tmp_path):
    store = StrategyParameterStore(tmp_path)
    first = materialize_parameter_set(PAPER_MIGRATION_BASELINE)
    store.save(first)
    second = materialize_parameter_set(
        PAPER_MIGRATION_BASELINE,
        configured_revision=2,
        effective_revision=2,
    )
    assert store.save(second).status is StoreSaveStatus.SAVED
    loaded = store.load(ParameterScope.PAPER)
    assert loaded.parameter_set.configuredRevision == 2
    assert not (
        store.path_for(ParameterScope.PAPER).parent
        / ".strategy-params__PAPER.json.tmp"
    ).exists()


def test_revision_preservation(tmp_path):
    store = StrategyParameterStore(tmp_path)
    parameter_set = materialize_parameter_set(
        PAPER_MIGRATION_BASELINE,
        configured_revision=5,
        effective_revision=3,
    )
    store.save(parameter_set)
    loaded = store.load(ParameterScope.PAPER)
    assert loaded.parameter_set.configuredRevision == 5
    assert loaded.parameter_set.effectiveRevision == 3


def test_scope_isolation(tmp_path):
    store = StrategyParameterStore(tmp_path)
    store.save(_paper())
    assert store.load(ParameterScope.LIVE).status is StoreLoadStatus.MISSING

    store.save(_live())
    paper = store.load(ParameterScope.PAPER)
    live = store.load(ParameterScope.LIVE)
    assert paper.parameter_set.scope is ParameterScope.PAPER
    assert live.parameter_set.scope is ParameterScope.LIVE
    assert paper.parameter_set.parameter_value(
        "minimumCompositeScore"
    ) == 0.34
    assert live.parameter_set.parameter_value(
        "minimumCompositeScore"
    ) == 0.55


def test_duplicate_keys_rejected(tmp_path):
    store = StrategyParameterStore(tmp_path)
    target = store.path_for(ParameterScope.PAPER)
    target.parent.mkdir(parents=True)
    target.write_bytes(
        b'{"envelopeVersion":"a","envelopeVersion":"b"}'
    )
    os.chmod(target, 0o600)
    assert store.load(ParameterScope.PAPER).status is StoreLoadStatus.CORRUPT


def test_nan_and_infinity_rejected(tmp_path):
    store = StrategyParameterStore(tmp_path)
    target = store.path_for(ParameterScope.PAPER)
    target.parent.mkdir(parents=True)
    target.write_bytes(
        b'{"envelopeVersion":"strategy-parameter-envelope/v1",'
        b'"integrityAlgorithm":"SHA256","integrityDigest":"' + b"0" * 64 + b'",'
        b'"payload":{"value":NaN}}'
    )
    os.chmod(target, 0o600)
    assert store.load(ParameterScope.PAPER).status is StoreLoadStatus.CORRUPT


def test_envelope_shape(tmp_path):
    store = StrategyParameterStore(tmp_path)
    store.save(_paper())
    envelope = json.loads(
        store.path_for(ParameterScope.PAPER).read_bytes()
    )
    assert set(envelope) == {
        "envelopeVersion",
        "integrityAlgorithm",
        "integrityDigest",
        "payload",
    }
    assert envelope["envelopeVersion"] == ENVELOPE_VERSION
    assert envelope["integrityAlgorithm"] == INTEGRITY_ALGORITHM
    assert len(envelope["integrityDigest"]) == 64


def test_serialization_is_deterministic():
    parameter_set = _paper()
    first = serialize_parameter_envelope(parameter_set)
    second = serialize_parameter_envelope(parameter_set)
    assert first == second


def test_unsafe_relative_base(tmp_path):
    store = StrategyParameterStore(Path("relative"))
    result = store.save(_paper())
    assert result.status is StoreSaveStatus.FAILED
    assert result.failure_code is StoreFailureCode.UNSAFE_PATH
    assert store.load(ParameterScope.PAPER).status is StoreLoadStatus.INVALID


def test_missing_base_directory(tmp_path):
    store = StrategyParameterStore(tmp_path / "does-not-exist")
    result = store.save(_paper())
    assert result.status is StoreSaveStatus.FAILED
    assert result.failure_code is StoreFailureCode.UNSAFE_PATH


def test_invalid_set_rejected(tmp_path):
    store = StrategyParameterStore(tmp_path)
    result = store.save({"not": "a set"})
    assert result.status is StoreSaveStatus.FAILED
    assert result.failure_code is StoreFailureCode.INVALID_SET
