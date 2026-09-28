"""Tests for the observation-only Trading Cycle diagnostics adapter (J2)."""

from copy import deepcopy

import pytest

from backend.runtime.cycle_diagnostics import (
    Actionable,
    BlockerType,
    STEP_COUNT,
    StepStatus,
    build_trading_cycle_diagnostics,
)
from backend.runtime.runtime_health_snapshot import build_trading_decision_snapshot


def _strategy_hold_result(
    *,
    suppression_reason="ENTRY_THRESHOLD_NOT_MET",
    conditions=None,
    execution_allowed=False,
    blocking_condition="COMPOSITE_SCORE",
):
    return {
        "strategyRuntimeReached": True,
        "strategyOutput": {
            "strategy": {
                "executionAllowed": execution_allowed,
                "direction": "NEUTRAL",
                "confidence": 0.42,
                "edge": 0.42,
                "minimumConfidence": 0.50,
                "minimumCompositeScore": 0.55,
                "featureContract": "TIME_SYMBOL_NORMALIZED_V1",
                "suppressionReason": suppression_reason,
                "parameterAuthority": {
                    "scope": "PAPER_ONLY",
                    "configuredRevision": 3,
                    "effectiveRevision": 3,
                },
                "entryReadiness": {
                    "available": True,
                    "cycleId": "CYCLE_B",
                    "schemaVersion": 1,
                    "candidateDirection": "BUY",
                    "strategyDecision": "HOLD",
                    "executionAllowed": execution_allowed,
                    "conditions": conditions
                    if conditions is not None
                    else [
                        {
                            "code": "COMPOSITE_SCORE",
                            "status": "FAIL",
                            "currentValue": 0.42,
                            "threshold": 0.55,
                            "operator": ">=",
                            "delta": 0.13,
                            "sourceStatus": "DERIVED",
                        }
                    ],
                    "blockingCondition": blocking_condition,
                    "suppressionReason": suppression_reason,
                },
            }
        },
        "aiRuntimeReached": False,
        "governanceRuntimeReached": False,
        "executionRuntimeReached": False,
    }


def _decision(runtime_result, **overrides):
    values = {
        "running": True,
        "cycle_id": "CYCLE_B",
        "mode": "paper",
        "market_ready": True,
        "runtime_result": runtime_result,
        "pending_order": False,
        "position_active": False,
        "money_management_guard": None,
    }
    values.update(overrides)
    return build_trading_decision_snapshot(**values)


def _diagnostics(runtime_result=None, decision=None, **kwargs):
    if decision is None:
        decision = _decision(runtime_result or _strategy_hold_result())
    return build_trading_cycle_diagnostics(
        decision,
        runtime_result=runtime_result or _strategy_hold_result(),
        context={"bot": {"running": True}, "status": "RUNNING"},
        evaluated_at=decision.get("timestamp"),
        **kwargs,
    )


def test_diagnostics_has_exactly_fifteen_steps_indexed_0_to_14():
    diagnostics = _diagnostics()

    assert diagnostics["schemaVersion"] == 1
    assert len(diagnostics["steps"]) == STEP_COUNT == 15
    assert [step["index"] for step in diagnostics["steps"]] == list(range(15))
    assert len({step["key"] for step in diagnostics["steps"]}) == 15


def test_diagnostics_does_not_mutate_trading_decision():
    decision = _decision(_strategy_hold_result())
    before = {
        "blockingStage": decision["blockingStage"],
        "blockingReason": decision["blockingReason"],
        "currentStageIndex": decision["currentStageIndex"],
    }
    build_trading_cycle_diagnostics(decision, runtime_result=_strategy_hold_result())
    assert {
        "blockingStage": decision["blockingStage"],
        "blockingReason": decision["blockingReason"],
        "currentStageIndex": decision["currentStageIndex"],
    } == before


