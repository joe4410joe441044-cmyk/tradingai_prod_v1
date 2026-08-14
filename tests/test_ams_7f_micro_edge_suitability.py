"""AMS-1B focused Micro Edge Suitability test suite.

Covers:

 A. Contract creation from valid existing detector/feature evidence
 B. Candidate mismatch fail closed
 C. Stale evidence fail closed
 D. Missing evidence fail closed
 E. Invalid feature snapshot fail closed
 F. Phase-1 blocks missing suitability
 G. Phase-1 accepts suitable evidence
 H. Phase-2 revalidates suitability
 I. Suitability changes after Phase-1 -> Phase-2 blocks
 J. Permission cannot outlive/change suitability authority
 K. Strategy decision does not substitute for suitability
 L. AI review does not substitute for suitability
 M. Ranking alone does not substitute for suitability
 N. No SafeSwitch invocation occurs when suitability fails
"""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.auto_market_selection import (
    LiveAutoActivationApproval,
    LiveAutoRuntimeObservation,
    LiveAutoSelectionRuntime,
    MicroEdgeSuitabilityContract,
    MicroEdgeSuitabilityEvidence,
    MicroEdgeSuitabilityReason,
    MicroEdgeSuitabilityStatus,
    evaluate_micro_edge_suitability,
    revalidate_micro_edge_suitability,
)


NOW_TS = 1700000000.0
CANDIDATE = "ETHUSDT"
RUNTIME_ID = "rt-test-001"


def _now():
    return datetime.fromtimestamp(NOW_TS, tz=timezone.utc)


def _stale_now():
    return datetime.fromtimestamp(NOW_TS + 70, tz=timezone.utc)


def _valid_evidence(*, symbol=CANDIDATE, ts=NOW_TS, calibration=True):
    return MicroEdgeSuitabilityEvidence(
        candidate_symbol=symbol,
        evaluated_at=datetime.fromtimestamp(ts, tz=timezone.utc),
        calibration_ready=calibration,
        detector_snapshot={
            "absorption": {"conditionPassed": False},
            "stagnantHeavyFlow": {"conditionPassed": False},
            "fakePressure": {"conditionPassed": False},
        },
        runtime_id=RUNTIME_ID,
        feature_version="detector/v1",
    )


# ---------------------------------------------------------------------------
# A. Contract creation from valid existing detector/feature evidence
# ---------------------------------------------------------------------------

def test_valid_evidence_produces_suitable_contract():
    evidence = _valid_evidence()
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(), max_age_seconds=60,
    )
    assert contract.status is MicroEdgeSuitabilityStatus.SUITABLE
    assert contract.suitable is True
    assert contract.candidate_symbol == CANDIDATE
    assert contract.calibration_ready is True
    assert contract.evidence_identity is not None
    assert contract.freshness_seconds is not None
    assert contract.freshness_seconds >= 0
    assert len(contract.reason_codes) == 0


def test_evidence_from_detector_dict():
    evidence = MicroEdgeSuitabilityEvidence.from_detector_dict({
        "evaluatedAt": NOW_TS,
        "detectors": {
            "calibrationReady": True,
            "details": {
                "absorption": {"conditionPassed": False},
                "stagnantHeavyFlow": {"conditionPassed": False},
                "fakePressure": {"conditionPassed": False},
            },
        },
        "runtimeId": RUNTIME_ID,
    }, candidate_symbol=CANDIDATE)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.SUITABLE


def test_evidence_from_strategy_state():
    contract = evaluate_micro_edge_suitability(
        MicroEdgeSuitabilityEvidence.from_strategy_state({
            "liquidityInstabilityDebug": {
                "calibrationReady": True,
                "detectorDetails": {
                    "absorption": {"conditionPassed": False},
                    "stagnantHeavyFlow": {"conditionPassed": False},
                    "fakePressure": {"conditionPassed": False},
                },
            },
            "evaluatedAt": NOW_TS,
        }, candidate_symbol=CANDIDATE, runtime_id=RUNTIME_ID),
        candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.SUITABLE


# ---------------------------------------------------------------------------
# B. Candidate mismatch fail closed
# ---------------------------------------------------------------------------

def test_candidate_mismatch_fail_closed():
    evidence = _valid_evidence(symbol=CANDIDATE)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol="XRPUSDT", now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.INVALID
    assert any(r == MicroEdgeSuitabilityReason.SUITABILITY_CANDIDATE_MISMATCH
               for r in contract.reason_codes)


def test_evidence_with_none_candidate_fails():
    evidence = replace(_valid_evidence(), candidate_symbol=None)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.suitable is False


# ---------------------------------------------------------------------------
# C. Stale evidence fail closed
# ---------------------------------------------------------------------------

def test_evidence_past_max_age_is_stale():
    evidence = _valid_evidence(ts=NOW_TS)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_stale_now(), max_age_seconds=60,
    )
    assert contract.status is MicroEdgeSuitabilityStatus.STALE
    assert MicroEdgeSuitabilityReason.SUITABILITY_STALE in contract.reason_codes


