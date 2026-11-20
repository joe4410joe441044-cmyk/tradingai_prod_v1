"""BC-11E-7A secret review readiness tests.

All fixtures are synthetic and in-memory. No test reads a real report body,
runs the detector against a real source file, performs an import, or writes to
production. The path/streaming safety gate is exercised only against temporary
synthetic files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.bc11e_secret_review as sec  # noqa: E402

HASH_A = "a" * 64
HASH_B = "b" * 64
GENERATED_AT = "2026-11-09T00:00:00+00:00"
MTIME = "2026-11-08T00:00:00+00:00"
ROOT_PATH = "/synthetic/reports"

SECRET_API_KEY = "sk-A1b2C3d4E5f6G7h8I9j0K1l2"
SECRET_GITHUB = "ghp_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SECRET_PASSWORD = "S3cr3t-P@ssw0rd!"
SECRET_COOKIE = "sessionid=abc123def456ghi789"
SECRET_DB = "postgres://app:SuperSecretValue@db.example.com:5432/appdb"
SECRET_EXCHANGE = "abc123def456ghi789jkl012"


def _hash_entry(
    source_id: str,
    content_hash: str,
    *,
    root: str = ROOT_PATH,
    size: int = 120,
    mtime: str = MTIME,
) -> dict:
    return {
        "source_id": source_id,
        "absolute_path": f"{root}/{source_id}.md",
        "source_root": root,
        "sha256": content_hash,
        "verification_status": "CONTENT_IDENTICAL",
        "size_bytes": size,
        "mtime": mtime,
        "body_stored": False,
        "provenance_status": "UNKNOWN",
    }


def _content_record(
    content_hash: str,
    representative: str,
    members: list[str],
    *,
    priority: str = "P2",
    root: str = ROOT_PATH,
) -> dict:
    paths = [f"{root}/{member}.md" for member in members]
    return {
        "content_hash": content_hash,
        "content_hash_algorithm": "SHA-256",
        "representative_source_id": representative,
        "member_source_ids": list(members),
        "source_paths": paths,
        "source_roots": [root],
        "member_count": len(members),
        "member_provenance": [
            {
                "source_id": member,
                "classification": "UNKNOWN_CANDIDATE",
                "source_classification": "UNKNOWN_REPORT_CANDIDATE",
                "provenance_status": "UNKNOWN",
                "review_priority": priority,
                "confirmed_cursor": False,
                "confirmed_other_agent": False,
                "confirmed_chatgpt": False,
            }
            for member in members
        ],
        "classification_counts": {"UNKNOWN_CANDIDATE": len(members)},
        "classifications": ["UNKNOWN_CANDIDATE"],
        "source_classifications": {
            member: "UNKNOWN_REPORT_CANDIDATE" for member in members
        },
        "review_priority": priority,
        "review_required": True,
        "review_status": "NOT_STARTED",
        "secret_review_status": "NOT_PERFORMED",
        "provenance_status": "UNKNOWN",
        "confirmed_cursor": False,
        "confirmed_other_agent": False,
        "confirmed_chatgpt": False,
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "source_truth_class": "AGENT_REPORTED",
        "authority_scope": "NONE",
        "historical_record": True,
        "historical_runtime_authority": False,
    }


def _provenance_entry(record: dict) -> dict:
    return {
        "content_hash": record["content_hash"],
        "representative_source_id": record["representative_source_id"],
        "member_source_ids": list(record["member_source_ids"]),
        "classifications": list(record["classifications"]),
        "classification_counts": dict(record["classification_counts"]),
        "source_classifications": dict(record["source_classifications"]),
        "member_provenance": list(record["member_provenance"]),
        "provenance_status": "UNKNOWN",
        "confirmed_cursor": False,
        "confirmed_other_agent": False,
        "confirmed_chatgpt": False,
        "review_priority": record["review_priority"],
        "review_required": True,
        "review_status": "NOT_STARTED",
        "source_truth_class": "AGENT_REPORTED",
        "authority_scope": "NONE",
        "historical_record": True,
        "historical_runtime_authority": False,
    }


def _manifest_entry(record: dict) -> dict:
    return {
        "content_hash": record["content_hash"],
        "representative_source_id": record["representative_source_id"],
        "member_source_ids": list(record["member_source_ids"]),
        "approved": False,
        "import_ready": False,
        "real_import_allowed": False,
        "secret_review_status": "NOT_PERFORMED",
        "review_priority": record["review_priority"],
        "review_status": "NOT_STARTED",
        "source_truth_class": "AGENT_REPORTED",
        "authority_scope": "NONE",
        "historical_record": True,
        "historical_runtime_authority": False,
    }


def _fixtures() -> dict:
    records = [
        _content_record(HASH_A, "a1", ["a1", "a2", "a3"], priority="P0"),
        _content_record(HASH_B, "b1", ["b1"], priority="P2"),
    ]
    hash_entries = [
        _hash_entry("a1", HASH_A),
        _hash_entry("a2", HASH_A),
        _hash_entry("a3", HASH_A),
        _hash_entry("b1", HASH_B),
    ]
    return {
        "content_review": {
            "approved": False,
            "records": records,
            "counts": {
                "CONTENT_UNIQUE_COUNT": 2,
                "SOURCE_REFERENCE_COUNT": 4,
                "DISTINCT_CONTENT_HASHES": 2,
                "TOTAL_SOURCE_ENTRIES": 4,
            },
        },
        "provenance_review": {
            "entries": [_provenance_entry(record) for record in records],
        },
        "import_manifest": {
            "approved": False,
            "entries": [_manifest_entry(record) for record in records],
        },
        "hash_results": {"entries": hash_entries},
        "import_target_final": {
            "path": "/synthetic/BC11E6_IMPORT_TARGET_FINAL.md",
            "exists": True,
            "size_bytes": 10,
        },
    }


def _expected() -> dict:
    return {
        "CONTENT_UNIQUE_COUNT": 2,
        "SOURCE_REFERENCE_COUNT": 4,
        "DISTINCT_CONTENT_HASHES": 2,
        "SOURCE_ENTRY_COUNT": 4,
        "SINGLETON_CONTENT_COUNT": 1,
        "CONFIRMED_DUPLICATE_GROUPS": 1,
        "ADDITIONAL_COPY_COUNT": 2,
        "PROVENANCE_REVIEW_COUNT": 2,
        "IMPORT_MANIFEST_COUNT": 2,
        "MEMBER_SOURCE_REFERENCE_COUNT": 4,
        "UNIQUE_MEMBER_SOURCE_IDS": 4,
        "ALL_SECRET_REVIEW_NOT_PERFORMED": True,
        "ALL_PROVENANCE_UNKNOWN": True,
        "ALL_APPROVED_FALSE": True,
        "ALL_IMPORT_READY_FALSE": True,
        "ALL_REAL_IMPORT_ALLOWED_FALSE": True,
        "ALL_MEMBER_SOURCE_IDS_RESOLVE": True,
        "REPRESENTATIVE_IN_MEMBERS": True,
        "CONTENT_HASHES_UNIQUE": True,
        "MEMBER_SOURCE_IDS_UNIQUE": True,
    }


def _build(fixtures: dict | None = None, expected: dict | None = None) -> dict:
    return sec.build_stage_a(
        fixtures or _fixtures(),
        expected=expected or _expected(),
        generated_at=GENERATED_AT,
    )


def _large_fixtures() -> dict:
    group_sizes = [1] * 30
    for index in range(6155):
        group_sizes[index % 30] += 1

    hash_entries: list[dict] = []
    records: list[dict] = []
    priorities = ("P0", "P1", "P2", "P3")

    for group_index, size in enumerate(group_sizes):
        content_hash = hashlib.sha256(f"group-{group_index}".encode()).hexdigest()
        members = [f"src_{group_index}_{member}" for member in range(size)]
        for member in members:
            hash_entries.append(_hash_entry(member, content_hash))
        records.append(
            _content_record(
                content_hash,
                members[0],
                members,
                priority=priorities[group_index % len(priorities)],
            )
        )

    for singleton_index in range(461):
        content_hash = hashlib.sha256(
            f"singleton-{singleton_index}".encode()
        ).hexdigest()
        source_id = f"src_s_{singleton_index}"
        hash_entries.append(_hash_entry(source_id, content_hash))
        records.append(
            _content_record(
                content_hash,
                source_id,
                [source_id],
                priority=priorities[singleton_index % len(priorities)],
            )
        )

    assert len(records) == 491
    assert len(hash_entries) == 6646

    return {
        "content_review": {
            "approved": False,
            "records": records,
            "counts": {
                "CONTENT_UNIQUE_COUNT": 491,
                "SOURCE_REFERENCE_COUNT": 6646,
                "DISTINCT_CONTENT_HASHES": 491,
                "TOTAL_SOURCE_ENTRIES": 6646,
            },
        },
        "provenance_review": {
            "entries": [_provenance_entry(record) for record in records],
        },
        "import_manifest": {
            "approved": False,
            "entries": [_manifest_entry(record) for record in records],
        },
        "hash_results": {"entries": hash_entries},
        "import_target_final": {
            "path": "/synthetic/BC11E6_IMPORT_TARGET_FINAL.md",
            "exists": True,
            "size_bytes": 10,
        },
    }


def _root_guard(name: str) -> bool:
    return sec.secret_filename(name)


def test_input_validation(tmp_path: Path) -> None:
    with pytest.raises(sec.InputError) as exc_info:
        sec.load_input(tmp_path / "missing.json")
    assert exc_info.value.code == sec.BLOCKED_MISSING_INPUT

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    with pytest.raises(sec.InputError) as exc_info:
        sec.load_input(invalid)
    assert exc_info.value.code == sec.BLOCKED_INVALID_INPUT

    fixtures = _fixtures()
    fixtures["import_manifest"]["entries"] = "not a list"
    with pytest.raises(sec.InputError):
        sec.validate_inputs(fixtures, expected=_expected())

    fixtures = _fixtures()
    del fixtures["content_review"]["records"][0]["content_hash"]
    with pytest.raises(sec.InputError):
        sec.validate_inputs(fixtures, expected=_expected())

    fixtures = _fixtures()
    del fixtures["hash_results"]["entries"][0]["source_id"]
    with pytest.raises(sec.InputError):
        sec.validate_inputs(fixtures, expected=_expected())

    result = sec.validate_inputs(_fixtures(), expected=_expected())
    assert result["status"] == sec.INPUTS_VALID
    assert result["inputs_valid"] is True

    bad = _expected()
    bad["CONTENT_UNIQUE_COUNT"] = 3
    result = sec.validate_inputs(_fixtures(), expected=bad)
    assert result["status"] == sec.INPUT_COUNT_MISMATCH
    assert any(item["key"] == "CONTENT_UNIQUE_COUNT" for item in result["mismatches"])


def test_content_unique_and_source_reference_counts() -> None:
    result = _build()
    plan = result["scan_plan"]
    assert plan["counts"]["CONTENT_UNIQUE_COUNT"] == 2
    assert plan["counts"]["SOURCE_REFERENCE_COUNT"] == 4
    assert plan["counts"]["SCAN_TARGET_COUNT"] == 2
    assert plan["counts"]["ADDITIONAL_COPY_COUNT"] == 2
    assert len(plan["candidates"]) == 2
    assert len(plan["source_references"]) == 4
    assert sum(1 for ref in plan["source_references"] if ref["inspection_target"]) == 2
    assert [candidate["content_hash"] for candidate in plan["candidates"]] == sorted(
        [HASH_A, HASH_B]
    )


def test_baseline_constants() -> None:
    assert sec.EXPECTED_BASELINE["CONTENT_UNIQUE_COUNT"] == 491
    assert sec.EXPECTED_BASELINE["SOURCE_REFERENCE_COUNT"] == 6646
    assert sec.EXPECTED_BASELINE["ADDITIONAL_COPY_COUNT"] == 6155


def test_491_content_unique_records_and_6646_source_references() -> None:
    fixtures = _large_fixtures()
    result = sec.build_stage_a(
        fixtures,
        expected=sec.EXPECTED_BASELINE,
        generated_at=GENERATED_AT,
    )
    plan = result["scan_plan"]
    assert plan["counts"]["CONTENT_UNIQUE_COUNT"] == 491
    assert plan["counts"]["SOURCE_REFERENCE_COUNT"] == 6646
    assert len(plan["candidates"]) == 491
    assert len(plan["source_references"]) == 6646
    assert plan["counts"]["SCAN_TARGET_COUNT"] == 491
    assert plan["counts"]["SOURCE_REFERENCE_INSPECTION_TARGET_COUNT"] == 491
    assert plan["counts"]["ADDITIONAL_COPY_COUNT"] == 6155
    assert len({ref["source_id"] for ref in plan["source_references"]}) == 6646
    targets = [ref for ref in plan["source_references"] if ref["inspection_target"]]
    assert len(targets) == 491
    assert all(candidate["approval_required"] for candidate in plan["candidates"])
    assert all(
        candidate["scan_status"] == sec.SCAN_NOT_STARTED
        for candidate in plan["candidates"]
    )


def test_approved_root_validation(tmp_path: Path) -> None:
    approved = tmp_path / "approved"
    approved.mkdir()
    report = approved / "report.md"
    report.write_text("synthetic", encoding="utf-8")

    allowed = sec.validate_scan_path(
        report, approved, approved_roots=(str(approved),)
    )
    assert allowed["status"] == sec.SCAN_PATH_APPROVED

    other = tmp_path / "other"
    other.mkdir()
    outside = other / "report.md"
    outside.write_text("synthetic", encoding="utf-8")
    rejected = sec.validate_scan_path(
        outside, other, approved_roots=(str(approved),)
    )
    assert rejected["status"] == sec.SCAN_PATH_REJECTED
    assert rejected["rejection_reason"] == sec.REJECT_SOURCE_ROOT_NOT_APPROVED

    canonical = sec.CANONICAL_ROOT / "synthetic-report.md"
    rejected = sec.validate_scan_path(
        canonical, sec.CANONICAL_ROOT, approved_roots=(str(sec.CANONICAL_ROOT),)
    )
    assert rejected["status"] == sec.SCAN_PATH_REJECTED
    assert rejected["rejection_reason"] == sec.REJECT_SOURCE_ROOT_NOT_APPROVED


def test_symlink_rejection(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("synthetic", encoding="utf-8")
    link = tmp_path / "link.md"
    os.symlink(target, link)

    rejected = sec.validate_scan_path(link, tmp_path, approved_roots=(str(tmp_path),))
    assert rejected["status"] == sec.SCAN_PATH_REJECTED
    assert rejected["rejection_reason"] == sec.REJECT_SYMLINK

    with pytest.raises(sec.ScanRejected) as exc_info:
        list(sec.iter_verified_chunks(link, tmp_path, approved_roots=(str(tmp_path),)))
    assert exc_info.value.code == sec.REJECT_SYMLINK


def test_path_traversal_rejection(tmp_path: Path) -> None:
    traversal = tmp_path / "sub" / ".." / "report.md"
    rejected = sec.validate_scan_path(
        traversal, tmp_path, approved_roots=(str(tmp_path),)
    )
    assert rejected["status"] == sec.SCAN_PATH_REJECTED
    assert rejected["rejection_reason"] == sec.REJECT_PATH_TRAVERSAL


def test_secret_filename_rejection(tmp_path: Path) -> None:
    for name in ("credentials.json", ".env", "id_rsa", "api_key.txt"):
        assert _root_guard(name)
        candidate = tmp_path / name
        candidate.write_text("synthetic", encoding="utf-8")
        rejected = sec.validate_scan_path(
            candidate, tmp_path, approved_roots=(str(tmp_path),)
        )
        assert rejected["status"] == sec.SCAN_PATH_REJECTED
        assert rejected["rejection_reason"] == sec.REJECT_SECRET_FILENAME


def test_streaming_safety_gate(tmp_path: Path) -> None:
    path = tmp_path / "report.md"
    payload = b"line one\nline two\n"
    path.write_bytes(payload)

    collected = b"".join(
        sec.iter_verified_chunks(
            path,
            tmp_path,
            approved_roots=(str(tmp_path),),
            expected_size=len(payload),
            expected_mtime=sec._iso_from_epoch(path.stat().st_mtime),
            chunk_size=4,
        )
    )
    assert collected == payload

    with pytest.raises(sec.ScanRejected) as exc_info:
        list(
            sec.iter_verified_chunks(
                path,
                tmp_path,
                approved_roots=(str(tmp_path),),
                max_bytes=4,
            )
        )
    assert exc_info.value.code == sec.REJECT_SIZE_LIMIT_EXCEEDED

    with pytest.raises(sec.ScanRejected) as exc_info:
        list(
            sec.iter_verified_chunks(
                path,
                tmp_path,
                approved_roots=(str(tmp_path),),
                expected_mtime="2000-01-01T00:00:00+00:00",
            )
        )
    assert exc_info.value.code == sec.REJECT_METADATA_CHANGED


def test_changed_during_read_detection(tmp_path: Path) -> None:
    path = tmp_path / "growing.md"
    path.write_bytes(b"a" * 4096)
    expected_size = path.stat().st_size

    generator = sec.iter_verified_chunks(
        path,
        tmp_path,
        approved_roots=(str(tmp_path),),
        expected_size=expected_size,
        chunk_size=1024,
    )
    first = next(generator)
    assert first == b"a" * 1024
    with path.open("ab") as handle:
        handle.write(b"appended")
    with pytest.raises(sec.ScanRejected) as exc_info:
        list(generator)
    assert exc_info.value.code == sec.REJECT_CHANGED_DURING_READ


def _types(findings: list[dict]) -> set[str]:
    return {finding["secret_type"] for finding in findings}


def test_api_key_detection() -> None:
    findings = sec.scan_to_safe_findings(
        f'api_key = "{SECRET_API_KEY}"', content_hash=HASH_A
    )
    assert "API_KEY" in _types(findings)
    assert all(
        finding["severity"] == sec.SEVERITY_HIGH
        for finding in findings
        if finding["secret_type"] == "API_KEY"
    )


def test_access_token_detection() -> None:
    findings = sec.scan_to_safe_findings(
        f'access_token = "{SECRET_GITHUB}"', content_hash=HASH_A
    )
    assert "ACCESS_TOKEN" in _types(findings)
    assert all(
        finding["severity"] == sec.SEVERITY_HIGH
        for finding in findings
        if finding["secret_type"] == "ACCESS_TOKEN"
    )


def test_bearer_token_detection() -> None:
    findings = sec.scan_to_safe_findings(
        f'Authorization: Bearer {SECRET_GITHUB}', content_hash=HASH_A
    )
    assert _types(findings) & {"AUTHORIZATION_HEADER", "BEARER_TOKEN"}
    assert all(
        finding["severity"] == sec.SEVERITY_HIGH for finding in findings
    )


def test_password_detection() -> None:
    findings = sec.scan_to_safe_findings(
        f'password = "{SECRET_PASSWORD}"', content_hash=HASH_A
    )
    assert "PASSWORD" in _types(findings)
    assert all(
        finding["severity"] == sec.SEVERITY_HIGH
        for finding in findings
        if finding["secret_type"] == "PASSWORD"
    )


def test_private_key_detection() -> None:
    findings = sec.scan_to_safe_findings(
        "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----",
        content_hash=HASH_A,
    )
    assert "PRIVATE_KEY" in _types(findings)
    assert all(
        finding["severity"] == sec.SEVERITY_CRITICAL
        for finding in findings
        if finding["secret_type"] == "PRIVATE_KEY"
    )


def test_cookie_detection() -> None:
    findings = sec.scan_to_safe_findings(
        f"Set-Cookie: {SECRET_COOKIE}", content_hash=HASH_A
    )
    assert "SESSION_COOKIE" in _types(findings)
    assert all(
        finding["severity"] == sec.SEVERITY_HIGH
        for finding in findings
        if finding["secret_type"] == "SESSION_COOKIE"
    )


def test_database_credential_detection() -> None:
    findings = sec.scan_to_safe_findings(
        f"DATABASE_URL={SECRET_DB}", content_hash=HASH_A
    )
    assert "DATABASE_CREDENTIAL" in _types(findings)
    assert all(
        finding["severity"] == sec.SEVERITY_CRITICAL
        for finding in findings
        if finding["secret_type"] == "DATABASE_CREDENTIAL"
    )


def test_exchange_credential_detection() -> None:
    findings = sec.scan_to_safe_findings(
        f'binance_api_key = "{SECRET_EXCHANGE}"', content_hash=HASH_A
    )
    assert "EXCHANGE_API_CREDENTIAL" in _types(findings)
    assert all(
        finding["severity"] == sec.SEVERITY_CRITICAL
        for finding in findings
        if finding["secret_type"] == "EXCHANGE_API_CREDENTIAL"
    )


def test_false_positive_handling() -> None:
    text = "\n".join(
        [
            "API_KEY=<your-api-key>",
            'password = "changeme"',
            "api_key: ${API_KEY}",
            'token = os.environ["TOKEN"]',
            'secret_key = "REDACTED"',
            "secret = dummy",
        ]
    )
    findings = sec.scan_to_safe_findings(text, content_hash=HASH_A)
    assert findings == []


def test_credential_like_context_detection() -> None:
    findings = sec.scan_to_safe_findings(
        "The API key is stored in the team vault.", content_hash=HASH_A
    )
    assert _types(findings) == {"CREDENTIAL_LIKE_TEXT"}
    assert findings[0]["severity"] == sec.SEVERITY_MEDIUM
    assert findings[0]["confidence"] == sec.CONFIDENCE_LOW


def test_severity_classification() -> None:
    assert sec.severity_for("PRIVATE_KEY") == sec.SEVERITY_CRITICAL
    assert sec.severity_for("EXCHANGE_API_CREDENTIAL") == sec.SEVERITY_CRITICAL
    assert sec.severity_for("ACCESS_TOKEN") == sec.SEVERITY_HIGH
    assert sec.severity_for("PASSWORD") == sec.SEVERITY_HIGH
    assert sec.severity_for("CREDENTIAL_LIKE_TEXT") == sec.SEVERITY_MEDIUM
    assert sec.action_for("PRIVATE_KEY") == sec.ACTION_EXCLUDE
    assert sec.action_for("PASSWORD") == sec.ACTION_REDACT
    assert sec.action_for("CREDENTIAL_LIKE_TEXT") == sec.ACTION_REVIEW


def test_no_secret_value_serialization() -> None:
    text = "\n".join(
        [
            f'api_key = "{SECRET_API_KEY}"',
            f'password = "{SECRET_PASSWORD}"',
            f"Set-Cookie: {SECRET_COOKIE}",
            f"DATABASE_URL={SECRET_DB}",
        ]
    )
    internal = sec.scan_text(text)
    serialized = sec.serialize_findings(internal, content_hash=HASH_A)
    payload = json.dumps(serialized, sort_keys=True)

    for value in (
        SECRET_API_KEY,
        SECRET_PASSWORD,
        SECRET_COOKIE,
        SECRET_DB,
        "SuperSecretValue",
    ):
        assert value not in payload

    expected_fields = {
        "finding_id",
        "content_hash",
        "secret_type",
        "severity",
        "confidence",
        "line_number",
        "detection_method",
        "review_status",
        "default_action",
        "value_stored",
    }
    for finding in serialized:
        assert set(finding) == expected_fields
        assert finding["value_stored"] is False
        for forbidden in ("value", "match", "raw", "snippet", "context", "secret_value"):
            assert forbidden not in finding


def test_no_secret_value_logging() -> None:
    text = "\n".join(
        [
            f'api_key = "{SECRET_API_KEY}"',
            f'password = "{SECRET_PASSWORD}"',
        ]
    )
    summary = sec.summarize_findings(
        sec.scan_to_safe_findings(text, content_hash=HASH_A)
    )
    payload = json.dumps(summary, sort_keys=True)
    assert SECRET_API_KEY not in payload
    assert SECRET_PASSWORD not in payload
    assert summary["values_stored"] is False
    assert summary["context_stored"] is False
    assert summary["finding_count"] == 2
    assert summary["by_secret_type"] == {"API_KEY": 1, "PASSWORD": 1}


def test_synthetic_redaction() -> None:
    text = (
        "Project notes\n"
        f'api_key = "{SECRET_API_KEY}"\n'
        "the rest of the report stays intact\n"
    )
    internal = sec.scan_text(text)
    redacted = sec.redact_text(text, internal)

    assert SECRET_API_KEY not in redacted
    assert "[REDACTED:API_KEY]" in redacted
    assert "Project notes" in redacted
    assert "the rest of the report stays intact" in redacted
    assert redacted.count("\n") == text.count("\n")


def test_scan_plan_determinism() -> None:
    first = _build()
    second = _build()
    assert first["scan_plan"] == second["scan_plan"]

    reordered = _fixtures()
    reordered["content_review"]["records"] = list(
        reversed(reordered["content_review"]["records"])
    )
    reordered["hash_results"]["entries"] = list(
        reversed(reordered["hash_results"]["entries"])
    )
    reordered["provenance_review"]["entries"] = list(
        reversed(reordered["provenance_review"]["entries"])
    )
    reordered["import_manifest"]["entries"] = list(
        reversed(reordered["import_manifest"]["entries"])
    )
    third = _build(reordered)
    assert third["scan_plan"] == first["scan_plan"]
    assert third["provenance_review_plan"] == first["provenance_review_plan"]


def test_approval_gate() -> None:
    result = _build()
    gate = result["approval_gate"]
    assert gate["approval_required"] is True
    assert gate["real_source_scan_approved"] is False
    assert gate["real_source_scan_approved_label"] == "NO"
    assert gate["real_source_scan_executed"] is False
    assert gate["real_import_executed"] is False
    assert gate["blocked"] is True
    assert gate["block_reason"] == "OPERATOR_APPROVAL_REQUIRED"

    granted = sec.build_approval_gate(
        result["scan_plan"], approval_token=sec.REAL_SCAN_APPROVAL_TOKEN
    )
    assert granted["real_source_scan_approved"] is True
    assert granted["blocked"] is False
    assert granted["real_source_scan_executed"] is False
    assert granted["real_import_executed"] is False


def test_manifest_approved_false_and_secret_not_performed() -> None:
    result = _build()
    plan = result["scan_plan"]
    assert result["counts"]["ALL_APPROVED_FALSE"] is True
    assert result["counts"]["ALL_IMPORT_READY_FALSE"] is True
    assert result["counts"]["ALL_REAL_IMPORT_ALLOWED_FALSE"] is True
    assert result["counts"]["ALL_SECRET_REVIEW_NOT_PERFORMED"] is True
    assert result["counts"]["SECRET_SCAN_APPROVED_COUNT"] == 0

    for candidate in plan["candidates"]:
        assert candidate["approved"] is False
        assert candidate["import_ready"] is False
        assert candidate["real_import_allowed"] is False
        assert candidate["secret_review_status"] == sec.SECRET_REVIEW_NOT_PERFORMED
        assert candidate["secret_finding_count"] is None
        assert candidate["secret_review_required"] is True
        assert candidate["secret_scan_approved"] is False
        assert candidate["provenance_status"] == "UNKNOWN"
        assert candidate["source_truth_class"] == "AGENT_REPORTED"
        assert candidate["authority_scope"] == "NONE"
        assert candidate["historical_record"] is True
        assert candidate["historical_runtime_authority"] is False

    for entry in result["provenance_review_plan"]["entries"]:
        assert entry["provenance_status"] == "UNKNOWN"
        assert entry["confirmed_cursor"] is False
        assert entry["confirmed_other_agent"] is False
        assert entry["confirmed_chatgpt"] is False
        assert entry["review_status"] == sec.REVIEW_NOT_STARTED


def test_no_real_source_read(monkeypatch) -> None:
    fixtures = _fixtures()

    def _forbidden_read(*args, **kwargs):
        raise AssertionError("real source body must not be read")

    monkeypatch.setattr(Path, "read_text", _forbidden_read)
    monkeypatch.setattr(Path, "open", _forbidden_read)

    result = _build(fixtures)
    assert result["scan_plan"]["content_read"] is False
    assert result["scan_plan"]["source_body_stored"] is False
    assert result["scan_plan"]["real_source_scan_executed"] is False
    assert result["validation"]["inputs_valid"] is True


def test_no_real_import() -> None:
    source = (ROOT / "scripts" / "bc11e_secret_review.py").read_text(
        encoding="utf-8"
    )
    for token in (
        "real_import(",
        "import_report(",
        "import_knowledge(",
        "ingest_report(",
    ):
        assert token not in source

    result = _build()
    assert result["scan_plan"]["real_import_executed"] is False
    assert result["provenance_review_plan"]["real_import_executed"] is False
    assert result["redaction_policy"]["real_import_executed"] is False
    assert result["acceptance"]["NO_REAL_IMPORT"] is True


def test_no_production_write(tmp_path: Path) -> None:
    source = (ROOT / "scripts" / "bc11e_secret_review.py").read_text(
        encoding="utf-8"
    )
    for token in ("sqlite3", "psycopg", "/var/lib/tradingai", "production_db"):
        assert token not in source

    result = _build()
    out = tmp_path / "out"
    paths = sec.write_stage_a_outputs(result, output_dir=out)
    written = {Path(item).resolve() for item in paths.values()}
    assert all(item.parent == out.resolve() for item in written)
    assert len(written) == 6
    assert {item.name for item in written} == {
        sec.SCAN_PLAN_JSON_NAME,
        sec.DETECTION_POLICY_JSON_NAME,
        sec.PROVENANCE_PLAN_JSON_NAME,
        sec.REDACTION_POLICY_JSON_NAME,
        sec.APPROVAL_REQUEST_MD_NAME,
        sec.FINAL_MD_NAME,
    }


def test_outputs_and_policies(tmp_path: Path) -> None:
    result = _build()
    out = tmp_path / "out"
    paths = sec.write_stage_a_outputs(
        result,
        output_dir=out,
        meta={
            "worktree": "/synthetic/worktree",
            "branch": "feature/synthetic",
            "head_before": "0" * 40,
            "head_after": "1" * 40,
            "test_results": "PASS",
            "changed_files": "two",
            "commit": "abc1234",
        },
    )
    plan = json.loads(Path(paths["secret_scan_plan"]).read_text("utf-8"))
    policy = json.loads(Path(paths["secret_detection_policy"]).read_text("utf-8"))
    provenance = json.loads(
        Path(paths["provenance_review_plan"]).read_text("utf-8")
    )
    redaction = json.loads(Path(paths["redaction_policy"]).read_text("utf-8"))
    approval = Path(paths["real_scan_approval_request"]).read_text("utf-8")
    final = Path(paths["stage_a_final"]).read_text("utf-8")

    assert plan["counts"]["CONTENT_UNIQUE_COUNT"] == 2
    assert plan["counts"]["SOURCE_REFERENCE_COUNT"] == 4
    assert plan["real_source_scan_executed"] is False
    assert policy["real_source_scan_executed"] is False
    assert policy["entropy_policy"]["used_as_sole_evidence"] is False
    assert provenance["counts"]["PROVENANCE_REVIEW_COUNT"] == 2
    assert provenance["content_read"] is False
    assert redaction["real_file_modified"] is False
    assert redaction["import_body_generated"] is False
    assert redaction["applies_to"] == "SYNTHETIC_FIXTURE_ONLY"
    assert "REQUIRED_APPROVAL_TOKEN=" + sec.REAL_SCAN_APPROVAL_TOKEN in approval
    assert "REAL_SOURCE_SCAN_EXECUTED=NO" in approval
    for field in (
        "TASK_ID",
        "VERDICT",
        "WORKTREE",
        "BRANCH",
        "HEAD_BEFORE",
        "HEAD_AFTER",
        "CONTENT_UNIQUE_COUNT",
        "SOURCE_REFERENCE_COUNT",
        "SECRET_SCAN_PLAN_COUNT",
        "SECRET_DETECTION_POLICY_CREATED",
        "PROVENANCE_REVIEW_PLAN_CREATED",
        "REDACTION_POLICY_CREATED",
        "REAL_SCAN_APPROVAL_REQUEST_CREATED",
        "ALL_SECRET_REVIEW_NOT_PERFORMED",
        "ALL_APPROVED_FALSE",
        "ALL_IMPORT_READY_FALSE",
        "ALL_REAL_IMPORT_ALLOWED_FALSE",
        "TEST_RESULTS",
        "CHANGED_FILES",
        "COMMIT",
        "PRODUCTION_DB_UNCHANGED",
        "CANONICAL_UNCHANGED",
        "WORK_AA_UNCHANGED",
        "BB_CC_UNCHANGED",
        "REAL_SOURCE_SCAN_EXECUTED",
        "REAL_IMPORT_EXECUTED",
        "GIT_PUSH",
        "PRODUCTION_RESTART",
        "NEXT_REQUIRED_APPROVAL",
    ):
        assert f"{field}=" in final


def test_cli_stage_a(tmp_path: Path) -> None:
    fixtures = _large_fixtures()
    paths = {
        "content": tmp_path / "content.json",
        "provenance": tmp_path / "provenance.json",
        "manifest": tmp_path / "manifest.json",
        "hash": tmp_path / "hash.json",
        "final_ref": tmp_path / "final.md",
    }
    paths["content"].write_text(
        json.dumps(fixtures["content_review"]), encoding="utf-8"
    )
    paths["provenance"].write_text(
        json.dumps(fixtures["provenance_review"]), encoding="utf-8"
    )
    paths["manifest"].write_text(
        json.dumps(fixtures["import_manifest"]), encoding="utf-8"
    )
    paths["hash"].write_text(
        json.dumps(fixtures["hash_results"]), encoding="utf-8"
    )
    paths["final_ref"].write_text("# synthetic\n", encoding="utf-8")

    out = tmp_path / "out"
    exit_code = sec.main(
        [
            "--stage-a",
            "--content-unique-review",
            str(paths["content"]),
            "--provenance-review-queue",
            str(paths["provenance"]),
            "--import-manifest-review",
            str(paths["manifest"]),
            "--import-target-final",
            str(paths["final_ref"]),
            "--hash-results",
            str(paths["hash"]),
            "--confirmed-duplicates",
            str(tmp_path / "absent-confirmed.json"),
            "--unique-content-candidates",
            str(tmp_path / "absent-unique.json"),
            "--output-dir",
            str(out),
            "--generated-at",
            GENERATED_AT,
        ]
    )
    assert exit_code == 0
    assert (out / sec.SCAN_PLAN_JSON_NAME).exists()
    assert (out / sec.FINAL_MD_NAME).exists()


# ---------------------------------------------------------------------------
# Stage B: approved read-only real source content scan (synthetic fixtures)
# ---------------------------------------------------------------------------


def _stage_b_fixture(tmp_path: Path, specs: list[dict]) -> dict:
    root = tmp_path / "reports"
    root.mkdir(parents=True, exist_ok=True)
    candidates: list[dict] = []
    references: list[dict] = []
    provenance_entries: list[dict] = []
    manifest_entries: list[dict] = []

    for index, spec in enumerate(specs):
        path = root / spec.get("name", f"report_{index}.md")
        data = spec.get("content", "").encode("utf-8")
        path.write_bytes(data)
        stat_result = path.stat()
        content_hash = hashlib.sha256(data).hexdigest()
        source_id = f"src_{index}"
        mtime = sec._iso_from_epoch(stat_result.st_mtime)
        candidates.append(
            {
                "content_hash": content_hash,
                "representative_source_id": source_id,
                "absolute_path": str(path),
                "source_root": str(root),
                "size_bytes": stat_result.st_size,
                "mtime": mtime,
                "source_metadata_available": True,
                "source_metadata_hash_matches": True,
            }
        )
        references.append(
            {
                "source_id": source_id,
                "content_hash": content_hash,
                "absolute_path": str(path),
                "source_root": str(root),
                "size_bytes": stat_result.st_size,
                "mtime": mtime,
                "inspection_target": True,
                "in_content_unique_set": True,
            }
        )
        provenance_entries.append(
            {
                "content_hash": content_hash,
                "representative_source_id": source_id,
                "member_source_ids": [source_id],
                "provenance_status": "UNKNOWN",
                "classifications": [],
            }
        )
        manifest_entries.append(
            {
                "content_hash": content_hash,
                "representative_source_id": source_id,
                "approved": False,
                "import_ready": False,
                "real_import_allowed": False,
                "secret_review_status": "NOT_PERFORMED",
            }
        )

    return {
        "root": root,
        "scan_plan": {
            "approved_roots": [str(root)],
            "candidates": candidates,
            "source_references": references,
            "counts": {"SOURCE_REFERENCE_COUNT": len(references)},
        },
        "provenance_plan": {"entries": provenance_entries},
        "hash_results": {"entries": [dict(reference) for reference in references]},
        "manifest_review": {"entries": manifest_entries},
    }


def _build_stage_b(
    fixture: dict,
    *,
    approval_granted: bool = True,
    expected_targets: int | None = None,
    expected_references: int | None = None,
) -> dict:
    return sec.build_stage_b(
        scan_plan=fixture["scan_plan"],
        provenance_plan=fixture["provenance_plan"],
        hash_results=fixture["hash_results"],
        manifest_review=fixture["manifest_review"],
        detection_policy={"schema_version": sec.DETECTION_POLICY_SCHEMA_VERSION},
        redaction_policy={"schema_version": sec.REDACTION_POLICY_SCHEMA_VERSION},
        generated_at=GENERATED_AT,
        approval_granted=approval_granted,
        approved_roots=(str(fixture["root"]),),
        expected_targets=expected_targets
        if expected_targets is not None
        else len(fixture["scan_plan"]["candidates"]),
        expected_references=expected_references
        if expected_references is not None
        else len(fixture["scan_plan"]["source_references"]),
    )


def test_stage_b_approval_gate_blocks_before_open(
    tmp_path: Path, monkeypatch
) -> None:
    fixture = _stage_b_fixture(tmp_path, [{"content": "clean report\n"}])

    def _boom(*args, **kwargs):
        raise AssertionError("real source must not be opened without approval")

    monkeypatch.setattr(sec, "iter_verified_chunks", _boom)
    with pytest.raises(sec.SecurityBoundaryError):
        _build_stage_b(fixture, approval_granted=False)


def test_stage_b_target_and_reference_validation(tmp_path: Path) -> None:
    fixture = _stage_b_fixture(
        tmp_path,
        [
            {"content": "clean report one\n"},
            {"content": "clean report two\n"},
            {"content": "clean report three\n"},
        ],
    )
    result = _build_stage_b(fixture)
    assert result["verdict"] == sec.VERDICT_STAGE_B_COMPLETE
    assert result["counts"]["EXPECTED_TARGET_COUNT"] == 3
    assert result["counts"]["ACTUAL_SCAN_TARGET_COUNT"] == 3
    assert result["counts"]["SOURCE_REFERENCE_COUNT"] == 3
    assert result["acceptance"]["ALL_TARGETS_EXPLICITLY_RECORDED"] is True

    with pytest.raises(sec.InputError):
        _build_stage_b(fixture, expected_targets=sec.EXPECTED_TARGET_COUNT)


def test_stage_b_read_only_open_preserves_source(tmp_path: Path) -> None:
    content = "stable historical report body\n"
    fixture = _stage_b_fixture(tmp_path, [{"content": content}])
    path = Path(fixture["scan_plan"]["candidates"][0]["absolute_path"])
    before = (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)

    result = _build_stage_b(fixture)
    after = (path.read_bytes(), path.stat().st_size, path.stat().st_mtime_ns)

    assert before == after
    assert result["targets"][0]["scan_status"] == sec.SCAN_COMPLETED_NO_FINDINGS
    assert result["targets"][0]["content_hash_verified"] is True


def test_stage_b_symlink_rejection(tmp_path: Path) -> None:
    target = tmp_path / "real_report.md"
    target.write_text("clean\n", encoding="utf-8")
    link = tmp_path / "link_report.md"
    link.symlink_to(target)
    stat_result = target.stat()
    candidate = {
        "content_hash": hashlib.sha256(b"clean\n").hexdigest(),
        "representative_source_id": "src_link",
        "absolute_path": str(link),
        "source_root": str(tmp_path),
        "size_bytes": stat_result.st_size,
        "mtime": sec._iso_from_epoch(stat_result.st_mtime),
    }
    result = sec.scan_target(candidate, approved_roots=(tmp_path,))
    assert result["scan_status"] == sec.SOURCE_REJECTED
    assert result["rejection_reason"] == sec.REJECT_SYMLINK


def test_stage_b_path_traversal_rejection(tmp_path: Path) -> None:
    candidate = {
        "content_hash": "0" * 64,
        "representative_source_id": "src_traversal",
        "absolute_path": str(tmp_path / "reports" / ".." / "escape.md"),
        "source_root": str(tmp_path / "reports"),
        "size_bytes": 1,
        "mtime": MTIME,
    }
    result = sec.scan_target(candidate, approved_roots=(tmp_path,))
    assert result["scan_status"] == sec.SOURCE_REJECTED
    assert result["rejection_reason"] == sec.REJECT_PATH_TRAVERSAL


def test_stage_b_source_changed_detection(tmp_path: Path) -> None:
    fixture = _stage_b_fixture(tmp_path, [{"content": "original report\n"}])
    candidate = fixture["scan_plan"]["candidates"][0]

    stale_size = dict(candidate)
    stale_size["size_bytes"] = int(stale_size["size_bytes"]) + 1
    assert (
        sec.scan_target(stale_size, approved_roots=(tmp_path,))["scan_status"]
        == sec.SOURCE_CHANGED
    )

    stale_mtime = dict(candidate)
    stale_mtime["mtime"] = "2000-01-01T00:00:00+00:00"
    assert (
        sec.scan_target(stale_mtime, approved_roots=(tmp_path,))["scan_status"]
        == sec.SOURCE_CHANGED
    )

    path = Path(candidate["absolute_path"])
    path.write_text("replaced report body with different bytes\n", encoding="utf-8")
    stat_result = path.stat()
    hash_mismatch = dict(candidate)
    hash_mismatch["size_bytes"] = stat_result.st_size
    hash_mismatch["mtime"] = sec._iso_from_epoch(stat_result.st_mtime)
    result = sec.scan_target(hash_mismatch, approved_roots=(tmp_path,))
    assert result["scan_status"] == sec.SOURCE_CHANGED
    assert result["rejection_reason"] == "CONTENT_HASH_MISMATCH"


def test_stage_b_secret_detection_and_safe_serialization(tmp_path: Path) -> None:
    content = (
        "Historical note\n"
        f"api_key = {SECRET_API_KEY}\n"
        f"password = {SECRET_PASSWORD}\n"
    )
    fixture = _stage_b_fixture(tmp_path, [{"content": content}])
    result = _build_stage_b(fixture)
    target = result["targets"][0]
    assert target["scan_status"] == sec.SCAN_COMPLETED_FINDINGS
    assert target["finding_count"] >= 2
    assert target["severity_counts"]["HIGH"] >= 2

    serialized = json.dumps(result, sort_keys=True)
    for secret in (SECRET_API_KEY, SECRET_PASSWORD):
        assert secret not in serialized
    findings_blob = json.dumps(result["targets"][0]["findings"], sort_keys=True)
    for forbidden in (
        "raw_match",
        "raw_context",
        "secret_value",
        "unmasked_token",
        "private_key_body",
    ):
        assert forbidden not in findings_blob
    for finding in target["findings"]:
        assert finding["value_stored"] is False
        assert set(finding) == {
            "finding_id",
            "content_hash",
            "secret_type",
            "severity",
            "confidence",
            "line_number",
            "detection_method",
            "review_status",
            "default_action",
            "value_stored",
        }


def test_stage_b_provenance_evidence_classification(tmp_path: Path) -> None:
    fixture = _stage_b_fixture(
        tmp_path,
        [
            {"content": "Generated by Cursor\nclean body\n"},
            {"content": "We discussed Cursor and OpenCode in this note.\n"},
            {"content": "Generated by Cursor\nAgent: OpenCode\n"},
        ],
    )
    result = _build_stage_b(fixture)
    entries = {
        entry["representative_source_id"]: entry
        for entry in result["provenance_evidence_review"]["entries"]
    }
    first, second, third = entries["src_0"], entries["src_1"], entries["src_2"]

    assert first["provenance_status"] == sec.PROVENANCE_CONFIRMED
    assert first["classification"] == sec.PROVENANCE_CURSOR_CANDIDATE
    assert first["confirmed_cursor"] is True

    assert second["provenance_status"] == sec.PROVENANCE_UNKNOWN_CLASS
    assert second["confirmed_cursor"] is False
    assert second["confirmed_opencode"] is False

    assert third["provenance_status"] == sec.PROVENANCE_UNKNOWN_CLASS


def test_stage_b_import_eligibility_classification(tmp_path: Path) -> None:
    content_api_key = f"api_key = {SECRET_API_KEY}\n"
    content_private_key = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "c3ludGhldGljLWJvZHktZm9yLXRlc3Rpbmctb25seQ==\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    fixture = _stage_b_fixture(
        tmp_path,
        [
            {"content": "clean historical report\n"},
            {"content": content_api_key},
            {"content": content_private_key},
        ],
    )
    result = _build_stage_b(fixture)
    by_id = {
        target["representative_source_id"]: target for target in result["targets"]
    }
    assert by_id["src_0"]["import_eligibility"] == sec.ELIGIBLE_CANDIDATE
    assert by_id["src_1"]["import_eligibility"] == sec.REDACTION_REQUIRED
    assert by_id["src_2"]["import_eligibility"] == sec.MANUAL_REVIEW_REQUIRED
    assert result["counts"]["ELIGIBLE_CANDIDATE_COUNT"] == 1
    assert result["counts"]["REDACTION_REQUIRED_COUNT"] == 1
    assert result["counts"]["MANUAL_REVIEW_REQUIRED_COUNT"] == 1


def test_stage_b_unavailable_and_rejected_eligibility(tmp_path: Path) -> None:
    fixture = _stage_b_fixture(
        tmp_path,
        [{"content": "clean one\n"}, {"content": "clean two\n"}],
    )
    missing = dict(fixture["scan_plan"]["candidates"][0])
    missing["absolute_path"] = str(tmp_path / "reports" / "does_not_exist.md")
    missing["source_metadata_available"] = True
    fixture["scan_plan"]["candidates"][0] = missing
    fixture["scan_plan"]["source_references"][0]["content_hash"] = missing[
        "content_hash"
    ]
    fixture["scan_plan"]["source_references"][0][
        "absolute_path"
    ] = missing["absolute_path"]

    result = _build_stage_b(fixture)
    by_id = {
        target["representative_source_id"]: target for target in result["targets"]
    }
    assert by_id["src_0"]["scan_status"] == sec.SOURCE_UNAVAILABLE
    assert by_id["src_0"]["import_eligibility"] == sec.SOURCE_UNAVAILABLE
    assert result["counts"]["SOURCE_UNAVAILABLE_COUNT"] == 1


def test_stage_b_manifest_flags_stay_false(tmp_path: Path) -> None:
    fixture = _stage_b_fixture(
        tmp_path,
        [{"content": f"token = {SECRET_API_KEY}\n"}, {"content": "clean\n"}],
    )
    result = _build_stage_b(fixture)
    for target in result["targets"]:
        assert target["approved"] is False
        assert target["import_ready"] is False
        assert target["real_import_allowed"] is False
    assert result["counts"]["ALL_APPROVED_FALSE"] is True
    assert result["counts"]["ALL_IMPORT_READY_FALSE"] is True
    assert result["counts"]["ALL_REAL_IMPORT_ALLOWED_FALSE"] is True
    for entry in result["import_eligibility_review"]["entries"]:
        assert entry["approved"] is False
        assert entry["import_ready"] is False
        assert entry["real_import_allowed"] is False
        assert entry["source_truth_class"] == "AGENT_REPORTED"
        assert entry["authority_scope"] == "NONE"
        assert entry["historical_record"] is True
        assert entry["historical_runtime_authority"] is False
    assert result["safety"]["real_import_executed"] is False
    assert result["safety"]["source_files_modified"] is False


def test_stage_b_outputs_are_private(tmp_path: Path) -> None:
    fixture = _stage_b_fixture(tmp_path, [{"content": "clean report\n"}])
    result = _build_stage_b(fixture)
    out = tmp_path / "out"
    paths = sec.write_stage_b_outputs(result, output_dir=out)
    assert {Path(value).name for value in paths.values()} == {
        sec.REAL_SCAN_RESULTS_JSON_NAME,
        sec.SECRET_FINDINGS_SUMMARY_JSON_NAME,
        sec.PROVENANCE_EVIDENCE_JSON_NAME,
        sec.IMPORT_ELIGIBILITY_JSON_NAME,
        sec.STAGE_B_FINAL_MD_NAME,
    }
    for value in paths.values():
        path = Path(value)
        assert path.parent == out.resolve()
        assert (path.stat().st_mode & 0o777) == 0o600
    final = Path(paths["stage_b_final"]).read_text("utf-8")
    assert "VERDICT=BC11E7A_STAGE_B_REAL_SCAN_COMPLETE" in final
    assert "REAL_IMPORT_EXECUTED=NO" in final


def test_stage_b_cli_approval_gate(tmp_path: Path) -> None:
    fixture = _stage_b_fixture(tmp_path, [{"content": "clean report\n"}])
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    scan_plan_path = inputs / "scan_plan.json"
    detection_path = inputs / "detection.json"
    provenance_path = inputs / "provenance.json"
    redaction_path = inputs / "redaction.json"
    hash_path = inputs / "hash.json"
    manifest_path = inputs / "manifest.json"
    stage_a_final = inputs / "stage_a_final.md"
    scan_plan_path.write_text(json.dumps(fixture["scan_plan"]), "utf-8")
    detection_path.write_text(
        json.dumps({"schema_version": sec.DETECTION_POLICY_SCHEMA_VERSION}), "utf-8"
    )
    provenance_path.write_text(
        json.dumps(fixture["provenance_plan"]), "utf-8"
    )
    redaction_path.write_text(
        json.dumps({"schema_version": sec.REDACTION_POLICY_SCHEMA_VERSION}), "utf-8"
    )
    hash_path.write_text(json.dumps(fixture["hash_results"]), "utf-8")
    manifest_path.write_text(json.dumps(fixture["manifest_review"]), "utf-8")
    stage_a_final.write_text("stage a\n", "utf-8")

    base = [
        "--stage-b",
        "--secret-scan-plan", str(scan_plan_path),
        "--secret-detection-policy", str(detection_path),
        "--provenance-review-plan", str(provenance_path),
        "--redaction-policy", str(redaction_path),
        "--hash-results", str(hash_path),
        "--import-manifest-review", str(manifest_path),
        "--stage-a-final", str(stage_a_final),
        "--output-dir", str(tmp_path / "out"),
        "--expected-target-count", "1",
        "--expected-source-reference-count", "1",
    ]
    assert sec.main(base) == 3
    assert not (tmp_path / "out" / sec.REAL_SCAN_RESULTS_JSON_NAME).exists()

    assert sec.main(base + ["--real-source-scan-approved"]) == 0
    results = json.loads(
        (tmp_path / "out" / sec.REAL_SCAN_RESULTS_JSON_NAME).read_text("utf-8")
    )
    assert results["real_source_scan_approved"] is True
    assert results["real_import_executed"] is False
    assert results["counts"]["ACTUAL_SCAN_TARGET_COUNT"] == 1
