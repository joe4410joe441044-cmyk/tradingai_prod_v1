# Bot/utils/telegram_notifier.py
import requests
import datetime
import logging

logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logging.basicConfig(level=logging.INFO)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    # =========================
    # CORE SEND
    # =========================
    def send_message(self, message: str):
        """互換用メイン送信関数"""
        payload = {"chat_id": self.chat_id, "text": message}

        try:
            response = requests.post(self.url, data=payload, timeout=5)
            if not response.ok:
                logger.warning(f"Telegram send failed: {response.text}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    # 旧互換
    def send(self, message: str):
        self.send_message(message)

    # =========================
    # PRESET MESSAGES
    # =========================
    def bot_started(self):
        t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.send_message(f"BOT STARTED\nTime: {t}")

    def entry(self, trade_type: str, entry: float, sl: float, tp: float):
        self.send_message(
            "NEW TRADE\n"
            f"Type: {trade_type}\n"
            f"Entry: {entry}\n"
            f"SL: {sl}\n"
            f"TP: {tp}"
        )

    def take_profit(self, profit: float):
        self.send_message(f"TAKE PROFIT\nProfit: {profit}")

    def stop_loss(self, loss: float):
        self.send_message(f"STOP LOSS\nLoss: {loss}")