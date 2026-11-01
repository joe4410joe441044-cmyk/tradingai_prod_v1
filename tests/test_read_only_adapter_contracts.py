from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

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
from backend.accounts.registry_contract import AccountRegistrationDraft
from backend.accounts.registry_models import (
    CREDENTIAL_REFERENCE_SCHEMA_VERSION,
    CredentialBundleReference,
    CredentialReferenceSource,
    ExternalAccountBinding,
    ExternalBindingEnvironment,
    ExternalBindingStatus,
)
from backend.accounts.registry_store import AccountRegistryStore, DurableAccountRegistry
from backend.accounts.resolver import (
    AccountResolutionRequest,
    CredentialRequirement,
    resolve_account,
)
from backend.execution.adapter_contracts import CapabilityState
from backend.execution.read_only_adapter_contracts import (
    EndpointProfile,
    ReadBindingCurrentness,
    ReadCapabilities,
    ReadOnlyAdapterConfiguration,
    ReadPurpose,
    build_read_only_configuration,
    evaluate_read_binding,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _reference() -> CredentialBundleReference:
    return CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        "fabricated-bundle",
        "HYRO_DEMO",
    )


def _binding() -> ExternalAccountBinding:
    return ExternalAccountBinding(
        ExecutionVenue.BYBIT_DEMO,
        ExternalBindingEnvironment.DEMO,
        ExternalBindingStatus.VERIFIED,
        "fabricated-external",
        "fingerprint-1",
        NOW,
        "injected-test",
    )


def _capabilities() -> ReadCapabilities:
    return ReadCapabilities(
        account_read=CapabilityState.SUPPORTED,
        positions_read=CapabilityState.SUPPORTED,
        orders_read=CapabilityState.SUPPORTED,
        server_time=CapabilityState.SUPPORTED,
    )


def _draft(request_id: str, *, binding=None, reference=None) -> AccountRegistrationDraft:
    return AccountRegistrationDraft(
        request_id,
        AccountType.PROP,
        ExecutionMode.EXTERNAL_SIMULATION,
        ExecutionVenue.BYBIT_DEMO,
        PropProgram.HYROTRADER,
        PropPhase.CHALLENGE,
        display_label="Fabricated read account",
        credential_reference=reference,
        external_binding=binding,
    )


def _setup(tmp_path):
    ticks = iter(NOW + timedelta(seconds=i) for i in range(60))
    store = AccountRegistryStore(tmp_path)
    registry = DurableAccountRegistry(store, clock=lambda: next(ticks))
    assert registry.initialize().status.value == "SAVED"
    initial_snapshot = store.load().snapshot
    reference = _reference()
    binding = _binding()
    registered = registry.register(
        _draft("read-request", binding=binding, reference=reference),
        expected_registry_revision=1,
        operation_id="op-read-register",
    )
    account_id = registered.identity.account_id
    resolution = resolve_account(
        AccountResolutionRequest(
            account_id,
            expected_registry_revision=2,
            required_account_type=AccountType.PROP,
            required_execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
            required_execution_venue=ExecutionVenue.BYBIT_DEMO,
            credential_requirement=CredentialRequirement.REFERENCE_REQUIRED,
            require_verified_external_binding=True,
        ),
        store.load(),
    )
    return store, registry, account_id, reference, resolution, initial_snapshot


def _configuration(resolution) -> ReadOnlyAdapterConfiguration:
    return build_read_only_configuration(
        resolution,
        endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
        read_purpose=ReadPurpose.ACCOUNT_OBSERVATION,
        capabilities=_capabilities(),
    )


