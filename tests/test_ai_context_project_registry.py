from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.context import (
    Availability,
    VerificationState,
    WorkstreamStatus,
    load_project_truth,
)

REGISTRY = Path("docs/ai/PROJECT_STATE.yaml")
FIXED_NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)

EXPECTED_WORKSTREAMS = {
    "A",
    "A1",
    "A2",
    "A-INTEGRATION",
    "B",
    "C",
    "D",
    "F",
    "G",
    "H",
    "J",
    "AA",
    "MM",
    "BB",
}


def test_project_registry_loads_and_validates():
    truth = load_project_truth(REGISTRY, observed_at=FIXED_NOW)
    assert truth.meta.availability is Availability.AVAILABLE
    assert truth.schemaVersion == "tradingai-project-truth/v1"
    assert {item.workstreamId for item in truth.workstreams} == EXPECTED_WORKSTREAMS
    assert [item.contractId for item in truth.contracts] == ["tradingai-context/v1"]


def test_unknown_workstream_states_are_not_inferred():
    truth = load_project_truth(REGISTRY, observed_at=FIXED_NOW)
    by_id = {item.workstreamId: item for item in truth.workstreams}
    bb = by_id["BB"]
    assert bb.status is WorkstreamStatus.IN_PROGRESS
    assert bb.verification is VerificationState.PARTIAL
    for workstream_id in EXPECTED_WORKSTREAMS - {"BB"}:
        item = by_id[workstream_id]
        assert item.status is WorkstreamStatus.UNKNOWN
        assert item.verification is VerificationState.UNVERIFIED
        assert item.owner == "UNKNOWN"
        assert item.branch is None
        assert item.lastVerified is None


def test_missing_status_defaults_to_unknown(tmp_path):
    registry = tmp_path / "PROJECT_STATE.yaml"
    registry.write_text(
        """
schemaVersion: tradingai-project-truth/v1
workstreams:
  - workstreamId: X
    name: "Unconfirmed workstream"
""",
        encoding="utf-8",
    )
    truth = load_project_truth(registry, observed_at=FIXED_NOW)
    item = truth.workstreams[0]
    assert item.status is WorkstreamStatus.UNKNOWN
    assert item.verification is VerificationState.UNVERIFIED
    assert item.lastVerified is None


def test_complete_without_verification_rejected(tmp_path):
    registry = tmp_path / "PROJECT_STATE.yaml"
    registry.write_text(
        """
schemaVersion: tradingai-project-truth/v1
workstreams:
  - workstreamId: X
    name: "Looks done"
    status: COMPLETE
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_project_truth(registry, observed_at=FIXED_NOW)


def test_verified_requires_evidence(tmp_path):
    registry = tmp_path / "PROJECT_STATE.yaml"
    registry.write_text(
        """
schemaVersion: tradingai-project-truth/v1
workstreams:
  - workstreamId: X
    name: "Claimed verified"
    status: IN_PROGRESS
    verification: VERIFIED
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_project_truth(registry, observed_at=FIXED_NOW)


def test_duplicate_workstream_ids_rejected(tmp_path):
    registry = tmp_path / "PROJECT_STATE.yaml"
    registry.write_text(
        """
schemaVersion: tradingai-project-truth/v1
workstreams:
  - workstreamId: X
    name: "One"
  - workstreamId: X
    name: "Two"
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_project_truth(registry, observed_at=FIXED_NOW)


def test_invalid_status_rejected(tmp_path):
    registry = tmp_path / "PROJECT_STATE.yaml"
    registry.write_text(
        """
schemaVersion: tradingai-project-truth/v1
workstreams:
  - workstreamId: X
    name: "Bad status"
    status: DEFINITELY_DONE
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_project_truth(registry, observed_at=FIXED_NOW)


def test_missing_registry_is_unavailable(tmp_path):
    truth = load_project_truth(tmp_path / "missing.yaml", observed_at=FIXED_NOW)
    assert truth.meta.availability is Availability.UNAVAILABLE
    assert truth.workstreams == ()
