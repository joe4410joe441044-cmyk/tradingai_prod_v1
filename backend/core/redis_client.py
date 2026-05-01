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
        try:
            return float(val) if val else 0.0
        except:
            return 0.0

    # =========================
    # POSITIONS
    # =========================

    def set_positions(self, positions: dict):
        self.r.set("positions:open", json.dumps(positions))

    def get_positions(self):
        val = self.r.get("positions:open")
        try:
            return json.loads(val) if val else []
        except:
            return []

    # =========================
    # RISK（%統一）
    # =========================

    def set_risk(self, risk: dict):
        """
        risk = {
            "risk_percent": 1,
            "sl_percent": 1,
            "leverage": 10
        }
        """
        self.r.set("risk:state", json.dumps(risk))

    def get_risk(self):
        val = self.r.get("risk:state")

        # 安全読み込み
        try:
            data = json.loads(val) if val else {}
        except:
            data = {}

        # =========================
        # 🔥 %ベースで統一
        # =========================
        risk_percent = data.get("risk_percent", 1)
        sl_percent = data.get("sl_percent", 1)
        leverage = data.get("leverage", 10)

        # 型安全（壊れ対策）
        try:
            risk_percent = float(risk_percent)
        except:
            risk_percent = 1

        try:
            sl_percent = float(sl_percent)
        except:
            sl_percent = 1

        try:
            leverage = float(leverage)
        except:
            leverage = 10

        return {
            "risk_percent": risk_percent,   # ← %（1 = 1%）
            "sl_percent": sl_percent,       # ← %（追加）
            "leverage": leverage
        }