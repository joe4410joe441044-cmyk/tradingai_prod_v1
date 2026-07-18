# -*- coding: utf-8 -*-

# =========================
# IMPORTS
# =========================
from backend.aggregation.MicrostructureStateBuilder import (
    MicrostructureStateBuilder
)

from backend.runtime import runtime_registry
from backend.runtime.governance_runtime import (
    EMERGENCY_ACTION_REQUIRED,
    EMERGENCY_LOCKED,
    EMERGENCY_PROCESSING,
    EMERGENCY_READY,
    begin_emergency_operation,
    build_emergency_status,
    complete_emergency_operation,
    governance_state,
)
from backend.runtime.runtime_health_snapshot import (
    build_runtime_health_snapshot,
)
from backend import config as backend_config
import json
import traceback
import math
import os
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone
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

        self.emergency_orchestrator_lock = threading.Lock()
        # stop() and shutdown() share this re-entrant lifecycle boundary.
        # shutdown() delegates to stop(), so a plain Lock would deadlock.
        self.shutdown_lock = threading.RLock()
        self.stopped_paper_durable_rebind_lock = threading.Lock()

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

        self.lifecycle_state = "STOPPED"

        self.lifecycle_revision = 0

        self.lifecycle_changed_at = time.time()

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

        self.exchange_client_ready = False

        self.exchange_auth_ready = False

        self.exchange_auth_error = None

        self.balance_check_ok = False

        self.position_check_ok = False

        # Keep the latest account values independently from the execution
        # engine.  stop() intentionally tears the engine down, but account
        # telemetry must remain readable by the dashboard afterwards.
        self.account_snapshot = {
            "balance": None,
            "equity": None,
            "availableBalance": None,
            "pnl": None,
            "position": None,
            "positions": None,
            "realizedPnl": None,
            "unrealizedPnl": None,
            "last_update": None,
            "available": False,
        }

        self.account_snapshot_generation = 0
        self.account_refresh_interval = 30
        self.account_stale_after = 90
        self.runtime_instance_id = str(uuid.uuid4())
        self.stopped_paper_durable_snapshot_path = (
            self._default_stopped_paper_durable_snapshot_path()
        )
        self.stopped_paper_durable_snapshot_max_age = 7 * 24 * 60 * 60
        self.account_read_client = None
        self.account_read_client_exchange = None
        self.real_account_snapshot = (
            self._empty_real_account_snapshot(
                self.exchange_name,
                self.account_snapshot_generation,
                loading=False,
                reason="ACCOUNT_NOT_SYNCED",
            )
        )

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

    def _effective_engine_config(self):

        return (
            getattr(self.engine, "config", None)
            if self.engine
            else None
        ) or self.config or {}

    def _build_trade_settings_snapshot(
        self,
        engine_config,
        selected_mode,
        dry_run,
        execution_mode,
        real_order_allowed,
    ):

        return {
            "symbol": (
                self.symbol
                or self.config.get("symbol")
            ),
            "exchange": self.exchange_name,
            "orderbookSource": self.orderbook_source,
            "orderbookSymbol": self.orderbook_symbol,
            "mode": selected_mode,
            "dryRun": dry_run,
            "executionMode": execution_mode,
            "realOrderAllowed": real_order_allowed,
            "risk_percent": engine_config.get("risk_percent"),
            "leverage": engine_config.get("leverage"),
            "timeframe": engine_config.get(
                "timeframe",
                self.config.get("timeframe", "1m"),
            ),
            "sl_percent": engine_config.get("sl_percent"),
            "tp_percent": engine_config.get("tp_percent"),
        }

    def _normalize_account_exchange(self, exchange=None):

        return str(
            exchange
            or self.exchange_name
            or self.config.get("exchange")
            or "kucoin"
        ).strip().lower()

    def _empty_real_account_snapshot(
        self,
        exchange=None,
        generation=None,
        loading=False,
        reason="ACCOUNT_NOT_SYNCED",
    ):

        normalized_exchange = self._normalize_account_exchange(
            exchange
        )

        return {
            "exchange": normalized_exchange,
            "accountType": "UNKNOWN",
            "connected": False,
            "authenticated": False,
            "apiKeyPresent": False,
            "permission": "NOT_VERIFIED",
            "balance": None,
            "equity": None,
            "availableBalance": None,
            "positions": None,
            "positionSummary": None,
            "lastSync": None,
            "lastAttempt": None,
            "stale": False,
            "loading": bool(loading),
            "authReason": reason,
            "connectionReason": reason,
            "accountReason": reason,
            "balanceReason": reason,
            "positionReason": reason,
            "lastError": reason if reason != "ACCOUNT_NOT_SYNCED" else None,
            "accountSource": None,
            "balanceSource": None,
            "positionSource": None,
            "generation": (
                self.account_snapshot_generation
                if generation is None
                else generation
            ),
        }

    def _prepare_real_account_snapshot_for_exchange(
        self,
        exchange=None,
        loading=True,
    ):

        normalized_exchange = self._normalize_account_exchange(
            exchange
        )
        current_exchange = (
            self.real_account_snapshot or {}
        ).get("exchange")

        if current_exchange == normalized_exchange:
            return self.real_account_snapshot

        self.account_snapshot_generation += 1
        self.account_read_client = None
        self.account_read_client_exchange = None
        self.real_account_snapshot = (
            self._empty_real_account_snapshot(
                normalized_exchange,
                self.account_snapshot_generation,
                loading=loading,
                reason="ACCOUNT_EXCHANGE_CHANGED",
            )
        )

        return self.real_account_snapshot

    @staticmethod
    def _classify_account_error(error, default_reason):

        text = str(error or "").upper()

        if "TIMEOUT" in text or "TIMED OUT" in text:
            return "REQUEST_TIMEOUT"
        if "PERMISSION" in text or "FORBIDDEN" in text or "403" in text:
            return "PERMISSION_DENIED"
        if "AUTH" in text or "UNAUTHORIZED" in text or "401" in text:
            return "AUTH_FAILED"
        if "FUTURES" in text and "UNAVAILABLE" in text:
            return "FUTURES_ACCOUNT_UNAVAILABLE"
        if "CREDENTIAL" in text or "API KEY" in text:
            return "CREDENTIALS_MISSING"

        return default_reason

    @staticmethod
    def _normalize_positions_for_account(value):

        if value is None:
            return []

        if isinstance(value, list):
            return deepcopy(value)

        return [deepcopy(value)]

    @staticmethod
    def _position_summary(positions):

        if positions is None:
            return None

        if isinstance(positions, list):
            return (
                "NO_OPEN_POSITION"
                if not positions
                else "OPEN"
            )

        return "OPEN"

    @staticmethod
    def _legacy_real_position_value(positions):

        if isinstance(positions, list):
            if not positions:
                return []
            if len(positions) == 1:
                return deepcopy(positions[0])

        return deepcopy(positions)

    def _mark_real_account_stale_if_needed(self, snapshot):

        snapshot = dict(snapshot or {})
        last_sync = snapshot.get("lastSync")

        if (
            last_sync
            and time.time() - float(last_sync) > self.account_stale_after
        ):
            snapshot["stale"] = True
            snapshot["lastError"] = (
                snapshot.get("lastError")
                or "STALE_ACCOUNT_DATA"
            )

        self.real_account_snapshot = snapshot

        return snapshot

    def _get_real_account_snapshot(self, force=False):

        exchange = self._normalize_account_exchange()
        snapshot = self._prepare_real_account_snapshot_for_exchange(
            exchange,
            loading=False,
        )

        if (
            not self.config
            and self.engine is None
            and not force
        ):
            return snapshot

        if (
            not force
            and self.engine is None
            and not self.symbol
            and not self.config.get("symbol")
        ):
            return snapshot

        now = time.time()
        last_attempt = snapshot.get("lastAttempt")

        if (
            not force
            and last_attempt
            and now - float(last_attempt) < self.account_refresh_interval
            and not snapshot.get("loading")
        ):
            return self._mark_real_account_stale_if_needed(snapshot)

        return self._refresh_real_account_snapshot(exchange)

    def _refresh_real_account_snapshot(self, exchange=None):

        exchange = self._normalize_account_exchange(exchange)
        snapshot = self._prepare_real_account_snapshot_for_exchange(
            exchange,
            loading=True,
        )
        generation = snapshot.get("generation")
        previous = dict(snapshot or {})
        now = time.time()

        loading_snapshot = dict(previous)
        loading_snapshot.update({
            "loading": True,
            "lastAttempt": now,
        })
        self.real_account_snapshot = loading_snapshot

        def commit(next_snapshot):
            current_exchange = self._normalize_account_exchange()
            if (
                generation == self.account_snapshot_generation
                and exchange == current_exchange
            ):
                self.real_account_snapshot = next_snapshot
                return next_snapshot

            stale_snapshot = dict(next_snapshot)
            stale_snapshot.update({
                "stale": True,
                "loading": False,
                "lastError": "ACCOUNT_EXCHANGE_MISMATCH",
                "connectionReason": "ACCOUNT_EXCHANGE_MISMATCH",
                "accountReason": "ACCOUNT_EXCHANGE_MISMATCH",
                "balanceReason": "ACCOUNT_EXCHANGE_MISMATCH",
                "positionReason": "ACCOUNT_EXCHANGE_MISMATCH",
            })
            return stale_snapshot

        if exchange != "kucoin":
            unavailable = self._empty_real_account_snapshot(
                exchange,
                generation,
                loading=False,
                reason="EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE",
            )
            unavailable.update({
                "lastAttempt": now,
                "lastError": "EXCHANGE_ACCOUNT_CLIENT_UNAVAILABLE",
            })
            return commit(unavailable)

        api_key_present = KucoinTradeClient.credentials_present()

        if not api_key_present:
            missing = self._empty_real_account_snapshot(
                exchange,
                generation,
                loading=False,
                reason="CREDENTIALS_MISSING",
            )
            missing.update({
                "accountType": "KUCOIN_FUTURES",
                "lastAttempt": now,
                "lastError": "CREDENTIALS_MISSING",
            })
            return commit(missing)

        client = None
        connection_reason = "KUCOIN_CLIENT_READY"
        auth_reason = "KUCOIN_CREDENTIALS_PRESENT"

        try:
            if (
                self.account_read_client
                and self.account_read_client_exchange == exchange
            ):
                client = self.account_read_client
            else:
                client = KucoinTradeClient()
                self.account_read_client = client
                self.account_read_client_exchange = exchange
        except Exception as e:
            reason = self._classify_account_error(
                e,
                "AUTH_FAILED",
            )
            failed = self._empty_real_account_snapshot(
                exchange,
                generation,
                loading=False,
                reason=reason,
            )
            failed.update({
                "accountType": "KUCOIN_FUTURES",
                "apiKeyPresent": True,
                "lastAttempt": now,
                "lastError": reason,
            })
            return commit(failed)

        overview = {}
        balance_ok = False
        balance_reason = "BALANCE_FETCH_FAILED"

        try:
            overview = client.get_account_overview() or {}
            has_balance_value = any(
                overview.get(key) is not None
                for key in [
                    "balance",
                    "equity",
                    "availableBalance",
                ]
            )
            balance_ok = bool(has_balance_value)
            balance_reason = (
                "KUCOIN_BALANCE_SYNC_OK"
                if balance_ok
                else "BALANCE_FETCH_FAILED"
            )
        except Exception as e:
            balance_reason = self._classify_account_error(
                e,
                "BALANCE_FETCH_FAILED",
            )

        positions = None
        position_ok = False
        position_reason = "POSITION_FETCH_FAILED"

        try:
            positions = self._normalize_positions_for_account(
                client.get_positions(
                    self.orderbook_symbol
                    or self.symbol
                )
            )
            position_ok = True
            position_reason = "KUCOIN_POSITION_SYNC_OK"
        except Exception as e:
            position_reason = self._classify_account_error(
                e,
                "POSITION_FETCH_FAILED",
            )

        authenticated = balance_ok or position_ok
        successful_sync = authenticated
        last_sync = (
            now
            if successful_sync
            else previous.get("lastSync")
        )
        stale = (
            (not balance_ok or not position_ok)
            and previous.get("lastSync") is not None
        )
        last_error = None

        if not balance_ok:
            last_error = balance_reason
        if not position_ok and last_error is None:
            last_error = position_reason

        balance = (
            overview.get("balance")
            if balance_ok
            else previous.get("balance")
            if stale
            else None
        )
        equity = (
            overview.get("equity")
            if balance_ok
            else previous.get("equity")
            if stale
            else None
        )
        available_balance = (
            overview.get("availableBalance")
            if balance_ok
            else previous.get("availableBalance")
            if stale
            else None
        )
        positions_value = (
            positions
            if position_ok
            else previous.get("positions")
            if stale
            else None
        )
        account_reason = (
            "KUCOIN_READ_ONLY_SYNC_OK"
            if authenticated
            else last_error
            or "AUTH_FAILED"
        )
        auth_reason = (
            "KUCOIN_CREDENTIALS_VERIFIED"
            if authenticated
            else last_error
            or auth_reason
        )

        refreshed = {
            "exchange": exchange,
            "accountType": overview.get(
                "accountType",
                "KUCOIN_FUTURES",
            ),
            "connected": client is not None,
            "authenticated": authenticated,
            "apiKeyPresent": True,
            "permission": (
                overview.get("permission")
                or ("READ_ONLY" if authenticated else "NOT_VERIFIED")
            ),
            "balance": balance,
            "equity": equity,
            "availableBalance": available_balance,
            "positions": positions_value,
            "positionSummary": self._position_summary(
                positions_value
            ),
            "lastSync": last_sync,
            "lastAttempt": now,
            "stale": stale,
            "loading": False,
            "authReason": auth_reason,
            "connectionReason": connection_reason,
            "accountReason": account_reason,
            "balanceReason": balance_reason,
            "positionReason": position_reason,
            "lastError": last_error,
            "accountSource": (
                "KUCOIN_FUTURES_READ_ONLY"
                if authenticated
                else None
            ),
            "balanceSource": (
                "KUCOIN_FUTURES_READ_ONLY"
                if balance_ok
                else None
            ),
            "positionSource": (
                "KUCOIN_FUTURES_READ_ONLY"
                if position_ok
                else None
            ),
            "generation": generation,
        }

        return commit(refreshed)

    def _build_paper_account_runtime(self, snapshot):

        snapshot = dict(snapshot or {})
        available = bool(snapshot.get("available"))
        position = deepcopy(snapshot.get("position"))
        positions = (
            []
            if available and position is None
            else [deepcopy(position)]
            if available
            else None
        )

        return {
            "balance": snapshot.get("balance") if available else None,
            "equity": snapshot.get("equity") if available else None,
            "availableBalance": (
                snapshot.get("availableBalance")
                if available
                else None
            ),
            "position": position if available else None,
            "positions": positions,
            "realizedPnl": (
                snapshot.get("realizedPnl")
                if available
                else None
            ),
            "unrealizedPnl": (
                snapshot.get("unrealizedPnl")
                if available
                else None
            ),
            "totalPnl": snapshot.get("pnl") if available else None,
            "source": "PAPER_SIMULATION",
            "lastUpdate": snapshot.get("last_update") if available else None,
            "available": available,
        }

    def _build_account_runtime(
        self,
        account_snapshot,
        live_readiness,
        selected_mode,
        dry_run,
        execution_mode,
        real_order_allowed,
    ):

        real_account = dict(
            live_readiness.get("realAccount") or
            self._get_real_account_snapshot()
        )

        return {
            "paperAccount": self._build_paper_account_runtime(
                account_snapshot
            ),
            "realAccount": real_account,
            "execution": {
                "selectedMode": selected_mode,
                "executionMode": execution_mode,
                "realOrderAllowed": real_order_allowed,
                "dryRun": dry_run,
                "allowLive": backend_config.ALLOW_LIVE,
                "tradeMode": backend_config.TRADE_MODE,
                "liveBlockReasons": live_readiness.get(
                    "blockReasons",
                    [],
                ),
            },
            "connection": {
                "exchange": real_account.get("exchange"),
                "connected": real_account.get("connected"),
                "authenticated": real_account.get("authenticated"),
                "apiKeyPresent": real_account.get("apiKeyPresent"),
                "apiKeyStatus": (
                    "VERIFIED"
                    if real_account.get("authenticated")
                    else (
                        "PRESENT"
                        if real_account.get("apiKeyPresent")
                        else "MISSING"
                    )
                ),
                "permission": real_account.get(
                    "permission",
                    "NOT_VERIFIED",
                ),
                "accountType": real_account.get(
                    "accountType",
                    "UNKNOWN",
                ),
                "authReason": real_account.get("authReason"),
                "connectionReason": real_account.get(
                    "connectionReason"
                ),
                "generation": real_account.get("generation"),
            },
        }

    def _flatten_account_runtime_fields(
        self,
        account_runtime,
        live_readiness,
    ):

        real_account = dict(
            account_runtime.get("realAccount") or {}
        )
        account_source = (
            real_account.get("accountSource")
            or "PAPER_SIMULATION"
        )
        balance_source = (
            real_account.get("balanceSource")
            or "PAPER_SIMULATION"
        )
        position_source = (
            real_account.get("positionSource")
            or "PAPER_SIMULATION"
        )
        real_connected = bool(
            real_account.get("authenticated")
            or real_account.get("balanceSource")
            or real_account.get("positionSource")
        )
        api_key_status = (
            "VERIFIED"
            if real_account.get("authenticated")
            else (
                "PRESENT"
                if real_account.get("apiKeyPresent")
                else "MISSING"
            )
        )

        return {
            "accountRuntime": account_runtime,
            "accountSource": account_source,
            "balanceSource": balance_source,
            "positionSource": position_source,
            "accountSourceReason": (
                real_account.get("accountReason")
                or live_readiness.get("accountSourceReason")
            ),
            "balanceSourceReason": (
                real_account.get("balanceReason")
                or live_readiness.get("balanceSourceReason")
            ),
            "positionSourceReason": (
                real_account.get("positionReason")
                or live_readiness.get("positionSourceReason")
            ),
            "exchangeAuth": (
                "VERIFIED"
                if real_account.get("authenticated")
                else "NOT_VERIFIED"
            ),
            "exchangeConnection": (
                "CONNECTED"
                if real_account.get("connected")
                else "NOT_CONNECTED"
            ),
            "apiKeyStatus": api_key_status,
            "permission": real_account.get(
                "permission",
                "NOT_VERIFIED",
            ),
            "accountType": real_account.get(
                "accountType",
                "UNKNOWN",
            ),
            "realAccountConnected": real_connected,
            "realBalance": real_account.get("balance"),
            "realEquity": real_account.get("equity"),
            "realAvailableBalance": real_account.get(
                "availableBalance"
            ),
            "realPosition": self._legacy_real_position_value(
                real_account.get("positions")
            ),
            "realPositionState": real_account.get(
                "positionSummary"
            ),
            "realAccountLastSync": real_account.get("lastSync"),
            "realLastSync": real_account.get("lastSync"),
            "exchangeAuthReason": real_account.get("authReason"),
            "exchangeConnectionReason": real_account.get(
                "connectionReason"
            ),
            "accountReason": real_account.get("accountReason"),
            "balanceReason": real_account.get("balanceReason"),
            "positionReason": real_account.get("positionReason"),
        }

    def _build_live_readiness_snapshot(
        self,
        selected_mode,
        dry_run,
    ):

        if (
            self.engine
            and hasattr(self.engine, "build_live_readiness")
        ):
            readiness = self.engine.build_live_readiness()
        else:
            exchange_client_ready = bool(
                self.exchange_client_ready
            )
            exchange_auth_ready = bool(
                self.exchange_auth_ready
            )
            balance_check_ok = bool(
                self.balance_check_ok
            )
            position_check_ok = bool(
                self.position_check_ok
            )
            execution_enabled = bool(
                governance_state.get(
                    "execution_enabled",
                    False,
                )
            )
            emergency_stop = bool(
                governance_state.get(
                    "emergency_stop",
                    False,
                )
            )

            checks = {
                "selectedModeLive": selected_mode == "LIVE",
                "dryRunDisabled": dry_run is False,
                "allowLive": backend_config.ALLOW_LIVE is True,
                "tradeModeLive": backend_config.TRADE_MODE == "live",
                "exchangeClientReady": exchange_client_ready,
                "exchangeAuthReady": exchange_auth_ready,
                "balanceCheckOk": balance_check_ok,
                "positionCheckOk": position_check_ok,
                "executionEnabled": execution_enabled,
                "emergencyStopClear": not emergency_stop,
            }

            block_reasons = []

            if not checks["selectedModeLive"]:
                block_reasons.append("SELECTED_MODE_NOT_LIVE")
            if not checks["dryRunDisabled"]:
                block_reasons.append("DRY_RUN_ACTIVE")
            if not checks["allowLive"]:
                block_reasons.append("LIVE_NOT_ENABLED")
            if not checks["tradeModeLive"]:
                block_reasons.append("TRADE_MODE_NOT_LIVE")
            if not checks["exchangeAuthReady"]:
                block_reasons.append("KUCOIN_CREDENTIALS_MISSING")
            if not checks["exchangeClientReady"]:
                block_reasons.append("EXCHANGE_CLIENT_NOT_READY")
            if not checks["balanceCheckOk"]:
                block_reasons.append("BALANCE_CHECK_FAILED")
            if not checks["positionCheckOk"]:
                block_reasons.append("POSITION_CHECK_FAILED")
            if not checks["executionEnabled"]:
                block_reasons.append("EXECUTION_DISABLED")
            if not checks["emergencyStopClear"]:
                block_reasons.append("EMERGENCY_STOP_ACTIVE")

            readiness = {
                "ready": not block_reasons,
                "realOrderAllowed": not block_reasons,
                "checks": checks,
                "blockReasons": block_reasons,
                "selectedMode": selected_mode,
                "dryRun": dry_run,
                "tradeMode": backend_config.TRADE_MODE,
                "allowLive": backend_config.ALLOW_LIVE,
                "exchangeClientReady": exchange_client_ready,
                "exchangeAuthReady": exchange_auth_ready,
                "balanceCheckOk": balance_check_ok,
                "positionCheckOk": position_check_ok,
                "executionEnabled": execution_enabled,
                "emergencyStop": emergency_stop,
                "authError": self.exchange_auth_error,
                "realBalance": None,
                "realEquity": None,
                "realAvailableBalance": None,
                "realPosition": None,
                "realPositionState": "NOT_SYNCED",
                "realAccountLastSync": None,
                "exchangeConnection": (
                    "CONNECTED"
                    if exchange_client_ready
                    else "NOT_CONNECTED"
                ),
                "apiKeyStatus": (
                    "VERIFIED"
                    if exchange_auth_ready
                    else "MISSING"
                ),
                "permission": (
                    "READ_ONLY"
                    if exchange_auth_ready
                    else "NOT_VERIFIED"
                ),
                "accountType": (
                    "KUCOIN_FUTURES"
                    if exchange_auth_ready
                    else "UNKNOWN"
                ),
                "exchangeAuthReason": (
                    "KUCOIN_CREDENTIALS_VERIFIED"
                    if exchange_auth_ready
                    else (
                        self.exchange_auth_error
                        or "KUCOIN_CREDENTIALS_MISSING"
                    )
                ),
                "exchangeConnectionReason": (
                    "KUCOIN_CLIENT_READY"
                    if exchange_client_ready
                    else "EXCHANGE_CLIENT_NOT_READY"
                ),
                "accountReason": "KUCOIN_READ_ONLY_NOT_CONNECTED",
                "balanceReason": "BALANCE_NOT_SYNCED",
                "positionReason": "POSITION_NOT_SYNCED",
                "accountSnapshot": {},
            }

        readiness = dict(readiness)
        block_reasons = list(
            readiness.get("blockReasons") or []
        )

        readiness_account_available = (
            readiness.get("realBalance") is not None
            or readiness.get("realEquity") is not None
            or readiness.get("realPosition") is not None
            or readiness.get("balanceCheckOk")
            or readiness.get("positionCheckOk")
        )
        real_account = (
            {}
            if readiness_account_available
            else self._get_real_account_snapshot()
        )

        if (
            not real_account.get("authenticated")
            and (
                readiness.get("realBalance") is not None
                or readiness.get("balanceCheckOk")
                or readiness.get("positionCheckOk")
            )
        ):
            readiness_positions = (
                self._normalize_positions_for_account(
                    readiness.get("realPosition")
                )
                if readiness.get("positionCheckOk")
                else None
            )
            readiness_authenticated = bool(
                readiness.get("exchangeAuthReady")
                or readiness.get("balanceCheckOk")
                or readiness.get("positionCheckOk")
            )
            real_account = {
                "exchange": self._normalize_account_exchange(),
                "accountType": readiness.get(
                    "accountType",
                    "KUCOIN_FUTURES",
                ),
                "connected": bool(
                    readiness.get("exchangeClientReady")
                    or readiness.get("exchangeConnection")
                    == "CONNECTED"
                ),
                "authenticated": readiness_authenticated,
                "apiKeyPresent": readiness_authenticated,
                "permission": readiness.get(
                    "permission",
                    "READ_ONLY"
                    if readiness_authenticated
                    else "NOT_VERIFIED",
                ),
                "balance": readiness.get("realBalance"),
                "equity": readiness.get("realEquity"),
                "availableBalance": readiness.get(
                    "realAvailableBalance"
                ),
                "positions": readiness_positions,
                "positionSummary": (
                    readiness.get("realPositionState")
                    or self._position_summary(readiness_positions)
                ),
                "lastSync": readiness.get("realAccountLastSync"),
                "lastAttempt": readiness.get("realAccountLastSync"),
                "stale": False,
                "loading": False,
                "authReason": readiness.get("exchangeAuthReason"),
                "connectionReason": readiness.get(
                    "exchangeConnectionReason"
                ),
                "accountReason": readiness.get("accountReason"),
                "balanceReason": readiness.get("balanceReason"),
                "positionReason": readiness.get("positionReason"),
                "lastError": None,
                "accountSource": (
                    "KUCOIN_FUTURES_READ_ONLY"
                    if readiness_authenticated
                    else None
                ),
                "balanceSource": (
                    "KUCOIN_FUTURES_READ_ONLY"
                    if readiness.get("balanceCheckOk")
                    else None
                ),
                "positionSource": (
                    "KUCOIN_FUTURES_READ_ONLY"
                    if readiness.get("positionCheckOk")
                    else None
                ),
                "generation": self.account_snapshot_generation,
            }

        read_balance_ok = (
            real_account.get("balanceSource")
            == "KUCOIN_FUTURES_READ_ONLY"
        )
        read_position_ok = (
            real_account.get("positionSource")
            == "KUCOIN_FUTURES_READ_ONLY"
        )
        read_authenticated = bool(
            real_account.get("authenticated")
        )
        account_source = (
            real_account.get("accountSource")
            or "PAPER_SIMULATION"
        )
        balance_source = (
            real_account.get("balanceSource")
            or "PAPER_SIMULATION"
        )
        position_source = (
            real_account.get("positionSource")
            or "PAPER_SIMULATION"
        )

        readiness.update({
            "blockReasons": block_reasons,
            "realAccount": real_account,
            "accountSource": account_source,
            "balanceSource": balance_source,
            "positionSource": position_source,
            "accountSourceReason": real_account.get(
                "accountReason"
            ),
            "balanceSourceReason": real_account.get(
                "balanceReason"
            ),
            "positionSourceReason": real_account.get(
                "positionReason"
            ),
            "balanceCheckOk": bool(
                readiness.get("balanceCheckOk")
                or read_balance_ok
            ),
            "positionCheckOk": bool(
                readiness.get("positionCheckOk")
                or read_position_ok
            ),
            "exchangeAuthReady": bool(
                readiness.get("exchangeAuthReady")
                or read_authenticated
            ),
            "realBalance": real_account.get("balance"),
            "realEquity": real_account.get("equity"),
            "realAvailableBalance": real_account.get(
                "availableBalance"
            ),
            "realPosition": real_account.get("positions"),
            "realPositionState": real_account.get(
                "positionSummary"
            ),
            "realAccountLastSync": real_account.get("lastSync"),
            "exchangeConnection": (
                "CONNECTED"
                if real_account.get("connected")
                else "NOT_CONNECTED"
            ),
            "apiKeyStatus": (
                "VERIFIED"
                if real_account.get("authenticated")
                else (
                    "PRESENT"
                    if real_account.get("apiKeyPresent")
                    else "MISSING"
                )
            ),
            "permission": real_account.get(
                "permission",
                "NOT_VERIFIED",
            ),
            "accountType": real_account.get(
                "accountType",
                "UNKNOWN",
            ),
            "exchangeAuthReason": real_account.get(
                "authReason"
            ),
            "exchangeConnectionReason": real_account.get(
                "connectionReason"
            ),
            "accountReason": real_account.get("accountReason"),
            "balanceReason": real_account.get("balanceReason"),
            "positionReason": real_account.get("positionReason"),
        })

        checks = dict(readiness.get("checks") or {})
        checks.update({
            "exchangeAuthReady": readiness.get(
                "exchangeAuthReady",
                False,
            ),
            "balanceCheckOk": readiness.get(
                "balanceCheckOk",
                False,
            ),
            "positionCheckOk": readiness.get(
                "positionCheckOk",
                False,
            ),
        })
        readiness["checks"] = checks

        return readiness

    def attach_orderbook_runtime_debug(self, runtime_result):

        if not isinstance(runtime_result, dict):
            return runtime_result

        runtime_debug_result = runtime_result.get(
            "runtimeDebug"
        )

        if not isinstance(runtime_debug_result, dict):
            runtime_debug_result = {}
            runtime_result["runtimeDebug"] = runtime_debug_result

        # Calculate safety state variables
        dry_run = bool(
            self.config.get("dry_run", True)
        )
        selected_mode = str(
            self.config.get("mode", "paper")
        ).strip().upper()
        live_readiness = self._build_live_readiness_snapshot(
            selected_mode,
            dry_run,
        )

        real_order_allowed = bool(
            live_readiness.get("realOrderAllowed", False)
        )
        execution_mode = (
            "LIVE"
            if real_order_allowed
            else "SIMULATION"
        )

        safety_reasons = []
        if selected_mode == "LIVE" and not real_order_allowed:
            safety_reasons.append("LIVE_NOT_ENABLED")
        if dry_run:
            safety_reasons.append("DRY_RUN_ACTIVE")
        if not safety_reasons and not real_order_allowed:
            safety_reasons.append("LIVE_NOT_ENABLED")
        safety_reason = " / ".join(safety_reasons) or "NONE"

        engine_config = self._effective_engine_config()

        risk_config = {
            "risk_percent": engine_config.get("risk_percent"),
            "position_size": engine_config.get("position_size"),
            "max_drawdown_pct": engine_config.get(
                "max_drawdown_pct"
            ),
            "tp_percent": engine_config.get("tp_percent"),
            "sl_percent": engine_config.get("sl_percent"),
            "trailing_stop": engine_config.get("trailing_stop"),
            "trailing_stop_distance_percent": engine_config.get(
                "trailing_stop_distance_percent"
            ),
        }

        risk_state = (
            self.engine.get_risk_state()
            if self.engine
            and hasattr(self.engine, "get_risk_state")
            else {}
        )

        trade_settings = self._build_trade_settings_snapshot(
            engine_config,
            selected_mode,
            dry_run,
            execution_mode,
            real_order_allowed,
        )
        account_snapshot = self._capture_account_snapshot()
        account_runtime = self._build_account_runtime(
            account_snapshot,
            live_readiness,
            selected_mode,
            dry_run,
            execution_mode,
            real_order_allowed,
        )
        account_status_fields = (
            self._flatten_account_runtime_fields(
                account_runtime,
                live_readiness,
            )
        )

        runtime_debug_result.update({
            "symbol": (
                self.symbol
                or self.config.get("symbol")
            ),
            "exchange": self.exchange_name,
            "orderbookSource": self.orderbook_source,
            "orderbookSymbol": self.orderbook_symbol,
            "allowLive": backend_config.ALLOW_LIVE,
            "tradeMode": backend_config.TRADE_MODE,
            "dryRun": dry_run,
            "realOrderAllowed": real_order_allowed,
            "selectedMode": selected_mode,
            "executionMode": execution_mode,
            "safetyReason": safety_reason,
            "liveReadiness": live_readiness,
            "liveBlockReasons": live_readiness.get(
                "blockReasons",
                [],
            ),
            "exchangeClientReady": live_readiness.get(
                "exchangeClientReady",
                False,
            ),
            "exchangeAuthReady": live_readiness.get(
                "exchangeAuthReady",
                False,
            ),
            "balanceCheckOk": live_readiness.get(
                "balanceCheckOk",
                False,
            ),
            "positionCheckOk": live_readiness.get(
                "positionCheckOk",
                False,
            ),
            "executionEnabled": live_readiness.get(
                "executionEnabled",
                False,
            ),
            "emergencyStop": live_readiness.get(
                "emergencyStop",
                False,
            ),
            "accountSource": live_readiness.get(
                "accountSource",
                "PAPER_SIMULATION",
            ),
            "balanceSource": live_readiness.get(
                "balanceSource",
                "PAPER_SIMULATION",
            ),
            "positionSource": live_readiness.get(
                "positionSource",
                "PAPER_SIMULATION",
            ),
            "accountSourceReason": live_readiness.get(
                "accountSourceReason"
            ),
            "balanceSourceReason": live_readiness.get(
                "balanceSourceReason"
            ),
            "positionSourceReason": live_readiness.get(
                "positionSourceReason"
            ),
            "balance": account_snapshot.get("balance"),
            "equity": account_snapshot.get("equity"),
            "availableBalance": account_snapshot.get(
                "availableBalance",
                account_snapshot.get("balance"),
            ),
            "pnl": account_snapshot.get("pnl"),
            "position": account_snapshot.get("position"),
            "exchangeAuth": (
                "VERIFIED"
                if live_readiness.get("exchangeAuthReady")
                else "NOT_VERIFIED"
            ),
            "exchangeConnection": live_readiness.get(
                "exchangeConnection",
                "NOT_CONNECTED",
            ),
            "apiKeyStatus": live_readiness.get(
                "apiKeyStatus",
                "MISSING",
            ),
            "permission": live_readiness.get(
                "permission",
                "NOT_VERIFIED",
            ),
            "accountType": live_readiness.get(
                "accountType",
                "UNKNOWN",
            ),
            "realAccountConnected": bool(
                live_readiness.get("balanceCheckOk")
                or live_readiness.get("positionCheckOk")
            ),
            "realBalance": live_readiness.get("realBalance"),
            "realEquity": live_readiness.get("realEquity"),
            "realAvailableBalance": live_readiness.get(
                "realAvailableBalance"
            ),
            "realPosition": live_readiness.get("realPosition"),
            "realPositionState": live_readiness.get(
                "realPositionState"
            ),
            "realAccountLastSync": live_readiness.get(
                "realAccountLastSync"
            ),
            "realLastSync": live_readiness.get(
                "realAccountLastSync"
            ),
            "exchangeAuthReason": live_readiness.get(
                "exchangeAuthReason"
            ),
            "exchangeConnectionReason": live_readiness.get(
                "exchangeConnectionReason"
            ),
            "accountReason": live_readiness.get("accountReason"),
            "balanceReason": live_readiness.get("balanceReason"),
            "positionReason": live_readiness.get("positionReason"),
            "trade_settings": trade_settings,
            "tradeSettings": trade_settings,
            "riskConfig": risk_config,
            "riskState": risk_state,
        })
        runtime_debug_result.update(account_status_fields)

        return runtime_result

    # ============================================
    # START
    # ============================================

    def _set_lifecycle_state(self, state):

        if self.lifecycle_state == state:

            return

        self.lifecycle_state = state

        self.lifecycle_revision += 1

        self.lifecycle_changed_at = time.time()

    def start(self, config):

        try:
            requested_mode = str(
                config.get("mode", "")
            ).strip().lower()
            requested_dry_run = config.get("dry_run", True)

            if requested_mode == "paper":
                pending_authority = (
                    self.get_authoritative_pending_order_state()
                )
                if self.engine is not None:
                    from backend.routers import positions as positions_router

                    trading_runtime = runtime_registry.trading_runtime
                    execution_runtime = (
                        getattr(trading_runtime, "execution_runtime", None)
                        if trading_runtime is not None
                        else None
                    )
                    if positions_router.engine is not self.engine:
                        return {
                            "status": "error",
                            "reason": "POSITIONS_REGISTRY_MISMATCH",
                            "success": False,
                            "completed": False,
                            "stateUnknown": True,
                        }
                    if (
                        execution_runtime is None
                        or getattr(execution_runtime, "engine", None)
                        is not self.engine
                    ):
                        return {
                            "status": "error",
                            "reason": "EXECUTION_REGISTRY_MISMATCH",
                            "success": False,
                            "completed": False,
                            "stateUnknown": True,
                        }
                durable_start_safe = False
                if (
                    pending_authority.get("safe") is not True
                    and os.path.lexists(
                        self.stopped_paper_durable_snapshot_path
                    )
                ):
                    durable_snapshot, _durable_reason = (
                        self._load_stopped_paper_durable_snapshot()
                    )
                    durable_start_safe = bool(
                        isinstance(durable_snapshot, dict)
                        and durable_snapshot.get("mode") == "paper"
                        and durable_snapshot.get("lifecycleState")
                        == "STOPPED"
                        and durable_snapshot.get("stateUnknown") is False
                        and durable_snapshot.get("positionRemaining")
                        is False
                        and durable_snapshot.get("pendingOrder") is False
                        and durable_snapshot.get("openOrderCount") == 0
                        and type(
                            durable_snapshot.get("openOrderCount")
                        ) is int
                    )
                if (
                    requested_dry_run is not True
                    or (
                        durable_start_safe is not True
                        and (
                            pending_authority.get("known") is not True
                            or pending_authority.get("pending") is not False
                            or pending_authority.get("safe") is not True
                        )
                    )
                ):
                    reason = (
                        "PAPER_DRY_RUN_REQUIRED"
                        if requested_dry_run is not True
                        else pending_authority.get("reason")
                        or "PENDING_ORDER_AUTHORITY_REQUIRED"
                    )
                    return {
                        "status": "error",
                        "reason": reason,
                        "success": False,
                        "completed": False,
                        "stateUnknown": (
                            pending_authority.get("known") is not True
                        ),
                    }

        except Exception as e:
            return {
                "status": "error",
                "reason": str(e),
                "success": False,
                "completed": False,
                "stateUnknown": True,
            }

        try:

            stop_result = self.stop()
            if (
                not isinstance(stop_result, dict)
                or stop_result.get("status") != "stopped"
                or stop_result.get("success") is not True
                or stop_result.get("completed") is not True
                or stop_result.get("stateUnknown") is not False
            ):
                return {
                    "status": "error",
                    "reason": (
                        stop_result.get("reason")
                        if isinstance(stop_result, dict)
                        else "ENGINE_STOP_RESULT_INVALID"
                    ),
                    "success": False,
                    "completed": False,
                    "stateUnknown": True,
                }

            self._set_lifecycle_state(
                "STARTING"
            )

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

            self.exchange_client_ready = False

            self.exchange_auth_ready = False

            self.exchange_auth_error = None

            self.balance_check_ok = False

            self.position_check_ok = False

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

            self._prepare_real_account_snapshot_for_exchange(
                self.exchange_name,
                loading=True,
            )

            self.config = dict(config)

            self.config["exchange"] = self.exchange_name

            config = self.config

            invalidated = self._invalidate_stopped_paper_durable_snapshot(
                "BOT_START"
            )
            if invalidated is not True:
                raise RuntimeError(
                    "STOPPED_PAPER_SNAPSHOT_INVALIDATION_FAILED"
                )

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

                if KucoinTradeClient.credentials_present():

                    self.exchange_auth_ready = True

                    try:

                        exchange = KucoinTradeClient()

                        self.exchange_client_ready = True

                    except Exception as e:

                        self.exchange_auth_ready = False
                        self.exchange_auth_error = str(e)
                        self.exchange_client_ready = False

                        logger.warning(
                            "KuCoin client init failed: %s",
                            e,
                        )

                else:

                    self.exchange_auth_ready = False
                    self.exchange_auth_error = (
                        "KUCOIN_CREDENTIALS_MISSING"
                    )

                    logger.warning(
                        "KuCoin credentials missing; live orders disabled"
                    )

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

            self.balance_check_ok = bool(
                getattr(
                    self.engine,
                    "balance_check_ok",
                    False,
                )
            )

            self.position_check_ok = bool(
                getattr(
                    self.engine,
                    "position_check_ok",
                    False,
                )
            )

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

            self._set_lifecycle_state(
                "RUNNING"
            )

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

            cleanup_result = self.stop()
            cleanup_succeeded = bool(
                isinstance(cleanup_result, dict)
                and cleanup_result.get("status") == "stopped"
                and cleanup_result.get("success") is True
                and cleanup_result.get("completed") is True
                and cleanup_result.get("stateUnknown") is False
            )

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
                "success": False,
                "completed": False,
                "stateUnknown": cleanup_succeeded is not True,
            }

    def shutdown(self):

        """Persist stopped-paper authority before process teardown."""

        with self.shutdown_lock:
            engine = self.engine
            if engine is not None:
                mode = self._normalize_emergency_mode(
                    getattr(engine, "mode", None)
                )
                if mode != "paper":
                    add_log("SHUTDOWN_SNAPSHOT_NOT_AVAILABLE: LIVE_MODE")

                # stop() persists paper authority before clearing self.engine.
                return self.stop()

            snapshot = self.account_snapshot
            authority = self._stopped_paper_shutdown_evidence_state(
                snapshot
            )
            if authority.get("valid") is not True:
                reason = authority.get("reason") or "STATE_UNKNOWN"
                self.account_snapshot = (
                    self._stopped_paper_unknown_snapshot(
                        snapshot,
                        reason,
                    )
                )
                add_log(
                    f"SHUTDOWN_SNAPSHOT_NOT_AVAILABLE: {reason}"
                )
                return {
                    "success": True,
                    "persisted": False,
                    "reason": reason,
                }

            persisted, reason = (
                self._persist_stopped_paper_durable_snapshot(snapshot)
            )
            if persisted is not True:
                failure_reason = reason or "SNAPSHOT_PERSIST_FAILED"
                if failure_reason in {
                    "SNAPSHOT_GENERATION_OLDER",
                    "SNAPSHOT_TIMESTAMP_OLDER",
                }:
                    add_log(
                        "SHUTDOWN_SNAPSHOT_NOT_AVAILABLE: "
                        f"{failure_reason}"
                    )
                    return {
                        "success": True,
                        "persisted": False,
                        "reason": failure_reason,
                    }
                logger.error(
                    "SNAPSHOT_PERSIST_FAILED during shutdown: %s",
                    failure_reason,
                )
                self.account_snapshot = (
                    self._stopped_paper_unknown_snapshot(
                        snapshot,
                        "SNAPSHOT_PERSIST_FAILED",
                    )
                )
                return {
                    "success": True,
                    "persisted": False,
                    "reason": failure_reason,
                }

            return {
                "success": True,
                "persisted": True,
                "reason": None,
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
            actual_position = deepcopy(
                getattr(self.engine, "actual_position", None)
            )
            positions = (
                []
                if actual_position is None
                else [deepcopy(actual_position)]
            )

            self.account_snapshot = {
                "balance": balance,
                "equity": balance + unrealized_pnl,
                "availableBalance": balance,
                "pnl": realized_pnl + unrealized_pnl,
                "position": actual_position,
                "positions": positions,
                "realizedPnl": realized_pnl,
                "unrealizedPnl": unrealized_pnl,
                "last_update": time.time(),
                "available": True,
            }

        except Exception as e:

            logger.error(
                f"❌ ACCOUNT SNAPSHOT ERROR: {e}"
            )

        return self.account_snapshot

    def _emergency_response(
        self,
        success=False,
        completed=False,
        partial=False,
        state_unknown=False,
        execution_path=None,
        symbol=None,
        cancel=None,
        flatten=None,
        position_remaining=None,
        retryable=True,
        error_code=None,
    ):

        return {
            "success": success,
            "completed": completed,
            "partial": partial,
            "state_unknown": state_unknown,
            "emergency_locked": bool(
                governance_state.get(
                    "emergency_stop",
                    False,
                )
            ),
            "auto_trade_disabled": not bool(
                governance_state.get(
                    "execution_enabled",
                    False,
                )
            ),
            "execution_path": execution_path,
            "path": execution_path,
            "symbol": symbol,
            "cancel": cancel,
            "flatten": flatten,
            "position_remaining": position_remaining,
            "retryable": retryable,
            "error_code": error_code,
        }

    @staticmethod
    def _emergency_not_required_result(kind):

        result = {
            "success": True,
            "completed": True,
            "status": "NOT_REQUIRED",
            "skipped": True,
            "not_required": True,
            "reason": "NOT_REQUIRED",
        }

        if kind == "cancel":
            result.update({
                "requested": 0,
                "cancelled": 0,
                "failed": 0,
            })

        if kind == "flatten":
            result.update({
                "closed": True,
                "position_closed": True,
            })

        return result

    @classmethod
    def _emergency_position_value_present(cls, value):

        if value is None:
            return False

        if isinstance(value, list):
            return any(
                cls._emergency_position_value_present(item)
                for item in value
            )

        if isinstance(value, dict):
            return bool(value)

        if isinstance(value, str):
            return value.strip().upper() not in {
                "",
                "NONE",
                "NO_OPEN_POSITION",
                "FLAT",
            }

        return bool(value)

    def _stopped_paper_unknown_response(
        self,
        symbol,
        error_code,
        execution_path="paper",
    ):

        return self._emergency_response(
            success=False,
            completed=False,
            partial=True,
            state_unknown=True,
            execution_path=execution_path,
            symbol=symbol,
            cancel=None,
            flatten=None,
            position_remaining=None,
            retryable=True,
            error_code=error_code,
        )

    @classmethod
    def _stopped_paper_position_state(cls, snapshot):

        if not isinstance(snapshot, dict):
            return "unknown"

        if (
            "position" not in snapshot
            or "positions" not in snapshot
        ):
            return "unknown"

        position = snapshot.get("position")
        positions = snapshot.get("positions")

        if not isinstance(positions, list):
            return "unknown"

        if position is not None:
            if cls._emergency_position_value_present(position):
                return "remaining"
            return "unknown"

        if not positions:
            return "flat"

        for item in positions:
            if cls._emergency_position_value_present(item):
                return "remaining"
            return "unknown"

        return "unknown"

    @staticmethod
    def _stopped_paper_open_order_state(snapshot):

        missing = object()
        source = missing
        open_order_count = missing

        if isinstance(snapshot, dict):
            source = snapshot.get("openOrderStateSource", missing)
            open_order_count = snapshot.get("openOrderCount", missing)

        allowed_sources = BotManager._stopped_paper_open_order_sources()

        if source is missing or source not in allowed_sources:
            return {
                "state": "unknown",
                "count": None,
                "source": (
                    source
                    if isinstance(source, str)
                    else "unknown"
                ),
                "reason": "OPEN_ORDER_UNKNOWN",
            }

        if open_order_count is not missing:
            if (
                type(open_order_count) is not int
                or open_order_count < 0
            ):
                return {
                    "state": "unknown",
                    "count": None,
                    "source": source,
                    "reason": "OPEN_ORDER_UNKNOWN",
                }

            no_collection_source = (
                "execution_engine."
                "paper_immediate_fill_no_open_order_collection"
            )
            if (
                source == no_collection_source
                and open_order_count != 0
            ):
                return {
                    "state": "unknown",
                    "count": None,
                    "source": source,
                    "reason": "OPEN_ORDER_SOURCE_MISMATCH",
                }

            if open_order_count > 0:
                return {
                    "state": "remaining",
                    "count": open_order_count,
                    "source": source,
                    "reason": "OPEN_ORDER_REMAINING",
                }

            return {
                "state": "flat",
                "count": 0,
                "source": source,
                "reason": "NO_OPEN_ORDER",
            }

        return {
            "state": "unknown",
            "count": None,
            "source": "unknown",
            "reason": "OPEN_ORDER_UNKNOWN",
        }

    @staticmethod
    def _stopped_paper_engine_pending_order_state(engine):

        missing = object()

        try:
            pending_order = getattr(engine, "pending_order", missing)
        except Exception:
            return {
                "state": "unknown",
                "pending_order": None,
                "source": "execution_engine.pending_order_duplicate_lock",
                "reason": "PENDING_ORDER_READ_FAILED",
            }

        if type(pending_order) is not bool:
            return {
                "state": "unknown",
                "pending_order": None,
                "source": "execution_engine.pending_order_duplicate_lock",
                "reason": "PENDING_ORDER_UNKNOWN",
            }

        if pending_order is True:
            return {
                "state": "remaining",
                "pending_order": True,
                "source": "execution_engine.pending_order_duplicate_lock",
                "reason": "PENDING_ORDER_REMAINING",
            }

        return {
            "state": "flat",
            "pending_order": False,
            "source": "execution_engine.pending_order_duplicate_lock",
            "reason": "NO_PENDING_ORDER",
        }

    @classmethod
    def _stopped_paper_engine_position_state(cls, engine):

        missing = object()
        sources = []

        try:
            actual_position = getattr(engine, "actual_position", missing)
        except Exception:
            actual_position = missing

        if actual_position is not missing:
            if actual_position is None:
                sources.append({
                    "state": "flat",
                    "source": "execution_engine.actual_position",
                    "position": None,
                })
            elif (
                isinstance(actual_position, dict)
                and cls._emergency_position_value_present(actual_position)
            ):
                sources.append({
                    "state": "remaining",
                    "source": "execution_engine.actual_position",
                    "position": deepcopy(actual_position),
                })
            else:
                sources.append({
                    "state": "unknown",
                    "source": "execution_engine.actual_position",
                    "reason": "POSITION_MALFORMED",
                })

        portfolio_positions = missing
        try:
            portfolio = getattr(engine, "portfolio", None)
            if (
                portfolio is not None
                and hasattr(portfolio, "positions")
            ):
                if hasattr(portfolio, "lock"):
                    with portfolio.lock:
                        portfolio_positions = deepcopy(
                            portfolio.positions
                        )
                else:
                    portfolio_positions = deepcopy(portfolio.positions)
        except Exception:
            portfolio_positions = missing

        if portfolio_positions is not missing:
            if not isinstance(portfolio_positions, dict):
                sources.append({
                    "state": "unknown",
                    "source": "portfolio.positions",
                    "reason": "POSITION_MALFORMED",
                })
            elif not portfolio_positions:
                sources.append({
                    "state": "flat",
                    "source": "portfolio.positions",
                    "positions": {},
                })
            elif any(
                isinstance(item, dict)
                and cls._emergency_position_value_present(item)
                for item in portfolio_positions.values()
            ):
                sources.append({
                    "state": "remaining",
                    "source": "portfolio.positions",
                    "positions": deepcopy(portfolio_positions),
                })
            else:
                sources.append({
                    "state": "unknown",
                    "source": "portfolio.positions",
                    "reason": "POSITION_MALFORMED",
                })

        if not sources:
            return {
                "state": "unknown",
                "source": None,
                "reason": "POSITION_SOURCE_UNAVAILABLE",
                "position": None,
                "positions": None,
            }

        if any(item["state"] == "unknown" for item in sources):
            unknown_source = next(
                item for item in sources if item["state"] == "unknown"
            )
            return {
                "state": "unknown",
                "source": unknown_source.get("source"),
                "reason": unknown_source.get("reason")
                or "POSITION_STATE_UNKNOWN",
                "position": None,
                "positions": None,
            }

        states = {item["state"] for item in sources}
        if states == {"flat", "remaining"}:
            return {
                "state": "unknown",
                "source": "+".join(item["source"] for item in sources),
                "reason": "POSITION_SOURCE_MISMATCH",
                "position": None,
                "positions": None,
            }

        if "remaining" in states:
            position = next(
                (
                    item.get("position")
                    for item in sources
                    if item.get("position") is not None
                ),
                None,
            )
            positions = next(
                (
                    item.get("positions")
                    for item in sources
                    if item.get("positions") is not None
                ),
                None,
            )
            return {
                "state": "remaining",
                "source": "+".join(item["source"] for item in sources),
                "reason": "POSITION_REMAINING",
                "position": position,
                "positions": positions,
            }

        return {
            "state": "flat",
            "source": "+".join(item["source"] for item in sources),
            "reason": "NO_POSITION",
            "position": None,
            "positions": {},
        }

    @staticmethod
    def _stopped_paper_engine_open_order_state(engine):

        missing = object()

        for attr in ("open_orders", "open_order", "orders"):
            try:
                value = getattr(engine, attr, missing)
            except Exception:
                return {
                    "state": "unknown",
                    "count": None,
                    "source": f"execution_engine.{attr}",
                    "reason": "OPEN_ORDER_UNKNOWN",
                }
            if value is missing:
                continue
            if isinstance(value, dict):
                count = len(value)
            elif isinstance(value, list):
                count = len(value)
            else:
                return {
                    "state": "unknown",
                    "count": None,
                    "source": f"execution_engine.{attr}",
                    "reason": "OPEN_ORDER_MALFORMED",
                }
            return {
                "state": "remaining" if count > 0 else "flat",
                "count": count,
                "source": f"execution_engine.{attr}",
                "reason": (
                    "OPEN_ORDER_REMAINING"
                    if count > 0
                    else "NO_OPEN_ORDER"
                ),
            }

        try:
            engine_is_immediate_fill = isinstance(engine, ExecutionEngine)
        except Exception:
            engine_is_immediate_fill = False

        if engine_is_immediate_fill:
            for attr in ("open_orders", "open_order", "orders"):
                if getattr(type(engine), attr, missing) is not missing:
                    return {
                        "state": "unknown",
                        "count": None,
                        "source": f"execution_engine.{attr}",
                        "reason": "OPEN_ORDER_UNKNOWN",
                    }

            return {
                "state": "flat",
                "count": 0,
                "source": (
                    "execution_engine."
                    "paper_immediate_fill_no_open_order_collection"
                ),
                "reason": "NO_OPEN_ORDER",
            }

        return {
            "state": "unknown",
            "count": None,
            "source": "unknown",
            "reason": "OPEN_ORDER_UNKNOWN",
        }

    @staticmethod
    def _normalize_emergency_mode(value):

        if type(value) is not str:
            return None

        normalized = value.strip().lower()

        if normalized in {"paper", "live"}:
            return normalized

        return None

    def _stopped_paper_mode_resolution(self, snapshot=None):

        candidates = []
        current_candidates = []
        snapshot_candidates = []

        def candidate(source, value):
            return {
                "source": source,
                "value": value,
                "normalized": self._normalize_emergency_mode(value),
            }

        def add_current_candidate(source, value):
            item = candidate(source, value)
            candidates.append(item)
            current_candidates.append(item)

        def add_snapshot_candidate(source, value):
            item = candidate(source, value)
            candidates.append(item)
            snapshot_candidates.append(item)

        if not isinstance(self.config, dict):
            return {
                "mode": None,
                "source": None,
                "reason": "MODE_UNKNOWN",
                "candidates": [{
                    "source": "manager_config",
                    "value": type(self.config).__name__,
                    "normalized": None,
                }],
            }

        if "mode" in self.config:
            add_current_candidate(
                "manager_config.mode",
                self.config.get("mode"),
            )

        if "mode" in governance_state:
            add_current_candidate(
                "governance_state.mode",
                governance_state.get("mode"),
            )

        invalid_current_candidates = [
            candidate
            for candidate in current_candidates
            if candidate["normalized"] is None
        ]

        if invalid_current_candidates:
            return {
                "mode": None,
                "source": None,
                "reason": "MODE_UNKNOWN",
                "candidates": candidates,
            }

        valid_current_candidates = [
            candidate
            for candidate in current_candidates
            if candidate["normalized"] is not None
        ]
        current_modes = {
            candidate["normalized"]
            for candidate in valid_current_candidates
        }

        if len(current_modes) > 1:
            return {
                "mode": None,
                "source": None,
                "reason": "MODE_CONFLICT",
                "candidates": candidates,
            }

        if not valid_current_candidates:
            return {
                "mode": None,
                "source": None,
                "reason": "MODE_UNKNOWN",
                "candidates": candidates,
            }

        selected = valid_current_candidates[0]

        if selected["normalized"] == "live":
            return {
                "mode": "live",
                "source": selected["source"],
                "reason": None,
                "candidates": candidates,
            }

        if isinstance(snapshot, dict):
            for key in ("tradeMode", "mode", "selectedMode"):
                if key in snapshot:
                    add_snapshot_candidate(
                        f"account_snapshot.{key}",
                        snapshot.get(key),
                    )

        invalid_candidates = [
            candidate
            for candidate in snapshot_candidates
            if candidate["normalized"] is None
        ]

        if invalid_candidates:
            return {
                "mode": None,
                "source": None,
                "reason": "MODE_UNKNOWN",
                "candidates": candidates,
            }

        valid_candidates = (
            valid_current_candidates
            + [
                candidate
                for candidate in snapshot_candidates
                if candidate["normalized"] is not None
            ]
        )
        modes = {
            candidate["normalized"]
            for candidate in valid_candidates
        }

        if len(modes) > 1:
            return {
                "mode": None,
                "source": None,
                "reason": "MODE_CONFLICT",
                "candidates": candidates,
            }

        return {
            "mode": selected["normalized"],
            "source": selected["source"],
            "reason": None,
            "candidates": candidates,
        }

    @staticmethod
    def _project_root():

        return os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "..",
            )
        )

    @classmethod
    def _default_stopped_paper_durable_snapshot_path(cls):

        return os.path.join(
            cls._project_root(),
            "logs",
            "runtime",
            "stopped_paper_safety_snapshot.json",
        )

    @staticmethod
    def _stopped_paper_durable_schema_version():

        return 1

    @staticmethod
    def _stopped_paper_durable_snapshot_type():

        return "stopped_paper_authoritative_safety"

    @staticmethod
    def _stopped_paper_durable_invalid_snapshot_type():

        return "stopped_paper_authoritative_safety_invalidated"

    @staticmethod
    def _finite_positive_number(value):

        return (
            type(value) in {int, float}
            and math.isfinite(value)
            and value > 0
        )

    @staticmethod
    def _non_negative_int(value):

        return (
            type(value) is int
            and value >= 0
        )

    @staticmethod
    def _non_empty_string(value):

        return (
            type(value) is str
            and bool(value.strip())
        )

    def _stopped_paper_durable_pending_source(self, snapshot):

        if not isinstance(snapshot, dict):
            return None

        return (
            snapshot.get("pendingStateSource")
            or snapshot.get("pendingOrderStateSource")
        )

    def _stopped_paper_durable_snapshot_payload(
        self,
        snapshot,
        written_at=None,
    ):

        if not isinstance(snapshot, dict):
            return None

        if written_at is None:
            written_at = time.time()

        pending_source = self._stopped_paper_durable_pending_source(
            snapshot
        )

        source = snapshot.get("source")
        is_preserved = source == "stopped_paper_preserved_runtime_state"
        evidence_source = snapshot.get("evidenceSource")
        evidence_generation = snapshot.get("evidenceGeneration")
        evidence_runtime_id = snapshot.get("evidenceRuntimeInstanceId")
        evidence_captured_at = snapshot.get("evidenceCapturedAt")

        if not is_preserved:
            evidence_source = source
            evidence_generation = snapshot.get("generation")
            evidence_runtime_id = snapshot.get("runtimeInstanceId")
            evidence_captured_at = snapshot.get("capturedAt")

        payload = {
            "schemaVersion": (
                self._stopped_paper_durable_schema_version()
            ),
            "snapshotType": (
                self._stopped_paper_durable_snapshot_type()
            ),
            "capturedAt": evidence_captured_at,
            "timestampEpoch": evidence_captured_at,
            "source": evidence_source,
            "tradeMode": snapshot.get("tradeMode"),
            "mode": snapshot.get("mode"),
            "selectedMode": snapshot.get("selectedMode"),
            "lifecycleState": snapshot.get("lifecycleState"),
            "position": deepcopy(snapshot.get("position")),
            "positions": deepcopy(snapshot.get("positions")),
            "positionRemaining": snapshot.get("positionRemaining"),
            "pendingOrder": snapshot.get("pendingOrder"),
            "pending_order": snapshot.get("pendingOrder"),
            "openOrderCount": snapshot.get("openOrderCount"),
            "stateUnknown": snapshot.get("stateUnknown"),
            "positionStateSource": snapshot.get("positionStateSource"),
            "pendingStateSource": pending_source,
            "pendingOrderStateSource": pending_source,
            "openOrderStateSource": snapshot.get("openOrderStateSource"),
            "generation": evidence_generation,
            "evidenceGeneration": evidence_generation,
            "evidenceCapturedAt": evidence_captured_at,
            "evidenceSource": evidence_source,
            "evidenceOperationId": snapshot.get("operationId"),
            "runtimeInstanceId": evidence_runtime_id,
            "evidenceRuntimeInstanceId": evidence_runtime_id,
            "writtenAt": written_at,
            "authorityReason": snapshot.get("authorityReason"),
        }

        return payload

    def _validate_stopped_paper_durable_snapshot(
        self,
        snapshot,
        allow_current_runtime=False,
    ):

        if not isinstance(snapshot, dict):
            return {
                "valid": False,
                "reason": "DURABLE_SNAPSHOT_UNAVAILABLE",
            }

        if (
            snapshot.get("snapshotType")
            == self._stopped_paper_durable_invalid_snapshot_type()
        ):
            return {
                "valid": False,
                "reason": "DURABLE_SNAPSHOT_INVALIDATED",
            }

        if (
            snapshot.get("schemaVersion")
            != self._stopped_paper_durable_schema_version()
        ):
            return {
                "valid": False,
                "reason": "DURABLE_SNAPSHOT_SCHEMA_UNSUPPORTED",
            }

        if (
            snapshot.get("snapshotType")
            != self._stopped_paper_durable_snapshot_type()
        ):
            return {
                "valid": False,
                "reason": "DURABLE_SNAPSHOT_TYPE_INVALID",
            }

        for field in (
            "capturedAt",
            "timestampEpoch",
            "source",
            "tradeMode",
            "mode",
            "selectedMode",
            "lifecycleState",
            "positionRemaining",
            "pendingOrder",
            "openOrderCount",
            "stateUnknown",
            "positionStateSource",
            "pendingStateSource",
            "openOrderStateSource",
            "generation",
            "evidenceGeneration",
            "runtimeInstanceId",
            "evidenceRuntimeInstanceId",
            "writtenAt",
        ):
            if field not in snapshot:
                return {
                    "valid": False,
                    "reason": "DURABLE_SNAPSHOT_FIELD_MISSING",
                    "field": field,
                }

        if snapshot.get("source") not in (
            self._stopped_paper_base_snapshot_sources()
        ):
            return {
                "valid": False,
                "reason": "SNAPSHOT_SOURCE_UNKNOWN",
                "source": snapshot.get("source"),
            }

        for key in ("tradeMode", "mode", "selectedMode"):
            if self._normalize_emergency_mode(snapshot.get(key)) != "paper":
                return {
                    "valid": False,
                    "reason": "MODE_UNKNOWN",
                    "field": key,
                }

        if snapshot.get("lifecycleState") != "STOPPED":
            return {
                "valid": False,
                "reason": "DURABLE_SNAPSHOT_LIFECYCLE_MISMATCH",
            }

        if snapshot.get("stateUnknown") is not False:
            return {
                "valid": False,
                "reason": (
                    snapshot.get("authorityReason")
                    or "STATE_UNKNOWN"
                ),
            }

        position_remaining = snapshot.get("positionRemaining")
        if type(position_remaining) is not bool:
            return {
                "valid": False,
                "reason": "POSITION_STATE_UNKNOWN",
            }

        pending_order = snapshot.get("pendingOrder")
        if type(pending_order) is not bool:
            return {
                "valid": False,
                "reason": "PENDING_ORDER_UNKNOWN",
            }

        open_order_count = snapshot.get("openOrderCount")
        if not self._non_negative_int(open_order_count):
            return {
                "valid": False,
                "reason": "OPEN_ORDER_UNKNOWN",
            }

        position_source = snapshot.get("positionStateSource")
        if position_source not in self._stopped_paper_position_sources():
            return {
                "valid": False,
                "reason": "POSITION_STATE_UNKNOWN",
                "position_state_source": position_source,
            }

        pending_source = self._stopped_paper_durable_pending_source(
            snapshot
        )
        if pending_source not in self._stopped_paper_pending_order_sources():
            return {
                "valid": False,
                "reason": "PENDING_ORDER_UNKNOWN",
                "pending_order_state_source": pending_source,
            }

        open_order_source = snapshot.get("openOrderStateSource")
        if open_order_source not in self._stopped_paper_open_order_sources():
            return {
                "valid": False,
                "reason": "OPEN_ORDER_UNKNOWN",
                "open_order_state_source": open_order_source,
            }

        expected_source = (
            self._stopped_paper_snapshot_source_for_authority_sources(
                position_source,
                open_order_source,
            )
        )
        if snapshot.get("source") != expected_source:
            return {
                "valid": False,
                "reason": "SNAPSHOT_SOURCE_MISMATCH",
                "source": snapshot.get("source"),
                "expectedSource": expected_source,
            }

        if (
            open_order_source
            == (
                "execution_engine."
                "paper_immediate_fill_no_open_order_collection"
            )
            and open_order_count != 0
        ):
            return {
                "valid": False,
                "reason": "OPEN_ORDER_SOURCE_MISMATCH",
            }

        positions = snapshot.get("positions")
        if not isinstance(positions, list):
            return {
                "valid": False,
                "reason": "POSITION_STATE_UNKNOWN",
            }

        snapshot_position_state = self._stopped_paper_position_state(
            snapshot
        )
        if position_remaining:
            if snapshot_position_state != "remaining":
                return {
                    "valid": False,
                    "reason": "POSITION_STATE_UNKNOWN",
                }
        elif snapshot_position_state != "flat":
            return {
                "valid": False,
                "reason": "POSITION_STATE_UNKNOWN",
            }

        for field in ("capturedAt", "timestampEpoch", "writtenAt"):
            if not self._finite_positive_number(snapshot.get(field)):
                return {
                    "valid": False,
                    "reason": "SNAPSHOT_TIMESTAMP_INVALID",
                    "field": field,
                }

        if not self._non_negative_int(snapshot.get("generation")):
            return {
                "valid": False,
                "reason": "SNAPSHOT_GENERATION_MISMATCH",
            }

        if not self._non_negative_int(snapshot.get("evidenceGeneration")):
            return {
                "valid": False,
                "reason": "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
            }

        if snapshot.get("evidenceGeneration") != snapshot.get("generation"):
            return {
                "valid": False,
                "reason": "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
            }

        if not self._non_empty_string(snapshot.get("runtimeInstanceId")):
            return {
                "valid": False,
                "reason": "DURABLE_RUNTIME_INSTANCE_UNKNOWN",
            }

        if not self._non_empty_string(
            snapshot.get("evidenceRuntimeInstanceId")
        ):
            return {
                "valid": False,
                "reason": "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
            }

        if (
            snapshot.get("evidenceRuntimeInstanceId")
            != snapshot.get("runtimeInstanceId")
        ):
            return {
                "valid": False,
                "reason": "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
            }

        if (
            allow_current_runtime is not True
            and
            snapshot.get("runtimeInstanceId")
            == self.runtime_instance_id
        ):
            return {
                "valid": False,
                "reason": "DURABLE_RUNTIME_INSTANCE_CURRENT",
            }

        try:
            now = time.time()
        except Exception:
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIME_UNAVAILABLE",
            }

        if not self._finite_positive_number(now):
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIME_UNAVAILABLE",
            }

        age = now - snapshot.get("capturedAt")
        if age < 0:
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIMESTAMP_FUTURE",
                "age": age,
            }

        if age > self.stopped_paper_durable_snapshot_max_age:
            return {
                "valid": False,
                "reason": "DURABLE_SNAPSHOT_STALE",
                "age": age,
                "threshold": (
                    self.stopped_paper_durable_snapshot_max_age
                ),
            }

        return {
            "valid": True,
            "reason": None,
            "source": snapshot.get("source"),
            "position_state": (
                "remaining" if position_remaining else "flat"
            ),
            "pending_order_state": (
                "remaining" if pending_order else "flat"
            ),
            "open_order_state": (
                "remaining" if open_order_count > 0 else "flat"
            ),
            "open_order_count": open_order_count,
            "position_state_source": position_source,
            "pending_order_state_source": pending_source,
            "open_order_state_source": open_order_source,
        }

    def _write_json_atomic(self, path, payload):

        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        temp_path = (
            f"{path}.tmp-{self.runtime_instance_id}-{uuid.uuid4().hex}"
        )

        try:
            descriptor = os.open(
                temp_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    payload,
                    handle,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temp_path, path)
        finally:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

    def _persist_stopped_paper_durable_snapshot(self, snapshot):

        try:
            payload = self._stopped_paper_durable_snapshot_payload(
                snapshot
            )
            validation = self._validate_stopped_paper_durable_snapshot(
                payload,
                allow_current_runtime=True,
            )
            if validation.get("valid") is not True:
                return False, validation.get("reason") or "STATE_UNKNOWN"

            path = self.stopped_paper_durable_snapshot_path
            existing = None
            if path and os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as handle:
                        existing = json.load(handle)
                except Exception:
                    existing = None

            existing_validation = (
                self._validate_stopped_paper_durable_snapshot(
                    existing,
                    allow_current_runtime=True,
                )
            )
            if existing_validation.get("valid") is True:
                existing_generation = existing.get("generation")
                candidate_generation = payload.get("generation")
                if candidate_generation < existing_generation:
                    return False, "SNAPSHOT_GENERATION_OLDER"
                if (
                    candidate_generation == existing_generation
                    and payload.get("timestampEpoch")
                    < existing.get("timestampEpoch")
                ):
                    return False, "SNAPSHOT_TIMESTAMP_OLDER"

            self._write_json_atomic(
                path,
                payload,
            )
            return True, None
        except Exception:
            return False, "SNAPSHOT_PERSIST_FAILED"

    def _invalidate_stopped_paper_durable_snapshot(self, reason):

        path = self.stopped_paper_durable_snapshot_path

        try:
            if not path or not os.path.exists(path):
                return True

            os.remove(path)
            return True
        except FileNotFoundError:
            return True
        except Exception:
            logger.error(
                "Stopped paper durable snapshot invalidation failed: %s",
                reason,
            )
            return False

    def _load_stopped_paper_durable_snapshot(self):

        path = self.stopped_paper_durable_snapshot_path

        if not path or not os.path.exists(path):
            return None, "DURABLE_SNAPSHOT_MISSING"

        try:
            with open(path, "r", encoding="utf-8") as handle:
                snapshot = json.load(handle)
        except json.JSONDecodeError:
            return None, "DURABLE_SNAPSHOT_CORRUPT"
        except Exception:
            return None, "DURABLE_SNAPSHOT_READ_FAILED"

        validation = self._validate_stopped_paper_durable_snapshot(
            snapshot
        )
        if validation.get("valid") is not True:
            return None, validation.get("reason") or "STATE_UNKNOWN"

        return snapshot, None

    def _rebind_stopped_paper_durable_snapshot(
        self,
        operation_id=None,
    ):

        durable_snapshot, reason = (
            self._load_stopped_paper_durable_snapshot()
        )
        if durable_snapshot is None:
            return None, reason

        now = time.time()
        pending_source = self._stopped_paper_durable_pending_source(
            durable_snapshot
        )

        rebound = {
            "balance": None,
            "equity": None,
            "availableBalance": None,
            "pnl": None,
            "position": deepcopy(durable_snapshot.get("position")),
            "positions": deepcopy(durable_snapshot.get("positions")),
            "realizedPnl": None,
            "unrealizedPnl": None,
            "last_update": now,
            "available": True,
            "capturedAt": durable_snapshot.get("capturedAt"),
            "timestamp": durable_snapshot.get("timestampEpoch"),
            "timestampEpoch": durable_snapshot.get("timestampEpoch"),
            "source": durable_snapshot.get("source"),
            "tradeMode": "paper",
            "mode": "paper",
            "selectedMode": "PAPER",
            "botRunning": False,
            "lifecycleState": "STOPPED",
            "loopEnabled": False,
            "autoTradeEnabled": False,
            "executionEnabled": False,
            "positionRemaining": durable_snapshot.get(
                "positionRemaining"
            ),
            "pendingOrder": durable_snapshot.get("pendingOrder"),
            "pending_order": durable_snapshot.get("pendingOrder"),
            "openOrderCount": durable_snapshot.get("openOrderCount"),
            "stateUnknown": False,
            "dataQuality": "AUTHORITATIVE_STOPPED_PAPER_DURABLE_EVIDENCE",
            "operationId": None,
            "generation": self.account_snapshot_generation,
            "runtimeInstanceId": self.runtime_instance_id,
            "positionStateSource": durable_snapshot.get(
                "positionStateSource"
            ),
            "pendingStateSource": pending_source,
            "pendingOrderStateSource": pending_source,
            "openOrderStateSource": durable_snapshot.get(
                "openOrderStateSource"
            ),
            "authorityReason": "STOPPED_PAPER_DURABLE_EVIDENCE_REBOUND",
            "evidenceGeneration": durable_snapshot.get("generation"),
            "evidenceCapturedAt": durable_snapshot.get("capturedAt"),
            "evidenceSource": durable_snapshot.get("source"),
            "evidenceRuntimeInstanceId": durable_snapshot.get(
                "runtimeInstanceId"
            ),
            "currentEmergencyOperationId": operation_id,
            "currentRetryGeneration": (
                self.account_snapshot_generation + 1
            ),
            "durableReboundAt": now,
        }

        return rebound, None

    def _restore_stopped_paper_durable_authority(self):

        with self.stopped_paper_durable_rebind_lock:
            current = self.account_snapshot
            if (
                isinstance(current, dict)
                and current.get("available") is True
            ):
                return current, None

            if self._running is not False:
                return None, "BOT_NOT_STOPPED"

            if self.lifecycle_state != "STOPPED":
                return None, "BOT_NOT_STOPPED"

            if governance_state.get("execution_enabled") is not False:
                return None, "EXECUTION_STATE_UNKNOWN"

            if self.engine is not None:
                return None, "ENGINE_AVAILABLE"

            if self.session_id != 0 or self.account_snapshot_generation != 0:
                return None, "SNAPSHOT_NOT_SYNCED"

            if (
                governance_state.get("emergency_state") != EMERGENCY_READY
                or governance_state.get("emergency_stop") is not False
            ):
                return None, "SNAPSHOT_NOT_SYNCED"

            configured_mode = str(
                self.config.get("mode", "paper")
            ).strip().lower()
            if (
                configured_mode != "paper"
                or self.config.get("dry_run", True) is not True
                or backend_config.TRADE_MODE != "paper"
                or backend_config.ALLOW_LIVE is not False
            ):
                return None, "DURABLE_RESTORE_MODE_UNSAFE"

            live_readiness = self._build_live_readiness_snapshot(
                "PAPER",
                True,
            )
            if live_readiness.get("realOrderAllowed") is not False:
                return None, "REAL_ORDER_ALLOWED"

            try:
                from backend.routers import positions as positions_router

                if positions_router.engine is not None:
                    return None, "POSITIONS_REGISTRY_ATTACHED"
            except Exception:
                return None, "POSITIONS_REGISTRY_UNKNOWN"

            try:
                trading_runtime = runtime_registry.trading_runtime
                execution_runtime = (
                    getattr(trading_runtime, "execution_runtime", None)
                    if trading_runtime is not None
                    else None
                )
                if (
                    execution_runtime is not None
                    and getattr(execution_runtime, "engine", None) is not None
                ):
                    return None, "EXECUTION_REGISTRY_ATTACHED"
            except Exception:
                return None, "EXECUTION_REGISTRY_UNKNOWN"

            rebound, reason = self._rebind_stopped_paper_durable_snapshot()
            if rebound is None:
                return None, reason

            self.account_snapshot = rebound
            return rebound, None

    def _stopped_paper_unknown_snapshot(
        self,
        snapshot,
        reason,
    ):

        failed = deepcopy(
            snapshot
            if isinstance(snapshot, dict)
            else {}
        )
        failed.update({
            "available": False,
            "last_update": time.time(),
            "positionRemaining": None,
            "pendingOrder": None,
            "pending_order": None,
            "openOrderCount": None,
            "stateUnknown": True,
            "generation": self.account_snapshot_generation,
            "authorityReason": reason,
        })
        return failed

    @staticmethod
    def _stopped_paper_snapshot_sources():

        return {
            "stopped_paper_engine_snapshot",
            "stopped_paper_portfolio_snapshot",
            "stopped_paper_engine_portfolio_snapshot",
            "stopped_paper_preserved_runtime_state",
        }

    @staticmethod
    def _stopped_paper_base_snapshot_sources():

        return {
            "stopped_paper_engine_snapshot",
            "stopped_paper_portfolio_snapshot",
            "stopped_paper_engine_portfolio_snapshot",
        }

    @staticmethod
    def _stopped_paper_position_sources():

        return {
            "execution_engine.actual_position",
            "portfolio.positions",
            "execution_engine.actual_position+portfolio.positions",
        }

    @staticmethod
    def _stopped_paper_pending_order_sources():

        return {
            "execution_engine.pending_order_duplicate_lock",
        }

    @staticmethod
    def _stopped_paper_open_order_sources():

        return {
            "execution_engine.open_orders",
            "execution_engine.open_order",
            "execution_engine.orders",
            (
                "execution_engine."
                "paper_immediate_fill_no_open_order_collection"
            ),
        }

    @staticmethod
    def _stopped_paper_snapshot_source_for_authority_sources(
        position_source,
        open_order_source=None,
    ):

        has_engine = (
            isinstance(position_source, str)
            and "execution_engine.actual_position" in position_source
        ) or (
            isinstance(open_order_source, str)
            and open_order_source.startswith("execution_engine.")
        )
        has_portfolio = (
            isinstance(position_source, str)
            and "portfolio.positions" in position_source
        )

        if has_engine and has_portfolio:
            return "stopped_paper_engine_portfolio_snapshot"
        if has_engine:
            return "stopped_paper_engine_snapshot"
        if has_portfolio:
            return "stopped_paper_portfolio_snapshot"

        return None

    def _build_stopped_paper_engine_safety_snapshot(
        self,
        engine,
        operation_id=None,
    ):

        if engine is None:
            return None, "ENGINE_UNAVAILABLE"

        mode = self._normalize_emergency_mode(
            getattr(engine, "mode", None)
        )
        if mode != "paper":
            return None, "LIVE_MODE"

        position_state = self._stopped_paper_engine_position_state(engine)
        pending_order_state = (
            self._stopped_paper_engine_pending_order_state(engine)
        )
        open_order_state = self._stopped_paper_engine_open_order_state(engine)

        try:
            now = time.time()
        except Exception:
            return None, "SNAPSHOT_TIME_UNAVAILABLE"

        if (
            type(now) not in {int, float}
            or not math.isfinite(now)
            or now <= 0
        ):
            return None, "SNAPSHOT_TIME_UNAVAILABLE"

        position_source = position_state.get("source")
        open_order_source = open_order_state.get("source")
        snapshot_source = (
            self._stopped_paper_snapshot_source_for_authority_sources(
                position_source,
                open_order_source,
            )
            or "stopped_paper_engine_portfolio_snapshot"
        )

        position_unknown = position_state.get("state") == "unknown"
        pending_order_unknown = (
            pending_order_state.get("state") == "unknown"
        )
        open_order_unknown = open_order_state.get("state") == "unknown"
        state_unknown = (
            position_unknown
            or pending_order_unknown
            or open_order_unknown
        )
        next_generation = self.account_snapshot_generation + 1

        snapshot = deepcopy(
            self.account_snapshot
            if isinstance(self.account_snapshot, dict)
            else {}
        )
        position = position_state.get("position")
        positions = position_state.get("positions")
        if position_state.get("state") == "flat":
            position = None
            positions = []
        elif isinstance(positions, dict):
            positions = list(deepcopy(positions).values())
        elif positions is None and position is not None:
            positions = [deepcopy(position)]

        snapshot.update({
            "position": deepcopy(position),
            "positions": deepcopy(positions),
            "last_update": now,
            "available": state_unknown is not True,
            "capturedAt": now,
            "timestamp": now,
            "timestampEpoch": now,
            "source": snapshot_source,
            "tradeMode": "paper",
            "mode": "paper",
            "selectedMode": "PAPER",
            "botRunning": False,
            "lifecycleState": "STOPPED",
            "loopEnabled": False,
            "autoTradeEnabled": False,
            "executionEnabled": False,
            "positionRemaining": (
                position_state.get("state") == "remaining"
                if position_state.get("state") in {"flat", "remaining"}
                else None
            ),
            "pendingOrder": (
                pending_order_state.get("pending_order")
                if type(pending_order_state.get("pending_order")) is bool
                else None
            ),
            "pending_order": (
                pending_order_state.get("pending_order")
                if type(pending_order_state.get("pending_order")) is bool
                else None
            ),
            "openOrderCount": open_order_state.get("count"),
            "stateUnknown": state_unknown,
            "dataQuality": (
                "AUTHORITATIVE_STOPPED_PAPER_ENGINE_SNAPSHOT"
                if state_unknown is not True
                else "STOPPED_PAPER_ENGINE_SNAPSHOT_UNKNOWN"
            ),
            "operationId": operation_id,
            "generation": next_generation,
            "runtimeInstanceId": self.runtime_instance_id,
            "evidenceGeneration": next_generation,
            "evidenceRuntimeInstanceId": self.runtime_instance_id,
            "evidenceSource": snapshot_source,
            "evidenceCapturedAt": now,
            "positionStateSource": position_state.get("source"),
            "openOrderStateSource": open_order_state.get("source"),
            "pendingStateSource": pending_order_state.get("source"),
            "pendingOrderStateSource": pending_order_state.get("source"),
            "authorityReason": (
                position_state.get("reason")
                if position_unknown
                else pending_order_state.get("reason")
                if pending_order_unknown
                else open_order_state.get("reason")
                if open_order_unknown
                else "STOPPED_PAPER_ENGINE_STATE_CAPTURED"
            ),
        })

        return snapshot, None

    def _preserve_stopped_paper_engine_safety_snapshot(
        self,
        operation_id=None,
    ):

        try:
            engine = self.engine
        except Exception:
            return None

        if engine is None:
            return None

        if operation_id is None:
            operation_id = governance_state.get(
                "current_emergency_operation_id"
            )

        snapshot, reason = self._build_stopped_paper_engine_safety_snapshot(
            engine,
            operation_id=operation_id,
        )
        if snapshot is None:
            self._invalidate_stopped_paper_durable_snapshot(
                reason or "SNAPSHOT_UNAVAILABLE"
            )
            return None

        if snapshot.get("stateUnknown") is True:
            self._invalidate_stopped_paper_durable_snapshot(
                snapshot.get("authorityReason") or "STATE_UNKNOWN"
            )
            self.account_snapshot = self._stopped_paper_unknown_snapshot(
                snapshot,
                snapshot.get("authorityReason") or "STATE_UNKNOWN",
            )
            return None

        persisted, persist_reason = (
            self._persist_stopped_paper_durable_snapshot(snapshot)
        )
        if persisted is not True:
            self.account_snapshot = self._stopped_paper_unknown_snapshot(
                snapshot,
                persist_reason or "SNAPSHOT_PERSIST_FAILED",
            )
            return None

        self.account_snapshot = snapshot
        self.account_snapshot_generation = snapshot.get(
            "generation",
            self.account_snapshot_generation,
        )
        return snapshot

    def _stopped_paper_snapshot_authority_state(self, snapshot):

        if not isinstance(snapshot, dict):
            return {
                "valid": False,
                "reason": "SNAPSHOT_UNAVAILABLE",
            }

        source = snapshot.get("source")
        if source not in self._stopped_paper_snapshot_sources():
            return {
                "valid": False,
                "reason": "SNAPSHOT_SOURCE_UNKNOWN",
                "source": source,
            }

        for field in (
            "capturedAt",
            "timestampEpoch",
            "tradeMode",
            "mode",
            "selectedMode",
            "lifecycleState",
            "operationId",
        ):
            if field not in snapshot:
                return {
                    "valid": False,
                    "reason": "SNAPSHOT_REQUIRED_FIELD_MISSING",
                    "source": source,
                    "field": field,
                }

        generation = snapshot.get("generation")
        if generation != self.account_snapshot_generation:
            return {
                "valid": False,
                "reason": "SNAPSHOT_GENERATION_MISMATCH",
                "source": source,
                "generation": generation,
                "expectedGeneration": self.account_snapshot_generation,
            }

        if snapshot.get("stateUnknown") is True:
            return {
                "valid": False,
                "reason": (
                    snapshot.get("authorityReason")
                    or "STATE_UNKNOWN"
                ),
                "source": source,
            }

        position_source = snapshot.get("positionStateSource")
        if position_source not in self._stopped_paper_position_sources():
            return {
                "valid": False,
                "reason": "POSITION_STATE_UNKNOWN",
                "source": source,
                "position_state_source": position_source,
            }

        pending_order_source = self._stopped_paper_durable_pending_source(
            snapshot
        )
        if (
            pending_order_source
            not in self._stopped_paper_pending_order_sources()
        ):
            return {
                "valid": False,
                "reason": "PENDING_ORDER_UNKNOWN",
                "source": source,
                "pending_order_state_source": pending_order_source,
            }

        open_order_source = snapshot.get("openOrderStateSource")
        if open_order_source not in self._stopped_paper_open_order_sources():
            return {
                "valid": False,
                "reason": "OPEN_ORDER_UNKNOWN",
                "source": source,
                "open_order_state_source": open_order_source,
            }

        effective_source = source
        if source == "stopped_paper_preserved_runtime_state":
            effective_source = snapshot.get("sourceSnapshotSource")
            if (
                effective_source
                not in self._stopped_paper_base_snapshot_sources()
            ):
                return {
                    "valid": False,
                    "reason": "SNAPSHOT_SOURCE_MISMATCH",
                    "source": source,
                    "sourceSnapshotSource": effective_source,
                }

        expected_source = (
            self._stopped_paper_snapshot_source_for_authority_sources(
                position_source,
                open_order_source,
            )
        )
        if effective_source != expected_source:
            return {
                "valid": False,
                "reason": "SNAPSHOT_SOURCE_MISMATCH",
                "source": source,
                "effectiveSource": effective_source,
                "expectedSource": expected_source,
            }

        position_remaining = snapshot.get("positionRemaining")
        if type(position_remaining) is not bool:
            return {
                "valid": False,
                "reason": "POSITION_STATE_UNKNOWN",
                "source": source,
            }

        snapshot_position_state = self._stopped_paper_position_state(
            snapshot
        )
        if position_remaining:
            if snapshot_position_state != "remaining":
                return {
                    "valid": False,
                    "reason": "POSITION_STATE_UNKNOWN",
                    "source": source,
                }
        elif snapshot_position_state != "flat":
            return {
                "valid": False,
                "reason": "POSITION_STATE_UNKNOWN",
                "source": source,
            }

        pending_order = snapshot.get("pendingOrder")
        if type(pending_order) is not bool:
            return {
                "valid": False,
                "reason": "PENDING_ORDER_UNKNOWN",
                "source": source,
            }

        open_order_state = self._stopped_paper_open_order_state(snapshot)
        if open_order_state.get("state") == "unknown":
            return {
                "valid": False,
                "reason": (
                    open_order_state.get("reason")
                    or "OPEN_ORDER_UNKNOWN"
                ),
                "source": source,
            }

        return {
            "valid": True,
            "source": source,
            "position_state": (
                "remaining" if position_remaining else "flat"
            ),
            "pending_order_state": (
                "remaining" if pending_order else "flat"
            ),
            "open_order_state": open_order_state.get("state"),
            "open_order_count": open_order_state.get("count"),
            "position_state_source": snapshot.get("positionStateSource"),
            "pending_order_state_source": pending_order_source,
            "open_order_state_source": (
                snapshot.get("openOrderStateSource")
                or open_order_state.get("source")
            ),
        }

    def _stopped_paper_shutdown_evidence_state(self, snapshot):

        authority = self._stopped_paper_snapshot_authority_state(snapshot)
        if authority.get("valid") is not True:
            return authority

        source = snapshot.get("source")
        generation = snapshot.get("generation")
        runtime_id = snapshot.get("runtimeInstanceId")
        evidence_generation = snapshot.get("evidenceGeneration")
        evidence_runtime_id = snapshot.get("evidenceRuntimeInstanceId")
        evidence_source = snapshot.get("evidenceSource")

        identity_valid = (
            self._non_negative_int(generation)
            and self._non_negative_int(evidence_generation)
            and self._non_empty_string(runtime_id)
            and self._non_empty_string(evidence_runtime_id)
        )

        direct_durable = (
            source in self._stopped_paper_base_snapshot_sources()
            and snapshot.get("authorityReason")
            == "STOPPED_PAPER_DURABLE_EVIDENCE_REBOUND"
        )
        preserved_durable = (
            source == "stopped_paper_preserved_runtime_state"
            and self._finite_positive_number(
                snapshot.get("durableReboundAt")
            )
        )

        if direct_durable or preserved_durable:
            durable_snapshot, durable_reason = (
                self._load_stopped_paper_durable_snapshot()
            )
            if durable_snapshot is None:
                return {
                    "valid": False,
                    "reason": durable_reason or "STATE_UNKNOWN",
                }

            runtime_reason = self._stopped_paper_durable_runtime_reason()
            if runtime_reason is not None:
                return {"valid": False, "reason": runtime_reason}

            effective_source = (
                snapshot.get("sourceSnapshotSource")
                if preserved_durable
                else source
            )
            identity_valid = (
                identity_valid
                and snapshot.get("available") is True
                and runtime_id == self.runtime_instance_id
                and generation == self.account_snapshot_generation
                and effective_source == durable_snapshot.get("source")
                and evidence_source == durable_snapshot.get("source")
                and evidence_generation
                == durable_snapshot.get("evidenceGeneration")
                and evidence_runtime_id
                == durable_snapshot.get("evidenceRuntimeInstanceId")
                and snapshot.get("capturedAt")
                == durable_snapshot.get("capturedAt")
                and snapshot.get("evidenceCapturedAt")
                == durable_snapshot.get("capturedAt")
                and snapshot.get("timestampEpoch")
                == durable_snapshot.get("timestampEpoch")
                and snapshot.get("mode") == "paper"
                and snapshot.get("mode") == durable_snapshot.get("mode")
                and snapshot.get("tradeMode") == "paper"
                and snapshot.get("tradeMode")
                == durable_snapshot.get("tradeMode")
                and snapshot.get("selectedMode") == "PAPER"
                and snapshot.get("selectedMode")
                == durable_snapshot.get("selectedMode")
                and snapshot.get("lifecycleState") == "STOPPED"
                and snapshot.get("lifecycleState")
                == durable_snapshot.get("lifecycleState")
                and snapshot.get("stateUnknown") is False
                and durable_snapshot.get("stateUnknown") is False
                and snapshot.get("positionRemaining") is False
                and durable_snapshot.get("positionRemaining") is False
                and snapshot.get("pendingOrder") is False
                and snapshot.get("pending_order") is False
                and durable_snapshot.get("pendingOrder") is False
                and type(snapshot.get("openOrderCount")) is int
                and snapshot.get("openOrderCount") == 0
                and type(durable_snapshot.get("openOrderCount")) is int
                and durable_snapshot.get("openOrderCount") == 0
                and snapshot.get("positionStateSource")
                == durable_snapshot.get("positionStateSource")
                and snapshot.get("pendingStateSource")
                == durable_snapshot.get("pendingStateSource")
                and snapshot.get("pendingOrderStateSource")
                == durable_snapshot.get("pendingOrderStateSource")
                and snapshot.get("openOrderStateSource")
                == durable_snapshot.get("openOrderStateSource")
                and self._finite_positive_number(
                    snapshot.get("durableReboundAt")
                )
            )
        elif source in self._stopped_paper_base_snapshot_sources():
            identity_valid = (
                identity_valid
                and source == evidence_source
                and generation == evidence_generation
                and runtime_id == evidence_runtime_id
                and runtime_id == self.runtime_instance_id
            )
        elif source == "stopped_paper_preserved_runtime_state":
            identity_valid = (
                identity_valid
                and evidence_source
                in self._stopped_paper_base_snapshot_sources()
                and runtime_id == self.runtime_instance_id
                and snapshot.get("lifecycleState") == "STOPPED"
                and snapshot.get("positionRemaining") is False
                and snapshot.get("pendingOrder") is False
                and snapshot.get("openOrderCount") == 0
            )
        else:
            identity_valid = False

        if not identity_valid:
            return {
                "valid": False,
                "reason": "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
            }

        if "durable_snapshot" in locals():
            authority = dict(authority)
            authority["durable_snapshot"] = durable_snapshot

        return authority

    def _stopped_paper_durable_runtime_reason(self):

        if self._running is not False or self.lifecycle_state != "STOPPED":
            return "BOT_NOT_STOPPED"
        if governance_state.get("execution_enabled") is not False:
            return "EXECUTION_STATE_UNKNOWN"
        if self.engine is not None:
            return "ENGINE_AVAILABLE"
        if str(self.config.get("mode", "paper")).strip().lower() != "paper":
            return "LIVE_MODE"
        if self.config.get("dry_run", True) is not True:
            return "PAPER_DRY_RUN_REQUIRED"
        if (
            backend_config.TRADE_MODE != "paper"
            or backend_config.ALLOW_LIVE is not False
        ):
            return "DURABLE_RESTORE_MODE_UNSAFE"
        if self._build_live_readiness_snapshot("PAPER", True).get(
            "realOrderAllowed"
        ) is not False:
            return "REAL_ORDER_ALLOWED"

        try:
            from backend.routers import positions as positions_router
            if positions_router.engine is not None:
                return "POSITIONS_REGISTRY_ATTACHED"
        except Exception:
            return "POSITIONS_REGISTRY_UNKNOWN"

        try:
            trading_runtime = runtime_registry.trading_runtime
            execution_runtime = (
                getattr(trading_runtime, "execution_runtime", None)
                if trading_runtime is not None
                else None
            )
            if execution_runtime is not None and getattr(
                execution_runtime,
                "engine",
                None,
            ) is not None:
                return "EXECUTION_REGISTRY_ATTACHED"
        except Exception:
            return "EXECUTION_REGISTRY_UNKNOWN"

        return None

    def _save_stopped_paper_safety_snapshot(self, snapshot):

        self.account_snapshot = snapshot
        return True

    def _refresh_stopped_paper_safety_snapshot(
        self,
        snapshot,
        operation_id=None,
    ):

        if not isinstance(snapshot, dict):
            return None, "SNAPSHOT_UNAVAILABLE"

        authority_state = self._stopped_paper_snapshot_authority_state(
            snapshot
        )
        if authority_state.get("valid") is not True:
            return None, authority_state.get("reason") or "STATE_UNKNOWN"

        if authority_state.get("position_state") == "remaining":
            return None, "POSITION_REMAINING"
        if authority_state.get("pending_order_state") == "remaining":
            return None, "PENDING_ORDER_REMAINING"
        if authority_state.get("open_order_state") == "remaining":
            return None, "OPEN_ORDER_REMAINING"

        try:
            now = time.time()
        except Exception:
            return None, "SNAPSHOT_TIME_UNAVAILABLE"

        if (
            type(now) not in {int, float}
            or not math.isfinite(now)
            or now <= 0
        ):
            return None, "SNAPSHOT_TIME_UNAVAILABLE"

        durable_evidence = (
            snapshot.get("authorityReason")
            == "STOPPED_PAPER_DURABLE_EVIDENCE_REBOUND"
            or self._finite_positive_number(
                snapshot.get("durableReboundAt")
            )
        )
        if durable_evidence:
            evidence_state = self._stopped_paper_shutdown_evidence_state(
                snapshot
            )
            if evidence_state.get("valid") is not True:
                return None, (
                    evidence_state.get("reason")
                    or "SNAPSHOT_EVIDENCE_IDENTITY_INVALID"
                )

        refreshed = deepcopy(snapshot)
        next_generation = self.account_snapshot_generation + 1
        refreshed.update({
            "position": None,
            "positions": [],
            "last_update": (
                snapshot.get("last_update")
                if durable_evidence
                else now
            ),
            "available": True,
            "capturedAt": (
                snapshot.get("capturedAt")
                if durable_evidence
                else now
            ),
            "timestamp": (
                snapshot.get("timestamp")
                if durable_evidence
                else now
            ),
            "timestampEpoch": (
                snapshot.get("timestampEpoch")
                if durable_evidence
                else now
            ),
            "source": "stopped_paper_preserved_runtime_state",
            "sourceSnapshotSource": authority_state.get("source"),
            "tradeMode": "paper",
            "mode": "paper",
            "selectedMode": "PAPER",
            "botRunning": False,
            "lifecycleState": self.lifecycle_state,
            "loopEnabled": False,
            "autoTradeEnabled": False,
            "executionEnabled": False,
            "positionRemaining": False,
            "pendingOrder": False,
            "pending_order": False,
            "openOrderCount": authority_state.get("open_order_count"),
            "stateUnknown": False,
            "dataQuality": "AUTHORITATIVE_STOPPED_PAPER_RECHECK",
            "operationId": operation_id,
            "generation": next_generation,
            "runtimeInstanceId": self.runtime_instance_id,
            "positionStateSource": authority_state.get(
                "position_state_source"
            ),
            "pendingStateSource": authority_state.get(
                "pending_order_state_source"
            ),
            "pendingOrderStateSource": authority_state.get(
                "pending_order_state_source"
            ),
            "openOrderStateSource": authority_state.get(
                "open_order_state_source"
            ),
            "authorityReason": "STOPPED_PAPER_PRESERVED_STATE_SYNCED",
            "evidenceGeneration": snapshot.get(
                "evidenceGeneration",
                snapshot.get("generation"),
            ),
            "evidenceCapturedAt": snapshot.get(
                "evidenceCapturedAt",
                snapshot.get("capturedAt"),
            ),
            "evidenceSource": snapshot.get(
                "evidenceSource",
                authority_state.get("source"),
            ),
            "evidenceRuntimeInstanceId": snapshot.get(
                "evidenceRuntimeInstanceId",
                snapshot.get("runtimeInstanceId"),
            ),
            "currentEmergencyOperationId": operation_id,
            "currentRetryGeneration": next_generation,
        })
        if not durable_evidence:
            refreshed.pop("durableReboundAt", None)

        try:
            saved = self._save_stopped_paper_safety_snapshot(refreshed)
        except Exception:
            return None, "SNAPSHOT_SAVE_FAILED"

        if saved is not True:
            return None, "SNAPSHOT_SAVE_FAILED"

        self.account_snapshot_generation = next_generation
        return refreshed, None

    @staticmethod
    def _pending_order_authority_payload(
        known,
        pending,
        safe,
        reason,
        source,
        manager_pending_order=None,
        engine_available=False,
        engine_pending_order=None,
        mismatch=False,
    ):

        legacy_pending_order = (
            pending is True
            if known
            else True
        )

        return {
            "pending_order": legacy_pending_order,
            "known": known,
            "pending": pending,
            "safe": safe,
            "reason": reason,
            "source": source,
            "manager_pending_order": manager_pending_order,
            "engine_available": engine_available,
            "engine_pending_order": engine_pending_order,
            "mismatch": mismatch,
        }

    @staticmethod
    def _pending_order_status_state(pending_order_state):

        return {
            "known": pending_order_state.get("known") is True,
            "pending": pending_order_state.get("pending"),
            "safe": pending_order_state.get("safe") is True,
            "reason": pending_order_state.get("reason"),
            "source": pending_order_state.get("source", "unknown"),
            "managerPendingOrder": pending_order_state.get(
                "manager_pending_order"
            ),
            "engineAvailable": pending_order_state.get(
                "engine_available"
            ) is True,
            "enginePendingOrder": pending_order_state.get(
                "engine_pending_order"
            ),
            "mismatch": pending_order_state.get("mismatch") is True,
        }

    def _stopped_paper_snapshot_timestamp_state(self, snapshot):

        durable_candidate = (
            snapshot.get("authorityReason")
            == "STOPPED_PAPER_DURABLE_EVIDENCE_REBOUND"
            or (
                snapshot.get("source")
                == "stopped_paper_preserved_runtime_state"
                and self._finite_positive_number(
                    snapshot.get("durableReboundAt")
                )
            )
        )

        if durable_candidate:
            evidence_state = self._stopped_paper_shutdown_evidence_state(
                snapshot
            )
            if evidence_state.get("valid") is not True:
                return {
                    "valid": False,
                    "reason": (
                        evidence_state.get("reason")
                        or "SNAPSHOT_EVIDENCE_IDENTITY_INVALID"
                    ),
                }

            durable_snapshot = evidence_state.get("durable_snapshot")
            if not isinstance(durable_snapshot, dict):
                return {
                    "valid": False,
                    "reason": "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
                }

            captured_at = durable_snapshot.get("capturedAt")
            try:
                now = time.time()
            except Exception:
                return {
                    "valid": False,
                    "reason": "SNAPSHOT_TIME_UNAVAILABLE",
                }

            if not self._finite_positive_number(now):
                return {
                    "valid": False,
                    "reason": "SNAPSHOT_TIME_UNAVAILABLE",
                }

            age = now - captured_at
            if age < 0:
                return {
                    "valid": False,
                    "reason": "SNAPSHOT_TIMESTAMP_FUTURE",
                    "age": age,
                    "threshold": self.stopped_paper_durable_snapshot_max_age,
                    "freshnessClass": "DURABLE_EVIDENCE_VALIDITY",
                }

            if age > self.stopped_paper_durable_snapshot_max_age:
                return {
                    "valid": False,
                    "reason": "DURABLE_SNAPSHOT_STALE",
                    "age": age,
                    "threshold": self.stopped_paper_durable_snapshot_max_age,
                    "freshnessClass": "DURABLE_EVIDENCE_VALIDITY",
                }

            return {
                "valid": True,
                "reason": None,
                "age": age,
                "threshold": self.stopped_paper_durable_snapshot_max_age,
                "freshnessClass": "DURABLE_EVIDENCE_VALIDITY",
            }

        missing = object()
        last_update = snapshot.get("last_update", missing)

        if last_update is missing or last_update is None:
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIMESTAMP_MISSING",
            }

        if type(last_update) not in {int, float}:
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIMESTAMP_INVALID",
            }

        if (
            not math.isfinite(last_update)
            or last_update <= 0
        ):
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIMESTAMP_INVALID",
            }

        try:
            stale_after = self.account_stale_after
        except Exception:
            return {
                "valid": False,
                "reason": "SNAPSHOT_STALE_THRESHOLD_INVALID",
            }

        if type(stale_after) not in {int, float}:
            return {
                "valid": False,
                "reason": "SNAPSHOT_STALE_THRESHOLD_INVALID",
            }

        if (
            not math.isfinite(stale_after)
            or stale_after <= 0
        ):
            return {
                "valid": False,
                "reason": "SNAPSHOT_STALE_THRESHOLD_INVALID",
            }

        try:
            now = time.time()
        except Exception:
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIME_UNAVAILABLE",
            }

        if (
            type(now) not in {int, float}
            or not math.isfinite(now)
            or now <= 0
        ):
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIME_UNAVAILABLE",
            }

        age = now - last_update

        if age < 0:
            return {
                "valid": False,
                "reason": "SNAPSHOT_TIMESTAMP_FUTURE",
                "age": age,
                "threshold": stale_after,
            }

        if age > stale_after:
            return {
                "valid": False,
                "reason": "SNAPSHOT_STALE",
                "age": age,
                "threshold": stale_after,
            }

        return {
            "valid": True,
            "reason": None,
            "age": age,
            "threshold": stale_after,
            "freshnessClass": "RUNTIME_FRESHNESS",
        }

    def _stopped_paper_authoritative_safety_state(
        self,
        refresh_snapshot=False,
        operation_id=None,
    ):

        state = {
            "applies": True,
            "safe": False,
            "reason": None,
            "snapshot": None,
            "snapshot_timestamp_state": None,
            "snapshot_refresh_state": None,
            "snapshot_operation_state": None,
            "mode_resolution": None,
            "position_state": None,
            "pending_order_state": None,
            "open_order_state": None,
            "open_order_count": None,
            "durable_snapshot_state": None,
        }

        def unknown(reason):
            result = dict(state)
            result["reason"] = reason
            return result

        if (
            self._running
            or self.lifecycle_state != "STOPPED"
        ):
            return unknown("BOT_NOT_STOPPED")

        if governance_state.get("execution_enabled") is not False:
            return unknown("EXECUTION_STATE_UNKNOWN")

        try:
            snapshot = self._capture_account_snapshot()
        except Exception:
            return unknown("SNAPSHOT_UNAVAILABLE")

        if not isinstance(snapshot, dict):
            return unknown("SNAPSHOT_UNAVAILABLE")

        mode_resolution = self._stopped_paper_mode_resolution(snapshot)

        if mode_resolution.get("mode") == "live":
            result = unknown("LIVE_MODE")
            result["applies"] = False
            result["snapshot"] = snapshot
            result["mode_resolution"] = mode_resolution
            return result

        if mode_resolution.get("mode") != "paper":
            result = unknown(
                mode_resolution.get("reason") or "MODE_UNKNOWN"
            )
            result["snapshot"] = snapshot
            result["mode_resolution"] = mode_resolution
            return result

        if (
            snapshot.get("available") is not True
            and refresh_snapshot is not True
        ):
            snapshot, restore_reason = (
                self._restore_stopped_paper_durable_authority()
            )
            if snapshot is None:
                result = unknown(
                    restore_reason or "SNAPSHOT_NOT_SYNCED"
                )
                result["snapshot"] = self.account_snapshot
                result["durable_snapshot_state"] = {
                    "loaded": False,
                    "reason": restore_reason,
                }
                result["mode_resolution"] = mode_resolution
                return result
            mode_resolution = self._stopped_paper_mode_resolution(snapshot)
            state["durable_snapshot_state"] = {
                "loaded": True,
                "reason": None,
            }

        expected_operation_id = (
            operation_id
            or governance_state.get("current_emergency_operation_id")
        )
        snapshot_operation_state = {
            "valid": True,
            "reason": None,
            "operationId": snapshot.get("operationId"),
            "expectedOperationId": expected_operation_id,
            "source": snapshot.get("source"),
        }

        if (
            expected_operation_id
            and (
                snapshot.get("source")
                == "stopped_paper_preserved_runtime_state"
                or snapshot.get("operationId") is not None
            )
            and snapshot.get("operationId") != expected_operation_id
        ):
            snapshot_operation_state["valid"] = False
            snapshot_operation_state[
                "reason"
            ] = "SNAPSHOT_OPERATION_ID_MISMATCH"
            result = unknown("SNAPSHOT_OPERATION_ID_MISMATCH")
            result["snapshot"] = snapshot
            result["snapshot_operation_state"] = snapshot_operation_state
            result["mode_resolution"] = mode_resolution
            return result

        if refresh_snapshot:
            authority_probe = self._stopped_paper_snapshot_authority_state(
                snapshot
            )
            if (
                authority_probe.get("valid") is not True
                and authority_probe.get("reason")
                in {
                    "SNAPSHOT_UNAVAILABLE",
                    "SNAPSHOT_SOURCE_UNKNOWN",
                    "SNAPSHOT_REQUIRED_FIELD_MISSING",
                }
            ):
                rebound_snapshot, durable_reason = (
                    self._rebind_stopped_paper_durable_snapshot(
                        operation_id=operation_id,
                    )
                )
                if rebound_snapshot is not None:
                    snapshot = rebound_snapshot
                    mode_resolution = (
                        self._stopped_paper_mode_resolution(snapshot)
                    )
                elif durable_reason != "DURABLE_SNAPSHOT_MISSING":
                    result = unknown(durable_reason)
                    result["snapshot"] = snapshot
                    result["durable_snapshot_state"] = {
                        "loaded": False,
                        "reason": durable_reason,
                    }
                    result["mode_resolution"] = mode_resolution
                    return result

            refreshed_snapshot, refresh_reason = (
                self._refresh_stopped_paper_safety_snapshot(
                    snapshot,
                    operation_id=operation_id,
                )
            )
            if refreshed_snapshot is None:
                result = unknown(refresh_reason)
                result["snapshot"] = snapshot
                result["snapshot_refresh_state"] = {
                    "refreshed": False,
                    "reason": refresh_reason,
                    "source": "stopped_paper_recheck",
                }
                if refresh_reason == "POSITION_REMAINING":
                    result["position_state"] = "remaining"
                elif refresh_reason == "POSITION_STATE_UNKNOWN":
                    result["position_state"] = "unknown"
                if refresh_reason == "PENDING_ORDER_REMAINING":
                    result["position_state"] = "flat"
                    result["pending_order_state"] = "remaining"
                elif refresh_reason == "PENDING_ORDER_UNKNOWN":
                    result["position_state"] = "flat"
                    result["pending_order_state"] = "unknown"
                if refresh_reason == "OPEN_ORDER_REMAINING":
                    result["position_state"] = "flat"
                    result["pending_order_state"] = "flat"
                    result["open_order_state"] = "remaining"
                elif refresh_reason == "OPEN_ORDER_UNKNOWN":
                    result["position_state"] = "flat"
                    result["pending_order_state"] = "flat"
                    result["open_order_state"] = "unknown"
                result["mode_resolution"] = mode_resolution
                return result

            snapshot = refreshed_snapshot
            snapshot_operation_state = {
                "valid": True,
                "reason": None,
                "operationId": snapshot.get("operationId"),
                "expectedOperationId": expected_operation_id,
                "source": snapshot.get("source"),
            }

        timestamp_state = (
            self._stopped_paper_snapshot_timestamp_state(snapshot)
        )

        if timestamp_state.get("valid") is not True:
            result = unknown(
                timestamp_state.get(
                    "reason",
                    "SNAPSHOT_TIMESTAMP_INVALID",
                )
            )
            result["snapshot"] = snapshot
            result["snapshot_timestamp_state"] = timestamp_state
            result["mode_resolution"] = mode_resolution
            return result

        authority_state = self._stopped_paper_snapshot_authority_state(
            snapshot
        )

        if authority_state.get("valid") is not True:
            result = unknown(
                authority_state.get("reason") or "STATE_UNKNOWN"
            )
            result["snapshot"] = snapshot
            result["snapshot_operation_state"] = snapshot_operation_state
            result["mode_resolution"] = mode_resolution
            return result

        result = dict(state)
        result["snapshot"] = snapshot
        result["snapshot_timestamp_state"] = timestamp_state
        result["snapshot_operation_state"] = snapshot_operation_state
        result["mode_resolution"] = mode_resolution
        result["snapshot_refresh_state"] = {
            "refreshed": refresh_snapshot is True,
            "reason": None,
            "source": (
                "stopped_paper_recheck"
                if refresh_snapshot is True
                else "account_snapshot"
            ),
        }
        position_state = authority_state.get("position_state")
        pending_order_state = authority_state.get("pending_order_state")
        open_order_state = authority_state.get("open_order_state")
        result["position_state"] = position_state
        result["pending_order_state"] = pending_order_state
        result["open_order_state"] = open_order_state
        result["open_order_count"] = authority_state.get(
            "open_order_count"
        )

        if position_state == "unknown":
            result["reason"] = "POSITION_STATE_UNKNOWN"
            return result

        if pending_order_state == "unknown":
            result["reason"] = "PENDING_ORDER_UNKNOWN"
            return result

        if open_order_state == "unknown":
            result["reason"] = "OPEN_ORDER_UNKNOWN"
            return result

        result["position_remaining"] = position_state == "remaining"
        result["pending_order"] = pending_order_state == "remaining"
        result["open_order_remaining"] = open_order_state == "remaining"

        if result["position_remaining"]:
            result["reason"] = "POSITION_REMAINING"
            return result

        if result["pending_order"]:
            result["reason"] = "PENDING_ORDER_REMAINING"
            return result

        if result["open_order_remaining"]:
            result["reason"] = "OPEN_ORDER_REMAINING"
            return result

        result["safe"] = True
        result["reason"] = "STOPPED_PAPER_AUTHORITATIVE_SAFE"
        return result

    def _bootstrap_stopped_paper_authority_state(
        self,
        manager_pending_order,
    ):

        def blocked(reason):
            return {
                "safe": False,
                "reason": reason,
                "source": "bootstrap_stopped_paper",
            }

        if self.engine is not None:
            return blocked("ENGINE_AVAILABLE")

        if (
            self._running is not False
            or self.lifecycle_state != "STOPPED"
        ):
            return blocked("BOT_NOT_STOPPED")

        if governance_state.get("execution_enabled") is not False:
            return blocked("EXECUTION_STATE_UNKNOWN")

        if (
            governance_state.get("emergency_state") != EMERGENCY_READY
            or governance_state.get("emergency_stop") is not False
        ):
            return blocked("EMERGENCY_NOT_READY")

        configured_mode = str(
            self.config.get("mode", "paper")
        ).strip().lower()
        configured_dry_run = self.config.get("dry_run", True)
        if (
            configured_mode != "paper"
            or configured_dry_run is not True
            or backend_config.TRADE_MODE != "paper"
            or backend_config.ALLOW_LIVE is not False
        ):
            return blocked("BOOTSTRAP_MODE_UNSAFE")

        live_readiness = self._build_live_readiness_snapshot(
            "PAPER",
            True,
        )
        if live_readiness.get("realOrderAllowed") is not False:
            return blocked("REAL_ORDER_ALLOWED")

        if manager_pending_order is not False:
            return blocked("PENDING_ORDER_MANAGER_UNKNOWN")

        try:
            from backend.routers import positions as positions_router

            if positions_router.engine is not None:
                return blocked("POSITIONS_REGISTRY_ATTACHED")
        except Exception:
            return blocked("POSITIONS_REGISTRY_UNKNOWN")

        try:
            trading_runtime = runtime_registry.trading_runtime
            execution_runtime = (
                getattr(trading_runtime, "execution_runtime", None)
                if trading_runtime is not None
                else None
            )
            if (
                execution_runtime is not None
                and getattr(execution_runtime, "engine", None) is not None
            ):
                return blocked("EXECUTION_REGISTRY_ATTACHED")
        except Exception:
            return blocked("EXECUTION_REGISTRY_UNKNOWN")

        if os.path.lexists(self.stopped_paper_durable_snapshot_path):
            return blocked("DURABLE_SNAPSHOT_PRESENT")

        snapshot = self.account_snapshot
        if not isinstance(snapshot, dict):
            return blocked("POSITION_STATE_UNKNOWN")

        # Bootstrap authority is restricted to a virgin process.  Once an
        # engine session or account evidence generation has existed, only the
        # normal stopped-paper snapshot authority may prove flat state.
        if (
            self.session_id != 0
            or self.account_snapshot_generation != 0
            or self.position != "NONE"
            or snapshot.get("position") is not None
            or snapshot.get("positions") is not None
        ):
            return blocked("POSITION_STATE_UNKNOWN")

        return {
            "safe": True,
            "reason": "BOOTSTRAP_STOPPED_PAPER_CONFIRMED",
            "source": "bootstrap_stopped_paper",
            "position_state": "flat",
            "pending_order_state": "flat",
            "open_order_state": "flat",
            "open_order_count": 0,
        }

    def get_authoritative_pending_order_state(self):

        missing = object()

        try:
            manager_pending_order = getattr(
                self,
                "pending_order",
                missing,
            )
        except Exception:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="PENDING_ORDER_MANAGER_UNKNOWN",
                source="unknown",
            )

        if manager_pending_order is missing:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="PENDING_ORDER_MANAGER_UNKNOWN",
                source="unknown",
            )

        if type(manager_pending_order) is not bool:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="PENDING_ORDER_MANAGER_UNKNOWN",
                source="unknown",
            )

        try:
            engine = self.engine
        except Exception:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="ENGINE_UNAVAILABLE",
                source="unknown",
                manager_pending_order=manager_pending_order,
            )

        current_snapshot = self.account_snapshot
        durable_memory = (
            isinstance(current_snapshot, dict)
            and (
                current_snapshot.get("authorityReason")
                == "STOPPED_PAPER_DURABLE_EVIDENCE_REBOUND"
                or (
                    current_snapshot.get("source")
                    == "stopped_paper_preserved_runtime_state"
                    and self._finite_positive_number(
                        current_snapshot.get("durableReboundAt")
                    )
                )
            )
        )
        if durable_memory and engine is not None:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="ENGINE_AVAILABLE",
                source="stopped_paper_authoritative",
                manager_pending_order=manager_pending_order,
                engine_available=True,
            )

        if engine is None:
            stopped_state = (
                self._stopped_paper_authoritative_safety_state()
            )
            timestamp_state = stopped_state.get(
                "snapshot_timestamp_state"
            )

            if stopped_state.get("safe") is True:
                return self._pending_order_authority_payload(
                    known=True,
                    pending=False,
                    safe=True,
                    reason="STOPPED_PAPER_AUTHORITATIVE_SAFE",
                    source="stopped_paper_authoritative",
                    manager_pending_order=manager_pending_order,
                    engine_available=False,
                )

            if (
                isinstance(timestamp_state, dict)
                and timestamp_state.get("valid") is False
            ):
                return self._pending_order_authority_payload(
                    known=False,
                    pending=None,
                    safe=False,
                    reason=(
                        timestamp_state.get("reason")
                        or "SNAPSHOT_TIMESTAMP_INVALID"
                    ),
                    source="stopped_paper_authoritative",
                    manager_pending_order=manager_pending_order,
                    engine_available=False,
                )

            if (
                stopped_state.get("pending_order_state")
                == "remaining"
            ):
                return self._pending_order_authority_payload(
                    known=True,
                    pending=True,
                    safe=False,
                    reason="PENDING_ORDER_REMAINING",
                    source="stopped_paper_authoritative",
                    manager_pending_order=manager_pending_order,
                    engine_available=False,
                )

            if (
                stopped_state.get("pending_order_state")
                == "unknown"
            ):
                return self._pending_order_authority_payload(
                    known=False,
                    pending=None,
                    safe=False,
                    reason="PENDING_ORDER_UNKNOWN",
                    source="stopped_paper_authoritative",
                    manager_pending_order=manager_pending_order,
                    engine_available=False,
                )

            stopped_reason = stopped_state.get("reason")

            if stopped_reason:
                bootstrap_state = (
                    self._bootstrap_stopped_paper_authority_state(
                        manager_pending_order
                    )
                )
                if bootstrap_state.get("safe") is True:
                    return self._pending_order_authority_payload(
                        known=True,
                        pending=False,
                        safe=True,
                        reason=(
                            "BOOTSTRAP_STOPPED_PAPER_CONFIRMED"
                        ),
                        source="bootstrap_stopped_paper",
                        manager_pending_order=manager_pending_order,
                        engine_available=False,
                    )

                return self._pending_order_authority_payload(
                    known=False,
                    pending=None,
                    safe=False,
                    reason=stopped_reason,
                    source="stopped_paper_authoritative",
                    manager_pending_order=manager_pending_order,
                    engine_available=False,
                )

            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="ENGINE_UNAVAILABLE",
                source="unknown",
                manager_pending_order=manager_pending_order,
                engine_available=False,
            )

        try:
            engine_pending_order = getattr(
                engine,
                "pending_order",
                missing,
            )
        except Exception:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="PENDING_ORDER_READ_FAILED",
                source="engine",
                manager_pending_order=manager_pending_order,
                engine_available=True,
            )

        if engine_pending_order is missing:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="PENDING_ORDER_UNKNOWN",
                source="engine",
                manager_pending_order=manager_pending_order,
                engine_available=True,
            )

        if type(engine_pending_order) is not bool:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="PENDING_ORDER_UNKNOWN",
                source="engine",
                manager_pending_order=manager_pending_order,
                engine_available=True,
                engine_pending_order=None,
            )

        if engine_pending_order != manager_pending_order:
            return self._pending_order_authority_payload(
                known=False,
                pending=None,
                safe=False,
                reason="PENDING_ORDER_MISMATCH",
                source="manager_and_engine",
                manager_pending_order=manager_pending_order,
                engine_available=True,
                engine_pending_order=engine_pending_order,
                mismatch=True,
            )

        if engine_pending_order is True:
            return self._pending_order_authority_payload(
                known=True,
                pending=True,
                safe=False,
                reason="PENDING_ORDER_REMAINING",
                source="manager_and_engine",
                manager_pending_order=manager_pending_order,
                engine_available=True,
                engine_pending_order=engine_pending_order,
            )

        return self._pending_order_authority_payload(
            known=True,
            pending=False,
            safe=True,
            reason="NO_PENDING_ORDER",
            source="manager_and_engine",
            manager_pending_order=manager_pending_order,
            engine_available=True,
            engine_pending_order=engine_pending_order,
        )

    def _stopped_paper_emergency_response(
        self,
        symbol,
        refresh_snapshot=False,
        operation_id=None,
    ):

        current_snapshot = self.account_snapshot
        if (
            isinstance(current_snapshot, dict)
            and current_snapshot.get("authorityReason")
            == "STOPPED_PAPER_DURABLE_EVIDENCE_REBOUND"
        ):
            rebound_evidence = (
                self._stopped_paper_shutdown_evidence_state(
                    current_snapshot
                )
            )
            if rebound_evidence.get("valid") is not True:
                return self._stopped_paper_unknown_response(
                    symbol,
                    rebound_evidence.get("reason")
                    or "SNAPSHOT_EVIDENCE_IDENTITY_INVALID",
                )

        stopped_state = (
            self._stopped_paper_authoritative_safety_state(
                refresh_snapshot=refresh_snapshot,
                operation_id=operation_id,
            )
        )

        if stopped_state.get("applies") is False:
            return None

        if stopped_state.get("position_state") is None:
            mode_reason = stopped_state.get("reason")
            return self._stopped_paper_unknown_response(
                symbol,
                mode_reason or "STATE_UNKNOWN",
                execution_path=(
                    None
                    if mode_reason in {
                        "MODE_UNKNOWN",
                        "MODE_CONFLICT",
                        "LIVE_MODE",
                    }
                    else "paper"
                ),
            )

        position_state = stopped_state.get("position_state")
        pending_order_state = stopped_state.get("pending_order_state")
        open_order_state = stopped_state.get("open_order_state")

        if position_state == "unknown":
            return self._stopped_paper_unknown_response(
                symbol,
                "POSITION_STATE_UNKNOWN",
            )

        if pending_order_state == "unknown":
            return self._stopped_paper_unknown_response(
                symbol,
                "PENDING_ORDER_UNKNOWN",
            )

        if open_order_state == "unknown":
            return self._stopped_paper_unknown_response(
                symbol,
                stopped_state.get("reason") or "OPEN_ORDER_UNKNOWN",
            )

        position_remaining = position_state == "remaining"
        pending_order = pending_order_state == "remaining"
        open_order_remaining = open_order_state == "remaining"

        cancel_not_required = self._emergency_not_required_result(
            "cancel"
        )
        flatten_not_required = self._emergency_not_required_result(
            "flatten"
        )

        if position_remaining:
            return self._emergency_response(
                success=False,
                completed=False,
                partial=True,
                state_unknown=False,
                execution_path="paper",
                symbol=symbol,
                cancel=cancel_not_required,
                flatten={
                    "success": False,
                    "completed": False,
                    "status": "NOT_RUN",
                    "reason": "POSITION_REMAINING_WITHOUT_ENGINE",
                    "position_remaining": True,
                },
                position_remaining=True,
                retryable=True,
                error_code="POSITION_REMAINING",
            )

        if pending_order:
            return self._emergency_response(
                success=False,
                completed=False,
                partial=True,
                state_unknown=False,
                execution_path="paper",
                symbol=symbol,
                cancel={
                    "success": False,
                    "completed": False,
                    "status": "NOT_RUN",
                    "reason": "PENDING_ORDER_REMAINING_WITHOUT_ENGINE",
                    "requested": None,
                    "cancelled": None,
                    "failed": None,
                },
                flatten=flatten_not_required,
                position_remaining=False,
                retryable=True,
                error_code="PENDING_ORDER_REMAINING",
            )

        if open_order_remaining:
            return self._emergency_response(
                success=False,
                completed=False,
                partial=True,
                state_unknown=False,
                execution_path="paper",
                symbol=symbol,
                cancel={
                    "success": False,
                    "completed": False,
                    "status": "NOT_RUN",
                    "reason": "OPEN_ORDER_REMAINING_WITHOUT_ENGINE",
                    "requested": None,
                    "cancelled": None,
                    "failed": None,
                },
                flatten=flatten_not_required,
                position_remaining=False,
                retryable=True,
                error_code=(
                    stopped_state.get("reason")
                    or "OPEN_ORDER_REMAINING"
                ),
            )

        return self._emergency_response(
            success=True,
            completed=True,
            partial=False,
            state_unknown=False,
            execution_path="paper",
            symbol=symbol,
            cancel=cancel_not_required,
            flatten=flatten_not_required,
            position_remaining=False,
            retryable=False,
        )

    def _emergency_symbol(self, engine):

        symbol = (
            self.orderbook_symbol
            or self.symbol
            or (
                self.config.get("symbol")
                if isinstance(self.config, dict)
                else None
            )
            or (
                getattr(engine, "symbol", None)
                if engine is not None
                else None
            )
        )

        symbol = (
            str(symbol).strip()
            if symbol is not None
            else ""
        )

        return (
            symbol.upper()
            if symbol
            else None
        )

    @staticmethod
    def _emergency_error_code(result, fallback):

        if isinstance(result, dict):
            return (
                result.get("error_code")
                or result.get("error")
                or fallback
            )

        return fallback

    @staticmethod
    def _emergency_position_remaining(flatten_result):

        if not isinstance(flatten_result, dict):
            return None

        explicit_remaining = flatten_result.get("position_remaining")

        if explicit_remaining is True:
            return True

        if explicit_remaining is False:
            return False

        if flatten_result.get("error_code") == "POSITION_REMAINS":
            return True

        final_position = flatten_result.get("final_position")

        if (
            isinstance(final_position, dict)
            and final_position.get("success") is True
        ):
            if final_position.get("found") is True:
                return True
            if final_position.get("found") is False:
                return False

        if (
            flatten_result.get("success") is True
            and (
                flatten_result.get("confirmed") is True
                or flatten_result.get("closed") is True
                or flatten_result.get("skipped") is True
            )
        ):
            return False

        position_after = flatten_result.get("position_after")

        if position_after is not None:
            return True

        return None

    @staticmethod
    def _emergency_flatten_unconfirmed(flatten_result):

        return (
            isinstance(flatten_result, dict)
            and flatten_result.get("accepted") is True
            and flatten_result.get("confirmed") is not True
        )

    def _classify_live_emergency_result(
        self,
        symbol,
        cancel_result,
        flatten_result,
    ):

        cancel_completed = (
            isinstance(cancel_result, dict)
            and cancel_result.get("success") is True
        )
        flatten_completed = (
            isinstance(flatten_result, dict)
            and flatten_result.get("success") is True
        )
        position_remaining = self._emergency_position_remaining(
            flatten_result
        )
        flatten_unconfirmed = self._emergency_flatten_unconfirmed(
            flatten_result
        )

        position_unknown = position_remaining is None

        if (
            cancel_completed
            and flatten_completed
            and position_remaining is False
        ):
            return self._emergency_response(
                success=True,
                completed=True,
                partial=False,
                state_unknown=False,
                execution_path="live",
                symbol=symbol,
                cancel=cancel_result,
                flatten=flatten_result,
                position_remaining=False,
                retryable=False,
            )

        if (
            not cancel_completed
            and flatten_completed
            and position_remaining is False
        ):
            return self._emergency_response(
                success=False,
                completed=False,
                partial=True,
                state_unknown=False,
                execution_path="live",
                symbol=symbol,
                cancel=cancel_result,
                flatten=flatten_result,
                position_remaining=False,
                retryable=True,
                error_code="CANCEL_FAILED_FLATTEN_COMPLETED",
            )

        if position_remaining is True:
            return self._emergency_response(
                success=False,
                completed=False,
                partial=True,
                state_unknown=False,
                execution_path="live",
                symbol=symbol,
                cancel=cancel_result,
                flatten=flatten_result,
                position_remaining=True,
                retryable=True,
                error_code="POSITION_REMAINS",
            )

        if (
            position_unknown
            or flatten_unconfirmed
        ):
            error_code = (
                "CANCEL_AND_FLATTEN_FAILED"
                if not cancel_completed
                and not flatten_completed
                else self._emergency_error_code(
                    flatten_result,
                    "FLATTEN_FAILED",
                )
            )

            return self._emergency_response(
                success=False,
                completed=False,
                partial=True,
                state_unknown=True,
                execution_path="live",
                symbol=symbol,
                cancel=cancel_result,
                flatten=flatten_result,
                position_remaining=position_remaining,
                retryable=True,
                error_code=error_code,
            )

        error_code = (
            "CANCEL_AND_FLATTEN_FAILED"
            if not cancel_completed
            else self._emergency_error_code(
                flatten_result,
                "FLATTEN_FAILED",
            )
        )

        return self._emergency_response(
            success=False,
            completed=False,
            partial=True,
            state_unknown=False,
            execution_path="live",
            symbol=symbol,
            cancel=cancel_result,
            flatten=flatten_result,
            position_remaining=position_remaining,
            retryable=True,
            error_code=error_code,
        )

    def _emergency_already_running_response(self):

        return self._emergency_response(
            success=False,
            completed=False,
            partial=False,
            state_unknown=False,
            execution_path=None,
            symbol=None,
            cancel=None,
            flatten=None,
            position_remaining=None,
            retryable=True,
            error_code="EMERGENCY_ALREADY_RUNNING",
        )

    @staticmethod
    def _emergency_retry_block_reason(state):

        if state == EMERGENCY_ACTION_REQUIRED:
            return None

        if state == EMERGENCY_PROCESSING:
            return "PROCESSING"

        if state == EMERGENCY_LOCKED:
            return "ALREADY_LOCKED"

        if state == EMERGENCY_READY:
            return "NOT_ACTION_REQUIRED"

        if state is None:
            return "STATE_MISSING"

        return "INVALID_STATE"

    @staticmethod
    def _emergency_retry_rejected_response(reason):

        return {
            "success": False,
            "retry": False,
            "retry_rejected": True,
            "reason": reason,
            "error_code": reason,
            "emergency": build_emergency_status(),
        }

    def run_emergency_orchestrator(self):

        acquired = self.emergency_orchestrator_lock.acquire(
            blocking=False
        )

        if not acquired:
            return self._emergency_already_running_response()

        operation = None

        try:
            governance_state["emergency_stop"] = True
            governance_state["execution_enabled"] = False
            operation = begin_emergency_operation()

            return self._run_emergency_orchestrator_locked(
                operation
            )

        except Exception:
            response = self._emergency_response(
                success=False,
                completed=False,
                partial=False,
                state_unknown=True,
                execution_path=None,
                retryable=True,
                error_code="ORCHESTRATOR_EXCEPTION",
            )

            if operation is not None:
                complete_emergency_operation(
                    response,
                    operation,
                )
                self.stop()

            return response

        finally:
            self.emergency_orchestrator_lock.release()

    def retry_emergency_orchestrator(self):

        acquired = self.emergency_orchestrator_lock.acquire(
            blocking=False
        )

        if not acquired:
            return self._emergency_retry_rejected_response(
                "PROCESSING"
            )

        operation = None

        try:
            state = governance_state.get("emergency_state")
            reason = self._emergency_retry_block_reason(state)

            if reason is not None:
                return self._emergency_retry_rejected_response(
                    reason
                )

            if governance_state.get("emergency_stop") is not True:
                return self._emergency_retry_rejected_response(
                    "NOT_ACTION_REQUIRED"
                )

            if governance_state.get("execution_enabled") is not False:
                return self._emergency_retry_rejected_response(
                    "EXECUTION_ENABLED"
                )

            operation = begin_emergency_operation()
            operation["recheck"] = True

            return self._run_emergency_orchestrator_locked(
                operation
            )

        except Exception:
            response = self._emergency_response(
                success=False,
                completed=False,
                partial=False,
                state_unknown=True,
                execution_path=None,
                retryable=True,
                error_code="ORCHESTRATOR_EXCEPTION",
            )

            if operation is not None:
                complete_emergency_operation(
                    response,
                    operation,
                )
                self.stop()

                return response

            return self._emergency_retry_rejected_response(
                "RETRY_EXCEPTION"
            )

        finally:
            self.emergency_orchestrator_lock.release()

    def _run_emergency_orchestrator_locked(self, operation):

        def finalize(response):
            proposed_success = (
                isinstance(response, dict)
                and response.get("success") is True
                and response.get("completed") is True
                and response.get("state_unknown") is False
            )
            engine_was_present = engine is not None
            stop_result = (
                self.stop()
                if engine_was_present
                else {
                    "status": "stopped",
                    "reason": "ENGINE_STOPPED",
                    "success": True,
                    "completed": True,
                    "stateUnknown": False,
                }
            )

            failure_reason = None
            if (
                not isinstance(stop_result, dict)
                or stop_result.get("status") != "stopped"
                or stop_result.get("success") is not True
                or stop_result.get("completed") is not True
                or stop_result.get("stateUnknown") is not False
                or stop_result.get("reason") != "ENGINE_STOPPED"
            ):
                failure_reason = (
                    stop_result.get("reason")
                    if isinstance(stop_result, dict)
                    else None
                ) or "ENGINE_STOP_RESULT_INVALID"
            elif self.engine is not None:
                failure_reason = "ENGINE_STILL_ATTACHED"
            else:
                from backend.routers import positions as positions_router

                if positions_router.engine is not None:
                    failure_reason = "ENGINE_REGISTRY_STILL_ATTACHED"
                elif (
                    runtime_registry.trading_runtime
                    and runtime_registry.trading_runtime
                    .execution_runtime.engine is not None
                ):
                    failure_reason = "ENGINE_REGISTRY_STILL_ATTACHED"

            if failure_reason is None and proposed_success:
                if (
                    isinstance(self.account_snapshot, dict)
                    and self.account_snapshot.get("stateUnknown") is True
                ):
                    failure_reason = "FINAL_STATE_UNKNOWN"

                path = response.get("execution_path") or response.get("path")
                if failure_reason is None and path == "paper":
                    final_authority = (
                        self._stopped_paper_shutdown_evidence_state(
                            self.account_snapshot
                        )
                    )
                    if final_authority.get("valid") is not True:
                        failure_reason = (
                            final_authority.get("reason")
                            or "FINAL_SNAPSHOT_INVALID"
                        )
                    elif (
                        final_authority.get("position_state") != "flat"
                        or final_authority.get("pending_order_state") != "flat"
                        or final_authority.get("open_order_state") != "flat"
                    ):
                        failure_reason = "FINAL_SNAPSHOT_NOT_FLAT"

            if failure_reason is not None:
                response = self._emergency_response(
                    success=False,
                    completed=False,
                    partial=True,
                    state_unknown=True,
                    execution_path=(
                        response.get("execution_path")
                        if isinstance(response, dict)
                        else None
                    ),
                    symbol=(
                        response.get("symbol")
                        if isinstance(response, dict)
                        else None
                    ),
                    cancel=(
                        response.get("cancel")
                        if isinstance(response, dict)
                        else None
                    ),
                    flatten=(
                        response.get("flatten")
                        if isinstance(response, dict)
                        else None
                    ),
                    position_remaining=(
                        response.get("position_remaining")
                        if isinstance(response, dict)
                        else None
                    ),
                    retryable=True,
                    error_code=failure_reason,
                )

            complete_emergency_operation(
                response,
                operation,
            )

            return response

        try:
            engine = self.engine
            engine_mode = (
                str(getattr(engine, "mode", "") or "")
                .strip()
                .lower()
                if engine is not None
                else None
            )
            exchange = (
                getattr(engine, "exchange", None)
                if engine is not None
                else None
            )
            symbol = self._emergency_symbol(engine)
            live_readiness = {}

            if (
                engine is not None
                and hasattr(engine, "build_live_readiness")
            ):
                try:
                    readiness = engine.build_live_readiness()
                    if isinstance(readiness, dict):
                        live_readiness = readiness
                except Exception:
                    live_readiness = {}

            live_allowed_before_lock = (
                live_readiness.get("realOrderAllowed") is True
            )

            if governance_state.get("execution_enabled") is not False:
                return finalize(self._emergency_response(
                    success=False,
                    completed=False,
                    partial=False,
                    state_unknown=True,
                    execution_path=None,
                    symbol=symbol,
                    retryable=True,
                    error_code="AUTO_TRADE_DISABLE_FAILED",
                ))

            if engine is None:
                stopped_response = (
                    self._stopped_paper_emergency_response(
                        symbol,
                        refresh_snapshot=(
                            operation.get("recheck") is True
                        ),
                        operation_id=operation.get("operation_id"),
                    )
                )

                if stopped_response is not None:
                    return finalize(stopped_response)

                return finalize(self._emergency_response(
                    success=False,
                    completed=False,
                    partial=False,
                    state_unknown=True,
                    execution_path=None,
                    symbol=None,
                    retryable=True,
                    error_code="ENGINE_UNAVAILABLE",
                ))

            if engine_mode == "paper":
                try:
                    flatten_result = engine.flatten_paper_position(
                        reason="EMERGENCY_FLATTEN"
                    )
                except Exception as e:
                    flatten_result = {
                        "success": False,
                        "error": str(e),
                    }

                flatten_completed = (
                    isinstance(flatten_result, dict)
                    and flatten_result.get("success") is True
                )
                position_remaining = self._emergency_position_remaining(
                    flatten_result
                )

                if flatten_completed:
                    return finalize(self._emergency_response(
                        success=True,
                        completed=True,
                        partial=False,
                        state_unknown=False,
                        execution_path="paper",
                        symbol=symbol,
                        flatten=flatten_result,
                        position_remaining=False,
                        retryable=False,
                    ))

                return finalize(self._emergency_response(
                    success=False,
                    completed=False,
                    partial=True,
                    state_unknown=position_remaining is None,
                    execution_path="paper",
                    symbol=symbol,
                    flatten=flatten_result,
                    position_remaining=position_remaining,
                    retryable=True,
                    error_code=self._emergency_error_code(
                        flatten_result,
                        "PAPER_FLATTEN_FAILED",
                    ),
                ))

            if live_allowed_before_lock and exchange is not None:
                try:
                    cancel_result = exchange.cancel_all_orders(
                        symbol
                    )
                except Exception as e:
                    cancel_result = {
                        "success": False,
                        "error": str(e),
                    }

                try:
                    flatten_result = exchange.flatten_current_position(
                        symbol
                    )
                except Exception as e:
                    flatten_result = {
                        "success": False,
                        "error_code": "FLATTEN_EXCEPTION",
                        "error": str(e),
                    }

                return finalize(self._classify_live_emergency_result(
                    symbol,
                    cancel_result,
                    flatten_result,
                ))

            return finalize(self._emergency_response(
                success=False,
                completed=False,
                partial=False,
                state_unknown=True,
                execution_path=None,
                symbol=symbol,
                retryable=True,
                error_code="EXECUTION_PATH_UNAVAILABLE",
            ))

        except Exception:
            return finalize(self._emergency_response(
                success=False,
                completed=False,
                partial=False,
                state_unknown=True,
                execution_path=None,
                retryable=True,
                error_code="ORCHESTRATOR_EXCEPTION",
            ))

    def stop(self):

        with self.shutdown_lock:
            return self._stop_locked()

    def _stop_locked(self):

        engine = self.engine

        self._set_lifecycle_state(
            "STOPPING"
        )

        add_log(
            "🛑 BOT STOP"
        )

        self._running = False

        governance_state["execution_enabled"] = False

        # Invalidate callbacks from the old exchange WebSocket immediately.
        self.active_runtime_id = None

        cleanup_failures = []

        try:

            if self.ws:
                try:
                    self.ws.stop()
                    time.sleep(1)
                    self.ws = None
                except Exception:
                    cleanup_failures.append("WEBSOCKET_STOP_FAILED")

            runtime_metrics = (
                self.state.runtime_metrics
            )

            if "WEBSOCKET_STOP_FAILED" not in cleanup_failures:
                runtime_metrics[
                    "ws_connected"
                ] = False

                runtime_metrics[
                    "ws_thread_alive"
                ] = False

            runtime_metrics[
                "market_ready"
            ] = False

            self.strategy = None

            self.ob_manager = None

            # Capture the last backend-owned values before removing the
            # engine.  /api/bot/status and /ws continue serving this snapshot
            # while execution is stopped.
            self._capture_account_snapshot()

            engine_mode = self._normalize_emergency_mode(
                getattr(engine, "mode", None)
            ) if engine is not None else None

            if engine is not None and engine_mode == "paper":
                preserved = (
                    self._preserve_stopped_paper_engine_safety_snapshot()
                )
                if preserved is None:
                    reason = (
                        self.account_snapshot.get("authorityReason")
                        if isinstance(self.account_snapshot, dict)
                        else None
                    ) or "SNAPSHOT_PERSIST_FAILED"
                    return {
                        "status": "error",
                        "reason": reason,
                        "success": False,
                        "completed": False,
                        "stateUnknown": True,
                    }

            if engine is not None:
                try:
                    engine_stop_result = engine.stop()
                except Exception:
                    engine_stop_result = None

                engine_stopped = (
                    isinstance(engine_stop_result, dict)
                    and engine_stop_result.get("status") == "stopped"
                )
                if engine_stopped is not True:
                    if engine_mode == "paper":
                        self._invalidate_stopped_paper_durable_snapshot(
                            "ENGINE_STOP_FAILED"
                        )
                    self.account_snapshot = (
                        self._stopped_paper_unknown_snapshot(
                            self.account_snapshot,
                            "ENGINE_STOP_FAILED",
                        )
                    )
                    self._set_lifecycle_state("STOPPING")
                    add_log("ENGINE_STOP_FAILED", "error")
                    return {
                        "status": "error",
                        "reason": "ENGINE_STOP_FAILED",
                        "success": False,
                        "completed": False,
                        "stateUnknown": True,
                    }

            positions_router = None
            try:
                from backend.routers import positions as positions_router
            except Exception:
                cleanup_failures.append(
                    "POSITIONS_REGISTRY_STATE_UNKNOWN"
                )

            if positions_router is not None:
                try:
                    positions_router.set_engine(None)
                except Exception:
                    cleanup_failures.append(
                        "POSITIONS_REGISTRY_DETACH_FAILED"
                    )

            execution_runtime = None
            try:
                trading_runtime = runtime_registry.trading_runtime
                execution_runtime = (
                    trading_runtime.execution_runtime
                    if trading_runtime is not None
                    else None
                )
                if execution_runtime is not None:
                    execution_runtime.set_engine(None)
            except Exception:
                cleanup_failures.append(
                    "EXECUTION_REGISTRY_DETACH_FAILED"
                )

            try:
                positions_engine = (
                    positions_router.engine
                    if positions_router is not None
                    else engine
                )
            except Exception:
                positions_engine = engine
                cleanup_failures.append(
                    "POSITIONS_REGISTRY_STATE_UNKNOWN"
                )

            try:
                execution_engine = (
                    execution_runtime.engine
                    if execution_runtime is not None
                    else None
                )
            except Exception:
                execution_engine = engine
                cleanup_failures.append(
                    "EXECUTION_REGISTRY_STATE_UNKNOWN"
                )

            if positions_engine is not None:
                cleanup_failures.append(
                    "ENGINE_REGISTRY_STILL_ATTACHED"
                )
            if execution_engine is not None:
                cleanup_failures.append(
                    "ENGINE_REGISTRY_STILL_ATTACHED"
                )

            if (
                positions_engine is None
                and execution_engine is None
            ):
                self.engine = None

            self._running = False

            if (
                cleanup_failures
                or self.ws is not None
                or self.engine is not None
                or positions_engine is not None
                or execution_engine is not None
                or self._running is not False
            ):
                self._set_lifecycle_state("STOPPING")
                return {
                    "status": "error",
                    "reason": cleanup_failures[0]
                    if cleanup_failures
                    else "STOP_RESIDUAL_STATE",
                    "success": False,
                    "completed": False,
                    "stateUnknown": True,
                }

            self._set_lifecycle_state(
                "STOPPED"
            )

            self.position = "NONE"

            self.entry_price = None

            self.last_signal = None

            self.last_price = 0

            self.market_ready = False

            self.last_update_time = 0

            self.pending_order = False

            self.exchange_client_ready = False

            self.balance_check_ok = False

            self.position_check_ok = False

            add_log(
                "🛑 BOT STOPPED"
            )

            return {
                "status": "stopped",
                "reason": "ENGINE_STOPPED",
                "success": True,
                "completed": True,
                "stateUnknown": False,
            }

        except Exception as e:

            self._set_lifecycle_state(
                "STOPPING"
            )

            add_log(
                f"❌ STOP ERROR: "
                f"{e}"
            )

            return {
                "status": "error",
                "reason": str(e),
                "success": False,
                "completed": False,
                "stateUnknown": True,
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

        pending_order_state = (
            self.get_authoritative_pending_order_state()
        )
        pending_order_status_state = (
            self._pending_order_status_state(pending_order_state)
        )
        pending_order = (
            pending_order_state.get("pending_order") is True
        )

        pnl = float(snapshot.get("pnl") or 0.0)

        balance = float(snapshot.get("balance") or 0.0)

        equity = float(snapshot.get("equity") or balance)

        available_balance = float(
            snapshot.get("availableBalance") or balance
        )

        completed_runtime_result = deepcopy(
            self.latest_runtime_result
        )

        if self._running and isinstance(
            completed_runtime_result,
            dict,
        ):
            self.attach_orderbook_runtime_debug(
                completed_runtime_result
            )

        latest_runtime_trace = (
            completed_runtime_result
            if self._running and isinstance(completed_runtime_result, dict)
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
        loop_enabled = bool(
            self._running
            and self.lifecycle_state == "RUNNING"
        )
        auto_trade_enabled = bool(
            governance_state.get(
                "execution_enabled",
                False,
            )
        )
        emergency_locked = bool(
            governance_state.get(
                "emergency_stop",
                False,
            )
        )
        emergency_state = (
            "LOCKED"
            if emergency_locked
            else "UNLOCKED"
        )
        emergency_status = build_emergency_status()

        runtime_health = build_runtime_health_snapshot(
            running=self._running,
            market_stale=market_stale,
            exchange_ws_connected=websocket_connected,
            browser_ws_connected=self.browser_ws_clients > 0,
            browser_ws_clients=self.browser_ws_clients,
            engine_available=self.engine is not None,
            runtime_healthy=runtime_healthy,
            runtime_result=(
                completed_runtime_result
                if isinstance(completed_runtime_result, dict)
                else {}
            ),
            runtime_trace=self.state.runtime_trace,
            runtime_metrics=self.state.runtime_metrics,
            governance_state=governance_state,
            snapshot_timestamp=(
                self.state.runtime_metrics.get("last_bot_update")
                or time.time()
            ),
            lifecycle_revision=self.lifecycle_revision,
            lifecycle_state=self.lifecycle_state,
            cycle_id=(
                f"{self.session_id}:{self.update_id}"
            ),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        runtime_states = runtime_health["states"]

        if self.engine:

            actual_position = getattr(
                self.engine,
                "actual_position",
                None
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

        dry_run = bool(
            self.config.get("dry_run", True)
        )

        selected_mode = str(
            self.config.get("mode", "paper")
        ).strip().upper()

        live_readiness = self._build_live_readiness_snapshot(
            selected_mode,
            dry_run,
        )

        real_order_allowed = bool(
            live_readiness.get("realOrderAllowed", False)
        )

        execution_mode = (
            "LIVE"
            if real_order_allowed
            else "SIMULATION"
        )

        safety_reasons = []

        if selected_mode == "LIVE" and not real_order_allowed:
            safety_reasons.append("LIVE_NOT_ENABLED")

        if dry_run:
            safety_reasons.append("DRY_RUN_ACTIVE")

        if not safety_reasons and not real_order_allowed:
            safety_reasons.append("LIVE_NOT_ENABLED")

        safety_reason = " / ".join(safety_reasons) or "NONE"

        engine_config = self._effective_engine_config()

        risk_config = {
            "risk_percent": engine_config.get("risk_percent"),
            "position_size": engine_config.get("position_size"),
            "max_drawdown_pct": engine_config.get(
                "max_drawdown_pct"
            ),
            "tp_percent": engine_config.get("tp_percent"),
            "sl_percent": engine_config.get("sl_percent"),
            "trailing_stop": engine_config.get("trailing_stop"),
            "trailing_stop_distance_percent": engine_config.get(
                "trailing_stop_distance_percent"
            ),
        }

        risk_state = (
            self.engine.get_risk_state()
            if self.engine
            and hasattr(self.engine, "get_risk_state")
            else {}
        )

        trade_settings = self._build_trade_settings_snapshot(
            engine_config,
            selected_mode,
            dry_run,
            execution_mode,
            real_order_allowed,
        )
        account_runtime = self._build_account_runtime(
            snapshot,
            live_readiness,
            selected_mode,
            dry_run,
            execution_mode,
            real_order_allowed,
        )
        account_status_fields = (
            self._flatten_account_runtime_fields(
                account_runtime,
                live_readiness,
            )
        )

        status_payload = {

            "timestamp": time.time(),

            "last_update": snapshot.get("last_update") or 0.0,

            "price": safe_price,

            "marketReady": self.market_ready,

            "marketStale": market_stale,

            "lastUpdateAge": stale_seconds,

            "pnl": pnl,

            "balance": balance,

            "equity": equity,

            "availableBalance": available_balance,

            "available_balance": available_balance,

            "risk_percent": risk_config.get(
                "risk_percent"
            ),

            "leverage": trade_settings.get(
                "leverage"
            ),

            "timeframe": trade_settings.get(
                "timeframe"
            ),

            "position_size": risk_config.get(
                "position_size"
            ),

            "positionSize": risk_config.get(
                "position_size"
            ),

            "max_drawdown_pct": risk_config.get(
                "max_drawdown_pct"
            ),

            "maxDd": risk_config.get(
                "max_drawdown_pct"
            ),

            "tp_percent": risk_config.get(
                "tp_percent"
            ),

            "sl_percent": risk_config.get(
                "sl_percent"
            ),

            "trailing_stop": risk_config.get(
                "trailing_stop"
            ),

            "trailingStop": risk_config.get(
                "trailing_stop"
            ),

            "current_drawdown_pct": risk_state.get(
                "currentDrawdownPct"
            ),

            "risk_block_reason": risk_state.get(
                "riskBlockReason"
            ),

            "risk_config": risk_config,

            "risk_state": risk_state,

            "trade_settings": trade_settings,

            "tradeSettings": trade_settings,

            "liveReadiness": live_readiness,

            "liveBlockReasons": live_readiness.get(
                "blockReasons",
                [],
            ),

            "exchangeClientReady": live_readiness.get(
                "exchangeClientReady",
                False,
            ),

            "exchangeAuthReady": live_readiness.get(
                "exchangeAuthReady",
                False,
            ),

            "balanceCheckOk": live_readiness.get(
                "balanceCheckOk",
                False,
            ),

            "positionCheckOk": live_readiness.get(
                "positionCheckOk",
                False,
            ),

            "executionEnabled": live_readiness.get(
                "executionEnabled",
                False,
            ),

            "loopEnabled": loop_enabled,

            "loopState": self.lifecycle_state,

            "autoTradeEnabled": auto_trade_enabled,

            "emergencyStop": live_readiness.get(
                "emergencyStop",
                False,
            ),

            "emergencyLocked": emergency_locked,

            "emergencyState": emergency_state,

            "emergency": emergency_status,

            "real_qty": risk_state.get(
                "realQty"
            ),

            "notional": risk_state.get(
                "notional"
            ),

            "active_position_qty": risk_state.get(
                "activePositionQty"
            ),

            "active_position_contract_qty": risk_state.get(
                "activePositionContractQty"
            ),

            "active_position_notional": risk_state.get(
                "activePositionNotional"
            ),

            "active_position_entry_notional": risk_state.get(
                "activePositionEntryNotional"
            ),

            "position": actual_position,

            "actual_position": actual_position,

            "pendingOrder": pending_order,

            "pendingOrderState": pending_order_status_state,

            "pending_order_state": deepcopy(pending_order_state),

            "signal": self.last_signal,

            "latestRuntimeResult": latest_runtime_trace or None,

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

            # Real account fields are populated only after read-only KuCoin
            # checks succeed.  Secrets are never included in this snapshot.
            "accountSource": live_readiness.get(
                "accountSource",
                "PAPER_SIMULATION",
            ),

            "balanceSource": live_readiness.get(
                "balanceSource",
                "PAPER_SIMULATION",
            ),

            "positionSource": live_readiness.get(
                "positionSource",
                "PAPER_SIMULATION",
            ),

            "accountSourceReason": live_readiness.get(
                "accountSourceReason"
            ),

            "balanceSourceReason": live_readiness.get(
                "balanceSourceReason"
            ),

            "positionSourceReason": live_readiness.get(
                "positionSourceReason"
            ),

            "realOrderAllowed": real_order_allowed,

            "executionMode": execution_mode,

            "dryRun": dry_run,

            "selectedMode": selected_mode,

            "safetyReason": safety_reason,

            "exchangeAuth": (
                "VERIFIED"
                if live_readiness.get("exchangeAuthReady")
                else "NOT_VERIFIED"
            ),

            "exchangeConnection": live_readiness.get(
                "exchangeConnection",
                "NOT_CONNECTED",
            ),

            "apiKeyStatus": live_readiness.get(
                "apiKeyStatus",
                "MISSING",
            ),

            "permission": live_readiness.get(
                "permission",
                "NOT_VERIFIED",
            ),

            "accountType": live_readiness.get(
                "accountType",
                "UNKNOWN",
            ),

            "exchangeAuthReason": live_readiness.get(
                "exchangeAuthReason"
            ),

            "exchangeConnectionReason": live_readiness.get(
                "exchangeConnectionReason"
            ),

            "accountReason": live_readiness.get(
                "accountReason"
            ),

            "balanceReason": live_readiness.get(
                "balanceReason"
            ),

            "positionReason": live_readiness.get(
                "positionReason"
            ),

            "realAccountConnected": bool(
                live_readiness.get("balanceCheckOk")
                or live_readiness.get("positionCheckOk")
            ),

            "realBalance": (
                live_readiness.get("realBalance")
                if live_readiness.get("realBalance") is not None
                else balance
                if live_readiness.get("balanceCheckOk")
                else None
            ),

            "realEquity": (
                live_readiness.get("realEquity")
                if live_readiness.get("realEquity") is not None
                else equity
                if live_readiness.get("balanceCheckOk")
                else None
            ),

            "realAvailableBalance": (
                live_readiness.get("realAvailableBalance")
                if live_readiness.get("realAvailableBalance") is not None
                else available_balance
                if live_readiness.get("balanceCheckOk")
                else None
            ),

            "realPosition": (
                live_readiness.get("realPosition")
                if live_readiness.get("realPosition") is not None
                else actual_position
                if live_readiness.get("positionCheckOk")
                else None
            ),

            "realPositionState": (
                live_readiness.get("realPositionState")
                or (
                    "OPEN"
                    if actual_position
                    else (
                        "NO_OPEN_POSITION"
                        if live_readiness.get("positionCheckOk")
                        else "NOT_SYNCED"
                    )
                )
            ),

            "realAccountLastSync": (
                live_readiness.get("realAccountLastSync")
                or (
                    snapshot.get("last_update")
                    if (
                        live_readiness.get("balanceCheckOk")
                        or live_readiness.get("positionCheckOk")
                    )
                    else None
                )
            ),

            "realLastSync": (
                live_readiness.get("realAccountLastSync")
                or (
                    snapshot.get("last_update")
                    if (
                        live_readiness.get("balanceCheckOk")
                        or live_readiness.get("positionCheckOk")
                    )
                    else None
                )
            ),

            "allowLive": backend_config.ALLOW_LIVE,

            "tradeMode": backend_config.TRADE_MODE,

            # Keep legacy names aligned for existing API consumers.
            "execution_mode": execution_mode,

            "real_order_allowed": real_order_allowed,

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

        status_payload.update(account_status_fields)

        return status_payload

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


def get_existing_bot_manager():

    return _bot_manager
