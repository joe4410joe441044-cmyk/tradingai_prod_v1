# =====================================================
# main_bot.py
# Trading AI Bot メイン起動スクリプト（systemd対応）
# Slack / Telegram / TradeCore
# =====================================================

import time
import threading

from Bot.core.trade_core import TradeCore
from config import IS_LIVE, LOG_PATH

# 通知モジュール
from Live.slack_bot.auto_bot_full_prod import send_slack

def main():
    print("=== Trading Bot Starting ===")
    print(f"Live Mode: {IS_LIVE}")

    trade_core = TradeCore(
        initial_balance=1000.0,
        is_live=IS_LIVE,
        log_path=LOG_PATH
    )

    print("TradeCore initialized.")
    print(trade_core.get_status())

    # -----------------------------
    # Slack はサブスレッドで常駐
    # -----------------------------
    threading.Thread(
        # target=start_slack_loop,  # ← 削除またはコメントアウト
        args=(trade_core,),
        daemon=True
    ).start()

    print("Slack loop started in background thread.")

    # -----------------------------
    # Telegram はメインスレッドで起動
    # これで systemd 上でも RuntimeError を回避
    # -----------------------------
    print("Starting Telegram loop in main thread...")
    

    # -----------------------------
    # メイン常駐ループ（Slackスレッドの監視用）
    # -----------------------------
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("=== Bot Stopped ===")


if __name__ == "__main__":
    main()
