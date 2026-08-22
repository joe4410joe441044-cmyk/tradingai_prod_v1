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

import backend.config as backend_config
import copy
import math
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal


def adjust_qty_to_step(qty, step_size):
    if step_size <= 0:
        return qty

    return math.floor(qty / step_size) * step_size


class ExecutionEngine:

    def __init__(
        self,
        exchange=None,
        logger=None,
        portfolio=None,
        notifier=None,
        price_manager=None
    ):

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

        # duplicate prevention
        self.pending_order = False
        self.execution_entry_guard_lock = threading.RLock()
        self.execution_entry_guard = None
        self.execution_entry_admission_lock = threading.RLock()
        self.execution_entry_admission_in_progress = False
        self.last_money_management_guard = None
        # One short-lived, exact-order MM admission lets the mainline evaluate
        # Money Management before Governance without evaluating the same entry
        # twice. It is consumed by the normal engine entry boundary.
        self.execution_entry_preapproval = None

        # realtime freshness
        self.last_market_update = 0

        # signal lifecycle
        self.last_signal_time = 0
        self.last_signal_id = None

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

                self.actual_position = pos
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

    def update_drawdown_state(self, equity=None):

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

            multiplier = float(
                position.get("multiplier", 1) or 1
            )

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

    def build_live_readiness(self):

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
        }

    def _live_order_allowed(self):

        readiness = self.build_live_readiness()
        self.last_live_block_reasons = list(
            readiness["blockReasons"]
        )

        if readiness["realOrderAllowed"]:
            self.last_order_blocked_reason = None
            return True

        self.last_order_blocked_reason = "LIVE_NOT_READY"

        return False

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

    def on_price(self, symbol, price):

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

                multiplier = self.actual_position.get(
                    "multiplier",
                    0.001
                )

                coin_qty = (
                    contracts * multiplier
                )

                side = self.actual_position.get(
                    "side"
                )

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

                stop_loss = self.actual_position.get(
                    "sl",
                    0,
                )

                take_profit = self.actual_position.get(
                    "tp",
                    0,
                )

                if self._is_short(side):

                    sl_hit = price >= stop_loss

                    tp_hit = price <= take_profit

                else:

                    sl_hit = price <= stop_loss

                    tp_hit = price >= take_profit

                if sl_hit:

                    add_log("🔴 SL HIT")

                    self.close_position(price, "SL")

                    return

                if tp_hit:

                    add_log("🟢 TP HIT")

                    self.close_position(price, "TP")

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
            return self._try_entry_candidate(signal)
        finally:
            with self.execution_entry_admission_lock:
                self.execution_entry_admission_in_progress = False

    def _try_entry_candidate(self, signal):
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

        preview = self.get_result()["preview"]

        runtime_debug("ExecutionEngine preview=%s", preview)

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

        add_log(f"🟡 ORDER: {order}")

        live_order_allowed = None
        if self.mode != "paper" and not self.config["dry_run"]:
            live_order_allowed = self._live_order_allowed()
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
                    price=order["price"]
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

                    self.actual_position = pos

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

    def close_position(self, price, reason):

        add_log(f"🚪 CLOSE ({reason})")

        if not self.actual_position:
            return

        entry = self.actual_position.get(
            "entry_price",
            price
        )

        contracts = self.actual_position.get(
            "qty",
            0
        )

        multiplier = self.actual_position.get(
            "multiplier",
            0.001
        )

        coin_qty = (
            contracts * multiplier
        )

        side = self.actual_position.get(
            "side"
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
        else:
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

        add_log(f"💰 PnL: {pnl:.4f}")

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
            self.trade_history.append(history_record)
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
        # CLEANUP
        # =========================

        self.actual_position = None

        self.pending_order = False

        add_log("🧹 POSITION CLEANUP")

    # =====================================
    # RESULT
    # =====================================

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

        if not price or price <= 0:

            preview = {
                "valid": False,
                "reason": "invalid_price"
            }

        else:

            risk = balance * (
                self.config["risk_percent"] / 100
            )

            configured_position_size = float(
                self.config.get("position_size", 0) or 0
            )

            if configured_position_size > 0:

                base_position_size = (
                    configured_position_size
                )

                sizing_mode = "fixed_position_size"

            else:

                # Leverage is margin-only.  It must not amplify the risk
                # budget into a larger position notional or quantity.
                base_position_size = risk

                sizing_mode = "risk_percent"

            pos_size = base_position_size

            # =====================================
            # CONTRACT-AWARE MIN SIZE
            # =====================================

            if self.exchange:

                rules = self.exchange.get_symbol_rules(
                    self.symbol
                )

            else:

                rules = {
                    "multiplier": 0.001,
                    "min_size": 1
                }

            multiplier = rules.get(
                "multiplier",
                0.001
            )

            min_contracts = rules.get(
                "min_size",
                1
            )

            coin_qty = (
                min_contracts * multiplier
            )

            min_position_value = (
                coin_qty * price
            )

            pos_size = max(
                pos_size,
                min_position_value
            )

            # =====================================
            # MINIMUM BALANCE SAFETY
            # =====================================

            required_margin = (
                pos_size
                / self.config["leverage"]
            )

            safety_ratio = 0.8

            safe_limit = (
                balance * safety_ratio
            )

            if required_margin > safe_limit:

                preview = {
                    "valid": False,
                    "reason": (
                        "insufficient_balance_for_position_size"
                        if configured_position_size > 0
                        else "insufficient_balance_for_min_contract"
                    )
                }

            else:

                qty = pos_size / price

                preview = {
                    "qty": round(qty, 6),
                    "valid": True,
                    "position_size": round(pos_size, 6),
                    "configured_position_size": (
                        configured_position_size
                    ),
                    "sizing_mode": sizing_mode,
                    "required_margin": round(
                        required_margin,
                        6,
                    ),
                }



            runtime_debug(
                "Execution preview balance=%s price=%s risk_percent=%s "
                "leverage=%s risk=%s sizing_mode=%s configured_position_size=%s "
                "position_size=%s multiplier=%s "
                "min_contracts=%s coin_qty=%s min_position_value=%s "
                "required_margin=%s safe_limit=%s raw_qty=%s",
                balance,
                price,
                self.config["risk_percent"],
                self.config["leverage"],
                risk,
                sizing_mode,
                configured_position_size,
                pos_size,
                multiplier,
                min_contracts,
                coin_qty,
                min_position_value,
                required_margin,
                safe_limit,
                locals().get("qty"),
            )



        risk_state = self.update_drawdown_state()

        return {
            "status": self.status,
            "price": price,
            "pnl": self.pnl,
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
        }
