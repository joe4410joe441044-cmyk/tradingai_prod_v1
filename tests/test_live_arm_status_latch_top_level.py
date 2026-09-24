"""LIVE ARM latch must be visible at /api/bot/status top-level.

E2E #002: ARM POST succeeded (armed=true) but status top-level
liveOrderEntryAllowed stayed false because get_result() omitted the field and
StatusResponse defaulted it to False. Nested tradeSettings held the true latch;
realOrderAllowed=true proved the engine latch was armed.
"""

from __future__ import annotations

from backend.api.bot_api import StatusResponse
from backend.bot_manager.bot_manager import BotManager


def _status_with_latch(*, armed: bool, runtime_start: bool = True):
    manager = BotManager()
    manager.config["mode"] = "live"
    manager.config["dry_run"] = False
    manager.config["liveRuntimeStartAllowed"] = runtime_start
    manager.config["liveOrderEntryAllowed"] = armed
    manager.config["executionEntryAllowed"] = armed
    manager.config["realOrderAllowed"] = armed
    return manager.get_status()


def test_status_raw_dict_includes_top_level_arm_latch_when_armed():
    raw = _status_with_latch(armed=True)
    assert "liveOrderEntryAllowed" in raw
    assert raw["liveOrderEntryAllowed"] is True
    assert raw["executionEntryAllowed"] is True
    assert raw["liveRuntimeStartAllowed"] is True
    assert raw["tradeSettings"]["liveOrderEntryAllowed"] is True
    assert raw["liveOrderEntryAllowed"] == raw["tradeSettings"]["liveOrderEntryAllowed"]
    assert raw["executionEntryAllowed"] == raw["tradeSettings"]["executionEntryAllowed"]


def test_status_response_model_preserves_armed_latch():
    raw = _status_with_latch(armed=True)
    model = StatusResponse(**raw)
    assert model.liveOrderEntryAllowed is True
    assert model.executionEntryAllowed is True
    assert model.liveRuntimeStartAllowed is True


def test_status_top_level_arm_latch_false_when_disarmed():
    raw = _status_with_latch(armed=False, runtime_start=True)
    assert raw.get("liveOrderEntryAllowed") is False
    assert raw.get("executionEntryAllowed") is False
    assert raw["tradeSettings"]["liveOrderEntryAllowed"] is False
    model = StatusResponse(**raw)
    assert model.liveOrderEntryAllowed is False
    assert model.executionEntryAllowed is False


def test_status_response_defaults_document_omit_mask_risk():
    """If get_result omits the latch keys, StatusResponse masks them as False."""
    assert StatusResponse.model_fields["liveOrderEntryAllowed"].default is False
    assert StatusResponse.model_fields["executionEntryAllowed"].default is False
    assert StatusResponse.model_fields["liveRuntimeStartAllowed"].default is False


def test_arm_post_echo_vs_status_owner_alignment_helpers():
    """tradeSettings builder is the status owner projection for the latch."""
    manager = BotManager()
    manager.config["liveOrderEntryAllowed"] = True
    manager.config["executionEntryAllowed"] = True
    manager.config["liveRuntimeStartAllowed"] = True
    snap = manager._build_trade_settings_snapshot(
        engine_config=manager.config,
        selected_mode="LIVE",
        dry_run=False,
        execution_mode="LIVE",
        real_order_allowed=True,
    )
    assert snap["liveOrderEntryAllowed"] is True
    assert snap["executionEntryAllowed"] is True
    assert snap["liveRuntimeStartAllowed"] is True
