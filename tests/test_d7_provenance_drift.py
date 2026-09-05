"""Focused D-7 tests: deterministic provenance and drift detection.

These tests exercise the deterministic, read-only provenance/drift foundation
added by D-7 to the shared Knowledge Core, its projection into the Advisor and
Supervisor, and the invariants that D-7 must never mutate, execute, or promote
truth upward.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from backend.knowledge_core import (
    D7_REASON_CODES,
    DriftAssessment,
    DriftFinding,
    DriftStatus,
    SourceKind,
    SourceCategory,
    TemporalScope,
    TruthLevel,
    assess_authority_conflict,
    assess_provenance,
    build_conflicting_assessment,
    fingerprint_bytes,
    fingerprint_fields,
    fingerprint_structured,
    merge_status,
    mutation_interface_names,
    normalize_value,
    provenance_from_advisor,
    provenance_from_knowledge,
    provenance_from_specialist,
    provenance_from_trace,
)
from backend.knowledge_core.provenance import ProvenanceRecord


NOW = datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
_HASH_A = "sha256:" + "a" * 64
_HASH_B = "sha256:" + "b" * 64


def _canonical(*, content_hash=_HASH_A, version="1.0", reference="docs/x.md") -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.CANONICAL_SPECIFICATION,
        source_category=SourceCategory.SPECIFICATION,
        source_reference=reference,
        version=version,
        content_hash=content_hash,
    )


def _runtime(*, reference="runtime:main", identifier="rid", subsystem="RUNTIME",
             source_timestamp=None, freshness="FRESH") -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel.CURRENT_SOURCE_RUNTIME,
        source_category=SourceCategory.RUNTIME,
        source_reference=reference,
        source_identifier=identifier,
        source_subsystem=subsystem,
        source_timestamp=source_timestamp,
        freshness=freshness,
    )


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #


def test_provenance_record_deterministic_and_typed():
    first = _canonical()
    second = _canonical()
    assert first == second
    assert first.truth_level is TruthLevel.CANONICAL_SPECIFICATION
    assert first.source_category is SourceCategory.SPECIFICATION
    assert first.content_hash == _HASH_A
    assert first.version == "1.0"
    assert first.summarize() == "docs/x.md"


def test_provenance_record_frozen_and_bounded():
    record = _canonical()
    try:
        record.source_reference = "mutated"
    except (AttributeError, TypeError):
        pass
    else:
        raise AssertionError("ProvenanceRecord must be immutable")


def test_provenance_record_carries_d7_fields():
    record = _canonical()
    assert record.source_subsystem is None
    assert record.source_type is None
    assert record.source_identifier is None
    assert record.observed_at is None
    assert record.source_timestamp is None
    assert record.loaded_at is None
    assert record.freshness is None
    assert record.confidence is None
    assert record.warnings == ()


def test_fingerprint_deterministic():
    assert fingerprint_bytes(b"payload") == fingerprint_bytes(b"payload")
    assert fingerprint_bytes(b"payload") != fingerprint_bytes(b"payload2")
    assert fingerprint_structured({"a": 1, "b": 2}) == fingerprint_structured({"a": 1, "b": 2})


def test_equivalent_normalized_content_same_fingerprint():
    # Key ordering does not matter.
    assert fingerprint_structured({"b": 2, "a": 1}) == fingerprint_structured({"a": 1, "b": 2})
    # Nested ordering does not matter.
    assert fingerprint_structured({"x": [1, 2, {"k": "v"}]}) == fingerprint_structured(
        {"x": [1, 2, {"k": "v"}]}
    )
    # Set ordering does not matter.
    assert fingerprint_structured({1, 2, 3}) == fingerprint_structured({3, 2, 1})
    # Enum values collapse to their string value deterministically.
    assert fingerprint_structured(DriftStatus.CURRENT) == fingerprint_structured("CURRENT")


def test_changed_normalized_content_different_fingerprint():
    assert fingerprint_structured({"a": 1}) != fingerprint_structured({"a": 2})
    assert fingerprint_structured({"a": 1, "b": 2}) != fingerprint_structured({"a": 1, "b": 3})
    assert fingerprint_structured([1, 2]) != fingerprint_structured([2, 1])


def test_fingerprint_input_not_mutated():
    data = {"z": 1, "a": 2, "nested": {"y": 3, "x": 4}}
    snapshot = deepcopy(data)
    fingerprint_structured(data)
    assert data == snapshot


def test_timezone_aware_utc_semantics():
    aware = datetime(2026, 1, 1, 12, 30, tzinfo=timezone(timedelta(hours=9)))
    normalized = normalize_value(aware)
    assert normalized.endswith("Z")
    assert normalized.startswith("2026-01-01T03:30:00")
    # A naive datetime is never silently interpreted.
    try:
        normalize_value(datetime(2026, 1, 1, 12, 0))
    except ValueError:
        pass
    else:
        raise AssertionError("naive datetime must be rejected")
    # A naive source timestamp used in freshness must also be rejected.
    current = _runtime(source_timestamp=datetime(2026, 1, 1, 0, 0), freshness="FRESH")
    expected = _runtime(reference="runtime:main")
    try:
        assess_provenance(
            subject="runtime", source_kind=SourceKind.CURRENT_RUNTIME,
            expected=expected, current=current, assessed_at=NOW,
            freshness_window_seconds=10,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("naive source timestamp must be rejected")


def test_secret_fields_excluded_from_fingerprint():
    safe = {"itemId": "abc", "mode": "PAPER", "apiKey": "SECRET_1", "token": "TKN"}
    other = {"itemId": "abc", "mode": "PAPER", "apiKey": "SECRET_2", "token": "TKN2"}
    assert fingerprint_fields(safe, ("itemId", "mode")) == fingerprint_fields(other, ("itemId", "mode"))
    digest = fingerprint_fields(safe, ("itemId", "mode"))
    assert "SECRET" not in digest and "TKN" not in digest
    # Refusing a secret-bearing allowlist is explicit.
    try:
        fingerprint_fields(safe, ("apiKey",))
    except ValueError:
        pass
    else:
        raise AssertionError("secret-bearing allowlist must be refused")


# --------------------------------------------------------------------------- #
# Drift
# --------------------------------------------------------------------------- #


def test_matching_fingerprint_current():
    assessment = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=_canonical(), current=_canonical(), assessed_at=NOW,
    )
    assert assessment.status is DriftStatus.CURRENT
    assert assessment.findings == ()


def test_mismatched_fingerprint_drifted():
    assessment = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=_canonical(content_hash=_HASH_A),
        current=_canonical(content_hash=_HASH_B), assessed_at=NOW,
    )
    assert assessment.status is DriftStatus.DRIFTED
    assert any(f.code == "PROVENANCE_FINGERPRINT_MISMATCH" for f in assessment.findings)


def test_version_mismatch_drifted():
    assessment = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=_canonical(version="1.0"), current=_canonical(version="2.0"),
        assessed_at=NOW,
    )
    assert assessment.status is DriftStatus.DRIFTED
    assert any(f.code == "PROVENANCE_VERSION_MISMATCH" for f in assessment.findings)


def test_stale_source_stale():
    source_ts = NOW - timedelta(seconds=10_000)
    current = _runtime(source_timestamp=source_ts, freshness="FRESH")
    expected = _runtime(reference="runtime:main")
    assessment = assess_provenance(
        subject="runtime", source_kind=SourceKind.CURRENT_RUNTIME,
        expected=expected, current=current, assessed_at=NOW, freshness_window_seconds=60,
    )
    assert assessment.status is DriftStatus.STALE
    assert any(f.code == "EVIDENCE_STALE" for f in assessment.findings)


def test_stale_is_not_drifted_for_matching_static_source():
    stale = _canonical(
        content_hash=_HASH_A,
    )
    stale = ProvenanceRecord(
        truth_level=TruthLevel.CANONICAL_SPECIFICATION,
        source_category=SourceCategory.SPECIFICATION,
        source_reference="docs/x.md", version="1.0", content_hash=_HASH_A,
        source_timestamp=NOW - timedelta(days=2),
    )
    assessment = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=_canonical(), current=stale, assessed_at=NOW, freshness_window_seconds=60,
    )
    assert assessment.status is DriftStatus.STALE
    assert not any(f.status is DriftStatus.DRIFTED for f in assessment.findings)


def test_missing_current_source_unavailable():
    assessment = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=_canonical(), current=None, assessed_at=NOW,
    )
    assert assessment.status is DriftStatus.UNAVAILABLE
    assert any(f.code == "PROVENANCE_SOURCE_MISSING" for f in assessment.findings)


def test_insufficient_evidence_unknown():
    current = _runtime(reference="runtime:main", identifier=None, subsystem=None,
                       source_timestamp=None, freshness=None)
    expected = _runtime(reference="runtime:main")
    assessment = assess_provenance(
        subject="runtime", source_kind=SourceKind.CURRENT_RUNTIME,
        expected=expected, current=current, assessed_at=NOW,
    )
    assert assessment.status is DriftStatus.UNKNOWN


def test_incompatible_claims_conflicting():
    finding = assess_authority_conflict(
        subject="mode",
        claim_a="PAPER", claim_b="LIVE",
        temporal_scope_a=TemporalScope.CURRENT, temporal_scope_b=TemporalScope.CURRENT,
        provenance_a=_runtime(reference="governance"),
        provenance_b=_runtime(reference="bot"),
    )
    assert finding is not None
    assert finding.status is DriftStatus.CONFLICTING
    assessment = build_conflicting_assessment("mode", finding, assessed_at=NOW)
    assert assessment.status is DriftStatus.CONFLICTING


def test_historical_vs_current_not_automatically_conflict():
    finding = assess_authority_conflict(
        subject="botState",
        claim_a="STOPPED", claim_b="RUNNING",
        temporal_scope_a=TemporalScope.CURRENT, temporal_scope_b=TemporalScope.HISTORICAL,
        provenance_a=_runtime(reference="runtime"),
        provenance_b=_runtime(reference="history"),
    )
    assert finding is None


def test_dynamic_runtime_value_change_not_drifted():
    expected = _runtime(reference="runtime:main")
    current = _runtime(reference="runtime:main", freshness="FRESH")
    assessment = assess_provenance(
        subject="runtime", source_kind=SourceKind.CURRENT_RUNTIME,
        expected=expected, current=current, assessed_at=NOW,
    )
    assert assessment.status is not DriftStatus.DRIFTED
    assert not any(f.status is DriftStatus.DRIFTED for f in assessment.findings)


def test_assessment_deterministic():
    expected = _canonical()
    current = _canonical(content_hash=_HASH_B)
    first = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=expected, current=current, assessed_at=NOW,
    )
    second = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=expected, current=current, assessed_at=NOW,
    )
    assert first.stable_json() == second.stable_json()


def test_assessment_input_not_mutated():
    expected = _canonical()
    current = _canonical(content_hash=_HASH_B)
    exp_before = deepcopy(expected)
    cur_before = deepcopy(current)
    assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=expected, current=current, assessed_at=NOW,
    )
    assert expected == exp_before
    assert current == cur_before


# --------------------------------------------------------------------------- #
# Authority
# --------------------------------------------------------------------------- #


def test_truth_hierarchy_preserved():
    assert TruthLevel.CANONICAL_SPECIFICATION.value == "CANONICAL_SPECIFICATION"
    # Canonical is the highest priority; observation is lower.
    order = {
        TruthLevel.CANONICAL_SPECIFICATION: 1,
        TruthLevel.CURRENT_SOURCE_RUNTIME: 2,
        TruthLevel.VALIDATED_KNOWLEDGE: 3,
        TruthLevel.OBSERVATION_FINDING: 4,
        TruthLevel.HYPOTHESIS: 5,
    }
    assert order[TruthLevel.CANONICAL_SPECIFICATION] < order[TruthLevel.OBSERVATION_FINDING]


def test_observation_cannot_override_canonical():
    finding = assess_authority_conflict(
        subject="mode", claim_a="PAPER", claim_b="LIVE",
        temporal_scope_a=TemporalScope.CURRENT, temporal_scope_b=TemporalScope.CURRENT,
        provenance_a=_canonical(reference="docs/constitution.md"),
        provenance_b=ProvenanceRecord(
            truth_level=TruthLevel.OBSERVATION_FINDING,
            source_category=SourceCategory.RUNTIME, source_reference="advisor:observation",
        ),
    )
    assert finding is not None
    assert finding.status is DriftStatus.CONFLICTING
    assert finding.authoritative_layer is TruthLevel.CANONICAL_SPECIFICATION


def test_historical_evidence_cannot_override_current_runtime():
    finding = assess_authority_conflict(
        subject="botState", claim_a="STOPPED", claim_b="RUNNING",
        temporal_scope_a=TemporalScope.CURRENT, temporal_scope_b=TemporalScope.HISTORICAL,
        provenance_a=_runtime(reference="runtime"), provenance_b=_runtime(reference="history"),
    )
    assert finding is None


def test_specialist_finding_remains_observation():
    ref = _runtime(reference="strategy:evidence", identifier="ev1", subsystem="STRATEGY",
                   source_timestamp=NOW - timedelta(minutes=5), freshness="FRESH")
    assessment = assess_provenance(
        subject="specialist", source_kind=SourceKind.SPECIALIST_FINDING,
        expected=_runtime(reference="strategy:evidence"),
        current=ref, assessed_at=NOW, freshness_window_seconds=3600,
    )
    assert assessment.status is DriftStatus.CURRENT
    assert all(
        f.authority_layer is TruthLevel.OBSERVATION_FINDING for f in assessment.findings
    )


def test_drift_assessment_has_no_mutation_authority():
    assessment = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=_canonical(), current=_canonical(content_hash=_HASH_B), assessed_at=NOW,
    )
    assert assessment.authority.value == "INFORMATION_ONLY"
    assert assessment.grants_any_authority is False
    assert mutation_interface_names(assessment) == ()


# --------------------------------------------------------------------------- #
# D-5 / D-6 provenance reuse
# --------------------------------------------------------------------------- #


def test_d5_provenance_preserved():
    from backend.runtime.unified_trace import Provenance, SourceSubsystem

    d5 = Provenance(
        source_subsystem=SourceSubsystem.EXECUTION,
        source_type="TRACE_EVENT:EXECUTION",
        source_identifier="evt-1",
        timestamp=NOW.isoformat().replace("+00:00", "Z"),
        linkage_method="EVIDENCE_REFERENCE",
    )
    converted = provenance_from_trace(d5)
    assert converted.source_subsystem == "EXECUTION"
    assert converted.source_type == "TRACE_EVENT:EXECUTION"
    assert converted.source_identifier == "evt-1"
    assert converted.source_timestamp == NOW
    assert converted.truth_level is TruthLevel.OBSERVATION_FINDING


def test_partial_ambiguous_trace_stays_explicit():
    expected = _runtime(reference="history:trace")
    current = ProvenanceRecord(
        truth_level=TruthLevel.OBSERVATION_FINDING,
        source_category=SourceCategory.HISTORY,
        source_reference="history:trace:123", source_identifier="123",
        source_subsystem="EXECUTION", source_timestamp=NOW - timedelta(hours=1),
    )
    for completeness in ("PARTIAL", "AMBIGUOUS"):
        assessment = assess_provenance(
            subject="trace", source_kind=SourceKind.HISTORICAL_EVIDENCE,
            expected=expected, current=current, assessed_at=NOW, completeness=completeness,
        )
        assert assessment.status is not DriftStatus.CURRENT
        assert any(
            "TRACE_" + completeness in f.warnings for f in assessment.findings
        )
    unavailable = assess_provenance(
        subject="trace", source_kind=SourceKind.HISTORICAL_EVIDENCE,
        expected=expected, current=None, assessed_at=NOW, completeness="UNAVAILABLE",
    )
    assert unavailable.status is DriftStatus.UNAVAILABLE


def test_d6_specialist_source_reference_preserved():
    from backend.supervisor.specialists.contracts import SourceReference

    ref = SourceReference(
        sourceSubsystem="EXECUTION", sourceType="TRACE_EVENT:EXECUTION",
        sourceIdentifier="evt-2", timestamp=NOW.isoformat().replace("+00:00", "Z"),
        linkageMethod="EVIDENCE_REFERENCE",
    )
    converted = provenance_from_specialist(ref)
    assert converted.source_subsystem == "EXECUTION"
    assert converted.source_type == "TRACE_EVENT:EXECUTION"
    assert converted.source_identifier == "evt-2"
    assert converted.source_timestamp == NOW
    assert converted.truth_level is TruthLevel.OBSERVATION_FINDING


def test_stale_specialist_evidence_surfaced():
    current = _runtime(reference="strategy:evidence", identifier="ev1", subsystem="STRATEGY",
                       source_timestamp=NOW - timedelta(seconds=5000), freshness="STALE")
    assessment = assess_provenance(
        subject="specialist", source_kind=SourceKind.SPECIALIST_FINDING,
        expected=_runtime(reference="strategy:evidence"),
        current=current, assessed_at=NOW, freshness_window_seconds=60,
    )
    assert assessment.status is DriftStatus.STALE
    assert any(f.code == "EVIDENCE_STALE" for f in assessment.findings)


def test_missing_specialist_evidence_not_current():
    assessment = assess_provenance(
        subject="specialist", source_kind=SourceKind.SPECIALIST_FINDING,
        expected=_runtime(reference="strategy:evidence"), current=None, assessed_at=NOW,
    )
    assert assessment.status is not DriftStatus.CURRENT
    assert assessment.status is DriftStatus.UNAVAILABLE


# --------------------------------------------------------------------------- #
# Advisor / Supervisor integration
# --------------------------------------------------------------------------- #


def _drifted_assessment():
    return assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=_canonical(), current=_canonical(content_hash=_HASH_B), assessed_at=NOW,
    )


def _conflicting_assessment():
    finding = assess_authority_conflict(
        subject="mode", claim_a="PAPER", claim_b="LIVE",
        temporal_scope_a=TemporalScope.CURRENT, temporal_scope_b=TemporalScope.CURRENT,
        provenance_a=_runtime(reference="governance"), provenance_b=_runtime(reference="bot"),
    )
    return build_conflicting_assessment("mode", finding, assessed_at=NOW)


def test_advisor_exposes_bounded_drift_metadata():
    from backend.ai_advisor.drift_context import build_advisor_drift_context

    context = build_advisor_drift_context([_drifted_assessment()])
    assert context.items
    item = context.items[0]
    assert item.status == "DRIFTED"
    assert item.sourceKind == "STATIC_CANONICAL"
    assert item.reasonCodes == ("PROVENANCE_FINGERPRINT_MISMATCH",)
    assert len(item.itemId) <= 128


def test_advisor_drifted_item_not_silently_current():
    from backend.ai_advisor.drift_context import build_advisor_drift_context

    context = build_advisor_drift_context([_drifted_assessment()])
    assert context.items[0].asCurrent is False
    assert context.items[0].status == "DRIFTED"


def test_advisor_conflicting_item_not_silently_current():
    from backend.ai_advisor.drift_context import build_advisor_drift_context

    context = build_advisor_drift_context([_conflicting_assessment()])
    assert context.items[0].asCurrent is False
    assert context.items[0].status == "CONFLICTING"


def test_supervisor_can_surface_drift_finding():
    from backend.supervisor.drift_surface import build_supervisor_drift_notice

    notice = build_supervisor_drift_notice(_drifted_assessment(), generated_at=NOW)
    assert notice.status == "DRIFTED"
    assert notice.reasonCodes == ("PROVENANCE_FINGERPRINT_MISMATCH",)
    assert notice.sourceReferences
    assert notice.authority == "READ_ONLY_ANALYSIS"


def test_supervisor_cannot_repair_drift():
    from backend.supervisor.drift_surface import build_supervisor_drift_notice

    notice = build_supervisor_drift_notice(_drifted_assessment(), generated_at=NOW)
    assert notice.has_repair_authority is False
    assert notice.operationalAuthority == "NONE"
    assert notice.mutationAuthority == "NONE"
    repair_verbs = {"repair", "resync", "rewrite", "apply", "approve", "reload", "set",
                    "start", "stop", "cancel", "place", "execute"}
    for name in dir(notice):
        if name.startswith("_"):
            continue
        first = name.lower().rstrip("_s").split("_")[0]
        assert first not in repair_verbs, f"repair surface present: {name}"


def test_advisor_bounded_context():
    from backend.ai_advisor.drift_context import build_advisor_drift_context

    context = build_advisor_drift_context([_drifted_assessment(), _conflicting_assessment()])
    assert len(context.items) <= 8
    assert all(item.status in {s.value for s in DriftStatus} for item in context.items)


def test_advisor_truncation_explicit():
    from backend.ai_advisor.drift_context import build_advisor_drift_context

    items = [_drifted_assessment(), _conflicting_assessment(), _drifted_assessment()]
    context = build_advisor_drift_context(items, max_items=1)
    assert context.truncated is True
    assert context.omittedCount == 2
    assert context.warning is not None
    assert "omitted" in context.warning


# --------------------------------------------------------------------------- #
# Provider / security / authority
# --------------------------------------------------------------------------- #


def test_provider_neutrality_no_llm_import():
    import inspect

    from backend import ai_advisor as advisor_pkg
    from backend import supervisor as supervisor_pkg

    for module in (
        advisor_pkg.drift_context,
        supervisor_pkg.drift_surface,
    ):
        source = inspect.getsource(module)
        for token in ("openai", "deepseek", "anthropic", "byteplus", "llm"):
            assert token not in source, f"{module.__name__} leaks provider/LLM dependency"


def test_no_llm_dependency_for_drift_decision():
    # The drift decision is a pure function of typed inputs; it is already
    # proven deterministic in the Drift section, and requires no provider.
    assessment = assess_provenance(
        subject="doc", source_kind=SourceKind.STATIC_CANONICAL,
        expected=_canonical(), current=_canonical(content_hash=_HASH_B), assessed_at=NOW,
    )
    assert assessment.status is DriftStatus.DRIFTED
    assert assessment.reason_codes == ("PROVENANCE_FINGERPRINT_MISMATCH",)


def test_secrets_not_exposed_in_projection():
    from backend.ai_advisor.drift_context import render_drift_context, build_advisor_drift_context
    from backend.supervisor.drift_surface import build_supervisor_drift_notice

    context = build_advisor_drift_context([_drifted_assessment()])
    rendered = render_drift_context(context)
    assert "apiKey" not in rendered
    assert "SECRET" not in rendered
    notice = build_supervisor_drift_notice(_drifted_assessment(), generated_at=NOW)
    serialized = notice.stable_json()
    assert "apiKey" not in serialized
    assert "SECRET" not in serialized


def test_no_operational_mutation():
    assessment = _drifted_assessment()
    assert mutation_interface_names(assessment) == ()
    assert assessment.grants_any_authority is False
    assert assessment.authority.value == "INFORMATION_ONLY"


def test_no_execution_authority():
    finding = _conflicting_assessment()
    assert finding.authority.value == "INFORMATION_ONLY"
    assert finding.grants_any_authority is False


def test_deterministic_output_across_runs():
    from backend.ai_advisor.drift_context import build_advisor_drift_context, render_drift_context
    from backend.supervisor.drift_surface import build_supervisor_drift_notice

    a1 = _drifted_assessment()
    a2 = _drifted_assessment()
    assert a1.stable_json() == a2.stable_json()
    c1 = build_advisor_drift_context([a1])
    c2 = build_advisor_drift_context([a2])
    assert render_drift_context(c1) == render_drift_context(c2)
    n1 = build_supervisor_drift_notice(a1, generated_at=NOW)
    n2 = build_supervisor_drift_notice(a2, generated_at=NOW)
    assert n1.stable_json() == n2.stable_json()


def test_d7_reason_codes_narrow_and_known():
    assert set(D7_REASON_CODES) == {
        "PROVENANCE_SOURCE_MISSING",
        "PROVENANCE_FINGERPRINT_MISMATCH",
        "PROVENANCE_VERSION_MISMATCH",
        "EVIDENCE_STALE",
        "AUTHORITY_CONFLICT",
        "PROVENANCE_UNKNOWN",
    }


def test_merge_status_reference_semantics():
    # Deterministically prefer DRIFTED over STALE, and CONFLICTING over DRIFTED.
    assert merge_status([]) is DriftStatus.CURRENT
    assert merge_status([DriftStatus.STALE, DriftStatus.DRIFTED]) is DriftStatus.DRIFTED
    assert (
        merge_status([DriftStatus.DRIFTED, DriftStatus.CONFLICTING])
        is DriftStatus.CONFLICTING
    )
    assert merge_status([DriftStatus.UNAVAILABLE, DriftStatus.UNKNOWN]) is DriftStatus.UNAVAILABLE
