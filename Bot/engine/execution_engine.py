# -*- coding: utf-8 -*-

from backend.utils.order import place_paper_order as place_order_safe
from backend.runtime.governance_runtime import governance_state
from backend.utils.log_buffer import (
    add_log,
    logger as app_logger,
    runtime_debug,
    ws_debug,
)
from backend.money_management.loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionOperation,
)
from backend.money_management.loss_execution_integration import (
    LossExecutionAdmissionResult,
    LossExecutionIntent,
)

from backend.money_management.order_sizing import OrderSizingAuthority, SizingRejected, number
from backend.money_management.models import MoneyManagementConfig

import backend.config as backend_config
import copy
import math
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal


LIVE_POSITION_PROTECTION_UNAVAILABLE = "LIVE_POSITION_PROTECTION_UNAVAILABLE"
LIVE_POSITION_PROTECTION_SOURCE = "LIVE_POSITION_PROTECTION_AUTHORITY"
# A confirmed LIVE close whose local PnL could not be computed (no authoritative
# contract multiplier).  Local balance/PnL/drawdown are then unknown, not 0.
LIVE_PNL_ACCOUNTING_UNAVAILABLE = "LIVE_PNL_ACCOUNTING_UNAVAILABLE"


def _positive_finite(value):
    """Return ``value`` as a positive finite float, otherwise ``None``.

    Used to distinguish "a valid level/multiplier at X" from "unavailable";
    missing, zero, negative, NaN, infinite and boolean inputs are unavailable.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number_value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number_value) or number_value <= 0:
        return None
    return number_value


def adjust_qty_to_step(qty, step_size):
    if step_size <= 0:
        return qty

    return math.floor(qty / step_size) * step_size


class ExecutionEngine:

    # Match BotRuntimeState's existing two-second reconciliation cadence.  A
    # normal LIVE close gets three read-only follow-up observations after the
    # exchange adapter's immediate post-submit position check.
    LIVE_CLOSE_RECONCILIATION_ATTEMPTS = 3
    LIVE_CLOSE_RECONCILIATION_INTERVAL_SECONDS = 2
    LIVE_CLOSE_EVIDENCE_MAX_AGE_SECONDS = 30

    def __init__(
        self,
        exchange=None,
        logger=None,
        portfolio=None,
        notifier=None,
        price_manager=None
    ):

        self._sizing_account_cache = None
        self._sizing_contract_cache = None
        self.sizing_policy_provider = None
        self.sizing_contract_provider = None
        self.exchange = exchange
        self.logger = logger or app_logger
        self.portfolio = portfolio
        self.notifier = notifier
        self.price_manager = price_manager

        self.pnl = 0

        self.balance = (
            portfolio.initial_balance
            if portfolio
            else 0
        )

        self.symbol = None

        self.engine_id = id(self)

        self.ws_client = None

        self.status = "STOPPED"

        self.mode = "paper"

        # =====================================
        # EXECUTION AUTHORITY STATE
        # =====================================

        # legacy (段階移行用)
        self.position = None

        # actual execution state
        self.actual_position = None

        # realtime price state
        self.latest_price = 0

        # realtime pnl state
        self.unrealized_pnl = 0
        # False when a LIVE position has no authoritative contract multiplier:
        # unrealized PnL is then unavailable (reported as 0.0, never estimated).
        self.unrealized_pnl_available = True
        # Set (dict) after a confirmed LIVE close whose PnL was unavailable.
        # While set, local balance/PnL are not authoritative: drawdown is not
        # recomputed from them and new LIVE entries fail closed until an
        # authoritative exchange balance/equity resync clears it.
        self.live_pnl_accounting_unavailable = None

        # duplicate prevention
        self.pending_order = False
        self.execution_entry_guard_lock = threading.RLock()
        self.execution_entry_guard = None
        self.execution_entry_admission_lock = threading.RLock()
        self.execution_entry_admission_in_progress = False
        # Manager-owned shared authority boundary callback. It is consulted at
        # the entry commit boundary (after MM preflight and Governance) so the
        # final BOT/MANUAL authority and stale-intent revalidation cannot be
        # bypassed by a pre-approved MM admission.
        self.execution_authority_guard_lock = threading.RLock()
        self.execution_authority_guard = None
        self.last_execution_authority_guard = None
        self.last_money_management_guard = None
        # Shared close boundary. One authoritative position may commit at most
        # one close. Manual close, SL, TP, trailing, natural/time exit and
        # emergency flatten all funnel through ``close_position`` so the
        # reservation serializes them and prevents a double close commit.
        self.close_authority_lock = threading.RLock()
        self.close_reservation = None
        # One short-lived, exact-order MM admission lets the mainline evaluate
        # Money Management before Governance without evaluating the same entry
        # twice. It is consumed by the normal engine entry boundary.
        self.execution_entry_preapproval = None

        # realtime freshness
        self.last_market_update = 0

        # signal lifecycle
        self.last_signal_time = 0
        self.last_signal_id = None

        # strategy-specific exit authority (MicrostructureEdgeStrategy exit)
        self.exit_evaluator = None

        # execution lifecycle
        self.last_execution_time = 0

        self.price_ready = False

        self.config = {
            "risk_percent": 1,
            "position_size": 0.0,
            "leverage": 10,
            "timeframe": "1m",
            "sl_percent": 1,
            "tp_percent": 2,
            "max_drawdown_pct": 5.0,
            "trailing_stop": False,
            "trailing_stop_distance_percent": None,
            "dry_run": True
        }

        self.initial_equity = self.balance
        self.peak_equity = self.balance
        self.current_drawdown_pct = 0.0
        self.risk_trading_disabled = False
        self.risk_block_reason = None

        self.exchange_auth_ready = False
        self.balance_check_ok = False
        self.position_check_ok = False
        self.balance_check_error = None
        self.position_check_error = None
        self.real_balance = None
        self.real_equity = None
        self.real_available_balance = None
        self.real_account_snapshot = {}
        self.real_account_last_sync = None
        self.real_position = None
        self.real_position_state = "NOT_SYNCED"
        self.last_order_blocked_reason = None
        self.last_live_block_reasons = []

        # LIVE close observability.  A natural (non-emergency) LIVE exit must
        # submit a real reduceOnly exchange close and may only move local state
        # to FLAT on authoritative exchange confirmation.  These fields are
        # intentionally distinct from emergency flatten state.
        self.live_close_state = None
        self.live_close_in_flight = False

        # Paper execution audit trail.  Paper orders fill immediately, but we
        # retain the order and fill as separate lifecycle records so the
        # simulation path can be inspected without touching an exchange.
        self.paper_orders = []
        self.paper_fills = []
        self.trade_history = []

    # =====================================
    # START
    # =====================================

    def start(self):

        add_log("🚀 ENGINE START CALLED")

        selected_mode = str(
            self.config.get("mode", "paper")
        ).strip().upper()

        self.exchange_auth_ready = (
            self._exchange_credentials_ready()
            if self.exchange
            else False
        )

        if selected_mode == "LIVE" and self.exchange:

            try:

                account_overview = {}

                if hasattr(self.exchange, "get_account_overview"):
                    account_overview = (
                        self.exchange.get_account_overview()
                        or {}
                    )
                    balance = float(
                        account_overview.get(
                            "balance",
                            account_overview.get("equity", 0.0),
                        )
                        or 0.0
                    )
                else:
                    balance = self.exchange.get_balance()
                    account_overview = {
                        "source": "KUCOIN_FUTURES_READ_ONLY",
                        "accountType": "KUCOIN_FUTURES",
                        "balance": balance,
                        "equity": balance,
                        "availableBalance": None,
                        "exchangeAuth": "VERIFIED",
                        "exchangeConnection": "CONNECTED",
                        "apiKeyStatus": "VERIFIED",
                        "permission": "READ_ONLY",
                        "lastSync": time.time(),
                    }

                runtime_debug("ExecutionEngine live balance=%s", balance)

                self.balance_check_ok = True
                self.balance_check_error = None
                self.real_account_snapshot = dict(account_overview)
                self.real_balance = balance
                self.real_equity = account_overview.get(
                    "equity",
                    balance,
                )
                self.real_available_balance = account_overview.get(
                    "availableBalance"
                )
                self.real_account_last_sync = account_overview.get(
                    "lastSync",
                    time.time(),
                )

                if balance > 0:

                    self.balance = balance

                    if self.portfolio:
                        self.portfolio.balance = balance

                    self._resolve_live_pnl_accounting(
                        "START_ACCOUNT_SYNC"
                    )

            except Exception as e:

                self.balance_check_ok = False
                self.balance_check_error = str(e)

                self.logger.exception("BALANCE FETCH ERROR")

        # =====================================
        # POSITION SYNC
        # =====================================

        if (
            selected_mode == "LIVE"
            and self.exchange
            and self.symbol
        ):

            try:

                pos = self.exchange.get_positions(
                    self.symbol
                )

                # The exchange position carries no SL/TP/multiplier; attach
                # the canonical LIVE protection (or an explicit UNAVAILABLE).
                self.actual_position = (
                    self._attach_live_position_protection(
                        pos,
                        previous=self.actual_position,
                    )
                )
                self.real_position = pos
                self.real_position_state = (
                    "OPEN"
                    if pos
                    else "NO_OPEN_POSITION"
                )

                runtime_debug("ExecutionEngine synced position=%s", pos)

                self.position_check_ok = True
                self.position_check_error = None

            except Exception as e:

                self.position_check_ok = False
                self.position_check_error = str(e)
                self.real_position_state = "SYNC_FAILED"

                self.logger.exception("POSITION SYNC ERROR")

        # =====================================
        # RUNNING
        # =====================================

        self.status = "RUNNING"

        add_log(
            f"🔥 ENGINE STARTED: "
            f"{self.mode}"
        )

        return {
            "status": "started"
        }

    # =====================================
    # REFRESH BALANCE
    # =====================================

    def refresh_balance(self):

        if not self.exchange:

            return

        try:

            balance = (
                self.exchange.get_balance()
            )

            runtime_debug("ExecutionEngine refreshed balance=%s", balance)

            if balance > 0:

                self.balance = balance

                if self.portfolio:

                    self.portfolio.balance = (
                        balance
                    )

                self._resolve_live_pnl_accounting(
                    "EXCHANGE_BALANCE_REFRESH"
                )

        except Exception as e:

            add_log(
                f"❌ REFRESH BALANCE ERROR: "
                f"{e}",
                "error",
            )

    # =====================================
    # STOP
    # =====================================

    def stop(self):

        self.status = "STOPPED"

        add_log("🛑 ENGINE STOPPED")

        return {
            "status": "stopped"
        }

    # =====================================
    # RISK STATE
    # =====================================

    def _current_balance(self):

        return float(
            self.portfolio.balance
            if self.portfolio
            else self.balance
        )

    def _current_equity(self):

        return (
            self._current_balance()
            + float(self.unrealized_pnl or 0)
        )

    def _reset_risk_state(self):

        equity = self._current_equity()

        self.initial_equity = equity
        self.peak_equity = equity
        self.current_drawdown_pct = 0.0
        self.risk_trading_disabled = False
        self.risk_block_reason = None

    def apply_live_risk_equity_authority(
        self,
        *,
        initial_equity,
        peak_equity,
        authority_source,
    ):
        """Apply validated canonical LIVE equity/HWM to local risk state."""

        if self.mode != "live":
            return False
        if authority_source != "REAL_LIVE_ACCOUNT_EQUITY":
            return False
        try:
            initial = float(initial_equity)
            peak = float(peak_equity)
        except (TypeError, ValueError):
            return False
        if (
            not math.isfinite(initial)
            or not math.isfinite(peak)
            or initial <= 0
            or peak <= 0
            or peak < initial
        ):
            return False

        if (
            self.live_pnl_accounting_unavailable
            and not self.actual_position
        ):
            # Flat after a close whose local PnL was unavailable: the canonical
            # exchange equity (REAL_LIVE_ACCOUNT_EQUITY) is the authoritative
            # balance; the stale local balance is never used for drawdown.
            self.balance = initial
            if self.portfolio:
                self.portfolio.balance = initial
            self._resolve_live_pnl_accounting("REAL_LIVE_ACCOUNT_EQUITY")

        self.initial_equity = initial
        self.peak_equity = peak
        self.risk_trading_disabled = False
        self.risk_block_reason = None
        self.update_drawdown_state(self._current_equity())
        return True

    def _live_accounting_unavailable_reason(self):
        """Reason local LIVE equity is not authoritative, else ``None``."""

        if not self._is_live_execution():
            return None
        if self.live_pnl_accounting_unavailable:
            return LIVE_PNL_ACCOUNTING_UNAVAILABLE
        if self.actual_position and self.unrealized_pnl_available is False:
            return "LIVE_UNREALIZED_PNL_UNAVAILABLE"
        return None

    def _resolve_live_pnl_accounting(self, source):
        """Clear the unavailable-PnL flag after an authoritative resync."""

        if not self.live_pnl_accounting_unavailable:
            return False
        if self.actual_position:
            return False
        add_log(
            f"✅ {LIVE_PNL_ACCOUNTING_UNAVAILABLE} resolved by {source}"
        )
        self.live_pnl_accounting_unavailable = None
        return True

    def update_drawdown_state(self, equity=None):

        if self._live_accounting_unavailable_reason() is not None:
            # LIVE local equity is unknown (unavailable PnL): keep the last
            # authoritative drawdown state instead of computing it from a
            # fabricated 0.  New LIVE entries fail closed via live readiness.
            return self.get_risk_state()

        if equity is None:
            equity = self._current_equity()

        equity = float(equity)

        if self.initial_equity is None:
            self.initial_equity = equity

        if self.peak_equity is None or equity > self.peak_equity:
            self.peak_equity = equity

        if not self.peak_equity:
            self.current_drawdown_pct = 0.0
        else:
            self.current_drawdown_pct = max(
                0.0,
                (
                    (self.peak_equity - equity)
                    / self.peak_equity
                    * 100
                ),
            )

        if (
            self.current_drawdown_pct
            >= self.config["max_drawdown_pct"]
        ):
            self.risk_trading_disabled = True
            self.risk_block_reason = "MAX_DRAWDOWN"

            runtime_debug(
                "ExecutionEngine risk halted drawdown=%s max=%s",
                self.current_drawdown_pct,
                self.config["max_drawdown_pct"],
            )

        return self.get_risk_state()

    def _active_position_metrics(self):

        position = self.actual_position

        if isinstance(position, list):

            position = (
                position[0]
                if position
                else None
            )

        if not isinstance(position, dict):

            return {
                "activePositionQty": None,
                "activePositionContractQty": None,
                "activePositionNotional": None,
                "activePositionEntryNotional": None,
            }

        try:

            contracts = float(
                position.get("qty", 0) or 0
            )

            multiplier = _positive_finite(
                position.get("multiplier")
            )

            if multiplier is None:
                if self._is_live_execution():
                    # No authoritative LIVE contract multiplier: size and
                    # notional are unavailable, never estimated.
                    raise ValueError("LIVE_POSITION_MULTIPLIER_UNAVAILABLE")
                multiplier = 1.0

            real_qty = float(
                position.get(
                    "coin_qty",
                    contracts * multiplier,
                )
                or 0
            )

            entry_price = float(
                position.get("entry_price", 0) or 0
            )

            mark_price = float(
                self.latest_price
                or entry_price
                or 0
            )

            notional = (
                real_qty * mark_price
                if mark_price > 0
                else None
            )

            entry_notional = (
                real_qty * entry_price
                if entry_price > 0
                else None
            )

            return {
                "activePositionQty": real_qty,
                "activePositionContractQty": contracts,
                "activePositionNotional": notional,
                "activePositionEntryNotional": entry_notional,
            }

        except Exception:

            return {
                "activePositionQty": None,
                "activePositionContractQty": None,
                "activePositionNotional": None,
                "activePositionEntryNotional": None,
            }

    def get_risk_state(self):

        position_metrics = self._active_position_metrics()

        return {
            "initialEquity": self.initial_equity,
            "peakEquity": self.peak_equity,
            "currentEquity": self._current_equity(),
            "currentDrawdownPct": self.current_drawdown_pct,
            "maxDrawdownPct": self.config["max_drawdown_pct"],
            "riskTradingDisabled": self.risk_trading_disabled,
            "riskBlockReason": self.risk_block_reason,
            "pnlAccountingAvailable": (
                self._live_accounting_unavailable_reason() is None
            ),
            "pnlAccountingBlockReason": (
                self._live_accounting_unavailable_reason()
            ),
            "unrealizedPnlAvailable": bool(self.unrealized_pnl_available),
            "positionSize": self.config["position_size"],
            "tpPercent": self.config["tp_percent"],
            "slPercent": self.config["sl_percent"],
            "trailingStop": self.config["trailing_stop"],
            "trailingStopDistancePercent": (
                self.config.get("trailing_stop_distance_percent")
                or self.config["sl_percent"]
            ),
            "realQty": position_metrics["activePositionQty"],
            "notional": position_metrics["activePositionNotional"],
            **position_metrics,
        }

    # =====================================
    # CONFIG
    # =====================================

    @staticmethod
    def _as_bool(value):

        if isinstance(value, str):
            return (
                value.strip().lower()
                in ["1", "true", "yes", "on"]
            )

        return bool(value)

    def _exchange_credentials_ready(self):

        if not self.exchange:
            return False

        credentials_ready = getattr(
            self.exchange,
            "credentials_ready",
            None,
        )

        if callable(credentials_ready):
            return bool(credentials_ready())

        return bool(
            getattr(self.exchange, "api_key", None)
            and getattr(self.exchange, "api_secret", None)
            and getattr(self.exchange, "passphrase", None)
        )

    def build_live_readiness(self, *, entry_authority=None):
        # Status uses the backend-owned control mirror. Actual submission passes
        # the authority returned by the manager guard, never the signal label.
        if entry_authority is None:
            entry_authority = governance_state.get("control_authority", "BOT")


        selected_mode = str(
            self.config.get("mode", "paper")
        ).strip().upper()
        dry_run = bool(
            self.config.get("dry_run", True)
        )
        trade_mode_live = (
            backend_config.TRADE_MODE == "live"
        )
        allow_live = (
            backend_config.ALLOW_LIVE is True
        )
        exchange_client_ready = self.exchange is not None
        exchange_auth_ready = (
            self._exchange_credentials_ready()
            if exchange_client_ready
            else False
        )
        balance_check_ok = bool(self.balance_check_ok)
        position_check_ok = bool(self.position_check_ok)
        execution_enabled = bool(
            governance_state.get("execution_enabled", False)
        )
        emergency_stop = bool(
            governance_state.get("emergency_stop", False)
        )

        checks = {
            "selectedModeLive": selected_mode == "LIVE",
            "dryRunDisabled": dry_run is False,
            "allowLive": allow_live,
            "tradeModeLive": trade_mode_live,
            "exchangeClientReady": exchange_client_ready,
            "exchangeAuthReady": exchange_auth_ready,
            "balanceCheckOk": balance_check_ok,
            "positionCheckOk": position_check_ok,
            "executionEnabled": execution_enabled,
            "liveOrderEntryAllowed": self.config.get("liveOrderEntryAllowed") is True,
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
        if entry_authority not in {"BOT", "MANUAL"}:
            block_reasons.append("EXECUTION_AUTHORITY_UNKNOWN")
        if entry_authority != "MANUAL" and not checks["executionEnabled"]:
            block_reasons.append("EXECUTION_DISABLED")
        if not checks["liveOrderEntryAllowed"]:
            block_reasons.append("LIVE_ORDER_ENTRY_DISARMED")
        if not checks["emergencyStopClear"]:
            block_reasons.append("EMERGENCY_STOP_ACTIVE")

        live_position_protection = self.live_position_protection_status()
        # Also expressed as checks so the bot-status projection
        # (derive_live_readiness, which rebuilds reasons from checks) keeps the
        # fail-closed reasons visible in liveReadiness / liveBlockReasons.
        checks["livePositionProtectionAvailable"] = (
            live_position_protection.get("state") != "UNAVAILABLE"
        )
        checks["livePnlAccountingAvailable"] = (
            not self.live_pnl_accounting_unavailable
        )
        if live_position_protection.get("state") == "UNAVAILABLE":
            # An open LIVE position without protection authority fails closed
            # for new entries/ARM; close paths do not consult readiness.
            block_reasons.append(LIVE_POSITION_PROTECTION_UNAVAILABLE)
        if self.live_pnl_accounting_unavailable:
            # Local LIVE PnL/balance/drawdown are unknown after a close whose
            # PnL could not be computed: new entries fail closed until an
            # authoritative exchange resync (close paths skip readiness).
            block_reasons.append(LIVE_PNL_ACCOUNTING_UNAVAILABLE)

        real_order_allowed = not block_reasons
        account_snapshot = dict(self.real_account_snapshot or {})
        account_type = account_snapshot.get(
            "accountType",
            "KUCOIN_FUTURES" if exchange_auth_ready else "UNKNOWN",
        )
        exchange_connection = (
            "CONNECTED"
            if exchange_client_ready
            else "NOT_CONNECTED"
        )
        api_key_status = (
            "VERIFIED"
            if exchange_auth_ready
            else "MISSING"
        )
        permission = (
            account_snapshot.get("permission")
            or ("READ_ONLY" if exchange_auth_ready else "NOT_VERIFIED")
        )
        auth_reason = (
            "KUCOIN_CREDENTIALS_VERIFIED"
            if exchange_auth_ready
            else "KUCOIN_CREDENTIALS_MISSING"
        )
        connection_reason = (
            "KUCOIN_CLIENT_READY"
            if exchange_client_ready
            else "EXCHANGE_CLIENT_NOT_READY"
        )
        balance_reason = (
            "KUCOIN_BALANCE_SYNC_OK"
            if balance_check_ok
            else (
                self.balance_check_error
                or "BALANCE_NOT_SYNCED"
            )
        )
        position_reason = (
            "KUCOIN_POSITION_SYNC_OK"
            if position_check_ok
            else (
                self.position_check_error
                or "POSITION_NOT_SYNCED"
            )
        )
        account_reason = (
            "KUCOIN_READ_ONLY_SYNC_OK"
            if balance_check_ok or position_check_ok
            else "KUCOIN_READ_ONLY_NOT_CONNECTED"
        )

        return {
            "ready": real_order_allowed,
            "entryAuthority": entry_authority,
            "realOrderAllowed": real_order_allowed,
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
            "balanceCheckError": self.balance_check_error,
            "positionCheckError": self.position_check_error,
            "realBalance": self.real_balance,
            "realEquity": self.real_equity,
            "realAvailableBalance": self.real_available_balance,
            "realUnrealizedPnl": self.real_account_snapshot.get(
                "unrealizedPnl"
            ),
            "realMarginUsed": self.real_account_snapshot.get(
                "marginUsed"
            ),
            "realMarginAvailable": self.real_account_snapshot.get(
                "availableMargin"
            ),
            "realPosition": self.real_position,
            "realPositionState": self.real_position_state,
            "realAccountLastSync": self.real_account_last_sync,
            "exchangeConnection": exchange_connection,
            "apiKeyStatus": api_key_status,
            "permission": permission,
            "accountType": account_type,
            "exchangeAuthReason": auth_reason,
            "exchangeConnectionReason": connection_reason,
            "accountReason": account_reason,
            "balanceReason": balance_reason,
            "positionReason": position_reason,
            "accountSnapshot": account_snapshot,
            "livePositionProtection": live_position_protection,
            "livePnlAccounting": (
                dict(self.live_pnl_accounting_unavailable, state="UNAVAILABLE")
                if self.live_pnl_accounting_unavailable
                else {"state": "AVAILABLE"}
            ),
        }

    def _live_order_allowed(self, authority_context=None):

        origin = (authority_context or {}).get("entryAuthority")
        if origin not in {"BOT", "MANUAL"} or (
            origin == "MANUAL"
            and (authority_context.get("governanceDecision") or {}).get("allowed") is not True
        ):
            self.last_live_block_reasons = ["EXECUTION_AUTHORITY_UNKNOWN"]
            return False
        readiness = self.build_live_readiness(entry_authority=origin)
        self.last_live_block_reasons = list(
            readiness["blockReasons"]
        )

        if readiness["realOrderAllowed"]:
            self.last_order_blocked_reason = None
            return True

        self.last_order_blocked_reason = "LIVE_NOT_READY"

        return False

    def set_live_order_entry_authority(self, armed):
        """ARM/DISARM LIVE real-order entry authority.

        ARM is fail-closed: it only succeeds while every runtime safety
        prerequisite currently holds (LIVE mode, dry-run disabled, ALLOW_LIVE,
        TRADE_MODE=live, exchange client/credentials ready, balance/position
        authority synced and consistent, emergency clear).  The auto-trade-loop
        gate (governance ``execution_enabled``) is intentionally NOT required
        here because arming real-order entry is a distinct concept from running
        the auto-trade loop.

        This mutates only the three authority flags; it never creates, cancels,
        or closes an order or a position.  DISARM is the inverse and preserves
        runtime/monitoring.
        """
        if armed:
            readiness = self.build_live_readiness()
            reasons = [
                reason
                for reason in (readiness.get("blockReasons") or [])
                if reason not in {"LIVE_ORDER_ENTRY_DISARMED", "EXECUTION_DISABLED"}
            ]
            if reasons:
                return {
                    "success": False,
                    "armed": False,
                    "liveOrderEntryAllowed": False,
                    "realOrderAllowed": False,
                    "executionEntryAllowed": False,
                    "reason": reasons[0],
                    "blockReasons": reasons,
                }
            self.config["liveOrderEntryAllowed"] = True
            self.config["realOrderAllowed"] = True
            self.config["executionEntryAllowed"] = True
            return {
                "success": True,
                "armed": True,
                "liveOrderEntryAllowed": True,
                "realOrderAllowed": True,
                "executionEntryAllowed": True,
                "reason": "LIVE_ORDER_ENTRY_ARMED",
            }

        self.config["liveOrderEntryAllowed"] = False
        self.config["realOrderAllowed"] = False
        self.config["executionEntryAllowed"] = False
        return {
            "success": True,
            "armed": False,
            "liveOrderEntryAllowed": False,
            "realOrderAllowed": False,
            "executionEntryAllowed": False,
            "reason": "LIVE_ORDER_ENTRY_DISARMED",
        }

    def set_config(self, config: dict):

        try:

            if not config:
                return

            safe_config = dict(config)

            safe_config.pop("symbol", None)

            self.config["mode"] = str(
                safe_config.get(
                    "mode",
                    self.config.get("mode", "paper")
                )
                or "paper"
            ).strip().lower()

            self.config["risk_percent"] = float(
                safe_config.get(
                    "risk_percent",
                    self.config["risk_percent"]
                )
            )

            self.config["position_size"] = float(
                safe_config.get(
                    "position_size",
                    safe_config.get(
                        "positionSize",
                        self.config["position_size"]
                    )
                ) or 0
            )

            self.config["leverage"] = float(
                float(
                    safe_config.get(
                        "leverage",
                        self.config["leverage"]
                    )
                )
            )

            runtime_debug(
                "ExecutionEngine normalized leverage=%s type=%s",
                self.config["leverage"],
                type(self.config["leverage"]).__name__,
            )

            # The canonical effective leverage resolved by the Money
            # Management / runtime authority at START is carried separately
            # from the legacy display/config leverage.  The LIVE order
            # construction path consumes only this canonical authority and
            # fails closed when it is absent.
            if safe_config.get("effective_leverage") is not None:
                self.config["effective_leverage"] = safe_config.get(
                    "effective_leverage"
                )

            self.config["timeframe"] = str(
                safe_config.get(
                    "timeframe",
                    self.config["timeframe"]
                )
                or "1m"
            )

            self.config["sl_percent"] = float(
                safe_config.get(
                    "sl_percent",
                    self.config["sl_percent"]
                )
            )

            self.config["tp_percent"] = float(
                safe_config.get(
                    "tp_percent",
                    self.config["tp_percent"]
                )
            )

            self.config["max_drawdown_pct"] = float(
                safe_config.get(
                    "max_drawdown_pct",
                    safe_config.get(
                        "maxDd",
                        self.config["max_drawdown_pct"]
                    )
                )
            )

            trailing_value = safe_config.get(
                "trailing_stop",
                safe_config.get(
                    "trailing",
                    self.config["trailing_stop"]
                )
            )

            if isinstance(trailing_value, str):

                trailing_value = (
                    trailing_value.strip().upper()
                    in ["ON", "TRUE", "1", "YES"]
                )

            self.config["trailing_stop"] = bool(
                trailing_value
            )

            trailing_distance = safe_config.get(
                "trailing_stop_distance_percent",
                self.config["trailing_stop_distance_percent"]
            )

            self.config[
                "trailing_stop_distance_percent"
            ] = (
                None
                if trailing_distance in [None, ""]
                else float(trailing_distance)
            )

            self.config["dry_run"] = self._as_bool(
                safe_config.get(
                    "dry_run",
                    self.config["dry_run"]
                )
            )

            # =====================================
            # MODE NORMALIZATION
            # =====================================

            if self.config["dry_run"]:

                self.mode = "paper"

            else:

                self.mode = "live"

            add_log(
                f"🔥 FINAL MODE => {self.mode}"
            )

            add_log(
                f"🟡 DRY RUN => "
                f"{self.config['dry_run']}"
            )

            self._reset_risk_state()

        except Exception:

            self.logger.exception("ExecutionEngine config error")

    # =====================================
    # POSITION RISK HELPERS
    # =====================================

    @staticmethod
    def _is_short(side):

        return str(side).upper() in [
            "SELL",
            "SHORT",
        ]

    def _target_prices(self, side, price):

        sl_distance = (
            self.config["sl_percent"] / 100
        )

        tp_distance = (
            self.config["tp_percent"] / 100
        )

        if self._is_short(side):

            return {
                "sl": price * (1 + sl_distance),
                "tp": price * (1 - tp_distance),
            }

        return {
            "sl": price * (1 - sl_distance),
            "tp": price * (1 + tp_distance),
        }

    # =====================================
    # LIVE POSITION PROTECTION AUTHORITY
    # =====================================

    def _is_live_execution(self):

        return (
            str(self.mode or "").strip().lower() == "live"
            or str(self.config.get("mode", "") or "").strip().upper() == "LIVE"
        )

    def _position_multiplier(self, position):
        """Contract multiplier for PnL/size. LIVE: authoritative or ``None``."""

        multiplier = _positive_finite(
            (position or {}).get("multiplier")
        )

        if multiplier is not None:
            return multiplier

        if self._is_live_execution():
            return None

        # PAPER positions always carry a multiplier; legacy default retained.
        return 0.001

    @staticmethod
    def _position_protection_levels(position):
        """Return ``(sl, tp)``; each is a valid positive level or ``None``."""

        position = position or {}
        return (
            _positive_finite(position.get("sl")),
            _positive_finite(position.get("tp")),
        )

    def _live_contract_multiplier(self, position_symbol=None):
        """Resolve the KuCoin contract multiplier for ``self.symbol``.

        Authority: ``exchange.get_symbol_rules`` (KuCoin public contract
        metadata, ``get_order_contract_rules``); falls back to the engine's
        sizing contract cache for the same symbol when the fresh read fails.
        Returns ``(multiplier, reason)``; ``multiplier`` is ``None`` when
        unavailable.
        """

        from backend.market.kucoin_futures_public import (
            to_kucoin_futures_symbol,
        )

        if not self.symbol:
            return None, "LIVE_POSITION_SYMBOL_UNAVAILABLE"

        expected = to_kucoin_futures_symbol(self.symbol)

        if position_symbol and str(position_symbol) != expected:
            return None, "LIVE_POSITION_SYMBOL_MISMATCH"

        rules = None
        provider = getattr(self.exchange, "get_symbol_rules", None)

        if callable(provider):
            try:
                rules = provider(self.symbol)
            except Exception:
                rules = None

        if not isinstance(rules, dict):
            cached = self._sizing_contract_cache
            if (
                cached
                and cached[0] == self.symbol
                and isinstance(cached[2], dict)
            ):
                rules = cached[2]

        if not isinstance(rules, dict):
            return None, "LIVE_CONTRACT_METADATA_UNAVAILABLE"

        if rules.get("symbol") != expected or rules.get("isInverse") is True:
            return None, "LIVE_CONTRACT_METADATA_MISMATCH"

        multiplier = _positive_finite(rules.get("multiplier"))

        if multiplier is None:
            return None, "LIVE_CONTRACT_MULTIPLIER_INVALID"

        return multiplier, None

    def _attach_live_position_protection(self, position, previous=None):
        """Single canonical LIVE position protection authority.

        The KuCoin position (``KucoinTradeClient.get_positions``) carries only
        symbol/qty/side/entry_price.  This attaches, following the PAPER
        position layout, the SL/TP levels derived by ``_target_prices`` from
        the exchange entry price and the configured SL%/TP%, and the
        authoritative contract multiplier.

        * A re-sync of the same position (same side and entry price) keeps the
          existing levels, so a trailed SL is never reset.
        * Invalid or missing inputs never produce levels: the position is
          marked ``protection_state=UNAVAILABLE`` (fail closed; exposed as
          ``LIVE_POSITION_PROTECTION_UNAVAILABLE`` in live readiness).
        * Nothing is invented: no hard-coded percentage or multiplier.
        """

        if not isinstance(position, dict) or not position:
            return position

        protected = dict(position)
        protected.setdefault("state", "OPEN")

        side = protected.get("side")
        entry = _positive_finite(protected.get("entry_price"))
        contracts = _positive_finite(protected.get("qty"))
        multiplier, multiplier_reason = self._live_contract_multiplier(
            protected.get("symbol")
        )

        same_lifecycle = bool(
            isinstance(previous, dict)
            and previous.get("protection_state") == "ACTIVE"
            and entry is not None
            and str(previous.get("side") or "").upper()
            == str(side or "").upper()
            and _positive_finite(previous.get("entry_price")) == entry
        )

        if same_lifecycle:
            previous_sl, previous_tp = self._position_protection_levels(previous)
            previous_multiplier = _positive_finite(previous.get("multiplier"))
            if (
                previous_sl is not None
                and previous_tp is not None
                and (multiplier or previous_multiplier) is not None
            ):
                merged = dict(previous)
                # Exchange facts win; protection state is preserved.
                merged.update(position)
                merged["state"] = previous.get("state") or "OPEN"
                merged["multiplier"] = multiplier or previous_multiplier
                if contracts is not None:
                    merged["coin_qty"] = contracts * merged["multiplier"]
                merged["protection_state"] = "ACTIVE"
                merged["protection_reason"] = None
                return merged

        reasons = []

        if str(side or "").upper() not in ("BUY", "SELL", "LONG", "SHORT"):
            reasons.append("LIVE_POSITION_SIDE_UNKNOWN")
        if entry is None:
            reasons.append("LIVE_POSITION_ENTRY_PRICE_INVALID")
        if contracts is None:
            reasons.append("LIVE_POSITION_QTY_INVALID")
        if _positive_finite(self.config.get("sl_percent")) is None:
            reasons.append("LIVE_SL_PERCENT_INVALID")
        if _positive_finite(self.config.get("tp_percent")) is None:
            reasons.append("LIVE_TP_PERCENT_INVALID")
        if multiplier is None:
            reasons.append(multiplier_reason)

        if reasons:
            for key in ("sl", "tp", "trailing_stop_price"):
                protected.pop(key, None)
            if multiplier is None:
                protected.pop("multiplier", None)
                protected.pop("coin_qty", None)
            else:
                protected["multiplier"] = multiplier
            protected["trailing"] = False
            protected["protection_state"] = "UNAVAILABLE"
            protected["protection_reason"] = reasons
            protected["protection_source"] = LIVE_POSITION_PROTECTION_SOURCE
            add_log(
                f"⛔ {LIVE_POSITION_PROTECTION_UNAVAILABLE}: "
                f"{','.join(reasons)}",
                "error",
            )
            return protected

        target_prices = self._target_prices(side, entry)
        trailing_enabled = bool(self.config.get("trailing_stop"))

        protected.update({
            "multiplier": multiplier,
            "coin_qty": contracts * multiplier,
            "entry_time": protected.get("entry_time") or time.time(),
            "sl": target_prices["sl"],
            "tp": target_prices["tp"],
            "tp_percent": self.config["tp_percent"],
            "sl_percent": self.config["sl_percent"],
            "trailing": trailing_enabled,
            "trailing_distance_percent": self._trailing_distance_percent(),
            "trailing_reference_price": entry,
            "trailing_stop_price": (
                target_prices["sl"] if trailing_enabled else None
            ),
            "protection_state": "ACTIVE",
            "protection_reason": None,
            "protection_source": LIVE_POSITION_PROTECTION_SOURCE,
            "protection_basis": "EXCHANGE_ENTRY_PRICE_X_CONFIGURED_PERCENT",
        })

        return protected

    def live_position_protection_status(self):
        """Read-only protection status of the current LIVE position."""

        position = self.actual_position

        if not isinstance(position, dict) or not position:
            return {"state": "NO_POSITION", "protected": None, "reasons": []}

        if not self._is_live_execution():
            return {"state": "NOT_LIVE", "protected": None, "reasons": []}

        stop_loss, take_profit = self._position_protection_levels(position)
        multiplier = _positive_finite(position.get("multiplier"))
        reasons = list(position.get("protection_reason") or [])

        if position.get("protection_state") == "UNAVAILABLE" and not reasons:
            reasons.append(LIVE_POSITION_PROTECTION_UNAVAILABLE)
        if stop_loss is None and "LIVE_POSITION_SL_UNAVAILABLE" not in reasons:
            reasons.append("LIVE_POSITION_SL_UNAVAILABLE")
        if take_profit is None and "LIVE_POSITION_TP_UNAVAILABLE" not in reasons:
            reasons.append("LIVE_POSITION_TP_UNAVAILABLE")
        if multiplier is None and "LIVE_POSITION_MULTIPLIER_UNAVAILABLE" not in reasons:
            reasons.append("LIVE_POSITION_MULTIPLIER_UNAVAILABLE")

        protected = (
            position.get("protection_state") != "UNAVAILABLE"
            and stop_loss is not None
            and take_profit is not None
            and multiplier is not None
        )

        return {
            "state": "ACTIVE" if protected else "UNAVAILABLE",
            "protected": protected,
            "reasons": [] if protected else reasons,
            "stopLoss": stop_loss,
            "takeProfit": take_profit,
            "multiplier": multiplier,
            "source": position.get("protection_source"),
            "monitoring": "ENGINE_ON_PRICE",
        }

    def _trailing_distance_percent(self):

        return float(
            self.config.get(
                "trailing_stop_distance_percent"
            )
            or self.config["sl_percent"]
        )

    def _update_trailing_stop(self, price):

        if not self.actual_position:
            return

        if not self.actual_position.get(
            "trailing",
            False,
        ):
            return

        side = self.actual_position.get("side")

        distance = (
            float(
                self.actual_position.get(
                    "trailing_distance_percent",
                    self._trailing_distance_percent(),
                )
            )
            / 100
        )

        reference = self.actual_position.get(
            "trailing_reference_price",
            self.actual_position.get("entry_price", price),
        )

        current_sl = self.actual_position.get("sl")

        if self._is_short(side):

            if price < reference:

                new_sl = price * (1 + distance)

                if current_sl is None or new_sl < current_sl:

                    self.actual_position["sl"] = new_sl
                    self.actual_position[
                        "trailing_stop_price"
                    ] = new_sl

                self.actual_position[
                    "trailing_reference_price"
                ] = price

        else:

            if price > reference:

                new_sl = price * (1 - distance)

                if current_sl is None or new_sl > current_sl:

                    self.actual_position["sl"] = new_sl
                    self.actual_position[
                        "trailing_stop_price"
                    ] = new_sl

                self.actual_position[
                    "trailing_reference_price"
                ] = price

    # =====================================
    # PRICE EVENT
    # =====================================

    def set_exit_evaluator(self, evaluator):
        """Bind the strategy-specific exit evaluator used by on_price().

        The evaluator receives (microstructure_state, position_info) and
        returns an ExitDecision (or dict) with a "decision" of "EXIT"/"HOLD".
        Generic SL/TP close authority is not replaced by this evaluator.
        """

        if evaluator is not None and not callable(evaluator):
            return False
        self.exit_evaluator = evaluator
        return True

    def _evaluate_strategy_exit(self, price, microstructure_state):
        """Evaluate a strategy-specific exit for the OPEN position.

        Returns an exit reason string when a close is authorized, otherwise
        None.  Only OPEN positions are evaluated, so FLAT / pending-entry /
        closing states never produce an exit request.
        """

        if self.exit_evaluator is None:
            return None
        if not isinstance(self.actual_position, dict):
            return None
        if self.actual_position.get("state") != "OPEN":
            return None
        if not isinstance(microstructure_state, dict):
            return None

        position_info = {
            "symbol": self.symbol or self.actual_position.get("symbol"),
            "positionSide": self.actual_position.get("side"),
            "entryPrice": self.actual_position.get("entry_price"),
            "currentPrice": price,
            "openedAt": self.actual_position.get("entry_time"),
            "traceId": self.actual_position.get("trace_id"),
        }
        if position_info["symbol"] is None:
            return None

        decision = self.exit_evaluator(microstructure_state, position_info)
        if isinstance(decision, dict):
            if decision.get("decision") == "EXIT":
                reason = decision.get("reason") or "MICROSTRUCTURE_EXIT"
                return getattr(reason, "value", reason)
            return None
        if getattr(decision, "decision", None) == "EXIT":
            reason = getattr(decision, "reason", None) or "MICROSTRUCTURE_EXIT"
            return getattr(reason, "value", reason)
        return None

    def on_price(self, symbol, price, microstructure_state=None):

        try:
            if getattr(self, "_on_price_running", False):

                ws_debug("ExecutionEngine blocked on_price reentry")

                return

            self._on_price_running = True

            import inspect

            self.last_market_update = time.time()

            if self.status != "RUNNING":
                return

            if symbol != self.symbol:

                ws_debug(
                    "ExecutionEngine blocked symbol=%s active=%s",
                    symbol,
                    self.symbol,
                )

                return

            self.latest_price = price

            if not self.price_ready and price > 0:

                add_log("✅ FIRST PRICE RECEIVED")

                self.price_ready = True

            self.update_drawdown_state()

            # =====================================
            # POSITION MANAGEMENT
            # =====================================

            if self.actual_position:

                entry = self.actual_position.get(
                    "entry_price",
                    0
                )

                contracts = self.actual_position.get(
                    "qty",
                    0
                )

                multiplier = self._position_multiplier(
                    self.actual_position
                )

                side = self.actual_position.get(
                    "side"
                )

                if multiplier is None:

                    # LIVE without an authoritative contract multiplier:
                    # unrealized PnL is unavailable, never estimated.
                    self.unrealized_pnl = 0.0
                    self.unrealized_pnl_available = False

                else:

                    coin_qty = (
                        contracts * multiplier
                    )

                    self.unrealized_pnl_available = True

                    if self._is_short(side):

                        self.unrealized_pnl = (
                            (entry - price)
                            * coin_qty
                        )

                    else:

                        self.unrealized_pnl = (
                            (price - entry)
                            * coin_qty
                        )

                self.update_drawdown_state()

                self._update_trailing_stop(price)

                runtime_debug(
                    "Position tick price=%s entry=%s side=%s qty=%s upnl=%s",
                    price,
                    entry,
                    side,
                    contracts,
                    self.unrealized_pnl,
                )

                stop_loss, take_profit = (
                    self._position_protection_levels(
                        self.actual_position
                    )
                )

                # A missing / non-positive level is "unavailable", never 0:
                # it can neither trigger nor look healthy (see
                # live_position_protection_status / live readiness).
                if self._is_short(side):

                    sl_hit = (
                        stop_loss is not None
                        and price >= stop_loss
                    )

                    tp_hit = (
                        take_profit is not None
                        and price <= take_profit
                    )

                else:

                    sl_hit = (
                        stop_loss is not None
                        and price <= stop_loss
                    )

                    tp_hit = (
                        take_profit is not None
                        and price >= take_profit
                    )

                if sl_hit:

                    add_log("🔴 SL HIT")

                    self.close_position(price, "SL")

                    return

                if tp_hit:

                    add_log("🟢 TP HIT")

                    self.close_position(price, "TP")

                    return

                # Strategy-specific microstructure exit.  Runs only after the
                # generic SL/TP authority has declined to close, so a single
                # close mutation is guaranteed per price cycle.
                strategy_exit_reason = self._evaluate_strategy_exit(
                    price, microstructure_state
                )
                if strategy_exit_reason:

                    add_log(
                        f"🧠 MICROSTRUCTURE EXIT ({strategy_exit_reason})"
                    )

                    self.close_position(price, str(strategy_exit_reason))

                    return

                return

        except Exception:

            self.logger.exception("ON_PRICE EXCEPTION")

        finally:

            self._on_price_running = False

    # =====================================
    # SIGNAL ENTRYPOINT
    # =====================================

    def set_execution_entry_guard(self, callback):

        if callback is not None and not callable(callback):
            return False

        with self.execution_entry_guard_lock:
            self.execution_entry_guard = callback

        return True

    def set_execution_authority_guard(self, callback):

        if callback is not None and not callable(callback):
            return False

        with self.execution_authority_guard_lock:
            self.execution_authority_guard = callback

        return True

    def _evaluate_execution_authority_guard(self, signal):

        with self.execution_authority_guard_lock:
            callback = self.execution_authority_guard

        if not isinstance(signal, dict):
            return False, self._entry_rejection("EXECUTION_AUTHORITY_UNKNOWN")
        if signal.get("entryAuthority") not in (None, "BOT", "MANUAL"):
            return False, self._entry_rejection("EXECUTION_AUTHORITY_UNKNOWN")
        if callback is None:
            self.last_execution_authority_guard = None
            if self.mode == "live" or signal.get("entryAuthority") == "MANUAL":
                return False, self._entry_rejection("EXECUTION_AUTHORITY_UNKNOWN")
            return True, None

        try:
            result = callback(signal)
        except Exception:
            self.last_execution_authority_guard = {
                "allowed": False,
                "reason": "EXECUTION_AUTHORITY_UNKNOWN",
            }
            return False, self._entry_rejection(
                "EXECUTION_AUTHORITY_UNKNOWN"
            )

        if not isinstance(result, dict):
            self.last_execution_authority_guard = {
                "allowed": False,
                "reason": "EXECUTION_AUTHORITY_UNKNOWN",
            }
            return False, self._entry_rejection(
                "EXECUTION_AUTHORITY_UNKNOWN"
            )

        self.last_execution_authority_guard = dict(result)

        if result.get("allowed") is True:
            origin = result.get("entryAuthority")
            if self.mode == "live" or signal.get("entryAuthority") == "MANUAL":
                if origin not in {"BOT", "MANUAL"}:
                    return False, self._entry_rejection("EXECUTION_AUTHORITY_UNKNOWN")
                if signal.get("entryAuthority") == "MANUAL" and origin != "MANUAL":
                    return False, self._entry_rejection("EXECUTION_AUTHORITY_UNKNOWN")
                if origin == "MANUAL" and (
                    not isinstance(result.get("governanceDecision"), dict)
                    or result["governanceDecision"].get("allowed") is not True
                ):
                    return False, self._entry_rejection("GOVERNANCE_REQUIRED")
            return True, result

        return False, self._entry_rejection(
            result.get("reason") or "EXECUTION_AUTHORITY_DENIED"
        )

    def _entry_preapproval_matches(self, order):
        """Return True only for an unconsumed exact-order MM admission."""

        with self.execution_entry_guard_lock:
            preapproval = self.execution_entry_preapproval

        if not isinstance(preapproval, dict):
            return False

        return bool(
            preapproval.get("traceId") == order.get("traceId")
            and preapproval.get("side") == order.get("side")
            and preapproval.get("quantity") == str(order.get("qty"))
            and preapproval.get("expiresAt", 0) >= time.time()
        )

    @staticmethod
    def _entry_rejection(reason, guard_result=None):

        result = {
            "success": False,
            "status": "rejected",
            "submitted": False,
            "accepted": False,
            "orderCreated": False,
            "providerCall": False,
            "exchangeCall": False,
            "reason": str(reason),
        }
        if isinstance(guard_result, LossExecutionAdmissionResult):
            result.update({
                "operation": (
                    guard_result.operation.value
                    if guard_result.operation
                    else None
                ),
                "decision": guard_result.decision.value,
                "generatedAt": (
                    guard_result.generated_at
                    .isoformat()
                    .replace("+00:00", "Z")
                ),
                "revision": guard_result.revision,
                "sequence": guard_result.sequence,
            })
        return result

    def _evaluate_execution_entry_guard(self, order):

        if (
            self.mode == "live"
            and (
                self.config.get("realOrderAllowed") is not True
                or self.config.get("executionEntryAllowed") is not True
                or self.config.get("liveOrderEntryAllowed") is not True
            )
        ):
            return False, self._entry_rejection(
                "LIVE_ORDER_ENTRY_DISARMED"
            )

        with self.execution_entry_guard_lock:
            preapproval = self.execution_entry_preapproval
            self.execution_entry_preapproval = None

        if isinstance(preapproval, dict):
            exact_order = (
                preapproval.get("traceId") == order.get("traceId")
                and preapproval.get("side") == order.get("side")
                and preapproval.get("quantity") == str(order.get("qty"))
                and preapproval.get("expiresAt", 0) >= time.time()
            )
            if exact_order:
                self.last_money_management_guard = dict(
                    preapproval["decision"]
                )
                return True, None

        side = order.get("side")
        expected_operation = {
            "BUY": LossExecutionOperation.NEW_BUY,
            "SELL": LossExecutionOperation.NEW_SELL,
        }.get(side)
        if expected_operation is None:
            return False, self._entry_rejection(
                "EXECUTION_INTENT_INVALID"
            )
        try:
            quantity = Decimal(str(order.get("qty")))
            intent = LossExecutionIntent(
                side,
                quantity,
                self.actual_position is not None,
            )
        except (TypeError, ValueError, ArithmeticError):
            return False, self._entry_rejection(
                "EXECUTION_INTENT_INVALID"
            )

        with self.execution_entry_guard_lock:
            callback = self.execution_entry_guard

        if callback is None:
            return False, self._entry_rejection(
                "MONEY_MANAGEMENT_UNKNOWN"
            )
        try:
            result = callback(intent)
        except Exception:
            return False, self._entry_rejection(
                "MONEY_MANAGEMENT_UNKNOWN"
            )

        now = datetime.now(timezone.utc)
        valid = (
            isinstance(result, LossExecutionAdmissionResult)
            and result.operation is expected_operation
            and type(result.allowed) is bool
            and result.allowed
            == (result.decision is LossExecutionEntryDecision.ALLOW)
            and result.generated_at <= now
            and (
                result.revision is None
                and result.sequence is None
                or (
                    type(result.revision) is int
                    and result.revision >= 1
                    and type(result.sequence) is int
                    and result.sequence >= 1
                )
            )
            and (
                not result.allowed
                or (
                    result.revision is not None
                    and result.sequence is not None
                )
            )
            and result.submitted is False
            and result.order_created is False
            and result.provider_call is False
            and result.exchange_call is False
        )
        if not valid:
            return False, self._entry_rejection(
                "MONEY_MANAGEMENT_GUARD_INVALID"
            )

        self.last_money_management_guard = result.to_dict()
        if not result.allowed:
            return False, self._entry_rejection(
                result.reason.value,
                result,
            )
        return True, None

    def clear_execution_entry_preflight(self, trace_id=None):
        """Discard an unused MM admission, for example after Governance BLOCK."""

        with self.execution_entry_guard_lock:
            current = self.execution_entry_preapproval
            if (
                trace_id is None
                or not isinstance(current, dict)
                or current.get("traceId") == trace_id
            ):
                self.execution_entry_preapproval = None

    def preflight_execution_entry(self, side, trace_id):
        """Evaluate the exact candidate at MM before Governance.

        This is fail-closed and creates no order, position, provider call, or
        exchange call. A successful decision is valid only for the matching
        synchronous engine handoff and is consumed there.
        """

        normalized_side = str(side or "").strip().upper()
        if normalized_side not in {"BUY", "SELL"} or not trace_id:
            return {
                "allowed": False,
                "decision": "BLOCK",
                "reason": "EXECUTION_INTENT_INVALID",
            }
        if self.pending_order:
            return {
                "allowed": False,
                "decision": "BLOCK",
                "reason": "PENDING_ORDER_REMAINING",
            }
        if self.actual_position is not None:
            return {
                "allowed": False,
                "decision": "BLOCK",
                "reason": "POSITION_ALREADY_OPEN",
            }

        price = self.get_price()
        preview = self.get_result().get("preview", {})
        quantity = preview.get("qty")
        if (
            not price
            or price <= 0
            or preview.get("valid") is not True
            or not quantity
            or quantity <= 0
        ):
            return {
                "allowed": False,
                "decision": "BLOCK",
                "reason": preview.get("reason") or "ENTRY_PREVIEW_INVALID",
            }

        order = {
            "symbol": self.symbol,
            "side": normalized_side,
            "qty": quantity,
            "price": price,
            "traceId": trace_id,
        }
        self.clear_execution_entry_preflight()
        allowed, rejection = self._evaluate_execution_entry_guard(order)
        decision = dict(self.last_money_management_guard or {})
        if not allowed:
            rejection = dict(rejection or {})
            return {
                **decision,
                "allowed": False,
                "decision": rejection.get("decision") or "BLOCK",
                "reason": rejection.get("reason") or "MONEY_MANAGEMENT_BLOCKED",
                "suggestedQuantity": quantity,
                "approvedQuantity": None,
            }

        decision.update({
            "allowed": True,
            "decision": "ALLOW",
            "suggestedQuantity": quantity,
            "approvedQuantity": quantity,
        })
        with self.execution_entry_guard_lock:
            self.execution_entry_preapproval = {
                "traceId": trace_id,
                "side": normalized_side,
                "quantity": str(quantity),
                "expiresAt": time.time() + 5.0,
                "decision": dict(decision),
            }
        return decision

    def submit_signal(self, signal):

        if not signal:
            return

        signal_id = signal.get("id")

        if signal_id:

            if signal_id == self.last_signal_id:

                runtime_debug("ExecutionEngine duplicate signal blocked")

                return

            self.last_signal_id = signal_id

        # =====================================
        # EARLY COOLDOWN BLOCK
        # =====================================

        if (
            self.last_execution_time
            and
            time.time()
            - self.last_execution_time
            < 3
        ):

            runtime_debug("ExecutionEngine early cooldown blocked signal")

            return

        self.last_signal_time = time.time()

        return self.try_entry(signal)

    # =====================================
    # PRICE
    # =====================================

    def get_price(self):

        try:

            if not self.price_manager or not self.symbol:
                return 0.0

            result = self.price_manager.get_current_price()

            runtime_debug(
                "ExecutionEngine price symbol=%s result=%s",
                self.symbol,
                result,
            )

            return result

        except Exception:

            self.logger.exception("GET_PRICE EXCEPTION")

            return 0.0

    def flatten_paper_position(
        self,
        price=None,
        reason="EMERGENCY_FLATTEN"
    ):

        symbol = self.symbol

        if not self.actual_position:

            result = {
                "success": True,
                "mode": "paper",
                "symbol": symbol,
                "requested": 0,
                "flattened": 0,
                "failed": 0,
                "skipped": True,
                "results": [],
                "error": None,
                "timestamp": time.time(),
            }

            runtime_debug("Paper flatten result=%s", result)

            return result

        position_before = copy.deepcopy(
            self.actual_position
        )

        def valid_price(value):
            try:
                value = float(value)
            except (TypeError, ValueError):
                return None

            if not math.isfinite(value) or value <= 0:
                return None

            return value

        flatten_price = valid_price(price)

        if flatten_price is None:
            flatten_price = valid_price(self.latest_price)

        if flatten_price is None:
            try:
                flatten_price = valid_price(self.get_price())
            except Exception as e:
                result = {
                    "success": False,
                    "mode": "paper",
                    "symbol": symbol,
                    "requested": 1,
                    "flattened": 0,
                    "failed": 1,
                    "skipped": False,
                    "results": [],
                    "error": str(e),
                    "position_after": copy.deepcopy(
                        self.actual_position
                    ),
                    "timestamp": time.time(),
                }

                runtime_debug("Paper flatten result=%s", result)

                return result

        if flatten_price is None:

            result = {
                "success": False,
                "mode": "paper",
                "symbol": symbol,
                "requested": 1,
                "flattened": 0,
                "failed": 1,
                "skipped": False,
                "results": [],
                "error": "INVALID_FLATTEN_PRICE",
                "position_after": copy.deepcopy(
                    self.actual_position
                ),
                "timestamp": time.time(),
            }

            runtime_debug("Paper flatten result=%s", result)

            return result

        try:
            self.close_position(flatten_price, reason)
        except Exception as e:
            self.logger.exception("PAPER FLATTEN CLOSE EXCEPTION")

            result = {
                "success": False,
                "mode": "paper",
                "symbol": symbol,
                "requested": 1,
                "flattened": 0,
                "failed": 1,
                "skipped": False,
                "results": [],
                "error": str(e),
                "position_before": position_before,
                "position_after": copy.deepcopy(
                    self.actual_position
                ),
                "timestamp": time.time(),
            }

            runtime_debug("Paper flatten result=%s", result)

            return result

        if self.actual_position is not None:

            result = {
                "success": False,
                "mode": "paper",
                "symbol": symbol,
                "requested": 1,
                "flattened": 0,
                "failed": 1,
                "skipped": False,
                "results": [],
                "error": "POSITION_NOT_CLOSED",
                "position_before": position_before,
                "position_after": copy.deepcopy(
                    self.actual_position
                ),
                "timestamp": time.time(),
            }

            runtime_debug("Paper flatten result=%s", result)

            return result

        try:
            if (
                self.portfolio
                and symbol
                and hasattr(self.portfolio, "positions")
            ):
                if hasattr(self.portfolio, "lock"):
                    with self.portfolio.lock:
                        self.portfolio.positions.pop(
                            symbol,
                            None
                        )
                else:
                    self.portfolio.positions.pop(
                        symbol,
                        None
                    )
        except Exception as e:
            self.logger.exception("PAPER FLATTEN PORTFOLIO SYNC EXCEPTION")

            result = {
                "success": False,
                "mode": "paper",
                "symbol": symbol,
                "requested": 1,
                "flattened": 1,
                "failed": 1,
                "skipped": False,
                "results": [{
                    "symbol": symbol,
                    "success": True,
                    "reason": reason,
                    "price": flatten_price,
                    "position_before": position_before,
                }],
                "error": str(e),
                "position_after": None,
                "timestamp": time.time(),
            }

            runtime_debug("Paper flatten result=%s", result)

            return result

        result = {
            "success": True,
            "mode": "paper",
            "symbol": symbol,
            "requested": 1,
            "flattened": 1,
            "failed": 0,
            "skipped": False,
            "results": [{
                "symbol": symbol,
                "success": True,
                "reason": reason,
                "price": flatten_price,
                "position_before": position_before,
            }],
            "error": None,
            "timestamp": time.time(),
        }

        runtime_debug("Paper flatten result=%s", result)

        return result


    # =====================================
    # POSITION STATE
    # =====================================

    def set_position_state(
        self,
        state
    ):

        if not self.actual_position:

            return

        old_state = self.actual_position.get(
            "state"
        )

        # =====================================
        # SKIP DUPLICATE
        # =====================================

        if old_state == state:

            return

        self.actual_position["state"] = state

        add_log(
            f"🟢 POSITION STATE: "
            f"{old_state} -> {state}"
        )


    # =====================================
    # POSITION CHECK
    # =====================================

    def has_open_position(self):

        return bool(
            self.actual_position
        )


    # =====================================
    # ENTRY
    # =====================================

    def try_entry(self, signal):

        with self.execution_entry_admission_lock:
            if self.execution_entry_admission_in_progress:
                return self._entry_rejection(
                    "EXECUTION_ENTRY_IN_PROGRESS"
                )
            self.execution_entry_admission_in_progress = True

        try:
            authority_allowed, authority_context = (
                self._evaluate_execution_authority_guard(signal)
            )
            if not authority_allowed:
                return authority_context
            return self._try_entry_candidate(signal, authority_context)
        finally:
            with self.execution_entry_admission_lock:
                self.execution_entry_admission_in_progress = False

    def _try_entry_candidate(self, signal, authority_context=None):
        runtime_debug(
            "ExecutionEngine try_entry engine_id=%s symbol=%s signal=%s",
            self.engine_id,
            self.symbol,
            signal,
        )

        # =====================================
        # DUPLICATE PREVENTION
        # =====================================

        if self.pending_order:

            runtime_debug("ExecutionEngine blocked: pending order")

            return

        # =====================================
        # EXECUTION COOLDOWN
        # =====================================

        runtime_debug(
            "ExecutionEngine cooldown last_execution=%s type=%s",
            self.last_execution_time,
            type(self.last_execution_time).__name__,
        )

        cooldown_seconds = 3

        if (
            self.last_execution_time
            and
            time.time() - self.last_execution_time
            < cooldown_seconds
        ):

            runtime_debug("ExecutionEngine cooldown blocked signal")

            return

        # =====================================
        # MARKET STALE CHECK
        # =====================================

        if time.time() - self.last_market_update > 5:

            self.price_ready = False

            runtime_debug(
                "ExecutionEngine blocked: stale market; price readiness reset"
            )

            return

        # =====================================
        # PRICE READY
        # =====================================

        if not self.price_ready:

            runtime_debug("ExecutionEngine blocked: price not ready")

            return

        # =====================================
        # STALE PROTECTION
        # =====================================

        if time.time() - self.last_market_update > 5:

            runtime_debug("ExecutionEngine blocked: stale market")

            return

        # =====================================
        # POSITION EXISTS
        # =====================================

        if self.actual_position:

            state = self.actual_position.get(
                "state",
                "OPEN"
            )

            qty = self.actual_position.get(
                "qty",
                0
            )

            runtime_debug(
                "ExecutionEngine position check state=%s qty=%s",
                state,
                qty,
            )

            # =================================
            # AUTHORITATIVE OPEN CHECK
            # =================================

            if state == "OPEN":

                runtime_debug("ExecutionEngine blocked: open position exists")

                return

        # =====================================
        # PRICE
        # =====================================

        price = self.get_price()

        if not price or price <= 0:

            runtime_debug("ExecutionEngine skipped entry: no price")

            return

        risk_state = self.update_drawdown_state()

        if risk_state.get("riskTradingDisabled"):

            runtime_debug(
                "ExecutionEngine blocked by risk state=%s",
                risk_state,
            )

            return

        # =====================================
        # PREVIEW
        # =====================================

        entry_authority = (
            str(signal.get("entryAuthority") or "").strip().upper()
            if isinstance(signal, dict)
            else ""
        )

        preview = self.get_result()["preview"]

        runtime_debug("ExecutionEngine preview=%s", preview)

        if entry_authority == "MANUAL":
            # Manual entry binds the exact quantity approved by the Money
            # Management admission.  It is never silently recalculated here.
            # A changed context (invalidated preview) fails closed instead of
            # submitting a different quantity than the one that was approved.
            bound_quantity = (
                signal.get("boundQuantity")
                if isinstance(signal, dict)
                else None
            )
            if (
                isinstance(bound_quantity, bool)
                or not isinstance(bound_quantity, (int, float))
                or not math.isfinite(float(bound_quantity))
                or float(bound_quantity) <= 0
            ):
                return self._entry_rejection(
                    "INVALID_MANUAL_QUANTITY"
                )
            if preview.get("valid") is not True:
                return self._entry_rejection("DENY_STALE_INTENT")
            qty = bound_quantity
            valid = True
        else:
            qty = preview.get("qty", 0)

            valid = preview.get("valid", False)

        # =====================================
        # PREVIEW VALIDATION
        # =====================================

        if not valid:

            # =====================================
            # INVALID PREVIEW COOLDOWN
            # =====================================

            self.last_execution_time = time.time()

            runtime_debug(
                "ExecutionEngine preview invalid reason=%s",
                preview.get("reason"),
            )

            return

        if qty <= 0:

            runtime_debug("ExecutionEngine preview quantity was zero")

            return

        # =====================================
        # TEMP VALIDATION MODE
        # SKIP MIN_QTY CHECK
        # =====================================

        order = {
            "symbol": self.symbol,
            "side": str(signal.get("side")).upper(),
            "qty": qty,
            "price": price,
            "traceId": signal.get("traceId"),
        }

        try:
            authority = self._order_sizing_authority(price=price, fresh=True)
            authority.validate(number(qty) / authority.multiplier, approved_base=preview.get("qty"))
        except Exception as exc:
            return self._entry_rejection(str(exc) if isinstance(exc, SizingRejected)
                                         else "SIZING_AUTHORITY_UNAVAILABLE")

        # A manual entry may only commit the exact MM admission that was
        # reserved for this request.  An expired or mismatched admission must
        # never fall through to a fresh Money Management recalculation.
        if entry_authority == "MANUAL" and not (
            self._entry_preapproval_matches(order)
        ):
            return self._entry_rejection("DENY_STALE_INTENT")

        add_log(f"🟡 ORDER: {order}")

        live_order_allowed = None
        if self.mode != "paper" and not self.config["dry_run"]:
            live_order_allowed = self._live_order_allowed(authority_context)
            if not live_order_allowed:
                add_log(
                    "LIVE ORDER BLOCKED: LIVE_NOT_READY",
                    "warning",
                )
                runtime_debug(
                    "Live order blocked reasons=%s",
                    self.last_live_block_reasons,
                )
                if hasattr(self.exchange, "set_live_order_gate"):
                    self.exchange.set_live_order_gate(
                        False,
                        self.last_live_block_reasons,
                    )
                return

        guard_allowed, guard_rejection = (
            self._evaluate_execution_entry_guard(order)
        )
        if not guard_allowed:
            self.last_order_blocked_reason = guard_rejection.get(
                "reason"
            )
            runtime_debug(
                "ExecutionEngine entry rejected operation=%s "
                "decision=%s reason=%s revision=%s sequence=%s mode=%s",
                guard_rejection.get("operation"),
                guard_rejection.get("decision"),
                guard_rejection.get("reason"),
                guard_rejection.get("revision"),
                guard_rejection.get("sequence"),
                self.mode,
            )
            return guard_rejection

        # =====================================
        # EXECUTION LOCK
        # =====================================

        with self.execution_entry_admission_lock:
            if self.pending_order or self.actual_position is not None:
                return self._entry_rejection(
                    "EXECUTION_STATE_CHANGED"
                )
            self.pending_order = True

        try:

            # =====================================
            # PAPER
            # =====================================

            if self.mode == "paper":

                raw_res = place_order_safe(
                    self.portfolio,
                    order
                )

                runtime_debug("Paper execution raw result=%s", raw_res)

                res = {
                    "success": raw_res.get(
                        "success",
                        False
                    ),
                    "raw": raw_res
                }

            # =====================================
            # LIVE
            # =====================================

            else:

                # =====================================
                # DRY RUN GUARD
                # =====================================

                if self.config["dry_run"]:

                    add_log(
                        "🟡 DRY RUN ACTIVE"
                    )

                    return

                if live_order_allowed is not True:

                    add_log(
                        "🛑 LIVE ORDER BLOCKED: LIVE_NOT_READY",
                        "warning",
                    )

                    runtime_debug(
                        "Live order blocked reasons=%s",
                        self.last_live_block_reasons,
                    )

                    if hasattr(
                        self.exchange,
                        "set_live_order_gate",
                    ):
                        self.exchange.set_live_order_gate(
                            False,
                            self.last_live_block_reasons,
                        )

                    return

                if hasattr(
                    self.exchange,
                    "set_live_order_gate",
                ):
                    self.exchange.set_live_order_gate(
                        True,
                        [],
                    )

                raw_res = self.exchange.place_order(
                    symbol=order["symbol"],
                    side=order["side"],
                    qty=order["qty"],
                    price=order["price"],
                    leverage=self.config.get("effective_leverage"),
                    sizing_validator=lambda **final: self._validate_final_entry_quantity(
                        **final, approved_base=qty, side=order["side"], trace_id=order.get("traceId")),
                )

                runtime_debug("Live execution raw result=%s", raw_res)

                res = {
                    "success": raw_res.get(
                        "success",
                        False
                    ),
                    "raw": raw_res
                }

            add_log(f"🟢 EXECUTION RESULT: {res}")

            # =====================================
            # RESULT VALIDATION
            # =====================================

            if not res:

                add_log("❌ invalid execution result", "error")

                return


            if not res.get("success"):

                add_log("❌ execution failed", "error")

                return


            if self.actual_position:

                runtime_debug(
                    "ExecutionEngine blocked result: position already exists"
                )

                return


            add_log("✅ execution success")

            # =====================================
            # AUTHORITATIVE BALANCE REFRESH
            # =====================================

            try:

                self.refresh_balance()

            except Exception as e:

                add_log(
                    f"❌ BALANCE REFRESH ERROR: "
                    f"{e}",
                    "error",
                )

            # =====================================
            # PAPER POSITION
            # =====================================

            if self.mode == "paper":

                paper_order_id = (
                    f"paper-{self.engine_id}-{signal.get('id') or int(time.time() * 1000)}"
                )
                filled_at = time.time()
                runtime_context = signal.get("runtimeSymbolContext")
                if not isinstance(runtime_context, dict):
                    runtime_context = {}
                source_identity = {
                    key: runtime_context.get(key)
                    for key in (
                        "contextKey", "runtimeInstanceId", "runtimeId", "exchangeSymbol",
                    )
                    if runtime_context.get(key) is not None
                }
                self.paper_orders.append({
                    "orderId": paper_order_id,
                    "mode": "paper",
                    "status": "FILLED",
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "qty": qty,
                    "price": price,
                    "signalId": signal.get("id"),
                    "traceId": signal.get("traceId"),
                    "createdAt": filled_at,
                    "entryAuthority": entry_authority or None,
                    "requestId": signal.get("requestId"),
                    **source_identity,
                })
                self.paper_fills.append({
                    "fillId": f"{paper_order_id}-fill-1",
                    "orderId": paper_order_id,
                    "traceId": signal.get("traceId"),
                    "mode": "paper",
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "qty": qty,
                    "price": price,
                    "filledAt": filled_at,
                    "fillType": "ENTRY",
                    "tradeId": paper_order_id,
                    "entryAuthority": entry_authority or None,
                    "requestId": signal.get("requestId"),
                    **source_identity,
                })

                rules = (
                    self.exchange.get_symbol_rules(
                        self.symbol
                    )
                    if self.exchange
                    else {
                        "multiplier": 0.001
                    }
                )

                multiplier = rules.get(
                    "multiplier",
                    0.001
                )

                contracts = qty / multiplier

                target_prices = self._target_prices(
                    order["side"],
                    price,
                )

                trailing_enabled = bool(
                    self.config["trailing_stop"]
                )

                trailing_distance = (
                    self._trailing_distance_percent()
                )

                self.actual_position = {
                    "state": "OPEN",

                    "side": order["side"],

                    "entry_price": price,

                    # authoritative contract qty
                    "qty": contracts,

                    # normalized coin qty
                    "coin_qty": qty,

                    # contract spec
                    "multiplier": multiplier,

                    "entry_time": time.time(),

                    "signal_id": signal.get("id"),

                    "trace_id": signal.get("traceId"),

                    "entry_authority": entry_authority or None,

                    "request_id": signal.get("requestId"),

                    "runtimeSymbolContext": signal.get("runtimeSymbolContext"),

                    "order_id": paper_order_id,

                    "sl": target_prices["sl"],

                    "tp": target_prices["tp"],

                    "tp_percent": self.config["tp_percent"],

                    "sl_percent": self.config["sl_percent"],

                    "position_size": (
                        preview.get("position_size")
                    ),

                    "trailing": trailing_enabled,

                    "trailing_distance_percent": (
                        trailing_distance
                    ),

                    "trailing_reference_price": (
                        price
                    ),

                    "trailing_stop_price": (
                        target_prices["sl"]
                        if trailing_enabled
                        else None
                    ),
                }

                add_log(
                    "📦 PAPER POSITION OPENED"
                )

            # =====================================
            # LIVE POSITION SYNC
            # =====================================

            else:

                try:

                    pos = self.exchange.get_positions(
                        self.symbol
                    )

                    # New lifecycle: reconstruct protection from the exchange
                    # entry price and the configured SL/TP authority.
                    self.actual_position = (
                        self._attach_live_position_protection(pos)
                    )

                    if pos:
                        # A newly observed exchange position begins a new
                        # lifecycle; do not carry the previous close marker.
                        self.live_close_state = None
                        self.live_close_in_flight = False

                    add_log("📦 LIVE POSITION OPENED")

                except Exception as e:

                    add_log(
                        f"❌ POSITION FETCH ERROR: {e}",
                        "error",
                    )

            self.last_execution_time = time.time()

        except Exception as e:

            add_log(
                f"❌ Order Error: {e}",
                "error",
            )

        finally:

            # =====================================
            # ALWAYS UNLOCK
            # =====================================

            self.pending_order = False

            runtime_debug("ExecutionEngine pending order reset")

    # =====================================
    # CLOSE
    # =====================================

    def _live_close_evidence_fresh(self, value):
        if not isinstance(value, dict):
            return False
        timestamp = value.get("timestamp")
        if isinstance(timestamp, bool):
            return False
        try:
            age = time.time() - float(timestamp)
        except (TypeError, ValueError, OverflowError):
            return False
        return (
            math.isfinite(age)
            and 0 <= age <= self.LIVE_CLOSE_EVIDENCE_MAX_AGE_SECONDS
        )

    def _live_close_position_state(self, position):
        """Classify only the authenticated KuCoin position response shape."""
        if (
            not isinstance(position, dict)
            or position.get("success") is not True
            or type(position.get("found")) is not bool
            or not self._live_close_evidence_fresh(position)
        ):
            return "UNKNOWN"

        quantity = position.get("quantity")
        signed_quantity = position.get("signed_quantity")
        if isinstance(quantity, bool) or isinstance(signed_quantity, bool):
            return "UNKNOWN"
        try:
            quantity = float(quantity)
            signed_quantity = float(signed_quantity)
        except (TypeError, ValueError, OverflowError):
            return "UNKNOWN"
        if not math.isfinite(quantity) or not math.isfinite(signed_quantity):
            return "UNKNOWN"

        if position["found"] is False:
            return "FLAT" if quantity == 0 and signed_quantity == 0 else "UNKNOWN"
        return "NON_FLAT" if quantity > 0 and signed_quantity != 0 else "UNKNOWN"

    def _live_close_open_order_state(self, orders):
        if (
            not isinstance(orders, dict)
            or orders.get("success") is not True
            or not self._live_close_evidence_fresh(orders)
        ):
            return "UNKNOWN"
        count = orders.get("count")
        entries = orders.get("orders")
        if (
            type(count) is not int
            or count < 0
            or not isinstance(entries, list)
            or len(entries) != count
        ):
            return "UNKNOWN"
        return "FLAT" if count == 0 else "REMAINING"

    def _read_live_close_authority(self, symbol):
        exchange = self.exchange
        try:
            position = exchange.get_current_position(symbol)
        except Exception:
            position = None
        try:
            orders = exchange.get_open_orders(symbol)
        except Exception:
            orders = None
        return {
            "position": position,
            "positionState": self._live_close_position_state(position),
            "openOrders": orders,
            "openOrderState": self._live_close_open_order_state(orders),
        }

    def _reconcile_live_close(self, symbol, flatten):
        """Poll position/order authority without ever resubmitting a close."""
        accepted = flatten.get("accepted") is True
        skipped = flatten.get("skipped") is True
        order_id = flatten.get("order_id")
        final_position = flatten.get("final_position")
        position_state = self._live_close_position_state(final_position)
        last_authority = {
            "position": final_position,
            "positionState": position_state,
            "openOrders": None,
            "openOrderState": "UNKNOWN",
        }

        # Adapter-level FLAT evidence is not complete until the symbol's active
        # order collection is authoritatively empty.
        if position_state == "FLAT":
            try:
                orders = self.exchange.get_open_orders(symbol)
            except Exception:
                orders = None
            last_authority.update({
                "openOrders": orders,
                "openOrderState": self._live_close_open_order_state(orders),
            })
            if last_authority["openOrderState"] == "FLAT":
                return {
                    "success": True,
                    "status": "CONFIRMED",
                    "confirmed": True,
                    "closed": True,
                    "accepted": accepted,
                    "skipped": skipped,
                    "reason": "EXCHANGE_CLOSE_CONFIRMED",
                    "reconciliationAttempts": 0,
                    "positionAuthority": final_position,
                    "openOrderAuthority": orders,
                    "positionState": "FLAT",
                    "openOrderState": "FLAT",
                    "order_id": order_id,
                }

        if not accepted and not skipped:
            return {
                "success": False,
                "status": "REJECTED",
                "confirmed": False,
                "closed": False,
                "accepted": False,
                "reason": "EXCHANGE_CLOSE_REJECTED",
                "reconciliationAttempts": 0,
                "positionAuthority": final_position,
                "openOrderAuthority": last_authority["openOrders"],
                "positionState": last_authority["positionState"],
                "openOrderState": last_authority["openOrderState"],
                "order_id": order_id,
            }

        for attempt in range(1, self.LIVE_CLOSE_RECONCILIATION_ATTEMPTS + 1):
            self.live_close_state = {
                "success": False,
                "status": "RECONCILING",
                "confirmed": False,
                "closed": False,
                "accepted": accepted,
                "reason": "CLOSE_ACCEPTED_PENDING_RECONCILIATION",
                "reconciliationAttempts": attempt - 1,
                "order_id": order_id,
            }
            time.sleep(self.LIVE_CLOSE_RECONCILIATION_INTERVAL_SECONDS)
            last_authority = self._read_live_close_authority(symbol)
            if (
                last_authority["positionState"] == "FLAT"
                and last_authority["openOrderState"] == "FLAT"
            ):
                return {
                    "success": True,
                    "status": "CONFIRMED",
                    "confirmed": True,
                    "closed": True,
                    "accepted": accepted,
                    "skipped": skipped,
                    "reason": "EXCHANGE_CLOSE_CONFIRMED",
                    "reconciliationAttempts": attempt,
                    "positionAuthority": last_authority["position"],
                    "openOrderAuthority": last_authority["openOrders"],
                    "positionState": "FLAT",
                    "openOrderState": "FLAT",
                    "order_id": order_id,
                }

        if last_authority["positionState"] == "NON_FLAT":
            failure_reason = "EXCHANGE_CLOSE_PARTIAL"
        elif last_authority["positionState"] == "UNKNOWN":
            failure_reason = "EXCHANGE_POSITION_UNKNOWN"
        elif last_authority["openOrderState"] == "REMAINING":
            failure_reason = "OPEN_CLOSE_ORDER_REMAINS"
        else:
            failure_reason = "OPEN_ORDER_STATE_UNKNOWN"
        return {
            "success": False,
            "status": "RECONCILIATION_FAILED",
            "confirmed": False,
            "closed": False,
            "accepted": accepted,
            "reason": failure_reason,
            "reconciliationAttempts": self.LIVE_CLOSE_RECONCILIATION_ATTEMPTS,
            "positionAuthority": last_authority["position"],
            "openOrderAuthority": last_authority["openOrders"],
            "positionState": last_authority["positionState"],
            "openOrderState": last_authority["openOrderState"],
            "order_id": order_id,
        }

    def _live_close_via_exchange(self, symbol):
        """Submit and classify a normal (non-emergency) LIVE close.

        Reuses the exchange adapter's reduceOnly flatten primitive
        (:meth:`flatten_current_position`) so close order construction is not
        duplicated.  This is the real exchange-side close; the caller may only
        move local state to FLAT when the primitive reports authoritative
        confirmation.  Partial / unknown / rejected / timeout closings fail
        closed and preserve the open position.
        """
        result = {
            "success": False,
            "status": "UNKNOWN",
            "confirmed": False,
            "closed": False,
            "exchangeCall": False,
            "reason": "EXCHANGE_CLOSE_UNAVAILABLE",
        }
        exchange = self.exchange
        if exchange is None or not callable(
            getattr(exchange, "flatten_current_position", None)
        ):
            result.update({
                "reason": "EXCHANGE_CLOSE_CAPABILITY_MISSING",
            })
            self.live_close_state = dict(result)
            return result

        try:
            flatten = exchange.flatten_current_position(symbol)
        except Exception as e:
            result.update({
                "reason": "EXCHANGE_CLOSE_EXCEPTION",
                "error": str(e),
            })
            self.live_close_state = dict(result)
            return result

        if not isinstance(flatten, dict):
            result.update({
                "reason": "EXCHANGE_CLOSE_UNKNOWN",
            })
            self.live_close_state = dict(result)
            return result

        result["exchangeCall"] = True
        result["symbol"] = flatten.get("symbol")
        result["order_id"] = flatten.get("order_id")
        result["raw_order"] = flatten.get("raw_order")
        result["final_position"] = flatten.get("final_position")
        result["error_code"] = flatten.get("error_code")

        accepted = bool(flatten.get("accepted"))
        error_code = flatten.get("error_code")
        result["accepted"] = accepted

        if not accepted and not (
            flatten.get("confirmed") is True
            and flatten.get("skipped") is True
        ):
            result.update({
                "status": "REJECTED",
                "reason": "EXCHANGE_CLOSE_REJECTED",
            })
        else:
            result.update(self._reconcile_live_close(symbol, flatten))
            result["raw_order"] = flatten.get("raw_order")
            result["final_position"] = result.get("positionAuthority")
            result["error_code"] = error_code

        self.live_close_state = dict(result)
        return result

    def close_position(self, price, reason):
        """Shared close boundary. Exactly one close may commit per position.

        Manual close, SL, TP, trailing, natural/time exit and emergency flatten
        all pass through here.  A concurrent or repeated close is rejected as
        ``CLOSE_IN_PROGRESS`` / ``ALREADY_CLOSED`` instead of producing a second
        fill, history record or PnL commit.
        """

        with self.close_authority_lock:

            if self.close_reservation is not None:
                return {
                    "success": False,
                    "status": "ALREADY_CLOSED",
                    "reason": "CLOSE_IN_PROGRESS",
                    "closed": False,
                    "confirmed": False,
                    "closedBy": self.close_reservation.get("reason"),
                }

            if not self.actual_position:
                return None

            position_before = copy.deepcopy(self.actual_position)

            reservation = {
                "positionId": (
                    position_before.get("position_id")
                    or position_before.get("order_id")
                ),
                "side": position_before.get("side"),
                "reason": reason,
                "startedAt": time.time(),
            }
            self.close_reservation = reservation

            try:
                return self._close_position_body(price, reason)
            finally:
                if self.close_reservation is reservation:
                    self.close_reservation = None

    @staticmethod
    def _attach_position_parameter_context(record, position_before):
        """Retain the entry parameter context on a closed-trade record.

        Metadata only.  The entry ``parameter_snapshot`` was bound to the
        position at entry by the execution runtime; copying it here preserves
        the authority the trade was actually observed under.  This never reads
        the current registry and never changes an order, a close or a quantity.
        """

        if not isinstance(record, dict) or not isinstance(position_before, dict):
            return record

        # Explicit entry control source: a human MANUAL entry is distinguished
        # from the automatic BOT strategy entry.  Metadata only; it never changes
        # an order, a close, a quantity or any authority.
        entry_authority = str(
            position_before.get("entry_authority") or ""
        ).strip().upper()
        record["controlSource"] = (
            entry_authority if entry_authority in ("MANUAL", "BOT") else "UNKNOWN"
        )

        snapshot = position_before.get("parameter_snapshot")
        if not isinstance(snapshot, dict) or not snapshot:
            return record

        record["parameterSnapshot"] = copy.deepcopy(snapshot)
        record["parameterScope"] = (
            snapshot.get("canonicalScope") or snapshot.get("scope")
        )
        record["parameterSetId"] = snapshot.get("parameterSetId")
        record["configuredRevision"] = snapshot.get("configuredRevision")
        record["effectiveRevision"] = snapshot.get("effectiveRevision")
        record["parameterRevision"] = snapshot.get("effectiveRevision")
        record["featureContract"] = snapshot.get("featureContract")
        return record

    def _close_position_body(self, price, reason):

        add_log(f"🚪 CLOSE ({reason})")

        if not self.actual_position:
            return None

        live_close = None

        # =====================================
        # NORMAL LIVE EXIT: real reduceOnly close
        # =====================================
        # A natural LIVE exit must submit a real exchange-side reduceOnly close
        # and only move local state to FLAT on authoritative exchange evidence.
        # A paper / dry-run exit stays simulation-only (unchanged).
        if self.mode == "live" and not self.config.get("dry_run", True):
            if self.live_close_in_flight:
                # Do not send repeated blind close orders while a prior close is
                # accepted-but-unconfirmed.  Fail closed.
                return dict(self.live_close_state or {
                    "success": False,
                    "status": "UNKNOWN",
                    "confirmed": False,
                    "closed": False,
                    "reason": "EXCHANGE_CLOSE_PENDING",
                })
            self.pending_order = True
            live_close = self._live_close_via_exchange(self.symbol)
            if live_close.get("confirmed") is not True:
                self.live_close_state = dict(live_close)
                self.live_close_in_flight = True
                add_log(
                    f"🔒 LIVE CLOSE UNCONFIRMED ({reason}): "
                    f"{live_close.get('status')}"
                )
                return live_close

        entry = self.actual_position.get(
            "entry_price",
            price
        )

        contracts = self.actual_position.get(
            "qty",
            0
        )

        multiplier = self._position_multiplier(
            self.actual_position
        )

        side = self.actual_position.get(
            "side"
        )

        pnl_available = multiplier is not None

        if not pnl_available:

            # LIVE without an authoritative contract multiplier: the local
            # PnL estimate is unavailable (recorded as None, never guessed).
            coin_qty = None
            pnl = 0.0

        else:

            coin_qty = (
                contracts * multiplier
            )

            if self._is_short(side):

                pnl = (
                    (entry - price)
                    * coin_qty
                )

            else:

                pnl = (
                    (price - entry)
                    * coin_qty
                )

        position_before = copy.deepcopy(self.actual_position)

        if not pnl_available:
            # Do NOT book a fabricated 0 into cumulative PnL / balance /
            # drawdown.  Mark local accounting unavailable (visible in risk
            # state and live readiness) until an authoritative resync.
            self.live_pnl_accounting_unavailable = {
                "reason": LIVE_PNL_ACCOUNTING_UNAVAILABLE,
                "cause": "LIVE_CONTRACT_MULTIPLIER_UNAVAILABLE",
                "symbol": self.symbol,
                "closeReason": reason,
                "at": time.time(),
            }
            add_log(
                f"⛔ {LIVE_PNL_ACCOUNTING_UNAVAILABLE}: close PnL not "
                f"computable (no contract multiplier); entries blocked "
                f"until exchange resync",
                "error",
            )
        else:
            self.pnl += pnl

        paper_portfolio_position = bool(
            self.mode == "paper"
            and self.portfolio
            and self.symbol
            and self.symbol in self.portfolio.get_positions()
        )

        if paper_portfolio_position:
            # place_order_safe opened the authoritative simulated portfolio
            # position.  Close it through the matching simulation boundary so
            # positions, realized PnL and balance stay consistent.
            portfolio_pnl = self.portfolio.close_position(
                self.symbol,
                price,
            )
            self.balance = self.portfolio.balance
            pnl = portfolio_pnl
        elif pnl_available:
            self.balance += pnl
            if self.mode == "paper" and self.portfolio:
                self.portfolio.balance = self.balance

        self.unrealized_pnl = 0

        runtime_debug(
            "Position accounting balance=%.4f cumulative_pnl=%.4f",
            self.balance,
            self.pnl,
        )

        if self.portfolio and self.mode != "paper":
            self.portfolio.balance = self.balance

        self.update_drawdown_state(
            self._current_equity()
        )

        add_log(
            f"💰 PnL: {pnl:.4f}" if pnl_available else "💰 PnL: UNAVAILABLE"
        )

        if self.mode == "paper":
            closed_at = time.time()
            history_record = {
                "tradeId": (
                    position_before.get("order_id")
                    or f"paper-trade-{self.engine_id}-{int(closed_at * 1000)}"
                ),
                "mode": "paper",
                "traceId": position_before.get("trace_id"),
                "status": "CLOSED",
                "symbol": self.symbol,
                "side": side,
                "qty": coin_qty,
                "entryPrice": entry,
                "exitPrice": price,
                "pnl": pnl,
                "reason": reason,
                "openedAt": position_before.get("entry_time"),
                "closedAt": closed_at,
                "balanceAfter": self.balance,
            }
            runtime_context = position_before.get("runtimeSymbolContext")
            if not isinstance(runtime_context, dict):
                runtime_context = {}
            source_identity = {
                key: runtime_context.get(key)
                for key in (
                    "contextKey", "runtimeInstanceId", "runtimeId", "exchangeSymbol",
                )
                if runtime_context.get(key) is not None
            }
            history_record.update(source_identity)
            self._attach_position_parameter_context(
                history_record, position_before
            )
            trade_id = history_record["tradeId"]
            self.paper_fills.append({
                "fillId": f"{trade_id}-close-fill-1",
                "orderId": position_before.get("order_id"),
                "tradeId": trade_id,
                "traceId": position_before.get("trace_id"),
                "mode": "paper",
                "fillType": "CLOSE",
                "symbol": self.symbol,
                "side": "BUY" if self._is_short(side) else "SELL",
                "positionSide": side,
                "qty": coin_qty,
                "price": price,
                "filledAt": closed_at,
                "reason": reason,
                **source_identity,
            })
            self.trade_history.append(history_record)
            # Durable Stage 13 parameter-performance record.  Observational and
            # best-effort: it can never affect P&L, a close or an order.
            try:
                from backend.runtime.parameter_performance import (
                    record_completed_trade,
                )
                record_completed_trade(history_record)
            except Exception:
                pass
            # Trace recording is intentionally best-effort and cannot affect P&L.
            trace_id = position_before.get("trace_id")
            if trace_id:
                try:
                    from backend.runtime.trading_trace import safe_record
                    runtime_context = position_before.get("runtimeSymbolContext") or {}
                    common = {
                        "trace_id": trace_id, "mode": "PAPER", "symbol": self.symbol,
                        "runtime_id": runtime_context.get("runtimeId"),
                    }
                    safe_record(stage="RESULT", status="CLOSED", reason_code=reason,
                                metadata={"decision": side, "positionId": position_before.get("order_id"),
                                          "entry": entry, "exit": price, "quantity": coin_qty,
                                          "grossPnL": pnl, "netPnL": pnl,
                                          "openedAt": position_before.get("entry_time"), "closedAt": closed_at},
                                **common)
                    safe_record(stage="HISTORY", status="RECORDED",
                                metadata={"tradeId": history_record["tradeId"],
                                          "positionId": position_before.get("order_id")}, **common)
                except Exception:
                    pass

        # =========================
        # LIVE EXCHANGE EVIDENCE
        # =========================
        # Preserve the authoritative exchange-side evidence for a confirmed real
        # close.  The locally estimated PnL above is NOT authoritative LIVE
        # realized PnL; it is retained only as an estimate and the exchange
        # order evidence is recorded separately.  Do not fabricate exchange
        # realized PnL that the current architecture cannot observe.
        if self.mode == "live" and isinstance(live_close, dict):
            runtime_context = position_before.get("runtimeSymbolContext") or {}
            identity = {
                key: runtime_context.get(key)
                for key in (
                    "contextKey", "runtimeInstanceId", "runtimeId", "exchangeSymbol",
                )
                if runtime_context.get(key) is not None
            } or {
                "symbol": self.symbol,
                "exchangeSymbol": (
                    live_close.get("symbol") or self.symbol
                ),
            }
            live_record = {
                "status": "CLOSED",
                "mode": "live",
                "symbol": self.symbol,
                "exchangeSymbol": live_close.get("symbol"),
                "side": side,
                "qty": coin_qty,
                "entryPrice": entry,
                "exitPrice": price,
                "estimatedPnl": pnl if pnl_available else None,
                "estimatedPnlAvailable": pnl_available,
                "estimatedPnlAuthoritative": False,
                "reason": reason,
                "orderId": live_close.get("order_id"),
                "exchangeCall": True,
                "confirmed": True,
                "closed": True,
                "exchangeClose": {
                    k: live_close.get(k)
                    for k in (
                        "order_id", "raw_order", "final_position", "symbol",
                        "openOrderAuthority", "positionState", "openOrderState",
                        "reconciliationAttempts",
                    )
                },
                **identity,
            }
            self._attach_position_parameter_context(
                live_record, position_before
            )
            self.trade_history.append(live_record)
            # Durable Stage 13 record (LIVE PnL stays explicitly non-authoritative).
            try:
                from backend.runtime.parameter_performance import (
                    record_completed_trade,
                )
                record_completed_trade(live_record)
            except Exception:
                pass
            self.live_close_state = {
                **live_close,
                "status": "CONFIRMED",
                "confirmed": True,
                "closed": True,
                "reason": "EXCHANGE_CLOSE_CONFIRMED",
                "order_id": live_close.get("order_id"),
            }

        # =========================
        # CLEANUP
        # =========================

        self.actual_position = None

        self.pending_order = False

        self.live_close_in_flight = False

        add_log("🧹 POSITION CLEANUP")

        if self.mode == "live":
            return {
                **(live_close or {}),
                "success": True,
                "confirmed": True,
                "closed": True,
                "status": "CONFIRMED",
                "reason": "EXCHANGE_CLOSE_CONFIRMED",
                "order_id": (
                    live_close.get("order_id")
                    if isinstance(live_close, dict)
                    else None
                ),
            }
        return None

    # =====================================
    # RESULT
    # =====================================

    def _order_sizing_authority(self, *, price, rules=None, fresh=False):
        """Read current MM policy and mode-specific order capital, never reference capital."""
        policy = self.sizing_policy_provider() if callable(self.sizing_policy_provider) else None
        if not isinstance(policy, MoneyManagementConfig):
            raise SizingRejected("SIZING_MM_POLICY_UNAVAILABLE")
        live = self.mode == "live"
        if live:
            cached = self._sizing_account_cache
            if not fresh and cached and 0 <= time.time() - cached[0] <= 2:
                account = cached[1]
            else:
                account = self.exchange.get_account_overview()
                self._sizing_account_cache = (time.time(), account)
            if not isinstance(account, dict) or account.get("source") != "KUCOIN_FUTURES_READ_ONLY" or account.get("currency") != "USDT":
                raise SizingRejected("LIVE_SIZING_CAPITAL_UNAVAILABLE")
            age = time.time() - float(account.get("lastSync", 0))
            if not 0 <= age <= 5:
                raise SizingRejected("LIVE_SIZING_CAPITAL_STALE")
            equity = number(account.get("equity"))
            available = number(account.get("availableBalance"), zero=True)
        else:
            if self.portfolio is None:
                raise SizingRejected("PAPER_SIZING_CAPITAL_UNAVAILABLE")
            equity = number(self.portfolio.balance) + number(self.unrealized_pnl, zero=True)
            available = number(self.portfolio.balance, zero=True)
        # The entry contract permits one position, only from FLAT. Do not guess
        # cross-symbol exposure from the local portfolio in LIVE mode.
        if self.actual_position is not None:
            raise SizingRejected("SIZING_REQUIRES_FLAT_POSITION")
        if live and (number(account.get("positionMargin"), zero=True) != 0
                     or number(account.get("orderMargin"), zero=True) != 0):
            raise SizingRejected("SIZING_ACCOUNT_EXPOSURE_NOT_FLAT")
        if rules is None:
            cached = self._sizing_contract_cache
            if not fresh and cached and cached[0] == self.symbol and 0 <= time.time() - cached[1] <= 2:
                rules = cached[2]
            else:
                provider = self.exchange.get_symbol_rules if live else self.sizing_contract_provider
                if not callable(provider):
                    raise SizingRejected("SIZING_CONTRACT_UNAVAILABLE")
                rules = provider(self.symbol)
                self._sizing_contract_cache = (self.symbol, time.time(), rules)
        if not isinstance(rules, dict) or rules.get("status") != "Open":
            raise SizingRejected("SIZING_CONTRACT_UNAVAILABLE")
        from backend.market.kucoin_futures_public import to_kucoin_futures_symbol
        symbol = to_kucoin_futures_symbol(self.symbol)
        if (rules.get("symbol") != symbol or rules.get("isInverse") is not False
                or rules.get("settle_currency") != "USDT" or rules.get("quote_currency") != "USDT"):
            raise SizingRejected("SIZING_CONTRACT_MISMATCH")
        leverage = number(self.config.get("effective_leverage") if live else self.config.get("leverage"))
        if leverage > min(policy.maximum_leverage, number(rules.get("max_leverage"))):
            raise SizingRejected("SIZING_LEVERAGE_EXCEEDS_AUTHORITY")
        return OrderSizingAuthority(
            symbol=symbol, price=price, equity=equity, available=available,
            risk_percent=min(number(self.config.get("risk_percent")), policy.risk_per_trade_pct),
            sl_percent=self.config.get("sl_percent"), leverage=leverage,
            fixed_notional=self.config.get("position_size"),
            position_cap=policy.maximum_position_notional,
            symbol_capacity=equity * policy.single_symbol_exposure_pct / 100,
            total_capacity=equity * policy.total_exposure_pct / 100,
            multiplier=rules.get("multiplier"), minimum=rules.get("min_size"),
            step=rules.get("qty_step"), maximum=rules.get("max_size"),
            cost_percent=number(rules.get("taker_fee_rate"), zero=True) * 200,
        )

    def _validate_final_entry_quantity(self, *, symbol, contracts, price, rules,
                                       leverage, approved_base, side, trace_id):
        """Adapter callback: recheck the exact wire quantity with fresh capital/MM."""
        authority = self._order_sizing_authority(price=price, rules=rules, fresh=True)
        if symbol != authority.symbol or number(leverage) != authority.leverage:
            raise SizingRejected("FINAL_SIZING_CONTEXT_CHANGED")
        base, _ = authority.validate(contracts, approved_base=approved_base)
        allowed, _ = self._evaluate_execution_entry_guard({
            "symbol": self.symbol, "side": side, "qty": float(base),
            "price": float(price), "traceId": trace_id,
        })
        if not allowed:
            raise SizingRejected("FINAL_QUANTITY_MM_REJECTED")
        return True

    def get_result(self):

        balance = (
            self.portfolio.balance
            if self.portfolio
            else self.balance
        )

        # Balance already includes realized PnL.  Equity adds only current
        # unrealized PnL; adding cumulative realized PnL again double-counts it.
        equity = balance + float(self.unrealized_pnl or 0)

        price = self.get_price()

        try:
            preview = self._order_sizing_authority(price=price).size()
        except Exception as exc:
            preview = {"valid": False, "reason": str(exc) if isinstance(exc, SizingRejected)
                       else "SIZING_AUTHORITY_UNAVAILABLE"}

        risk_state = self.update_drawdown_state()

        return {
            "status": self.status,
            "price": price,
            "pnl": self.pnl,
            "pnlAvailable": self._live_accounting_unavailable_reason() is None,
            "balance": balance,
            "equity": equity,
            "preview": preview,
            "symbol": self.symbol,
            "risk_percent": self.config["risk_percent"],
            "leverage": self.config["leverage"],
            "timeframe": self.config["timeframe"],
            "position_size": self.config["position_size"],
            "max_drawdown_pct": self.config["max_drawdown_pct"],
            "current_drawdown_pct": self.current_drawdown_pct,
            "tp_percent": self.config["tp_percent"],
            "sl_percent": self.config["sl_percent"],
            "trailing_stop": self.config["trailing_stop"],
            "risk_config": {
                "risk_percent": self.config["risk_percent"],
                "leverage": self.config["leverage"],
                "timeframe": self.config["timeframe"],
                "position_size": self.config["position_size"],
                "max_drawdown_pct": self.config["max_drawdown_pct"],
                "tp_percent": self.config["tp_percent"],
                "sl_percent": self.config["sl_percent"],
                "trailing_stop": self.config["trailing_stop"],
                "trailing_stop_distance_percent": (
                    self._trailing_distance_percent()
                ),
            },
            "risk_state": risk_state,
            "engine_id": self.engine_id,
            "pending_order": self.pending_order,
            "actual_position": self.actual_position,
            "paper_orders": copy.deepcopy(self.paper_orders),
            "paper_fills": copy.deepcopy(self.paper_fills),
            "trade_history": copy.deepcopy(self.trade_history),
            "live_close_state": copy.deepcopy(self.live_close_state),
        }
