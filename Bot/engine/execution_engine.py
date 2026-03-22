from core.trade_core import TradeCore
from utils.logger import BotLogger

import logging

class ExecutionEngine:

    def __init__(self, live=False, logger=None, notifier=None):
        self.live = live
        self.logger = logger or self._create_default_logger()
        self.notifier = notifier

        # 👇 追加（超重要）
        self.position = None  # "LONG", "SHORT", None

    def _create_default_logger(self):
        logger = logging.getLogger("ExecutionEngine")

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '[%(asctime)s] [%(levelname)s] %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

        return logger

    # -----------------------------
    # Signal受信（←ここが本体）
    # -----------------------------
    def execute(self, signal):

        if signal is None:
            return

        action = signal.get("action")

        if action == "BUY":
            self._buy(signal)

        elif action == "SELL":
            self._sell(signal)

        elif action == "CLOSE":
            self._close()

    # -----------------------------
    # 内部処理
    # -----------------------------
    def _buy(self, signal):

        if self.position == "LONG":
            self.logger.info("Already LONG → skip")
            return

        self._send_order("BUY", signal)
        self.position = "LONG"

    def _sell(self, signal):

        if self.position == "SHORT":
            self.logger.info("Already SHORT → skip")
            return

        self._send_order("SELL", signal)
        self.position = "SHORT"

    def _close(self):

        if self.position is None:
            self.logger.info("No position → skip")
            return

        self._send_order("CLOSE", {})
        self.position = None

    # -----------------------------
    # 注文処理（既存ロジック活用）
    # -----------------------------
    def _send_order(self, action, data):

        order_msg = {
            "action": action,
            **data
        }

        if self.live:
            msg = f"Live order executed: {order_msg}"
        else:
            msg = f"Simulated order: {order_msg}"

        self.logger.info(msg)

        if self.notifier:
            try:
                self.notifier.send(msg)
            except Exception as e:
                self.logger.error(f"Notifier error: {e}")