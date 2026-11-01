from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from backend.accounts import (
    ACCOUNT_IDENTITY_SCHEMA_VERSION,
    AccountId,
    AccountIdentity,
    AccountLifecycleState,
    AccountLookupResult,
    AccountRegistrationDraft,
    AccountRegistrationResult,
    RegistryLookupStatus,
    RegistryRegistrationStatus,
    AccountType,
    ExecutionMode,
    ExecutionVenue,
    PropPhase,
    PropProgram,
    ensure_account_match,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
ACCOUNT_ID = AccountId("acc_00000000000040008000000000000001")
OTHER_ID = AccountId("acc_00000000000040008000000000000002")


def identity(**changes):
    values = dict(
        schema_version=ACCOUNT_IDENTITY_SCHEMA_VERSION,
        account_id=ACCOUNT_ID,
        account_type=AccountType.PROP,
        execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
        execution_venue=ExecutionVenue.BYBIT_DEMO,
        lifecycle_state=AccountLifecycleState.REGISTERED,
        revision=1,
        created_at=NOW,
        updated_at=NOW,
        prop_program=PropProgram.HYROTRADER,
        prop_phase=PropPhase.CHALLENGE,
    )
    values.update(changes)
    return AccountIdentity(**values)


@pytest.mark.parametrize("value", ["", "acc_", "ACC_00000000000040008000000000000001", "api-key", None])
def test_account_id_rejects_missing_empty_and_invalid_values(value):
    with pytest.raises((TypeError, ValueError)):
        AccountId(value)


def test_account_id_requires_uuid_v4_and_new_generates_one():
    with pytest.raises(ValueError):
        AccountId("acc_00000000000010008000000000000001")
    assert AccountId.new().value.startswith("acc_")


def test_identity_is_immutable_and_phase_change_preserves_account_id():
    original = identity()
    with pytest.raises(FrozenInstanceError):
        original.revision = 2
    changed_phase = replace(original, prop_phase=PropPhase.VERIFICATION, revision=2)
    assert changed_phase.account_id == original.account_id


def test_account_mismatch_is_rejected_without_fallback():
    ensure_account_match(ACCOUNT_ID, ACCOUNT_ID)
    with pytest.raises(ValueError, match="mismatch"):
        ensure_account_match(ACCOUNT_ID, OTHER_ID)


def test_execution_modes_remain_distinct_and_venue_scoped():
    assert len({mode.value for mode in ExecutionMode}) == 3
    with pytest.raises(ValueError, match="incompatible"):
        identity(execution_mode=ExecutionMode.PAPER)
    with pytest.raises(ValueError, match="incompatible"):
        identity(execution_mode=ExecutionMode.LIVE, execution_venue=ExecutionVenue.BYBIT_DEMO)


def test_normal_and_prop_invariants_are_strict():
    with pytest.raises(ValueError, match="requires"):
        identity(prop_phase=None)
    with pytest.raises(ValueError, match="must not declare"):
        identity(
            account_type=AccountType.NORMAL,
            execution_mode=ExecutionMode.LIVE,
            execution_venue=ExecutionVenue.KUCOIN_FUTURES,
        )
    normal = identity(
        account_type=AccountType.NORMAL,
        execution_mode=ExecutionMode.PAPER,
        execution_venue=ExecutionVenue.INTERNAL_PAPER,
        prop_program=None,
        prop_phase=None,
    )
    assert normal.account_type is AccountType.NORMAL


def test_unknown_schema_enum_and_naive_time_are_rejected():
    with pytest.raises(ValueError, match="unsupported"):
        identity(schema_version="v2")
    with pytest.raises(ValueError, match="unknown account_type"):
        identity(account_type="MYSTERY")
    with pytest.raises(TypeError, match="timezone-aware"):
        identity(created_at=datetime(2026, 1, 1))


def test_public_serialization_round_trip_has_no_private_references():
    original = identity()
    document = original.to_dict()
    assert AccountIdentity.from_dict(document) == original
    assert "credential_ref" not in document
    assert "external_account_ref" not in document
    marker = "api_key_FAKE_SECRET_MARKER"
    with pytest.raises(ValueError, match="unknown") as exc_info:
        AccountIdentity.from_dict({**document, marker: "secret"})
    assert marker not in str(exc_info.value)


def test_f06_registry_draft_excludes_registry_owned_identity_fields_and_hides_refs():
    draft = AccountRegistrationDraft(
        "register-request-1",
        AccountType.PROP,
        ExecutionMode.EXTERNAL_SIMULATION,
        ExecutionVenue.BYBIT_DEMO,
        PropProgram.HYROTRADER,
        PropPhase.CHALLENGE,
        display_label="Test prop account",
    )
    rendered = repr(draft)
    assert "credential_reference" not in rendered
    for registry_owned in ("account_id", "revision", "created_at", "updated_at", "lifecycle_state"):
        assert not hasattr(draft, registry_owned)


def test_f06_registry_results_are_typed_and_fail_closed():
    found = AccountLookupResult(RegistryLookupStatus.FOUND, identity(), 2)
    registered = AccountRegistrationResult(
        RegistryRegistrationStatus.REGISTERED, identity(), 3
    )
    assert found.identity.account_id == ACCOUNT_ID
    assert registered.registry_revision == 3
    with pytest.raises(ValueError, match="identity"):
        AccountLookupResult(RegistryLookupStatus.NOT_FOUND, identity(), 2)
    with pytest.raises(ValueError, match="issued identity"):
        AccountRegistrationResult(RegistryRegistrationStatus.REGISTERED, None, 3)
