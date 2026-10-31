"""Runtime truth integration tests for tradingai-context/v1.

These tests use injected projections only. They do not submit orders or
contact an exchange.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import inspect
from unittest.mock import patch

import pytest

from backend.context import (
    SCHEMA_VERSION,
    Availability,
    CanonicalContext,
    Freshness,
    RuntimeTruthSource,
    SafetyContext,
    ValueState,
    build_canonical_context,
    compose_tradingai_context,
    read_position_truth,
    to_canonical_json,
)
from backend.context.runtime_composer import compose_tradingai_context as compose_entry
from backend.runtime.current_position_view import current_position
from backend.runtime.cycle_diagnostics import build_trading_cycle_diagnostics
from backend.supervisor.contracts import ReadOnlySupervisorSnapshot
from tests.test_ai_context_support import FIXED_NOW, bot_payload, make_supervisor_snapshot


def _fields(section) -> dict[str, object]:
    return {item.name: item for item in section.fields}


def _paper_account(now: float, **position):
    return {
        "available": True,
        "lastUpdate": now,
        "positionState": "OPEN" if position else "FLAT",
        "positions": [position] if position else [],
        "unrealizedPnl": 1.25 if position else None,
    }


def _position_view(side: str, *, now: float, symbol: str = "XRPUSDTM"):
    account = _paper_account(
        now,
        symbol=symbol,
        side=side,
        qty=1,
        entry_price=0.5,
        entry_time=now - 30,
        entry_authority="MANUAL",
        coin_qty=10,
    )
    return current_position(account, "PAPER", now=now, symbol=symbol)


def test_schema_remains_compatible():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        supervisor_snapshot=make_supervisor_snapshot(),
        position_projection=_position_view("LONG", now=FIXED_NOW.timestamp()),
    )
    assert context.schemaVersion == SCHEMA_VERSION == "tradingai-context/v1"
    assert set(type(context).model_fields) == set(CanonicalContext.model_fields)
    assert context.safety == SafetyContext()
    revalidated = CanonicalContext.model_validate(context.model_dump())
    assert revalidated == context


def test_supervisor_snapshot_without_extras_matches_builder():
    snapshot = make_supervisor_snapshot()
    direct = build_canonical_context(
        generated_at=FIXED_NOW,
        runtime_truth=RuntimeTruthSource(snapshot=snapshot),
    )
    composed = compose_tradingai_context(
        generated_at=FIXED_NOW, supervisor_snapshot=snapshot
    )
    assert to_canonical_json(composed) == to_canonical_json(direct)


def test_open_long_position_uses_current_position_projection():
    now = FIXED_NOW.timestamp()
    view = _position_view("LONG", now=now)
    assert view["status"] == "OPEN"
    context = compose_tradingai_context(
        generated_at=FIXED_NOW, position_projection=view
    )
    fields = _fields(context.position)
    assert fields["status"].value == "OPEN"
    assert fields["side"].value == "LONG"
    assert fields["mode"].value == "PAPER"
    assert fields["symbol"].value == "XRPUSDTM"
    assert fields["contractQuantity"].value == 1
    assert fields["coinQuantity"].value == 10
    assert fields["avgEntry"].value == 0.5
    assert fields["pnlUsdt"].value == 1.25
    assert fields["durationSeconds"].value == pytest.approx(30)
    assert fields["observationScope"].value == "CURRENT"
    assert fields["riskPercent"].state is ValueState.UNAVAILABLE
    assert fields["pnlPercent"].state is ValueState.UNAVAILABLE
    assert fields["avgExit"].state is ValueState.UNAVAILABLE


def test_open_short_position():
    view = _position_view("SHORT", now=FIXED_NOW.timestamp())
    context = compose_tradingai_context(
        generated_at=FIXED_NOW, position_projection=view
    )
    fields = _fields(context.position)
    assert fields["status"].value == "OPEN"
    assert fields["side"].value == "SHORT"
    assert fields["mode"].value == "PAPER"


def test_flat_position():
    now = FIXED_NOW.timestamp()
    view = current_position(_paper_account(now), "PAPER", now=now)
    assert view["status"] == "FLAT"
    context = compose_tradingai_context(
        generated_at=FIXED_NOW, position_projection=view
    )
    fields = _fields(context.position)
    assert fields["status"].value == "FLAT"
    assert fields["side"].state is ValueState.NULL
    assert fields["quantity"].value is None


def test_unknown_position_is_not_open():
    now = FIXED_NOW.timestamp()
    view = current_position({"available": False, "lastUpdate": now}, "PAPER", now=now)
    context = compose_tradingai_context(
        generated_at=FIXED_NOW, position_projection=view
    )
    fields = _fields(context.position)
    assert fields["status"].value == "UNKNOWN"
    assert fields["status"].value != "OPEN"
    assert fields["side"].state is not ValueState.PRESENT


def test_multiple_positions_are_not_collapsed_to_open():
    now = FIXED_NOW.timestamp()
    account = {
        "available": True,
        "lastUpdate": now,
        "positions": [
            {"symbol": "XRPUSDTM", "side": "LONG", "qty": 1, "entry_price": 0.5, "entry_time": now - 5},
            {"symbol": "BTCUSDTM", "side": "SHORT", "qty": 2, "entry_price": 100, "entry_time": now - 5},
        ],
    }
    view = current_position(account, "PAPER", now=now)
    assert view["reason"] == "MULTIPLE_POSITIONS"
    context = compose_tradingai_context(
        generated_at=FIXED_NOW, position_projection=view
    )
    fields = _fields(context.position)
    assert fields["status"].value == "UNKNOWN"
    assert fields["ambiguity"].value == "MULTIPLE_POSITIONS"
    assert fields["side"].state is not ValueState.PRESENT
    assert fields["quantity"].state is not ValueState.PRESENT
    assert fields["positionCount"].value != 0
    contradictory = {
        "status": "OPEN",
        "mode": "LIVE",
        "side": "LONG",
        "symbol": "XRPUSDTM",
        "quantity": 1,
        "contractQuantity": 1,
        "source": "KUCOIN_FUTURES",
        "freshness": "FRESH",
        "sourceUpdatedAt": "2026-10-25T00:00:00Z",
        "positions": [
            {"symbol": "XRPUSDTM", "side": "LONG", "quantity": 1},
            {"symbol": "XRPUSDTM", "side": "LONG", "quantity": 2},
        ],
    }
    hidden = compose_tradingai_context(
        generated_at=FIXED_NOW, position_projection=contradictory
    )
    hidden_fields = _fields(hidden.position)
    assert hidden_fields["status"].value == "UNKNOWN"
    assert hidden_fields["ambiguity"].value == "MULTIPLE_POSITIONS"
    assert hidden_fields["positionCount"].value == 2
    assert hidden_fields["side"].state is not ValueState.PRESENT


def test_paper_account_is_not_reported_as_live():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        account_projection={
            "mode": "PAPER",
            "balance": 1000,
            "equity": 1000,
            "availableBalance": 800,
            "realizedPnl": 12,
            "source": "PAPER_SIMULATION",
            "lastUpdate": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    )
    fields = _fields(context.account)
    assert fields["mode"].value == "PAPER"
    assert fields["balance"].value == 1000
    assert fields["paperBalance"].value == 1000
    assert fields["liveBalance"].state is ValueState.UNAVAILABLE
    assert fields["liveBalance"].value is None
    assert fields["observationScope"].value == "CURRENT"


def test_live_account_is_not_reported_as_paper():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        account_projection={
            "selectedMode": "LIVE",
            "paperAccount": {
                "balance": 111,
                "equity": 111,
                "availableBalance": 111,
                "source": "PAPER_SIMULATION",
                "lastUpdate": "2026-10-25T00:00:00Z",
                "freshness": "FRESH",
            },
            "realAccount": {
                "balance": 222,
                "equity": 220,
                "availableBalance": 180,
                "unrealizedPnl": 4,
                "realizedPnl": 9,
                "marginUsed": 40,
                "source": "KUCOIN_FUTURES",
                "lastSync": "2026-10-25T00:00:00Z",
                "freshness": "FRESH",
            },
        },
    )
    fields = _fields(context.account)
    assert fields["mode"].value == "LIVE"
    assert fields["balance"].value == 222
    assert fields["paperBalance"].value == 111
    assert fields["liveBalance"].value == 222
    assert fields["balance"].value != fields["paperBalance"].value
    assert fields["equity"].value == 220
    assert fields["available"].value == 180
    assert fields["marginUsed"].value == 40


def test_missing_account_values_are_not_zero():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        account_projection={
            "mode": "PAPER",
            "equity": None,
            "source": "PAPER_SIMULATION",
            "lastUpdate": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    )
    fields = _fields(context.account)
    assert fields["balance"].state is ValueState.UNAVAILABLE
    assert fields["balance"].value is None
    assert fields["equity"].state is ValueState.NULL
    assert fields["equity"].value is None
    assert fields["currency"].state is ValueState.UNAVAILABLE
    for item in context.account.fields:
        if item.name in {"balance", "equity", "available", "unrealizedPnl", "realizedPnl", "marginUsed"}:
            assert item.value != 0


def test_small_account_mm_projection_is_copied():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        mm_projection={
            "availableCapital": "250.00",
            "riskBudget": "5.00",
            "riskPercent": "1.5",
            "leverage": "2",
            "stopLossPercent": "0.4",
            "marginMode": "ISOLATED",
            "parameterRevision": "rev-7",
            "mmStatus": "NORMAL",
            "source": "MONEY_MANAGEMENT_RUNTIME",
            "sourceUpdatedAt": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    )
    fields = _fields(context.smallAccount)
    assert fields["availableCapital"].value == "250.00"
    assert fields["riskBudget"].value == "5.00"
    assert fields["riskPercent"].value == "1.5"
    assert fields["leverage"].value == "2"
    assert fields["stopLossPercent"].value == "0.4"
    assert fields["marginMode"].value == "ISOLATED"
    assert fields["parameterRevision"].value == "rev-7"
    assert fields["mmStatus"].value == "NORMAL"
    assert fields["takeProfitPercent"].state is ValueState.UNAVAILABLE
    assert fields["trailingPercent"].state is ValueState.UNAVAILABLE
    assert fields["timeExitSeconds"].state is ValueState.UNAVAILABLE


def test_mm_blockers_are_preserved():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        mm_projection={
            "blockers": ["RISK_BUDGET_EXHAUSTED", "MAX_LEVERAGE"],
            "sourceUpdatedAt": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    )
    fields = _fields(context.smallAccount)
    assert fields["blockers"].state is ValueState.PRESENT
    assert "RISK_BUDGET_EXHAUSTED" in fields["blockers"].value
    assert "MAX_LEVERAGE" in fields["blockers"].value
    assert fields["availableCapital"].state is ValueState.UNAVAILABLE


def _diagnostics(**overrides):
    decision = {"timestamp": "2026-10-25T00:00:00Z"}
    decision.update(overrides)
    return build_trading_cycle_diagnostics(
        decision,
        context={"status": "RUNNING", "timestamp": decision["timestamp"]},
        evaluated_at=decision["timestamp"],
    )


def test_trading_cycle_steps_keep_diagnostic_status():
    diagnostics = _diagnostics()
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        trading_cycle_projection=diagnostics,
    )
    fields = _fields(context.tradingCycle)
    assert fields["stepCount"].value == 15
    assert fields["diagnosticScope"].value == "UNKNOWN"
    for step in diagnostics["steps"]:
        observed = fields[f"step.{step['index']}.status"]
        assert observed.value == step["status"]
        assert observed.value != "PASS"
    assert fields["step.10.status"].value == "UNKNOWN"
    assert fields["step.13.status"].value == "UNKNOWN"
    assert fields["step.10.userActionRequired"].value != "PASS"


def test_root_blocker_is_propagated():
    diagnostics = _diagnostics(
        blockingStage="MARKET",
        blockingReason="MARKET_STALE",
        currentStageIndex=2,
    )
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        trading_cycle_projection=diagnostics,
    )
    fields = _fields(context.tradingCycle)
    root = diagnostics["rootBlocker"]
    assert fields["rootBlocker"].value == root["reasonCode"]
    assert fields["rootBlockerStep"].value == diagnostics["rootBlockerStep"]
    assert fields["rootBlockerStep"].value == root["step"]


def test_historical_diagnostics_are_not_marked_current():
    diagnostics = _diagnostics()
    diagnostics["diagnosticsGeneratedAt"] = "2026-10-20T00:00:00Z"
    diagnostics["evaluatedAt"] = "2026-10-20T00:00:00Z"
    diagnostics["evaluationProvenance"] = {
        "provenance": "HISTORICAL",
        "evaluatedAt": "2026-10-20T00:00:00Z",
        "sourceUpdatedAt": "2026-10-20T00:00:00Z",
    }
    later = FIXED_NOW + timedelta(days=1)
    context = compose_tradingai_context(
        generated_at=later,
        trading_cycle_projection=diagnostics,
    )
    assert context.generatedAt == later
    assert context.tradingCycle.meta.observedAt == datetime(
        2026, 10, 20, tzinfo=timezone.utc
    )
    assert context.tradingCycle.meta.freshness is Freshness.STALE
    assert context.tradingCycle.meta.freshness is not Freshness.FRESH
    fields = _fields(context.tradingCycle)
    assert fields["diagnosticScope"].value == "HISTORICAL"
    assert fields["step.10.provenance"].value == "HISTORICAL"
    assert fields["step.10.status"].value == "UNKNOWN"


def test_missing_producer_timestamp_is_unknown_freshness():
    later = FIXED_NOW + timedelta(hours=3)
    context = compose_tradingai_context(
        generated_at=later,
        position_projection={
            "status": "OPEN",
            "symbol": "XRPUSDTM",
            "side": "LONG",
            "mode": "PAPER",
            "quantity": 1,
            "contractQuantity": 1,
            "freshness": "FRESH",
        },
    )
    assert context.position.meta.freshness is Freshness.UNKNOWN
    assert context.position.meta.observedAt is None
    assert context.generatedAt == later
    assert _fields(context.position)["observationScope"].value == "UNKNOWN"


def test_bot_authority_is_distinct_from_market_mode():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        execution_projection={
            "selectedMode": "PAPER",
            "tradeMode": "PAPER",
            "executionMode": "PAPER",
            "controlAuthority": "BOT",
            "entryAuthority": "BOT",
            "realOrderAllowed": False,
            "botState": "RUNNING",
            "loopState": "RUNNING",
            "emergencyState": "ARMED",
            "sourceEvaluatedAt": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    )
    fields = _fields(context.executionControl)
    assert fields["controlAuthority"].value == "BOT"
    assert fields["entryAuthority"].value == "BOT"
    assert fields["selectedMode"].value == "PAPER"
    assert fields["realOrderAllowed"].value is False
    assert fields["realOrderAllowedEvidence"].value == "EXPLICIT_FALSE"


def test_manual_authority():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        execution_projection={
            "selectedMode": "LIVE",
            "tradeMode": "LIVE",
            "controlAuthority": "MANUAL",
            "entryAuthority": "MANUAL",
            "realOrderAllowed": False,
            "sourceEvaluatedAt": "2026-10-25T00:00:00Z",
            "freshness": "FRESH",
        },
    )
    fields = _fields(context.executionControl)
    assert fields["controlAuthority"].value == "MANUAL"
    assert fields["entryAuthority"].value == "MANUAL"
    assert fields["controlAuthority"].value != "BOT"


def test_selected_mode_and_trade_mode_mismatch_is_kept():
    context = compose_tradingai_context(
        generated_at=FIXED_NOW,
        execution_projection={
            "selectedMode": "PAPER",
            "tradeMode": "LIVE",
            "executionMode": "PAPER",
            "sourceEvaluatedAt": "2026-10-25T00:00:00Z",
        },
    )
    fields = _fields(context.executionControl)
    assert fields["selectedMode"].value == "PAPER"
    assert fields["tradeMode"].value == "LIVE"
    assert fields["modeMismatch"].value == "TRUE"


def test_real_order_allowed_fails_closed():
    closed = compose_tradingai_context(
        generated_at=FIXED_NOW,
        execution_projection={"selectedMode": "LIVE", "tradeMode": "LIVE"},
    )
    fields = _fields(closed.executionControl)
    assert fields["realOrderAllowed"].value is False
    assert fields["realOrderAllowed"].value is not True
    assert fields["realOrderAllowed"].state is ValueState.UNKNOWN
    assert fields["realOrderAllowedEvidence"].value == "FAIL_CLOSED"

    explicit = compose_tradingai_context(
        generated_at=FIXED_NOW,
        execution_projection={"realOrderAllowed": True, "selectedMode": "LIVE"},
    )
    assert _fields(explicit.executionControl)["realOrderAllowed"].value is True

    ambiguous = compose_tradingai_context(
        generated_at=FIXED_NOW,
        execution_projection={"realOrderAllowed": "yes", "selectedMode": "LIVE"},
    )
    assert _fields(ambiguous.executionControl)["realOrderAllowed"].value is not True

    supervisor = make_supervisor_snapshot(bot=bot_payload(realOrderAllowed=True))
    preserved = compose_tradingai_context(
        generated_at=FIXED_NOW,
        supervisor_snapshot=supervisor,
        execution_projection={"selectedMode": "MANUAL", "tradeMode": "LIVE"},
    )
    preserved_fields = _fields(preserved.executionControl)
    assert preserved_fields["realOrderAllowed"].value is True
    assert "realOrderAllowedEvidence" not in preserved_fields or (
        preserved_fields["realOrderAllowedEvidence"].value != "FAIL_CLOSED"
    )


def test_readers_do_not_mutate_inputs_or_call_managers():
    snapshot = make_supervisor_snapshot()
    before = snapshot.model_copy(deep=True)
    position = _position_view("LONG", now=FIXED_NOW.timestamp())
    position_before = deepcopy(position)
    account = {
        "mode": "PAPER",
        "balance": 10,
        "source": "PAPER_SIMULATION",
        "lastUpdate": "2026-10-25T00:00:00Z",
        "freshness": "FRESH",
    }
    account_before = deepcopy(account)

    class LiveManager:
        def start(self):
            raise AssertionError("bot start")

        def get_status(self):
            raise AssertionError("status read")

    with pytest.raises(TypeError):
        compose_tradingai_context(generated_at=FIXED_NOW, bot_status=LiveManager())

    compose_tradingai_context(
        generated_at=FIXED_NOW,
        supervisor_snapshot=snapshot,
        position_projection=position,
        account_projection=account,
    )
    assert snapshot == before
    assert position == position_before
    assert account == account_before


def test_no_exchange_or_network_call():
    modules = (
        "backend.context.runtime_projection",
        "backend.context.runtime_truth",
        "backend.context.runtime_composer",
    )
    source = "\n".join(inspect.getsource(__import__(name, fromlist=["*"])) for name in modules)
    for banned in (
        "get_bot_manager",
        "KucoinTradeClient",
        "place_order",
        "create_order",
        "requests.",
        "httpx",
        "aiohttp",
    ):
        assert banned not in source
    now = FIXED_NOW.timestamp()
    with patch("socket.socket", side_effect=AssertionError("no network")):
        compose_tradingai_context(
            generated_at=FIXED_NOW,
            position_account=_paper_account(
                now,
                symbol="XRPUSDTM",
                side="LONG",
                qty=1,
                entry_price=0.5,
                entry_time=now - 30,
                coin_qty=10,
            ),
            position_mode="PAPER",
            position_now=FIXED_NOW,
            position_symbol="XRPUSDTM",
        )


def test_serialization_is_deterministic_and_excludes_secrets():
    projection = {
        "status": "OPEN",
        "symbol": "password=SUPERSECRET789",
        "side": "LONG",
        "mode": "PAPER",
        "quantity": 1,
        "contractQuantity": 1,
        "sourceUpdatedAt": "2026-10-25T00:00:00Z",
        "freshness": "FRESH",
        "source": "PAPER_SIMULATION",
    }
    mm = {
        "blockers": ["api_key=SUPERSECRET456"],
        "sourceUpdatedAt": "2026-10-25T00:00:00Z",
        "freshness": "FRESH",
    }
    first = compose_tradingai_context(
        generated_at=FIXED_NOW,
        position_projection=projection,
        mm_projection=mm,
    )
    second = compose_tradingai_context(
        generated_at=FIXED_NOW,
        position_projection=deepcopy(projection),
        mm_projection=deepcopy(mm),
    )
    payload = to_canonical_json(first)
    assert payload == to_canonical_json(second)
    assert "SUPERSECRET789" not in payload
    assert "SUPERSECRET456" not in payload
    assert first.safety.secretsIncluded is False
    assert first.safety.liveOrder is False
    assert first.safety.runtimeWrite is False
    assert first.safety.orderWrite is False


def test_position_reader_reuses_current_position_without_context_clock():
    now = FIXED_NOW.timestamp()
    account = _paper_account(
        now,
        symbol="XRPUSDTM",
        side="LONG",
        qty=1,
        entry_price=0.5,
        entry_time=now - 30,
        coin_qty=10,
    )
    observed = read_position_truth(account=account, mode="PAPER", now=FIXED_NOW, symbol="XRPUSDTM")
    fields = _fields(observed)
    assert fields["status"].value == "OPEN"
    assert fields["side"].value == "LONG"
    assert observed.meta.observedAt == FIXED_NOW


def test_compose_entry_point_is_internal():
    assert compose_entry is compose_tradingai_context
    context = compose_tradingai_context(generated_at=FIXED_NOW)
    assert context.position.meta.availability is Availability.UNAVAILABLE
    assert context.safety.liveOrder is False
    assert not hasattr(ReadOnlySupervisorSnapshot, "submit_order")
