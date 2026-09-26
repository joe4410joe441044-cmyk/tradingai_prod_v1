"""WORK I Phase A focused tests: observational Stage 0-5 producer wiring.

These tests exercise the Phase A adapter/facade and the thin producer hooks.
They never start the production runtime, never touch the trading trace and write
only under ``tmp_path`` (or the ``CYCLE_EVIDENCE_PATH`` override).
"""

import copy
import os
from datetime import datetime, timezone

import pytest

from backend.runtime.cycle_evidence import (
    AvailabilityState,
    EvidenceType,
    LifecycleStage,
)
from backend.runtime.cycle_evidence_capture import (
    CaptureLifecycleState,
    CycleEvidenceCapture,
)
from backend.runtime.cycle_evidence_phase_a import (
    CYCLE_ID_SOURCE_AUTHORITY,
    CYCLE_ID_SOURCE_PHASE_A,
    OUTCOME_CAPTURED,
    OUTCOME_CONFLICT,
    OUTCOME_DISABLED,
    OUTCOME_DUPLICATE,
    OUTCOME_MODE_UNRESOLVED,
    OUTCOME_OBSERVATION_FAILED,
    OUTCOME_OUT_OF_PHASE_A_SCOPE,
    OUTCOME_REJECTED,
    OUTCOME_STORE_ERROR,
    PHASE_A_ENABLED_ENV,
    StageObservation,
    build_phase_a_cycle_key,
    capture_stage_observation,
    observe_ai_decision,
    observe_feature_evidence,
    observe_market_context,
    observe_market_selection,
    observe_parameter_context,
    observe_strategy_signal,
    phase_a_enabled,
    reset_phase_a_store,
)
from backend.runtime.cycle_evidence_store import CycleEvidenceStore

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _isolated_phase_a_default(monkeypatch, tmp_path):
    """Never let the Phase A default store point at the production path."""

    monkeypatch.setenv("CYCLE_EVIDENCE_PATH", str(tmp_path / "default-evidence.jsonl"))
    monkeypatch.delenv(PHASE_A_ENABLED_ENV, raising=False)
    reset_phase_a_store()
    yield
    reset_phase_a_store()


def _store(tmp_path) -> CycleEvidenceStore:
    return CycleEvidenceStore(tmp_path / "cycle_evidence.jsonl")


def _snapshot():
    return {
        "parameterSetId": "paper-baseline",
        "scope": "PAPER_ONLY",
        "source": "PAPER_CONSTANT_BASELINE",
        "configuredRevision": 3,
        "effectiveRevision": 2,
        "authorityStatus": "PERSISTED",
        "storeStatus": "VALID",
        "parameterSetStatus": "ACTIVE",
        "featureContract": "MICRO_V1",
        "capturedAt": "2026-01-01T00:00:00Z",
        "parameters": {"risk_per_trade_pct": 0.5, "maximum_spread_pct": 0.5},
    }


def _ams_result():
    return {
        "autoSelectionCycleId": "ams-4a-abc123",
        "startedAt": "2026-01-01T00:00:00Z",
        "evaluatedAt": "2026-01-01T00:00:01Z",
        "mode": "AUTO_PAPER",
        "currentActiveSymbol": "BTCUSDT",
        "topCandidateSymbol": "ETHUSDT",
        "proposedSymbol": "ETHUSDT",
        "finalActiveSymbol": "ETHUSDT",
        "scannerCycleId": "ams-2a-1",
        "rankingCycleId": "ams-1c-1",
        "auditEventId": "audit-1",
        "selectionProposalId": "proposal-1",
        "switchTransactionId": None,
        "status": "COMPLETED",
        "reasonCodes": ["INITIAL_SELECTION"],
    }


def _microstructure(symbol="BTCUSDT"):
    return {
        "symbol": symbol,
        "runtimeId": "rt-1",
        "buyPressure": 0.6,
        "sellPressure": 0.4,
        "pressureDiff": 0.2,
        "strategyTotalVolume": 12.5,
        "spread": 0.0005,
        "orderbookAggregationMode": "TOP_N",
        "orderbookAggregationDepth": 5,
        "featureContract": "MICRO_V1",
        "imbalanceStrength": 0.6,
        "momentumPersistence": 0.2,
        "normalizedMomentum": 0.1,
        "momentumDirection": "UP",
        "directionPurity": 0.7,
        "normalizedSpreadQuality": 0.8,
        "normalizedLiquidityQuality": 0.9,
        "triggeredReasons": [],
        "detectorDetails": {"absorption": {"triggered": False, "score": 0.1}},
        "strategyMomentumFeatures": {"normalizedMomentum": 0.1},
        "parameterAuthority": {
            "parameterSetId": "paper-baseline",
            "effectiveRevision": 2,
        },
    }


