import requests
import threading

class AILogger:

    def __init__(self):
        self.endpoint = "http://127.0.0.1:8010/api/ai/log"

    def log(self, data: dict):
        # 非同期送信（BOT止めないため重要）
        threading.Thread(target=self._send, args=(data,), daemon=True).start()

    def _send(self, data):
        try:
            requests.post(self.endpoint, json=data, timeout=0.5)
        except:
            pass