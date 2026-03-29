# -*- coding: utf-8 -*-
# bot_test.py

import requests
from Bot.control.telegram_controller import TelegramController
from Bot.control.telegram_listener import TelegramListener
from Bot.utils.telegram_notifier import TelegramNotifier

# ── ここに自分のTelegram BOT TokenとCHAT_IDを入れる
TOKEN = "8568714005:AAFlzofjXb1cDZyaM93Awq4TFMcBsFKizYc"
CHAT_ID = "1040943428"

# =========================
# TelegramNotifier の send メソッドにログ追加
class MyTelegramNotifier(TelegramNotifier):
    def send(self, text):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = {"chat_id": self.chat_id, "text": text}
        try:
            resp = requests.post(url, data=data)
            print("Send response:", resp.status_code, resp.text)  # 送信結果を確認
            resp.raise_for_status()
        except Exception as e:
            print("Send failed:", e)

# =========================
# 通知用 & Controller & Listener 作成
notifier = MyTelegramNotifier(token=TOKEN, chat_id=CHAT_ID)
controller = TelegramController(notifier)
listener = TelegramListener(token=TOKEN, controller=controller)

# =========================
# テスト通知
controller.notifier.send("テスト通知！")

# =========================
# Listener 起動
listener.start()