import redis
import json
import threading

from backend.utils.log_buffer import logger


class RedisPubSub:

    def __init__(self):
        self.r = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True
        )
        self.pubsub = self.r.pubsub()
        self._subscribed_channels = set()
        self._thread = None

    # =========================
    # PUBLISH
    # =========================

    def publish(self, channel: str, data: dict):
        try:
            self.r.publish(channel, json.dumps(data))
        except Exception as e:
            logger.error("PubSub publish error: %s", e)

    # =========================
    # SUBSCRIBE LOOP
    # =========================

    def subscribe(self, channel: str, callback):
        # 重複登録防止
        if channel in self._subscribed_channels:
            return

        self._subscribed_channels.add(channel)
        self.pubsub.subscribe(channel)

        # スレッド1本だけ
        if self._thread and self._thread.is_alive():
            return

        def listen():
            for message in self.pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                except Exception:
                    data = {}

                try:
                    callback(data)
                except Exception as e:
                    logger.error("PubSub callback error: %s", e)

        self._thread = threading.Thread(target=listen, daemon=True)
        self._thread.start()
