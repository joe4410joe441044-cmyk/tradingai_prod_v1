import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.runtime.ExecutionRuntime import ExecutionRuntime
from backend.runtime.governance_runtime import GovernanceRuntime, governance_state
from backend.runtime.trading_trace import trace_store


ROOT = Path(__file__).resolve().parents[1]


def strategy(direction="BUY", allowed=True, reason=None):
    return {
        "executionAllowed": allowed,
        "direction": direction,
        "edge": 0.9,
        "confidence": 0.9,
        "risk": 0.1,
        "suppressionReason": reason,
        "symbol": "BTCUSDT",
    }


class SyntheticPaperEngine:
    mode = "paper"
    dry_run = True
    exchange = None
    symbol = "BTCUSDT"

    def __init__(self, mm_allowed=True):
        self.mm_allowed = mm_allowed
        self.config = {"dry_run": True}
        self.actual_position = None
        self.paper_orders = []
        self.preflight_cleared = []

    def preflight_execution_entry(self, side, trace_id):
        return {
            "allowed": self.mm_allowed,
            "decision": "ALLOW" if self.mm_allowed else "BLOCK",
            "reason": None if self.mm_allowed else "RISK_BUDGET_EXCEEDED",
            "approvedQuantity": 0.01 if self.mm_allowed else None,
        }

    def clear_execution_entry_preflight(self, trace_id=None):
        self.preflight_cleared.append(trace_id)

    def get_risk_state(self):
        return {"riskTradingDisabled": False}

    def build_live_readiness(self):
        return {"realOrderAllowed": False, "executionEnabled": True}

    def submit_signal(self, signal):
        order_id = f"paper-{signal['traceId']}"
        self.paper_orders.append({"orderId": order_id, "traceId": signal["traceId"]})
        self.actual_position = {
            "state": "OPEN",
            "side": signal["side"],
            "coin_qty": 0.01,
            "entry_price": 100.0,
            "order_id": order_id,
        }


@pytest.fixture(autouse=True)
def governance_authority():
    previous = dict(governance_state)
    governance_state.update({"execution_enabled": True, "emergency_stop": False})
    try:
        yield
    finally:
        governance_state.clear()
        governance_state.update(previous)


def runtime_with_engine(mm_allowed=True):
    runtime = ExecutionRuntime()
    runtime.set_engine(SyntheticPaperEngine(mm_allowed=mm_allowed))
    return runtime


def run(runtime, state, governance_resolver=None, money_management_decision=None):
    with patch("backend.runtime.ExecutionRuntime.config.ALLOW_LIVE", False), patch(
        "backend.runtime.ExecutionRuntime.config.TRADE_MODE", "paper"
    ):
        return runtime.process_execution_runtime(
            state,
            governance_resolver=governance_resolver,
            money_management_decision=money_management_decision,
        )


def test_strategy_hold_makes_mm_not_required_and_does_not_execute():
    runtime = runtime_with_engine()
    result = run(runtime, strategy("HOLD", False, "ENTRY_THRESHOLD_NOT_MET"))

    assert result["moneyManagementReached"] is False
    assert result["governanceRuntimeReached"] is False
    assert result["handoffAttempted"] is False
    assert runtime.engine.paper_orders == []


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_strategy_candidate_reaches_mm_with_trading_ai_off(direction):
    runtime = runtime_with_engine(mm_allowed=False)
    result = run(runtime, strategy(direction), GovernanceRuntime().process_governance)

    assert result["tradingAiMode"] == "OFF"
    assert result["tradingAiStatus"] == "NOT_INSTALLED"
    assert result["aiRuntimeReached"] is False
    assert result["moneyManagementReached"] is True


def test_mm_block_prevents_governance_and_execution():
    calls = []
    runtime = runtime_with_engine(mm_allowed=False)
    result = run(runtime, strategy(), lambda value: calls.append(value))

    assert result["moneyManagementDecision"]["decision"] == "BLOCK"
    assert result["governanceRuntimeReached"] is False
    assert result["handoffAttempted"] is False
    assert calls == []


def test_mm_allow_reaches_governance_and_governance_block_prevents_execution():
    runtime = runtime_with_engine()
    result = run(
        runtime,
        strategy(),
        lambda _state: {"allowed": False, "reason": "OPERATOR_DISABLED"},
    )

    assert result["moneyManagementReached"] is True
    assert result["governanceRuntimeReached"] is True
    assert result["governanceDecision"] == "BLOCK"
    assert result["handoffAttempted"] is False
    assert runtime.engine.paper_orders == []


def test_governance_allow_reaches_synthetic_paper_execution():
    runtime = runtime_with_engine()
    result = run(runtime, strategy(), GovernanceRuntime().process_governance)

    assert result["moneyManagementDecision"]["decision"] == "ALLOW"
    assert result["governanceDecision"] == "ALLOW"
    assert result["handoffExecuted"] is True
    assert result["runtime"]["executionAllowed"] is True
    assert runtime.engine.paper_orders


def test_ai_off_trace_and_session_are_complete_and_normal():
    failed_before = trace_store.session(mode="PAPER")["failedTraces"]
    runtime = runtime_with_engine()
    result = run(runtime, strategy(), GovernanceRuntime().process_governance)
    trace = trace_store.trace(result["traceId"])
    session = trace_store.session(mode="PAPER")

    assert trace["finalStatus"] == "COMPLETE_EXECUTED"
    assert next(event for event in trace["events"] if event["stage"] == "AI")["status"] == "DISABLED"
    assert session["tradingAiMode"] == "OFF"
    assert session["tradingAiRequired"] is False
    assert session["incompleteTraces"] == 0
    # The store is intentionally process-global and other tests may retain
    # failed traces.  This AI-OFF decision must not add one.
    assert session["failedTraces"] == failed_before


def test_production_mainline_has_no_legacy_ai_import():
    production_files = [
        "backend/main.py",
        "backend/runtime/ExecutionRuntime.py",
        "backend/runtime/governance_runtime.py",
        "backend/strategy/MicrostructureEdgeStrategy.py",
        "Bot/engine/execution_engine.py",
    ]
    for relative in production_files:
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        imported = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert not any(name.startswith("backend.legacy_ai") for name in imported)


def test_ai_advisor_import_boundary_is_unchanged():
    from backend.ai_advisor.openai_sdk_transport import OpenAISDKTransport

    assert OpenAISDKTransport.__module__ == "backend.ai_advisor.openai_sdk_transport"
