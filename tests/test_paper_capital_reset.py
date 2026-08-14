from decimal import Decimal
import json
import threading

import pytest
from pydantic import ValidationError

from backend.api.bot_api import PaperCapitalRequest
from backend.bot_manager.bot_manager import BotManager
from backend.runtime.paper_account_store import PaperAccountStore, normalize_capital


def make_manager(tmp_path):
    manager = BotManager.__new__(BotManager)
    manager.paper_capital_lock = threading.RLock()
    manager.paper_account_store = PaperAccountStore(
        str(tmp_path / "paper-state.json"),
        str(tmp_path / "paper-history.jsonl"),
    )
    manager.paper_account_state = manager.paper_account_store.default_state()
    manager.account_snapshot = manager.paper_account_store.as_runtime_snapshot(
        manager.paper_account_state
    )
    manager.engine = None
    manager.pending_order = False
    manager.real_account_snapshot = {"balance": 792.0, "availableBalance": 7.92}
    manager.config = {
        "mode": "paper",
        "dry_run": True,
        "allowLive": False,
        "realOrderAllowed": False,
        "autoTradeEnabled": False,
    }
    return manager


@pytest.mark.parametrize("capital", ["100", "1000", "10000", "7.92"])
def test_reset_updates_all_paper_values_and_preserves_real_safety(tmp_path, capital):
    manager = make_manager(tmp_path)
    real_before = dict(manager.real_account_snapshot)
    config_before = dict(manager.config)

    response = manager.reset_paper_capital(Decimal(capital))

    expected = float(capital)
    assert response == {
        "success": True,
        "paperBalance": expected,
        "paperEquity": expected,
        "paperAvailableBalance": expected,
        "paperPnl": 0.0,
        "paperPositionState": "FLAT",
        "source": "DASHBOARD_MANUAL",
        "updatedAt": response["updatedAt"],
    }
    assert manager.account_snapshot["positions"] == []
    assert manager.account_snapshot["realizedPnl"] == 0.0
    assert manager.real_account_snapshot == real_before
    assert manager.config == config_before


@pytest.mark.parametrize(
    "capital",
    ["", "0", "-1", "NaN", "Infinity", "1000000000.01", "1.001"],
)
def test_invalid_capital_is_rejected(capital):
    with pytest.raises(ValueError):
        normalize_capital(capital)


def test_request_rejects_empty_nan_infinity_and_extra_fields():
    for value in ["", "NaN", "Infinity"]:
        with pytest.raises(ValidationError):
            PaperCapitalRequest(capital=value)
    with pytest.raises(ValidationError):
        PaperCapitalRequest(capital="100", dryRun=False)


def test_open_position_and_pending_order_are_rejected(tmp_path):
    manager = make_manager(tmp_path)
    manager.account_snapshot["position"] = {"side": "BUY", "size": 1}
    manager.account_snapshot["positions"] = [manager.account_snapshot["position"]]
    with pytest.raises(ValueError, match="PAPER_POSITION_OPEN"):
        manager.reset_paper_capital("100")

    manager = make_manager(tmp_path)
    manager.pending_order = True
    with pytest.raises(ValueError, match="PAPER_PENDING_ORDER"):
        manager.reset_paper_capital("100")


def test_reset_persists_across_store_restart_and_writes_audit_event(tmp_path):
    manager = make_manager(tmp_path)
    manager.reset_paper_capital("1234.56", "REAL_AVAILABLE_PRESET")

    restarted_store = PaperAccountStore(
        manager.paper_account_store.state_path,
        manager.paper_account_store.history_path,
    )
    restored = restarted_store.load()
    assert restored["capital"] == "1234.56"
    assert restored["balance"] == "1234.56"
    assert restored["positionState"] == "FLAT"
    event = json.loads(
        (tmp_path / "paper-history.jsonl").read_text(encoding="utf-8").strip()
    )
    assert event["event"] == "PAPER_CAPITAL_RESET"
    assert event["previousCapital"] == "1000.00"
    assert event["newCapital"] == "1234.56"
    assert event["source"] == "REAL_AVAILABLE_PRESET"
    assert event["result"] == "SUCCESS"


def test_saved_500_restores_stopped_loop_off_runtime_snapshot(tmp_path):
    store = PaperAccountStore(str(tmp_path / "paper-state.json"))
    saved = store.build_state("500", "DASHBOARD_MANUAL", 1234.5)
    store.save(saved)

    restored = store.load()
    snapshot = store.as_runtime_snapshot(restored)

    assert snapshot == {
        "balance": 500.0,
        "equity": 500.0,
        "availableBalance": 500.0,
        "pnl": 0.0,
        "position": None,
        "positions": [],
        "realizedPnl": 0.0,
        "unrealizedPnl": 0.0,
        "last_update": 1234.5,
        "available": True,
        "source": "DASHBOARD_MANUAL",
        "paperCapital": 500.0,
    }

    manager = make_manager(tmp_path)
    manager.paper_account_store = store
    manager.paper_account_state = restored
    manager.account_snapshot = snapshot
    manager.account_snapshot["positions"] = None
    manager.engine = None
    manager.loop_enabled = False
    runtime = manager._build_paper_account_runtime(
        manager._capture_account_snapshot()
    )
    assert runtime["balance"] == 500.0
    assert runtime["equity"] == 500.0
    assert runtime["availableBalance"] == 500.0
    assert runtime["totalPnl"] == 0.0
    assert runtime["positionState"] == "FLAT"
    assert runtime["source"] == "DASHBOARD_MANUAL"
    assert runtime["lastUpdate"] == 1234.5


def test_missing_state_uses_default_1000(tmp_path):
    store = PaperAccountStore(str(tmp_path / "missing.json"))
    restored = store.load()
    assert restored["capital"] == "1000.00"
    assert store.as_runtime_snapshot(restored)["balance"] == 1000.0


def test_corrupt_state_is_explicitly_unavailable_not_defaulted(tmp_path):
    path = tmp_path / "paper-state.json"
    path.write_text("{broken", encoding="utf-8")
    store = PaperAccountStore(str(path))

    restored = store.load()
    snapshot = store.as_runtime_snapshot(restored)

    assert restored["capital"] is None
    assert restored["restoreReason"] == "PAPER_ACCOUNT_STATE_CORRUPT"
    assert snapshot["available"] is False
    assert snapshot["reason"] == "PAPER_ACCOUNT_STATE_CORRUPT"
    assert snapshot["balance"] is None


def test_restore_does_not_change_real_account_or_money_management_input(tmp_path):
    manager = make_manager(tmp_path)
    real_before = dict(manager.real_account_snapshot)
    manager.paper_account_state = manager.paper_account_store.build_state(
        "500", "DASHBOARD_MANUAL", 1234.5
    )
    manager.account_snapshot = manager.paper_account_store.as_runtime_snapshot(
        manager.paper_account_state
    )

    snapshot = manager._capture_account_snapshot()
    assert snapshot["availableBalance"] == 500.0
    assert manager.real_account_snapshot == real_before
