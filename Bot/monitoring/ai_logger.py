import time
import json

class AILogger:

    def __init__(self):
        self.logs = []

    def log_decision(self, symbol, bot_signal, ai_score, ai_decision, final_action):
        entry = {
            "timestamp": time.time(),
            "symbol": symbol,
            "bot_signal": bot_signal,
            "ai_score": ai_score,
            "ai_decision": ai_decision,
            "final_action": final_action
        }

        self.logs.append(entry)

        print(f"[AI LOG] {json.dumps(entry)}")

    def get_recent(self, limit=50):
        return self.logs[-limit:]