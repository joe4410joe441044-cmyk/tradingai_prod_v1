# bot_trade_demo.py
from Bot.core.trade_core import TradeCore
from Bot.control.telegram_controller import TelegramController
from Bot.control.telegram_listener import TelegramListener
from Bot.utils.telegram_notifier import TelegramNotifier
import time

# ── ここに自分のTelegram BOT TokenとチャットIDを設定
TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

# Notifier/Controller/Listener 初期化
notifier = TelegramNotifier(TOKEN, CHAT_ID)
controller = TelegramController(notifier)
listener = TelegramListener(TOKEN, controller)

# Listenerをバックグラウンドで起動（ポーリング）
listener.start()

# TradeCoreの簡易ダミー初期化
trade_core = TradeCore()  # 実際のTradeCoreの引数に合わせて調整

# ── ダミー注文（BUY）を発生
trade_type = "BUY"
entry_price = 100.0
sl_price = 95.0
tp_price = 110.0

print("[Demo] Opening position...")
trade_core.open_position(trade_type, entry_price, sl_price, tp_price)
controller.notify_entry(trade_type, entry_price, sl_price, tp_price)

time.sleep(2)  # 2秒待って通知を確認

# ── ダミーTP通知
profit = 10.0
print("[Demo] Take profit hit...")
controller.notify_take_profit(profit)

time.sleep(2)

# ── ダミーSL通知
loss = 5.0
print("[Demo] Stop loss hit...")
controller.notify_stop_loss(loss)

print("[Demo] Demo finished. Check Telegram for notifications.")