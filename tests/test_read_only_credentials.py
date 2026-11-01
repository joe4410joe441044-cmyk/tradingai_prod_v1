from __future__ import annotations

import copy
import pickle

import pytest

from backend.accounts.models import AccountId, ExecutionMode, ExecutionVenue
from backend.accounts.registry_models import (
    CREDENTIAL_REFERENCE_SCHEMA_VERSION,
    CredentialBundleReference,
    CredentialReferenceSource,
)
from backend.execution.read_only_adapter_contracts import EndpointProfile
from backend.execution.read_only_credentials import (
    CredentialProviderError,
    CredentialProviderErrorCode,
    CredentialScope,
    ReadOnlyCredential,
    ReadOnlyCredentialProvider,
)

ACCOUNT_ID = AccountId("acc_11111111111141118111111111111111")


def _reference(credential_id: str = "fabricated-bundle") -> CredentialBundleReference:
    return CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        CredentialReferenceSource.INJECTED_TEST,
        credential_id,
        "HYRO_DEMO",
    )


def _scope(
    *,
    mode: ExecutionMode = ExecutionMode.EXTERNAL_SIMULATION,
    venue: ExecutionVenue = ExecutionVenue.BYBIT_DEMO,
    profile: EndpointProfile = EndpointProfile.BYBIT_DEMO_V5,
) -> CredentialScope:
    return CredentialScope(ACCOUNT_ID, mode, venue, profile)


class FakeProvider:
    def __init__(self, *, reference=None, credential=None, error=None) -> None:
        self.reference = reference
        self.credential = credential
        self.error = error
        self.calls = []

    def resolve(self, reference, scope):
        self.calls.append((reference, scope))
        if self.error is not None:
            raise self.error
        if self.reference is not None and reference != self.reference:
            raise CredentialProviderError(CredentialProviderErrorCode.REFERENCE_UNKNOWN)
        if self.credential is not None:
            return self.credential
        return ReadOnlyCredential(
            reference,
            "fabricated-key-not-real",
            "fabricated-secret-not-real",
            scope=scope,
        )


def _credential(reference=None, *, scope=None) -> ReadOnlyCredential:
    return ReadOnlyCredential(
        reference or _reference(),
        "fabricated-key-not-real",
        "fabricated-secret-not-real",
        scope=scope,
    )


def test_protocol_is_structural_and_has_no_default_provider():
    assert getattr(ReadOnlyCredentialProvider, "_is_protocol", False) is True
    provider = FakeProvider()
    assert isinstance(provider, ReadOnlyCredentialProvider)
    assert provider.calls == []


def test_credential_repr_str_and_serialization_are_redacted():
    credential = _credential()
    rendered = repr(credential)
    text = str(credential)
    assert "fabricated-key-not-real" not in rendered
    assert "fabricated-secret-not-real" not in rendered
    assert "fabricated-key-not-real" not in text
    assert "fabricated-secret-not-real" not in text
    assert "ReadOnlyCredential(<redacted>)" in rendered
    assert not hasattr(credential, "to_dict")
    with pytest.raises(TypeError):
        pickle.dumps(credential)
    with pytest.raises(TypeError):
        copy.copy(credential)
    with pytest.raises(TypeError):
        copy.deepcopy(credential)


def test_signing_material_is_available_only_on_explicit_call():
    credential = _credential()
    assert credential.signing_material() == (
        "fabricated-key-not-real",
        "fabricated-secret-not-real",
    )


def test_scope_rejects_non_demo_scope_and_wrong_profile():
    with pytest.raises(ValueError):
        _scope(mode=ExecutionMode.PAPER, venue=ExecutionVenue.INTERNAL_PAPER)
    with pytest.raises(ValueError):
        _scope(venue=ExecutionVenue.KUCOIN_FUTURES)
    with pytest.raises(ValueError):
        _scope(profile=EndpointProfile.BLOFIN_DEMO_V1)
    with pytest.raises(TypeError):
        CredentialScope(ACCOUNT_ID, "EXTERNAL_SIMULATION", ExecutionVenue.BYBIT_DEMO, EndpointProfile.BYBIT_DEMO_V5)


def test_provider_rejects_unknown_reference_without_fallback():
    provider = FakeProvider(reference=_reference("other-bundle"))
    with pytest.raises(CredentialProviderError) as caught:
        provider.resolve(_reference(), _scope())
    assert caught.value.code is CredentialProviderErrorCode.REFERENCE_UNKNOWN
    assert "other-bundle" not in str(caught.value)


def test_provider_error_text_is_fixed():
    error = CredentialProviderError(CredentialProviderErrorCode.UNAVAILABLE)
    assert error.code is CredentialProviderErrorCode.UNAVAILABLE
    assert error.safe_message == "credential is unavailable"
    assert str(error) == "credential is unavailable"
    with pytest.raises(ValueError):
        CredentialProviderError("free form provider text")


def test_credential_rejects_empty_or_control_character_material():
    with pytest.raises(ValueError):
        ReadOnlyCredential(_reference(), "", "fabricated-secret-not-real")
    with pytest.raises(ValueError):
        ReadOnlyCredential(_reference(), "fabricated-key-not-real", "")
    with pytest.raises(ValueError):
        ReadOnlyCredential(_reference(), "fabricated key", "fabricated-secret-not-real")
    with pytest.raises(ValueError):
        ReadOnlyCredential(_reference(), "fabricated\x00key", "fabricated-secret-not-real")
    with pytest.raises(TypeError):
        ReadOnlyCredential("not-a-reference", "fabricated-key-not-real", "fabricated-secret-not-real")
