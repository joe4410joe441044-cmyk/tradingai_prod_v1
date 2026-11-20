"""BC isolated partial-import acceptance with record-level approval."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.knowledge_hub.import_readiness import PRODUCTION_STORE_PATH, SearchProbe
from backend.knowledge_hub.knowledge_store import KnowledgeStore, StoreLimits
from backend.knowledge_hub.partial_import import (
    STATUS_BLOCKED,
    STATUS_COMPLETE,
    STATUS_PREVIEW,
    SourceFileApproval,
    create_source_file_approval,
    run_partial_import,
)
from backend.knowledge_hub.record_approval import (
    ApprovalError,
    ApprovalLedger,
    FINDING_REDACTED,
    FindingDisposition,
    MANUAL_APPROVED,
    MANUAL_NOT_REQUIRED,
    MANUAL_PENDING,
    ManualReviewDecision,
    OperatorAuthorization,
    RECORD_APPROVED,
    RECORD_EXCLUDED,
    RECORD_REJECTED,
    RecordDecision,
    RedactionApproval,
    SecretFinding,
    prepare_redaction,
)

AT = "2026-11-18T00:00:00+00:00"
AUTH = OperatorAuthorization(
    authorization_id="auth-partial-1",
    authority="OPERATOR",
    issued_at=AT,
)
OBS = "2026-11-18T00:00:01+00:00"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_id(path: Path) -> str:
    return f"rec_{_hash(path)[:24]}"


def _approval(paths, store: Path, *, auth=AUTH) -> SourceFileApproval:
    return create_source_file_approval(paths, store_path=store, authorization=auth)


def _approve(ledger: ApprovalLedger, path: Path, **overrides) -> RecordDecision:
    values = {
        "record_id": _record_id(path),
        "content_hash": _hash(path),
        "state": RECORD_APPROVED,
        "decision_authority": "OPERATOR",
        "decided_at": AT,
        "source_file": str(path.resolve()),
        "workstream": "WORK_BC",
        "manual_review_state": MANUAL_NOT_REQUIRED,
        "reason": "SYNTHETIC_OPERATOR_APPROVAL",
    }
    values.update(overrides)
    return ledger.decide_record(RecordDecision(**values), AUTH)


def _run(store: Path, paths, approval, ledger, *, apply):
    return run_partial_import(
        store,
        source_paths=paths,
        source_roots=(paths[0].parent,),
        source_approval=approval,
        ledger=ledger,
        indexed_at=OBS,
        apply=apply,
    )


def _rows(store: Path):
    knowledge = KnowledgeStore.open(store, StoreLimits(max_results=500))
    try:
        return knowledge.list_records(limit=500)
    finally:
        knowledge.close()


def _fixture(tmp_path: Path):
    root = tmp_path / "reports"
    safe_a = _write(
        root / "safe_a.md",
        "TASK_ID: SYNTHETIC-A\nWORKSTREAM: WORK_BC\nVERDICT: PASS\nsafealphamarker\n",
    )
    safe_b = _write(
        root / "safe_b.md",
        "TASK_ID: SYNTHETIC-B\nWORKSTREAM: WORK_BB\nVERDICT: PASS\nsafebetamarker\n",
    )
    manual = _write(
        root / "manual.md",
        "TASK_ID: SYNTHETIC-M\nWORKSTREAM: WORK_CC\nVERDICT: PASS\nmanualmarker\n",
    )
    secret = _write(
        root / "sensitive.md",
        "TASK_ID: SYNTHETIC-S\nWORKSTREAM: WORK_BC\npassword=hunter2\nsecretmarker\n",
    )
    redact = _write(
        root / "redact.md",
        "TASK_ID: SYNTHETIC-R\nWORKSTREAM: WORK_BC\npassword=hunter2\nredactmarker kept\n",
    )
    rejected = _write(
        root / "rejected.md",
        "TASK_ID: SYNTHETIC-X\nWORKSTREAM: WORK_BC\nrejectedmarker\n",
    )
    excluded = _write(
        root / "excluded.md",
        "TASK_ID: SYNTHETIC-E\nWORKSTREAM: WORK_BC\nexcludedmarker\n",
    )
    return {
        "root": root,
        "safe_a": safe_a,
        "safe_b": safe_b,
        "manual": manual,
        "secret": secret,
        "redact": redact,
        "rejected": rejected,
        "excluded": excluded,
        "all": [safe_a, safe_b, manual, secret, redact, rejected, excluded],
    }


def _add_redaction(ledger: ApprovalLedger, path: Path):
    record_id = _record_id(path)
    finding = SecretFinding(
        finding_id="find-redact",
        record_id=record_id,
        category="PASSWORD",
        severity="HIGH",
        redaction_required=True,
        source_file=str(path.resolve()),
    )
    ledger.register_finding(finding)
    ledger.dispose_finding(
        FindingDisposition(
            finding_id=finding.finding_id,
            record_id=record_id,
            category="PASSWORD",
            disposition=FINDING_REDACTED,
            decision_authority="OPERATOR",
            decided_at=AT,
        ),
        AUTH,
    )
    candidate = prepare_redaction(record_id, path.read_text(encoding="utf-8"), [finding.finding_id])
    ledger.record_redaction(
        RedactionApproval(
            record_id=record_id,
            original_content_hash=candidate.original_content_hash,
            sanitized_content_hash=candidate.sanitized_content_hash,
            finding_ids=(finding.finding_id,),
            method="MATCHED_SPAN_REDACTION",
            decision_authority="OPERATOR",
            decided_at=AT,
        ),
        AUTH,
    )
    return candidate, record_id


def test_approved_safe_record_imports_and_unapproved_record_is_blocked(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    _approve(ledger, fixture["safe_a"])
    approval = _approval(fixture["all"], store)
    result = _run(store, fixture["all"], approval, ledger, apply=True)
    assert result.status == "PARTIAL"
    assert result.imported_count == 1
    assert result.blocked_count >= 1
    rows = _rows(store)
    assert [row["workstream"] for row in rows] == ["WORK_BC"]
    assert "safealphamarker" in rows[0]["content"]
    assert all("safebetamarker" not in row["content"] for row in rows)
    codes = {outcome.code for outcome in result.outcomes if outcome.status == "BLOCKED"}
    assert "RECORD_NOT_APPROVED" in codes


def test_source_approval_cannot_bypass_record_level_restrictions(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    _approve(ledger, fixture["safe_a"])
    approval = _approval(fixture["all"], store)
    result = _run(store, fixture["all"], approval, ledger, apply=False)
    assert result.status == STATUS_PREVIEW
    assert result.eligible_count == 1
    assert result.blocked_count == len(fixture["all"]) - 1
    assert not store.exists()
    safe_b = next(item for item in result.outcomes if item.source_file.endswith("safe_b.md"))
    assert safe_b.status == "BLOCKED"
    assert safe_b.code == "RECORD_NOT_APPROVED"


def test_missing_or_mismatched_source_approval_fails_closed(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    _approve(ledger, fixture["safe_a"])
    absent = _run(store, fixture["all"], None, ledger, apply=True)
    assert absent.status == STATUS_BLOCKED
    assert absent.errors == ("SOURCE_APPROVAL_REQUIRED",)
    assert not store.exists()

    subset = _approval([fixture["safe_a"]], store)
    mismatch = _run(store, fixture["all"], subset, ledger, apply=True)
    assert mismatch.status == STATUS_BLOCKED
    assert mismatch.errors == ("SOURCE_APPROVAL_SET_MISMATCH",)
    assert not store.exists()


def test_production_store_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    ledger = ApprovalLedger()
    _approve(ledger, fixture["safe_a"])
    approval = _approval([fixture["safe_a"]], PRODUCTION_STORE_PATH)
    result = run_partial_import(
        PRODUCTION_STORE_PATH,
        source_paths=[fixture["safe_a"]],
        source_roots=(fixture["root"],),
        source_approval=approval,
        ledger=ledger,
        indexed_at=OBS,
        apply=True,
    )
    assert result.status == STATUS_BLOCKED
    assert result.errors == ("PRODUCTION_STORE_REJECTED",)


def test_unresolved_secret_finding_blocks_import_even_with_legacy_decision(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    path = fixture["secret"]
    record_id = _record_id(path)
    snapshot = {
        "findings": [
            {
                "finding_id": "find-unresolved",
                "record_id": record_id,
                "category": "PASSWORD",
                "severity": "HIGH",
                "redaction_required": True,
            }
        ],
        "records": [
            {
                "record_id": record_id,
                "content_hash": _hash(path),
                "state": RECORD_APPROVED,
                "decision_authority": "OPERATOR",
                "decided_at": AT,
                "source_file": str(path.resolve()),
                "workstream": "WORK_BC",
                "manual_review_state": MANUAL_NOT_REQUIRED,
                "redaction_required": True,
            }
        ],
    }
    ledger.load_snapshot(snapshot)
    approval = _approval([path], store)
    result = _run(store, [path], approval, ledger, apply=True)
    assert result.status == STATUS_BLOCKED
    assert result.imported_count == 0
    assert any(outcome.code == "UNRESOLVED_SECRET_FINDING" for outcome in result.outcomes)
    assert not store.exists()


def test_redaction_required_record_blocks_until_sanitized_representation(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    candidate, record_id = _add_redaction(ledger, fixture["redact"])
    _approve(
        ledger,
        fixture["redact"],
        record_id=record_id,
        redaction_required=True,
        sanitized_content_hash=candidate.sanitized_content_hash,
    )
    approval = _approval([fixture["redact"]], store)
    blocked = _run(store, [fixture["redact"]], approval, ledger, apply=True)
    assert blocked.imported_count == 0
    assert any(
        outcome.code == "SANITIZED_REPRESENTATION_REQUIRED" for outcome in blocked.outcomes
    )
    assert not store.exists()

    result = run_partial_import(
        store,
        source_paths=[fixture["redact"]],
        source_roots=(fixture["root"],),
        source_approval=approval,
        ledger=ledger,
        indexed_at=OBS,
        apply=True,
        sanitized_representations={candidate.original_content_hash: candidate.sanitized_content},
        search_probes=(
            SearchProbe("sanitized", "redactmarker kept"),
            SearchProbe("secret", "hunter2"),
        ),
    )
    assert result.status == STATUS_COMPLETE
    assert result.imported_count == 1
    rows = _rows(store)
    assert "redactmarker kept" in rows[0]["content"]
    assert "hunter2" not in rows[0]["content"]
    assert rows[0]["metadata"]["redaction_status"] == "APPLIED"
    assert result.search[0]["total_count"] == 1
    assert result.search[1]["total_count"] == 0


def test_manual_review_pending_is_blocked_and_approved_is_imported(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    path = fixture["manual"]
    record_id = _record_id(path)
    ledger.load_snapshot(
        {
            "records": [
                {
                    "record_id": record_id,
                    "content_hash": _hash(path),
                    "state": RECORD_APPROVED,
                    "decision_authority": "OPERATOR",
                    "decided_at": AT,
                    "source_file": str(path.resolve()),
                    "workstream": "WORK_CC",
                    "manual_review_state": MANUAL_PENDING,
                }
            ]
        }
    )
    approval = _approval([path], store)
    blocked = _run(store, [path], approval, ledger, apply=True)
    assert blocked.imported_count == 0
    assert any(outcome.code == "MANUAL_REVIEW_PENDING" for outcome in blocked.outcomes)

    ledger.record_manual_review(
        ManualReviewDecision(
            record_id=record_id,
            state=MANUAL_APPROVED,
            reason="OPERATOR_REVIEWED",
            decision_authority="OPERATOR",
            decided_at=AT,
        ),
        AUTH,
    )
    imported = _run(store, [path], approval, ledger, apply=True)
    assert imported.imported_count == 1
    rows = _rows(store)
    assert "manualmarker" in rows[0]["content"]
    assert rows[0]["workstream"] == "WORK_CC"


def test_rejected_and_excluded_records_are_never_imported(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    _approve(ledger, fixture["rejected"], state=RECORD_REJECTED)
    _approve(ledger, fixture["excluded"], state=RECORD_EXCLUDED)
    approval = _approval([fixture["rejected"], fixture["excluded"]], store)
    result = _run(
        store, [fixture["rejected"], fixture["excluded"]], approval, ledger, apply=True
    )
    assert result.imported_count == 0
    assert result.status == STATUS_BLOCKED
    codes = {outcome.code for outcome in result.outcomes}
    assert "RECORD_REJECTED" in codes
    assert "RECORD_EXCLUDED" in codes
    assert not store.exists()


def test_duplicate_import_is_idempotent(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    _approve(ledger, fixture["safe_a"])
    approval = _approval([fixture["safe_a"]], store)
    first = _run(store, [fixture["safe_a"]], approval, ledger, apply=True)
    second = _run(store, [fixture["safe_a"]], approval, ledger, apply=True)
    assert first.imported_count == 1
    assert second.imported_count == 0
    assert second.skipped_count == 1
    assert first.total_count == second.total_count == 1
    assert len(_rows(store)) == 1


def test_incremental_refresh_preserves_approval_boundaries(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    _approve(ledger, fixture["safe_a"])
    approval = _approval([fixture["safe_a"], fixture["safe_b"]], store)
    first = _run(store, [fixture["safe_a"], fixture["safe_b"]], approval, ledger, apply=True)
    assert first.imported_count == 1
    assert first.blocked_count == 1

    _approve(ledger, fixture["safe_b"], workstream="WORK_BB")
    second = _run(store, [fixture["safe_a"], fixture["safe_b"]], approval, ledger, apply=True)
    assert second.imported_count == 1
    assert second.skipped_count == 1
    assert second.total_count == 2
    rows = {row["workstream"] for row in _rows(store)}
    assert rows == {"WORK_BC", "WORK_BB"}


def test_workstream_attribution_and_cross_source_boundary(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    _approve(ledger, fixture["safe_a"])
    decision = ledger.decision_for(content_hash=_hash(fixture["safe_a"]))
    assert decision is not None
    mismatch = ledger.evaluate(
        content_hash=_hash(fixture["safe_a"]),
        source_file=str(fixture["safe_b"].resolve()),
    )
    assert mismatch.eligible is False
    assert mismatch.code == "SOURCE_FILE_MISMATCH"

    approval = _approval([fixture["safe_a"]], store)
    result = _run(store, [fixture["safe_a"]], approval, ledger, apply=True)
    assert result.imported_count == 1
    rows = _rows(store)
    assert rows[0]["workstream"] == "WORK_BC"
    assert rows[0]["metadata"]["workstream_attribution"] == "WORK_BC"


def test_end_to_end_preview_then_import_with_fts_and_no_secret(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    _approve(ledger, fixture["safe_a"])
    _approve(ledger, fixture["manual"])
    ledger.record_manual_review(
        ManualReviewDecision(
            record_id=_record_id(fixture["manual"]),
            state=MANUAL_APPROVED,
            reason="OPERATOR_REVIEWED",
            decision_authority="OPERATOR",
            decided_at=AT,
        ),
        AUTH,
    )
    approval = _approval(fixture["all"], store)
    preview = _run(store, fixture["all"], approval, ledger, apply=False)
    assert preview.status == STATUS_PREVIEW
    assert preview.imported_count == 0
    assert not store.exists()

    approved_paths = [fixture["safe_a"], fixture["manual"]]
    approval = _approval(approved_paths, store)
    result = run_partial_import(
        store,
        source_paths=approved_paths,
        source_roots=(fixture["root"],),
        source_approval=approval,
        ledger=ledger,
        indexed_at=OBS,
        apply=True,
        search_probes=(SearchProbe("marker", "safealphamarker"),),
    )
    assert result.status == STATUS_COMPLETE
    assert result.imported_count == 2
    assert result.integrity == "OK"
    assert result.fts_count == 2
    assert result.search[0]["total_count"] >= 1
    rows = _rows(store)
    contents = "\n".join(row["content"] for row in rows)
    assert "hunter2" not in contents
    assert all(row["truth_kind"] == "AGENT_REPORTED" for row in rows)
    assert all(row["authority_scope"] == "NONE" for row in rows)


def test_ledger_approval_error_propagates_without_write(tmp_path):
    fixture = _fixture(tmp_path)
    store = tmp_path / "store.sqlite3"
    ledger = ApprovalLedger()
    path = fixture["secret"]
    record_id = _record_id(path)
    ledger.register_finding(
        SecretFinding(
            finding_id="find-secret",
            record_id=record_id,
            category="PASSWORD",
            severity="HIGH",
            redaction_required=True,
        )
    )
    with pytest.raises(ApprovalError) as exc:
        _approve(ledger, path, record_id=record_id, redaction_required=True)
    assert exc.value.code == "UNRESOLVED_SECRET_FINDING"
    assert not store.exists()
