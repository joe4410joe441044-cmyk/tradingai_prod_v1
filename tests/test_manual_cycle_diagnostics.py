"""WORK J: MANUAL entry vs BOT strategy cycle diagnostic semantics."""

from copy import deepcopy

from backend.runtime.cycle_diagnostics import (
    BlockerType,
    StepStatus,
    build_trading_cycle_diagnostics,
)
from backend.runtime.runtime_health_snapshot import build_trading_decision_snapshot


def _strategy_result(
    *,
    cycle_id="CYCLE_B",
    execution_allowed=False,
    suppression_reason="ENTRY_THRESHOLD_NOT_MET",
    money_allowed=None,
    money_reached=False,
):
    strategy = {
        "executionAllowed": execution_allowed,
        "direction": "NEUTRAL" if not execution_allowed else "BUY",
        "confidence": 0.42,
        "edge": 0.42,
        "minimumConfidence": 0.50,
        "minimumCompositeScore": 0.55,
        "featureContract": "TIME_SYMBOL_NORMALIZED_V1",
        "suppressionReason": suppression_reason,
        "entryReadiness": {
            "available": True,
            "cycleId": cycle_id,
            "executionAllowed": execution_allowed,
            "conditions": [],
        },
    }
    result = {
        "strategyRuntimeReached": True,
        "strategyOutput": {"strategy": strategy},
        "governanceRuntimeReached": False,
        "executionRuntimeReached": False,
        "moneyManagementReached": money_reached,
    }
    if money_allowed is not None:
        result["moneyManagementDecision"] = {
            "allowed": money_allowed,
            "decision": "ALLOW" if money_allowed else "BLOCK",
            "reason": None if money_allowed else "BOT_MM_POLICY_BLOCK",
        }
    return result


