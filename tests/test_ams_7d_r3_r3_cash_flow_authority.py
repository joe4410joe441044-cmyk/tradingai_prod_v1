from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.money_management.cash_flow_adjustment import reconcile_equity_change
from backend.money_management.external_cash_flow import (
    CashFlowCheckpoint, ExternalCashFlowType, advance_checkpoint,
    classify_deposit, classify_withdrawal, eligible_events,
    load_cash_flow_checkpoint, map_futures_ledger_item,
    net_external_cash_flow, save_cash_flow_checkpoint,
    validate_futures_ledger_page, validate_paginated_items,
)

BASELINE = datetime(2026, 8, 9, 11, 36, 12, 481464, tzinfo=timezone.utc)


def wallet(kind="deposit", status="SUCCESS", currency="USDT"):
    return {"id": "stable-wallet-id", "currency": currency, "status": status,
            "amount": "10", "fee": "0.1", "createdAt": 1786276000000,
            "updatedAt": 1786276001000}


def ledger(kind="TransferIn", status="Completed", offset=123, amount="10",
           currency="USDT", at=1786276000000):
    return {"offset": offset, "currency": currency, "type": kind,
            "amount": amount, "fee": "0", "time": at, "status": status,
            "accountEquity": "100"}


@pytest.mark.parametrize("status,expected", [("SUCCESS", "EXTERNAL_DEPOSIT_OBSERVATION"),
                                               ("PROCESSING", "IGNORED_NOT_FINAL"),
                                               ("FAILURE", "IGNORED_NOT_FINAL")])
def test_deposit_mapping_is_observation_not_profit(status, expected):
    assert classify_deposit(wallet(status=status)) == expected


@pytest.mark.parametrize("status,expected", [("SUCCESS", "EXTERNAL_WITHDRAWAL_OBSERVATION"),
                                               ("PROCESSING", "IGNORED_NOT_FINAL"),
                                               ("FAILURE", "IGNORED_NOT_FINAL")])
def test_withdrawal_mapping_uses_current_stable_id(status, expected):
    assert classify_withdrawal(wallet("withdrawal", status)) == expected


def test_futures_boundary_maps_completed_transfers_with_stable_offset():
    incoming = map_futures_ledger_item(ledger())
    outgoing = map_futures_ledger_item(ledger("TransferOut", offset=124))
    assert incoming.event_id == incoming.exchange_event_id == "123"
    assert incoming.event_type is ExternalCashFlowType.TRANSFER_IN and incoming.amount == 10
    assert outgoing.event_type is ExternalCashFlowType.TRANSFER_OUT and outgoing.amount == -10
    assert map_futures_ledger_item(ledger(status="Pending")) is None


@pytest.mark.parametrize("kind", ["RealisedPNL", "FundingFee", "TradingFee"])
def test_trading_activity_is_never_external_cash_flow(kind):
    assert map_futures_ledger_item(ledger(kind)) is None


def test_baseline_duplicate_and_restart_idempotency(tmp_path):
    old = ledger(offset=1, at=int(BASELINE.timestamp() * 1000) - 1)
    new = ledger(offset=2, at=int(BASELINE.timestamp() * 1000) + 1)
    events = eligible_events([new, old, new], baseline_at=BASELINE)
    assert [event.event_id for event in events] == ["2"]
    checkpoint = advance_checkpoint(CashFlowCheckpoint(), events,
                                    synced_at=datetime.now(timezone.utc))
    save_cash_flow_checkpoint(checkpoint, tmp_path)
    assert (tmp_path / "cash_flow_checkpoint.json").stat().st_mode & 0o777 == 0o600
    restarted = load_cash_flow_checkpoint(tmp_path)
    assert eligible_events([new], baseline_at=BASELINE,
                           processed_event_ids=restarted.processed_event_ids) == ()


def test_unsupported_currency_and_unknown_status_fail_closed():
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        map_futures_ledger_item(ledger(currency="BTC"))
    with pytest.raises(ValueError, match="unknown"):
        classify_deposit(wallet(status="MYSTERY"))


def test_pagination_is_strict():
    page = {"currentPage": 1, "pageSize": 50, "totalNum": 1,
            "totalPage": 1, "items": [wallet()]}
    assert len(validate_paginated_items(page, expected_page=1)) == 1
    page["currentPage"] = 2
    with pytest.raises(ValueError, match="pagination"):
        validate_paginated_items(page, expected_page=1)

    items, offset = validate_futures_ledger_page(
        {"dataList": [ledger(offset=12), ledger(offset=10)], "hasMore": True}
    )
    assert len(items) == 2 and offset == 10
    with pytest.raises(ValueError, match="inconsistency"):
        validate_futures_ledger_page({"dataList": [], "hasMore": True})


def test_cash_flow_connects_to_adjustment_without_profit_or_loss():
    events = eligible_events([ledger()], baseline_at=BASELINE)
    result = reconcile_equity_change(previous_equity=Decimal("100"),
        current_equity=Decimal("110"), net_external_cash_flow=net_external_cash_flow(events),
        previous_adjusted_equity=Decimal("100"), previous_adjusted_high_water_mark=Decimal("100"))
    assert result.trading_pnl == 0 and result.drawdown_percent == 0


def test_checkpoint_integrity_failure_is_closed(tmp_path):
    save_cash_flow_checkpoint(CashFlowCheckpoint(), tmp_path)
    path = tmp_path / "cash_flow_checkpoint.json"
    path.write_text(path.read_text().replace("KUCOIN", "KUCOIN-X"))
    with pytest.raises(ValueError, match="integrity"):
        load_cash_flow_checkpoint(tmp_path)
