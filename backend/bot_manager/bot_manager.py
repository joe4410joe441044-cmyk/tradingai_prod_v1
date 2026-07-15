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

            self.stop()

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

            self._running = False

            self._set_lifecycle_state(
                "STOPPED"
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

    def _stopped_paper_pending_order_state(self):

        if not hasattr(self, "pending_order"):
            return "unknown"

        pending_order = self.pending_order

        if type(pending_order) is not bool:
            return "unknown"

        if pending_order:
            return "remaining"

        return "flat"

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
        }

    def _stopped_paper_authoritative_safety_state(self):

        state = {
            "applies": True,
            "safe": False,
            "reason": None,
            "snapshot": None,
            "snapshot_timestamp_state": None,
            "position_state": None,
            "pending_order_state": None,
        }

        def unknown(reason):
            result = dict(state)
            result["reason"] = reason
            return result

        if not isinstance(self.config, dict):
            return unknown("MODE_UNKNOWN")

        if "mode" not in self.config:
            return unknown("MODE_UNKNOWN")

        raw_mode = self.config.get("mode")

        if raw_mode is None:
            return unknown("MODE_UNKNOWN")

        selected_mode = str(raw_mode).strip().lower()

        if selected_mode == "live":
            result = unknown("LIVE_MODE")
            result["applies"] = False
            return result

        if selected_mode != "paper":
            return unknown("MODE_UNKNOWN")

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

        if snapshot.get("available") is not True:
            result = unknown("SNAPSHOT_NOT_SYNCED")
            result["snapshot"] = snapshot
            return result

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
            return result

        position_state = self._stopped_paper_position_state(snapshot)
        pending_order_state = self._stopped_paper_pending_order_state()

        result = dict(state)
        result["snapshot"] = snapshot
        result["snapshot_timestamp_state"] = timestamp_state
        result["position_state"] = position_state
        result["pending_order_state"] = pending_order_state

        if position_state == "unknown":
            result["reason"] = "POSITION_STATE_UNKNOWN"
            return result

        if pending_order_state == "unknown":
            result["reason"] = "PENDING_ORDER_UNKNOWN"
            return result

        result["position_remaining"] = position_state == "remaining"
        result["pending_order"] = pending_order_state == "remaining"

        if result["position_remaining"]:
            result["reason"] = "POSITION_REMAINING"
            return result

        if result["pending_order"]:
            result["reason"] = "PENDING_ORDER_REMAINING"
            return result

        result["safe"] = True
        result["reason"] = "STOPPED_PAPER_AUTHORITATIVE_SAFE"
        return result

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

    def _stopped_paper_emergency_response(self, symbol):

        stopped_state = (
            self._stopped_paper_authoritative_safety_state()
        )

        if stopped_state.get("applies") is False:
            return None

        if stopped_state.get("position_state") is None:
            return self._stopped_paper_unknown_response(
                symbol,
                stopped_state.get("reason", "STATE_UNKNOWN"),
                execution_path=(
                    None
                    if stopped_state.get("reason") == "MODE_UNKNOWN"
                    else "paper"
                ),
            )

        position_state = stopped_state.get("position_state")
        pending_order_state = stopped_state.get("pending_order_state")

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

        position_remaining = position_state == "remaining"
        pending_order = pending_order_state == "remaining"

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
            complete_emergency_operation(
                response,
                operation,
            )
            self.stop()

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
                        symbol
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
                "status": "stopped"
            }

        except Exception as e:

            self._set_lifecycle_state(
                "STOPPED"
            )

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
