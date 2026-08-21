from datetime import datetime, timezone
from backend.market.kucoin_futures_public import (
    KucoinFuturesPublicClient, MarketUniverseSnapshot,
)
from backend.auto_market_selection import (
    AutoMarketSelectionRuntime, PaperAutoSelectionE2E, PaperAutoSelectionLifecycle,
)
from backend.auto_market_selection.market_scanner import TickerSnapshot
from backend.money_management.capital_eligibility import evaluate_market_capital_eligibility


def attach_production_paper_auto_selection(bot_manager):
    """Attach the production PAPER AUTO lifecycle to the bot manager."""

    # Create public market client
    public_client = KucoinFuturesPublicClient()

    # Create Auto Market Selection Runtime
    auto_runtime = AutoMarketSelectionRuntime(
        bot_manager,
        universe_provider=lambda: MarketUniverseSnapshot(
            public_client.get_active_contracts(),
            datetime.now(timezone.utc),
            "FRESH"
        ),
        ticker_provider=lambda: TickerSnapshot(
            public_client.get_all_tickers(),
            datetime.now(timezone.utc),
            "FRESH"
        ),
        capital_provider=bot_manager.get_official_mm_capital_authority,
        eligibility_provider=lambda universe, capital: {
            contract.canonical_symbol: evaluate_market_capital_eligibility(
                contract, capital
            )
            for contract in universe.contracts
        },
        position_provider=lambda: bot_manager.get_authoritative_pending_order_state().get("position"),
        pending_order_provider=lambda: bot_manager.get_authoritative_pending_order_state().get("pending"),
        emergency_provider=lambda: not bool(bot_manager.state.emergency_stop),
    )

    # Create Paper E2E Runtime
    e2e_runtime = PaperAutoSelectionE2E(
        bot_manager,
        auto_runtime,
        initial_state_provider=lambda: {
            "activeSymbolKnown": True,
            "positionKnown": True,
            "pendingOrderKnown": True,
            "mmAvailable": True,
            "emergencySafe": True,
            "governanceAvailable": True,
        },
        market_intelligence=lambda context: context,
        strategy=lambda market, context: {"decision": "BUY", "runtimeSymbolContext": context},
        ai_review=lambda strategy, context: {"decision": "NOT_REQUIRED", "runtimeSymbolContext": context},
        money_management=lambda strategy, context: {"decision": "ALLOW", "allowed": True, "runtimeSymbolContext": context},
        governance=lambda mm, context: {"decision": "ALLOW", "allowed": True, "runtimeSymbolContext": context},
        paper_execution=lambda governance, context: {"paperOrderCreated": True, "realExchangeCalled": False, "runtimeSymbolContext": context},
    )

    # Create readiness provider
    def readiness_provider():
        return {
            "dependenciesAvailable": True,
            "mmAvailable": bot_manager.get_official_mm_capital_authority() is not None,
            "emergencySafe": not bool(bot_manager.state.emergency_stop),
        }

    # Create and attach lifecycle
    lifecycle = PaperAutoSelectionLifecycle(
        bot_manager, e2e_runtime, readiness_provider=readiness_provider
    )
    bot_manager.auto_market_selection_lifecycle = lifecycle
