import requests
import datetime
import logging

class TelegramNotifier:

    def __init__(self, token, chat_id):

        self.token = token
        self.chat_id = chat_id

        self.url = f"https://api.telegram.org/bot{token}/sendMessage"

    # ---------------------------------
    # メッセージ送信
    # ---------------------------------

    def send(self, message):

        payload = {
            "chat_id": self.chat_id,
            "text": message
        }

        try:
            requests.post(self.url, data=payload)

        except Exception as e:
            print("Telegram error:", e)

    # ---------------------------------
    # BOT起動通知
    # ---------------------------------

    def bot_started(self):

        t = datetime.datetime.now()

        msg = f"""
🚀 BOT STARTED

Time: {t}
"""

        self.send(msg)

    # ---------------------------------
    # エントリー通知
    # ---------------------------------

    def entry(self, trade_type, entry, sl, tp):

        msg = f"""
📊 NEW TRADE

Type: {trade_type}
Entry: {entry}
SL: {sl}
TP: {tp}
"""

        self.send(msg)

    # ---------------------------------
    # 利確通知
    # ---------------------------------

    def take_profit(self, profit):

        msg = f"""
💰 TAKE PROFIT

Profit: {profit}
"""

        self.send(msg)

    # ---------------------------------
    # 損切通知
    # ---------------------------------

    def stop_loss(self, loss):

        msg = f"""
⚠️ STOP LOSS

Loss: {loss}
"""

        self.send(msg)