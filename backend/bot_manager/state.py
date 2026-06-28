# ============================================
# BOT RUNTIME STATE
# ============================================

class BotRuntimeState:

    IDLE = "IDLE"

    SIGNAL_RECEIVED = "SIGNAL_RECEIVED"

    ORDER_PENDING = "ORDER_PENDING"

    ORDER_SUBMITTED = "ORDER_SUBMITTED"

    POSITION_OPEN = "POSITION_OPEN"

    POSITION_MANAGING = "POSITION_MANAGING"

    TP_HIT = "TP_HIT"

    SL_HIT = "SL_HIT"

    BREAK_EVEN = "BREAK_EVEN"

    TRAILING = "TRAILING"

    POSITION_CLOSED = "POSITION_CLOSED"

    ERROR = "ERROR"