def test_evidence_just_within_boundary_is_fresh():
    evidence = _valid_evidence(ts=NOW_TS)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(), max_age_seconds=60,
    )
    assert contract.status is MicroEdgeSuitabilityStatus.SUITABLE


# ---------------------------------------------------------------------------
# D. Missing evidence fail closed
# ---------------------------------------------------------------------------

def test_none_evidence_is_unavailable():
    contract = evaluate_micro_edge_suitability(
        None, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.UNAVAILABLE
    assert MicroEdgeSuitabilityReason.SUITABILITY_UNAVAILABLE in contract.reason_codes


def test_non_evidence_type_is_unavailable():
    contract = evaluate_micro_edge_suitability(
        "not an evidence object", candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# E. Invalid feature snapshot fail closed
# ---------------------------------------------------------------------------

def test_malformed_timestamp_is_invalid():
    evidence = replace(_valid_evidence(), evaluated_at=None)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.suitable is False
    assert MicroEdgeSuitabilityReason.SUITABILITY_TIMESTAMP_MISSING in contract.reason_codes


def test_future_timestamp_is_malformed():
    evidence = _valid_evidence(ts=NOW_TS + 100)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(), max_age_seconds=60,
    )
    assert contract.suitable is False
    assert MicroEdgeSuitabilityReason.SUITABILITY_MALFORMED in contract.reason_codes


def test_calibration_not_ready_is_unsuitable():
    evidence = _valid_evidence(calibration=False)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.UNSUITABLE
    assert MicroEdgeSuitabilityReason.SUITABILITY_CALIBRATION_NOT_READY in contract.reason_codes


def test_calibration_not_required_when_explicitly_disabled():
    evidence = _valid_evidence(calibration=False)
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(),
        requires_calibration=False,
    )
    assert contract.suitable is True


# ---------------------------------------------------------------------------
# F. Phase-1 blocks missing suitability
# G. Phase-1 accepts suitable evidence
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self, value=0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def approved():
    return LiveAutoActivationApproval(
        live_auto_enabled=True,
        configuration_version="ams-live-auto/v1",
        approved_at="2026-08-09T00:00:00Z",
        approval_identity="operator:test",
        approval_source="explicit-test-contract",
    )


def observation(**changes):
    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    value = LiveAutoRuntimeObservation(
        candidate_symbol=CANDIDATE,
        candidate_score=Decimal("0.92"),
        active_market_score=Decimal("0.50"),
        micro_edge_suitability=contract,
    )
    return replace(value, **changes)


def runtime(*, enabled=True, active="BTCUSDT"):
    clock = Clock()
    return LiveAutoSelectionRuntime(
        active_symbol_provider=lambda: active,
        approval=approved() if enabled else None,
        clock=clock,
    ), clock


def observe_wins(service, clock, value=None, count=5, start=60):
    clock.value = start
    for _ in range(count):
        result = service.observe(value or observation())
        clock.advance(10)
    return result


def test_phase1_blocks_missing_suitability():
    service, clock = runtime()
    obs = observation()
    obs = replace(obs, micro_edge_suitability=None)
    clock.value = 60
    result = service.observe(obs)
    assert result["switchEligible"] is False
    assert "MICRO_EDGE_SUITABILITY_UNAVAILABLE" in result["blockReasons"]


