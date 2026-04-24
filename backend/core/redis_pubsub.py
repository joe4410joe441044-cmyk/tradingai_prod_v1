import redis
import json
import threading

class RedisPubSub:

    def __init__(self):
        self.r = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True
        )
        self.pubsub = self.r.pubsub()

    # =========================
    # PUBLISH
    # =========================

    def publish(self, channel: str, data: dict):
        self.r.publish(channel, json.dumps(data))

    # =========================
    # SUBSCRIBE LOOP
    # =========================

    def subscribe(self, channel: str, callback):
        self.pubsub.subscribe(channel)

        def listen():
            for message in self.pubsub.listen():
                if message["type"] == "message":
                    data = json.loads(message["data"])
                    callback(data)

        thread = threading.Thread(target=listen, daemon=True)
        thread.start()