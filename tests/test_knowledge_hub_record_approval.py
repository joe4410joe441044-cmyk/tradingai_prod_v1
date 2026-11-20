"""BC record-level approval, disposition, redaction, and manual-review tests."""

from __future__ import annotations

import pytest

from backend.knowledge_hub.record_approval import (
    ApprovalError,
    ApprovalLedger,
    index_manifest_records,
    seed_pending_findings,
    seed_pending_manual_reviews,
    FINDING_EXCLUDED,
    FINDING_FALSE_POSITIVE_REVIEWED,
    FINDING_PENDING,
    FINDING_REDACTED,
    FindingDisposition,
    MANUAL_APPROVED,
    MANUAL_NOT_REQUIRED,
    MANUAL_PENDING,
    ManualReviewDecision,
    OPERATOR_DECISION_SCHEMA_VERSION,
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
    authorization_id="auth-bc-final-1",
    authority="OPERATOR",
    issued_at=AT,
)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _finding(finding_id="find_1", record_id="rec_a", **overrides):
    values = {
        "finding_id": finding_id,
        "record_id": record_id,
        "category": "PASSWORD",
        "severity": "HIGH",
        "redaction_required": True,
        "manual_review_required": False,
        "source_file": "/tmp/source.md",
    }
    values.update(overrides)
    return SecretFinding(**values)


def _decision(content_hash=HASH_A, state=RECORD_APPROVED, **overrides):
    values = {
        "record_id": "rec_a",
        "content_hash": content_hash,
        "state": state,
        "decision_authority": "OPERATOR",
        "decided_at": AT,
        "source_file": "/tmp/source.md",
        "workstream": "WORK_BC",
        "manual_review_state": MANUAL_NOT_REQUIRED,
        "reason": "TEST_EXPLICIT_DECISION",
    }
    values.update(overrides)
    return RecordDecision(**values)


def _proposed():
    return {
        "schema_version": "tradingai-bc11e7e-operator-decisions/v1",
        "task_id": "TRADINGAI-WORK-BC-11E-7E-OPERATOR-PRIORITY-390-APPROVAL-DECISION-1",
        "authoritative": False,
        "proposed_decision_artifact": True,
        "entries": [
            {
                "recordId": "xwsrc_a",
                "contentHash": HASH_A,
                "sourceWorkstream": "WORK_BC",
                "source_paths": ["/tmp/source.md"],
                "redactionRequired": False,
                "manualReviewRequired": False,
            }
        ],
    }


def _operator():
    return {
        "schema_version": OPERATOR_DECISION_SCHEMA_VERSION,
        "authoritative": True,
        "authorization_id": AUTH.authorization_id,
        "decisions": [
            {
                "recordId": "xwsrc_a",
                "contentHash": HASH_A,
                "decision": "APPROVE",
                "reason": "OPERATOR_REVIEWED",
            }
        ],
    }


def test_finding_disposition_requires_explicit_authorization():
    ledger = ApprovalLedger()
    ledger.register_finding(_finding())
    disposition = FindingDisposition(
        finding_id="find_1",
        record_id="rec_a",
        category="PASSWORD",
        disposition=FINDING_REDACTED,
        decision_authority="",
        decided_at=AT,
    )
    with pytest.raises(ApprovalError) as exc:
        ledger.dispose_finding(disposition, None)
    assert exc.value.code == "AUTHORIZATION_REQUIRED"


def test_resolving_disposition_records_authority_time_and_provenance():
    ledger = ApprovalLedger()
    ledger.register_finding(_finding())
    recorded = ledger.dispose_finding(
        FindingDisposition(
            finding_id="find_1",
            record_id="rec_a",
            category="PASSWORD",
            disposition=FINDING_FALSE_POSITIVE_REVIEWED,
            decision_authority="OPERATOR",
            decided_at=AT,
            provenance={"review": "manual"},
        ),
        AUTH,
    )
    assert recorded.decision_authority == "OPERATOR"
    event = ledger.audit_events()[-1]
    assert event["event"] == "FINDING_DISPOSITION"
    assert event["decision_authority"] == "OPERATOR"
    assert event["decided_at"] == AT
    assert event["resolved"] is True
    assert event["provenance"] == {"review": "manual"}
    assert "hunter2" not in repr(ledger.snapshot())


def test_pending_finding_keeps_record_blocked():
    ledger = ApprovalLedger()
    ledger.register_finding(_finding())
    ledger.dispose_finding(
        FindingDisposition(
            finding_id="find_1",
            record_id="rec_a",
            category="PASSWORD",
            disposition=FINDING_PENDING,
            decision_authority="PENDING_OPERATOR_REVIEW",
            decided_at=AT,
        )
    )
    with pytest.raises(ApprovalError) as exc:
        ledger.decide_record(_decision(), AUTH)
    assert exc.value.code == "UNRESOLVED_SECRET_FINDING"


