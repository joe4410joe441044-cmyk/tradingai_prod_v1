# -*- coding: utf-8 -*-

from backend.utils.order import place_order_safe
from backend.log_store import add_log

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

        self.status = "RUNNING"

        self.price_ready = False

        print("🔥 ENGINE STARTED | MODE:", self.mode)

        return {
            "status": "started"
        }

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

            if "mode" in config:

                self.mode = config["mode"]

                print("🔥 MODE SET:", self.mode)

            safe_config = dict(config)

            safe_config.pop("symbol", None)

            self.config["risk_percent"] = float(
                safe_config.get(
                    "risk_percent",
                    self.config["risk_percent"]
                )
            )

            self.config["leverage"] = float(
                safe_config.get(
                    "leverage",
                    self.config["leverage"]
                )
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

            self.config["dry_run"] = False

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

            print("ENGINE FILE:", inspect.getfile(self.__class__))

            print("PRICE_READY VALUE:", self.price_ready)
            print("PRICE_READY VALUE:", self.price_ready)
            print("PRICE_READY TYPE:", type(self.price_ready))
            print("ENGINE ID:", self.engine_id)
            print("ON_PRICE VALUE:", price)
            print("ON_PRICE TYPE:", type(price))
            print("ON_PRICE SYMBOL:", symbol)
            print("ENGINE SYMBOL:", self.symbol)
            print("BEFORE MARKET UPDATE")

            # self.last_market_update = time.time()
            
            print("AFTER MARKET UPDATE")
            self.last_market_update = time.time()
            
            
            # add_log("🔥 ENGINE TICK")
            
            print("ENGINE STATUS:", self.status)
            print("STATUS EQ:", self.status == "RUNNING")

            if self.status != "RUNNING":
                return

            print("SYMBOL EQ:", symbol == self.symbol)
            print("SYMBOL REPR:", repr(symbol))
            print("ENGINE SYMBOL REPR:", repr(self.symbol))

            if symbol != self.symbol:

                print("BLOCKED SYMBOL")

                return

            print("PASSED SYMBOL CHECK")

            print("PRICE > 0:", price > 0)
            print("NOT PRICE_READY:", not self.price_ready)
            print(
                "FINAL CONDITION:",
                (not self.price_ready and price > 0)
            )

            if not self.price_ready and price > 0:

                print("✅ FIRST PRICE RECEIVED")

                add_log("✅ FIRST PRICE RECEIVED")

                self.price_ready = True

                print("PRICE_READY UPDATED:", self.price_ready)

            # =====================================
            # POSITION MANAGEMENT
            # =====================================

            if self.actual_position:

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

        if time.time() - self.last_execution_time < 1:

            print("⑤ BLOCK cooldown")

            add_log("BLOCK: cooldown")

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

        if self.actual_position is not None:

            print("BLOCK: actual_position")

            add_log("BLOCK: actual_position")

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

        print("STEP-7 BEFORE ORDER BUILD")

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

                raw_res = place_order_safe(
                    self.exchange,
                    self.portfolio,
                    order
                )

                res = {
                    "success": bool(raw_res),
                    "raw": raw_res
                }

            # =====================================
            # LIVE
            # =====================================

            else:

                self.exchange.set_leverage(
                    symbol=order["symbol"],
                    leverage=int(
                        self.config.get(
                            "leverage",
                            10
                        )
                    )
                )

                raw_res = self.exchange.place_order(
                    symbol=order["symbol"],
                    side=order["side"],
                    qty=order["qty"],
                    price=order["price"]
                )

                res = {
                    "success": bool(raw_res),
                    "raw": raw_res
                }

            print("🟢 RESULT:", res)

            add_log(f"🟢 RESULT: {res}")

            # =====================================
            # RESULT VALIDATION
            # =====================================

            if not res.get("success"):

                print("❌ invalid result")

                add_log("❌ invalid result")

                return

            print("✅ ORDER SUCCESS")

            add_log("✅ ORDER SUCCESS")

            # =====================================
            # PAPER POSITION
            # =====================================

            if self.mode == "paper":

                self.actual_position = {
                    "side": signal.get("side"),
                    "entry_price": price,
                    "qty": qty,
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

        qty = self.actual_position.get(
            "qty",
            0
        )

        pnl = (price - entry) * qty

        self.pnl += pnl

        self.balance += pnl

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

            qty = pos_size / price
            print("BALANCE:", balance)
            print("RISK_PERCENT:", self.config["risk_percent"])
            print("LEVERAGE:", self.config["leverage"])
            print("RISK:", risk)
            print("POS_SIZE:", pos_size)
            print("RAW QTY:", qty)

            preview = {
                "qty": round(qty, 6),
                "valid": True
            }

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
