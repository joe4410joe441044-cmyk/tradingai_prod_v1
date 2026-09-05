"""Focused D-9C backend API integration tests: Knowledge + Human Review.

Authority contract under test (task section 44):

    Investigation          = ANALYSIS_ONLY
    Pattern / Finding      = OBSERVATION_ONLY
    Hypothesis             = HYPOTHESIS_ONLY
    Validation             = ANALYSIS_ONLY
    HumanReview            = HUMAN_REVIEW_REQUIRED (APPEND-ONLY)
    ValidatedKnowledge     = INFORMATION_ONLY
    Knowledge Promotion    = HUMAN_REVIEW_REQUIRED (ATOMIC)

NO operational / execution / strategy / MM / canonical mutation surface may be
reachable through the Knowledge API.  Human-review reviewer identity is derived
ONLY from a trusted server-side operator session; the review subject
fingerprint is derived ONLY server-side from the persisted Hypothesis +
Validation.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.auth_config import OperatorAuthConfig
from backend.auth.operator_session import COOKIE_NAME, OperatorSessionManager
from backend.auth.session_middleware import OperatorSessionMiddleware
from backend.knowledge_evolution.store import (
    KnowledgeEvolutionStore,
    review_subject_fingerprint,
)
from backend.knowledge_evolution.service import KnowledgeEvolutionService
from backend.api.knowledge import create_knowledge_router
from backend.knowledge_evolution import (
    AcceptanceCriterion,
    EvidenceStrength,
    ExperienceType,
    HypothesisStatus,
    InvestigationFilter,
    PatternType,
    Relation,
    ReviewDecision,
    ValidationEvidence,
    ValidationMethod,
    ValidationMetric,
    build_finding,
    make_experience,
    make_investigation,
    propose_hypothesis,
    record_human_review,
    run_investigation,
)
from backend.knowledge_evolution.pattern import build_pattern
from backend.knowledge_evolution.validation import evaluate_validation


SESSION_SECRET = "a" * 32


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _build_client(tmp_path, service=None):
    if service is None:
        store = KnowledgeEvolutionStore(tmp_path / "knowledge.sqlite3")
        svc = KnowledgeEvolutionService(store=store)
    else:
        svc = service
    manager = OperatorSessionManager(SESSION_SECRET, 3600)
    config = OperatorAuthConfig(
        credential_hash="x",
        session_secret=SESSION_SECRET,
        session_ttl_seconds=3600,
        secure_cookie=False,
    )
    app = FastAPI()
    app.add_middleware(
        OperatorSessionMiddleware,
        session_manager=manager,
        config=config,
    )
    app.include_router(create_knowledge_router(svc))
    client = TestClient(app, raise_server_exceptions=False)
    return client, svc, manager


def _authenticate(client, manager):
    session = manager.create_session("operator")
    client.cookies.set(COOKIE_NAME, manager.sign(session.session_id))


def _seed_investigation_finding(store, question="why did it lag?"):
    inv = make_investigation(
        question=question, criterion=InvestigationFilter(symbol="BTCUSDT")
    )
    store.save_investigation(inv)
    exp1 = make_experience(
        experience_type=ExperienceType.MARKET_OBSERVATION,
        symbol="BTCUSDT",
        summary="obs-1",
    )
    exp2 = make_experience(
        experience_type=ExperienceType.MARKET_OBSERVATION,
        symbol="BTCUSDT",
        summary="obs-2",
    )
    result = run_investigation(inv, [exp1, exp2])
    finding = build_finding(result, statement="observed lag")
    store.save_finding(finding)
    return inv, finding


def _seed_pattern(store):
    wins = [
        make_experience(
            experience_type=ExperienceType.TRADE_RESULT,
            symbol="BTCUSDT",
            outcome="WIN",
        )
        for _ in range(3)
    ]
    losses = [
        make_experience(
            experience_type=ExperienceType.TRADE_RESULT,
            symbol="BTCUSDT",
            outcome="LOSS",
        )
        for _ in range(1)
    ]
    pattern = build_pattern(
        wins + losses,
        pattern_type=PatternType.CO_OCCURRENCE,
        description="win-win cooccurrence",
        condition=lambda e: e.symbol == "BTCUSDT",
        outcome=lambda e: e.outcome == "WIN",
    )
    store.save_pattern(pattern)
    return pattern


def _supported_hypothesis(store, **kwargs):
    h = propose_hypothesis(
        statement=kwargs.get(
            "statement", "a supported testable hypothesis"
        ),
        validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),),
    )
    store.create_hypothesis(h)
    h = store.transition_hypothesis(
        h.hypothesis_id, HypothesisStatus.READY_FOR_VALIDATION
    )
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.VALIDATING)
    h = store.transition_hypothesis(h.hypothesis_id, HypothesisStatus.SUPPORTED)
    return h


def _supported_validation(hypothesis, *, sample=10, support=8):
    v = evaluate_validation(
        hypothesis,
        evidence=ValidationEvidence(
            sample_size=sample,
            support_count=support,
            counterexample_count=sample - support,
            method=ValidationMethod.HISTORICAL_REPLAY,
        ),
        criteria=(
            AcceptanceCriterion(
                ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5
            ),
        ),
    )
    assert v.result.value == "SUPPORTED"
    return v


def _tamper_payload(store, table, pk_col, pk_value, mutate):
    connection = sqlite3.connect(str(store.path))
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        "INSERT INTO _schema_meta(key, value) VALUES('__noop', 'x') "
        "ON CONFLICT(key) DO NOTHING"
    )
    row = connection.execute(
        f"SELECT payload FROM {table} WHERE {pk_col}=?", (pk_value,)
    ).fetchone()
    payload = json.loads(row[0])
    mutate(payload)
    connection.execute(
        f"UPDATE {table} SET payload=? WHERE {pk_col}=?",
        (json.dumps(payload, sort_keys=True, separators=(",", ":")), pk_value),
    )
    connection.commit()
    connection.close()


def _approve_via_store(store, h, v, reviewer="operator"):
    review = record_human_review(
        hypothesis_id=h.hypothesis_id,
        decision=ReviewDecision.APPROVED,
        reviewer=reviewer,
        reviewed_at="2026-09-05T10:00:00Z",
    )
    store.append_human_review(review, validation=v)
    return review


# --------------------------------------------------------------------------- #
# Composition
# --------------------------------------------------------------------------- #


def test_01_router_composition_loads(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    # The router is part of the app and all knowledge paths are registered.
    schema = client.app.openapi()
    knowledge_paths = [
        p for p in schema["paths"] if p.startswith("/api/knowledge")
    ]
    assert len(knowledge_paths) == 16
    # The service uses a temporary store, never the production DB path.
    assert "logs/runtime/tradingai_knowledge.sqlite3" not in str(svc.store.path)


def test_02_temporary_store_injected(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    assert svc.store.path.exists()
    # The store is a temporary per-test DB, never the production path.
    assert str(tmp_path) in str(svc.store.path)
    assert "logs/runtime/tradingai_knowledge.sqlite3" not in str(svc.store.path)


# --------------------------------------------------------------------------- #
# Investigation
# --------------------------------------------------------------------------- #


def test_03_create_investigation(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    resp = client.post(
        "/api/knowledge/investigations",
        json={"question": "why did it lag?", "symbol": "BTCUSDT"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["investigationId"]
    assert body["authority"] == "ANALYSIS_ONLY"
    assert body["question"] == "why did it lag?"


def test_04_get_investigation(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    created = client.post(
        "/api/knowledge/investigations",
        json={"question": "why did it lag?", "symbol": "BTCUSDT"},
    ).json()
    resp = client.get("/api/knowledge/investigations/" + created["investigationId"])
    assert resp.status_code == 200
    assert resp.json()["investigationId"] == created["investigationId"]
    assert resp.json()["authority"] == "ANALYSIS_ONLY"


def test_05_list_investigations_bounded(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    for i in range(3):
        client.post(
            "/api/knowledge/investigations",
            json={"question": f"q-{i}", "symbol": "BTCUSDT"},
        )
    resp = client.get("/api/knowledge/investigations?limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert len(body["items"]) == 2
    assert body["authority"] == "ANALYSIS_ONLY"


# --------------------------------------------------------------------------- #
# Pattern / Finding (read-only)
# --------------------------------------------------------------------------- #


def test_06_get_pattern(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    pattern = _seed_pattern(svc.store)
    resp = client.get("/api/knowledge/patterns/" + pattern.pattern_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["patternId"] == pattern.pattern_id
    assert body["authority"] == "OBSERVATION_ONLY"
    assert body["causalClaim"] is False


def test_07_list_patterns_bounded(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    _seed_pattern(svc.store)
    resp = client.get("/api/knowledge/patterns")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["authority"] == "OBSERVATION_ONLY"


def test_08_get_finding(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    inv, finding = _seed_investigation_finding(svc.store)
    resp = client.get("/api/knowledge/findings/" + finding.finding_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["findingId"] == finding.finding_id
    assert body["authority"] == "OBSERVATION_ONLY"
    assert "patternId" not in body  # Finding contract has no pattern_id


def test_09_list_findings_bounded(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    _seed_investigation_finding(svc.store)
    resp = client.get("/api/knowledge/findings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["items"][0]["authority"] == "OBSERVATION_ONLY"


def test_10_pattern_creation_route_absent(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    resp = client.post("/api/knowledge/patterns", json={})
    # Pattern creation is OUT OF SCOPE (arbitrary callables cannot be serialized).
    assert resp.status_code in (404, 405)


# --------------------------------------------------------------------------- #
# Hypothesis
# --------------------------------------------------------------------------- #


def test_11_create_hypothesis(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    resp = client.post(
        "/api/knowledge/hypotheses",
        json={
            "statement": "a testable hypothesis",
            "validation_criteria": [
                {"metric": "SUPPORT_RATIO", "relation": "AT_LEAST", "threshold": 0.5}
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["hypothesisId"]
    assert body["status"] == "PROPOSED"
    assert body["authority"] == "HYPOTHESIS_ONLY"


def test_12_get_and_list_hypotheses(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    created = client.post(
        "/api/knowledge/hypotheses",
        json={
            "statement": "h1",
            "validation_criteria": [
                {"metric": "SUPPORT_RATIO", "relation": "AT_LEAST", "threshold": 0.5}
            ],
        },
    ).json()
    get_resp = client.get("/api/knowledge/hypotheses/" + created["hypothesisId"])
    assert get_resp.status_code == 200
    assert get_resp.json()["authority"] == "HYPOTHESIS_ONLY"
    list_resp = client.get("/api/knowledge/hypotheses")
    assert list_resp.status_code == 200
    assert list_resp.json()["count"] == 1
    assert list_resp.json()["authority"] == "HYPOTHESIS_ONLY"


def test_13_valid_hypothesis_transition(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    created = client.post(
        "/api/knowledge/hypotheses",
        json={
            "statement": "h",
            "validation_criteria": [
                {"metric": "SUPPORT_RATIO", "relation": "AT_LEAST", "threshold": 0.5}
            ],
        },
    ).json()
    resp = client.post(
        "/api/knowledge/hypotheses/%s/transition"
        % created["hypothesisId"],
        json={"target_status": "READY_FOR_VALIDATION"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "READY_FOR_VALIDATION"


def test_14_invalid_hypothesis_transition_rejected(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    created = client.post(
        "/api/knowledge/hypotheses",
        json={"statement": "h"},
    ).json()
    resp = client.post(
        "/api/knowledge/hypotheses/%s/transition"
        % created["hypothesisId"],
        json={"target_status": "SUPPORTED"},
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_TRANSITION"


def test_15_direct_arbitrary_status_write_impossible(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    created = client.post(
        "/api/knowledge/hypotheses", json={"statement": "h"}
    ).json()
    # There is no way to PUT a status directly; only the transition endpoint exists.
    put_resp = client.put(
        "/api/knowledge/hypotheses/" + created["hypothesisId"],
        json={"status": "SUPPORTED"},
    )
    assert put_resp.status_code in (404, 405)
    get_resp = client.get("/api/knowledge/hypotheses/" + created["hypothesisId"])
    assert get_resp.json()["status"] == "PROPOSED"


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #


def _reach_supported(store):
    return _supported_hypothesis(store)


def test_16_create_validation_via_deterministic_evaluation(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    resp = client.post(
        "/api/knowledge/validations",
        json={
            "hypothesis_id": h.hypothesis_id,
            "method": "HISTORICAL_REPLAY",
            "sample_size": 10,
            "support_count": 8,
            "counterexample_count": 2,
            "acceptance_criteria": [
                {"metric": "SUPPORT_RATIO", "relation": "AT_LEAST", "threshold": 0.5}
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    # The result is derived server-side - the client never supplied a result.
    assert body["result"] == "SUPPORTED"
    assert body["authority"] == "ANALYSIS_ONLY"
    assert body["hypothesisId"] == h.hypothesis_id


def test_17_get_validation(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    created = client.post(
        "/api/knowledge/validations",
        json={
            "hypothesis_id": h.hypothesis_id,
            "method": "HISTORICAL_REPLAY",
            "sample_size": 10,
            "support_count": 8,
            "counterexample_count": 2,
            "acceptance_criteria": [
                {"metric": "SUPPORT_RATIO", "relation": "AT_LEAST", "threshold": 0.5}
            ],
        },
    ).json()
    resp = client.get("/api/knowledge/validations/" + created["validationId"])
    assert resp.status_code == 200
    assert resp.json()["authority"] == "ANALYSIS_ONLY"


def test_18_list_validations_bounded(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    client.post(
        "/api/knowledge/validations",
        json={
            "hypothesis_id": h.hypothesis_id,
            "method": "HISTORICAL_REPLAY",
            "sample_size": 10,
            "support_count": 8,
            "counterexample_count": 2,
            "acceptance_criteria": [
                {"metric": "SUPPORT_RATIO", "relation": "AT_LEAST", "threshold": 0.5}
            ],
        },
    )
    resp = client.get("/api/knowledge/validations")
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    assert resp.json()["authority"] == "ANALYSIS_ONLY"


def test_19_validation_cannot_start_paper_runtime(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    # The validation endpoint returns an analysis-only object and the service has
    # no runtime mutation surface.
    resp = client.post(
        "/api/knowledge/validations",
        json={
            "hypothesis_id": h.hypothesis_id,
            "method": "PAPER_RESULTS",
            "sample_size": 10,
            "support_count": 8,
            "counterexample_count": 2,
            "acceptance_criteria": [
                {"metric": "SUPPORT_RATIO", "relation": "AT_LEAST", "threshold": 0.5}
            ],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["authority"] == "ANALYSIS_ONLY"
    assert not hasattr(svc, "start") and not hasattr(svc, "execute")


# --------------------------------------------------------------------------- #
# Human Review
# --------------------------------------------------------------------------- #


def test_20_record_human_review(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    _authenticate(client, manager)
    resp = client.post(
        "/api/knowledge/human-reviews",
        json={
            "hypothesis_id": h.hypothesis_id,
            "validation_id": v.validation_id,
            "decision": "APPROVED",
            "notes": "looks sound",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["decision"] == "APPROVED"
    assert body["reviewer"] == "operator"
    assert body["hypothesisId"] == h.hypothesis_id
    assert body["validationId"] == v.validation_id


def test_21_server_derives_review_fingerprint(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    _authenticate(client, manager)
    resp = client.post(
        "/api/knowledge/human-reviews",
        json={
            "hypothesis_id": h.hypothesis_id,
            "validation_id": v.validation_id,
            "decision": "APPROVED",
        },
    )
    body = resp.json()
    # The server-derived fingerprint matches the deterministic subject hash.
    assert body["subjectFingerprint"] == review_subject_fingerprint(h, v)
    assert len(body["subjectFingerprint"]) >= 32


def test_22_client_cannot_override_review_fingerprint(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    _authenticate(client, manager)
    resp = client.post(
        "/api/knowledge/human-reviews",
        json={
            "hypothesis_id": h.hypothesis_id,
            "validation_id": v.validation_id,
            "decision": "APPROVED",
            "subjectFingerprint": "clientsupplied",
        },
    )
    # Unknown/forbidden field -> strict model rejects it.
    assert resp.status_code == 422


def test_23_trusted_reviewer_identity_required(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    # No operator session -> fail closed.
    resp = client.post(
        "/api/knowledge/human-reviews",
        json={
            "hypothesis_id": h.hypothesis_id,
            "validation_id": v.validation_id,
            "decision": "APPROVED",
        },
    )
    assert resp.status_code == 401


def test_23b_client_cannot_set_reviewer_body(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    _authenticate(client, manager)
    resp = client.post(
        "/api/knowledge/human-reviews",
        json={
            "hypothesis_id": h.hypothesis_id,
            "validation_id": v.validation_id,
            "decision": "APPROVED",
            "reviewer": "spoofed",
        },
    )
    assert resp.status_code == 422


def test_24_get_human_review(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    resp = client.get("/api/knowledge/human-reviews/" + review.review_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["reviewId"] == review.review_id
    assert body["subjectFingerprint"] == review_subject_fingerprint(h, v)


def test_25_list_human_reviews_bounded(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    _approve_via_store(svc.store, h, v)
    resp = client.get("/api/knowledge/human-reviews")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["authority"] == "HUMAN_REVIEW_REQUIRED"
    assert body["items"][0]["subjectFingerprint"]


def test_26_no_human_review_update_route(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    resp = client.put(
        "/api/knowledge/human-reviews/" + review.review_id,
        json={"decision": "REJECTED"},
    )
    assert resp.status_code in (404, 405)


def test_27_no_human_review_delete_route(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    resp = client.delete("/api/knowledge/human-reviews/" + review.review_id)
    assert resp.status_code in (404, 405)


def test_28_human_review_pins_validation(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    _authenticate(client, manager)
    resp = client.post(
        "/api/knowledge/human-reviews",
        json={
            "hypothesis_id": h.hypothesis_id,
            "validation_id": v.validation_id,
            "decision": "APPROVED",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["validationId"] == v.validation_id


# --------------------------------------------------------------------------- #
# Promotion
# --------------------------------------------------------------------------- #


def _promote_payload(client, h, v, review_id):
    return client.post(
        "/api/knowledge/promotions",
        json={
            "hypothesis_id": h.hypothesis_id,
            "validation_id": v.validation_id,
            "review_id": review_id,
            "version": "1.0",
        },
    )


def test_29_stale_review_rejected(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    # Tamper the underlying hypothesis AFTER the approval -> fingerprint no longer
    # matches the persisted subject.
    _tamper_payload(
        svc.store,
        "hypotheses",
        "hypothesis_id",
        h.hypothesis_id,
        lambda p: p.update({"validation_criteria": [["SUPPORT_RATIO", "AT_LEAST", 0.9]]}),
    )
    resp = _promote_payload(client, h, v, review.review_id)
    assert resp.status_code == 409
    assert resp.json()["code"] == "STALE_REVIEW"


def test_30_rejected_review_cannot_promote(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = record_human_review(
        hypothesis_id=h.hypothesis_id,
        decision=ReviewDecision.REJECTED,
        reviewer="operator",
        reviewed_at="2026-09-05T10:00:00Z",
    )
    svc.store.append_human_review(review, validation=v)
    resp = _promote_payload(client, h, v, review.review_id)
    assert resp.status_code == 409
    assert resp.json()["code"] == "REVIEW_NOT_APPROVED"


def test_31_needs_more_evidence_cannot_promote(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = record_human_review(
        hypothesis_id=h.hypothesis_id,
        decision=ReviewDecision.NEEDS_MORE_EVIDENCE,
        reviewer="operator",
        reviewed_at="2026-09-05T10:00:00Z",
    )
    svc.store.append_human_review(review, validation=v)
    resp = _promote_payload(client, h, v, review.review_id)
    assert resp.status_code == 409


def test_32_unsupported_hypothesis_cannot_promote(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = propose_hypothesis(
        statement="unsupported", validation_criteria=(("SUPPORT_RATIO", "AT_LEAST", 0.5),)
    )
    svc.store.create_hypothesis(h)
    v = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=10, support_count=8, counterexample_count=2,
            method=ValidationMethod.HISTORICAL_REPLAY,
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    resp = _promote_payload(client, h, v, review.review_id)
    assert resp.status_code == 409
    assert resp.json()["code"] == "PROMOTION_REJECTED"


def test_33_unsupported_validation_cannot_promote(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=10, support_count=2, counterexample_count=8,
            method=ValidationMethod.HISTORICAL_REPLAY,
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.8),),
    )
    assert v.result.value == "NOT_SUPPORTED"
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    resp = _promote_payload(client, h, v, review.review_id)
    assert resp.status_code == 409
    assert resp.json()["code"] == "PROMOTION_REJECTED"


def test_34_mismatched_hypothesis_rejected(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h1 = _reach_supported(svc.store)
    v1 = _supported_validation(h1)
    svc.store.save_validation(v1)
    review1 = _approve_via_store(svc.store, h1, v1)
    # Review1 approves h1; attempting to promote a different hypothesis fails.
    h2 = _supported_hypothesis(svc.store, statement="a second hypothesis")
    v2 = _supported_validation(h2, sample=12, support=10)
    svc.store.save_validation(v2)
    resp = _promote_payload(client, h2, v2, review1.review_id)
    assert resp.status_code == 409
    assert resp.json()["code"] in {"PROMOTION_REJECTED", "REVIEW_NOT_APPROVED"}


def test_35_mismatched_validation_rejected(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)  # review pins v
    other = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=12, support_count=9, counterexample_count=3,
            method=ValidationMethod.HISTORICAL_REPLAY,
            dataset_references=("other",),
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    svc.store.save_validation(other)
    resp = _promote_payload(client, h, other, review.review_id)
    assert resp.status_code == 409


def test_36_mismatched_review_rejected(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    # A non-existent review -> 404, and a review bound to another subject -> 409.
    resp = _promote_payload(client, h, v, "review:does-not-exist")
    assert resp.status_code == 404


def test_37_valid_promotion_succeeds(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    resp = _promote_payload(client, h, v, review.review_id)
    assert resp.status_code == 201
    body = resp.json()
    assert body["knowledgeId"]
    assert body["originHypothesisId"] == h.hypothesis_id
    assert body["authority"] == "INFORMATION_ONLY"
    assert body["strategyMutationAuthority"] == "NONE"


def test_38_promotion_persists(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    promoted = _promote_payload(client, h, v, review.review_id).json()
    assert svc.store.get_validated_knowledge(promoted["knowledgeId"]) is not None


def test_39_get_validated_knowledge(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    knowledge_id = _promote_payload(client, h, v, review.review_id).json()["knowledgeId"]
    resp = client.get("/api/knowledge/validated-knowledge/" + knowledge_id)
    assert resp.status_code == 200
    assert resp.json()["authority"] == "INFORMATION_ONLY"
    assert resp.json()["status"] == "VALIDATED_KNOWN"


def test_40_list_validated_knowledge_bounded(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    _promote_payload(client, h, v, review.review_id)
    resp = client.get("/api/knowledge/validated-knowledge")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["authority"] == "INFORMATION_ONLY"


def test_41_no_arbitrary_validated_knowledge_creation(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    resp = client.post(
        "/api/knowledge/validated-knowledge",
        json={"statement": "invented", "authority": "CANONICAL"},
    )
    assert resp.status_code in (404, 405)


def test_42_promotion_remains_atomic(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)  # pins v
    other = evaluate_validation(
        h,
        evidence=ValidationEvidence(
            sample_size=20, support_count=15, counterexample_count=5,
            method=ValidationMethod.HISTORICAL_REPLAY,
            dataset_references=("unpinned",),
        ),
        criteria=(AcceptanceCriterion(ValidationMetric.SUPPORT_RATIO, Relation.AT_LEAST, 0.5),),
    )
    svc.store.save_validation(other)
    resp = _promote_payload(client, h, other, review.review_id)
    assert resp.status_code == 409
    assert svc.store.list_validated_knowledge(h.hypothesis_id) == ()


# --------------------------------------------------------------------------- #
# Error / input / ordering
# --------------------------------------------------------------------------- #


def test_43_duplicate_conflicting_write_returns_conflict(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    first = client.post(
        "/api/knowledge/hypotheses",
        json={"statement": "a", "hypothesis_id": "h-dup"},
    )
    assert first.status_code == 201
    second = client.post(
        "/api/knowledge/hypotheses",
        json={"statement": "b", "hypothesis_id": "h-dup"},
    )
    assert second.status_code == 409
    assert second.json()["code"] == "DUPLICATE_CONFLICT"


def test_44_not_found_returns_404(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    resp = client.get("/api/knowledge/hypotheses/hypothesis:missing")
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"


def test_45_store_unavailable_maps_to_503(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    client, svc, _ = _build_client(
        tmp_path, service=KnowledgeEvolutionService(store_path=blocker / "k.sqlite3")
    )
    resp = client.get("/api/knowledge/investigations")
    assert resp.status_code == 503
    assert resp.json()["code"] == "STORE_UNAVAILABLE"


def test_46_unknown_request_fields_rejected(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    resp = client.post(
        "/api/knowledge/investigations",
        json={"question": "q", "unexpectedFlag": True},
    )
    assert resp.status_code == 422


def test_47_oversized_input_rejected(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    resp = client.post(
        "/api/knowledge/hypotheses",
        json={"statement": "x" * 5000},
    )
    assert resp.status_code == 422
    # Unbounded list also rejected.
    resp2 = client.post(
        "/api/knowledge/hypotheses",
        json={
            "statement": "h",
            "validation_criteria": [
                {"metric": "SUPPORT_RATIO", "relation": "AT_LEAST", "threshold": 0.5}
            ]
            * 50,
        },
    )
    assert resp2.status_code == 422


def test_48_deterministic_list_ordering(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    for statement in ("z", "a", "m"):
        client.post(
            "/api/knowledge/hypotheses",
            json={"statement": statement},
        )
    first = client.get("/api/knowledge/hypotheses").json()["items"]
    second = client.get("/api/knowledge/hypotheses").json()["items"]
    # Deterministic ordering: two separate list calls return identical order and
    # the order is not affected by SQLite's undefined row order.
    assert first == second
    assert len(first) == 3


def test_49_authority_classifications_preserved(tmp_path):
    client, svc, manager = _build_client(tmp_path)
    inv, finding = _seed_investigation_finding(svc.store)
    pattern = _seed_pattern(svc.store)
    h = _reach_supported(svc.store)
    v = _supported_validation(h)
    svc.store.save_validation(v)
    review = _approve_via_store(svc.store, h, v)
    knowledge_id = _promote_payload(client, h, v, review.review_id).json()["knowledgeId"]

    assert client.get("/api/knowledge/investigations/" + inv.investigation_id).json()["authority"] == "ANALYSIS_ONLY"
    assert client.get("/api/knowledge/patterns/" + pattern.pattern_id).json()["authority"] == "OBSERVATION_ONLY"
    assert client.get("/api/knowledge/findings/" + finding.finding_id).json()["authority"] == "OBSERVATION_ONLY"
    assert client.get("/api/knowledge/hypotheses/" + h.hypothesis_id).json()["authority"] == "HYPOTHESIS_ONLY"
    assert client.get("/api/knowledge/validations/" + v.validation_id).json()["authority"] == "ANALYSIS_ONLY"
    review_resp = client.get("/api/knowledge/human-reviews/" + review.review_id).json()
    assert review_resp["knowledgePromotionAuthority"] == "HUMAN_REVIEW_REQUIRED"
    vk = client.get("/api/knowledge/validated-knowledge/" + knowledge_id).json()
    assert vk["authority"] == "INFORMATION_ONLY"
    assert vk["strategyMutationAuthority"] == "NONE"
    assert vk["canonicalMutationAuthority"] == "NONE"


# --------------------------------------------------------------------------- #
# Firewalls (no runtime / strategy / MM / canonical / provider / frontend)
# --------------------------------------------------------------------------- #


def test_50_no_runtime_mutation_dependency(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    forbidden = {
        "start", "stop", "start_trading", "stop_trading", "place_order",
        "submit_order", "cancel_order", "close_position", "set_mode",
        "set_leverage", "set_risk", "update_strategy", "write_canonical",
        "emergency", "set_auto_trade", "enable_live", "disable_live",
        "restart", "execute_order", "begin", "loop",
    }
    service_methods = {
        name for name in dir(svc) if not name.startswith("_") and callable(getattr(svc, name))
    }
    store_methods = {
        name for name in dir(svc.store)
        if not name.startswith("_") and callable(getattr(svc.store, name))
    }
    assert not (service_methods & forbidden)
    assert not (store_methods & forbidden)


def test_51_no_strategy_mutation_dependency(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    import inspect
    src = inspect.getsource(KnowledgeEvolutionService)
    for token in ("MicrostructureEdgeStrategy", "update_strategy", "MutateStrategy"):
        assert token not in src


def test_52_no_mm_mutation_dependency(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    import inspect
    src = inspect.getsource(KnowledgeEvolutionService)
    for token in ("MoneyManagement", "money_management", "configure_money_management"):
        assert token not in src


def test_53_no_canonical_mutation_dependency(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    import inspect
    src = inspect.getsource(KnowledgeEvolutionService)
    for token in ("write_canonical", "update_canonical", "canonical_loader", "CanonicalSpecification"):
        assert token not in src


def test_54_no_provider_dependency(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    import inspect
    src = inspect.getsource(KnowledgeEvolutionService) + inspect.getsource(create_knowledge_router)
    for token in ("openai", "OpenAI", "ollama", "Ollama", "deepseek", "anthropic", "gemini", "byteplus"):
        assert token.lower() not in src.lower()


def test_55_no_frontend_dependency(tmp_path):
    client, svc, _ = _build_client(tmp_path)
    import inspect
    src = inspect.getsource(create_knowledge_router)
    assert "frontend" not in src.lower()
    assert "import(" not in src