def test_step4_maps_entry_readiness_current_required_and_comparison():
    diagnostics = _diagnostics()
    step = diagnostics["steps"][4]

    assert step["status"] == StepStatus.BLOCKED
    assert step["current"]["blockingCondition"] == "COMPOSITE_SCORE"
    assert step["current"]["blockingConditionCurrent"] == 0.42
    assert step["required"]["minimumCompositeScore"] == 0.55
    assert step["required"]["conditionThreshold"] == 0.55
    assert step["comparison"] == "BLOCK"
    assert step["blockerType"] == BlockerType.PARAMETER
    assert step["actionable"] == Actionable.YES
    assert step["relatedParameters"][0]["key"] == "minimumCompositeScore"
    assert step["extra"]["conditions"][0]["code"] == "COMPOSITE_SCORE"


def test_root_blocker_maps_to_step4_parameter_classification():
    diagnostics = _diagnostics()
    root = diagnostics["rootBlocker"]

    assert root["step"] == 4
    assert root["blockerType"] == BlockerType.PARAMETER
    assert root["reasonCode"] == "LOW_COMPOSITE_SCORE" or root["reasonCode"] == "ENTRY_THRESHOLD_NOT_MET"
    assert diagnostics["rootBlockerStep"] == 4
    assert diagnostics["cycleState"] == "BLOCKED"


def test_market_block_is_classified_as_market_not_parameter():
    conditions = [
        {
            "code": "SPREAD",
            "status": "FAIL",
            "currentValue": 0.9,
            "threshold": 0.5,
            "operator": "<=",
            "sourceStatus": "MEASURED",
        }
    ]
    runtime = _strategy_hold_result(
        suppression_reason="ABNORMAL_SPREAD",
        conditions=conditions,
        blocking_condition="SPREAD",
    )
    diagnostics = _diagnostics(runtime_result=runtime)

    assert diagnostics["rootBlocker"]["blockerType"] == BlockerType.MARKET
    assert diagnostics["steps"][4]["blockerType"] == BlockerType.MARKET
    assert diagnostics["steps"][4]["actionable"] == Actionable.NO


def test_subsequent_steps_report_waiting_dependency_on_root_blocker():
    diagnostics = _diagnostics()
    for step in diagnostics["steps"]:
        if step["index"] > 4 and step["index"] != 5:
            assert step["dependencyState"] == "WAITING_FOR_STEP_4"
            assert step["rootBlockerStep"] == 4
            assert step["status"] == StepStatus.WAITING


def test_ai_step_is_bypassed_not_completed_when_trading_ai_is_off():
    diagnostics = _diagnostics()
    ai_step = diagnostics["steps"][5]

    assert ai_step["status"] == StepStatus.BYPASSED
    assert ai_step["reasonCode"] == "TRADING_AI_OFF"
    assert ai_step["blockerType"] == BlockerType.MODE
    assert ai_step["dependencyState"] is None


def test_bot_stopped_is_not_reported_as_parameter_context_failure():
    decision = _decision(_strategy_hold_result(), running=False)
    diagnostics = build_trading_cycle_diagnostics(
        decision,
        runtime_result=_strategy_hold_result(),
        context={"bot": {"running": False}, "status": "STOPPED"},
        evaluated_at=decision.get("timestamp"),
    )

    assert diagnostics["rootBlocker"] is None
    assert diagnostics["rootBlockerStep"] is None
    assert diagnostics["cycleState"] == "BOT_STOPPED"
    assert all(step["status"] == StepStatus.NOT_REACHED for step in diagnostics["steps"])
    assert all(step["reasonCode"] == "BOT_STOPPED" for step in diagnostics["steps"])
    assert diagnostics["steps"][0]["blockerType"] == BlockerType.MODE


def test_unknown_when_entry_readiness_is_absent():
    runtime = {
        "strategyRuntimeReached": True,
        "strategyOutput": {"strategy": {"executionAllowed": False, "entryReadiness": {"cycleId": "CYCLE_B"}}},
    }
    decision = _decision(runtime)
    diagnostics = build_trading_cycle_diagnostics(
        decision,
        runtime_result=runtime,
        context={"bot": {"running": True}, "status": "RUNNING"},
    )

    step = diagnostics["steps"][4]
    # The canonical decision still reports the strategy block, but the missing
    # entry-readiness detail is never invented.
    assert step["comparison"] == "NOT_AVAILABLE"
    assert step["current"] == "NOT_AVAILABLE"
    assert step["reasonCode"] == "ENTRY_READINESS_NOT_EXPOSED"
    assert step["blockerType"] == BlockerType.UNKNOWN


