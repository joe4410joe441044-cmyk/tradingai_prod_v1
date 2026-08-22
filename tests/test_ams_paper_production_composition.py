"""Test composition of AMS paper production components."""

import pytest
import time
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
    bot_manager.get_authoritative_pending_order_state.return_value = {
        'known': True, 'pending': False, 'safe': True,
    }
    bot_manager.state = MagicMock()
    bot_manager.state.emergency_stop = False
    bot_manager.state.position_state = 'FLAT'
    
    # Mock Kucoin futures client
    governance = MagicMock()
    governance.process_governance = MagicMock()
    trading_runtime = MagicMock(governance_runtime=governance)
    with (patch.object(KucoinFuturesPublicClient, '__new__') as mock_kucoin,
          patch('backend.auto_market_selection.paper_production.runtime_registry.trading_runtime',
                trading_runtime)):
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


def test_paper_production_unknown_authority_is_fail_safe():
    bot_manager = MagicMock()
    bot_manager.get_official_mm_capital_authority.return_value = None
    bot_manager.get_authoritative_pending_order_state.return_value = {
        'known': False, 'pending': None, 'safe': False,
    }
    bot_manager.state.position_state = 'UNKNOWN'
    bot_manager.state.emergency_stop = None

    with patch.object(KucoinFuturesPublicClient, '__new__') as mock_kucoin:
        mock_kucoin.return_value = MockKucoinFuturesPublicClient()
        from backend.auto_market_selection.paper_production import (
            attach_production_paper_auto_selection,
        )
        attach_production_paper_auto_selection(bot_manager)

    readiness = bot_manager.auto_market_selection_lifecycle.readiness_provider()
    assert readiness['mmAvailable'] is False
    assert readiness['emergencySafe'] is False
    assert readiness['positionFlat'] is False
    assert readiness['pendingKnown'] is False
    assert readiness['pendingClear'] is False
    assert readiness['pendingSafe'] is False


def _production_manager():
    manager = MagicMock()
    manager.config = {
        'mode': 'paper', 'dry_run': True, 'realOrderAllowed': False,
    }
    manager._running = True
    manager.activeSymbol = 'BTCUSDT'
    manager.active_runtime_id = 'runtime-1'
    manager.exchange_name = 'kucoin'
    manager.orderbook_symbol = 'XBTUSDTM'
    manager.last_update_time = time.time()
    manager.market_ready = True
    manager.ob_manager.bids = {100.0: 2.0}
    manager.ob_manager.asks = {101.0: 3.0}
    manager.ob_manager.current_price = 100.5
    manager.microstructure_builder.build_microstructure_state.return_value = {
        'normalizedFeatureContract': True,
    }
    return manager


def test_production_pipeline_uses_formal_feature_and_runtime_and_preserves_hold():
    from backend.auto_market_selection.paper_production import (
        PaperProductionPipelineAdapter,
    )
    manager = _production_manager()
    execution_runtime = MagicMock()
    execution_runtime.engine.mode = 'paper'
    execution_runtime.engine.exchange = None
    execution_runtime.engine.paper_orders = []
    execution_runtime.handoff_attempted = False
    execution_runtime.handoff_executed = False
    runtime = MagicMock(execution_runtime=execution_runtime)
    runtime.process_runtime.return_value = {
        'valid': True,
        'strategyOutput': {
            'valid': True,
            'strategy': {
                'direction': 'HOLD',
                'executionAllowed': False,
                'suppressionReason': 'LOW_CONFIDENCE',
            },
        },
        'moneyManagementReached': False,
        'runtime': {'executionAllowed': False, 'reason': 'LOW_CONFIDENCE'},
    }
    context = {'symbol': 'BTCUSDT', 'runtimeId': 'runtime-1'}

    with patch(
        'backend.auto_market_selection.paper_production.runtime_registry.trading_runtime',
        runtime,
    ):
        result = PaperProductionPipelineAdapter(manager).run(context)

    manager.microstructure_builder.build_microstructure_state.assert_called_once()
    runtime.process_runtime.assert_called_once()
    assert manager.latest_runtime_result == runtime.process_runtime.return_value
    assert result['strategy']['decision'] == 'HOLD'
    assert result['moneyManagementReached'] is False
    assert result['paperOrderCreated'] is False


def test_production_pipeline_does_not_synthesize_paper_order():
    from backend.auto_market_selection.paper_production import (
        PaperProductionPipelineAdapter,
    )
    execution_runtime = MagicMock(handoff_executed=True)
    result = PaperProductionPipelineAdapter._project_result(
        {'symbol': 'BTCUSDT', 'runtimeId': 'runtime-1'},
        {
            'strategyOutput': {
                'strategy': {'direction': 'BUY', 'executionAllowed': True},
            },
            'moneyManagementReached': True,
            'moneyManagementDecision': {'allowed': True, 'decision': 'ALLOW'},
            'governanceRuntimeReached': True,
            'governanceOutput': {'allowed': True},
            'runtime': {'executionAllowed': False},
        },
        execution_runtime,
        paper_order_created=False,
    )
    assert result['paperOrderCreated'] is False
    assert result['paperFilled'] is False


def test_production_pipeline_blocks_attached_real_exchange_before_runtime():
    from backend.auto_market_selection.paper_production import (
        PaperProductionPipelineAdapter,
    )
    manager = _production_manager()
    execution_runtime = MagicMock()
    execution_runtime.engine.mode = 'paper'
    execution_runtime.engine.exchange = object()
    runtime = MagicMock(execution_runtime=execution_runtime)

    with patch(
        'backend.auto_market_selection.paper_production.runtime_registry.trading_runtime',
        runtime,
    ):
        result = PaperProductionPipelineAdapter(manager).run(
            {'symbol': 'BTCUSDT', 'runtimeId': 'runtime-1'},
        )

    assert result['valid'] is False
    assert result['reason'] == 'REAL_EXCHANGE_ATTACHED'
    runtime.process_runtime.assert_not_called()
