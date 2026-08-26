from datetime import datetime, timezone

import pytest

from backend.bot_manager.bot_manager import BotManager
from backend.core.orderbook_manager import OrderBookManager


def manager():
    value = BotManager()
    value._active_symbol = "BTCUSDT"
    value.active_runtime_id = "runtime-1"
    value.ob_manager = OrderBookManager()
    return value


def snapshot(**overrides):
    value = {
        "symbol": "BTCUSDT",
        "timestamp": 1_800_000_000.0,
        "price": 100,
        "bids": {99.0: 1.0},
        "asks": {101.0: 1.0},
    }
    value.update(overrides)
    return value


def synchronize(value, observation):
    return value._synchronize_market_intelligence_for_safe_switch(
        "BTCUSDT", "runtime-1", observation
    )


def test_datetime_timestamp_is_normalized_to_epoch():
    value = manager()
    observed_at = datetime(2026, 8, 24, 10, 30, tzinfo=timezone.utc)
    assert synchronize(value, snapshot(timestamp=observed_at)) is True
    assert value.last_update_time == observed_at.timestamp()


def test_epoch_timestamp_and_legacy_market_timestamp_are_preserved():
    value = manager()
    assert synchronize(value, snapshot(timestamp=1_700_000_000.25)) is True
    assert value.last_update_time == 1_700_000_000.25
    legacy = snapshot()
    legacy.pop("timestamp")
    legacy["market_timestamp"] = 1_600_000_000.5
    assert synchronize(value, legacy) is True
    assert value.last_update_time == 1_600_000_000.5


@pytest.mark.parametrize(
    "timestamp",
    (None, True, 0, -1, "1800000000", float("nan"), float("inf")),
)
def test_invalid_or_missing_timestamp_fails_closed(timestamp):
    value = manager()
    observation = snapshot(timestamp=timestamp)
    before = value.last_update_time
    assert synchronize(value, observation) is False
    assert value.last_update_time == before
    assert value.market_ready is False
    assert value.ob_manager.bids == {}
    assert value.ob_manager.asks == {}


def test_stale_timestamp_is_not_replaced_with_current_time():
    value = manager()
    stale_at = 1_500_000_000.0
    assert synchronize(value, snapshot(timestamp=stale_at)) is True
    assert value.last_update_time == stale_at


def test_symbol_mismatch_fails_without_updating_freshness():
    value = manager()
    before = value.last_update_time
    assert synchronize(value, snapshot(symbol="ETHUSDT")) is False
    assert value.last_update_time == before
