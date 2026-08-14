from datetime import datetime, timezone
from decimal import Decimal

from backend.auto_market_selection.live_account_authority import LiveAccountAuthoritySnapshot
from backend.money_management.cash_flow_adjustment import reconcile_equity_change
from backend.money_management.live_initial_baseline import (
    APPROVAL_SOURCE, BaselineBootstrapStatus, LiveBaselineApproval,
    bootstrap_live_initial_baseline, build_live_initial_loss_state,
)
from backend.money_management.loss_persistence_adapter import LoadStatus, load_loss_state

NOW = datetime(2026, 8, 9, 11, 45, tzinfo=timezone.utc)


def snapshot(equity="10"):
    return LiveAccountAuthoritySnapshot(
        "REAL_LIVE_ACCOUNT", Decimal(equity), Decimal(equity), "FLAT", "NONE",
        Decimal("0"), None, NOW, True, (), NOW, NOW, NOW, True, True, True,
        snapshot_consistent=True, capital_source="LIVE_ACCOUNT",
        source_authority="REAL_LIVE_ACCOUNT",
    )


def approval():
    return LiveBaselineApproval(APPROVAL_SOURCE, NOW)


def safety():
    return {"botStopped": True, "autoTradeOff": True, "loopStopped": True,
            "realOrderAllowed": False, "liveAutoOff": True, "emergencyReady": True}


def test_initial_state_starts_managed_history_at_fresh_approved_equity():
    state = build_live_initial_loss_state(snapshot(), approval())
    assert state.schema_version == "money-management-loss-state/v1"
    assert state.drawdown_state.high_water_mark == Decimal("10")
    assert state.drawdown_state.current_equity == Decimal("10")
    assert state.daily_state.net_loss == state.weekly_state.net_loss == state.monthly_state.net_loss == 0
    assert state.cash_flow_state.net_cash_flow_amount == 0
    assert state.daily_state.last_updated_at == NOW


def test_bootstrap_is_atomic_rereadable_and_one_time(tmp_path):
    first = bootstrap_live_initial_baseline(snapshot(), approval(), persistence_directory=tmp_path,
                                            safety_state=safety(), captured_at=NOW)
    assert first.status is BaselineBootstrapStatus.CREATED
    loaded = load_loss_state(tmp_path)
    assert loaded.status is LoadStatus.VALID and loaded.state == first.state
    assert (tmp_path / "loss_limit_state.json").stat().st_mode & 0o777 == 0o600
    second = bootstrap_live_initial_baseline(snapshot("999"), approval(), persistence_directory=tmp_path,
                                             safety_state=safety(), captured_at=NOW)
    assert second.status is BaselineBootstrapStatus.BLOCKED
    assert second.reason == "AUTHORITATIVE_STATE_ALREADY_EXISTS"
    assert load_loss_state(tmp_path).state.drawdown_state.current_equity == Decimal("10")


def test_safety_or_stale_authority_blocks_without_file(tmp_path):
    bad = safety(); bad["liveAutoOff"] = False
    assert bootstrap_live_initial_baseline(snapshot(), approval(), persistence_directory=tmp_path,
                                           safety_state=bad).status is BaselineBootstrapStatus.BLOCKED
    stale = snapshot(); object.__setattr__(stale, "authority_fresh", False)
    result = bootstrap_live_initial_baseline(stale, approval(), persistence_directory=tmp_path,
                                             safety_state=safety())
    assert result.reason == "LIVE_ACCOUNT_STALE"
    assert not (tmp_path / "loss_limit_state.json").exists()


def test_deposit_is_cash_flow_not_profit_and_capital_tracks_current_equity():
    result = reconcile_equity_change(previous_equity=Decimal("10"), current_equity=Decimal("100"),
        net_external_cash_flow=Decimal("90"), previous_adjusted_equity=Decimal("10"),
        previous_adjusted_high_water_mark=Decimal("10"))
    assert result.current_equity == 100 and result.trading_pnl == 0
    assert result.adjusted_equity == 10 and result.drawdown_percent == 0


def test_withdrawal_is_not_loss_and_real_trading_loss_remains_loss():
    withdrawal = reconcile_equity_change(previous_equity=Decimal("100"), current_equity=Decimal("50"),
        net_external_cash_flow=Decimal("-50"), previous_adjusted_equity=Decimal("100"),
        previous_adjusted_high_water_mark=Decimal("100"))
    assert withdrawal.trading_pnl == 0 and withdrawal.drawdown_percent == 0
    loss = reconcile_equity_change(previous_equity=Decimal("100"), current_equity=Decimal("90"),
        net_external_cash_flow=Decimal("0"), previous_adjusted_equity=Decimal("100"),
        previous_adjusted_high_water_mark=Decimal("100"))
    assert loss.trading_pnl == -10 and loss.drawdown_percent == 10


def test_mixed_cash_flow_and_trading_pnl_are_separate():
    deposit_loss = reconcile_equity_change(previous_equity=Decimal("10"), current_equity=Decimal("95"),
        net_external_cash_flow=Decimal("90"), previous_adjusted_equity=Decimal("10"),
        previous_adjusted_high_water_mark=Decimal("10"))
    assert deposit_loss.trading_pnl == -5 and deposit_loss.adjusted_equity == 5
    withdrawal_profit = reconcile_equity_change(previous_equity=Decimal("100"), current_equity=Decimal("55"),
        net_external_cash_flow=Decimal("-50"), previous_adjusted_equity=Decimal("100"),
        previous_adjusted_high_water_mark=Decimal("100"))
    assert withdrawal_profit.trading_pnl == 5 and withdrawal_profit.adjusted_equity == 105
