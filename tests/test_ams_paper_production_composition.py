"""Test composition of AMS paper production components."""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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


def test_attach_production_paper_auto_selection():
    """Test that attach_production_paper_auto_selection creates the correct components."""
    
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
        
        # Verify lifecycle exists and has correct type
        assert hasattr(bot_manager, 'auto_market_selection_lifecycle')
        assert isinstance(bot_manager.auto_market_selection_lifecycle, PaperAutoSelectionLifecycle)
        
        print("✅ attach_production_paper_auto_selection test passed")


def test_paper_production_lifecycle():
    """Test that PaperAutoSelectionLifecycle has all required components."""
    
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
        
        lifecycle = bot_manager.auto_market_selection_lifecycle
        
        # Verify lifecycle has E2E runtime
        assert hasattr(lifecycle, 'e2e_runtime')
        assert isinstance(lifecycle.e2e_runtime, PaperAutoSelectionE2E)
        
        # Verify E2E runtime has auto runtime
        assert hasattr(lifecycle.e2e_runtime, 'auto_runtime')
        assert isinstance(lifecycle.e2e_runtime.auto_runtime, AutoMarketSelectionRuntime)
        
        # Verify auto runtime has required providers
        auto_runtime = lifecycle.e2e_runtime.auto_runtime
        assert callable(auto_runtime.universe_provider)
        assert callable(auto_runtime.ticker_provider)
        assert callable(auto_runtime.capital_provider)
        assert callable(auto_runtime.eligibility_provider)
        assert callable(auto_runtime.position_provider)
        assert callable(auto_runtime.pending_order_provider)
        assert callable(auto_runtime.emergency_provider)
        
        print("✅ PaperAutoSelectionLifecycle components test passed")


def test_paper_production_readiness():
    """Test readiness provider for paper production."""
    
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
        
        lifecycle = bot_manager.auto_market_selection_lifecycle
        
        # Test readiness when MM available and no emergency
        readiness = lifecycle.readiness_provider()
        assert readiness['dependenciesAvailable'] is True
        assert readiness['mmAvailable'] is True
        assert readiness['emergencySafe'] is True
        
        # Test readiness when MM unavailable
        bot_manager.get_official_mm_capital_authority.return_value = None
        readiness = lifecycle.readiness_provider()
        assert readiness['mmAvailable'] is False
        
        # Test readiness when emergency stop active
        bot_manager.get_official_mm_capital_authority.return_value = 10000
        bot_manager.state.emergency_stop = True
        readiness = lifecycle.readiness_provider()
        assert readiness['emergencySafe'] is False
        
        print("✅ Paper production readiness test passed")
