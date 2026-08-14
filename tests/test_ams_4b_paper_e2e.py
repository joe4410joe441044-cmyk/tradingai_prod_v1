from backend.auto_market_selection import (
    PaperAutoSelectionE2E, PaperAutoSelectionE2EStatus,
)
from tests.test_ams_4a_auto_selection_runtime import NOW, Manager, runtime


SAFE_STATE = {
    "activeSymbolKnown": True, "positionKnown": True,
    "pendingOrderKnown": True, "mmAvailable": True,
    "emergencySafe": True, "governanceAvailable": True,
}


class Chain:
    def __init__(self, *, strategy="BUY", ai="BUY", mm=True, governance=True,
                 stale_stage=None):
        self.strategy_value = strategy
        self.ai_value = ai
        self.mm_allowed = mm
        self.governance_allowed = governance
        self.stale_stage = stale_stage
        self.calls = []
        self.real_calls = 0

    def _result(self, stage, context, **values):
        self.calls.append((stage, context["symbol"], context["runtimeId"]))
        if self.stale_stage == stage:
            context = {**context, "symbol": "ETHUSDT", "runtimeId": "runtime-old"}
        return {"runtimeSymbolContext": context, **values}

    def market(self, context):
        return self._result("market", context, domValid=True, detectorsReady=True,
                            featuresReady=True)

    def strategy(self, market, context):
        return self._result("strategy", context, decision=self.strategy_value)

    def ai(self, strategy, context):
        return self._result("ai", context, decision=self.ai_value)

    def mm(self, ai, context):
        return self._result("mm", context, decision="ALLOW" if self.mm_allowed else "BLOCK",
                            allowed=self.mm_allowed, reasonCodes=[] if self.mm_allowed else ["MM_BLOCKED"])

    def governance(self, mm, context):
        return self._result(
            "governance", context,
            decision="ALLOW" if self.governance_allowed else "BLOCK",
            allowed=self.governance_allowed,
            reasonCodes=[] if self.governance_allowed else ["GOVERNANCE_BLOCKED"],
        )

    def execution(self, governance, context):
        return self._result("execution", context, paperOrderCreated=True,
                            realExchangeCalled=False)


def e2e(*, manager=None, chain=None, initial_state=None, **runtime_kwargs):
    auto, manager, switch_runtime, _ = runtime(manager=manager, **runtime_kwargs)
    chain = chain or Chain()
    service = PaperAutoSelectionE2E(
        manager, auto, initial_state_provider=lambda: initial_state or SAFE_STATE,
        market_intelligence=chain.market, strategy=chain.strategy,
        ai_review=chain.ai, money_management=chain.mm,
        governance=chain.governance, paper_execution=chain.execution,
        clock=lambda: NOW,
    )
    return service, manager, switch_runtime, chain


def test_selected_symbol_flows_through_every_authority_to_paper_execution():
    service, manager, _, chain = e2e()
    original_config = dict(manager.config)
    result = service.run(started_at=NOW)
    assert result.status is PaperAutoSelectionE2EStatus.COMPLETED_SWITCHED
    assert result.initial_active_symbol == "ETHUSDT"
    assert result.top_candidate_symbol == result.final_active_symbol == "BTCUSDT"
    assert result.paper_order_created is True
    assert result.strategy_decision == "BUY"
    assert result.ai_decision == "NOT_REQUIRED"
    assert result.mm_decision == result.governance_decision == "ALLOW"
    assert [item[0] for item in chain.calls] == [
        "market", "strategy", "mm", "governance", "execution",
    ]
    assert {item[1] for item in chain.calls} == {"BTCUSDT"}
    assert {item[2] for item in chain.calls} == {manager.active_runtime_id}
    assert manager.config == original_config


def test_same_symbol_completes_without_switch_but_can_use_current_paper_pipeline():
    manager = Manager(active="BTCUSDT")
    service, manager, switch_runtime, chain = e2e(manager=manager)
    result = service.run(started_at=NOW)
    assert result.status is PaperAutoSelectionE2EStatus.COMPLETED_NO_SWITCH
    assert result.final_active_symbol == "BTCUSDT" and result.paper_order_created
    assert switch_runtime.events == [] and chain.calls[-1][0] == "execution"


def test_strategy_hold_creates_no_order_and_trading_ai_is_not_called():
    service, _, _, chain = e2e(chain=Chain(strategy="HOLD", ai="SELL"))
    result = service.run(started_at=NOW)
    assert result.status is PaperAutoSelectionE2EStatus.COMPLETED_HOLD
    assert result.reason_codes == ("STRATEGY_HOLD",)
    assert not result.paper_order_created
    assert [item[0] for item in chain.calls] == ["market", "strategy"]