def test_paper_and_live_share_the_same_diagnostics_schema():
    runtime = _strategy_hold_result(
        execution_allowed=True,
        conditions=[],
        suppression_reason=None,
    )
    paper = _diagnostics(runtime_result=runtime, decision=_decision(runtime, mode="paper"))
    live = _diagnostics(
        runtime_result=runtime,
        decision=_decision(runtime, mode="live", real_order_allowed=False),
    )

    assert [s["index"] for s in paper["steps"]] == [s["index"] for s in live["steps"]]
    assert set(paper) == set(live)
    assert set(paper["steps"][0]) == set(live["steps"][0])


def test_closed_position_projects_settlement_and_readiness():
    close_state = {
        "status": "CONFIRMED",
        "confirmed": True,
        "closed": True,
        "reason": "EXCHANGE_CLOSE_CONFIRMED",
        "positionState": "FLAT",
        "openOrderState": "FLAT",
        "reconciliationAttempts": 1,
        "order_id": "o-1",
    }
    decision = _decision(
        _strategy_hold_result(
            execution_allowed=True, conditions=[], suppression_reason=None
        ),
        close_state=close_state,
    )
    diagnostics = _diagnostics(decision=decision)

    assert diagnostics["cycleState"] == "CLOSE_CONFIRMED"
    assert diagnostics["steps"][11]["status"] == StepStatus.COMPLETED
    assert diagnostics["steps"][12]["status"] == StepStatus.COMPLETED
    assert diagnostics["steps"][14]["status"] == StepStatus.ACTIVE


def test_status_response_model_exposes_the_additive_diagnostics_field():
    """The /api/bot/status response model must not strip the new contract."""

    from backend.api.bot_api import StatusResponse

    fields = StatusResponse.model_fields
    assert "tradingDecision" in fields
    assert "tradingCycleDiagnostics" in fields



# J5-2: explicit evidence identity is required; timestamp freshness is independent.


def _liquidity_runtime(cycle_id="CYCLE_B", timestamp=1000):
    runtime = _strategy_hold_result(
        suppression_reason="LIQUIDITY_INSTABILITY",
        blocking_condition="LIQUIDITY_SAFETY",
        conditions=[{
            "code": "LIQUIDITY_SAFETY", "currentValue": False,
            "expected": True, "operator": None, "threshold": None,
            "status": "FAIL", "sourceStatus": "DERIVED",
        }],
    )
    strategy = runtime["strategyOutput"]["strategy"]
    strategy["timestamp"] = timestamp
    strategy["featureContract"] = "LEGACY_CALLBACK_WINDOW"
    strategy["entryReadiness"]["cycleId"] = cycle_id
    strategy["liquidityInstabilityDebug"] = {"totalVolume": 4575346, "priceDifference": 0}
    return runtime


def _project(runtime, now=1001, **context):
    return build_trading_cycle_diagnostics(
        _decision(runtime, timestamp=now), runtime_result=runtime,
        context={"bot": {"running": True}, **context}, evaluated_at=now,
    )


def test_legacy_feature_contract_semantic_pass_is_preserved():
    step = _project(_liquidity_runtime())["steps"][3]
    assert (step["current"], step["required"], step["comparison"]) == (
        "LEGACY_CALLBACK_WINDOW", "FEATURE_CONTRACT_ACTIVE", "PASS")


def test_same_cycle_boolean_blocker_retains_false_and_expected_true():
    result = _project(_liquidity_runtime())
    step = result["steps"][4]
    assert step["current"]["blockingConditionCurrent"] is False
    assert step["required"]["conditionExpected"] is True
    assert step["comparison"] == "FAIL"
    assert step["valueType"] == "BOOLEAN"
    assert step["status"] == "BLOCKED"
    assert step["provenance"] == "CURRENT"
    assert step["reasonCode"] == "LIQUIDITY_INSTABILITY"
    assert result["rootBlockerStep"] == 4
    assert result["rootBlocker"]["evaluationCycleId"] == "CYCLE_B"


