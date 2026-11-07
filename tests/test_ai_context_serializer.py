from __future__ import annotations

import json

import pytest

from backend.context import (
    RuntimeTruthSource,
    build_canonical_context,
    context_to_dict,
    to_canonical_json,
    to_markdown,
)
from tests.test_ai_context_support import FIXED_NOW, make_supervisor_snapshot


def _context():
    return build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=RuntimeTruthSource(snapshot=make_supervisor_snapshot()),
    )


def test_json_serialization_is_deterministic():
    first = to_canonical_json(_context())
    second = to_canonical_json(_context())
    assert first == second
    assert ", " not in first
    assert list(json.loads(first)) == sorted(json.loads(first))


def test_json_round_trips_to_plain_dict():
    context = _context()
    payload = to_canonical_json(context)
    decoded = json.loads(payload)
    assert decoded == context_to_dict(context)
    assert decoded["schemaVersion"] == "tradingai-context/v1"
    assert decoded["generatedAt"] == "2026-10-25T00:00:00Z"
    assert decoded["safety"]["liveOrder"] is False


def test_serializer_rejects_non_context():
    with pytest.raises(TypeError):
        to_canonical_json({})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_markdown({})  # type: ignore[arg-type]


def test_markdown_is_deterministic():
    first = to_markdown(_context())
    second = to_markdown(_context())
    assert first == second
    for heading in (
        "# TradingAI Canonical AI Context",
        "## SOURCE TRUTH",
        "## runtime",
        "## moneyManagement",
        "## PROJECT TRUTH",
        "## SAFETY",
        "## FRESHNESS",
    ):
        assert heading in first
    assert "\n\n\n" not in first