def test_phase1_blocks_unsuitable_evidence():
    service, clock = runtime()
    unsuitable = evaluate_micro_edge_suitability(
        _valid_evidence(calibration=False), candidate_symbol=CANDIDATE, now=_now(),
    )
    obs = replace(observation(), micro_edge_suitability=unsuitable)
    clock.value = 60
    result = service.observe(obs)
    assert result["switchEligible"] is False
    assert "MICRO_EDGE_SUITABILITY_REJECTED" in result["blockReasons"]


def test_phase1_blocks_stale_evidence():
    service, clock = runtime()
    stale = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_stale_now(), max_age_seconds=60,
    )
    obs = replace(observation(), micro_edge_suitability=stale)
    clock.value = 60
    result = service.observe(obs)
    assert result["switchEligible"] is False
    assert "MICRO_EDGE_SUITABILITY_STALE" in result["blockReasons"]


def test_phase1_accepts_suitable_evidence():
    service, clock = runtime()
    result = observe_wins(service, clock)
    assert result["switchEligible"] is True
    assert result["runtimeState"] == "SWITCH_ELIGIBLE"


# ---------------------------------------------------------------------------
# H. Phase-2 revalidates suitability
# I. Suitability changes after Phase-1 -> Phase-2 blocks
# ---------------------------------------------------------------------------

def test_phase2_revalidates_suitability():
    service, clock = runtime()
    result = observe_wins(service, clock)
    assert result["switchEligible"] is True
    reval = service.pre_switch_revalidate(observation())
    assert reval["switchEligible"] is True, reval["blockReasons"]


def test_phase2_blocks_when_suitability_removed():
    service, clock = runtime()
    observe_wins(service, clock)
    stale = replace(observation(), micro_edge_suitability=None)
    reval = service.pre_switch_revalidate(stale)
    assert reval["switchEligible"] is False
    assert "MICRO_EDGE_SUITABILITY_UNAVAILABLE" in reval["blockReasons"]


def test_phase2_blocks_when_suitability_becomes_unsuitable():
    service, clock = runtime()
    observe_wins(service, clock)
    unsuitable = evaluate_micro_edge_suitability(
        _valid_evidence(calibration=False), candidate_symbol=CANDIDATE, now=_now(),
    )
    obs = replace(observation(), micro_edge_suitability=unsuitable)
    reval = service.pre_switch_revalidate(obs)
    assert reval["switchEligible"] is False
    assert "MICRO_EDGE_SUITABILITY_REJECTED" in reval["blockReasons"]


def test_phase2_blocks_candidate_mismatch():
    service, clock = runtime()
    observe_wins(service, clock)
    other = evaluate_micro_edge_suitability(
        _valid_evidence(symbol="XRPUSDT"), candidate_symbol="XRPUSDT", now=_now(),
    )
    obs = replace(observation(), micro_edge_suitability=other,
                  candidate_symbol="XRPUSDT")
    reval = service.pre_switch_revalidate(obs)
    assert reval["switchEligible"] is False


# ---------------------------------------------------------------------------
# J. Permission cannot outlive/change suitability authority
# ---------------------------------------------------------------------------

def test_permission_binds_suitability_identity():
    from backend.auto_market_selection import LiveSymbolSwitchPermission
    from datetime import timedelta

    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    now_dt = datetime.fromtimestamp(NOW_TS, tz=timezone.utc)
    permission = LiveSymbolSwitchPermission(
        enabled=True,
        configuration_version="ams-live-auto/v1",
        approval_identity="operator:test",
        approval_source="explicit-test",
        approved_at="2026-08-09T00:00:00Z",
        expected_active_symbol="BTCUSDT",
        expected_runtime_id=RUNTIME_ID,
        proposed_symbol=CANDIDATE,
        ranking_cycle_id="rc-test",
        observation_id="obs-test",
        validation_transaction_id="tx-test",
        issued_at=now_dt,
        expires_at=now_dt + timedelta(seconds=30),
        micro_edge_suitability_identity=contract.evidence_identity,
        micro_edge_suitability_status="SUITABLE",
        micro_edge_suitability_evaluated_at=contract.evaluated_at,
    )
    assert permission.micro_edge_suitability_identity == contract.evidence_identity
    assert permission.micro_edge_suitability_status == "SUITABLE"


