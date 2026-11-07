from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from knowledge_hub_release_acceptance import (
    ManifestError,
    compare_entries,
    derive_actual_diff,
    evaluate_release_acceptance,
    load_json,
    validate_approval_record,
    validate_diff_manifest,
    verify_expected_diff,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "knowledge_hub"
MANIFEST_PATH = FIXTURES / "cc4n_expected_diff_manifest.json"
APPROVAL_PATH = FIXTURES / "cc4n_owner_approvals.pending.json"
BASE_SHA = "70bd0e106704e62f9fa4089837651fe793d45427"
CANDIDATE_SHA = "1274e8df5ce9ed40392ddd4d505685c3343eff71"


@pytest.fixture(scope="module")
def manifest():
    return validate_diff_manifest(load_json(MANIFEST_PATH))


@pytest.fixture(scope="module")
def technical(manifest):
    return verify_expected_diff(
        REPO_ROOT,
        manifest,
        pinned_base_sha=BASE_SHA,
        pinned_candidate_sha=CANDIDATE_SHA,
    )


@pytest.fixture(scope="module")
def pending_approval(manifest):
    digest = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    return validate_approval_record(load_json(APPROVAL_PATH), manifest, digest)


def test_expected_diff_exactly_matches_fixed_candidate(manifest, technical):
    assert technical.matches, technical.errors
    assert technical.entry_count == 110
    assert technical.counts == {"A": 98, "M": 12}
    assert len(technical.shared_paths) == 12
    assert manifest["provenance"].endswith("not an approval record.")


def test_unapproved_added_path_is_rejected(manifest):
    actual = copy.deepcopy(manifest["entries"])
    extra = copy.deepcopy(next(item for item in actual if item["status"] == "A"))
    extra["path"] = "backend/unapproved_extra.py"
    errors = compare_entries(manifest["entries"], actual + [extra])
    assert errors == ("UNEXPECTED_PATH:backend/unapproved_extra.py",)


def test_expected_change_missing_is_rejected(manifest):
    missing_path = manifest["entries"][0]["path"]
    actual = [item for item in manifest["entries"] if item["path"] != missing_path]
    assert compare_entries(manifest["entries"], actual) == (
        f"MISSING_EXPECTED_PATH:{missing_path}",
    )


def test_same_path_content_change_is_rejected(manifest):
    actual = copy.deepcopy(manifest["entries"])
    actual[0]["afterSha256"] = "f" * 64
    errors = compare_entries(manifest["entries"], actual)
    assert errors == (f"CONTENT_MISMATCH:{actual[0]['path']}:afterSha256",)


def test_same_path_mode_change_is_rejected(manifest):
    actual = copy.deepcopy(manifest["entries"])
    actual[0]["afterMode"] = "100755"
    errors = compare_entries(manifest["entries"], actual)
    assert errors == (f"CONTENT_MISMATCH:{actual[0]['path']}:afterMode",)


@pytest.mark.parametrize(
    ("field", "replacement", "expected"),
    [
        ("baseSha", "1" * 40, "BASE_SHA_MISMATCH"),
        ("candidateSha", "2" * 40, "CANDIDATE_SHA_MISMATCH"),
    ],
)
def test_pinned_sha_mismatch_is_rejected(manifest, field, replacement, expected):
    changed = copy.deepcopy(manifest)
    changed[field] = replacement
    result = verify_expected_diff(
        REPO_ROOT,
        changed,
        pinned_base_sha=BASE_SHA,
        pinned_candidate_sha=CANDIDATE_SHA,
    )
    assert not result.matches
    assert result.errors == (expected,)


def test_manifest_unknown_field_is_rejected(manifest):
    changed = copy.deepcopy(manifest)
    changed["unexpected"] = True
    with pytest.raises(ManifestError, match="unknown"):
        validate_diff_manifest(changed)


def test_manifest_duplicate_path_is_rejected(manifest):
    changed = copy.deepcopy(manifest)
    changed["entries"].append(copy.deepcopy(changed["entries"][0]))
    changed["expectedEntryCount"] += 1
    changed["expectedCounts"][changed["entries"][0]["status"]] += 1
    with pytest.raises(ManifestError, match="duplicate path"):
        validate_diff_manifest(changed)


def test_manifest_invalid_json_is_rejected(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    with pytest.raises(ManifestError, match="cannot load"):
        load_json(invalid)


def test_manifest_invalid_mode_is_rejected(manifest):
    changed = copy.deepcopy(manifest)
    changed["entries"][0]["afterMode"] = "not-a-mode"
    with pytest.raises(ManifestError, match="invalid afterMode"):
        validate_diff_manifest(changed)


def test_missing_approval_record_is_not_ready(technical):
    result = evaluate_release_acceptance(technical, None, integration_passed=True)
    assert result.verdict == "NOT_READY"
    assert result.owner_response_status == "MISSING"
    assert "APPROVAL_RECORD_MISSING" in result.blockers


def test_partial_owner_approval_remains_pending(technical, pending_approval):
    record = copy.deepcopy(pending_approval)
    record["decisions"][0]["decision"] = "ACCEPT"
    result = evaluate_release_acceptance(technical, record, integration_passed=True)
    assert result.verdict == "NOT_READY"
    assert result.owner_response_status == "PENDING"
    assert len([item for item in result.blockers if item.startswith("OWNER_PENDING:")]) == 11


def test_owner_rejection_is_not_ready(technical, pending_approval):
    record = copy.deepcopy(pending_approval)
    record["decisions"][0]["decision"] = "REJECT"
    result = evaluate_release_acceptance(technical, record, integration_passed=True)
    assert result.verdict == "NOT_READY"
    assert result.owner_response_status == "REJECTED"
    assert any(item.startswith("OWNER_REJECTED:") for item in result.blockers)


def test_all_owner_accepts_do_not_replace_release_approval(technical, pending_approval):
    record = copy.deepcopy(pending_approval)
    for item in record["decisions"]:
        item["decision"] = "ACCEPT"
    result = evaluate_release_acceptance(technical, record, integration_passed=True)
    assert result.owner_response_status == "ALL_ACCEPTED"
    assert result.release_approval_status == "PENDING"
    assert result.verdict == "NOT_READY"
    assert "RELEASE_APPROVAL_PENDING" in result.blockers


def test_all_accept_synthetic_example_is_ready_only_in_test(technical, pending_approval):
    record = copy.deepcopy(pending_approval)
    record["recordKind"] = "SYNTHETIC_TEST_ONLY"
    record["releaseApprovalStatus"] = "APPROVED"
    for item in record["decisions"]:
        item["decision"] = "ACCEPT"
        item["evidence"] = "Synthetic test decision; not a real approval."
    result = evaluate_release_acceptance(technical, record, integration_passed=True)
    assert result.verdict == "READY_FOR_APPROVAL"
    assert result.blockers == ()
    assert load_json(APPROVAL_PATH)["releaseApprovalStatus"] == "PENDING"
    assert {item["decision"] for item in load_json(APPROVAL_PATH)["decisions"]} == {"PENDING"}


def test_approval_record_unknown_field_and_duplicate_path_are_rejected(manifest, pending_approval):
    digest = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    unknown = copy.deepcopy(pending_approval)
    unknown["unknown"] = True
    with pytest.raises(ManifestError, match="unknown"):
        validate_approval_record(unknown, manifest, digest)

    duplicate = copy.deepcopy(pending_approval)
    duplicate["decisions"].append(copy.deepcopy(duplicate["decisions"][0]))
    with pytest.raises(ManifestError, match="duplicate path"):
        validate_approval_record(duplicate, manifest, digest)


def test_approval_manifest_hash_mismatch_is_rejected(manifest, pending_approval):
    digest = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
    changed = copy.deepcopy(pending_approval)
    changed["diffManifestSha256"] = "0" * 64
    with pytest.raises(ManifestError, match="diff manifest hash mismatch"):
        validate_approval_record(changed, manifest, digest)


def test_git_comparison_never_uses_production_checkout(manifest):
    observed: list[tuple[Path, tuple[str, ...]]] = []

    def observe(repo: Path, args: tuple[str, ...]) -> None:
        observed.append((repo.resolve(), args))

    actual = derive_actual_diff(REPO_ROOT, BASE_SHA, CANDIDATE_SHA, observer=observe)
    assert not compare_entries(manifest["entries"], actual)
    assert observed
    assert {repo for repo, _ in observed} == {REPO_ROOT.resolve()}
    production = "/home/joe4410joe/tradingai_prod_v1"
    assert all(production not in args for _, args in observed)
    helper_source = (REPO_ROOT / "tests" / "knowledge_hub_release_acceptance.py").read_text()
    assert production not in helper_source


def test_fixture_is_pending_not_promoted_to_real_approval(pending_approval):
    assert pending_approval["recordKind"] == "REAL_OWNER_RESPONSES"
    assert pending_approval["releaseApprovalStatus"] == "PENDING"
    assert len(pending_approval["decisions"]) == 12
    assert {item["decision"] for item in pending_approval["decisions"]} == {"PENDING"}
