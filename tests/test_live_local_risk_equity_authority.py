from types import SimpleNamespace

import pytest

from Bot.engine.execution_engine import ExecutionEngine
from backend.auto_market_selection.live_status_consistency import derive_live_readiness
from backend.bot_manager.bot_manager import BotManager
from backend.portfolio.portfolio_manager import PortfolioManager


LIVE_EQUITY = 7.91836966
LIVE_AUTHORITY = "REAL_LIVE_ACCOUNT_EQUITY"


def engine(mode="live", balance=LIVE_EQUITY):
    result = ExecutionEngine(portfolio=PortfolioManager(initial_balance=balance))
    result.mode = mode
    result.config["max_drawdown_pct"] = 5.0
    return result


def metrics(*, equity=LIVE_EQUITY, peak=LIVE_EQUITY, session=3,
            runtime="runtime-1", complete=True, authority=LIVE_AUTHORITY):
    return SimpleNamespace(
        equity=equity,
        peak_equity=peak,
        session_id=session,
        runtime_instance_id=runtime,
        is_complete=complete,
        accounting_authority_source=authority,
    )


def manager_with(local_engine, current):
    manager = BotManager.__new__(BotManager)
    manager.engine = local_engine
    manager.lifecycle_state = "RUNNING"
    manager.session_id = 3
    manager.runtime_instance_id = "runtime-1"
    manager.money_management_runtime_metrics = SimpleNamespace(
        snapshot=lambda: current
    )
    return manager


def test_live_fresh_equity_replaces_stale_paper_risk_baseline():
    local = engine()
    local.initial_equity = 100.0
    local.peak_equity = 100.0
    local.risk_trading_disabled = True
    local.risk_block_reason = "MAX_DRAWDOWN"

    assert local.apply_live_risk_equity_authority(
        initial_equity=LIVE_EQUITY,
        peak_equity=LIVE_EQUITY,
        authority_source=LIVE_AUTHORITY,
    ) is True
    assert local.initial_equity == pytest.approx(LIVE_EQUITY)
    assert local.peak_equity == pytest.approx(LIVE_EQUITY)
    assert local.current_drawdown_pct == pytest.approx(0)
    assert local.risk_trading_disabled is False
    assert local.risk_block_reason is None


def test_live_drawdown_gate_uses_canonical_hwm_and_is_not_relaxed():
    local = engine(balance=9.0)
    local.config["max_drawdown_pct"] = 5.0

    assert local.apply_live_risk_equity_authority(
        initial_equity=10.0,
        peak_equity=10.0,
        authority_source=LIVE_AUTHORITY,
    ) is True
    assert local.current_drawdown_pct == pytest.approx(10.0)
    assert local.risk_trading_disabled is True
    assert local.risk_block_reason == "MAX_DRAWDOWN"


def test_paper_baseline_is_untouched_by_live_authority_bridge():
    local = engine(mode="paper", balance=100.0)
    before = (local.initial_equity, local.peak_equity)

    assert local.apply_live_risk_equity_authority(
        initial_equity=LIVE_EQUITY,
        peak_equity=LIVE_EQUITY,
        authority_source=LIVE_AUTHORITY,
    ) is False
    assert (local.initial_equity, local.peak_equity) == before


@pytest.mark.parametrize(
    "kwargs",
    [
        {"initial_equity": None, "peak_equity": LIVE_EQUITY,
         "authority_source": LIVE_AUTHORITY},
        {"initial_equity": LIVE_EQUITY, "peak_equity": LIVE_EQUITY,
         "authority_source": "PAPER_RUNTIME_EQUITY"},
        {"initial_equity": LIVE_EQUITY, "peak_equity": 1.0,
         "authority_source": LIVE_AUTHORITY},
    ],
)
def test_invalid_or_missing_live_authority_fails_closed(kwargs):
    local = engine(balance=LIVE_EQUITY)
    local.initial_equity = 100.0
    local.peak_equity = 100.0
    local.risk_trading_disabled = True
    local.risk_block_reason = "MAX_DRAWDOWN"

    assert local.apply_live_risk_equity_authority(**kwargs) is False
    assert local.initial_equity == 100.0
    assert local.peak_equity == 100.0
    assert local.risk_trading_disabled is True


def test_manager_uses_current_complete_live_mm_authority():
    local = engine()
    local.initial_equity = 100.0
    local.peak_equity = 100.0
    current = metrics()
    manager = manager_with(local, current)

    assert manager._synchronize_live_execution_risk_authority() is True
    assert local.initial_equity == pytest.approx(LIVE_EQUITY)
    assert local.peak_equity == pytest.approx(LIVE_EQUITY)


@pytest.mark.parametrize(
    "current",
    [
        metrics(complete=False),
        metrics(session=2),
        metrics(runtime="stale-runtime"),
        metrics(authority="PAPER_RUNTIME_EQUITY"),
    ],
)
def test_stop_start_and_mode_authority_mismatch_cannot_rebase_local_risk(current):
    local = engine()
    local.initial_equity = 100.0
    local.peak_equity = 100.0
    manager = manager_with(local, current)

    assert manager._synchronize_live_execution_risk_authority() is False
    assert local.initial_equity == 100.0
    assert local.peak_equity == 100.0


def test_live_to_paper_switch_does_not_apply_live_hwm():
    local = engine(mode="paper", balance=100.0)
    manager = manager_with(local, metrics())

    assert manager._synchronize_live_execution_risk_authority() is False
    assert local.initial_equity == 100.0
    assert local.peak_equity == 100.0


def test_no_open_position_is_valid_fresh_flat_position_authority():
    result = derive_live_readiness(
        {"checks": {"executionEnabled": False}},
        {
            "authenticated": True,
            "connected": True,
            "stale": False,
            "apiKeyStatus": "VERIFIED",
            "balanceSource": "KUCOIN_FUTURES_READ_ONLY",
            "positionSource": "KUCOIN_FUTURES_READ_ONLY",
            "equity": LIVE_EQUITY,
            "positionSummary": "NO_OPEN_POSITION",
        },
    )

    assert result["checks"]["positionCheckOk"] is True
    assert "POSITION_CHECK_FAILED" not in result["blockReasons"]