def test_binding_retains_identity_revisions_typed_reference_and_no_authority(tmp_path):
    store, _, account_id, reference, resolution, _ = _setup(tmp_path)
    configuration = _configuration(resolution)
    assert configuration.account_id == account_id
    assert configuration.account_type is AccountType.PROP
    assert configuration.execution_mode is ExecutionMode.EXTERNAL_SIMULATION
    assert configuration.execution_venue is ExecutionVenue.BYBIT_DEMO
    assert configuration.record_lifecycle is AccountLifecycleState.REGISTERED
    assert configuration.registry_revision == 2
    assert configuration.record_revision == 1
    assert configuration.credential_reference == reference
    assert configuration.external_binding_status is ExternalBindingStatus.VERIFIED
    assert configuration.external_binding_verified is True
    assert configuration.external_binding_fingerprint == "fingerprint-1"
    assert configuration.endpoint_profile is EndpointProfile.BYBIT_DEMO_V5
    assert configuration.read_purpose is ReadPurpose.ACCOUNT_OBSERVATION
    assert not hasattr(configuration, "runtime_authority")
    assert not hasattr(configuration, "order_authority")
    assert "fabricated-bundle" not in repr(configuration)
    assert "fabricated-external" not in repr(configuration)
    assert "fingerprint-1" not in repr(configuration)


def test_binding_rejects_scope_revision_lifecycle_and_credential_mismatches(tmp_path):
    _, _, account_id, reference, resolution, _ = _setup(tmp_path)
    with pytest.raises(ValueError):
        build_read_only_configuration(
            resolution,
            endpoint_profile=EndpointProfile.BLOFIN_DEMO_V1,
            read_purpose=ReadPurpose.ACCOUNT_OBSERVATION,
            capabilities=_capabilities(),
        )
    base = _configuration(resolution)
    common = dict(
        account_id=account_id,
        account_type=AccountType.PROP,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        record_lifecycle=AccountLifecycleState.REGISTERED,
        registry_revision=2,
        record_revision=1,
        credential_reference=reference,
        external_binding_status=ExternalBindingStatus.VERIFIED,
        external_binding_verified=True,
        external_binding_fingerprint="fingerprint-1",
        endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
        read_purpose=ReadPurpose.ACCOUNT_OBSERVATION,
        capabilities=_capabilities(),
    )
    with pytest.raises(ValueError):
        ReadOnlyAdapterConfiguration(**{**common, "record_lifecycle": AccountLifecycleState.DISABLED})
    with pytest.raises(ValueError):
        ReadOnlyAdapterConfiguration(**{**common, "registry_revision": True})
    with pytest.raises(ValueError):
        ReadOnlyAdapterConfiguration(**{**common, "record_revision": 0})
    with pytest.raises(ValueError):
        ReadOnlyAdapterConfiguration(**{**common, "credential_reference": None})
    with pytest.raises(ValueError):
        ReadOnlyAdapterConfiguration(
            **{
                **common,
                "external_binding_status": ExternalBindingStatus.UNVERIFIED,
            }
        )
    with pytest.raises(TypeError):
        ReadOnlyAdapterConfiguration(**{**common, "account_type": "PROP"})


def test_binding_serialization_round_trips_and_contains_no_secret_material(tmp_path):
    _, _, _, _, resolution, _ = _setup(tmp_path)
    configuration = _configuration(resolution)
    document = configuration.to_dict()
    restored = ReadOnlyAdapterConfiguration.from_dict(document)
    assert restored == configuration
    encoded = json.dumps(document)
    assert "secret" not in encoded.lower()
    assert "api_key" not in encoded.lower()
    assert "passphrase" not in encoded.lower()
    with pytest.raises(ValueError):
        ReadOnlyAdapterConfiguration.from_dict({**document, "registry_revision": True})
    with pytest.raises(ValueError):
        ReadOnlyAdapterConfiguration.from_dict({**document, "unknown": 1})
    with pytest.raises(ValueError):
        ReadOnlyAdapterConfiguration.from_dict(
            {**document, "endpoint_profile": "UNKNOWN_PROFILE"}
        )


