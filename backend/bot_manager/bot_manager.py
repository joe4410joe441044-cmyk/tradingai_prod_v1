# -*- coding: utf-8 -*-

# =========================
# IMPORTS
# =========================
from backend.aggregation.MicrostructureStateBuilder import (
    MicrostructureStateBuilder
)

from backend.runtime import runtime_registry
from backend.runtime.governance_runtime import governance_state
from backend.runtime.runtime_health_snapshot import (
    build_runtime_health_snapshot,
)
import traceback
import os
import time
import uuid
from copy import deepcopy
from dotenv import load_dotenv

from backend.utils.log_buffer import (
    add_log,
    runtime_debug,
    ws_debug,
)

from backend.bot_manager.runtime_state import (
    BotRuntimeState
)

from backend.portfolio.portfolio_manager import (
    PortfolioManager
)

from backend.core.orderbook_manager import (
    OrderBookManager
)

from backend.strategy.orderflow_depth_strategy import (
    OrderFlowDepthStrategy,
)

from backend.market.exchange_factory import (
    ExchangeFactory
)

from backend.core.logger import (
    logger
)

from backend.execution.kucoin_trade import (
    KucoinTradeClient
)

from Bot.engine.execution_engine import (
    ExecutionEngine
)

load_dotenv()

# =========================
# BOT MANAGER
# =========================

