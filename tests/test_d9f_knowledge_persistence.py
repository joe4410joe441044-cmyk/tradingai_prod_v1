"""Focused D-9F persistence tests: durable Knowledge Evolution store.

Authority contract under test (task section 44):

    Experience Memory      = EVIDENCE_ONLY / REBUILDABLE (NOT authoritative)
    Investigation          = ANALYSIS_ONLY
    Pattern / Finding      = OBSERVATION_ONLY
    Hypothesis             = HYPOTHESIS_ONLY
    Validation             = ANALYSIS_ONLY
    Validated Knowledge    = INFORMATION_ONLY
    Knowledge Promotion    = HUMAN_REVIEW_REQUIRED
    Knowledge Store        = PERSISTENCE_ONLY
    Operational / Execution / Strategy / MM / Canonical Mutation = NONE
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from backend.knowledge_evolution.store import (
    OPERATOR_SCOPE_POLICY_UNRESOLVED,
    SCHEMA_VERSION,
    KnowledgeEvolutionStore,
    KnowledgeStoreError,
    KnowledgeStoreErrorCode,
    review_subject_fingerprint,
    sanitize_text,
)
from backend.knowledge_evolution import (
    AcceptanceCriterion,
    EvidenceStrength,
    ExperienceType,
    FindingStatus,
    HypothesisStatus,
    InvestigationFilter,
    PatternStatus,
    PatternType,
    Relation,
    ReviewDecision,
    ValidationEvidence,
    ValidationMetric,
    ValidationMethod,
    ValidationResult,
    build_finding,
    make_experience,
    make_investigation,
    propose_hypothesis,
    record_human_review,
    run_investigation,
)
from backend.knowledge_evolution.pattern import build_pattern
from backend.knowledge_evolution.validation import evaluate_validation


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _store(tmp_path):
    return KnowledgeEvolutionStore(tmp_path / "knowledge.sqlite3")


def _supported_hypothesis(store, *, statement="a testable hypothesis"):
    h = propose_hypothesis(
        statement=statement,
        validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
    )
    store.create_hypothesis(h)
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.READY_FOR_VALIDATION)
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.VALIDATING)
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.SUPPORTED)
    return h


def _supported_validation(store, h, *, evidence_sample=10, evidence_support=8):
    v = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=evidence_sample,
            support_count=evidence_support,
            counterexample_count=evidence_sample - evidence_support,
            method=ValidationMethod.HISTORICAL_REPLAY,
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    assert v.result is ValidationResult.SUPPORTED
    store.save_validation(v)
    return v


def _approved_review(store, h, v):
    review = record_human_review(
        hypothesis_id=h.hypothesis_id,
        decision=ReviewDecision.APPROVED,
        reviewer="operator",
        reviewed_at="2026-09-05T10:00:00Z",
    )
    store.append_human_review(review, validation=v)
    return review


def _promote(store, h, v, review, **kwargs):
    return store.promote_to_validated_knowledge(
        hypothesis_id=h.hypothesis_id,
        validation_id=v.validation_id,
        review_id=review.review_id,
        version="1.0",
        created_at="2026-09-05T10:01:00Z",
        **kwargs,
    )


def _findings_context(store, question="q"):
    inv = make_investigation(question=question, criterion=InvestigationFilter(symbol="BTCUSDT"))
    store.save_investigation(inv)
    exp = make_experience(
        experience_type=ExperienceType.MARKET_OBSERVATION, symbol="BTCUSDT", summary="obs"
    )
    result = run_investigation(inv, [exp])
    return inv, result


def _raw(db_path):
    connection = sqlite3.connect(str(db_path))
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _tamper_payload(store, table, pk_col, pk_value, mutate):
    with _raw(store.path) as db:
        row = db.execute(f"SELECT payload FROM {table} WHERE {pk_col}=?", (pk_value,)).fetchone()
        payload = json.loads(row[0])
        mutate(payload)
        db.execute(
            f"UPDATE {table} SET payload=? WHERE {pk_col}=?",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")), pk_value),
        )
        db.commit()


# --------------------------------------------------------------------------- #
# Schema / version
# --------------------------------------------------------------------------- #


def test_d9f_01_store_initializes_schema(tmp_path):
    store = _store(tmp_path)
    assert store.schema_version == SCHEMA_VERSION
    assert store.foreign_keys_enabled() is True


def test_d9f_02_schema_version_recognized(tmp_path):
    store = _store(tmp_path)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    assert reopened.schema_version == SCHEMA_VERSION


def test_d9f_03_unknown_schema_fails_closed(tmp_path):
    path = tmp_path / "newer.sqlite3"
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE _schema_meta(key TEXT NOT NULL PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO _schema_meta VALUES('schema_version', '999')")
    db.commit()
    db.close()
    with pytest.raises(KnowledgeStoreError) as exc:
        KnowledgeEvolutionStore(path)
    assert exc.value.code is KnowledgeStoreErrorCode.OPERATOR_ACTION_REQUIRED


def test_d9f_04_foreign_keys_enabled(tmp_path):
    store = _store(tmp_path)
    assert store.foreign_keys_enabled() is True
    # Null (x)  32 hex deterministic IDs contain no SQL-injection risk; FK enforced.
    inv, result = _findings_context(store)
    finding = build_finding(result, statement="obs")
    orphan = finding.__class__(
        finding_id=finding.finding_id,
        investigation_id="investigation:missing",
        statement="orphan",
        supporting_evidence_ids=finding.supporting_evidence_ids,
        counterevidence_ids=finding.counterevidence_ids,
        provenance=finding.provenance,
        status=FindingStatus.OBSERVATION,
    )
    with pytest.raises(KnowledgeStoreError) as exc:
        store.save_finding(orphan)
    assert exc.value.code is KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION


# --------------------------------------------------------------------------- #
# Restart recoverability of every durable type
# --------------------------------------------------------------------------- #


def test_d9f_05_investigation_persists_reloads(tmp_path):
    store = _store(tmp_path)
    inv = make_investigation(question="why did it lag?", criterion=InvestigationFilter(symbol="BTCUSDT"))
    store.save_investigation(inv)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    loaded = reopened.get_investigation(inv.investigation_id)
    assert loaded is not None
    assert loaded.investigation_id == inv.investigation_id
    assert loaded.question == inv.question
    assert loaded.criterion.as_dict() == inv.criterion.as_dict()


def test_d9f_06_pattern_persists_reloads(tmp_path):
    store = _store(tmp_path)
    exp = make_experience(
        experience_type=ExperienceType.TRADE_RESULT, symbol="BTCUSDT", outcome="WIN"
    )
    exp2 = make_experience(
        experience_type=ExperienceType.TRADE_RESULT, symbol="BTCUSDT", outcome="WIN"
    )
    pattern = build_pattern(
        [exp, exp2],
        pattern_type=PatternType.CO_OCCURRENCE,
        description="win-win pattern",
        condition=lambda e: e.symbol == "BTCUSDT",
        outcome=lambda e: e.outcome == "WIN",
    )
    store.save_pattern(pattern)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    loaded = reopened.get_pattern(pattern.pattern_id)
    assert loaded is not None
    assert loaded.pattern_id == pattern.pattern_id
    assert loaded.support_count == 2 and loaded.sample_size == 2


def test_d9f_07_singleton_pattern_remains_singleton(tmp_path):
    store = _store(tmp_path)
    exp = make_experience(
        experience_type=ExperienceType.TRADE_RESULT, symbol="BTCUSDT", outcome="WIN"
    )
    pattern = build_pattern(
        [exp],
        pattern_type=PatternType.CO_OCCURRENCE,
        description="single",
        condition=lambda e: e.symbol == "BTCUSDT",
        outcome=lambda e: e.outcome == "WIN",
    )
    store.save_pattern(pattern)
    loaded = store.get_pattern(pattern.pattern_id)
    assert loaded.status is PatternStatus.SINGLETON
    assert loaded.is_repeated is False
    assert "SINGLE_EVENT_NOT_REPEATED_PATTERN" in loaded.warnings


def test_d9f_08_evidence_strength_categorical_preserved(tmp_path):
    store = _store(tmp_path)
    wins = [
        make_experience(experience_type=ExperienceType.TRADE_RESULT, symbol="S", outcome="WIN")
        for _ in range(6)
    ]
    losses = [
        make_experience(experience_type=ExperienceType.TRADE_RESULT, symbol="S", outcome="LOSS")
        for _ in range(2)
    ]
    pattern = build_pattern(
        list(wins) + list(losses),
        pattern_type=PatternType.CO_OCCURRENCE,
        description="cooccur",
        condition=lambda e: True,
        outcome=lambda e: e.outcome == "WIN",
    )
    store.save_pattern(pattern)
    loaded = store.get_pattern(pattern.pattern_id)
    assert loaded.evidence_strength in {
        EvidenceStrength.STRONG,
        EvidenceStrength.MODERATE,
        EvidenceStrength.WEAK,
        EvidenceStrength.INSUFFICIENT,
    }
    assert isinstance(loaded.evidence_strength, EvidenceStrength)


def test_d9f_09_finding_persists_reloads(tmp_path):
    store = _store(tmp_path)
    inv, result = _findings_context(store)
    finding = build_finding(result, statement="observed pattern")
    store.save_finding(finding)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    loaded = reopened.get_finding(finding.finding_id)
    assert loaded is not None
    assert loaded.finding_id == finding.finding_id
    assert loaded.investigation_id == finding.investigation_id


def test_d9f_10_orphan_finding_rejected(tmp_path):
    store = _store(tmp_path)
    inv, result = _findings_context(store)
    finding = build_finding(result, statement="obs")
    orphan = finding.__class__(
        finding_id=finding.finding_id,
        investigation_id="investigation:missing-investigation",
        statement="orphan",
        supporting_evidence_ids=finding.supporting_evidence_ids,
        counterevidence_ids=finding.counterevidence_ids,
        provenance=finding.provenance,
    )
    with pytest.raises(KnowledgeStoreError) as exc:
        store.save_finding(orphan)
    assert exc.value.code is KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION


def test_d9f_11_hypothesis_persists_reloads(tmp_path):
    store = _store(tmp_path)
    h = propose_hypothesis(
        statement="a durable hypothesis",
        derived_from_finding_ids=("finding:a",),
        validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
    )
    store.create_hypothesis(h)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    loaded = reopened.get_hypothesis(h.hypothesis_id)
    assert loaded is not None
    assert loaded.statement == h.statement
    assert loaded.status is HypothesisStatus.PROPOSED


def test_d9f_12_valid_hypothesis_transition_persists(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    loaded = store.get_hypothesis(h.hypothesis_id)
    assert loaded.status is HypothesisStatus.SUPPORTED
    transitions = store.list_hypothesis_transitions(h.hypothesis_id)
    assert [t["toStatus"] for t in transitions] == [
        "READY_FOR_VALIDATION",
        "VALIDATING",
        "SUPPORTED",
    ]


def test_d9f_13_invalid_hypothesis_transition_rejected(tmp_path):
    store = _store(tmp_path)
    h = propose_hypothesis(statement="no criteria")
    store.create_hypothesis(h)
    with pytest.raises(KnowledgeStoreError) as exc:
        store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.SUPPORTED)
    assert exc.value.code is KnowledgeStoreErrorCode.INVALID_TRANSITION


def test_d9f_14_transition_history_survives_restart(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    before = store.list_hypothesis_transitions(h.hypothesis_id)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    after = reopened.list_hypothesis_transitions(h.hypothesis_id)
    assert before == after
    assert len(after) == 3


def test_d9f_15_validation_persists_reloads(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    store.save_validation(v)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    loaded = reopened.get_validation(v.validation_id)
    assert loaded is not None
    assert loaded.validation_id == v.validation_id
    assert loaded.result is ValidationResult.SUPPORTED


def test_d9f_16_validation_retains_evidence_refs_counts(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=10,
            support_count=8,
            counterexample_count=2,
            method=ValidationMethod.PAPER_RESULTS,
            dataset_references=("paper-run/2026-01", "trace-5"),
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    store.save_validation(v)
    loaded = store.get_validation(v.validation_id)
    assert loaded.evidence.dataset_references == ("paper-run/2026-01", "trace-5")
    assert loaded.sample_size == 10
    assert loaded.support_count == 8
    assert loaded.counterexample_count == 2
    assert loaded.method is ValidationMethod.PAPER_RESULTS


def test_d9f_17_human_review_persists_reloads(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    loaded = reopened.get_human_review(review.review_id)
    assert loaded is not None
    assert loaded.decision is ReviewDecision.APPROVED
    assert loaded.reviewer == "operator"


def test_d9f_18_human_review_append_only(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    # Physical DELETE is forbidden by a SQL trigger.
    with pytest.raises(sqlite3.DatabaseError):
        with _raw(store.path) as db:
            db.execute("DELETE FROM human_reviews WHERE review_id=?", (review.review_id,))
            db.commit()
    # Physical UPDATE is forbidden too.
    with pytest.raises(sqlite3.DatabaseError):
        with _raw(store.path) as db:
            db.execute(
                "UPDATE human_reviews SET decision='REJECTED' WHERE review_id=?",
                (review.review_id,),
            )
            db.commit()


def test_d9f_19_human_review_pins_validation(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    reviews = store.list_human_reviews(h.hypothesis_id)
    assert reviews == ({
        "reviewId": review.review_id,
        "hypothesisId": h.hypothesis_id,
        "validationId": v.validation_id,
        "decision": ReviewDecision.APPROVED.value,
        "reviewer": "operator",
        "reviewedAt": "2026-09-05T10:00:00Z",
        "subjectFingerprint": reviews[0]["subjectFingerprint"],
    },)
    # The review pins ONE validation.  A promotion using the SAME review against a
    # DIFFERENT validation must be rejected.
    other = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=12, support_count=9, counterexample_count=3,
            method=ValidationMethod.HISTORICAL_REPLAY,
            dataset_references=("other-dataset",),
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    store.save_validation(other)
    assert other.validation_id != v.validation_id
    with pytest.raises(KnowledgeStoreError) as exc:
        store.promote_to_validated_knowledge(
            hypothesis_id=h.hypothesis_id, validation_id=other.validation_id,
            review_id=review.review_id, version="1.0", created_at="t",
        )
    assert exc.value.code is KnowledgeStoreErrorCode.REVIEW_VALIDATION_MISMATCH


# --------------------------------------------------------------------------- #
# Review subject fingerprint
# --------------------------------------------------------------------------- #


def test_d9f_20_review_subject_fingerprint_deterministic(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    assert review_subject_fingerprint(h, v) == review_subject_fingerprint(h, v)


def test_d9f_21_changed_hypothesis_invalidates_review(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    _tamper_payload(store, "hypotheses", "hypothesis_id", h.hypothesis_id, lambda p: p.update({"statement": "CHANGED"}))
    with pytest.raises(KnowledgeStoreError) as exc:
        _promote(store, h, v, review)
    assert exc.value.code in {
        KnowledgeStoreErrorCode.STALE_REVIEW,
        KnowledgeStoreErrorCode.CORRUPT_RECORD,
    }


def test_d9f_22_changed_validation_invalidates_review(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    _tamper_payload(
        store, "validations", "validation_id", v.validation_id, lambda p: p.update({"support_count": 3})
    )
    with pytest.raises(KnowledgeStoreError) as exc:
        _promote(store, h, v, review)
    assert exc.value.code in {
        KnowledgeStoreErrorCode.STALE_REVIEW,
        KnowledgeStoreErrorCode.CORRUPT_RECORD,
    }


def test_d9f_23_validated_knowledge_persists_reloads(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    vk = _promote(store, h, v, review)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    loaded = reopened.get_validated_knowledge(vk.knowledge_id)
    assert loaded is not None
    assert loaded.knowledge_id == vk.knowledge_id
    assert loaded.origin_hypothesis_id == h.hypothesis_id


# --------------------------------------------------------------------------- #
# Promotion gates
# --------------------------------------------------------------------------- #


def test_d9f_24_promotion_requires_supported_hypothesis(tmp_path):
    store = _store(tmp_path)
    h = propose_hypothesis(statement="h", validation_criteria=(("X", "AT_LEAST", 1.0),))
    store.create_hypothesis(h)
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.READY_FOR_VALIDATION)
    v = evaluate_validation(
        h,
        evidence=ValidationEvidence(sample_size=10, support_count=8, counterexample_count=2, method=ValidationMethod.HISTORICAL_REPLAY),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    store.save_validation(v)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED, reviewer="operator", reviewed_at="t")
    store.append_human_review(review, validation=v)
    with pytest.raises(KnowledgeStoreError) as exc:
        _promote(store, h, v, review)  # h still VALIDATING (not SUPPORTED)
    assert exc.value.code is KnowledgeStoreErrorCode.PROMOTION_BLOCKED


def test_d9f_25_promotion_requires_supported_validation(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = evaluate_validation(
        h,
        evidence=ValidationEvidence(sample_size=10, support_count=2, counterexample_count=8, method=ValidationMethod.HISTORICAL_REPLAY),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.8),),
    )
    assert v.result is ValidationResult.NOT_SUPPORTED
    store.save_validation(v)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED, reviewer="operator", reviewed_at="t")
    store.append_human_review(review, validation=v)
    with pytest.raises(KnowledgeStoreError) as exc:
        _promote(store, h, v, review)
    assert exc.value.code is KnowledgeStoreErrorCode.PROMOTION_BLOCKED


def test_d9f_26_promotion_requires_approved_human_review(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.REJECTED, reviewer="operator", reviewed_at="t")
    store.append_human_review(review, validation=v)
    with pytest.raises(KnowledgeStoreError) as exc:
        _promote(store, h, v, review)
    assert exc.value.code is KnowledgeStoreErrorCode.REVIEW_NOT_APPROVED


def test_d9f_27_promotion_requires_matching_hypothesis(tmp_path):
    store = _store(tmp_path)
    h1 = _supported_hypothesis(store)
    v1 = _supported_validation(store, h1)
    review1 = _approved_review(store, h1, v1)
    assert store.promote_to_validated_knowledge(
        hypothesis_id=h1.hypothesis_id, validation_id=v1.validation_id,
        review_id=review1.review_id, version="1.0", created_at="t",
    ) is not None
    # A review approved for h1 must NOT promote a DIFFERENT hypothesis h2.
    h2 = _supported_hypothesis(store, statement="a second hypothesis")
    v2 = _supported_validation(store, h2, evidence_sample=14, evidence_support=11)
    with pytest.raises(KnowledgeStoreError) as exc:
        store.promote_to_validated_knowledge(
            hypothesis_id=h2.hypothesis_id, validation_id=v2.validation_id,
            review_id=review1.review_id, version="1.0", created_at="t",
        )
    assert exc.value.code is KnowledgeStoreErrorCode.REVIEW_VALIDATION_MISMATCH


def test_d9f_28_promotion_requires_matching_validation(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    other = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=12, support_count=9, counterexample_count=3,
            method=ValidationMethod.HISTORICAL_REPLAY,
            dataset_references=("other-validation",),
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    store.save_validation(other)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED, reviewer="operator", reviewed_at="t")
    store.append_human_review(review, validation=v)  # review pins v, not other
    with pytest.raises(KnowledgeStoreError) as exc:
        store.promote_to_validated_knowledge(
            hypothesis_id=h.hypothesis_id, validation_id=other.validation_id,
            review_id=review.review_id, version="1.0", created_at="t",
        )
    assert exc.value.code is KnowledgeStoreErrorCode.REVIEW_VALIDATION_MISMATCH


def test_d9f_29_promotion_requires_matching_fingerprint(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    # The stored approval fingerprint was bound to the ORIGINAL review subject.
    # Change the (mutable) persisted hypothesis validation-criteria so the
    # current subject no longer matches -> promotion must be rejected.
    stored = store.list_human_reviews(h.hypothesis_id)[0]["subjectFingerprint"]
    _tamper_payload(
        store,
        "hypotheses",
        "hypothesis_id",
        h.hypothesis_id,
        lambda p: p.update({"validation_criteria": [["SUPPORT_RATIO", "AT_LEAST", 0.9]]}),
    )
    assert store.get_hypothesis(h.hypothesis_id).validation_criteria != h.validation_criteria
    with pytest.raises(KnowledgeStoreError) as exc:
        _promote(store, h, v, review)
    assert exc.value.code is KnowledgeStoreErrorCode.STALE_REVIEW


def test_d9f_30_atomic_promotion_succeeds(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    vk = _promote(store, h, v, review)
    assert isinstance(vk.origin_hypothesis_id, str)
    assert vk.validation_references == (v.validation_id,)
    assert vk.human_review_reference == review.review_id
    assert vk.status.value == "VALIDATED_KNOWN"


def test_d9f_31_failed_promotion_rolls_back(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)  # pins v
    # Attempt to promote using a validation that is NOT pinned by the review.
    other = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=20, support_count=15, counterexample_count=5,
            method=ValidationMethod.HISTORICAL_REPLAY,
            dataset_references=("unpinned-validation",),
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    store.save_validation(other)
    with pytest.raises(KnowledgeStoreError):
        store.promote_to_validated_knowledge(
            hypothesis_id=h.hypothesis_id, validation_id=other.validation_id,
            review_id=review.review_id, version="1.0", created_at="t",
        )
    # No partial Validated Knowledge; only the original list (empty) remains.
    assert store.list_validated_knowledge(h.hypothesis_id) == ()


def test_d9f_32_no_validated_knowledge_without_durable_review(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = record_human_review(hypothesis_id=h.hypothesis_id, decision=ReviewDecision.APPROVED, reviewer="operator", reviewed_at="t")
    # Never persisted in the store -> promotion must fail (no durable approval).
    with pytest.raises(KnowledgeStoreError) as exc:
        store.promote_to_validated_knowledge(
            hypothesis_id=h.hypothesis_id, validation_id=v.validation_id,
            review_id=review.review_id, version="1.0", created_at="t",
        )
    assert exc.value.code is KnowledgeStoreErrorCode.NOT_FOUND
    assert store.list_validated_knowledge(h.hypothesis_id) == ()


# --------------------------------------------------------------------------- #
# Idempotency / conflict / corruption
# --------------------------------------------------------------------------- #


def test_d9f_33_identical_deterministic_write_idempotent(tmp_path):
    store = _store(tmp_path)
    inv, result = _findings_context(store)
    finding = build_finding(result, statement="obs")
    store.save_finding(finding)
    store.save_finding(finding)  # identical -> idempotent, no error
    assert store.get_finding(finding.finding_id) is not None


def test_d9f_34_conflicting_duplicate_fails_closed(tmp_path):
    store = _store(tmp_path)
    inv, result = _findings_context(store)
    finding = build_finding(result, statement="obs")
    store.save_finding(finding)
    conflict = finding.__class__(
        finding_id=finding.finding_id,
        investigation_id=finding.investigation_id,
        statement="DIFFERENT",
        supporting_evidence_ids=finding.supporting_evidence_ids,
        counterevidence_ids=finding.counterevidence_ids,
        provenance=finding.provenance,
    )
    with pytest.raises(KnowledgeStoreError) as exc:
        store.save_finding(conflict)
    assert exc.value.code is KnowledgeStoreErrorCode.DUPLICATE_CONFLICT


def test_d9f_35_corrupted_enum_fails_safe(tmp_path):
    store = _store(tmp_path)
    inv, result = _findings_context(store)
    finding = build_finding(result, statement="obs")
    store.save_finding(finding)
    _tamper_payload(
        store, "findings", "finding_id", finding.finding_id, lambda p: p.update({"status": "NOT_A_REAL_ENUM"})
    )
    with pytest.raises(KnowledgeStoreError) as exc:
        store.get_finding(finding.finding_id)
    assert exc.value.code is KnowledgeStoreErrorCode.CORRUPT_RECORD


# --------------------------------------------------------------------------- #
# Boundedness
# --------------------------------------------------------------------------- #


def test_d9f_36_bounded_reads(tmp_path):
    store = KnowledgeEvolutionStore(tmp_path / "bounded.sqlite3", max_read_limit=5)
    for i in range(6):
        h = propose_hypothesis(statement=f"hypothesis {i}", validation_criteria=(("X", "AT_LEAST", 1.0),))
        store.create_hypothesis(h)
    listed = store.list_hypothesis_transitions(h.hypothesis_id, limit=100)  # clamped to 5
    assert isinstance(listed, tuple)
    assert len(listed) <= 5
    with pytest.raises(KnowledgeStoreError):
        store.list_hypothesis_transitions(h.hypothesis_id, limit=0)


def test_d9f_37_bounded_collections(tmp_path):
    store = _store(tmp_path)
    _, result = _findings_context(store)
    finding = build_finding(result, statement="obs")
    over = finding.__class__(
        finding_id=finding.finding_id,
        investigation_id=finding.investigation_id,
        statement="obs",
        supporting_evidence_ids=tuple([f"e{i}" for i in range(300)]),
        counterevidence_ids=(),
        provenance=finding.provenance,
    )
    with pytest.raises(KnowledgeStoreError) as exc:
        store.save_finding(over)
    assert exc.value.code is KnowledgeStoreErrorCode.CORRUPT_RECORD


# --------------------------------------------------------------------------- #
# Security / authority
# --------------------------------------------------------------------------- #


def test_d9f_38_free_text_sanitized(tmp_path):
    store = _store(tmp_path)
    inv = make_investigation(question="normal question", criterion=InvestigationFilter(symbol="BTCUSDT"))
    store.save_investigation(inv)
    assert store.get_investigation(inv.investigation_id).question == "normal question"
    secret_inv = make_investigation(question="my api_key=supersecret", criterion=InvestigationFilter(symbol="BTCUSDT"))
    store.save_investigation(secret_inv)
    assert store.get_investigation(secret_inv.investigation_id).question == "[REDACTED]"
    with pytest.raises(ValueError):
        sanitize_text("bad\x00value", limit=20)


def test_d9f_39_no_raw_secret_fields(tmp_path):
    store = _store(tmp_path)
    secret_inv = make_investigation(question="api_key=supersecret123", criterion=InvestigationFilter(symbol="BTCUSDT"))
    store.save_investigation(secret_inv)
    with _raw(store.path) as db:
        payload = db.execute("SELECT payload FROM investigations").fetchall()[0][0]
    assert "supersecret123" not in payload


def test_d9f_40_experience_not_authoritative(tmp_path):
    store = _store(tmp_path)
    assert store.has_experience_table() is False
    # TradingTraceStore remains authoritative.
    assert store.authoritative_authority_report()["TradingTraceStore"] == "AUTHORITATIVE_HISTORICAL_TRACE"
    assert store.authoritative_authority_report()["ExperienceRecord"] == "EVIDENCE_ONLY_REBUILDABLE"


def test_d9f_41_no_trading_mutation_interfaces(tmp_path):
    store = _store(tmp_path)
    runtime_mutation_verbs = {
        "start_trading", "stop_trading", "place_order", "submit_order", "cancel_order",
        "close_position", "set_mode", "set_leverage", "set_risk", "update_strategy",
        "write_canonical", "emergency", "set_auto_trade", "enable_live", "disable_live",
        "mutate_strategy", "mutate_mm", "execute_order",
    }
    methods = {name for name in dir(store) if not name.startswith("_") and callable(getattr(store, name))}
    assert not (methods & runtime_mutation_verbs)
    # Store is PERSISTENCE_ONLY; it never carries a trading authority.
    assert store.evidence_authority() == "PERSISTENCE_ONLY"
    assert store.authoritative_authority_report()["Operational"] == "NONE"
    assert store.authoritative_authority_report()["Canonical"] == "NONE"


def test_d9f_42_restart_recovery_full_chain(tmp_path):
    store = _store(tmp_path)
    inv, result = _findings_context(store, question="q42")
    store.save_investigation(inv)
    finding = build_finding(result, statement="obs")
    store.save_finding(finding)
    pattern = build_pattern(
        [make_experience(experience_type=ExperienceType.TRADE_RESULT, symbol="BTCUSDT", outcome="WIN"),
         make_experience(experience_type=ExperienceType.TRADE_RESULT, symbol="BTCUSDT", outcome="WIN")],
        pattern_type=PatternType.CO_OCCURRENCE,
        description="p42",
        condition=lambda e: True,
        outcome=lambda e: e.outcome == "WIN",
    )
    store.save_pattern(pattern)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    vk = _promote(store, h, v, review)
    store.close()
    reopened = KnowledgeEvolutionStore(store.path)
    assert reopened.get_investigation(inv.investigation_id) is not None
    assert reopened.get_finding(finding.finding_id) is not None
    assert reopened.get_pattern(pattern.pattern_id) is not None
    assert reopened.get_hypothesis(h.hypothesis_id).status is HypothesisStatus.SUPPORTED
    assert len(reopened.list_hypothesis_transitions(h.hypothesis_id)) == 3
    assert reopened.get_validation(v.validation_id) is not None
    assert reopened.get_human_review(review.review_id) is not None
    assert reopened.get_validated_knowledge(vk.knowledge_id) is not None


def test_d9f_43_store_unavailable_does_not_gain_authority(tmp_path):
    # A persistence failure must be typed/isolated (FAIL_CLOSED), never a
    # runtime authority.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    with pytest.raises(KnowledgeStoreError) as exc:
        KnowledgeEvolutionStore(blocker / "knowledge.sqlite3")
    assert exc.value.code is KnowledgeStoreErrorCode.STORE_UNAVAILABLE
    assert not hasattr(KnowledgeEvolutionStore, "start")
    assert not hasattr(KnowledgeEvolutionStore, "restart_trading")


def test_d9f_44_validated_knowledge_cannot_write_canonical(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    vk = _promote(store, h, v, review)
    assert vk.can_write_canonical is False
    assert not hasattr(vk, "write_canonical")


def test_d9f_45_validated_knowledge_no_strategy_exec_mm_mutation(tmp_path):
    store = _store(tmp_path)
    h = _supported_hypothesis(store)
    v = _supported_validation(store, h)
    review = _approved_review(store, h, v)
    vk = _promote(store, h, v, review)
    assert vk.strategy_mutation_authority.value == "NONE"
    assert vk.execution_authority.value == "NONE"
    assert vk.mutation_authority.value == "NONE"


def test_d9f_operator_scope_policy_unresolved(tmp_path):
    store = _store(tmp_path)
    inv = make_investigation(question="scope", criterion=InvestigationFilter(symbol="BTCUSDT"))
    store.save_investigation(inv)
    with _raw(store.path) as db:
        row = db.execute(
            "SELECT scope_policy FROM investigations WHERE investigation_id=?",
            (inv.investigation_id,),
        ).fetchone()
    assert row[0] == OPERATOR_SCOPE_POLICY_UNRESOLVED
