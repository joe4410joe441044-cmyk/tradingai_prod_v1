from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.context import (
    Availability,
    ContextObservation,
    FieldObservation,
    Freshness,
    ProvenanceEntry,
    RuntimeTruthSource,
    SectionMeta,
    ValueState,
    build_canonical_context,
    load_project_truth,
    read_source_truth,
    to_canonical_json,
)
from backend.supervisor.contracts import ReadOnlySupervisorSnapshot
from tests.test_ai_context_support import (
    FIXED_NOW,
    bot_payload,
    make_supervisor_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_deterministic_context_builder():
    snapshot = make_supervisor_snapshot()
    project = load_project_truth(
        REPO_ROOT / "docs/ai/PROJECT_STATE.yaml", observed_at=FIXED_NOW
    )
    source = read_source_truth(REPO_ROOT, observed_at=FIXED_NOW)

    first = build_canonical_context(
        generated_at=FIXED_NOW,
        source_truth=source,
        runtime_truth=RuntimeTruthSource(snapshot=snapshot),
        project_truth=project,
    )
    second = build_canonical_context(
        generated_at=FIXED_NOW,
        source_truth=source,
        runtime_truth=RuntimeTruthSource(snapshot=snapshot),
        project_truth=project,
    )
    assert first == second
    assert to_canonical_json(first) == to_canonical_json(second)


def test_missing_fields_are_not_filled_in():
    bot = bot_payload()
    del bot["autoTradeEnabled"]
    del bot["last_update"]
    snapshot = make_supervisor_snapshot(bot=bot)
    context = build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=RuntimeTruthSource(snapshot=snapshot),
    )
    fields = {item.name: item for item in context.executionControl.fields}
    assert fields["autoTradeEnabled"].state is ValueState.ABSENT
    assert fields["autoTradeEnabled"].value is None
    market_fields = {item.name: item for item in context.market.fields}
    assert market_fields["lastUpdate"].state is ValueState.NULL


def test_stale_source_is_marked_stale():
    bot = bot_payload(freshness="STALE")
    snapshot = make_supervisor_snapshot(bot=bot)
    context = build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=RuntimeTruthSource(snapshot=snapshot),
    )
    assert context.runtime.meta.availability is Availability.STALE
    assert context.runtime.meta.freshness is Freshness.STALE
    assert "runtime" in context.freshness.staleSections


def test_missing_runtime_authority_is_unavailable():
    snapshot = make_supervisor_snapshot(health=None)
    context = build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=RuntimeTruthSource(snapshot=snapshot),
    )
    assert context.health.meta.availability is Availability.UNAVAILABLE
    assert context.health.meta.freshness is Freshness.UNKNOWN


def test_absent_runtime_truth_is_explicitly_unavailable():
    context = build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=RuntimeTruthSource(),
    )
    for name in (
        "runtime",
        "market",
        "moneyManagement",
        "governance",
        "position",
        "orders",
        "smallAccount",
        "account",
        "emergency",
        "health",
    ):
        assert getattr(context, name).meta.availability is Availability.UNAVAILABLE
    assert "position" in context.freshness.unavailableSections
    assert context.freshness.overall is Freshness.UNKNOWN


def test_source_provenance_is_preserved():
    source = read_source_truth(REPO_ROOT, observed_at=FIXED_NOW)
    context = build_canonical_context(
        generated_at=FIXED_NOW,
        source_truth=source,
    )
    readers = {entry.reader for entry in context.provenance.entries}
    assert "source-truth-reader" in readers
    entries = list(context.provenance.entries)
    keys = [
        (
            entry.source,
            entry.reader,
            entry.observedAt.isoformat() if entry.observedAt else "",
            entry.detail or "",
        )
        for entry in entries
    ]
    assert keys == sorted(keys)


def test_secret_values_and_names_are_excluded():
    bot = bot_payload(status="api_key=SUPERSECRET123")
    observation = ContextObservation(
        meta=SectionMeta(
            source="TEST",
            observedAt=FIXED_NOW,
            freshness=Freshness.FRESH,
            availability=Availability.AVAILABLE,
            provenance=(
                ProvenanceEntry(
                    source="TEST",
                    reader="test",
                    observedAt=FIXED_NOW,
                    detail="password=PROVENANCE_SECRET",
                ),
            ),
        ),
        fields=(
            FieldObservation(
                name="apiKey", value="SUPERSECRET456", state=ValueState.PRESENT
            ),
            FieldObservation(
                name="note",
                value="password=SUPERSECRET789",
                state=ValueState.PRESENT,
            ),
        ),
    )
    context = build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=RuntimeTruthSource(
            snapshot=make_supervisor_snapshot(bot=bot),
            extra={"position": observation},
        ),
    )
    payload = to_canonical_json(context)
    for secret in (
        "SUPERSECRET123",
        "SUPERSECRET456",
        "SUPERSECRET789",
        "PROVENANCE_SECRET",
    ):
        assert secret not in payload
    position_fields = {item.name: item.value for item in context.position.fields}
    assert position_fields["apiKey"] == "[REDACTED:SENSITIVE]"
    assert "password=" not in position_fields["note"]


def test_builder_does_not_open_files_network_or_mutate_inputs():
    snapshot = make_supervisor_snapshot()
    snapshot_before = snapshot.model_copy(deep=True)
    project = load_project_truth(
        REPO_ROOT / "docs/ai/PROJECT_STATE.yaml", observed_at=FIXED_NOW
    )
    project_before = project.model_copy(deep=True)

    with patch("builtins.open", side_effect=AssertionError("no file access")):
        with patch("socket.socket", side_effect=AssertionError("no network access")):
            build_canonical_context(
                generated_at=FIXED_NOW,
                runtime_truth=RuntimeTruthSource(snapshot=snapshot),
                project_truth=project,
            )

    assert snapshot == snapshot_before
    assert project == project_before


def test_existing_supervisor_snapshot_is_reused_without_contract_change():
    snapshot = make_supervisor_snapshot()
    assert isinstance(snapshot, ReadOnlySupervisorSnapshot)
    before = snapshot.stable_json()
    context = build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=RuntimeTruthSource(snapshot=snapshot),
    )
    assert snapshot.stable_json() == before
    assert context.moneyManagement.meta.availability is Availability.AVAILABLE
    mm_fields = {item.name: item for item in context.moneyManagement.fields}
    assert mm_fields["equity"].state is ValueState.PRESENT
    assert mm_fields["equity"].value == "1000"
    assert context.governance.meta.source == "GOVERNANCE_RUNTIME"
    assert context.emergency.meta.availability is Availability.AVAILABLE


def test_generated_at_must_be_timezone_aware():
    from datetime import datetime

    with pytest.raises(ValueError):
        build_canonical_context(generated_at=datetime(2026, 10, 25))