@pytest.mark.parametrize("code,expected", [
    ("MARKET_SPREAD_SAFETY", True), ("LIQUIDITY_SAFETY", True),
    ("MOMENTUM_WARMUP", True), ("DIRECTION_CONSISTENCY", True),
    ("ABSORPTION", False), ("STAGNANT_FLOW", False), ("FAKE_PRESSURE", False),
])
@pytest.mark.parametrize("passes", [True, False])
def test_all_canonical_boolean_contracts(code, expected, passes):
    from backend.strategy.MicrostructureEdgeStrategy import MicrostructureEdgeStrategy
    current = expected if passes else not expected
    condition = MicrostructureEdgeStrategy._condition(code, current, expected=expected)
    runtime = _strategy_hold_result(conditions=[condition], blocking_condition=code)
    step = _project(runtime)["steps"][4]
    normalized = step["extra"]["conditions"][0]
    assert normalized["currentValue"] is current
    assert normalized["required"] is expected
    assert normalized["comparison"] == ("PASS" if passes else "FAIL")


@pytest.mark.parametrize("current", [False, 0, "", None])
def test_condition_values_are_not_lost_to_truthiness(current):
    runtime = _strategy_hold_result(conditions=[{
        "code": "EXAMPLE", "currentValue": current, "status": "DIAGNOSTIC",
    }], blocking_condition="EXAMPLE")
    step = _project(runtime)["steps"][4]
    assert step["current"]["blockingConditionCurrent"] == current
    assert type(step["current"]["blockingConditionCurrent"]) is type(current)
    assert step["extra"]["conditions"][0]["valueType"] == "UNKNOWN"
    assert step["required"]["conditionExpected"] is None


def test_numeric_zero_uses_runtime_threshold_not_boolean_equality():
    runtime = _strategy_hold_result(conditions=[{
        "code": "SPREAD", "currentValue": 0, "threshold": 0.0001,
        "operator": ">=", "status": "FAIL",
    }], blocking_condition="SPREAD")
    condition = _project(runtime)["steps"][4]["extra"]["conditions"][0]
    assert condition["valueType"] == "NUMERIC_THRESHOLD"
    assert condition["currentValue"] == 0
    assert condition["required"] == 0.0001
    assert condition["operator"] == ">="
    assert condition["comparison"] == "FAIL"


@pytest.mark.parametrize("cycle_id,stamp,now,state,freshness", [
    ("CYCLE_B", 1000, 1001, "CURRENT", "FRESH"),
    ("CYCLE_B", 1000, 33400, "CURRENT", "STALE"),
    ("CYCLE_A", 1000, 33400, "HISTORICAL", "STALE"),
    ("CYCLE_A", 1000, 1001, "HISTORICAL", "FRESH"),
    (None, 1000, 1001, "UNKNOWN", "FRESH"),
    (None, None, 1001, "UNKNOWN", "UNKNOWN"),
    ("CYCLE_B", None, 1001, "CURRENT", "UNKNOWN"),
])
def test_provenance_and_freshness_are_independent(cycle_id, stamp, now, state, freshness):
    runtime = _liquidity_runtime(cycle_id, stamp)
    before = deepcopy(runtime)
    result = _project(runtime, now)
    step = result["steps"][4]
    assert runtime == before
    assert result["cycleId"] == "CYCLE_B"
    assert step["evaluationCycleId"] == cycle_id
    assert step["currentCycleId"] == "CYCLE_B"
    assert step["provenance"] == state
    assert step["freshness"]["state"] == freshness
    assert step["evaluatedAt"] == stamp
    assert step["sourceUpdatedAt"] == stamp
    assert step["diagnosticsGeneratedAt"] == now
    if state != "CURRENT":
        assert result["rootBlocker"] is None
        assert step["status"] == "WAITING"
        assert step["retainedEvaluation"]["reasonCode"] == "LIQUIDITY_INSTABILITY"
        assert step["retainedEvaluation"]["entryReadiness"]["conditions"][0]["currentValue"] is False
        assert step["retainedEvaluation"]["liquidityInstabilityDebug"]["priceDifference"] == 0
    else:
        assert result["rootBlockerStep"] == 4