def _strategy_state():
    return {
        "symbol": "BTCUSDT",
        "direction": "LONG",
        "decision": "LONG",
        "confidence": 0.8,
        "executionAllowed": True,
        "suppressionReason": None,
        "featureContract": "MICRO_V1",
        "parameterAuthority": {"configuredRevision": 3, "effectiveRevision": 2},
    }


# 1. flag disabled => complete no-op -------------------------------------


def test_flag_disabled_is_complete_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(PHASE_A_ENABLED_ENV, raising=False)
    store = _store(tmp_path)
    path = store.path

    assert phase_a_enabled() is False
    results = [
        observe_parameter_context("PAPER", _snapshot(), store=store),
        observe_market_selection(_ams_result(), store=store),
        observe_market_context(_microstructure(), store=store, mode="PAPER"),
        observe_feature_evidence(_microstructure(), store=store, mode="PAPER"),
        observe_strategy_signal(
            _strategy_state(), store=store, trace_id="t1", mode="PAPER"
        ),
        observe_ai_decision(store=store, trace_id="t1", mode="PAPER"),
    ]
    assert all(result.outcome == OUTCOME_DISABLED for result in results)
    assert all(result.enabled is False for result in results)
    assert not path.exists()


def test_flag_disabled_short_circuits_before_adapting(monkeypatch):
    monkeypatch.delenv(PHASE_A_ENABLED_ENV, raising=False)

    def _boom(*args, **kwargs):
        raise AssertionError("adapter must not run when Phase A is disabled")

    monkeypatch.setattr(
        "backend.runtime.cycle_evidence_phase_a.market_selection_observation",
        _boom,
    )
    result = observe_market_selection(_ams_result())
    assert result.outcome == OUTCOME_DISABLED


# 2. import / constructor performs no write ------------------------------


def test_import_and_constructor_do_not_write(tmp_path, monkeypatch):
    default_path = tmp_path / "default-evidence.jsonl"
    monkeypatch.setenv("CYCLE_EVIDENCE_PATH", str(default_path))
    reset_phase_a_store()
    assert not default_path.exists()

    store = _store(tmp_path)
    CycleEvidenceCapture(store, cycle_id="no-write", mode="PAPER")
    CycleEvidenceStore(tmp_path / "another.jsonl")
    assert not store.path.exists()
    assert not default_path.exists()


# 3. Stage 0-5 each capture ----------------------------------------------


def test_all_phase_a_stages_capture(tmp_path):
    store = _store(tmp_path)
    results = [
        observe_parameter_context("PAPER", _snapshot(), store=store, enabled=True),
        observe_market_selection(_ams_result(), store=store, enabled=True),
        observe_market_context(
            _microstructure(), store=store, enabled=True, mode="PAPER"
        ),
        observe_feature_evidence(
            _microstructure(), store=store, enabled=True, mode="PAPER"
        ),
        observe_strategy_signal(
            _strategy_state(),
            store=store,
            enabled=True,
            trace_id="trace-1",
            mode="PAPER",
            status="LONG",
        ),
        observe_ai_decision(
            store=store, enabled=True, trace_id="trace-1", mode="PAPER"
        ),
    ]
    assert [r.outcome for r in results] == [OUTCOME_CAPTURED] * 6
    records = store.load()
    by_stage = {record["lifecycle_stage"]: record for record in records}
    assert set(by_stage) == {0, 1, 2, 3, 4, 5}
    assert by_stage[0]["evidence_type"] == EvidenceType.PARAMETER_REVISION.value
    assert by_stage[1]["evidence_type"] == EvidenceType.AUTO_CANDIDATE_SELECTION.value
    assert by_stage[2]["evidence_type"] == EvidenceType.MARKET_CONTEXT.value
    assert by_stage[3]["evidence_type"] == EvidenceType.FEATURE_EVIDENCE.value
    assert by_stage[4]["evidence_type"] == EvidenceType.STRATEGY_SIGNAL.value
    assert by_stage[5]["evidence_type"] == EvidenceType.AI_DECISION.value


