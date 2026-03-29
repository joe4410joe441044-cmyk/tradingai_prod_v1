# -*- coding: utf-8 -*-
import threading
import time
from Bot.control.telegram_controller import TelegramController
from Bot.control.telegram_listener import TelegramListener
from Bot.utils.telegram_notifier import TelegramNotifier
from Bot.core.trade_core import TradeCore, StrategyContext

# =========================
# Telegram設定
CHAT_ID = "1040943428"

# =========================
# Notifier / Controller / Listener
notifier = TelegramNotifier(token=TOKEN, chat_id=CHAT_ID)
controller = TelegramController(notifier)
listener = TelegramListener(token=TOKEN, controller=controller)

# Listenerを別スレッドで起動（/start や /status 受信用）
threading.Thread(target=listener.start, daemon=True).start()

# =========================
# TradeCore 本番連携
trade_core = TradeCore()  # 引数なしで初期化

# =========================
# 簡易通知ラッパーを作る
# try_enter 後に Telegram へ通知する
def notify_entry(ctx: StrategyContext):
    controller.notify_entry(ctx.trade_type, ctx.entry_price, ctx.stop_loss_price, ctx.take_profit_price)

# check_orders 後に TP/SL HIT を Telegram に送る
def notify_positions():
    for pos in trade_core.positions:
        if pos.status == "closed" and not hasattr(pos, "notified"):
            if pos.trade_type == "BUY" or pos.trade_type == "SELL":
                # TPかSLかを判定して通知
                price_hit = "TP" if (pos.trade_type == "BUY" and pos.tp <= pos.entry_price) or \
                                   (pos.trade_type == "SELL" and pos.tp >= pos.entry_price) else "SL"
                if price_hit == "TP":
                    controller.notify_take_profit(abs(pos.tp - pos.entry_price))
                else:
                    controller.notify_stop_loss(abs(pos.sl - pos.entry_price))
                pos.notified = True  # 通知済みフラグ

# =========================
# TradeCore メインループ（簡易サンプル）
while True:
    # サンプル：新規エントリーを作る
    ctx = StrategyContext(
        strategy_name="FVG",
        trade_type="BUY",
        entry_price=66116.23,
        stop_loss_price=66066.23,
        take_profit_price=66166.23
    )
    trade_core.try_enter(ctx)
    notify_entry(ctx)

    # サンプル：現在価格チェック（ダミー）
    price_dict = {"BTCUSDT": 66170.0}  # 実際はマーケット価格を ExecutionEngine から取得
    trade_core.check_orders(price_dict)
    notify_positions()

    time.sleep(5)  # 5秒ごとにループ