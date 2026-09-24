"""WORK I P0 focused tests: canonical cycle evidence envelope foundation.

Covers the envelope schema, strict validation, deterministic IDs and
serialization, availability semantics, secret handling and integrity.  No
production path, DB or runtime store is touched.
"""

import json

import pytest

from backend.runtime.cycle_evidence import (
    AVAILABILITY_TRACKED_FIELDS,
    AvailabilityState,
    EnvelopeValidationError,
    EvidenceEnvelope,
    IntegrityError,
    SecretFieldError,
    SecretPolicy,
    build_envelope,
    canonical_json,
    stable_fingerprint,
)

RECORDED_AT = "2026-09-24T00:00:00.000000Z"


def av(**present):
    """Availability map for absent tracked fields (present fields auto-mark)."""

    return {
        field: AvailabilityState.NOT_CAPTURED.value
        for field in AVAILABILITY_TRACKED_FIELDS
        if field not in present
    }


def base_kwargs(**overrides):
    kwargs = dict(
        evidence_type="AI_DECISION",
        mode="PAPER",
        source={"subsystem": "cycle-test", "module": "tests"},
        recorded_at=RECORDED_AT,
        cycle_id="cycle-1",
        trade_id="trade-1",
    )
    kwargs.update(overrides)
    if "availability" not in overrides:
        present = {
            key: value
            for key, value in kwargs.items()
            if key in AVAILABILITY_TRACKED_FIELDS and value is not None
        }
        kwargs["availability"] = av(**present)
    return kwargs


# -- valid envelope ---------------------------------------------------------


def test_valid_envelope_build_and_roundtrip():
    envelope = build_envelope(**base_kwargs())
    assert envelope.schema_version == "evidence-envelope/v1"
    assert envelope.evidence_type == "AI_DECISION"
    assert envelope.lifecycle_stage == 5
    assert envelope.mode == "PAPER"
    assert envelope.evidence_id.startswith("evidence-")
    assert envelope.event_id.startswith("evidence-event-")
    assert envelope.integrity["algorithm"] == "sha256"
    assert envelope.integrity["digest"] == envelope.content_digest()

    restored = EvidenceEnvelope.from_dict(envelope.to_dict())
    assert restored.evidence_id == envelope.evidence_id
    assert restored.content_digest() == envelope.content_digest()
    assert restored.to_json() == envelope.to_json()


def test_envelope_is_immutable():
    envelope = build_envelope(**base_kwargs())
    with pytest.raises(Exception):
        envelope.mode = "LIVE"  # type: ignore[misc]


# -- strict validation ------------------------------------------------------


@pytest.mark.parametrize("stage", [15, -1, 99, "bogus", 1.5, True])
def test_invalid_lifecycle_stage_rejected(stage):
    with pytest.raises(EnvelopeValidationError):
        build_envelope(**base_kwargs(lifecycle_stage=stage))


@pytest.mark.parametrize("stage", [0, 7, 13, 14])
def test_valid_lifecycle_stage_accepted(stage):
    envelope = build_envelope(**base_kwargs(lifecycle_stage=stage))
    assert envelope.lifecycle_stage == stage


def test_invalid_evidence_type_rejected():
    with pytest.raises(EnvelopeValidationError):
        build_envelope(**base_kwargs(evidence_type="NOT_A_TYPE"))


@pytest.mark.parametrize("mode", ["SANDBOX", "", None])
def test_invalid_mode_rejected(mode):
    with pytest.raises((EnvelopeValidationError, TypeError)):
        build_envelope(**base_kwargs(mode=mode))


def test_source_requires_subsystem():
    with pytest.raises(EnvelopeValidationError):
        build_envelope(**base_kwargs(source={"module": "x"}))
    with pytest.raises(EnvelopeValidationError):
        build_envelope(**base_kwargs(source={}))


def test_absent_field_without_availability_rejected():
    availability = av(cycle_id=1, trade_id=1)
    availability.pop("correlation_id")
    with pytest.raises(EnvelopeValidationError):
        build_envelope(**base_kwargs(availability=availability))


def test_value_present_without_value_rejected():
    availability = av(cycle_id=1, trade_id=1)
    availability["correlation_id"] = AvailabilityState.VALUE_PRESENT.value
    with pytest.raises(EnvelopeValidationError):
        build_envelope(**base_kwargs(availability=availability))


# -- PAPER / LIVE common schema --------------------------------------------


def test_paper_and_live_share_one_schema():
    paper = build_envelope(**base_kwargs(mode="PAPER"))
    live = build_envelope(**base_kwargs(mode="LIVE"))
    assert set(paper.to_dict()) == set(live.to_dict())
    assert paper.mode == "PAPER"
    assert live.mode == "LIVE"
    assert paper.lifecycle_stage == live.lifecycle_stage
    assert paper.evidence_id != live.evidence_id


# -- identifiers and determinism -------------------------------------------


def test_identifier_stability_across_recorded_at():
    first = build_envelope(**base_kwargs(recorded_at="2026-09-24T00:00:00.000000Z"))
    second = build_envelope(**base_kwargs(recorded_at="2026-09-25T11:22:33.000000Z"))
    assert first.evidence_id == second.evidence_id
    assert first.event_id == second.event_id
    assert first.logical_digest() == second.logical_digest()
    assert first.content_digest() != second.content_digest()


def test_event_id_override_changes_identity():
    first = build_envelope(**base_kwargs())
    second = build_envelope(**base_kwargs(event_id="explicit-event-1"))
    assert first.event_id != second.event_id
    assert first.evidence_id != second.evidence_id


