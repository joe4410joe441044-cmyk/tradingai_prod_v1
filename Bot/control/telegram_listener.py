import threading
import time
import requests

class TelegramListener:
    def __init__(self, token, controller):
        self.token = token
        self.controller = controller
        self.base_url = f"https://api.telegram.org/bot{self.token}/"
        self._stop = False

    def start(self):
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()
        print("📡 Telegram Listener Started")
        while True:
            time.sleep(1)

    def _listen(self):
        offset = None
        while not self._stop:
            try:
                url = self.base_url + "getUpdates"
                params = {"timeout": 10, "offset": offset}
                resp = requests.get(url, params=params).json()
                for update in resp.get("result", []):
                    offset = update["update_id"] + 1
                    text = update.get("message", {}).get("text")
                    if text:
                        self.controller.handle_command(text)
            except Exception as e:
                print("Listener error:", e)
                time.sleep(5)