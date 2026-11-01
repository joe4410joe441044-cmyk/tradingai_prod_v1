from datetime import datetime, timedelta, timezone

import pytest

from backend.accounts.models import (
    AccountId,
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
from backend.accounts.registry_store import (
    AccountRegistryStore,
    DurableAccountRegistry,
    RegistryLoadResult,
    RegistryLoadStatus,
)
from backend.accounts.resolver import (
    AccountResolutionError,
    AccountResolutionRequest,
    AccountResolutionResult,
    AccountResolutionStatus,
    CredentialRequirement,
    ResolvedAccountDescriptor,
    resolve_account,
)


def setup_registry(tmp_path, *, credential=False, binding=None):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ticks = iter(base + timedelta(seconds=i) for i in range(20))
    store = AccountRegistryStore(tmp_path)
    registry = DurableAccountRegistry(store, clock=lambda: next(ticks))
    registry.initialize()
    reference = (
        CredentialBundleReference(
            CREDENTIAL_REFERENCE_SCHEMA_VERSION,
            CredentialReferenceSource.INJECTED_TEST,
            "fabricated-bundle",
            "HYRO_DEMO",
        )
        if credential
        else None
    )
    result = registry.register(
        AccountRegistrationDraft(
            "resolver-request",
            AccountType.PROP,
            ExecutionMode.EXTERNAL_SIMULATION,
            ExecutionVenue.BYBIT_DEMO,
            PropProgram.HYROTRADER,
            PropPhase.CHALLENGE,
            display_label="Resolver test",
            credential_reference=reference,
            external_binding=binding,
        ),
        expected_registry_revision=1,
        operation_id="op-resolver-register",
    )
    return store, registry, result.identity.account_id


def test_requires_explicit_account_id_before_registry_access():
    result = resolve_account(
        AccountResolutionRequest(None),
        RegistryLoadResult(RegistryLoadStatus.CORRUPT),
    )
    assert result.error is AccountResolutionError.ACCOUNT_ID_REQUIRED


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (RegistryLoadStatus.CORRUPT, AccountResolutionError.REGISTRY_INVALID),
        (RegistryLoadStatus.MISSING, AccountResolutionError.REGISTRY_INVALID),
        (
            RegistryLoadStatus.INCOMPATIBLE_VERSION,
            AccountResolutionError.VERSION_UNSUPPORTED,
        ),
    ],
)
def test_registry_failures_are_typed_and_safe(status, error):
    result = resolve_account(
        AccountResolutionRequest(AccountId.new()), RegistryLoadResult(status)
    )
    assert result.error is error
    assert "fabricated" not in result.safe_message


def test_not_found_revision_and_scope_mismatch_have_no_fallback(tmp_path):
    store, _, account_id = setup_registry(tmp_path)
    missing = resolve_account(
        AccountResolutionRequest(AccountId.new()), store.load()
    )
    stale = resolve_account(
        AccountResolutionRequest(account_id, expected_registry_revision=1), store.load()
    )
    scope = resolve_account(
        AccountResolutionRequest(
            account_id, required_execution_venue=ExecutionVenue.BLOFIN_DEMO
        ),
        store.load(),
    )
    assert missing.error is AccountResolutionError.NOT_FOUND
    assert stale.error is AccountResolutionError.REVISION_MISMATCH
    assert scope.error is AccountResolutionError.SCOPE_MISMATCH


def test_credential_and_verified_binding_requirements(tmp_path):
    unverified = ExternalAccountBinding(
        ExecutionVenue.BYBIT_DEMO,
        ExternalBindingEnvironment.DEMO,
        ExternalBindingStatus.UNVERIFIED,
        "fabricated-external",
    )
    store, _, account_id = setup_registry(tmp_path, binding=unverified)
    credential = resolve_account(
        AccountResolutionRequest(
            account_id,
            credential_requirement=CredentialRequirement.REFERENCE_REQUIRED,
        ),
        store.load(),
    )
    binding = resolve_account(
        AccountResolutionRequest(
            account_id, require_verified_external_binding=True
        ),
        store.load(),
    )
    assert credential.error is AccountResolutionError.CREDENTIAL_REFERENCE_MISSING
    assert binding.error is AccountResolutionError.EXTERNAL_BINDING_UNVERIFIED


