from unittest.mock import patch

import pytest

from backend.core.orderbook_manager import OrderBookManager


def test_get_current_price_logs_success_at_debug_without_error():
    manager = OrderBookManager()
    manager.current_price = 1.457115

    with patch("backend.core.orderbook_manager.logger") as logger:
        price = manager.get_current_price()

    assert price == 1.457115
    logger.debug.assert_called_once_with("🟢 GET_CURRENT_PRICE=1.457115")
    logger.error.assert_not_called()
    logger.exception.assert_not_called()


def test_get_current_price_preserves_existing_attribute_failure():
    manager = OrderBookManager()
    del manager.current_price

    with patch("backend.core.orderbook_manager.logger") as logger:
        with pytest.raises(AttributeError):
            manager.get_current_price()

    logger.error.assert_not_called()
    logger.exception.assert_not_called()