def test_market_selection_uses_authority_cycle_id(tmp_path):
    store = _store(tmp_path)
    result = observe_market_selection(_ams_result(), store=store, enabled=True)
    assert result.outcome == OUTCOME_CAPTURED
    record = store.load()[0]
    assert record["cycle_id"] == "ams-4a-abc123"
    assert record["payload"]["cycleIdSource"] == CYCLE_ID_SOURCE_AUTHORITY
    assert "phaseACorrelationKey" not in record["links"]


def test_non_authority_stages_use_phase_a_correlation_key(tmp_path):
    store = _store(tmp_path)
    observe_market_context(_microstructure(), store=store, enabled=True, mode="PAPER")
    record = store.load()[0]
    assert record["cycle_id"].startswith("phase-a:s2:")
    assert record["payload"]["cycleIdSource"] == CYCLE_ID_SOURCE_PHASE_A
    assert record["links"]["phaseACorrelationKey"] == record["cycle_id"]


# 4. unavailable fields are explicit -------------------------------------


def test_unavailable_fields_are_explicit(tmp_path):
    store = _store(tmp_path)
    observe_parameter_context("PAPER", _snapshot(), store=store, enabled=True)
    observe_market_context(_microstructure(), store=store, enabled=True, mode="PAPER")
    records = {record["lifecycle_stage"]: record for record in store.load()}

    stage0 = records[0]["availability"]
    assert stage0["symbol"] == AvailabilityState.NOT_APPLICABLE.value
    assert stage0["trade_id"] == AvailabilityState.NOT_APPLICABLE.value
    assert stage0["strategyRevision"] == AvailabilityState.NOT_CAPTURED.value

    stage2 = records[2]["availability"]
    assert stage2["marketDataSource"] == AvailabilityState.NOT_CAPTURED.value
    assert stage2["marketUpdateTime"] == AvailabilityState.NOT_CAPTURED.value
    assert stage2["timeframe"] == AvailabilityState.NOT_APPLICABLE.value


# 5. secret redaction / rejection ----------------------------------------


def _secret_observation() -> StageObservation:
    return StageObservation(
        stage=3,
        evidence_type=EvidenceType.FEATURE_EVIDENCE,
        status=CaptureLifecycleState.COMPLETED,
        mode="PAPER",
        payload={"apiKey": "SUPER-SECRET", "token": "abc", "featureContract": "V1"},
        availability={
            "timeframe": AvailabilityState.NOT_APPLICABLE.value,
            "trade_id": AvailabilityState.NOT_APPLICABLE.value,
            "correlation_id": AvailabilityState.NOT_CAPTURED.value,
        },
        symbol="BTCUSDT",
        cycle_id="phase-a:test-secret",
        event_key="secret-event",
        stage_name="FEATURE_BUILDER",
    )


def test_secret_fields_are_redacted(tmp_path):
    store = _store(tmp_path)
    result = capture_stage_observation(
        _secret_observation(), store=store, enabled=True
    )
    assert result.outcome == OUTCOME_CAPTURED
    record = store.load()[0]
    assert "apiKey" not in record["payload"]
    assert "token" not in record["payload"]
    assert record["redaction"]["applied"] is True


def test_secret_fields_can_be_rejected(tmp_path):
    from backend.runtime.cycle_evidence import SecretPolicy

    store = _store(tmp_path)
    result = capture_stage_observation(
        _secret_observation(),
        store=store,
        enabled=True,
        secret_policy=SecretPolicy.REJECT,
    )
    assert result.outcome == OUTCOME_REJECTED
    assert "secret" in (result.error or "").lower()
    assert not store.path.exists()


# 6. idempotent retry ----------------------------------------------------


def test_identical_retry_is_idempotent(tmp_path):
    store = _store(tmp_path)
    observation = _secret_observation()
    first = capture_stage_observation(observation, store=store, enabled=True)
    second = capture_stage_observation(observation, store=store, enabled=True)
    assert first.outcome == OUTCOME_CAPTURED
    assert second.outcome == OUTCOME_DUPLICATE
    assert len(store.load()) == 1


# 7. conflicting content for the same event ------------------------------