def test_snapshot_never_stamps_current_identity_on_retained_evidence():
    for cycle_id in ("CYCLE_A", None):
        runtime = _liquidity_runtime(cycle_id)
        snapshot = _decision(runtime, cycle_id="CYCLE_B", timestamp=33400)
        assert snapshot["entryReadiness"]["cycleId"] == cycle_id
        assert snapshot["entryReadiness"]["evaluatedAt"] == 1000
        # Even an older caller that decorates its snapshot must not fool diagnostics.
        snapshot["entryReadiness"]["cycleId"] = "CYCLE_B"
        result = build_trading_cycle_diagnostics(snapshot, runtime_result=runtime)
        assert result["evaluationProvenance"]["evaluationCycleId"] == cycle_id
        assert result["rootBlocker"] is None


def test_historical_reason_is_separate_from_current_loop_state():
    result = _project(_liquidity_runtime("CYCLE_A"), 33400,
                      runtime_health={"runtimeEngine": {"status": "STOPPED"}})
    step = result["steps"][4]
    assert result["runtimeState"]["status"] == "STOPPED"
    assert step["current"]["strategyLoop"] == "STOPPED"
    assert result["rootBlocker"] is None
    assert "LIQUIDITY" not in step["reasonText"]
    assert "stopped" not in step["retainedEvaluation"]["reasonText"].lower()
    assert step["retainedEvaluation"]["reasonCode"] == "LIQUIDITY_INSTABILITY"


def test_current_market_blocker_wins_over_historical_strategy_reason():
    runtime = _liquidity_runtime("CYCLE_A")
    decision = _decision(runtime, market_ready=False)
    result = build_trading_cycle_diagnostics(decision, runtime_result=runtime)
    assert result["rootBlockerStep"] == 2
    assert result["steps"][4]["retainedEvaluation"]["reasonCode"] == "LIQUIDITY_INSTABILITY"


@pytest.mark.parametrize("cycle_id", ["CYCLE_A", "CYCLE_B", None])
def test_status_api_preserves_provenance_and_boolean_values(monkeypatch, cycle_id):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import bot_api
    from types import SimpleNamespace
    diagnostics = _project(_liquidity_runtime(cycle_id), 33400)
    payload = dict(status="RUNNING", timestamp=33400, last_update=1000, price=1,
                   marketReady=True, marketStale=False, execution_mode="SIMULATION",
                   real_order_allowed=False, ws_connected=False, position_active=False,
                   pendingOrder=False, balance=100, equity=100, pnl=0,
                   executionAuthorityScore=0, authoritativeRuntimeState="STOPPED",
                   runtimeSynchronizationState="OFFLINE", tradingCycleDiagnostics=diagnostics)
    monkeypatch.setattr(bot_api, "get_bot_manager", lambda: SimpleNamespace(get_status=lambda: payload))
    app = FastAPI()
    app.include_router(bot_api.router, prefix="/api/bot")
    with TestClient(app) as client:
        response = client.get("/api/bot/status")
    assert response.status_code == 200, response.text
    assert response.json()["tradingCycleDiagnostics"] == diagnostics


def test_stopped_bot_preserves_the_actual_retained_strategy_reason():
    runtime = _liquidity_runtime("CYCLE_A")
    result = build_trading_cycle_diagnostics(
        _decision(runtime, running=False), runtime_result=runtime,
        context={"bot": {"running": False}}, evaluated_at=33400,
    )
    step = result["steps"][4]
    assert step["status"] == "NOT_REACHED"
    assert step["reasonCode"] == "BOT_STOPPED"
    assert step["retainedEvaluation"]["reasonCode"] == "LIQUIDITY_INSTABILITY"
    assert step["retainedEvaluation"]["current"]["blockingConditionCurrent"] is False


