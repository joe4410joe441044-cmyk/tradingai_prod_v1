# -*- coding: utf-8 -*-

from backend.utils.order import place_order_safe
import math
import time


def adjust_qty_to_step(qty, step_size):
    if step_size <= 0:
        return qty
    return math.floor(qty / step_size) * step_size


class ExecutionEngine:

    def __init__(self, exchange=None, logger=None, portfolio=None, notifier=None, price_manager=None):
        self.exchange = exchange
        self.logger = logger
        self.portfolio = portfolio
        self.notifier = notifier
        self.price_manager = price_manager

        self.pnl = 0
        self.balance = portfolio.initial_balance if portfolio else 0

        self.symbol = None
        self.engine_id = id(self)

        self.ws_client = None

        self.status = "STOPPED"
        self.mode = "paper"

        self.position = None
        self.last_entry_time = 0

        self.price_ready = False

        self.config = {
            "risk_percent": 1,
            "leverage": 10,
            "sl_percent": 1,
            "tp_percent": 2,
            "dry_run": True
        }

    def start(self):

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

        if self.exchange and self.symbol:
            try:
                pos = self.exchange.get_positions(self.symbol)
                self.position = pos
                print("📦 SYNC POSITION:", pos)
            except Exception as e:
                print("❌ POSITION SYNC ERROR:", e)

        self.status = "RUNNING"
        self.price_ready = False

        print("🔥 ENGINE STARTED | MODE:", self.mode)

        return {"status": "started"}

    def stop(self):
        self.status = "STOPPED"
        print("🛑 ENGINE STOPPED")
        return {"status": "stopped"}

    def set_config(self, config: dict):
        try:
            if not config:
                return

            if "mode" in config:
                self.mode = config["mode"]
                print("🔥 MODE SET:", self.mode)

            safe_config = dict(config)
            safe_config.pop("symbol", None)

            self.config["risk_percent"] = float(safe_config.get("risk_percent", self.config["risk_percent"]))
            self.config["leverage"] = float(safe_config.get("leverage", self.config["leverage"]))
            self.config["sl_percent"] = float(safe_config.get("sl_percent", self.config["sl_percent"]))
            self.config["tp_percent"] = float(safe_config.get("tp_percent", self.config["tp_percent"]))
            self.config["dry_run"] = False  # 🔥 強制OFF

            print("🔥 ENGINE CONFIG APPLIED")

        except Exception as e:
            print("[CONFIG ERROR]", e)

    def on_price(self, symbol, price):

        if self.status != "RUNNING":
            return

        if symbol != self.symbol:
            return

        if not self.price_ready and price > 0:
            print("✅ FIRST PRICE RECEIVED")
            self.price_ready = True

        # ポジション管理
        if self.position:
            if price <= self.position.get("sl", 0):
                print("🔴 SL HIT")
                self.close_position(price, "SL")
                return

            if price >= self.position.get("tp", 0):
                print("🟢 TP HIT")
                self.close_position(price, "TP")
                return

            return

        # エントリー制御
        if time.time() - self.last_entry_time < 1:
            return

        self.try_entry({"side": "BUY"})

    def get_price(self):
        if not self.price_manager or not self.symbol:
            return 0.0
        return self.price_manager.get_price(self.symbol)

    def try_entry(self, signal):

        print("🔥 TRY ENTRY CALLED:", self.symbol)

        if time.time() - self.last_entry_time < 1:
            return

        if not self.price_ready:
            print("⛔ WAITING FIRST PRICE")
            return

        price = self.get_price()

        if not price or price <= 0:
            print("⛔ SKIP ENTRY: no price yet")
            return

        if self.position is not None:
            return

        preview = self.get_result()["preview"]

        qty = preview.get("qty", 0)
        valid = preview.get("valid", False)

        if not valid:
            print("❌ preview invalid:", preview.get("reason"))
            self.last_entry_time = time.time()
            return

        if qty <= 0:
            print("❌ qty zero")
            self.last_entry_time = time.time()
            return

        try:
            min_qty = self.exchange.get_min_qty(self.symbol)
            if qty < min_qty:
                print("❌ below min_qty")
                self.last_entry_time = time.time()
                return
        except:
            pass

        order = {
            "symbol": self.symbol,
            "side": signal.get("side"),
            "qty": qty,
            "price": price
        }

        print("🟡 ORDER:", order)

        try:

            if self.mode == "paper":
                res = place_order_safe(self.exchange, self.portfolio, order)
            else:
                self.exchange.set_leverage(
                    symbol=order["symbol"],
                    leverage=int(self.config.get("leverage", 10))
                )

                res = self.exchange.place_order(
                    symbol=order["symbol"],
                    side=order["side"],
                    qty=order["qty"],
                    price=order["price"]
                )

            print("🟢 RESULT:", res)

            if "-" in str(res):
                print("❌ invalid result")
                return

            print("✅ ORDER SUCCESS")

            # 🔥 ここが今回の核心（追加）
            if self.mode == "paper":
                self.position = {
                    "entry_price": price,
                    "qty": qty,
                    "sl": price * (1 - self.config["sl_percent"] / 100),
                    "tp": price * (1 + self.config["tp_percent"] / 100)
                }
                print("📦 PAPER POSITION CREATED:", self.position)

            else:
                try:
                    pos = self.exchange.get_positions(self.symbol)
                    self.position = pos
                    print("📦 UPDATED POSITION:", pos)
                except Exception as e:
                    print("❌ POSITION FETCH ERROR:", e)

            self.last_entry_time = time.time()

        except Exception as e:
            print("❌ Order Error:", e)

    def close_position(self, price, reason):

        print(f"🚪 CLOSE ({reason})")

        if not self.position:
            return

        entry = self.position.get("entry_price", price)
        qty = self.position.get("qty", 0)

        pnl = (price - entry) * qty

        self.pnl += pnl
        self.balance += pnl

        if self.portfolio:
            self.portfolio.balance = self.balance

        print(f"💰 PnL: {pnl:.4f}")

        self.position = None

    def get_result(self):

        balance = self.portfolio.balance if self.portfolio else self.balance
        equity = balance + self.pnl

        price = self.get_price()

        if not price or price <= 0:
            preview = {"valid": False, "reason": "invalid_price"}
        else:
            risk = balance * (self.config["risk_percent"] / 100)
            pos_size = risk * self.config["leverage"]
            qty = pos_size / price

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
            "engine_id": self.engine_id
        }