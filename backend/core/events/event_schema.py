import time
import uuid

def create_base_event():

    return {
        "event_id": str(uuid.uuid4()),
        "type": None,
        "stage": None,

        "symbol": None,
        "action": None,

        "source": {},
        "confidence": 0.0,

        "reason": "",

        "risk": {
            "allowed": True,
            "exposure": 0.0,
            "block_reason": None
        },

        "execution": {
            "order_id": None,
            "status": None
        },

        "timestamp": time.time()
    }