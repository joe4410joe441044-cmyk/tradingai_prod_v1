import redis
import json

class RedisClient:

    def __init__(self):
        self.r = redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=True
        )

    # =========================
    # BOT STATE
    # =========================

    def set_bot_status(self, status: str):
        self.r.set("bot:status", status)

    def get_bot_status(self):
        return self.r.get("bot:status")

    # =========================
    # PRICE
    # =========================

    def set_price(self, price: float):
        self.r.set("market:price", price)

    def get_price(self):
        val = self.r.get("market:price")
        return float(val) if val else 0.0

    # =========================
    # POSITIONS
    # =========================

    def set_positions(self, positions: dict):
        self.r.set("positions:open", json.dumps(positions))

    def get_positions(self):
        val = self.r.get("positions:open")
        return json.loads(val) if val else []

    # =========================
    # RISK
    # =========================

    def set_risk(self, risk: dict):
        self.r.set("risk:state", json.dumps(risk))

    def get_risk(self):
        val = self.r.get("risk:state")
        return json.loads(val) if val else {}