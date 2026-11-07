from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.context import (
    SCHEMA_VERSION,
    Availability,
    CanonicalContext,
    Freshness,
    GeneratorInfo,
    SafetyContext,
    build_canonical_context,
)
from tests.test_ai_context_support import FIXED_NOW, make_supervisor_snapshot


EXPECTED_SECTIONS = {
    "schemaVersion",
    "generatedAt",
    "generator",
    "source",
    "runtime",
    "marketSelection",
    "executionControl",
    "market",
    "moneyManagement",
    "governance",
    "tradingCycle",
    "position",
    "orders",
    "smallAccount",
    "account",
    "emergency",
    "health",
    "contracts",
    "workstreams",
    "knownIssues",
    "acceptedTests",
    "safety",
    "freshness",
    "provenance",
}


def _context():
    return build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=make_runtime_truth(),
        generator=GeneratorInfo(),
    )


def make_runtime_truth():
    from backend.context import RuntimeTruthSource

    return RuntimeTruthSource(snapshot=make_supervisor_snapshot())


def test_schema_validation_round_trips():
    context = _context()
    assert context.schemaVersion == SCHEMA_VERSION == "tradingai-context/v1"
    assert set(type(context).model_fields) == EXPECTED_SECTIONS
    revalidated = CanonicalContext.model_validate(context.model_dump())
    assert revalidated == context


def test_schema_rejects_wrong_version_and_extra_fields():
    context = _context()
    payload = context.model_dump()
    payload["schemaVersion"] = "tradingai-context/v2"
    with pytest.raises(ValidationError):
        CanonicalContext.model_validate(payload)

    payload = context.model_dump()
    payload["unexpectedSection"] = {}
    with pytest.raises(ValidationError):
        CanonicalContext.model_validate(payload)


def test_safety_context_is_fixed_read_only():
    safety = SafetyContext()
    assert safety.contextRead is True
    assert safety.sourceWrite is False
    assert safety.runtimeWrite is False
    assert safety.orderWrite is False
    assert safety.liveOrder is False
    assert safety.productionDeploy is False
    assert safety.secretsIncluded is False
    assert safety.paperLiveAuthorityUnchanged is True
    assert safety.botManualAuthorityUnchanged is True
    assert safety.emergencyStateUnchanged is True


def test_all_sections_have_explicit_availability_and_freshness():
    context = _context()
    for name in (
        "runtime",
        "marketSelection",
        "executionControl",
        "market",
        "moneyManagement",
        "governance",
        "tradingCycle",
        "position",
        "orders",
        "smallAccount",
        "account",
        "emergency",
        "health",
    ):
        section = getattr(context, name)
        assert isinstance(section.meta.availability, Availability)
        assert isinstance(section.meta.freshness, Freshness)
        assert section.meta.source
