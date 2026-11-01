from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.accounts.models import AccountId, ExecutionMode, ExecutionVenue
from backend.accounts.registry_models import (
    CREDENTIAL_REFERENCE_SCHEMA_VERSION,
    CredentialBundleReference,
    CredentialReferenceSource,
)
from backend.execution.read_only_adapter_contracts import EndpointProfile
from backend.execution.read_only_credential_file_provider import (
    CREDENTIAL_FILE_SCHEMA_VERSION,
    ReadOnlyCredentialFileProvider,
)
from backend.execution.read_only_credentials import (
    CredentialProviderError,
    CredentialProviderErrorCode,
    CredentialScope,
)


ACCOUNT_ID = AccountId("acc_11111111111141118111111111111111")
OTHER_ACCOUNT_ID = AccountId("acc_22222222222242228222222222222222")
CREDENTIAL_ID = "fabricated-credential-one"
FABRICATED_KEY = "fabricated-key-not-real"
FABRICATED_SECRET = "fabricated-secret-not-real"

SCOPE = CredentialScope(
    account_id=ACCOUNT_ID,
    execution_mode=ExecutionMode.EXTERNAL_SIMULATION,
    execution_venue=ExecutionVenue.BYBIT_DEMO,
    endpoint_profile=EndpointProfile.BYBIT_DEMO_V5,
)


def _reference(
    credential_id: str = CREDENTIAL_ID,
    source: CredentialReferenceSource = CredentialReferenceSource.INJECTED_TEST,
) -> CredentialBundleReference:
    return CredentialBundleReference(
        CREDENTIAL_REFERENCE_SCHEMA_VERSION,
        source,
        credential_id,
        "HYRO_DEMO",
    )


def _document(
    *,
    account_id: AccountId = ACCOUNT_ID,
    generation: str = "gen-1",
    api_key: str = FABRICATED_KEY,
    api_secret: str = FABRICATED_SECRET,
    credential_id: str = CREDENTIAL_ID,
) -> dict:
    return {
        "schema_version": CREDENTIAL_FILE_SCHEMA_VERSION,
        "credentials": {
            credential_id: {
                "account_id": account_id.value,
                "execution_mode": ExecutionMode.EXTERNAL_SIMULATION.value,
                "execution_venue": ExecutionVenue.BYBIT_DEMO.value,
                "endpoint_profile": EndpointProfile.BYBIT_DEMO_V5.value,
                "generation": generation,
                "api_key": api_key,
                "api_secret": api_secret,
            }
        },
    }


def _write(path: Path, document: dict, *, mode: int = 0o600) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(path, mode)


def _write_atomic(path: Path, document: dict, *, mode: int = 0o600) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(temp, mode)
    os.replace(temp, path)


def _provider(path: Path, **kwargs) -> ReadOnlyCredentialFileProvider:
    return ReadOnlyCredentialFileProvider(str(path), **kwargs)


def test_constructor_does_not_read_file(tmp_path: Path):
    missing = tmp_path / "does-not-exist.json"
    provider = _provider(missing)
    assert provider.generation_schema_version == CREDENTIAL_FILE_SCHEMA_VERSION
    assert "does-not-exist" not in repr(provider)
    with pytest.raises(CredentialProviderError) as raised:
        provider.resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


def test_relative_path_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        ReadOnlyCredentialFileProvider("relative/secret.json")


def test_non_normalized_absolute_path_rejected(tmp_path: Path):
    path = f"{tmp_path}/child/../credential.json"
    with pytest.raises(ValueError):
        ReadOnlyCredentialFileProvider(path)


def test_valid_file_resolves_scope_and_generation(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write(path, _document(generation="gen-7"))
    credential = _provider(path).resolve(_reference(), SCOPE)
    assert credential.reference == _reference()
    assert credential.scope == SCOPE
    assert credential.credential_generation == "gen-7"
    key, secret = credential.signing_material()
    assert key == FABRICATED_KEY
    assert secret == FABRICATED_SECRET
    assert FABRICATED_SECRET not in repr(credential)


def test_owner_mismatch_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write(path, _document())
    provider = _provider(path, expected_owner_uid=os.geteuid() + 1)
    with pytest.raises(CredentialProviderError) as raised:
        provider.resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o660, 0o604])
def test_group_or_other_permissions_rejected(tmp_path: Path, mode: int):
    path = tmp_path / "credential.json"
    _write(path, _document(), mode=mode)
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


def test_symlink_rejected(tmp_path: Path):
    target = tmp_path / "real.json"
    _write(target, _document())
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(CredentialProviderError) as raised:
        _provider(link).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


def test_non_regular_file_rejected(tmp_path: Path):
    directory = tmp_path / "credential-dir"
    directory.mkdir()
    with pytest.raises(CredentialProviderError) as raised:
        _provider(directory).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


def test_oversized_file_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write(path, _document())
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path, max_bytes=10).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


def test_malformed_json_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    path.write_text("{not json", encoding="utf-8")
    os.chmod(path, 0o600)
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.INVALID_CREDENTIAL


