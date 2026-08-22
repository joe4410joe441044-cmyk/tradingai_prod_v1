"""Production composition for the PAPER auto-selection lifecycle."""

from datetime import datetime, timezone
from decimal import Decimal
import math
import time

from backend.auto_market_selection import (
    AutoMarketSelectionRuntime,
    PaperAutoSelectionE2E,
    PaperAutoSelectionLifecycle,
)
from backend.auto_market_selection.market_scanner import TickerSnapshot
from backend.market.kucoin_futures_public import (
    KucoinFuturesPublicClient,
    MarketUniverseSnapshot,
)
from backend.money_management.capital_eligibility import (
    evaluate_market_capital_eligibility,
)
from backend.runtime import runtime_registry


class PaperProductionPipelineAdapter:
    """Bridge validated KuCoin telemetry into the authoritative mainline."""

    maximum_market_age_seconds = 5.0

    def __init__(self, bot_manager, *, clock=time.time):
        self.manager = bot_manager
        self.clock = clock

    def initial_state(self):
        pending = self.manager.get_authoritative_pending_order_state()
        position = getattr(self.manager.state, "position_state", None)
        trading_runtime = runtime_registry.trading_runtime
        governance = getattr(trading_runtime, "governance_runtime", None)
        return {
            "activeSymbolKnown": bool(self._active_symbol()),
            "positionKnown": position in {"FLAT", "OPEN"},
            "pendingOrderKnown": (
                isinstance(pending, dict)
                and pending.get("known") is True
                and type(pending.get("pending")) is bool
            ),
            "mmAvailable": (
                self.manager.get_official_mm_capital_authority() is not None
            ),
            "emergencySafe": (
                getattr(self.manager.state, "emergency_stop", None) is False
            ),
            "governanceAvailable": callable(
                getattr(governance, "process_governance", None)
            ),
        }

    def run(self, context):
        reason = self._safety_reason(context)
        if reason is not None:
            return self._blocked(context, reason)

        orderbook = getattr(self.manager, "ob_manager", None)
        bids = getattr(orderbook, "bids", None)
        asks = getattr(orderbook, "asks", None)
        price = getattr(orderbook, "current_price", None)
        if not isinstance(bids, dict) or not bids:
            return self._blocked(context, "MARKET_DATA_NOT_READY")
        if not isinstance(asks, dict) or not asks:
            return self._blocked(context, "MARKET_DATA_NOT_READY")
        if not self._positive_finite(price):
            return self._blocked(context, "MARKET_PRICE_INVALID")

        packet = {
            "buyVolume": sum(float(size) for size in bids.values()),
            "sellVolume": sum(float(size) for size in asks.values()),
            "orderbookBids": dict(bids),
            "orderbookAsks": dict(asks),
            "bestBid": float(max(bids)),
            "bestAsk": float(min(asks)),
            "lastPrice": float(price),
            "pricePathDebug": {
                "source": "KUCOIN_FUTURES_ORDERBOOK",
                "marketUpdateTime": self.manager.last_update_time,
            },
        }
        builder = getattr(self.manager, "microstructure_builder", None)
        build = getattr(builder, "build_microstructure_state", None)
        if not callable(build):
            return self._blocked(context, "FEATURE_BUILDER_UNAVAILABLE")
        try:
            microstructure = build(packet)
        except Exception:
            return self._blocked(context, "FEATURE_BUILDER_FAILED")
        if not isinstance(microstructure, dict):
            return self._blocked(context, "FEATURE_BUILDER_INVALID")

        trading_runtime = runtime_registry.trading_runtime
        process = getattr(trading_runtime, "process_runtime", None)
        if not callable(process):
            return self._blocked(context, "TRADING_RUNTIME_UNAVAILABLE")
        execution_runtime = getattr(trading_runtime, "execution_runtime", None)
        engine = getattr(execution_runtime, "engine", None)
        if engine is None or str(getattr(engine, "mode", "paper")).lower() != "paper":
            return self._blocked(context, "PAPER_EXECUTION_UNAVAILABLE")
        if getattr(engine, "exchange", None) is not None:
            return self._blocked(context, "REAL_EXCHANGE_ATTACHED")

        orders_before = len(getattr(engine, "paper_orders", ()) or ())
        result = process(
            microstructure,
            active_symbol=context["symbol"],
            runtime_id=context["runtimeId"],
        )
        self.manager.latest_runtime_result = result
        attach_debug = getattr(
            self.manager, "attach_orderbook_runtime_debug", None
        )
        if callable(attach_debug) and isinstance(result, dict):
            attach_debug(result)
        orders_after = len(getattr(engine, "paper_orders", ()) or ())
        return self._project_result(
            context, result, execution_runtime,
            paper_order_created=orders_after > orders_before,
        )

    def _safety_reason(self, context):
        config = getattr(self.manager, "config", None)
        if not isinstance(config, dict):
            return "PAPER_CONFIG_UNKNOWN"
        mode = str(config.get("mode", config.get("tradeMode", ""))).lower()
        if mode != "paper":
            return "PAPER_MODE_REQUIRED"
        if config.get("dry_run", config.get("dryRun")) is not True:
            return "DRY_RUN_REQUIRED"
        if config.get("realOrderAllowed", False) is not False:
            return "REAL_ORDER_FORBIDDEN"
        if getattr(self.manager, "_running", None) is not True:
            return "MARKET_DATA_NOT_READY"
        if context.get("symbol") != self._active_symbol():
            return "ACTIVE_SYMBOL_CONTEXT_INVALID"
        if context.get("runtimeId") != getattr(
            self.manager, "active_runtime_id", None
        ):
            return "ACTIVE_RUNTIME_CONTEXT_INVALID"
        if str(getattr(self.manager, "exchange_name", "")).lower() != "kucoin":
            return "REAL_MARKET_SOURCE_INVALID"
        if not getattr(self.manager, "orderbook_symbol", None):
            return "ORDERBOOK_SYMBOL_UNKNOWN"
        updated = getattr(self.manager, "last_update_time", None)
        if not self._positive_finite(updated):
            return "MARKET_DATA_NOT_READY"
        age = self.clock() - float(updated)
        if age < 0 or age > self.maximum_market_age_seconds:
            return "MARKET_DATA_STALE"
        if getattr(self.manager, "market_ready", None) is not True:
            return "MARKET_DATA_NOT_READY"
        return None

    @staticmethod
    def _project_result(context, result, execution_runtime, *, paper_order_created):
        if not isinstance(result, dict):
            return PaperProductionPipelineAdapter._blocked(
                context, "TRADING_RUNTIME_RESULT_INVALID"
            )
        strategy_wrapper = result.get("strategyOutput")
        strategy = (
            strategy_wrapper.get("strategy")
            if isinstance(strategy_wrapper, dict)
            else None
        )
        strategy = strategy if isinstance(strategy, dict) else {}
        direction = str(strategy.get("direction") or "HOLD").upper()
        decision = {
            "LONG": "BUY",
            "SHORT": "SELL",
        }.get(direction, direction)
        mm = result.get("moneyManagementDecision")
        mm = mm if isinstance(mm, dict) else {}
        governance = result.get("governanceOutput")
        governance = governance if isinstance(governance, dict) else {}
        runtime = result.get("runtime")
        runtime = runtime if isinstance(runtime, dict) else {}
        handoff_executed = bool(
            getattr(execution_runtime, "handoff_executed", False)
        )
        created = bool(paper_order_created and handoff_executed)
        return {
            "valid": bool(strategy),
            "runtimeSymbolContext": context,
            "strategy": {
                **strategy,
                "decision": decision,
            },
            "moneyManagement": {
                **mm,
                "decision": mm.get("decision") or (
                    "ALLOW" if mm.get("allowed") is True else "BLOCK"
                ),
            },
            "moneyManagementReached": result.get("moneyManagementReached") is True,
            "moneyManagementAllowed": mm.get("allowed") is True,
            "governance": {
                **governance,
                "decision": (
                    "ALLOW" if governance.get("allowed") is True else "BLOCK"
                ),
            },
            "governanceReached": result.get("governanceRuntimeReached") is True,
            "governanceAllowed": governance.get("allowed") is True,
            "paperExecutionReached": (
                governance.get("allowed") is True
                and bool(getattr(execution_runtime, "handoff_attempted", False))
            ),
            "paperOrderCreated": created,
            "paperFilled": created,
            "reason": runtime.get("reason"),
        }

    @staticmethod
    def _blocked(context, reason):
        return {
            "valid": False,
            "runtimeSymbolContext": context,
            "reason": reason,
        }

    @staticmethod
    def _positive_finite(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number > 0

    def _active_symbol(self):
        value = getattr(self.manager, "activeSymbol", None)
        return str(value).strip().upper() if value else None


def attach_production_paper_auto_selection(bot_manager):
    """Attach the production PAPER AUTO lifecycle to the bot manager."""

    public_client = KucoinFuturesPublicClient()
    auto_runtime = AutoMarketSelectionRuntime(
        bot_manager,
        universe_provider=lambda: MarketUniverseSnapshot(
            public_client.get_active_contracts(),
            datetime.now(timezone.utc),
            "FRESH",
        ),
        ticker_provider=lambda: TickerSnapshot(
            public_client.get_all_tickers(),
            datetime.now(timezone.utc),
            "FRESH",
        ),
        capital_provider=bot_manager.get_official_mm_capital_authority,
        eligibility_provider=lambda universe, capital: {
            contract.canonical_symbol: evaluate_market_capital_eligibility(
                contract,
                capital,
                stop_loss_percent=Decimal("1.0"),
                effective_cost_percent=Decimal("0.1"),
                risk_percent=Decimal("0.5"),
            )
            for contract in universe.contracts
        },
        position_provider=lambda: bot_manager.state.position_state,
        pending_order_provider=bot_manager.get_authoritative_pending_order_state,
        emergency_provider=lambda: (
            bot_manager.state.emergency_stop is False
        ),
    )
    pipeline = PaperProductionPipelineAdapter(bot_manager)
    e2e_runtime = PaperAutoSelectionE2E(
        bot_manager,
        auto_runtime,
        initial_state_provider=pipeline.initial_state,
        market_intelligence=None,
        strategy=None,
        ai_review=None,
        money_management=None,
        governance=None,
        paper_execution=None,
        production_pipeline=pipeline.run,
    )

    def readiness_provider():
        state = pipeline.initial_state()
        return {
            "dependenciesAvailable": state["governanceAvailable"],
            "mmAvailable": state["mmAvailable"],
            "emergencySafe": state["emergencySafe"],
            "positionFlat": (
                bot_manager.state.position_state == "FLAT"
            ),
            "pendingKnown": state["pendingOrderKnown"],
            "pendingClear": (
                bot_manager.get_authoritative_pending_order_state().get("pending")
                is False
            ),
            "pendingSafe": (
                bot_manager.get_authoritative_pending_order_state().get("safe")
                is True
            ),
        }

    bot_manager.auto_market_selection_lifecycle = PaperAutoSelectionLifecycle(
        bot_manager,
        e2e_runtime,
        readiness_provider=readiness_provider,
    )