def test_conflicting_content_is_detected(tmp_path):
    store = _store(tmp_path)
    original = _secret_observation()
    conflicting = StageObservation(
        stage=original.stage,
        evidence_type=original.evidence_type,
        status=original.status,
        mode=original.mode,
        payload={"featureContract": "CHANGED"},
        availability=original.availability,
        symbol=original.symbol,
        cycle_id=original.cycle_id,
        event_key=original.event_key,
        stage_name=original.stage_name,
    )
    first = capture_stage_observation(original, store=store, enabled=True)
    second = capture_stage_observation(conflicting, store=store, enabled=True)
    assert first.outcome == OUTCOME_CAPTURED
    assert second.outcome == OUTCOME_CONFLICT
    assert len(store.load()) == 1


# 8. capture failure leaves the producer result unchanged -----------------


def test_capture_failure_does_not_change_producer_result(tmp_path, monkeypatch):
    store = _store(tmp_path)
    result = _ams_result()
    before = copy.deepcopy(result)

    def _boom(*args, **kwargs):
        raise RuntimeError("injected capture failure")

    monkeypatch.setattr(
        "backend.runtime.cycle_evidence_phase_a._resolve_store", _boom
    )
    observed = observe_market_selection(result, store=store, enabled=True)
    assert observed.outcome == OUTCOME_OBSERVATION_FAILED
    assert result == before


def test_normal_capture_does_not_change_producer_result(tmp_path):
    store = _store(tmp_path)
    result = _ams_result()
    before = copy.deepcopy(result)
    observed = observe_market_selection(result, store=store, enabled=True)
    assert observed.outcome == OUTCOME_CAPTURED
    assert result == before


# 9. store failure leaves the authority result unchanged ------------------


def test_store_failure_does_not_change_authority_result(tmp_path, monkeypatch):
    store = _store(tmp_path)
    result = _ams_result()
    before = copy.deepcopy(result)

    def _append_failure(*args, **kwargs):
        raise RuntimeError("injected store failure")

    monkeypatch.setattr(store, "append", _append_failure)
    observed = observe_market_selection(result, store=store, enabled=True)
    assert observed.outcome == OUTCOME_STORE_ERROR
    assert result == before
    assert not store.path.exists()


# 10. stage number / name mismatch rejected -------------------------------


def test_stage_number_name_mismatch_rejected(tmp_path):
    store = _store(tmp_path)
    observation = StageObservation(
        stage=0,
        stage_name="EXECUTION",
        evidence_type=EvidenceType.PARAMETER_REVISION,
        status=CaptureLifecycleState.COMPLETED,
        mode="PAPER",
        payload={"parameterSetId": "p"},
        cycle_id="phase-a:mismatch",
        event_key="mismatch",
    )
    result = capture_stage_observation(observation, store=store, enabled=True)
    assert result.outcome == OUTCOME_REJECTED
    assert not store.path.exists()


# 11. Phase A boundary refuses Stages 6-14 --------------------------------


@pytest.mark.parametrize("stage", list(range(6, 15)))
def test_phase_a_boundary_rejects_stage_6_to_14(tmp_path, stage):
    store = _store(tmp_path)
    observation = StageObservation(
        stage=stage,
        evidence_type=EvidenceType.PROVENANCE,
        status=CaptureLifecycleState.COMPLETED,
        mode="PAPER",
        payload={"stage": stage},
        cycle_id=f"phase-a:boundary-{stage}",
        event_key=f"boundary-{stage}",
    )
    result = capture_stage_observation(observation, store=store, enabled=True)
    assert result.outcome == OUTCOME_OUT_OF_PHASE_A_SCOPE
    assert not store.path.exists()


# 12. writes only to the explicit tmp_path store --------------------------


def test_no_write_outside_tmp_path(tmp_path, monkeypatch):
    default_path = tmp_path / "default-evidence.jsonl"
    monkeypatch.setenv("CYCLE_EVIDENCE_PATH", str(default_path))
    reset_phase_a_store()
    store = _store(tmp_path)
    observe_market_selection(_ams_result(), store=store, enabled=True)
    assert store.path.exists()
    assert not default_path.exists()
    assert not os.path.exists(os.path.join(REPO_ROOT, "logs/runtime/cycle_evidence.jsonl"))


# extra: mode cannot be guessed -------------------------------------------


def test_unresolved_mode_is_not_captured(tmp_path):
    store = _store(tmp_path)
    result = observe_market_context(_microstructure(), store=store, enabled=True)
    assert result.outcome == OUTCOME_MODE_UNRESOLVED
    assert not store.path.exists()