def test_mm_and_governance_blocks_cannot_reach_paper_execution():
    for chain, reason, last_stage in (
        (Chain(mm=False), "MM_BLOCKED", "mm"),
        (Chain(governance=False), "GOVERNANCE_BLOCKED", "governance"),
    ):
        service, _, _, chain = e2e(chain=chain)
        result = service.run(started_at=NOW)
        assert result.status is PaperAutoSelectionE2EStatus.COMPLETED_BLOCKED
        assert reason in result.reason_codes and not result.paper_order_created
        assert chain.calls[-1][0] == last_stage


def test_old_strategy_decision_dies_after_symbol_switch():
    service, _, _, chain = e2e(chain=Chain(stale_stage="strategy"))
    result = service.run(started_at=NOW)
    assert result.status is PaperAutoSelectionE2EStatus.FAILED
    assert result.reason_codes == ("OLD_STRATEGY_DECISION_REJECTED",)
    assert not result.paper_order_created
    assert all(item[0] not in {"ai", "execution"} for item in chain.calls)


def test_ai_compatibility_callback_is_never_invoked():
    service, _, _, chain = e2e(chain=Chain(ai="HOLD", stale_stage="ai"))
    result = service.run(started_at=NOW)
    assert result.status is PaperAutoSelectionE2EStatus.COMPLETED_SWITCHED
    assert result.ai_decision == "NOT_REQUIRED"
    assert all(item[0] != "ai" for item in chain.calls)


def test_emergency_position_and_pending_block_before_decision_chain():
    cases = (
        ({"emergency": False}, "EMERGENCY_UNSAFE"),
        ({"position": "OPEN"}, "POSITION_NOT_FLAT"),
        ({"pending": True}, "PENDING_ORDER_EXISTS"),
    )
    for kwargs, reason in cases:
        service, manager, switch_runtime, chain = e2e(**kwargs)
        result = service.run(started_at=NOW)
        assert result.status is PaperAutoSelectionE2EStatus.COMPLETED_BLOCKED
        assert reason in result.reason_codes and not result.paper_order_created
        assert manager.activeSymbol == "ETHUSDT"
        assert switch_runtime.events == [] and chain.calls == []


def test_live_dryrun_and_real_order_safety_fail_before_auto_cycle():
    cases = (
        ({"mode": "live", "dry_run": True, "realOrderAllowed": False},
         "PAPER_E2E_LIVE_BLOCKED"),
        ({"mode": "paper", "dry_run": False, "realOrderAllowed": False},
         "PAPER_E2E_DRY_RUN_REQUIRED"),
        ({"mode": "paper", "dry_run": True, "realOrderAllowed": True},
         "PAPER_E2E_REAL_ORDER_FORBIDDEN"),
    )
    for config, reason in cases:
        service, manager, switch_runtime, chain = e2e(manager=Manager(config=config))
        result = service.run(started_at=NOW)
        assert result.status is PaperAutoSelectionE2EStatus.FAILED
        assert result.reason_codes == (reason,)
        assert manager.activeSymbol == "ETHUSDT"
        assert switch_runtime.events == [] and chain.calls == []


def test_unknown_initial_authority_fails_closed():
    state = {**SAFE_STATE, "governanceAvailable": False}
    service, _, switch_runtime, chain = e2e(initial_state=state)
    result = service.run(started_at=NOW)
    assert result.status is PaperAutoSelectionE2EStatus.FAILED
    assert not result.paper_order_created
    assert switch_runtime.events == [] and chain.calls == []

    missing, _, missing_switch, missing_chain = e2e(manager=Manager(active=None))
    missing_result = missing.run(started_at=NOW)
    assert missing_result.reason_codes == ("PAPER_E2E_ACTIVE_SYMBOL_UNKNOWN",)
    assert missing_switch.events == [] and missing_chain.calls == []


def test_manual_requested_symbol_is_not_consulted_or_promoted_to_authority():
    service, manager, _, chain = e2e()
    manager.requestedSymbol = "SOLUSDT"
    result = service.run(started_at=NOW)
    assert result.final_active_symbol == "BTCUSDT"
    assert manager.requestedSymbol == "SOLUSDT"
    assert {item[1] for item in chain.calls} == {"BTCUSDT"}


def test_dashboard_projection_follows_authority_and_keeps_candidate_separate():
    from backend.auto_market_selection import build_auto_market_selection_status

    service, manager, _, _ = e2e()
    result = service.run(started_at=NOW)
    observation = manager.auto_market_selection_observation
    status = build_auto_market_selection_status(
        active_symbol=manager.activeSymbol, requested_symbol="SOLUSDT",
        audit_event=observation["auditEvent"],
        proposal=observation["selectionProposal"],
        switch_result=observation["switchResult"],
        cycle=observation["autoSelectionCycle"],
    )
    assert status["activeSymbol"] == result.final_active_symbol == "BTCUSDT"
    assert status["topCandidate"]["symbol"] == "BTCUSDT"
    assert status["requestedSymbol"] == "SOLUSDT"
    assert status["autoRuntime"]["status"] == "COMPLETED"
    assert status["switch"]["state"] == "COMPLETED"
