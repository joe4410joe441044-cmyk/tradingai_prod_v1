# -*- coding: utf-8 -*-

from backend.utils.order import place_order_safe
from backend.utils.log_buffer import (
    add_log,
    logger as app_logger,
    runtime_debug,
    ws_debug,
)

import math
import time


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
            "leverage": 10,
            "sl_percent": 1,
            "tp_percent": 2,
            "dry_run": True
        }

    # =====================================
    # START
    # =====================================

    def start(self):

        add_log("🚀 ENGINE START CALLED")

        if self.mode == "live" and self.exchange:

            try:

                balance = self.exchange.get_balance()

                runtime_debug("ExecutionEngine live balance=%s", balance)

                if balance > 0:

                    self.balance = balance

                    if self.portfolio:
                        self.portfolio.balance = balance

            except Exception:

                self.logger.exception("BALANCE FETCH ERROR")

        # =====================================
        # POSITION SYNC
        # =====================================

        if self.exchange and self.symbol:

            try:

                pos = self.exchange.get_positions(
                    self.symbol
                )

                self.actual_position = pos

                runtime_debug("ExecutionEngine synced position=%s", pos)

            except Exception:

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
    # CONFIG
    # =====================================

    def set_config(self, config: dict):

        try:

            if not config:
                return

            safe_config = dict(config)

            safe_config.pop("symbol", None)

            self.config["risk_percent"] = float(
                safe_config.get(
                    "risk_percent",
                    self.config["risk_percent"]
                )
            )

            self.config["leverage"] = int(
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

            self.config["dry_run"] = bool(
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

        except Exception:

            self.logger.exception("ExecutionEngine config error")

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

                self.unrealized_pnl = (
                    (price - entry)
                    * coin_qty
                )

                runtime_debug(
                    "Position tick price=%s entry=%s qty=%s upnl=%s",
                    price,
                    entry,
                    contracts,
                    self.unrealized_pnl,
                )

                if price <= self.actual_position.get("sl", 0):

                    add_log("🔴 SL HIT")

                    self.close_position(price, "SL")

                    return

                if price >= self.actual_position.get("tp", 0):

                    add_log("🟢 TP HIT")

                    self.close_position(price, "TP")

                    return

                return

            # =====================================
            # TEMP SIGNAL EMIT
            # =====================================

            signal = {
                "id": int(time.time() * 1000),
                "side": "BUY",
                "timestamp": time.time()
            }

            self.submit_signal(signal)

        except Exception:

            self.logger.exception("ON_PRICE EXCEPTION")

        finally:

            self._on_price_running = False

    # =====================================
    # SIGNAL ENTRYPOINT
    # =====================================

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

        self.try_entry(signal)

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
            "side": signal.get("side"),
            "qty": qty,
            "price": price
        }

        add_log(f"🟡 ORDER: {order}")

        # =====================================
        # EXECUTION LOCK
        # =====================================

        self.pending_order = True

        try:

            # =====================================
            # PAPER
            # =====================================

            if self.mode == "paper":

                raw_res = place_order_safe(
                    self.exchange,
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

                self.actual_position = {
                    "state": "OPEN",

                    "side": signal.get("side"),

                    "entry_price": price,

                    # authoritative contract qty
                    "qty": contracts,

                    # normalized coin qty
                    "coin_qty": qty,

                    # contract spec
                    "multiplier": multiplier,

                    "entry_time": time.time(),

                    "signal_id": signal.get("id"),

                    "sl": price * (
                        1 - self.config["sl_percent"] / 100
                    ),

                    "tp": price * (
                        1 + self.config["tp_percent"] / 100
                    )
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

        pnl = (
            (price - entry)
            * coin_qty
        )

        self.pnl += pnl

        self.balance += pnl

        self.unrealized_pnl = 0

        runtime_debug(
            "Position accounting balance=%.4f cumulative_pnl=%.4f",
            self.balance,
            self.pnl,
        )

        if self.portfolio:
            self.portfolio.balance = self.balance

        add_log(f"💰 PnL: {pnl:.4f}")

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

        equity = balance + self.pnl

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

            pos_size = (
                risk * self.config["leverage"]
            )

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
                min_position_value
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
                        "insufficient_balance_for_min_contract"
                    )
                }

            else:

                qty = pos_size / price

                preview = {
                    "qty": round(qty, 6),
                    "valid": True
                }



            runtime_debug(
                "Execution preview balance=%s price=%s risk_percent=%s "
                "leverage=%s risk=%s position_size=%s multiplier=%s "
                "min_contracts=%s coin_qty=%s min_position_value=%s "
                "required_margin=%s safe_limit=%s raw_qty=%s",
                balance,
                price,
                self.config["risk_percent"],
                self.config["leverage"],
                risk,
                pos_size,
                multiplier,
                min_contracts,
                coin_qty,
                min_position_value,
                required_margin,
                safe_limit,
                locals().get("qty"),
            )



        return {
            "status": self.status,
            "price": price,
            "pnl": self.pnl,
            "balance": balance,
            "equity": equity,
            "preview": preview,
            "symbol": self.symbol,
            "engine_id": self.engine_id,
            "pending_order": self.pending_order,
            "actual_position": self.actual_position
        }
