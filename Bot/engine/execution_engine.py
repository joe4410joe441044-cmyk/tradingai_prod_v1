# engine/execution_engine.py
import logging

class ExecutionEngine:
    def __init__(self, live=False):
        self.live = live
        self._init_logger()

    def _init_logger(self):
        # Logger初期化
        self.logger = logging.getLogger("ExecutionEngine")
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def execute_order(self, order):
        if self.live:
            # ここに Binance 注文処理を実装予定
            self.logger.info(f"Live order executed: {order}")
        else:
            # 資金未投入モードではログ出力のみ
            self.logger.info(f"Simulated order: {order}")