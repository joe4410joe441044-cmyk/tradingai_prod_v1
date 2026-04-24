from .event_schema import create_base_event
from .event_types import *

# =========================
# AI DECISION EVENT
# =========================
def build_ai_event(symbol, action, reason, confidence, source):

    e = create_base_event()

    e["type"] = AI_DECISION
    e["stage"] = SIGNAL

    e["symbol"] = symbol
    e["action"] = action
    e["reason"] = reason
    e["confidence"] = confidence
    e["source"] = source

    return e


# =========================
# RISK EVENT
# =========================
def build_risk_event(symbol, allowed, exposure, reason):

    e = create_base_event()

    e["type"] = RISK_EVENT
    e["stage"] = RISK

    e["symbol"] = symbol
    e["risk"]["allowed"] = allowed
    e["risk"]["exposure"] = exposure
    e["risk"]["block_reason"] = reason

    return e


# =========================
# EXECUTION EVENT
# =========================
def build_execution_event(symbol, action, order_id, status):

    e = create_base_event()

    e["type"] = EXECUTION_EVENT
    e["stage"] = EXECUTION

    e["symbol"] = symbol
    e["action"] = action

    e["execution"]["order_id"] = order_id
    e["execution"]["status"] = status

    return e