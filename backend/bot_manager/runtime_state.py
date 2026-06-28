# ============================================
# BOT RUNTIME STATE
# ============================================

class BotRuntimeState:

    def __init__(self):

        # ============================================
        # STRATEGY STATE
        # ============================================

        self.strategy_state = {}

        # ============================================
        # EXECUTION STATE
        # ============================================

        self.execution_state = {}
    

        # =========================
        # POSITION
        # =========================

        self.actual_position = None

        self.pending_order = None
        # ============================================
        # RECONCILIATION
        # ============================================

        self.reconciliation_running = False

        self.last_reconciliation_ts = 0

        self.reconciliation_interval = 2

        self.exchange_position_cache = None

        self.position_state = "FLAT"

        # =========================
        # ORDER FLOW
        # =========================

        self.last_order_time = 0

        self.cooldown_until = 0

        # =========================
        # EXECUTION
        # =========================

        self.last_execution_result = None

        self.last_signal = None

        # =========================
        # SAFETY
        # =========================

        self.emergency_stop = False

        # ============================================
        # RUNTIME TRACE
        # ============================================

        self.runtime_trace = {

            "ws_receive": False,

            "callback_fire": False,

            "bot_update": False,

            "status_api": False,

            "frontend_update": False,
        }

        # ============================================
        # RUNTIME METRICS
        # ============================================

        self.runtime_metrics = {

            "ws_connected": False,

            "ws_thread_alive": False,

            "market_ready": False,

            "last_ws_message": None,

            "last_callback": None,

            "last_bot_update": None,

            "latency_ms": 0,

            "message_count": 0,
        }
