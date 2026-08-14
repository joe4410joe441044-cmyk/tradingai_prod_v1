from backend.runtime.runtime_health_snapshot import build_trading_decision_snapshot


def strategy_hold_result():
    return {
        "strategyRuntimeReached": True,
        "strategyOutput": {
            "strategy": {
                "executionAllowed": False,
                "direction": "NEUTRAL",
                "confidence": 0.42,
                "suppressionReason": "ENTRY_THRESHOLD_NOT_MET",
            }
        },
        "aiRuntimeReached": False,
        "governanceRuntimeReached": False,
        "executionRuntimeReached": False,
    }


def build(**overrides):
    values = {
        "running": True,
        "mode": "paper",
        "market_ready": True,
        "runtime_result": strategy_hold_result(),
        "pending_order": False,
        "position_active": False,
        "money_management_guard": None,
    }
    values.update(overrides)
    return build_trading_decision_snapshot(**values)


def test_strategy_hold_is_the_blocker_and_ai_is_not_misattributed():
    snapshot = build()

    assert snapshot["mode"] == "PAPER"
    assert snapshot["finalDecision"] == "HOLD"
    assert snapshot["currentState"] == "WAITING FOR SIGNAL"
    assert snapshot["blockingStage"] == "PYTHON STRATEGY"
    assert snapshot["blockingReason"] == "ENTRY_THRESHOLD_NOT_MET"
    assert snapshot["stages"]["market"]["status"] == "PASS"
    assert snapshot["stages"]["pythonStrategy"]["status"] == "HOLD"
    assert snapshot["stages"]["pythonStrategy"]["confidence"] == 0.42
    assert snapshot["tradingAiMode"] == "OFF"
    assert snapshot["tradingAiStatus"] == "NOT_INSTALLED"
    assert snapshot["stages"]["aiReview"]["status"] == "OFF"
    assert snapshot["stages"]["moneyManagement"]["status"] == "NOT REACHED"
    assert snapshot["stages"]["governance"]["status"] == "NOT REACHED"
    assert snapshot["stages"]["execution"]["status"] == "NO ORDER"


def test_legacy_ai_fields_cannot_reactivate_the_archived_production_stage():
    result = strategy_hold_result()
    result.update({
        "aiRuntimeReached": True,
        "aiDecision": "HOLD",
        "aiConfidence": 0.31,
        "aiHoldReason": "NO_CONSENSUS",
    })

    snapshot = build(runtime_result=result)

    assert snapshot["blockingStage"] == "PYTHON STRATEGY"
    assert snapshot["blockingReason"] == "ENTRY_THRESHOLD_NOT_MET"
    review = snapshot["stages"]["aiReview"]
    assert review["available"] is False
    assert review["called"] is False
    assert review["reached"] is False
    assert review["status"] == "OFF"
    assert review["decision"] == "NOT_REQUIRED"
    assert review["confidence"] is None
    assert review["reason"] == "TRADING_AI_OFF"


def test_execution_states_use_pending_order_and_position_facts():
    assert build(pending_order=True)["stages"]["execution"]["status"] == "WAITING FOR FILL"
    opened = build(pending_order=True, position_active=True)
    assert opened["stages"]["execution"]["status"] == "POSITION OPEN"
    assert opened["currentState"] == "POSITION OPEN"


def test_stopped_runtime_does_not_expose_stale_cycle_as_current_decision():
    snapshot = build(running=False)

    assert snapshot["blockingStage"] == "OPERATION"
    assert snapshot["blockingReason"] == "BOT_STOPPED"
    assert snapshot["stages"]["pythonStrategy"]["status"] == "NOT REACHED"
    assert snapshot["stages"]["aiReview"]["status"] == "OFF"


def test_buy_sell_and_live_safety_use_the_shared_contract():
    for direction in ("BUY", "SELL"):
        result = strategy_hold_result()
        result["strategyOutput"]["strategy"].update({
            "executionAllowed": True,
            "direction": direction,
            "suppressionReason": None,
        })
        snapshot = build(
            mode="live",
            runtime_result=result,
            real_order_allowed=False,
            exchange="kucoin",
        )
        assert snapshot["mode"] == "LIVE"
        assert snapshot["finalDecision"] == direction
        assert snapshot["realOrderAllowed"] is False
        assert snapshot["orderDestination"] == "KUCOIN"


def test_money_management_and_governance_blocks_are_distinct():
    result = strategy_hold_result()
    result["strategyOutput"]["strategy"].update({
        "executionAllowed": True,
        "direction": "BUY",
        "suppressionReason": None,
    })
    result.update({
        "moneyManagementReached": True,
        "moneyManagementDecision": {
            "allowed": False,
            "decision": "BLOCK",
            "reason": "RISK_BUDGET_EXCEEDED",
        },
    })
    money = build(
        runtime_result=result,
        money_management_guard={"allowed": False, "decision": "BLOCK", "reason": "RISK_BUDGET_EXCEEDED"},
    )
    assert money["blockingStage"] == "MONEY MANAGEMENT"
    assert money["finalDecision"] == "BLOCK"

    result.update({
        "moneyManagementDecision": {
            "allowed": True,
            "decision": "ALLOW",
            "reason": None,
        },
        "governanceRuntimeReached": True,
        "governanceAllowed": False,
        "governanceBlockedReason": "EXECUTION_DISABLED",
    })
    governance = build(runtime_result=result)
    assert governance["blockingStage"] == "GOVERNANCE"
    assert governance["blockingReason"] == "EXECUTION_DISABLED"


def test_order_position_and_stale_metadata_are_explicit():
    submitted = build(
        pending_order=True,
        order_state="SUBMITTED",
        order_side="BUY",
        order_type="LIMIT",
        stale=True,
        cycle_id="4:27",
        timestamp=123.0,
    )
    execution = submitted["stages"]["execution"]
    assert execution["state"] == "WAITING FOR FILL"
    assert execution["orderState"] == "SUBMITTED"
    assert execution["orderSide"] == "BUY"
    assert submitted["stale"] is True
    assert submitted["cycleId"] == "4:27"


def test_entry_readiness_is_enriched_from_the_authoritative_strategy_result():
    result = strategy_hold_result()
    result["strategyOutput"]["strategy"].update({
        "timestamp": "2026-08-08T12:00:00",
        "entryReadiness": {
            "available": True,
            "schemaVersion": 1,
            "candidateDirection": "SELL",
            "strategyDecision": "HOLD",
            "conditions": [{"code": "LIQUIDITY_QUALITY", "status": "FAIL"}],
        },
    })
    snapshot = build(runtime_result=result, cycle_id="cycle-7", timestamp="fallback")
    assert snapshot["entryReadinessAvailable"] is True
    assert snapshot["entryReadiness"]["candidateDirection"] == "SELL"
    assert snapshot["entryReadiness"]["cycleId"] == "cycle-7"
    assert snapshot["entryReadiness"]["evaluatedAt"] == "2026-08-08T12:00:00"


def test_entry_readiness_unavailable_is_explicit():
    snapshot = build()
    assert snapshot["entryReadinessAvailable"] is False
    assert snapshot["entryReadiness"] == {"available": False, "schemaVersion": 1, "conditions": []}
