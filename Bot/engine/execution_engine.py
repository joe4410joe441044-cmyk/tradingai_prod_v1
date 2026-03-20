# engine/execution_engine.py
import logging

class ExecutionEngine:

    def __init__(self, live=False, logger=None, notifier=None):
        self.live = live
        self.logger = logger or self._create_default_logger()
        self.notifier = notifier

    # -----------------------------
    # デフォルトLogger生成
    # -----------------------------
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
    # 注文実行
    # -----------------------------
    def execute_order(self, order):

        if self.live:
            msg = f"Live order executed: {order}"
        else:
            msg = f"Simulated order: {order}"

        # ログ出力
        self.logger.info(msg)

        # 通知（あれば）
        if self.notifier:
            try:
                self.notifier.send(msg)
            except Exception as e:
                self.logger.error(f"Notifier error: {e}")