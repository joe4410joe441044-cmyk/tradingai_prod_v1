from dataclasses import replace
from datetime import datetime, timezone

import pytest

from backend.money_management.cash_flow_transaction import (
    CashFlowCASConflict, commit_cash_flow_transaction,
    recover_cash_flow_transaction,
)
from backend.money_management.external_cash_flow import (
    CashFlowCheckpoint, advance_checkpoint, load_cash_flow_checkpoint,
    save_cash_flow_checkpoint,
)
from backend.money_management.loss_persistence_adapter import (
    LoadStatus, load_loss_state, save_loss_state,
)
from tests.test_money_management_loss_persistence_contract import state


NOW = datetime(2026, 8, 9, 12, 30, tzinfo=timezone.utc)


def setup_authority(path):
    original = state()
    assert save_loss_state(original, path).status.value == "SAVED"
    save_cash_flow_checkpoint(CashFlowCheckpoint(), path)
    return original


def candidate(original, event_id="101"):
    updated = replace(original, captured_at=original.captured_at)
    class Event:
        def __init__(self, value):
            self.event_id = value
    checkpoint = advance_checkpoint(CashFlowCheckpoint(), (Event(event_id),), synced_at=NOW)
    return updated, checkpoint


def test_atomic_transaction_success_and_restart_idempotency(tmp_path):
    original = setup_authority(tmp_path)
    updated, checkpoint = candidate(original)
    result = commit_cash_flow_transaction(
        base_directory=tmp_path, expected_revision=0, new_state=updated,
        new_checkpoint=checkpoint, event_ids=("101",), now=NOW,
    )
    assert result.revision == 1
    assert load_cash_flow_checkpoint(tmp_path).processed_event_ids == ("101",)
    assert recover_cash_flow_transaction(tmp_path) is None
    with pytest.raises(CashFlowCASConflict):
        commit_cash_flow_transaction(
            base_directory=tmp_path, expected_revision=0, new_state=updated,
            new_checkpoint=checkpoint, event_ids=("101",), now=NOW,
        )


def test_mid_commit_crash_is_completed_on_restart(tmp_path, monkeypatch):
    original = setup_authority(tmp_path)
    updated, checkpoint = candidate(original)
    import backend.money_management.cash_flow_transaction as transaction
    real_save = transaction.save_cash_flow_checkpoint
    monkeypatch.setattr(transaction, "save_cash_flow_checkpoint",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError, match="crash"):
        commit_cash_flow_transaction(
            base_directory=tmp_path, expected_revision=0, new_state=updated,
            new_checkpoint=checkpoint, event_ids=("101",), now=NOW,
        )
    assert load_loss_state(tmp_path).status is LoadStatus.VALID
    assert load_cash_flow_checkpoint(tmp_path).processed_event_ids == ()
    monkeypatch.setattr(transaction, "save_cash_flow_checkpoint", real_save)
    recovered = recover_cash_flow_transaction(tmp_path)
    assert recovered.recovered is True
    assert load_cash_flow_checkpoint(tmp_path).processed_event_ids == ("101",)


def test_fsync_failure_before_commit_changes_no_authority(tmp_path, monkeypatch):
    original = setup_authority(tmp_path)
    updated, checkpoint = candidate(original)
    import backend.money_management.cash_flow_transaction as transaction
    monkeypatch.setattr(transaction.os, "fsync",
                        lambda _fd: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(OSError, match="fsync"):
        commit_cash_flow_transaction(
            base_directory=tmp_path, expected_revision=0, new_state=updated,
            new_checkpoint=checkpoint, event_ids=("101",), now=NOW,
        )
    assert load_cash_flow_checkpoint(tmp_path).processed_event_ids == ()


def test_cas_rejects_wrong_revision(tmp_path):
    original = setup_authority(tmp_path)
    updated, checkpoint = candidate(original)
    with pytest.raises(CashFlowCASConflict):
        commit_cash_flow_transaction(
            base_directory=tmp_path, expected_revision=4, new_state=updated,
            new_checkpoint=checkpoint, event_ids=("101",), now=NOW,
        )