def test_duplicate_keys_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    # Duplicate ``api_key`` inside one entry.
    text = (
        '{"schema_version":"'
        + CREDENTIAL_FILE_SCHEMA_VERSION
        + '","credentials":{"'
        + CREDENTIAL_ID
        + '":{"account_id":"'
        + ACCOUNT_ID.value
        + '","execution_mode":"EXTERNAL_SIMULATION","execution_venue":"BYBIT_DEMO"'
        + ',"endpoint_profile":"BYBIT_DEMO_V5","generation":"gen-1"'
        + ',"api_key":"first","api_key":"second"'
        + ',"api_secret":"' + FABRICATED_SECRET + '"}}}'
    )
    path.write_text(text, encoding="utf-8")
    os.chmod(path, 0o600)
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.INVALID_CREDENTIAL


def test_unknown_schema_version_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    document = _document()
    document["schema_version"] = "tradingai-read-only-credential-file/v999"
    _write(path, document)
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.INVALID_CREDENTIAL


def test_missing_schema_field_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write(path, {"schema_version": CREDENTIAL_FILE_SCHEMA_VERSION})
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.INVALID_CREDENTIAL


def test_unknown_reference_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write(path, _document())
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(_reference("other-credential"), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.REFERENCE_UNKNOWN


def test_environment_source_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write(path, _document())
    reference = _reference(source=CredentialReferenceSource.ENVIRONMENT_BUNDLE)
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(reference, SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.REFERENCE_UNKNOWN


def test_scope_mismatch_rejected(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write(path, _document(account_id=OTHER_ACCOUNT_ID))
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.SCOPE_MISMATCH


def test_allowed_root_policy(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    path = outside / "credential.json"
    _write(path, _document())
    with pytest.raises(CredentialProviderError) as raised:
        _provider(path, allowed_root=root).resolve(_reference(), SCOPE)
    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


def test_symlinked_parent_component_is_rejected(tmp_path: Path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    path = real_parent / "credential.json"
    _write(path, _document())
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(CredentialProviderError) as raised:
        _provider(linked_parent / "credential.json").resolve(_reference(), SCOPE)

    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


@pytest.mark.parametrize("mode", [0o770, 0o707])
def test_group_or_other_writable_parent_is_rejected(tmp_path: Path, mode: int):
    parent = tmp_path / "writable-parent"
    parent.mkdir()
    path = parent / "credential.json"
    _write(path, _document())
    os.chmod(parent, mode)

    with pytest.raises(CredentialProviderError) as raised:
        _provider(path).resolve(_reference(), SCOPE)

    assert raised.value.code is CredentialProviderErrorCode.UNAVAILABLE


def test_generation_rotation_is_reread(tmp_path: Path):
    path = tmp_path / "credential.json"
    _write(path, _document(generation="gen-1"))
    provider = _provider(path)
    first = provider.resolve(_reference(), SCOPE)
    assert first.credential_generation == "gen-1"
    _write_atomic(path, _document(generation="gen-2"))
    second = provider.resolve(_reference(), SCOPE)
    assert second.credential_generation == "gen-2"
    assert first.credential_generation != second.credential_generation


def test_same_generation_material_change_is_visible_but_not_versioned(tmp_path: Path):
    """Documents the operator contract: material rotation must change generation."""
    path = tmp_path / "credential.json"
    _write(path, _document(generation="gen-1", api_secret="fabricated-secret-one"))
    provider = _provider(path)
    first = provider.resolve(_reference(), SCOPE)

    _write_atomic(
        path,
        _document(generation="gen-1", api_secret="fabricated-secret-two"),
    )
    second = provider.resolve(_reference(), SCOPE)

    assert first.credential_generation == second.credential_generation == "gen-1"
    assert first.signing_material()[1] != second.signing_material()[1]


def test_secret_not_in_errors_or_repr(tmp_path: Path):
    path = tmp_path / "credential.json"
    document = _document()
    del document["credentials"][CREDENTIAL_ID]["generation"]
    document["credentials"][CREDENTIAL_ID]["api_secret"] = FABRICATED_SECRET
    _write(path, document)
    provider = _provider(path)
    with pytest.raises(CredentialProviderError) as raised:
        provider.resolve(_reference(), SCOPE)
    assert FABRICATED_SECRET not in str(raised.value)
    assert FABRICATED_SECRET not in repr(raised.value)
    assert FABRICATED_SECRET not in repr(provider)
    assert str(path) not in repr(provider)


def test_environment_variable_is_not_used_as_fallback(tmp_path: Path, monkeypatch):
    path = tmp_path / "credential.json"
    _write(path, _document())
    monkeypatch.setenv("BYBIT_API_KEY", FABRICATED_KEY)
    monkeypatch.setenv("TRADINGAI_CREDENTIAL_FILE", str(tmp_path / "other.json"))
    credential = _provider(path).resolve(_reference(), SCOPE)
    assert credential.api_key == FABRICATED_KEY
