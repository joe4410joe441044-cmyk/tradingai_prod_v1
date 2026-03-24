# -*- coding: utf-8 -*-
import logging

# ★追加：安全ラッパー
from Bot.utils.safety import safe_run


class ExecutionEngine:
    """
    ExecutionEngine
    ----------------
    Strategy からの Signal を受け取り処理する。
    live=False の場合はログのみで、実際の発注は行わない。
    notifier があれば Telegram へ通知。
    """

    def __init__(self, live=False, logger=None, notifier=None):
        self.live = live
        self.logger = logger or logging.getLogger(__name__)
        self.notifier = notifier

        self.logger.info(f"ExecutionEngine initialized (live={self.live})")

    # --------------------------
    # Signal送信（TradeCore → ExecutionEngine）
    # --------------------------
    @safe_run  # ★追加
    def send_signal(self, signal):
        """
        Signal に応じて注文処理
        Signal 例: {'side': 'BUY', 'symbol': 'BTCUSDT', 'qty': 0.001, 'price': xxx}
        """
        # ログ強化
        self.logger.info(f"[EXECUTION] Processing signal: {signal}")

        if self.live:
            # 実際に発注する場合のコードはここに追加
            self.logger.info(f"[LIVE] Sending order: {signal}")
        else:
            # 発注前チェック・ログ
            self.logger.info(f"[DRY_RUN] Signal received: {signal}")

        # Telegram通知
        if self.notifier:
            try:
                self.notifier.send(f"Signal executed: {signal}")
            except Exception as e:
                self.logger.error(f"Failed to send Telegram notification: {e}")

    # --------------------------
    # 発注前準備
    # --------------------------
    @safe_run  # ★追加
    def prepare_order(self, position):
        """
        注文直前処理
        TradeCore から呼ばれる
        live=False の場合はログのみ
        """
        signal = {
            "symbol": position.symbol,
            "side": position.trade_type,
            "qty": position.volume,
            "price": position.entry_price
        }

        if self.live:
            self.logger.info(f"[LIVE] Preparing order: {signal}")
            # 実発注処理はここに実装
        else:
            self.logger.info(f"[DRY_RUN] Preparing order: {signal}")

    @safe_run  # ★追加
    def prepare_close_order(self, position):
        """
        決済直前処理
        TradeCore から呼ばれる
        """
        signal = {
            "symbol": position.symbol,
            "side": "SELL" if position.trade_type == "BUY" else "BUY",
            "qty": position.volume,
            "price": position.entry_price  # 実際の決済価格は別途取得
        }

        if self.live:
            self.logger.info(f"[LIVE] Preparing close order: {signal}")
            # 実決済処理はここに実装
        else:
            self.logger.info(f"[DRY_RUN] Preparing close order: {signal}")

    # --------------------------
    # 統一注文入口（追加）
    # --------------------------
    @safe_run  # ★追加（これが最重要）
    async def execute_order(self, signal):
        """
        Signal → 注文処理の統一入口
        TradeCore からはこの関数を呼ぶ
        """

        # 既存処理をそのまま使用（安全）
        self.send_signal(signal)