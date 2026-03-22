# core/execution_engine.py
import csv
from datetime import datetime
from binance.client import Client
from utils.logger import BotLogger

logger = BotLogger("ExecutionEngine")

class ExecutionEngine:
    def __init__(self, client: Client, enable_trading: bool = False, log_dir="dryrun_logs"):
        """
        :param client: Binance 譛ｬ逡ｪ繧ｯ繝ｩ繧､繧｢繝ｳ繝・
        :param enable_trading: True 縺ｫ縺吶ｋ縺ｨ螳滄圀縺ｮ逋ｺ豕ｨ縺悟庄閭ｽ
        :param log_dir: CSV 菫晏ｭ伜・・・ryRun逕ｨ・・
        """
        self.client = client
        self.enable_trading = enable_trading
        self.positions = {}  # symbol縺斐→縺ｮ蜀・Κ繝昴ず繧ｷ繝ｧ繝ｳ邂｡逅・
        self.log_dir = log_dir

        # CSV繝代せ
        self.bot_log_file = f"{log_dir}/bot_log.csv"
        self.equity_file = f"{log_dir}/equity_curve.csv"
        self.signal_file = f"{log_dir}/signal_log.csv"
        self.trade_file = f"{log_dir}/trade_log.csv"

    # ---------------- CSV 繝ｭ繧ｰ譖ｸ縺崎ｾｼ縺ｿ ----------------
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

    # ---------------- 蜀・Κ繝昴ず繧ｷ繝ｧ繝ｳ譖ｴ譁ｰ ----------------
    def update_position(self, symbol, side, qty, price):
        pos = self.positions.get(symbol, {"long": 0, "short": 0})
        if side.lower() == "buy":
            pos["long"] += qty
        else:
            pos["short"] += qty
        self.positions[symbol] = pos
        logger.debug(f"Updated position: {symbol} {pos}")

        # 邁｡譏・PnL 險育ｮ・
        pnl = (pos["long"] - pos["short"]) * price
        self.update_equity(symbol, pnl)

    # ---------------- 逋ｺ豕ｨ蜃ｦ逅・----------------
    def place_order(self, symbol, side, qty, price=None, order_type="MARKET"):
        """
        逋ｺ豕ｨ逶ｴ蜑榊・逅・
        enable_trading=False 縺ｮ蝣ｴ蜷医・螳滄圀縺ｮ豕ｨ譁・・騾∽ｿ｡縺励↑縺・
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
            else:  # LIMIT 縺ｪ縺ｩ
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

    # ---------------- Signal蜿励￠蜿悶ｊ遯灘哨 ----------------
    def execute_signal(self, symbol, side, qty, price=None, order_type="MARKET"):
        self.update_position(symbol, side, qty, price)
        return self.place_order(symbol, side, qty, price, order_type)
