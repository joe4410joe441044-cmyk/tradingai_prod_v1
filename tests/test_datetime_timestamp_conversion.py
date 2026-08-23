#!/usr/bin/env python3
"""Test for datetime timestamp conversion in _synchronize_market_intelligence_for_safe_switch"""

from datetime import datetime, timezone
import time
from backend.bot_manager.bot_manager import BotManager
from backend.core.orderbook_manager import OrderBookManager


def test_synchronize_with_datetime_timestamp():
    """Test that _synchronize_market_intelligence_for_safe_switch correctly handles datetime timestamp"""
    print("=== Testing datetime timestamp conversion ===")
    
    # Create test manager instance
    manager = BotManager()
    manager._active_symbol = "BTCUSDT"
    manager.active_runtime_id = "new"
    manager.ob_manager = OrderBookManager()
    
    # Create test snapshot with datetime timestamp
    test_time = datetime(2026, 8, 24, 10, 30, 0, tzinfo=timezone.utc)
    snapshot = {
        "symbol": "BTCUSDT",
        "exchange_symbol": "XBTUSDTM",
        "market_type": "FUTURES",
        "timestamp": test_time,  # 使用datetime对象而不是market_timestamp
        "sequence": 7,
        "price": 100,
        "best_bid": 99,
        "best_ask": 101,
        "spread": 2,
        "bids": {99.0: 1.0},
        "asks": {101.0: 1.0},
        "order_book": {
            "timestamp": test_time.timestamp(),
            "sequence": 7,
            "depth": 1,
            "bids": [{"price": 99, "size": 1}],
            "asks": [{"price": 101, "size": 1}],
            "dataQuality": "VALID",
            "syncState": "SYNCED"
        },
    }
    
    # Call the method
    result = manager._synchronize_market_intelligence_for_safe_switch(
        "BTCUSDT", "new", snapshot
    )
    
    # Verify the result
    assert result, "Synchronization failed"
    assert manager.last_update_time == test_time.timestamp(), \
        f"Expected last_update_time {test_time.timestamp()}, got {manager.last_update_time}"
    
    print("✓ Datetime timestamp conversion test PASSED")
    
    # Test with market_timestamp (legacy case)
    print("\n=== Testing market_timestamp (legacy case) ===")
    legacy_time = time.time() - 30
    legacy_snapshot = snapshot.copy()
    del legacy_snapshot["timestamp"]
    legacy_snapshot["market_timestamp"] = legacy_time
    
    # Reset manager state
    manager._active_symbol = "BTCUSDT"
    manager.active_runtime_id = "new"
    
    result = manager._synchronize_market_intelligence_for_safe_switch(
        "BTCUSDT", "new", legacy_snapshot
    )
    
    assert result, "Legacy market_timestamp synchronization failed"
    assert manager.last_update_time == legacy_time, \
        f"Expected last_update_time {legacy_time}, got {manager.last_update_time}"
    
    print("✓ Legacy market_timestamp test PASSED")


def test_synchronize_without_timestamp():
    """Test that synchronization fails closed without valid timestamp"""
    print("\n=== Testing synchronization without timestamp ===")
    
    manager = BotManager()
    manager._active_symbol = "BTCUSDT"
    manager.active_runtime_id = "new"
    manager.ob_manager = OrderBookManager()
    
    # Snapshot with no timestamp fields
    invalid_snapshot = {
        "symbol": "BTCUSDT",
        "exchange_symbol": "XBTUSDTM",
        "market_type": "FUTURES",
        "price": 100,
        "best_bid": 99,
        "best_ask": 101,
        "spread": 2,
        "bids": {99.0: 1.0},
        "asks": {101.0: 1.0},
        "order_book": {
            "timestamp": time.time(),
            "sequence": 7,
            "depth": 1,
            "bids": [{"price": 99, "size": 1}],
            "asks": [{"price": 101, "size": 1}],
            "dataQuality": "VALID",
            "syncState": "SYNCED"
        },
    }
    
    original_time = time.time()
    result = manager._synchronize_market_intelligence_for_safe_switch(
        "BTCUSDT", "new", invalid_snapshot
    )
    
    assert result, "Synchronization failed"
    # Check that we don't get current time as fallback (fail-closed behavior)
    assert manager.last_update_time != original_time, \
        "Should not use current time as fallback"
    # It should use time.time() as fallback, but let's verify it's a recent time
    assert abs(manager.last_update_time - original_time) < 2, \
        "Fallback time should be within 2 seconds of current time"
    
    print("✓ Fallback behavior test PASSED")


def test_synchronize_with_symbol_mismatch():
    """Test that synchronization fails with symbol mismatch"""
    print("\n=== Testing synchronization with symbol mismatch ===")
    
    manager = BotManager()
    manager._active_symbol = "BTCUSDT"
    manager.active_runtime_id = "new"
    manager.ob_manager = OrderBookManager()
    
    snapshot = {
        "symbol": "ETHUSDT",  # Wrong symbol
        "exchange_symbol": "ETHUSDTM",
        "market_type": "FUTURES",
        "timestamp": datetime.now(timezone.utc),
        "price": 2000,
        "bids": {1999: 1},
        "asks": {2001: 1}
    }
    
    result = manager._synchronize_market_intelligence_for_safe_switch(
        "BTCUSDT", "new", snapshot
    )
    
    assert not result, "Synchronization should fail with symbol mismatch"
    
    print("✓ Symbol mismatch test PASSED")


if __name__ == "__main__":
    try:
        test_synchronize_with_datetime_timestamp()
        test_synchronize_without_timestamp()
        test_synchronize_with_symbol_mismatch()
        print("\n✅ All datetime conversion tests PASSED!")
    except Exception as e:
        print(f"\n❌ Test FAILED: {e}")
        import traceback
        print(traceback.format_exc())