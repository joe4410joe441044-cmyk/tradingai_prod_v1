# Bot/utils/telegram.py
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

    def send(self, message: str):
        payload = {"chat_id": self.chat_id, "text": message}
        try:
            response = requests.post(self.url, data=payload, timeout=5)
            if not response.ok:
                logger.warning(f"Telegram send failed: {response.text}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    def bot_started(self):
        t = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"BOT STARTED\nTime: {t}"
        self.send(msg)

    def entry(self, trade_type: str, entry: float, sl: float, tp: float):
        msg = (
            f"NEW TRADE\n"
            f"Type: {trade_type}\n"
            f"Entry: {entry}\n"
            f"SL: {sl}\n"
            f"TP: {tp}"
        )
        self.send(msg)

    def take_profit(self, profit: float):
        msg = f"TAKE PROFIT\nProfit: {profit}"
        self.send(msg)

    def stop_loss(self, loss: float):
        msg = f"STOP LOSS\nLoss: {loss}"
        self.send(msg)