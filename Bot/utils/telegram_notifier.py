# -*- coding: utf-8 -*-

import requests
import datetime
import logging
import os
import time

logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO)


class TelegramNotifier:
    def __init__(self, token: str = None, chat_id: str = None):

        # 🔥 環境変数対応
        self.token = token or os.getenv("TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")

        if not self.token or not self.chat_id:
            logger.warning("Telegram not configured (TOKEN / CHAT_ID missing)")
            self.enabled = False
            return

        self.enabled = True
        self.url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        # 🔥 スパム制御
        self._last_send_time = 0
        self._min_interval = 1.0  # 秒

    # =========================
    # CORE SEND
    # =========================
    def send_message(self, message: str, markdown=True):

        if not self.enabled:
            return

        # 🔥 スパム防止（連打抑制）
        now = time.time()
        if now - self._last_send_time < self._min_interval:
            return
        self._last_send_time = now

        payload = {
            "chat_id": self.chat_id,
            "text": message,
        }

        # 🔥 Markdown対応
        if markdown:
            payload["parse_mode"] = "Markdown"

        try:
            response = requests.post(self.url, data=payload, timeout=5)

            if not response.ok:
                logger.warning(f"Telegram send failed: {response.text}")

        except Exception as e:
            logger.error(f"Telegram error: {e}")

    # 互換
    def send(self, message: str):
        self.send_message(message)

    # =========================
    # 🔥 ERROR専用（最重要）
    # =========================
    def error(self, source: str, message: str):

        t = datetime.datetime.now().strftime("%H:%M:%S")

        text = (
            f"🚨 *ERROR*\n"
            f"`{source}`\n"
            f"{message}\n"
            f"{t}"
        )

        self.send_message(text)

    # =========================
    # PRESET
    # =========================
    def bot_started(self):
        t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.send_message(f"🚀 *BOT STARTED*\n{t}")

    def entry(self, trade_type: str, entry: float, sl: float, tp: float):
        self.send_message(
            "📈 *NEW TRADE*\n"
            f"Type: `{trade_type}`\n"
            f"Entry: {entry}\n"
            f"SL: {sl}\n"
            f"TP: {tp}"
        )

    def take_profit(self, profit: float):
        self.send_message(f"✅ *TAKE PROFIT*\nProfit: {profit}")

    def stop_loss(self, loss: float):
        self.send_message(f"❌ *STOP LOSS*\nLoss: {loss}")


# =====================================================
# 🔥 グローバル関数（monitor用）
# =====================================================

_notifier = None


def _get_notifier():
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier()
    return _notifier


def send_telegram(message: str):
    """monitorから呼ぶ簡易関数"""
    _get_notifier().send_message(message)


def send_error(source: str, message: str):
    """ERROR専用（monitorから推奨）"""
    _get_notifier().error(source, message)