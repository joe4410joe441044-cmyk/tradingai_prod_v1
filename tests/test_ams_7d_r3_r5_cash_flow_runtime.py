from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Event, Thread

import pytest

from backend.money_management.cash_flow_runtime import (
    CashFlowAuthorityReader, CashFlowSyncRuntime, CashFlowSyncState,
)
from backend.money_management.cash_flow_transaction import CashFlowTransactionCoordinator
from backend.money_management.external_cash_flow import (
    CashFlowCheckpoint, load_cash_flow_checkpoint, save_cash_flow_checkpoint,
)
from backend.money_management.loss_persistence_adapter import save_loss_state
from tests.test_money_management_loss_persistence_contract import state


NOW = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)


def wallet_page(items=()):
    return {"currentPage": 1, "pageSize": 50, "totalNum": len(items),
            "totalPage": 1, "items": list(items)}


class Client:
    def __init__(self, ledgers=None, fail=None):
        self.ledgers = list(ledgers or [])
        self.fail = fail
        self.windows = []

    def get_deposit_history(self, **kwargs):
        if self.fail == "deposit": raise RuntimeError("deposit")
        return wallet_page()

    def get_withdrawal_history(self, **kwargs):
        if self.fail == "withdrawal": raise RuntimeError("withdrawal")
        return wallet_page()

    def get_futures_transaction_history(self, **kwargs):
        self.windows.append((kwargs["start_at"], kwargs["end_at"]))
        if self.fail == "ledger" or (self.fail == "window2" and len(self.windows) == 2):
            raise RuntimeError("ledger")
        return self.ledgers.pop(0) if self.ledgers else {"dataList": [], "hasMore": False}


def setup(path):
    original = state()
    assert save_loss_state(original, path).status.value == "SAVED"
    save_cash_flow_checkpoint(CashFlowCheckpoint(), path)
    return original


def test_reader_splits_deterministic_one_day_windows_and_maps_stably():
    item = {"offset": 9, "currency": "USDT", "type": "TransferIn",
            "amount": "5", "time": int((NOW + timedelta(days=1)).timestamp() * 1000),
            "status": "Completed"}
    client = Client([{"dataList": [], "hasMore": False},
                     {"dataList": [item], "hasMore": False},
                     {"dataList": [], "hasMore": False}])
    result = CashFlowAuthorityReader(client).read(
        start_at=NOW, end_at=NOW + timedelta(days=2, milliseconds=1))
    assert result == (item,)
    assert len(client.windows) == 2
    assert all(end - start <= 86_400_000 for start, end in client.windows)
    assert client.windows[1][0] == client.windows[0][1] + 1


def test_no_event_sync_updates_freshness_without_revision_or_state_rewrite(tmp_path):
    original = setup(tmp_path)
    target = tmp_path / "loss_limit_state.json"
    before = target.stat().st_mtime_ns
    runtime = CashFlowSyncRuntime(
        persistence_directory=tmp_path, reader=CashFlowAuthorityReader(Client()),
        equity_source=lambda: (_ for _ in ()).throw(AssertionError("not needed")),
        transaction_coordinator=CashFlowTransactionCoordinator(tmp_path), clock=lambda: NOW)
    runtime.initialize()
    result = runtime.sync_once()
    assert result.state is CashFlowSyncState.COMPLETED and result.events_applied == 0
    checkpoint = load_cash_flow_checkpoint(tmp_path)
    assert checkpoint.revision == 0 and checkpoint.last_successful_sync_at == NOW
    assert target.stat().st_mtime_ns == before


@pytest.mark.parametrize("failure", ["deposit", "withdrawal", "ledger", "window2"])
def test_any_required_get_failure_preserves_both_authorities(tmp_path, failure):
    setup(tmp_path)
    before_state = (tmp_path / "loss_limit_state.json").read_bytes()
    before_checkpoint = (tmp_path / "cash_flow_checkpoint.json").read_bytes()
    runtime = CashFlowSyncRuntime(
        persistence_directory=tmp_path,
        reader=CashFlowAuthorityReader(Client(fail=failure)),
        equity_source=lambda: Decimal("10"),
        transaction_coordinator=CashFlowTransactionCoordinator(tmp_path),
        clock=lambda: NOW + timedelta(days=2) if failure == "window2" else NOW)
    runtime.initialize()
    assert runtime.sync_once().state is CashFlowSyncState.FAILED
    assert (tmp_path / "loss_limit_state.json").read_bytes() == before_state
    assert (tmp_path / "cash_flow_checkpoint.json").read_bytes() == before_checkpoint


def test_concurrent_sync_is_rejected_without_second_read(tmp_path):
    setup(tmp_path)
    entered, release = Event(), Event()
    class BlockingReader:
        def read(self, **kwargs):
            entered.set(); release.wait(2); return ()
    runtime = CashFlowSyncRuntime(
        persistence_directory=tmp_path, reader=BlockingReader(),
        equity_source=lambda: Decimal("10"),
        transaction_coordinator=CashFlowTransactionCoordinator(tmp_path), clock=lambda: NOW)
    runtime.initialize()
    thread = Thread(target=runtime.sync_once); thread.start(); assert entered.wait(1)
    rejected = runtime.sync_once()
    assert rejected.accepted is False and rejected.reason == "SYNC_ALREADY_RUNNING"
    release.set(); thread.join(2)


def test_malformed_or_repeating_cursor_fails_closed():
    client = Client([{"dataList": [{"offset": 4}], "hasMore": True},
                     {"dataList": [{"offset": 4}], "hasMore": True}])
    with pytest.raises(ValueError, match="cursor"):
        CashFlowAuthorityReader(client).read(start_at=NOW, end_at=NOW)


def test_scheduler_shutdown_is_clean(tmp_path):
    setup(tmp_path)
    runtime = CashFlowSyncRuntime(
        persistence_directory=tmp_path, reader=CashFlowAuthorityReader(Client()),
        equity_source=lambda: Decimal("10"),
        transaction_coordinator=CashFlowTransactionCoordinator(tmp_path), clock=lambda: NOW,
        poll_interval_seconds=300)
    assert runtime.start(immediate=False) is True
    assert runtime.stop() is True
    assert runtime.read_model()["syncState"] == "STOPPED"
