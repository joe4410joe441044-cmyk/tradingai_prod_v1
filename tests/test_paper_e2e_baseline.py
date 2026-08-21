"""Test for Paper E2E baseline verification."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend.bot_manager import get_bot_manager
from backend.auto_market_selection import AutoMarketSelectionRuntime, PaperAutoSelectionE2E, PaperAutoSelectionLifecycle
from backend.market.kucoin_futures_public import KucoinFuturesPublicClient


NOW = datetime(2026, 8, 9, 3, tzinfo=timezone.utc)


class MockKucoinFuturesPublicClient:
    """Mock for KucoinFuturesPublicClient."""

    def get_active_contracts(self):
        return [
            type('Contract', (object,), {
                'canonical_symbol': 'BTCUSDT',
                'symbol': 'BTCUSDT',
                'price_tick': 0.5,
                'size_tick': 0.001,
                'max_leverage': 100,
            }),
            type('Contract', (object,), {
                'canonical_symbol': 'ETHUSDT',
                'symbol': 'ETHUSDT',
                'price_tick': 0.05,
                'size_tick': 0.01,
                'max_leverage': 100,
            }),
        ]

    def get_all_tickers(self):
        return {'BTCUSDT': {'price': 10000, 'funding_rate': 0.0001},
                'ETHUSDT': {'price': 2000, 'funding_rate': 0.0002}}


def test_paper_e2e_baseline():
    """Test Paper E2E baseline flow from strategy to position update."""
    
    # Mock bot manager
    bot_manager = MagicMock()
    bot_manager.get_official_mm_capital_authority.return_value = 10000
    bot_manager.get_authoritative_pending_order_state.return_value = {'position': None, 'pending': None}
    bot_manager.state = MagicMock()
    bot_manager.state.emergency_stop = False
    
    # Mock Kucoin futures client
    with patch.object(KucoinFuturesPublicClient, '__new__') as mock_kucoin:
        mock_kucoin.return_value = MockKucoinFuturesPublicClient()
        
        # Attach production paper auto selection
        from backend.auto_market_selection.paper_production import attach_production_paper_auto_selection
        attach_production_paper_auto_selection(bot_manager)
        
        # Verify lifecycle attached
        assert isinstance(bot_manager.auto_market_selection_lifecycle, PaperAutoSelectionLifecycle)
        
        # Verify lifecycle has E2E runtime
        assert hasattr(bot_manager.auto_market_selection_lifecycle, 'e2e_runtime')
        assert isinstance(bot_manager.auto_market_selection_lifecycle.e2e_runtime, PaperAutoSelectionE2E)
        
        # Verify E2E runtime has auto runtime
        assert hasattr(bot_manager.auto_market_selection_lifecycle.e2e_runtime, 'auto_runtime')
        assert isinstance(bot_manager.auto_market_selection_lifecycle.e2e_runtime.auto_runtime, AutoMarketSelectionRuntime)
        
        print("✅ Paper E2E baseline test passed")


def test_paper_production_composition():
    """Test composition of paper production components."""
    
    # Mock bot manager
    bot_manager = MagicMock()
    bot_manager.get_official_mm_capital_authority.return_value = 10000
    bot_manager.get_authoritative_pending_order_state.return_value = {'position': None, 'pending': None}
    bot_manager.state = MagicMock()
    bot_manager.state.emergency_stop = False
    
    # Mock Kucoin futures client
    with patch.object(KucoinFuturesPublicClient, '__new__') as mock_kucoin:
        mock_kucoin.return_value = MockKucoinFuturesPublicClient()
        
        # Attach production paper auto selection
        from backend.auto_market_selection.paper_production import attach_production_paper_auto_selection
        attach_production_paper_auto_selection(bot_manager)
        
        # Verify we can start and run cycle
        lifecycle = bot_manager.auto_market_selection_lifecycle
        # Set config to be in paper mode
        bot_manager.config = {'mode': 'paper', 'dry_run': True, 'realOrderAllowed': False}
        start_result = lifecycle.start()
        assert start_result['amsRuntimeState'] == 'READY'
        
        cycle_result = lifecycle.run_one_cycle(started_at=NOW)
        assert cycle_result['accepted'] is True
        
        print("✅ Paper production composition test passed")
