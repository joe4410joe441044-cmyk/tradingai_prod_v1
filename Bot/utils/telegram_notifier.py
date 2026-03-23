# -*- coding: utf-8 -*-
# Bot/utils/telegram.py
import requests
import datetime
import logging

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """
    Telegram BOT E
    - 
    - 
    -  / E
    """

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    # ------------------------------
    # E
    # ------------------------------
    def send(self, message: str):
        payload = {"chat_id": self.chat_id, "text": message}
        try:
            requests.post(self.url, data=payload, timeout=5)
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    # ------------------------------
    # BOT
    # ------------------------------
    def bot_started(self):
        t = datetime.datetime.now()
        msg = f" BOT STARTED\nTime: {t}"
        self.send(msg)

    # ------------------------------
    # 
    # ------------------------------
    def entry(self, trade_type: str, entry: float, sl: float, tp: float):
        msg = (
            f" NEW TRADE\n"
            f"Type: {trade_type}\n"
            f"Entry: {entry}\n"
            f"SL: {sl}\n"
            f"TP: {tp}"
        )
        self.send(msg)

    # ------------------------------
    # 
    # ------------------------------
    def take_profit(self, profit: float):
        msg = f" TAKE PROFIT\nProfit: {profit}"
        self.send(msg)

    # ------------------------------
    # E
    # ------------------------------
    def stop_loss(self, loss: float):
        msg = f"EESTOP LOSS\nLoss: {loss}"
        self.send(msg)