from copy import deepcopy
import json

import pytest

from backend.prop_trading import CompleteEvaluationOutcome, evaluate_complete_bundle
from backend.prop_trading.outcome_projection import (
    PROP_OUTCOME_READ_ONLY_CONTEXT_SCHEMA_VERSION,
    project_outcome_read_only_context,
)
from scripts.generate_prop_outcome_fixtures import _bundle, generate_document


def _outcome():
    return evaluate_complete_bundle(
        bundle=_bundle("projection-test"),
        evaluation_id="evaluation-cc-3h-projection-test",
        link_id="link-cc-3h-projection-test",
    )


def test_projection_strictly_round_trips_and_preserves_decimal_currency_and_authority():
    original = _outcome()
    projected = project_outcome_read_only_context(original.to_dict())
    assert CompleteEvaluationOutcome.from_dict(original.to_dict()) == original
    assert projected["schemaVersion"] == PROP_OUTCOME_READ_ONLY_CONTEXT_SCHEMA_VERSION
    assert projected["synthetic"] is True
    assert projected["accountScope"] == {
        "accountId": "acc_20000000000040008000000000000002",
        "identityRevision": 3,
        "executionMode": "EXTERNAL_SIMULATION",
        "executionVenue": "BYBIT_DEMO",
        "program": "HYROTRADER",
        "planId": "SYNTHETIC-NOT-OFFICIAL",
        "phase": "CHALLENGE",
        "currency": "USDT",
    }
    assert projected["calculation"]["freshnessState"] == "FRESH"
    assert projected["calculation"]["warnings"] == [
        "RULE_COMPATIBILITY_ONLY_NO_EXECUTION_AUTHORITY"
    ]
    evidence_refs = [
        ref
        for item in projected["coverage"]["items"]
        for ref in item["evidenceRefs"]
    ]
    assert evidence_refs
    assert all("://" in ref for ref in evidence_refs)
    assert projected["references"]["bundleId"]
    assert projected["calculation"]["ruleResults"][0]["threshold"] == "6000"
    assert projected["authority"] == {
        "executionAuthorityGranted": False,
        "runtimeReady": False,
        "tradeReady": False,
        "reasonCode": "READ_ONLY_CONTEXT_NO_EXECUTION_AUTHORITY",
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["evaluation"].__setitem__("account_id", "acc_ffffffffffffffffffffffffffffffff"),
        lambda data: data["evidence_link"].__setitem__("evaluation_digest", "sha256:" + "0" * 64),
        lambda data: data.__setitem__("operational_candidate_status", "CANDIDATE_COMPATIBLE"),
        lambda data: data["bundle"].__setitem__("knowledge_cutoff_at", "2026-11-01T23:59:59Z"),
    ],
)
def test_projection_rejects_account_link_candidate_and_cutoff_tampering(mutation):
    payload = deepcopy(_outcome().to_dict())
    mutation(payload)
    with pytest.raises(ValueError):
        project_outcome_read_only_context(payload)


def test_generator_is_deterministic_complete_and_secret_free():
    first = generate_document()
    second = generate_document()
    assert first == second
    assert [item["id"] for item in first["scenarios"]] == [
        "calculation_pass", "maximum_loss_block", "required_information_unknown",
        "unsupported_required_rule", "profit_target_reached",
        "pre_evaluation_validation_failure",
    ]
    serialized = json.dumps(first, sort_keys=True)
    for forbidden in ("apiKey", "credentialPath", "rawUid", "rawIp", "private_key"):
        assert forbidden not in serialized
    for item in first["scenarios"][:-1]:
        assert item["outcome"]["authority"]["executionAuthorityGranted"] is False
    assert first["scenarios"][-1]["rejection"]["outcome"] is None