def test_phase_a_cycle_key_never_invents_authority(tmp_path):
    key, source = build_phase_a_cycle_key(4, trace_id="trace-x")
    assert key == "phase-a:s4:ttrace-x"
    assert source == CYCLE_ID_SOURCE_PHASE_A
    authority_key, authority_source = build_phase_a_cycle_key(
        1, authority_cycle_id="ams-4a-1"
    )
    assert authority_key == "ams-4a-1"
    assert authority_source == CYCLE_ID_SOURCE_AUTHORITY


# integration: real AMS _finish hook --------------------------------------


class _FakeManager:
    def __init__(self):
        self.auto_market_selection_observation = None
        self.published = None

    def set_auto_market_selection_observation(self, observation):
        self.auto_market_selection_observation = observation
        self.published = observation


def test_ams_finish_hook_writes_phase_a_evidence(tmp_path, monkeypatch):
    from backend.auto_market_selection.auto_selection_runtime import (
        AutoMarketSelectionRuntime,
        AutoSelectionCycleResult,
        AutoSelectionCycleStatus,
        AutoSelectionRuntimeMode,
    )

    default_path = tmp_path / "default-evidence.jsonl"
    monkeypatch.setenv("CYCLE_EVIDENCE_PATH", str(default_path))
    monkeypatch.setenv(PHASE_A_ENABLED_ENV, "true")
    reset_phase_a_store()
    try:
        manager = _FakeManager()
        runtime = AutoMarketSelectionRuntime(
            manager,
            universe_provider=lambda: None,
            ticker_provider=lambda: None,
            capital_provider=lambda: None,
            eligibility_provider=lambda universe, capital: {},
            position_provider=lambda: "FLAT",
            pending_order_provider=lambda: {"pending": False},
            emergency_provider=lambda: True,
        )
        moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = AutoSelectionCycleResult(
            "ams-4a-integration",
            moment,
            moment,
            AutoSelectionRuntimeMode.AUTO_PAPER,
            "BTCUSDT",
            "ETHUSDT",
            "ETHUSDT",
            "ETHUSDT",
            "scanner-1",
            "ranking-1",
            "audit-1",
            "proposal-1",
            None,
            AutoSelectionCycleStatus.COMPLETED,
            ("INITIAL_SELECTION",),
        )
        returned = runtime._finish(result)
        assert returned is result
        assert manager.published is not None
        store = CycleEvidenceStore(default_path)
        records = store.load()
        assert len(records) == 1
        assert records[0]["lifecycle_stage"] == int(LifecycleStage.MARKET_SELECTION)
        assert records[0]["cycle_id"] == "ams-4a-integration"
    finally:
        reset_phase_a_store()


# integration: real BotManager parameter-snapshot hook --------------------


def test_bot_manager_parameter_snapshot_hook(tmp_path, monkeypatch):
    from backend.bot_manager.bot_manager import BotManager

    default_path = tmp_path / "default-evidence.jsonl"
    monkeypatch.setenv("CYCLE_EVIDENCE_PATH", str(default_path))
    monkeypatch.setenv(PHASE_A_ENABLED_ENV, "true")
    reset_phase_a_store()
    try:
        BotManager._record_observed_parameter_snapshot("PAPER", _snapshot())
        store = CycleEvidenceStore(default_path)
        records = store.load()
        assert len(records) == 1
        assert records[0]["lifecycle_stage"] == int(LifecycleStage.PARAMETER_CONTEXT)
        assert records[0]["parameter_revision_id"] == "2"
    finally:
        reset_phase_a_store()


# wiring: source-level proof that producer hooks are present -------------


@pytest.mark.parametrize(
    ("relative_path", "snippets"),
    [
        (
            "backend/bot_manager/bot_manager.py",
            ("observe_parameter_context",),
        ),
        (
            "backend/auto_market_selection/auto_selection_runtime.py",
            ("observe_market_selection",),
        ),
        (
            "backend/main.py",
            ("observe_market_context", "observe_feature_evidence"),
        ),
        (
            "backend/runtime/ExecutionRuntime.py",
            ("observe_strategy_signal", "observe_ai_decision"),
        ),
    ],
)
def test_producer_hooks_are_wired(relative_path, snippets):
    path = os.path.join(REPO_ROOT, relative_path)
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    for snippet in snippets:
        assert snippet in source
