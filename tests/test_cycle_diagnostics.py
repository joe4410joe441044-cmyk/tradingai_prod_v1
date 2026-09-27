"""Tests for the observation-only Trading Cycle diagnostics adapter (J2)."""

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
        "strategyOutput": {"strategy": {"executionAllowed": False}},
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