def _no_strategy_result():
    return {
        "strategyRuntimeReached": False,
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


def _manual_diagnostics(runtime_result, decision=None, **context):
    if decision is None:
        decision = _decision(runtime_result)
    ctx = {"bot": {"running": True}, "status": "RUNNING", **context}
    return build_trading_cycle_diagnostics(
        decision,
        runtime_result=runtime_result,
        context=ctx,
        evaluated_at=decision.get("timestamp"),
    )


def _step(diagnostics, index):
    return diagnostics["steps"][index]


def test_paper_manual_running_with_strategy_loop_stopped_does_not_block_manual_entry():
    runtime = _no_strategy_result()
    decision = _decision(runtime)
    diagnostics = _manual_diagnostics(
        runtime,
        decision,
        controlAuthority="MANUAL",
        runtime_health={"runtimeEngine": {"status": "STOPPED"}},
    )

    step4 = _step(diagnostics, 4)
    assert step4["status"] == StepStatus.BYPASSED
    assert step4["blocksManualEntry"] is False
    assert step4["manualEntryRelevance"] == "BOT_ONLY"
    assert step4["dependencyState"] is None
    assert diagnostics["controlAuthority"] == "MANUAL"
    assert diagnostics["cycleState"] == "MANUAL_ON_DEMAND"
    assert diagnostics["rootBlockerStep"] != 4
    assert diagnostics["manualEntry"]["state"] == "READY_ON_DEMAND"
    assert diagnostics["manualEntry"]["strategyCycleRequired"] is False
    for index in (6, 7, 8):
        assert _step(diagnostics, index)["status"] == StepStatus.WAITING
        assert _step(diagnostics, index)["dependencyState"] is None
        assert _step(diagnostics, index)["rootBlockerStep"] is None


def test_manual_without_strategy_signal_is_not_blocked_by_signal_absence():
    runtime = _strategy_result(execution_allowed=False)
    diagnostics = _manual_diagnostics(runtime, controlAuthority="MANUAL")

    assert _step(diagnostics, 4)["status"] == StepStatus.BYPASSED
    assert _step(diagnostics, 4)["blocksManualEntry"] is False
    assert diagnostics["rootBlocker"] is None
    assert diagnostics["manualEntry"]["state"] == "READY_ON_DEMAND"


def test_manual_ai_decision_waiting_does_not_block_manual_entry():
    runtime = _strategy_result(execution_allowed=True, suppression_reason=None)
    decision = _decision(runtime)
    decision["stages"]["aiReview"] = {
        "available": True,
        "reached": True,
        "required": True,
        "mode": "ON",
        "decision": "WAITING",
        "status": "WAITING",
    }
    diagnostics = _manual_diagnostics(
        runtime, decision, controlAuthority="MANUAL"
    )

    step5 = _step(diagnostics, 5)
    assert step5["status"] == StepStatus.BYPASSED
    assert step5["blocksManualEntry"] is False
    assert step5["rootBlockerStep"] is None
    assert step5["dependencyState"] is None
    assert "human BUY/SELL" in step5["reasonText"]
    assert diagnostics["manualEntry"]["aiDecisionRequired"] is False


def test_manual_genuine_mm_block_remains_fail_closed():
    runtime = _strategy_result(execution_allowed=True, suppression_reason=None)
    diagnostics = _manual_diagnostics(
        runtime,
        controlAuthority="MANUAL",
        manualMoneyManagementAuthority={
            "available": True,
            "allowed": False,
            "decision": "BLOCK",
            "reason": "MAX_DRAWDOWN_BLOCK",
        },
    )

    step6 = _step(diagnostics, 6)
    assert step6["status"] == StepStatus.BLOCKED
    assert step6["manualEntryState"] == "BLOCKED"
    assert diagnostics["rootBlockerStep"] == 6
    assert diagnostics["rootBlocker"]["reasonCode"] == "MAX_DRAWDOWN_BLOCK"
    assert diagnostics["manualEntry"]["state"] == "BLOCKED"
    assert diagnostics["manualEntry"]["moneyManagement"] == "BLOCKED"
    assert _step(diagnostics, 7)["dependencyState"] == "WAITING_FOR_STEP_6"
    assert _step(diagnostics, 8)["dependencyState"] == "WAITING_FOR_STEP_6"


def test_manual_mm_allow_does_not_collapse_with_stale_bot_cycle_mm_block():
    runtime = _strategy_result(
        execution_allowed=True,
        suppression_reason=None,
        money_allowed=False,
        money_reached=True,
    )
    decision = _decision(runtime)
    assert decision["blockingStage"] == "MONEY MANAGEMENT"

    diagnostics = _manual_diagnostics(
        runtime,
        decision,
        controlAuthority="MANUAL",
        manualMoneyManagementAuthority={
            "available": True,
            "allowed": True,
            "decision": "ALLOW",
            "reason": "MM_ALLOW",
        },
    )

    step6 = _step(diagnostics, 6)
    assert diagnostics["rootBlockerStep"] != 6
    assert step6["status"] == StepStatus.WAITING
    assert step6["manualEntryState"] == "ALLOW"
    assert step6["extra"]["botCycle"]["current"] == "BLOCK"
    assert diagnostics["manualEntry"]["moneyManagement"] == "ALLOW"
    assert diagnostics["botStrategyCycle"]["rootBlockerStep"] == 6


def test_manual_before_request_execution_waits_for_human_not_strategy():
    runtime = _strategy_result(execution_allowed=False)
    diagnostics = _manual_diagnostics(runtime, controlAuthority="MANUAL")

    step8 = _step(diagnostics, 8)
    assert step8["status"] == StepStatus.WAITING
    assert step8["reasonCode"] == "MANUAL_EXECUTION_WAITING_FOR_REQUEST"
    assert "human BUY/SELL" in step8["reasonText"]
    assert step8["dependencyState"] is None
    assert step8["rootBlockerStep"] is None
    assert diagnostics["manualEntry"]["execution"] == "WAITING_FOR_MANUAL_REQUEST"


def test_bot_mode_diagnostics_are_unchanged():
    runtime = _strategy_result(execution_allowed=False)
    diagnostics = _manual_diagnostics(runtime)

    assert diagnostics["controlAuthority"] == "BOT"
    assert diagnostics["manualEntry"] is None
    assert _step(diagnostics, 4)["status"] == StepStatus.BLOCKED
    assert diagnostics["rootBlockerStep"] == 4
    assert diagnostics["cycleState"] == "BLOCKED"


def test_select_selection_mode_with_manual_authority_is_valid():
    runtime = _strategy_result(execution_allowed=False)
    diagnostics = _manual_diagnostics(
        runtime,
        controlAuthority="MANUAL",
        selectionMode="MANUAL",
        activeSymbol="BTC/USDT",
    )

    assert _step(diagnostics, 1)["current"] == "BTC/USDT"
    assert _step(diagnostics, 4)["status"] == StepStatus.BYPASSED
    assert diagnostics["manualEntry"]["state"] == "READY_ON_DEMAND"


def test_auto_selection_mode_with_manual_authority_is_valid():
    runtime = _strategy_result(execution_allowed=False)
    diagnostics = _manual_diagnostics(
        runtime,
        controlAuthority="MANUAL",
        selectionMode="AUTO",
        activeSymbol="ETH/USDT",
        symbolSwitchState="IDLE",
    )

    assert _step(diagnostics, 1)["current"] == "ETH/USDT"
    assert _step(diagnostics, 4)["status"] == StepStatus.BYPASSED
    assert diagnostics["manualEntry"]["state"] == "READY_ON_DEMAND"


def test_manual_open_position_retains_post_position_and_exit_monitoring():
    runtime = _strategy_result(execution_allowed=True, suppression_reason=None)
    decision = _decision(
        runtime,
        position_active=True,
        position_state="OPEN",
    )
    diagnostics = _manual_diagnostics(
        runtime, decision, controlAuthority="MANUAL"
    )

    assert _step(diagnostics, 9)["status"] == StepStatus.ACTIVE
    assert _step(diagnostics, 10)["status"] == StepStatus.ACTIVE
    assert _step(diagnostics, 10)["reasonCode"] == "EXIT_MONITORING_ACTIVE"
    assert diagnostics["cycleState"] == "POSITION_OPEN"
    assert diagnostics["manualEntry"]["state"] == "POSITION_OPEN"


def test_switching_bot_to_manual_changes_diagnostics_without_mutating_execution_facts():
    runtime = _strategy_result(execution_allowed=False)
    decision = _decision(runtime)
    before = deepcopy(decision)

    bot = _manual_diagnostics(runtime, decision)
    manual = _manual_diagnostics(runtime, decision, controlAuthority="MANUAL")

    assert _step(bot, 4)["status"] == StepStatus.BLOCKED
    assert bot["rootBlockerStep"] == 4
    assert _step(manual, 4)["status"] == StepStatus.BYPASSED
    assert manual["rootBlockerStep"] is None
    assert decision == before


def test_switching_manual_to_bot_restores_bot_strategy_diagnostics():
    runtime = _strategy_result(execution_allowed=False)
    decision = _decision(runtime)

    manual = _manual_diagnostics(runtime, decision, controlAuthority="MANUAL")
    bot = _manual_diagnostics(runtime, decision, controlAuthority="BOT")

    assert _step(manual, 4)["status"] == StepStatus.BYPASSED
    assert _step(bot, 4)["status"] == StepStatus.BLOCKED
    assert bot["rootBlockerStep"] == 4
    assert bot["controlAuthority"] == "BOT"


def test_manual_authority_from_nested_execution_control_is_honored():
    runtime = _strategy_result(execution_allowed=False)
    diagnostics = _manual_diagnostics(
        runtime,
        executionControl={"controlAuthority": "MANUAL"},
    )

    assert diagnostics["controlAuthority"] == "MANUAL"
    assert _step(diagnostics, 4)["status"] == StepStatus.BYPASSED
    assert diagnostics["rootBlocker"] is None
