import time
import csv
import os
import logging
from utils import send_telegram

LOG_FILE = "bot_check_log.csv"
CHECK_INTERVAL = 60

class BotState:
    def __init__(self):
        self.dry_run = True
        self.running = False

bot_state = BotState()

def log_check(result):
    exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp", "result"])
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), result])

def start_bot_core():
    if bot_state.running:
        return

    bot_state.running = True
    send_telegram(f"?? Bot 起動（{'DRY' if bot_state.dry_run else '本番'}）")

    for _ in range(10):
        if not bot_state.running:
            break

        if bot_state.dry_run:
            logging.info("?? DRY_RUN：注文なし")
        else:
            logging.info("?? 本番注文実行（仮）")

        time.sleep(1)

    bot_state.running = False
    send_telegram("?? Bot 処理終了")

def periodic_check():
    while True:
        log_check("正常稼働中")
        time.sleep(CHECK_INTERVAL)