def test_unknown_source_time_never_falls_back_to_snapshot_generation_time():
    runtime = _liquidity_runtime(None, None)
    snapshot = _decision(runtime, timestamp=33400)
    assert snapshot["entryReadiness"]["evaluatedAt"] is None
    result = _project(runtime, 33400)
    assert result["steps"][4]["freshness"]["state"] == "UNKNOWN"


def test_naive_strategy_utc_timestamp_and_explicit_offset_have_same_age():
    result = _project(_liquidity_runtime("CYCLE_A", "2026-08-08T12:00:00"),
                      "2026-08-08T21:00:00+00:00")
    assert result["steps"][4]["freshness"]["ageSeconds"] == 32400


def test_generation_timestamp_zero_is_not_replaced_by_context_timestamp():
    runtime = _liquidity_runtime(timestamp=0)
    result = build_trading_cycle_diagnostics(
        _decision(runtime, timestamp=0), runtime_result=runtime,
        context={"timestamp": 1000},
    )
    assert result["diagnosticsGeneratedAt"] == 0
    assert result["steps"][4]["freshness"]["ageSeconds"] == 0


def test_evaluation_source_and_generation_timestamps_remain_distinct():
    runtime = _liquidity_runtime(timestamp=1000)
    runtime["strategyOutput"]["strategy"]["entryReadiness"]["evaluatedAt"] = 990
    step = _project(runtime, 1001)["steps"][4]
    assert step["evaluatedAt"] == 990
    assert step["sourceUpdatedAt"] == 1000
    assert step["diagnosticsGeneratedAt"] == 1001
    assert step["freshness"]["ageSeconds"] == 11
    assert step["provenance"] == "CURRENT"


@pytest.mark.parametrize("cycle_id", ["CYCLE_A", None])
def test_retained_block_keeps_downstream_waiting_and_ai_bypassed(cycle_id):
    result = _project(_liquidity_runtime(cycle_id))
    assert result["rootBlocker"] is None
    assert result["steps"][5]["status"] == "BYPASSED"
    for step in result["steps"][6:]:
        assert step["status"] == "WAITING"
        assert step["dependencyState"] == "WAITING_FOR_STEP_4"
        assert step["rootBlockerStep"] is None


def test_normalized_blocking_stage_cannot_bypass_provenance_guard():
    runtime = _liquidity_runtime("CYCLE_A")
    decision = _decision(runtime)
    decision["blockingStage"] = " python strategy "
    result = build_trading_cycle_diagnostics(decision, runtime_result=runtime)
    assert result["rootBlocker"] is None


@pytest.mark.parametrize("condition,value_type,comparison", [
    ({"currentValue": "BUY", "expected": "BUY"}, "ENUM", "PASS"),
    ({"currentValue": "SELL", "expected": "BUY"}, "ENUM", "FAIL"),
    ({"currentValue": 0, "threshold": 0, "operator": "<="}, "NUMERIC_THRESHOLD", "PASS"),
    ({"currentValue": 1, "threshold": 0, "operator": "<="}, "NUMERIC_THRESHOLD", "FAIL"),
    ({"currentValue": False, "expected": True, "sourceStatus": "MISSING"}, "BOOLEAN", "NOT_AVAILABLE"),
    ({"currentValue": None, "expected": True}, "BOOLEAN", "NOT_AVAILABLE"),
    ({"currentValue": 1, "operator": "CUSTOM", "status": "PASS"}, "PREDICATE", "PASS"),
])
def test_condition_contract_types(condition, value_type, comparison):
    runtime = _strategy_hold_result(conditions=[{"code": "EXAMPLE", **condition}])
    normalized = _project(runtime)["steps"][4]["extra"]["conditions"][0]
    assert normalized["valueType"] == value_type
    assert normalized["comparison"] == comparison


@pytest.mark.parametrize("stamp", [1000, 0, None])
def test_strategy_stage_time_is_never_replaced_by_snapshot_time(stamp):
    runtime = _liquidity_runtime("CYCLE_A", stamp)
    snapshot = _decision(runtime, timestamp=33400)
    assert snapshot["stages"]["pythonStrategy"]["evaluatedAt"] == stamp
    assert snapshot["entryReadiness"]["evaluatedAt"] == stamp
