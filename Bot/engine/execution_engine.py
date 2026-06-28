# -*- coding: utf-8 -*-

from backend.utils.order import place_order_safe
from backend.utils.log_buffer import add_log

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
        self.logger = logger
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

                print("💰 LIVE BALANCE:", balance)

                if balance > 0:

                    self.balance = balance

                    if self.portfolio:
                        self.portfolio.balance = balance

            except Exception as e:

                print("❌ BALANCE FETCH ERROR:", e)

        # =====================================
        # POSITION SYNC
        # =====================================

        if self.exchange and self.symbol:

            try:

                pos = self.exchange.get_positions(
                    self.symbol
                )

                self.actual_position = pos

                print("📦 SYNC POSITION:", pos)

            except Exception as e:

                print("❌ POSITION SYNC ERROR:", e)

        # =====================================
        # RUNNING
        # =====================================

        self.status = "RUNNING"

        print(
            "🔥 ENGINE STARTED | MODE:",
            self.mode
        )

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

            print(
                "💰 REFRESH BALANCE:",
                balance
            )

            add_log(
                f"💰 REFRESH BALANCE: "
                f"{balance}"
            )

            if balance > 0:

                self.balance = balance

                if self.portfolio:

                    self.portfolio.balance = (
                        balance
                    )

        except Exception as e:

            print(
                "❌ REFRESH BALANCE ERROR:",
                e
            )

            add_log(
                f"❌ REFRESH BALANCE ERROR: "
                f"{e}"
            )

    # =====================================
    # STOP
    # =====================================

    def stop(self):

        self.status = "STOPPED"

        add_log("🛑 ENGINE STOPPED")

        print("🛑 ENGINE STOPPED")

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

            print(
                f"🟣 NORMALIZED LEVERAGE: "
                f"{self.config['leverage']} "
                f"type={type(self.config['leverage'])}"
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

            print(
                f"🔥 FINAL MODE => {self.mode}"
            )

            add_log(
                f"🔥 FINAL MODE => {self.mode}"
            )

            print(
                f"🟡 DRY RUN => "
                f"{self.config['dry_run']}"
            )

            add_log(
                f"🟡 DRY RUN => "
                f"{self.config['dry_run']}"
            )

            print("🔥 ENGINE CONFIG APPLIED")

        except Exception as e:

            print("[CONFIG ERROR]", e)

    # =====================================
    # PRICE EVENT
    # =====================================

    def on_price(self, symbol, price):

        try:
            if getattr(self, "_on_price_running", False):

                print("BLOCK: on_price reentry")

                return

            self._on_price_running = True

            import inspect

            self.last_market_update = time.time()

            if self.status != "RUNNING":
                return

            if symbol != self.symbol:

                print("BLOCKED SYMBOL")

                return

            self.latest_price = price

            if not self.price_ready and price > 0:

                print("✅ FIRST PRICE RECEIVED")

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

                print(
                    f"PRICE={price} "
                    f"ENTRY={entry} "
                    f"QTY={contracts} "
                    f"UPNL={self.unrealized_pnl}"
                )

                if price <= self.actual_position.get("sl", 0):

                    print("🔴 SL HIT")

                    add_log("🔴 SL HIT")

                    self.close_position(price, "SL")

                    return

                if price >= self.actual_position.get("tp", 0):

                    print("🟢 TP HIT")

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

        except Exception as e:

            print("❌ ON_PRICE EXCEPTION:", e)

            import traceback
            traceback.print_exc()

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

                print("⛔ duplicate signal")

                add_log("⛔ duplicate signal")

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

            print(
                "[EARLY_COOLDOWN_BLOCK]"
            )

            add_log(
                "[EARLY_COOLDOWN_BLOCK]"
            )

            return

        self.last_signal_time = time.time()

        self.try_entry(signal)

    # =====================================
    # PRICE
    # =====================================

    def get_price(self):

        try:

            print("PRICE MANAGER:", self.price_manager)
            print("SYMBOL:", self.symbol)

            if not self.price_manager or not self.symbol:
                return 0.0

            result = self.price_manager.get_current_price()

            print("GET_PRICE RESULT:", result)

            return result

        except Exception as e:

            print("❌ GET_PRICE EXCEPTION:", e)

            import traceback
            traceback.print_exc()

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

        print(
            f"🟢 POSITION STATE: "
            f"{old_state} -> {state}"
        )

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
        print("TRY ENTRY ENGINE ID:", self.engine_id)

        add_log("🔥 TRY ENTRY")

        print("🔥 TRY ENTRY CALLED:", self.symbol)
        print("DEBUG A")
        print("DEBUG B")

        # =====================================
        # DUPLICATE PREVENTION
        # =====================================

        if self.pending_order:

            print("BLOCK: pending_order")

            add_log("BLOCK: pending_order")

            return

        # =====================================
        # EXECUTION COOLDOWN
        # =====================================

        print(
            "④ CHECK cooldown:",
            self.last_execution_time,
            type(self.last_execution_time)
        )

        cooldown_seconds = 3

        if (
            self.last_execution_time
            and
            time.time() - self.last_execution_time
            < cooldown_seconds
        ):

            print("[COOLDOWN_BLOCK] signal ignored")

            add_log(
                "[COOLDOWN_BLOCK] signal ignored"
            )

            return

        # =====================================
        # MARKET STALE CHECK
        # =====================================

        if time.time() - self.last_market_update > 5:

            self.price_ready = False

            print("BLOCK: stale")

            add_log("BLOCK: stale")

            print("⚠️ PRICE_READY RESET")

            add_log("⚠️ PRICE_READY RESET")

            return

        print("⑥ AFTER cooldown")

        # =====================================
        # PRICE READY
        # =====================================

        if not self.price_ready:

            print("BLOCK: no price_ready")

            add_log("BLOCK: no price_ready")

            return

        print("PASS: price_ready")

        # =====================================
        # STALE PROTECTION
        # =====================================

        if time.time() - self.last_market_update > 5:

            print("BLOCK: stale")

            add_log("BLOCK: stale")

            return

        print("PASS: stale_check")

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

            print(
                "POSITION CHECK:",
                state,
                qty
            )

            add_log(
                f"POSITION CHECK: "
                f"{state} {qty}"
            )

            # =================================
            # AUTHORITATIVE OPEN CHECK
            # =================================

            if state == "OPEN":

                print(
                    "BLOCK: open position exists"
                )

                add_log(
                    "BLOCK: open position exists"
                )

                return

        print("PASS: actual_position_check")

        # =====================================
        # PRICE
        # =====================================

        price = self.get_price()

        print("STEP-1 PRICE:", price)

        if not price or price <= 0:

            print("⛔ SKIP ENTRY: no price yet")

            add_log("⛔ SKIP ENTRY: no price yet")

            return

        # =====================================
        # PREVIEW
        # =====================================

        preview = self.get_result()["preview"]

        print("STEP-2 PREVIEW OK")

        print("🔥 PREVIEW:", preview)

        add_log(f"🔥 PREVIEW: {preview}")

        qty = preview.get("qty", 0)

        print("STEP-3 QTY:", qty)

        valid = preview.get("valid", False)

        print("STEP-4 VALID:", valid)
        print("STEP-5 QTY:", qty)
        print("STEP-6 PREVIEW:", preview)

        # =====================================
        # PREVIEW VALIDATION
        # =====================================

        if not valid:

            # =====================================
            # INVALID PREVIEW COOLDOWN
            # =====================================

            self.last_execution_time = time.time()

            print(
                "❌ preview invalid:",
                preview.get("reason")
            )

            add_log(
                f"❌ preview invalid: "
                f"{preview.get('reason')}"
            )

            return

        if qty <= 0:

            print("❌ qty zero")

            add_log("❌ qty zero")

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

        print("PASS: order_created")

        print("🟡 ORDER:", order)

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

                print("ENTER place_order_safe")

                raw_res = place_order_safe(
                    self.exchange,
                    self.portfolio,
                    order
                )

                print("EXIT place_order_safe")
                print(raw_res)

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

                    print(
                        "🟡 DRY RUN ACTIVE"
                    )

                    return

                print("ENTER exchange.place_order")

                raw_res = self.exchange.place_order(
                    symbol=order["symbol"],
                    side=order["side"],
                    qty=order["qty"],
                    price=order["price"]
                )

                print("EXIT exchange.place_order")
                print(raw_res)

                res = {
                    "success": raw_res.get(
                        "success",
                        False
                    ),
                    "raw": raw_res
                }

            print("🟢 EXECUTION RESULT:", res)

            add_log(f"🟢 EXECUTION RESULT: {res}")

            # =====================================
            # RESULT VALIDATION
            # =====================================

            if not res:

                print("❌ invalid result")

                add_log("❌ invalid result")

                return


            if not res.get("success"):

                print("❌ execution failed")

                add_log("❌ execution failed")

                return


            if self.actual_position:

                print(
                    "⚠️ POSITION ALREADY EXISTS"
                )

                add_log(
                    "⚠️ POSITION ALREADY EXISTS"
                )

                return


            print("✅ execution success")

            add_log("✅ execution success")

            # =====================================
            # AUTHORITATIVE BALANCE REFRESH
            # =====================================

            try:

                self.refresh_balance()

            except Exception as e:

                print(
                    "❌ BALANCE REFRESH ERROR:",
                    e
                )

                add_log(
                    f"❌ BALANCE REFRESH ERROR: "
                    f"{e}"
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

                print(
                    "📦 PAPER POSITION CREATED:",
                    self.actual_position
                )

                add_log(
                    "📦 PAPER POSITION CREATED"
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

                    print(
                        "📦 UPDATED POSITION:",
                        pos
                    )

                except Exception as e:

                    print(
                        "❌ POSITION FETCH ERROR:",
                        e
                    )

            self.last_execution_time = time.time()

        except Exception as e:

            print("❌ Order Error:", e)

            add_log(
                f"❌ Order Error: {e}"
            )

        finally:

            # =====================================
            # ALWAYS UNLOCK
            # =====================================

            self.pending_order = False

            print("🔓 pending_order reset")

            add_log("🔓 pending_order reset")

    # =====================================
    # CLOSE
    # =====================================

    def close_position(self, price, reason):

        print(f"🚪 CLOSE ({reason})")

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

        print(
            f"📊 ACCOUNTING | "
            f"BAL={self.balance:.4f} "
            f"PNL={self.pnl:.4f}"
        )

        if self.portfolio:
            self.portfolio.balance = self.balance

        print(f"💰 PnL: {pnl:.4f}")

        add_log(f"💰 PnL: {pnl:.4f}")

        # =========================
        # CLEANUP
        # =========================

        self.actual_position = None

        self.pending_order = False

        print("🧹 POSITION CLEANUP")

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

        print("STEP-1 PRICE:", price)

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

            print("MULTIPLIER:", multiplier)
            print("MIN_CONTRACTS:", min_contracts)
            print("COIN_QTY:", coin_qty)
            print("MIN_POSITION_VALUE:", min_position_value)

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

            print("REQUIRED_MARGIN:", required_margin)
            print("SAFE_LIMIT:", safe_limit)

            if required_margin > safe_limit:

                print(
                    "🚫 INSUFFICIENT BALANCE "
                    "FOR MIN CONTRACT"
                )

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



            print("BALANCE:", balance)
            print("RISK_PERCENT:", self.config["risk_percent"])
            print("LEVERAGE:", self.config["leverage"])
            print("RISK:", risk)
            print("POS_SIZE:", pos_size)

            if "qty" in locals():

                print("RAW QTY:", qty)



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