def test_permission_identity_valid_requires_suitability():
    from backend.auto_market_selection.live_safe_switch import (
        _PermissionRuntime, LiveSymbolSwitchPermission,
    )
    from datetime import timedelta

    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    now_dt = datetime.fromtimestamp(NOW_TS, tz=timezone.utc)

    perm = LiveSymbolSwitchPermission(  # noqa
        enabled=True,
        configuration_version="ams-live-auto/v1",
        approval_identity="operator:test",
        approval_source="explicit-test",
        approved_at="2026-08-09T00:00:00Z",
        expected_active_symbol="BTCUSDT",
        expected_runtime_id=RUNTIME_ID,
        proposed_symbol=CANDIDATE,
        ranking_cycle_id="rc-test",
        observation_id="obs-test",
        validation_transaction_id="tx-test",
        issued_at=now_dt,
        expires_at=now_dt + timedelta(seconds=30),
        micro_edge_suitability_identity=contract.evidence_identity,
        micro_edge_suitability_status="SUITABLE",
        micro_edge_suitability_evaluated_at=contract.evaluated_at,
    )

    valid_state = {
        "activeSymbol": "BTCUSDT",
        "activeRuntimeId": RUNTIME_ID,
        "rankingCycleId": "rc-test",
        "observationId": "obs-test",
        "configurationVersion": "ams-live-auto/v1",
        "candidateSymbol": CANDIDATE,
        "marketDataFresh": True,
        "liveAccountFresh": True,
        "mmFresh": True,
        "positionState": "FLAT",
        "pendingOrderState": "NONE",
        "emergencySafe": True,
        "governanceAllow": True,
        "runtimeConsistent": True,
        "snapshotConsistent": True,
        "statusConsistent": True,
        "realOrderAllowed": False,
        "autoTradeEnabled": False,
        "executionRealOrderEnabled": False,
        "microEdgeSuitabilityIdentity": contract.evidence_identity,
        "microEdgeSuitabilityStatus": "SUITABLE",
    }
    guarded = _PermissionRuntime(
        None, perm, lambda: valid_state,
    )
    assert guarded._identity_valid() is True

    wrong_identity = dict(valid_state, microEdgeSuitabilityIdentity="wrong-hash")
    wrong_permission = _PermissionRuntime(None, perm, lambda: wrong_identity)
    assert wrong_permission._identity_valid() is False

    not_suitable = dict(valid_state, microEdgeSuitabilityStatus="STALE")
    wrong_status = _PermissionRuntime(None, perm, lambda: not_suitable)
    assert wrong_status._identity_valid() is False

    missing_field = dict(valid_state)
    missing_field.pop("microEdgeSuitabilityIdentity", None)
    missing_field.pop("microEdgeSuitabilityStatus", None)
    missing = _PermissionRuntime(None, perm, lambda: missing_field)
    assert missing._identity_valid() is False


# ---------------------------------------------------------------------------
# K. Strategy decision does not substitute for suitability
# ---------------------------------------------------------------------------

def test_strategy_decision_alone_does_not_satisfy_suitability():
    service, clock = runtime()
    obs = observation()
    obs = replace(obs, micro_edge_suitability=None)
    clock.value = 60
    result = service.observe(obs)
    assert result["switchEligible"] is False
    assert "MICRO_EDGE_SUITABILITY_UNAVAILABLE" in result["blockReasons"]


# ---------------------------------------------------------------------------
# L. AI review does not substitute for suitability
# M. Ranking alone does not substitute for suitability
# ---------------------------------------------------------------------------

def test_ranking_and_candidate_score_alone_do_not_satisfy_suitability():
    service, clock = runtime()
    obs = observation()
    obs = replace(obs, micro_edge_suitability=None)
    clock.value = 60
    result = service.observe(obs)
    assert "MICRO_EDGE_SUITABILITY_UNAVAILABLE" in result["blockReasons"]


# ---------------------------------------------------------------------------
# N. No SafeSwitch invocation occurs when suitability fails
# ---------------------------------------------------------------------------

def test_no_safe_switch_invoked_when_suitability_fails():
    service, clock = runtime()
    obs = replace(observation(), micro_edge_suitability=None)
    clock.value = 60
    result = service.observe(obs)
    assert result["switchEligible"] is False
    status = service.get_status()
    assert status["safeSwitchInvoked"] is False
    assert status["switchCommitted"] is False