def test_success_returns_descriptor_without_authority_claim(tmp_path):
    verified = ExternalAccountBinding(
        ExecutionVenue.BYBIT_DEMO,
        ExternalBindingEnvironment.DEMO,
        ExternalBindingStatus.VERIFIED,
        "fabricated-external",
        "fingerprint-1",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        "injected-test",
    )
    store, _, account_id = setup_registry(
        tmp_path, credential=True, binding=verified
    )
    result = resolve_account(
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
    assert result.status is AccountResolutionStatus.RESOLVED
    assert result.descriptor.identity.account_id == account_id
    assert not hasattr(result.descriptor, "runtime_authority")
    assert "fabricated-bundle" not in repr(result.descriptor)
    assert "fabricated-external" not in repr(result.descriptor)


def test_disabled_and_retired_are_rejected(tmp_path):
    store, registry, account_id = setup_registry(tmp_path)
    registry.disable(
        account_id,
        expected_registry_revision=2,
        expected_record_revision=1,
        operation_id="op-resolver-disable",
    )
    disabled = resolve_account(AccountResolutionRequest(account_id), store.load())
    registry.retire(
        account_id,
        expected_registry_revision=3,
        expected_record_revision=2,
        operation_id="op-resolver-retire",
    )
    retired = resolve_account(AccountResolutionRequest(account_id), store.load())
    assert disabled.error is AccountResolutionError.DISABLED
    assert retired.error is AccountResolutionError.RETIRED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("required_account_type", "PROP"),
        ("required_execution_mode", "EXTERNAL_SIMULATION"),
        ("required_execution_venue", "BYBIT_DEMO"),
        ("credential_requirement", "REFERENCE_REQUIRED"),
        ("credential_requirement", 1),
        ("expected_registry_revision", True),
        ("expected_registry_revision", 0),
        ("expected_registry_revision", "2"),
        ("require_verified_external_binding", 1),
    ],
)
def test_untyped_typed_fields_cannot_bypass_the_request_contract(field, value):
    with pytest.raises((TypeError, ValueError)):
        AccountResolutionRequest(AccountId.new(), **{field: value})


def test_untyped_account_id_is_rejected():
    with pytest.raises(TypeError):
        AccountResolutionRequest("acc_00000000000040008000000000000001")


def test_explicit_from_dict_parses_allowed_text_and_rejects_unknown_values():
    account_id = AccountId.new()
    request = AccountResolutionRequest.from_dict(
        {
            "account_id": account_id.value,
            "expected_registry_revision": 3,
            "required_account_type": "PROP",
            "required_execution_mode": "EXTERNAL_SIMULATION",
            "required_execution_venue": "BYBIT_DEMO",
            "credential_requirement": "REFERENCE_REQUIRED",
            "require_verified_external_binding": True,
        }
    )
    assert request.account_id == account_id
    assert request.credential_requirement is CredentialRequirement.REFERENCE_REQUIRED
    with pytest.raises(ValueError):
        AccountResolutionRequest.from_dict(
            {"account_id": account_id.value, "credential_requirement": "UNKNOWN"}
        )
    with pytest.raises(TypeError):
        AccountResolutionRequest.from_dict(
            {"account_id": account_id.value, "expected_registry_revision": True}
        )
    with pytest.raises(TypeError):
        AccountResolutionRequest.from_dict(
            {"account_id": account_id.value, "require_verified_external_binding": "true"}
        )
    with pytest.raises(ValueError):
        AccountResolutionRequest.from_dict(
            {"account_id": account_id.value, "unknown_field": 1}
        )
    with pytest.raises(ValueError):
        AccountResolutionRequest.from_dict({"account_id": "not-an-account"})


def test_text_credential_requirement_is_parsed_not_treated_as_requirement_free(tmp_path):
    store, _, account_id = setup_registry(tmp_path)
    request = AccountResolutionRequest.from_dict(
        {
            "account_id": account_id.value,
            "credential_requirement": "REFERENCE_REQUIRED",
        }
    )
    result = resolve_account(request, store.load())
    assert result.error is AccountResolutionError.CREDENTIAL_REFERENCE_MISSING


def test_resolution_result_invariants_reject_mixed_success_and_failure(tmp_path):
    store, _, account_id = setup_registry(tmp_path, credential=True)
    success = resolve_account(AccountResolutionRequest(account_id), store.load())
    with pytest.raises(ValueError):
        AccountResolutionResult(AccountResolutionStatus.RESOLVED, success.registry_revision)
    with pytest.raises(ValueError):
        AccountResolutionResult(
            AccountResolutionStatus.REJECTED,
            success.registry_revision,
            descriptor=success.descriptor,
            error=AccountResolutionError.NOT_FOUND,
        )
    other = CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        "other-bundle",
        "HYRO_DEMO",
    )
    with pytest.raises(ValueError):
        ResolvedAccountDescriptor(
            success.descriptor.record, other, success.descriptor.external_binding
        )
