# -*- coding: utf-8 -*-

import csv
from datetime import datetime

from binance.client import Client
from Bot.utils.logger import BotLogger


class ExecutionEngine:

    def __init__(self, logger=None, notifier=None, live=False, client: Client = None, log_dir="dryrun_logs"):
        """
        新設計 + 旧機能統合版

        :param logger: BotLogger
        :param notifier: TelegramNotifier
        :param live: 本番実行フラグ（Falseなら発注しない）
        :param client: Binance Client（本番時のみ使用）
        :param log_dir: ログ保存先
        """
        print(">>> ExecutionEngine INIT CALLED")
        self.logger = logger or BotLogger("ExecutionEngine").get_logger()
        self.notifier = notifier
        self.live = live
        self.client = client
        self.positions = {}
        self.log_dir = log_dir

        # CSVログ
        self.bot_log_file = f"{log_dir}/bot_log.csv"
        self.equity_file = f"{log_dir}/equity_curve.csv"
        self.signal_file = f"{log_dir}/signal_log.csv"
        self.trade_file = f"{log_dir}/trade_log.csv"

    # ---------------- CSV ----------------
    def _log_csv(self, file_path, row):
        try:
            with open(file_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception as e:
            print("CSV log error:", e)

    def log_bot(self, msg: str):
        self._log_csv(self.bot_log_file, [datetime.now(), msg])
        self.logger.info(msg)

    def log_signal(self, symbol, side, qty, price):
        self._log_csv(self.signal_file, [datetime.now(), symbol, side, qty, price])

    def log_trade(self, symbol, side, qty, price, status):
        self._log_csv(self.trade_file, [datetime.now(), symbol, side, qty, price, status])

    def update_equity(self, symbol, pnl):
        self._log_csv(self.equity_file, [datetime.now(), symbol, pnl])

    # ---------------- ポジション ----------------
    def update_position(self, symbol, side, qty, price):
        pos = self.positions.get(symbol, {"long": 0, "short": 0})

        if side.lower() == "buy":
            pos["long"] += qty
        else:
            pos["short"] += qty

        self.positions[symbol] = pos

        self.logger.info(f"Updated position: {symbol} {pos}")

        # 簡易PnL
        if price:
            pnl = (pos["long"] - pos["short"]) * price
            self.update_equity(symbol, pnl)

    # ---------------- 注文 ----------------
    def place_order(self, symbol, side, qty, price=None, order_type="MARKET"):
        self.log_bot(f"Order requested: {symbol} {side} {qty} @ {price} ({order_type})")
        self.log_signal(symbol, side, qty, price)

        if not self.live:
            status = "skipped"
            self.log_trade(symbol, side, qty, price, status)
            self.logger.info("[ExecutionEngine] Trading disabled")
            return {"status": status, "symbol": symbol, "side": side, "qty": qty, "price": price}

        if not self.client:
            self.logger.error("Client not set for live trading")
            return {"status": "error", "error": "client not set"}

        try:
            if order_type.upper() == "MARKET":
                result = self.client.create_order(
                    symbol=symbol,
                    side=side,
                    type="MARKET",
                    quantity=qty
                )
            else:
                result = self.client.create_order(
                    symbol=symbol,
                    side=side,
                    type="LIMIT",
                    timeInForce="GTC",
                    quantity=qty,
                    price=price
                )

            status = "executed"
            self.log_trade(symbol, side, qty, price, status)
            self.logger.info(f"[ExecutionEngine] Order executed: {result}")
            return result

        except Exception as e:
            status = "error"
            self.log_trade(symbol, side, qty, price, status)
            self.logger.error(f"[ExecutionEngine] Order failed: {e}")
            return {"status": status, "error": str(e)}

    # ---------------- Signal ----------------
    def execute_signal(self, symbol, side, qty, price=None, order_type="MARKET"):
        self.update_position(symbol, side, qty, price)
        return self.place_order(symbol, side, qty, price, order_type)

    # ---------------- Runner 統一入口 ----------------
    def send_signal(self, signal: dict):
        """
        StrategyRunner から呼ばれる統一入口
        """
        print("[ExecutionEngine] Signal received:", signal)

        try:
            symbol = signal.get("symbol")
            side = signal.get("side")
            qty = signal.get("qty", 0.001)
            price = signal.get("price")

            # 通知
            if self.notifier:
                try:
                    self.notifier.send(f"Signal: {signal}")
                except Exception as e:
                    print("Notifier error:", e)

            return self.execute_signal(symbol, side, qty, price)

        except Exception as e:
            self.logger.error(f"Signal execution error: {e}")
            return {"status": "error", "error": str(e)}