def test_evaluate_binding_distinguishes_unrelated_and_target_updates(tmp_path):
    store, registry, account_id, _, resolution, initial_snapshot = _setup(tmp_path)
    configuration = _configuration(resolution)

    current = evaluate_read_binding(configuration, store.load().snapshot)
    assert current.currentness is ReadBindingCurrentness.CURRENT
    assert current.is_current is True

    second = registry.register(
        _draft("read-request-2"),
        expected_registry_revision=2,
        operation_id="op-read-second",
    )
    assert second.status.value == "REGISTERED"
    newer = evaluate_read_binding(configuration, store.load().snapshot)
    assert newer.currentness is ReadBindingCurrentness.CURRENT_WITH_NEWER_REGISTRY_REVISION
    assert newer.is_current is True
    assert newer.current_registry_revision == 3

    registry.update_label(
        account_id,
        "Renamed",
        expected_registry_revision=3,
        expected_record_revision=1,
        operation_id="op-read-label",
    )
    updated = evaluate_read_binding(configuration, store.load().snapshot)
    assert updated.currentness is ReadBindingCurrentness.RECORD_UPDATED
    assert updated.current_registry_revision == 4

    rotated_reference = CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        "fabricated-bundle-2",
        "HYRO_DEMO",
    )
    rotated = registry.rotate_credential_reference(
        account_id,
        rotated_reference,
        expected_registry_revision=4,
        expected_record_revision=2,
        operation_id="op-read-credential",
    )
    assert rotated.status.value == "SAVED"
    credential_changed = evaluate_read_binding(configuration, store.load().snapshot)
    assert credential_changed.currentness is ReadBindingCurrentness.CREDENTIAL_REFERENCE_CHANGED

    registry.disable(
        account_id,
        expected_registry_revision=5,
        expected_record_revision=3,
        operation_id="op-read-disable",
    )
    disabled = evaluate_read_binding(configuration, store.load().snapshot)
    assert disabled.currentness is ReadBindingCurrentness.ACCOUNT_DISABLED

    registry.retire(
        account_id,
        expected_registry_revision=6,
        expected_record_revision=4,
        operation_id="op-read-retire",
    )
    retired = evaluate_read_binding(configuration, store.load().snapshot)
    assert retired.currentness is ReadBindingCurrentness.ACCOUNT_RETIRED

    rolled_back = evaluate_read_binding(configuration, initial_snapshot)
    assert rolled_back.currentness is ReadBindingCurrentness.REGISTRY_ROLLED_BACK


def test_evaluate_binding_reports_missing_account(tmp_path):
    _, _, _, _, resolution, _ = _setup(tmp_path)
    configuration = _configuration(resolution)
    other_base = tmp_path / "other"
    other_base.mkdir()
    ticks = iter(NOW + timedelta(seconds=i) for i in range(10))
    other_store = AccountRegistryStore(other_base)
    other_registry = DurableAccountRegistry(other_store, clock=lambda: next(ticks))
    other_registry.initialize()
    other_registry.register(
        AccountRegistrationDraft(
            "other-request",
            AccountType.PROP,
            ExecutionMode.EXTERNAL_SIMULATION,
            ExecutionVenue.BYBIT_DEMO,
            PropProgram.HYROTRADER,
            PropPhase.CHALLENGE,
            display_label="Other account",
        ),
        expected_registry_revision=1,
        operation_id="op-other-register",
    )
    evaluation = evaluate_read_binding(configuration, other_store.load().snapshot)
    assert evaluation.currentness is ReadBindingCurrentness.ACCOUNT_NOT_FOUND


def test_build_requires_a_resolved_descriptor(tmp_path):
    _, _, _, _, resolution, _ = _setup(tmp_path)
    from backend.accounts.resolver import (
        AccountResolutionError,
        AccountResolutionResult,
        AccountResolutionStatus,
    )

    rejected = AccountResolutionResult(
        AccountResolutionStatus.REJECTED,
        resolution.registry_revision,
        error=AccountResolutionError.NOT_FOUND,
    )
    with pytest.raises(ValueError):
        build_read_only_configuration(
            rejected,
            endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
            read_purpose=ReadPurpose.ACCOUNT_OBSERVATION,
            capabilities=_capabilities(),
        )