def test_excluded_finding_blocks_record_approval():
    ledger = ApprovalLedger()
    ledger.register_finding(_finding())
    ledger.dispose_finding(
        FindingDisposition(
            finding_id="find_1",
            record_id="rec_a",
            category="PASSWORD",
            disposition=FINDING_EXCLUDED,
            decision_authority="OPERATOR",
            decided_at=AT,
        ),
        AUTH,
    )
    with pytest.raises(ApprovalError) as exc:
        ledger.decide_record(_decision(), AUTH)
    assert exc.value.code == "FINDING_EXCLUDED"


def test_redaction_preparation_is_not_approval_and_preserves_useful_text():
    original = "TASK_ID: synthetic\npassword=hunter2\nkeep this useful sentence\n"
    candidates = {}
    for name in ("not_approved", "approved"):
        ledger = ApprovalLedger()
        ledger.register_finding(_finding(record_id=name))
        candidate = prepare_redaction(name, original, ["find_1"])
        candidates[name] = (ledger, candidate)
        assert ledger.snapshot()["redactions"] == []
        assert not ledger.snapshot()["records"]
        assert "hunter2" not in candidate.sanitized_content
        assert "keep this useful sentence" in candidate.sanitized_content
        assert candidate.original_content_hash != candidate.sanitized_content_hash
    assert original == "TASK_ID: synthetic\npassword=hunter2\nkeep this useful sentence\n"


def test_redaction_requires_disposition_and_explicit_approval():
    ledger = ApprovalLedger()
    ledger.register_finding(_finding())
    candidate = prepare_redaction("rec_a", "password=hunter2\nkeep", ["find_1"])
    approval = RedactionApproval(
        record_id="rec_a",
        original_content_hash=candidate.original_content_hash,
        sanitized_content_hash=candidate.sanitized_content_hash,
        finding_ids=("find_1",),
        method="MATCHED_SPAN_REDACTION",
        decision_authority="OPERATOR",
        decided_at=AT,
    )
    with pytest.raises(ApprovalError) as exc:
        ledger.record_redaction(approval, AUTH)
    assert exc.value.code == "REDACTION_FINDING_NOT_RESOLVED"

    ledger.dispose_finding(
        FindingDisposition(
            finding_id="find_1",
            record_id="rec_a",
            category="PASSWORD",
            disposition=FINDING_REDACTED,
            decision_authority="OPERATOR",
            decided_at=AT,
        ),
        AUTH,
    )
    with pytest.raises(ApprovalError) as exc:
        ledger.record_redaction(approval, None)
    assert exc.value.code == "AUTHORIZATION_REQUIRED"
    ledger.record_redaction(approval, AUTH)
    decision = _decision(
        redaction_required=True,
        sanitized_content_hash=candidate.sanitized_content_hash,
    )
    ledger.decide_record(decision, AUTH)
    eligibility = ledger.evaluate(content_hash=HASH_A)
    assert eligibility.eligible is True
    assert eligibility.redaction_required is True
    assert eligibility.sanitized_content_hash == candidate.sanitized_content_hash


def test_manual_review_pending_blocks_until_explicit_approval():
    ledger = ApprovalLedger()
    ledger.register_finding(
        _finding(redaction_required=False, manual_review_required=True)
    )
    ledger.dispose_finding(
        FindingDisposition(
            finding_id="find_1",
            record_id="rec_a",
            category="PASSWORD",
            disposition=FINDING_FALSE_POSITIVE_REVIEWED,
            decision_authority="OPERATOR",
            decided_at=AT,
        ),
        AUTH,
    )
    with pytest.raises(ApprovalError) as exc:
        ledger.decide_record(
            _decision(manual_review_state=MANUAL_PENDING, reason="REVIEW_OUTSTANDING"),
            AUTH,
        )
    assert exc.value.code == "MANUAL_REVIEW_PENDING"

    ledger.record_manual_review(
        ManualReviewDecision(
            record_id="rec_a",
            state=MANUAL_APPROVED,
            reason="OPERATOR_CONFIRMED_NOT_A_SECRET",
            decision_authority="OPERATOR",
            decided_at=AT,
            source_provenance={"source": "/tmp/source.md"},
        ),
        AUTH,
    )
    ledger.decide_record(_decision(), AUTH)
    assert ledger.evaluate(content_hash=HASH_A).eligible is True


def test_source_file_approval_alone_is_not_record_approval():
    ledger = ApprovalLedger()
    result = ledger.evaluate(content_hash=HASH_A, source_file="/tmp/source.md")
    assert result.eligible is False
    assert result.code == "RECORD_NOT_APPROVED"