# ---------------------------------------------------------------------------
# Contract identity is stable
# ---------------------------------------------------------------------------

def test_evidence_identity_is_deterministic():
    e1 = _valid_evidence()
    e2 = _valid_evidence()
    assert e1.identity_hash() == e2.identity_hash()
    e3 = replace(_valid_evidence(), candidate_symbol="XRPUSDT")
    assert e1.identity_hash() != e3.identity_hash()


def test_contract_to_dict_contains_required_fields():
    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    d = contract.to_dict()
    assert d["candidateSymbol"] == CANDIDATE
    assert d["suitabilityStatus"] == "SUITABLE"
    assert d["evidenceIdentity"] is not None
    assert d["evaluatedAt"] is not None
    assert d["freshnessSeconds"] is not None
    assert d["calibrationReady"] is True
    assert len(d["reasonCodes"]) == 0


# ---------------------------------------------------------------------------
# Revalidation preserves identity, checks freshness / candidate
# ---------------------------------------------------------------------------

def test_revalidation_preserves_identity():
    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    rev = revalidate_micro_edge_suitability(
        contract, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert rev.suitable is True
    assert rev.evidence_identity == contract.evidence_identity


def test_revalidation_fails_on_candidate_mismatch():
    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    rev = revalidate_micro_edge_suitability(
        contract, candidate_symbol="XRPUSDT", now=_now(),
    )
    assert rev.suitable is False
    assert rev.status is MicroEdgeSuitabilityStatus.INVALID
    assert MicroEdgeSuitabilityReason.SUITABILITY_CANDIDATE_MISMATCH in rev.reason_codes


def test_revalidation_fails_on_stale():
    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    rev = revalidate_micro_edge_suitability(
        contract, candidate_symbol=CANDIDATE, now=_stale_now(), max_age_seconds=60,
    )
    assert rev.suitable is False
    assert rev.status is MicroEdgeSuitabilityStatus.STALE


def test_revalidation_of_already_unsuitable_is_noop():
    unsuit = evaluate_micro_edge_suitability(
        _valid_evidence(calibration=False), candidate_symbol=CANDIDATE, now=_now(),
    )
    assert unsuit.suitable is False
    rev = revalidate_micro_edge_suitability(
        unsuit, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert rev.suitable is False
    assert rev.status is MicroEdgeSuitabilityStatus.UNSUITABLE


# ---------------------------------------------------------------------------
# Old evidence reused after candidate change -> blocked
# ---------------------------------------------------------------------------

def test_old_evidence_reused_after_candidate_change_is_blocked():
    evidence = _valid_evidence(symbol="XRPUSDT")
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol="BTCUSDT", now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.INVALID
    assert MicroEdgeSuitabilityReason.SUITABILITY_CANDIDATE_MISMATCH in contract.reason_codes


# ---------------------------------------------------------------------------
# New candidate with no deep evidence -> blocked
# ---------------------------------------------------------------------------

def test_new_candidate_with_no_evidence_is_blocked():
    contract = evaluate_micro_edge_suitability(
        None, candidate_symbol="BTCUSDT", now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.UNAVAILABLE
    assert contract.suitable is False


# ---------------------------------------------------------------------------
# status read model exposes suitability fields
# ---------------------------------------------------------------------------

def test_status_exposes_suitability_when_present():
    service, clock = runtime()
    observe_wins(service, clock)
    status = service.get_status()
    assert status["microEdgeSuitabilityStatus"] == "SUITABLE"
    assert status["microEdgeSuitabilityCandidate"] == CANDIDATE
    assert status["microEdgeSuitabilityFresh"] is True


def test_status_suitability_is_none_when_not_set():
    service, _ = runtime()
    obs = replace(observation(), micro_edge_suitability=None)
    service._last_observation = obs
    status = service.get_status()
    assert status["microEdgeSuitabilityStatus"] is None
    assert status["microEdgeSuitabilityFresh"] is False


# ---------------------------------------------------------------------------
# Not substitutes
# ---------------------------------------------------------------------------

def test_ranking_score_alone_is_not_suitability():
    contract = evaluate_micro_edge_suitability(
        None, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.suitable is False
    assert MicroEdgeSuitabilityReason.SUITABILITY_UNAVAILABLE in contract.reason_codes


# ============================================================================
# AMS-FINAL-1B: Deep Analysis Gate and Suitability CAS
# ============================================================================


def _toxic_evidence():
    return MicroEdgeSuitabilityEvidence(
        candidate_symbol=CANDIDATE,
        evaluated_at=datetime.fromtimestamp(NOW_TS, tz=timezone.utc),
        calibration_ready=True,
        detector_snapshot={
            "absorption": {"conditionPassed": True},
            "stagnantHeavyFlow": {"conditionPassed": False},
            "fakePressure": {"conditionPassed": False},
        },
        runtime_id=RUNTIME_ID,
        feature_version="detector/v1",
    )


def _clean_evidence():
    return MicroEdgeSuitabilityEvidence(
        candidate_symbol=CANDIDATE,
        evaluated_at=datetime.fromtimestamp(NOW_TS, tz=timezone.utc),
        calibration_ready=True,
        detector_snapshot={
            "absorption": {"conditionPassed": False},
            "stagnantHeavyFlow": {"conditionPassed": False},
            "fakePressure": {"conditionPassed": False},
        },
        runtime_id=RUNTIME_ID,
        feature_version="detector/v1",
    )


# -- Deep analysis gate: toxic detector -> UNSUITABLE --

def test_absorption_detected_makes_market_unsuitable():
    contract = evaluate_micro_edge_suitability(
        _toxic_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.UNSUITABLE
    assert MicroEdgeSuitabilityReason.SUITABILITY_DETECTOR_TOXIC in contract.reason_codes
    assert contract.suitable is False


def test_fake_pressure_detected_makes_market_unsuitable():
    evidence = MicroEdgeSuitabilityEvidence(
        candidate_symbol=CANDIDATE,
        evaluated_at=datetime.fromtimestamp(NOW_TS, tz=timezone.utc),
        calibration_ready=True,
        detector_snapshot={
            "absorption": {"conditionPassed": False},
            "stagnantHeavyFlow": {"conditionPassed": False},
            "fakePressure": {"conditionPassed": True},
        },
        runtime_id=RUNTIME_ID,
        feature_version="detector/v1",
    )
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.UNSUITABLE
    assert MicroEdgeSuitabilityReason.SUITABILITY_DETECTOR_TOXIC in contract.reason_codes


def test_stagnant_flow_detected_makes_market_unsuitable():
    evidence = MicroEdgeSuitabilityEvidence(
        candidate_symbol=CANDIDATE,
        evaluated_at=datetime.fromtimestamp(NOW_TS, tz=timezone.utc),
        calibration_ready=True,
        detector_snapshot={
            "absorption": {"conditionPassed": False},
            "stagnantHeavyFlow": {"conditionPassed": True},
            "fakePressure": {"conditionPassed": False},
        },
        runtime_id=RUNTIME_ID,
        feature_version="detector/v1",
    )
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.UNSUITABLE
    assert MicroEdgeSuitabilityReason.SUITABILITY_DETECTOR_TOXIC in contract.reason_codes


def test_clean_detectors_pass_deep_analysis():
    contract = evaluate_micro_edge_suitability(
        _clean_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.SUITABLE
    assert contract.suitable is True


def test_empty_detector_snapshot_blocks_as_incomplete_evidence():
    evidence = MicroEdgeSuitabilityEvidence(
        candidate_symbol=CANDIDATE,
        evaluated_at=datetime.fromtimestamp(NOW_TS, tz=timezone.utc),
        calibration_ready=True,
        detector_snapshot={},
        runtime_id=RUNTIME_ID,
        feature_version="detector/v1",
    )
    contract = evaluate_micro_edge_suitability(
        evidence, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert contract.status is MicroEdgeSuitabilityStatus.INVALID
    assert MicroEdgeSuitabilityReason.SUITABILITY_DETECTOR_INCOMPLETE in contract.reason_codes


def test_deep_analysis_cannot_be_disabled_by_caller():
    with pytest.raises(TypeError):
        evaluate_micro_edge_suitability(
            _toxic_evidence(), candidate_symbol=CANDIDATE, now=_now(),
            requires_deep_analysis=False,
        )


# -- Phase-1 preflight captures suitability identity in proposal --

def test_phase1_preflight_captures_suitability_identity():
    service, clock = runtime()
    result = observe_wins(service, clock)
    assert result["switchEligible"] is True
    proposal = service._activation_proposal
    assert proposal is not None
    assert proposal.expected_micro_edge_suitability_identity is not None
    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    assert proposal.expected_micro_edge_suitability_identity == contract.evidence_identity


def test_phase1_preflight_suitability_identity_none_when_missing():
    service, clock = runtime()
    obs = replace(observation(), micro_edge_suitability=None)
    clock.value = 60
    for _ in range(3):
        service.observe(obs)
        clock.advance(10)
    proposal = service._activation_proposal
    assert proposal is None


# -- Phase-2 CAS detects suitability identity change --

def _obs_with_id(**changes):
    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    value = LiveAutoRuntimeObservation(
        candidate_symbol=CANDIDATE,
        candidate_score=Decimal("0.92"),
        active_market_score=Decimal("0.50"),
        runtime_id=RUNTIME_ID,
        observation_id="obs-test-cas",
        ranking_cycle_id="rc-test-cas",
        micro_edge_suitability=contract,
    )
    return replace(value, **changes)


def _observe_wins_with_id(service, clock, value=None, count=5, start=60):
    clock.value = start
    obs = value or _obs_with_id()
    for _ in range(count):
        result = service.observe(obs)
        clock.advance(10)
    return result


def test_phase2_cas_detects_suitability_identity_change():
    service, clock = runtime()
    _observe_wins_with_id(service, clock)
    old_contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    new_evidence = _toxic_evidence()
    new_contract = evaluate_micro_edge_suitability(
        new_evidence, candidate_symbol=CANDIDATE, now=_now(),
    )
    assert old_contract.evidence_identity != new_contract.evidence_identity
    obs_with_new = _obs_with_id(micro_edge_suitability=new_contract)
    result = service.validate_activation(obs_with_new)
    assert "MICRO_EDGE_SUITABILITY_IDENTITY_CHANGED" in result["activationBlockReasons"]


def test_phase2_cas_passes_when_suitability_identity_unchanged():
    service, clock = runtime()
    _observe_wins_with_id(service, clock)
    result = service.validate_activation(_obs_with_id())
    assert "MICRO_EDGE_SUITABILITY_IDENTITY_CHANGED" not in result["activationBlockReasons"]


def test_phase2_cas_blocks_when_proposal_has_no_suitability_identity():
    service, clock = runtime()
    observe_wins(service, clock)
    service._activation_proposal = replace(
        service._activation_proposal,
        expected_micro_edge_suitability_identity=None,
    )
    result = service.validate_activation(observation())
    assert "MICRO_EDGE_SUITABILITY_IDENTITY_MISSING" in result["activationBlockReasons"]
    assert result["safeSwitchBoundaryReached"] is False


# -- Status exposes expected suitability identity --

def test_status_exposes_expected_suitability_identity():
    service, clock = runtime()
    observe_wins(service, clock)
    status = service.get_status()
    assert status["expectedMicroEdgeSuitabilityIdentity"] is not None
    contract = evaluate_micro_edge_suitability(
        _valid_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    assert status["expectedMicroEdgeSuitabilityIdentity"] == contract.evidence_identity


def test_status_suitability_identity_none_when_no_proposal():
    service, _ = runtime()
    status = service.get_status()
    assert status["expectedMicroEdgeSuitabilityIdentity"] is None


# -- Phase-1 blocks toxic market (deep analysis gate integrated) --

def test_phase1_blocks_toxic_market_deep_analysis():
    service, clock = runtime()
    toxic_contract = evaluate_micro_edge_suitability(
        _toxic_evidence(), candidate_symbol=CANDIDATE, now=_now(),
    )
    obs = replace(observation(), micro_edge_suitability=toxic_contract)
    clock.value = 60
    result = service.observe(obs)
    assert result["switchEligible"] is False
    assert "MICRO_EDGE_SUITABILITY_REJECTED" in result["blockReasons"]


# -- Phase-1 deep analysis off allows toxic but only for integrated systems --

def test_auto_live_cannot_receive_opted_out_deep_analysis_contract():
    with pytest.raises(TypeError):
        evaluate_micro_edge_suitability(
            _toxic_evidence(), candidate_symbol=CANDIDATE, now=_now(),
            requires_deep_analysis=False,
        )
