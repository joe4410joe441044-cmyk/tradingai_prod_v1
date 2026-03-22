# core/execution_engine.py
import csv
from datetime import datetime
from binance.client import Client
from utils.logger import BotLogger

logger = BotLogger("ExecutionEngine")

class ExecutionEngine:
    def __init__(self, client: Client, enable_trading: bool = False, log_dir="dryrun_logs"):
        """
        :param client: Binance 本番クライアント
        :param enable_trading: True にすると実際の発注が可能
        :param log_dir: CSV 保存先（DryRun用）
        """
        self.client = client
        self.enable_trading = enable_trading
        self.positions = {}  # symbolごとの内部ポジション管理
        self.log_dir = log_dir

        # CSVパス
        self.bot_log_file = f"{log_dir}/bot_log.csv"
        self.equity_file = f"{log_dir}/equity_curve.csv"
        self.signal_file = f"{log_dir}/signal_log.csv"
        self.trade_file = f"{log_dir}/trade_log.csv"

    # ---------------- CSV ログ書き込み ----------------
    def _log_csv(self, file_path, row):
        with open(file_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row)

    def log_bot(self, msg: str):
        self._log_csv(self.bot_log_file, [datetime.now(), msg])
        logger.info(msg)

    def log_signal(self, symbol, side, qty, price):
        self._log_csv(self.signal_file, [datetime.now(), symbol, side, qty, price])

    def log_trade(self, symbol, side, qty, price, status):
        self._log_csv(self.trade_file, [datetime.now(), symbol, side, qty, price, status])

    def update_equity(self, symbol, pnl):
        self._log_csv(self.equity_file, [datetime.now(), symbol, pnl])

    # ---------------- 内部ポジション更新 ----------------
    def update_position(self, symbol, side, qty, price):
        pos = self.positions.get(symbol, {"long": 0, "short": 0})
        if side.lower() == "buy":
            pos["long"] += qty
        else:
            pos["short"] += qty
        self.positions[symbol] = pos
        logger.debug(f"Updated position: {symbol} {pos}")

        # 簡易 PnL 計算
        pnl = (pos["long"] - pos["short"]) * price
        self.update_equity(symbol, pnl)

    # ---------------- 発注処理 ----------------
    def place_order(self, symbol, side, qty, price=None, order_type="MARKET"):
        """
        発注直前処理
        enable_trading=False の場合は実際の注文は送信しない
        """
        self.log_bot(f"Order requested: {symbol} {side} {qty} @ {price} ({order_type})")
        self.log_signal(symbol, side, qty, price)

        if not self.enable_trading:
            status = "skipped"
            self.log_trade(symbol, side, qty, price, status)
            logger.info("[ExecutionEngine] Trading disabled, skipping actual order")
            return {"status": status, "symbol": symbol, "side": side, "qty": qty, "price": price}

        try:
            if order_type.upper() == "MARKET":
                result = self.client.create_order(
                    symbol=symbol,
                    side=side,
                    type="MARKET",
                    quantity=qty
                )
            else:  # LIMIT など
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
            logger.info(f"[ExecutionEngine] Order executed: {result}")
            return result
        except Exception as e:
            status = "error"
            self.log_trade(symbol, side, qty, price, status)
            logger.error(f"[ExecutionEngine] Order failed: {e}")
            return {"status": status, "error": str(e)}

    # ---------------- Signal受け取り窓口 ----------------
    def execute_signal(self, symbol, side, qty, price=None, order_type="MARKET"):
        self.update_position(symbol, side, qty, price)
        return self.place_order(symbol, side, qty, price, order_type)