def test_proposed_decision_artifact_is_not_applied_without_operator_decision():
    ledger = ApprovalLedger()
    result = ledger.apply_operator_decisions(_proposed(), None, AUTH)
    assert result["status"] == "NO_AUTHORITATIVE_OPERATOR_DECISION"
    assert result["applied"] == 0
    assert result["import_ready"] is False
    assert ledger.decision_for(content_hash=HASH_A) is None
    assert ledger.evaluate(content_hash=HASH_A).eligible is False


def test_non_authoritative_operator_artifact_is_rejected():
    ledger = ApprovalLedger()
    artifact = _operator()
    artifact["authoritative"] = False
    with pytest.raises(ApprovalError) as exc:
        ledger.apply_operator_decisions(_proposed(), artifact, AUTH)
    assert exc.value.code == "OPERATOR_DECISION_NOT_AUTHORITATIVE"


def test_explicit_operator_application_is_idempotent_and_audited():
    ledger = ApprovalLedger()
    first = ledger.apply_operator_decisions(_proposed(), _operator(), AUTH)
    assert first["status"] == "APPLIED"
    assert first["applied"] == 1
    assert first["import_ready"] is False
    second = ledger.apply_operator_decisions(_proposed(), _operator(), AUTH)
    assert second["status"] == "ALREADY_APPLIED"
    assert second["skipped"] == 1
    decision = ledger.decision_for(content_hash=HASH_A)
    assert decision is not None
    assert decision.state == RECORD_APPROVED
    assert decision.decision_authority == "OPERATOR"
    assert decision.decided_at == AT
    assert ledger.evaluate(content_hash=HASH_A).eligible is True
    assert sum(1 for event in ledger.audit_events() if event["event"] == "RECORD_DECISION") == 1


def test_operator_application_rejects_duplicate_conflicting_and_unknown_records():
    ledger = ApprovalLedger()
    duplicate = _operator()
    duplicate["decisions"].append(
        {"recordId": "xwsrc_a", "contentHash": HASH_A, "decision": "REJECT"}
    )
    with pytest.raises(ApprovalError) as exc:
        ledger.apply_operator_decisions(_proposed(), duplicate, AUTH)
    assert exc.value.code == "DUPLICATE_OPERATOR_DECISION"

    unknown = _operator()
    unknown["decisions"] = [
        {"recordId": "xwsrc_missing", "contentHash": HASH_B, "decision": "APPROVE"}
    ]
    with pytest.raises(ApprovalError) as exc:
        ledger.apply_operator_decisions(_proposed(), unknown, AUTH)
    assert exc.value.code == "PROPOSED_RECORD_NOT_FOUND"


def test_authorization_scope_is_enforced():
    scoped = OperatorAuthorization(
        authorization_id="auth-scope",
        authority="OPERATOR",
        issued_at=AT,
        scope=frozenset({"other-record"}),
    )
    ledger = ApprovalLedger()
    with pytest.raises(ApprovalError) as exc:
        ledger.decide_record(_decision(), scoped)
    assert exc.value.code == "AUTHORIZATION_SCOPE_DENIED"


def test_rejected_and_excluded_records_are_not_eligible():
    ledger = ApprovalLedger()
    ledger.decide_record(_decision(state=RECORD_REJECTED), AUTH)
    assert ledger.evaluate(content_hash=HASH_A).code == "RECORD_REJECTED"
    ledger.decide_record(_decision(state=RECORD_EXCLUDED), AUTH)
    assert ledger.evaluate(content_hash=HASH_A).code == "RECORD_EXCLUDED"


def test_existing_evidence_seeds_pending_state_only():
    manifest = {
        "records": [
            {
                "recordId": "xwsrc_seed",
                "contentHash": HASH_B,
                "source_paths": ["/tmp/seed.md"],
                "sourceWorkstream": "WORK_BC",
            }
        ]
    }
    index = index_manifest_records(manifest)
    ledger = ApprovalLedger()
    findings = [
        {
            "finding_id": "find_seed",
            "contentHash": HASH_B,
            "secret_type": "PASSWORD",
            "severity": "HIGH",
        }
    ]
    queue = [
        {
            "contentHash": HASH_B,
            "review_classification": "POSSIBLE_FALSE_POSITIVE",
        }
    ]
    assert seed_pending_findings(ledger, findings, index) == ("find_seed",)
    assert seed_pending_manual_reviews(ledger, queue, index) == ("xwsrc_seed",)
    snapshot = ledger.snapshot()
    assert snapshot["records"] == []
    assert snapshot["dispositions"][0]["disposition"] == FINDING_PENDING
    assert snapshot["manual_review"][0]["state"] == MANUAL_PENDING
    result = ledger.evaluate(content_hash=HASH_B, record_id="xwsrc_seed")
    assert result.eligible is False
    assert result.code == "RECORD_NOT_APPROVED"
