# ~/TradingAI_Bot_Main_new/Live/notification_utils.py
import os
import requests

# ===== 環境変数から設定を取得 =====
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_slack_message(message: str):
    """Slack にメッセージを1回だけ送信"""
    if not SLACK_WEBHOOK_URL:
        print("[Slack] Webhook URL が未設定")
        return
    try:
        res = requests.post(SLACK_WEBHOOK_URL, json={"text": message})
        res.raise_for_status()
        print(f"[Slack] メッセージ送信成功: {message}")
    except Exception as e:
        print(f"[Slack] メッセージ送信失敗: {e}")

def send_telegram_message(message: str):
    """Telegram にメッセージを1回だけ送信"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Bot Token または Chat ID が未設定")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        res = requests.post(url, data=data)
        res.raise_for_status()
        print(f"[Telegram] メッセージ送信成功: {message}")
    except Exception as e:
        print(f"[Telegram] メッセージ送信失敗: {e}")

def send_startup_notification():
    """Bot 起動時に両方に通知"""
    msg = "=== 本番 Bot が VPS で起動しました ==="
    send_slack_message(msg)
    send_telegram_message(msg)

# ===== テスト実行用 =====
if __name__ == "__main__":
    send_startup_notification()