# ~/TradingAI_Bot_Main_new/Live/notification_utils.py
import os
import requests

# ===== 迺ｰ蠅・､画焚縺九ｉ險ｭ螳壹ｒ蜿門ｾ・=====
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_slack_message(message: str):
    """Slack 縺ｫ繝｡繝・そ繝ｼ繧ｸ繧・蝗槭□縺鷹∽ｿ｡"""
    if not SLACK_WEBHOOK_URL:
        print("[Slack] Webhook URL 縺梧悴險ｭ螳・)
        return
    try:
        res = requests.post(SLACK_WEBHOOK_URL, json={"text": message})
        res.raise_for_status()
        print(f"[Slack] 繝｡繝・そ繝ｼ繧ｸ騾∽ｿ｡謌仙粥: {message}")
    except Exception as e:
        print(f"[Slack] 繝｡繝・そ繝ｼ繧ｸ騾∽ｿ｡螟ｱ謨・ {e}")

def send_telegram_message(message: str):
    """Telegram 縺ｫ繝｡繝・そ繝ｼ繧ｸ繧・蝗槭□縺鷹∽ｿ｡"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Bot Token 縺ｾ縺溘・ Chat ID 縺梧悴險ｭ螳・)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        res = requests.post(url, data=data)
        res.raise_for_status()
        print(f"[Telegram] 繝｡繝・そ繝ｼ繧ｸ騾∽ｿ｡謌仙粥: {message}")
    except Exception as e:
        print(f"[Telegram] 繝｡繝・そ繝ｼ繧ｸ騾∽ｿ｡螟ｱ謨・ {e}")

def send_startup_notification():
    """Bot 襍ｷ蜍墓凾縺ｫ荳｡譁ｹ縺ｫ騾夂衍"""
    msg = "=== 譛ｬ逡ｪ Bot 縺・VPS 縺ｧ襍ｷ蜍輔＠縺ｾ縺励◆ ==="
    send_slack_message(msg)
    send_telegram_message(msg)

# ===== 繝・せ繝亥ｮ溯｡檎畑 =====
if __name__ == "__main__":
    send_startup_notification()
