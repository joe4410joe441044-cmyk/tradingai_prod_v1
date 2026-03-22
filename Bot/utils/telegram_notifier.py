# Bot/utils/telegram.py
import requests
import datetime
import logging

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Telegram BOT 騾夂衍繝ｩ繝・ヱ繝ｼ
    - 襍ｷ蜍暮夂衍
    - 繧ｨ繝ｳ繝医Μ繝ｼ騾夂衍
    - 蛻ｩ遒ｺ / 謳榊・騾夂衍
    """

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    # ------------------------------
    # 繝｡繝・そ繝ｼ繧ｸ騾∽ｿ｡
    # ------------------------------
    def send(self, message: str):
        payload = {"chat_id": self.chat_id, "text": message}
        try:
            requests.post(self.url, data=payload, timeout=5)
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    # ------------------------------
    # BOT襍ｷ蜍暮夂衍
    # ------------------------------
    def bot_started(self):
        t = datetime.datetime.now()
        msg = f"噫 BOT STARTED\nTime: {t}"
        self.send(msg)

    # ------------------------------
    # 繧ｨ繝ｳ繝医Μ繝ｼ騾夂衍
    # ------------------------------
    def entry(self, trade_type: str, entry: float, sl: float, tp: float):
        msg = (
            f"投 NEW TRADE\n"
            f"Type: {trade_type}\n"
            f"Entry: {entry}\n"
            f"SL: {sl}\n"
            f"TP: {tp}"
        )
        self.send(msg)

    # ------------------------------
    # 蛻ｩ遒ｺ騾夂衍
    # ------------------------------
    def take_profit(self, profit: float):
        msg = f"腸 TAKE PROFIT\nProfit: {profit}"
        self.send(msg)

    # ------------------------------
    # 謳榊・騾夂衍
    # ------------------------------
    def stop_loss(self, loss: float):
        msg = f"笞・・STOP LOSS\nLoss: {loss}"
        self.send(msg)