def test_deterministic_serialization():
    envelope = build_envelope(**base_kwargs(payload={"b": 2, "a": 1}))
    assert envelope.to_json() == canonical_json(envelope.to_dict())
    assert envelope.to_json() == EvidenceEnvelope.from_dict(
        envelope.to_dict()
    ).to_json()
    parsed = json.loads(envelope.to_json())
    assert list(parsed) == sorted(parsed)
    assert stable_fingerprint({"a": 1, "b": 2}) == stable_fingerprint({"b": 2, "a": 1})


def test_integrity_tamper_detected():
    envelope = build_envelope(**base_kwargs(payload={"value": 1}))
    tampered = envelope.to_dict()
    tampered["payload"]["value"] = 2
    with pytest.raises(IntegrityError):
        EvidenceEnvelope.from_dict(tampered)


# -- availability semantics -------------------------------------------------


def test_availability_states_are_preserved():
    availability = av(cycle_id=1, trade_id=1)
    availability["correlation_id"] = {
        "state": AvailabilityState.CAPTURE_FAILED.value,
        "detail": "writer crashed before correlation id was recorded",
    }
    availability["commit_sha"] = AvailabilityState.NOT_APPLICABLE.value
    envelope = build_envelope(**base_kwargs(availability=availability))
    assert envelope.availability["correlation_id"]["state"] == "CAPTURE_FAILED"
    assert "crashed" in envelope.availability["correlation_id"]["detail"]
    assert envelope.availability["commit_sha"] == "NOT_APPLICABLE"
    assert envelope.availability["symbol"] == "NOT_CAPTURED"


def test_capture_failed_requires_detail():
    availability = av(cycle_id=1, trade_id=1)
    availability["correlation_id"] = AvailabilityState.CAPTURE_FAILED.value
    with pytest.raises(EnvelopeValidationError):
        build_envelope(**base_kwargs(availability=availability))


def test_present_field_availability_auto_marked():
    envelope = build_envelope(**base_kwargs(symbol="MOVEUSDT"))
    assert envelope.symbol == "MOVEUSDT"
    assert envelope.availability["symbol"] == "VALUE_PRESENT"


def test_unknown_is_not_backfilled():
    envelope = build_envelope(**base_kwargs(payload={"decision": "BUY"}))
    assert envelope.cycle_id == "cycle-1"
    assert envelope.parameter_revision_id is None
    assert envelope.configuration_revision_id is None
    assert envelope.availability["parameter_revision_id"] == "NOT_CAPTURED"
    assert envelope.payload == {"decision": "BUY"}


def test_legacy_and_unknown_states_accepted():
    availability = av(cycle_id=1, trade_id=1)
    availability["configuration_revision_id"] = AvailabilityState.LEGACY_UNVERIFIED.value
    availability["parameter_revision_id"] = AvailabilityState.UNKNOWN.value
    availability["acceptance_id"] = AvailabilityState.NOT_AVAILABLE.value
    envelope = build_envelope(**base_kwargs(availability=availability))
    assert envelope.availability["configuration_revision_id"] == "LEGACY_UNVERIFIED"
    assert envelope.availability["parameter_revision_id"] == "UNKNOWN"
    assert envelope.availability["acceptance_id"] == "NOT_AVAILABLE"


# -- secrets ----------------------------------------------------------------


def test_secret_fields_are_redacted_and_recorded():
    envelope = build_envelope(
        **base_kwargs(
            payload={
                "price": 1.0,
                "apiKey": "SUPER_SECRET_VALUE",
                "nested": {"authorization": "Bearer abc", "attempts": 3},
            }
        )
    )
    assert "SUPER_SECRET_VALUE" not in envelope.to_json()
    assert "Bearer abc" not in envelope.to_json()
    assert envelope.payload["price"] == 1.0
    assert envelope.payload["nested"]["attempts"] == 3
    assert envelope.redaction["applied"] is True
    assert "payload.apiKey" in envelope.redaction["fields"]
    assert "payload.nested.authorization" in envelope.redaction["fields"]


def test_secret_field_rejection_policy():
    with pytest.raises(SecretFieldError):
        build_envelope(
            **base_kwargs(
                payload={"secretKey": "x"},
                secret_policy=SecretPolicy.REJECT,
            )
        )


def test_source_secret_is_redacted():
    envelope = build_envelope(
        **base_kwargs(
            source={"subsystem": "cycle-test", "sessionToken": "abc123"},
        )
    )
    assert "abc123" not in envelope.to_json()
    assert "source.sessionToken" in envelope.redaction["fields"]


# -- provenance and links ---------------------------------------------------


def test_provenance_and_links_preserved():
    envelope = build_envelope(
        **base_kwargs(
            task_id="TRADINGAI-WORK-I-01",
            acceptance_id="ACC-1",
            commit_sha="deadbeef",
            provenance={"truthLevel": "CURRENT_SOURCE_RUNTIME"},
            links={"traceId": "trading-e2e-1"},
        )
    )
    assert envelope.provenance["truthLevel"] == "CURRENT_SOURCE_RUNTIME"
    assert envelope.provenance["contractVersion"] == "evidence-envelope/v1"
    assert envelope.provenance["verified"] is False
    assert envelope.links["traceId"] == "trading-e2e-1"
    assert envelope.task_id == "TRADINGAI-WORK-I-01"
    assert envelope.availability["task_id"] == "VALUE_PRESENT"
    assert envelope.availability["acceptance_id"] == "VALUE_PRESENT"
    assert envelope.availability["commit_sha"] == "VALUE_PRESENT"