class BotManager:

    def __init__(self):

        self.engine = None

        # ============================================
        # EXECUTION LOCK
        # ============================================

        self.pending_order = False

        # ============================================
        # COOLDOWN
        # ============================================

        self.last_order_time = 0

        self.cooldown_seconds = 2

        self.last_execution_time = 0

        # ============================================
        # FAILURE COOLDOWN
        # ============================================

        self.last_failure_time = 0

        self.failure_cooldown_sec = 10

        self.price_manager = None

        self._running = False

        self.symbol = None

        self.exchange_name = "kucoin"

        self.orderbook_source = "kucoin_futures"

        self.orderbook_symbol = None

        self.exchange = None

        self.config = {}

        # =========================
        # ORDERFLOW COMPONENTS
        # =========================

        self.ob_manager = None

        self.strategy = None

        self.ws = None

        # Browser monitor WebSockets are distinct from the exchange market
        # feed WebSocket.  The API router updates this observation-only count.
        self.browser_ws_clients = 0

        # =========================
        # SESSION
        # =========================

        self.session_id = 0

        # =========================
        # STATUS
        # =========================

        self.last_signal = None

        self.last_price = 0

        self.market_ready = False

        self.last_update_time = 0

        # Debug-only PriceProvider observation counter.
        self.provider_update_count = 0

        self.latest_runtime_result = None

        # Keep the latest account values independently from the execution
        # engine.  stop() intentionally tears the engine down, but account
        # telemetry must remain readable by the dashboard afterwards.
        self.account_snapshot = {
            "balance": 0.0,
            "equity": 0.0,
            "pnl": 0.0,
            "position": None,
            "last_update": time.time(),
        }

        # =========================
        # POSITION
        # =========================

        self.position = "NONE"

        self.entry_price = None

        # =========================
        # RISK
        # =========================

        self.tp_percent = 2.0

        self.sl_percent = 1.0

        # =========================
        # RUNTIME STATE
        # =========================

        self.state = BotRuntimeState()

        # ============================================
        # PROPAGATION UPDATE ID
        # ============================================

        self.update_id = 0

        # ============================================
        # ACTIVE RUNTIME
        # ============================================

        self.active_runtime_id = None
        # ============================================
        # MICROSTRUCTURE RUNTIME
        # ============================================

        self.microstructure_builder = (
            MicrostructureStateBuilder()
        )

    # ============================================
    # POSITION RECONCILIATION
    # ============================================

    def reconcile_positions(self):

        try:

            if self.state.reconciliation_running:

                return

            now = time.time()

            elapsed = (
                now
                - self.state.last_reconciliation_ts
            )

            if (
                elapsed
                < self.state.reconciliation_interval
            ):

                return

            self.state.reconciliation_running = True

            exchange_position = None

            if (
                self.engine
                and hasattr(self.engine, "get_position")
            ):

                exchange_position = (
                    self.engine.get_position()
                )

            self.state.exchange_position_cache = (
                exchange_position
            )

            local_position = (
                self.state.actual_position
            )

            if (
                exchange_position is None
                and local_position is not None
            ):

                logger.warning(
                    "[RECONCILIATION] "
                    "ghost local position detected"
                )

                self.state.actual_position = None

                self.state.position_state = "FLAT"

            elif (
                exchange_position is not None
                and local_position is None
            ):

                logger.warning(
                    "[RECONCILIATION] "
                    "exchange position exists "
                    "but local state is flat"
                )

                self.state.actual_position = (
                    exchange_position
                )

                self.state.position_state = "OPEN"

            elif (
                exchange_position is not None
                and local_position is not None
            ):

                exchange_side = (
                    exchange_position.get("side")
                    if isinstance(exchange_position, dict)
                    else None
                )

                local_side = (
                    local_position.get("side")
                    if isinstance(local_position, dict)
                    else None
                )

                if (
                    exchange_side
                    and local_side
                    and exchange_side != local_side
                ):

                    logger.warning(
                        "[RECONCILIATION] "
                        "position side mismatch"
                    )

                    self.state.actual_position = (
                        exchange_position
                    )

            self.state.last_reconciliation_ts = (
                time.time()
            )

        except Exception as e:

            logger.error(
                f"[RECONCILIATION_ERROR] {e}"
            )

        finally:

            self.state.reconciliation_running = False

    # ============================================
    # PROPAGATION TRACE UPDATE
    # ============================================

    def update_trace(
        self,
        stage,
        timestamp=None
    ):

        try:

            if timestamp is None:

                timestamp = time.time()

            trace = self.state.runtime_trace

            if stage not in trace:

                return

            trace[stage] = {
                "ok": True,
                "timestamp": timestamp,
                "update_id": self.update_id
            }

        except Exception as e:

            logger.error(
                f"[TRACE_UPDATE_ERROR] {e}"
            )

    def attach_orderbook_runtime_debug(self, runtime_result):

        if not isinstance(runtime_result, dict):
            return runtime_result

        runtime_debug_result = runtime_result.get(
            "runtimeDebug"
        )

        if not isinstance(runtime_debug_result, dict):
            runtime_debug_result = {}
            runtime_result["runtimeDebug"] = runtime_debug_result

        runtime_debug_result.update({
            "exchange": self.exchange_name,
            "orderbookSource": self.orderbook_source,
            "orderbookSymbol": self.orderbook_symbol,
        })

        return runtime_result

    # ============================================
    # START
    # ============================================

    def start(self, config):

        try:

            self.stop()

            self.session_id += 1

            current_session = (
                self.session_id
            )

            add_log(
                f"🆕 SESSION: "
                f"{current_session}"
            )

            self.position = "NONE"

            self.entry_price = None

            self.last_signal = None

            self.last_price = 0

            self.market_ready = False

            self.pending_order = False

            self.last_update_time = 0

            self.latest_runtime_result = None

            self.last_order_time = 0

            self.last_failure_time = 0

            self.update_id = 0

            self.provider_update_count = 0

            self.symbol = config["symbol"].upper()

            orderbook_context = (
                ExchangeFactory.describe_orderbook(
                    config.get("exchange", "kucoin"),
                    self.symbol,
                )
            )

            self.exchange_name = orderbook_context["exchange"]

            self.orderbook_source = orderbook_context[
                "orderbookSource"
            ]

            self.orderbook_symbol = orderbook_context[
                "orderbookSymbol"
            ]

            self.config = dict(config)

            self.config["exchange"] = self.exchange_name

            config = self.config

            self.tp_percent = config.get(
                "tp_percent",
                2.0
            )

            self.sl_percent = config.get(
                "sl_percent",
                1.0
            )

            add_log(
                f"🚀 START BOT: "
                f"{self.symbol}"
            )

            self.ob_manager = (
                OrderBookManager()
            )

            self.strategy = (
                OrderFlowDepthStrategy(
                    self.ob_manager
                )
            )

            exchange = None

            if config.get("mode") == "live":

                add_log(
                    "🟢 LIVE EXCHANGE ENABLED"
                )

                exchange = KucoinTradeClient()

            portfolio = PortfolioManager(
                initial_balance=1000
            )

            self.engine = ExecutionEngine(
                exchange=exchange,
                logger=logger,
                portfolio=portfolio,
                notifier=None,
                price_manager=self.ob_manager
            )

            if runtime_registry.trading_runtime:

                runtime_registry \
                    .trading_runtime \
                    .execution_runtime \
                    .set_engine(
                        self.engine
                    )

            from backend.routers.positions import (
                set_engine
            )

            set_engine(self.engine)

            self.reconcile_positions()

            self.engine.set_config(config)

            self.engine.symbol = self.symbol

            self.engine.start()

            runtime_metrics = (
                self.state.runtime_metrics
            )

            runtime_metrics[
                "ws_connected"
            ] = False

            runtime_metrics[
                "ws_thread_alive"
            ] = False

            runtime_metrics[
                "market_ready"
            ] = False

            def on_update(
                symbol,
                data,
                runtime_id
            ):

                now = time.time()

                self.update_id += 1

                rt = self.state.runtime_trace

                rm = self.state.runtime_metrics

                if runtime_id != self.active_runtime_id:

                    ws_debug(
                        "Stale callback blocked symbol=%s runtime_id=%s "
                        "active_runtime_id=%s",
                        symbol,
                        runtime_id,
                        self.active_runtime_id,
                    )

                    return

                if symbol != self.symbol:

                    ws_debug(
                        "Callback symbol mismatch blocked symbol=%s active=%s",
                        symbol,
                        self.symbol,
                    )

                    return

                if current_session != self.session_id:

                    return

                callback_symbol = data.get(
                    "symbol"
                )

                if callback_symbol != self.symbol:

                    ws_debug(
                        "Stale callback blocked callback_symbol=%s active=%s",
                        callback_symbol,
                        self.symbol,
                    )

                    return

                try:

                    # ============================================
                    # WS RECEIVE
                    # ============================================

                    self.update_trace(
                        "ws_receive",
                        now
                    )

                    rm[
                        "last_ws_message"
                    ] = now

                    rm[
                        "message_count"
                    ] += 1

                    rm[
                        "ws_connected"
                    ] = True

                    rm[
                        "ws_thread_alive"
                    ] = True

                    # ============================================
                    # CALLBACK FIRE
                    # ============================================

                    self.update_trace(
                        "callback_fire",
                        now
                    )

                    rm[
                        "last_callback"
                    ] = now

                    bids = data.get(
                        "bids",
                        {}
                    )

                    asks = data.get(
                        "asks",
                        {}
                    )

                    price = data.get(
                        "price",
                        data.get(
                            "last_price",
                            0
                        )
                    )

                    price_path_debug = dict(
                        data.get("price_path_debug")
                        or {}
                    )

                    price_path_debug.update({
                        "marketUpdatePrice": price,
                        "marketUpdateTime": now,
                    })
                    ws_debug(
                        "WebSocket callback symbol=%s active=%s bids=%d "
                        "asks=%d price=%s last_price=%s",
                        callback_symbol,
                        self.symbol,
                        len(bids),
                        len(asks),
                        data.get("price"),
                        data.get("last_price"),
                    )

                    if (
                        not bids
                        or not asks
                    ):

                        ws_debug("Empty callback orderbook")

                        return

                    provider_previous_price = (
                        self.ob_manager.current_price
                    )

                    self.ob_manager.update(
                        bids,
                        asks
                    )

                    self.ob_manager.current_price = (
                        price
                    )

                    self.provider_update_count += 1

                    provider_price = (
                        self.ob_manager.current_price
                    )

                    price_path_debug.update({
                        "providerPrice": provider_price,
                        "providerPreviousPrice": (
                            provider_previous_price
                        ),
                        "providerUpdateCount": (
                            self.provider_update_count
                        ),
                        "providerTimestamp": now,
                        "providerPriceChanged": (
                            provider_previous_price
                            != provider_price
                        ),
                    })

                    self.last_price = price

                    self.market_ready = True

                    self.last_update_time = (
                        time.time()
                    )

                    # ============================================
                    # RUNTIME PIPELINE
                    # ============================================

                    try:

                        buy_volume = sum(
                            float(size)
                            for size in bids.values()
                        )

                        sell_volume = sum(
                            float(size)
                            for size in asks.values()
                        )

                        packet = {

                            "buyVolume": buy_volume,

                            "sellVolume": sell_volume,

                            "orderbookBids": bids,

                            "orderbookAsks": asks,

                            "bestBid": float(
                                data.get("best_bid", 0)
                            ),

                            "bestAsk": float(
                                data.get("best_ask", 0)
                            ),

                            "lastPrice": float(price),

                            "pricePathDebug": price_path_debug,
                        }
                        runtime_debug(
                            "Runtime market packet=%s",
                            packet,
                        )

                        micro_state = (
                            self.microstructure_builder
                            .build_microstructure_state(
                                packet
                            )
                        )

                        if runtime_registry.trading_runtime:

                            self.latest_runtime_result = (
                                runtime_registry.trading_runtime.process_runtime(
                                    micro_state
                                )
                            )

                            self.attach_orderbook_runtime_debug(
                                self.latest_runtime_result
                            )

                    except Exception as runtime_error:

                        logger.exception(
                            "[RUNTIME PIPELINE ERROR]"
                        )

                    # ============================================
                    # BOT UPDATE
                    # ============================================

                    self.update_trace(
                        "bot_update",
                        time.time()
                    )

                    rm[
                        "last_bot_update"
                    ] = time.time()

                    rm[
                        "market_ready"
                    ] = True

                    rm[
                        "latency_ms"
                    ] = (
                        time.time() - now
                    ) * 1000

                    self.reconcile_positions()

                    if self.engine:

                        self.engine.on_price(
                            self.symbol,
                            price
                        )

                    signal = None

                    if signal:

                        self.last_signal = signal

                        self.state.strategy_state[
                            "signal"
                        ] = signal

                        add_log(
                            f"🟡 SIGNAL: "
                            f"{signal}"
                        )

                        if not self.engine:

                            return

                        if self.pending_order:

                            add_log(
                                "🛑 PENDING ORDER LOCK",
                                "warning"
                            )

                            return

                        current_time = time.time()

                        if (
                            current_time
                            - self.last_order_time
                            < self.cooldown_seconds
                        ):

                            return

                        if (
                            current_time
                            - self.last_failure_time
                            < self.failure_cooldown_sec
                        ):

                            return

                        self.pending_order = True

                        self.last_order_time = current_time

                        try:

                            runtime_debug(
                                "BotManager signal handoff to TradingRuntime"
                            )

                        except Exception as execution_error:

                            self.last_failure_time = (
                                time.time()
                            )

                            logger.error(
                                f"[EXECUTION_FAILURE] "
                                f"{execution_error}"
                            )

                            logger.error(
                                traceback.format_exc()
                            )

                        finally:

                            self.pending_order = False

                except Exception as e:

                    logger.error(
                        f"❌ on_update ERROR: "
                        f"{e}"
                    )

                    logger.error(
                        traceback.format_exc()
                    )

            self.active_runtime_id = str(
                uuid.uuid4()
            )

            ws_debug(
                "New WebSocket runtime id=%s",
                self.active_runtime_id,
            )

            add_log("ORDERBOOK WS STARTING")

            self.ws = (
                ExchangeFactory.create_market_ws(
                    exchange=self.exchange_name,
                    symbol=self.symbol,
                    on_update=on_update,
                    runtime_id=self.active_runtime_id
                )
            )

            ws_debug(
                "WebSocket client type=%s",
                type(self.ws).__name__,
            )

            runtime_metrics[
                "ws_thread_alive"
            ] = True

            self.ws.start()

            self._running = True

            add_log(
                "🟢 ORDERBOOK WS STARTED"
            )

            return {
                "status": "started",
                "symbol": self.symbol,
                "exchange": self.exchange_name,
                "orderbookSource": self.orderbook_source,
                "orderbookSymbol": self.orderbook_symbol,
            }

        except Exception as e:

            add_log(
                traceback.format_exc()
            )

            add_log(
                f"❌ BOT START ERROR: "
                f"{e}"
            )

            return {
                "status": "error",
                "reason": str(e),
            }

    # =========================
    # STOP
    # =========================

    def _capture_account_snapshot(self):

        if self.engine is None:

            return self.account_snapshot

        try:

            balance = float(
                getattr(self.engine, "balance", 0.0)
            )

            realized_pnl = float(
                getattr(self.engine, "pnl", 0.0)
            )

            unrealized_pnl = float(
                getattr(self.engine, "unrealized_pnl", 0.0)
            )

            self.account_snapshot = {
                "balance": balance,
                "equity": balance + unrealized_pnl,
                "pnl": realized_pnl + unrealized_pnl,
                "position": deepcopy(
                    getattr(self.engine, "actual_position", None)
                ),
                "last_update": time.time(),
            }

        except Exception as e:

            logger.error(
                f"❌ ACCOUNT SNAPSHOT ERROR: {e}"
            )

        return self.account_snapshot

    def stop(self):

        add_log(
            "🛑 BOT STOP"
        )

        self._running = False

        try:

            if self.ws:

                self.ws.stop()

                time.sleep(1)

            runtime_metrics = (
                self.state.runtime_metrics
            )

            runtime_metrics[
                "ws_connected"
            ] = False

            runtime_metrics[
                "ws_thread_alive"
            ] = False

            runtime_metrics[
                "market_ready"
            ] = False

            self.ws = None

            self.strategy = None

            self.ob_manager = None

            # Capture the last backend-owned values before removing the
            # engine.  /api/bot/status and /ws continue serving this snapshot
            # while execution is stopped.
            self._capture_account_snapshot()

            from backend.routers.positions import (
                set_engine
            )

            set_engine(None)

            if runtime_registry.trading_runtime:

                runtime_registry \
                    .trading_runtime \
                    .execution_runtime \
                    .set_engine(
                        None
                    )

            self.engine = None

            self._running = False

            self.position = "NONE"

            self.entry_price = None

            self.last_signal = None

            self.last_price = 0

            self.market_ready = False

            self.last_update_time = 0

            self.pending_order = False

            add_log(
                "🛑 BOT STOPPED"
            )

            return {
                "status": "stopped"
            }

        except Exception as e:

            add_log(
                f"❌ STOP ERROR: "
                f"{e}"
            )

            return {
                "status": "error",
                "reason": str(e),
            }

    # =========================
    # RESULT
    # =========================

    def get_result(self):

        stale_seconds = 0

        if self.last_update_time > 0:

            stale_seconds = (
                time.time()
                - self.last_update_time
            )

        market_stale = (
            not self._running
            or stale_seconds > 5
        )

        safe_price = (
            float(self.last_price)
            if self.market_ready
            else 0.0
        )

        snapshot = self._capture_account_snapshot()

        actual_position = deepcopy(
            snapshot.get("position")
        )

        pending_order = False

        pnl = float(snapshot.get("pnl", 0.0))

        balance = float(snapshot.get("balance", 0.0))

        equity = float(snapshot.get("equity", balance))

        latest_runtime_result = deepcopy(
            self.latest_runtime_result
        )

        latest_runtime_trace = (
            latest_runtime_result
            if isinstance(latest_runtime_result, dict)
            else {}
        )

        self.update_trace(
            "status_api",
            time.time()
        )

        self.state.runtime_metrics[
            "last_api_push"
        ] = time.time()

        trading_runtime = runtime_registry.trading_runtime
        execution_runtime = (
            getattr(trading_runtime, "execution_runtime", None)
            if trading_runtime is not None
            else None
        )
        runtime_healthy = bool(
            trading_runtime is not None
            and getattr(trading_runtime, "runtime_healthy", False)
            and execution_runtime is not None
            and getattr(execution_runtime, "runtime_healthy", False)
        )
        websocket_connected = bool(
            self.ws is not None
            and getattr(self.ws, "connected", False)
        )

        runtime_health = build_runtime_health_snapshot(
            running=self._running,
            market_stale=market_stale,
            exchange_ws_connected=websocket_connected,
            browser_ws_connected=self.browser_ws_clients > 0,
            browser_ws_clients=self.browser_ws_clients,
            engine_available=self.engine is not None,
            runtime_healthy=runtime_healthy,
            runtime_result=latest_runtime_trace,
            runtime_trace=self.state.runtime_trace,
            runtime_metrics=self.state.runtime_metrics,
            governance_state=governance_state,
            snapshot_timestamp=(
                self.state.runtime_metrics.get("last_bot_update")
                or time.time()
            ),
        )
        runtime_states = runtime_health["states"]

        if self.engine:

            actual_position = getattr(
                self.engine,
                "actual_position",
                None
            )

            pending_order = getattr(
                self.engine,
                "pending_order",
                False
            )

        position_candidate = (
            actual_position[0]
            if isinstance(actual_position, list) and actual_position
            else actual_position
        )

        position_side = (
            position_candidate.get("side")
            if isinstance(position_candidate, dict)
            else None
        )

        return {

            "timestamp": time.time(),

            "last_update": snapshot.get("last_update"),

            "price": safe_price,

            "marketReady": self.market_ready,

            "marketStale": market_stale,

            "lastUpdateAge": stale_seconds,

            "pnl": pnl,

            "balance": balance,

            "equity": equity,

            "position": actual_position,

            "actual_position": actual_position,

            "pendingOrder": pending_order,

            "signal": self.last_signal,

            "latestRuntimeResult": latest_runtime_result,

            "executionRuntimeReached": bool(
                latest_runtime_trace.get("executionRuntimeReached")
            ),

            "signalAdapterReached": bool(
                latest_runtime_trace.get("signalAdapterReached")
            ),

            "normalizedDirection": latest_runtime_trace.get(
                "normalizedDirection"
            ),

            "adapterOutput": latest_runtime_trace.get(
                "adapterOutput"
            ),

            "symbol": self.symbol,

            "exchange": self.exchange_name,

            "orderbookSource": self.orderbook_source,

            "orderbookSymbol": self.orderbook_symbol,

            "status": (
                "RUNNING"
                if self._running
                else "STOPPED"
            ),

            "runtime_trace": (
                self.state.runtime_trace
            ),

            "runtime_metrics": (
                self.state.runtime_metrics
            ),

            "strategy_state": (
                runtime_states["strategy"]
            ),

            "execution_state": (
                runtime_states["execution"]
            ),

            "ai_state": runtime_states["ai"],

            "governance_state": runtime_states["governance"],

            "runtime_health": runtime_health,

            "ws_connected": (
                websocket_connected
            ),

            "execution_mode": (
                "SIMULATION"
                if self.config.get(
                    "dry_run",
                    True
                )
                else "LIVE"
            ),

            "real_order_allowed": (
                not self.config.get(
                    "dry_run",
                    True
                )
            ),

            "cooldown_active": (
                self.last_execution_time
                and (
                    time.time()
                    - self.last_execution_time
                ) < 3
            ),

            "position_active": (
                actual_position is not None
            ),

            "position_side": (
                position_side
            ),

            "executionAuthorityScore": (
                100 if self.engine is not None else 0
            ),

            "authoritativeRuntimeState": (
                "STOPPED"
                if self.engine is None
                else (
                    "SYNCHRONIZED"
                    if self.market_ready
                    else "WAITING_MARKET"
                )
            ),

            "runtimeSynchronizationState": (
                "OFFLINE"
                if self.engine is None
                else (
                    "HEALTHY"
                    if not market_stale
                    else "STALE"
                )
            ),
        }

    # =========================
    # STATUS
    # =========================

    def get_status(self):
        return self.get_result()

    def set_browser_ws_connection_count(self, count):
        """Record connected dashboard clients without affecting trading."""

        self.browser_ws_clients = max(0, int(count or 0))

# =========================
# GLOBAL INSTANCE
# =========================

_bot_manager = None

# =========================
# GET BOT MANAGER
# =========================

def get_bot_manager():

    global _bot_manager

    if _bot_manager is None:

        _bot_manager = BotManager()

    return _bot_manager
