# -*- coding: utf-8 -*-

from dataclasses import dataclass
from typing import Dict, Any
import datetime
import logging
import time
import uuid
from queue import Queue

from Bot.utils.safety import safe_run

# =========================
# AI MODULES
# =========================
from Bot.ai.ai_risk_filter import AIRiskFilter
from Bot.monitoring.ai_logger import AILogger


# =====================================================
# POSITION STATE
# =====================================================
class PositionStatus:
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


# =====================================================
# POSITION
# =====================================================
@dataclass
class Position:
    id: str
    entry_price: float
    trade_type: str
    sl: float
    tp: float
    volume: float
    entry_time: datetime.datetime
    symbol: str = "BTCUSDT"
    status: str = PositionStatus.PENDING
    close_price: float = None


# =====================================================
# EVENT TYPES
# =====================================================
class EventType:
    ENTRY = "ENTRY"
    POSITION_OPENED = "POSITION_OPENED"
    PRICE_UPDATE = "PRICE_UPDATE"
    CLOSE = "CLOSE"


# =====================================================
# TRADE CORE
# =====================================================
class TradeCore:

    def __init__(self, execution_engine=None, logger=None):

        print(">>> TradeCore INIT")

        self.logger = logger or logging.getLogger("TradeCore")
        self.execution_engine = execution_engine

        self.positions: Dict[str, Position] = {}
        self.event_queue: Queue = Queue()

        self.last_entry_time = 0
        self.entry_cooldown = 5

        self.ai_filter = AIRiskFilter()
        self.ai_logger = AILogger()

        self.ai_last_score = 0.0
        self.ai_last_decision = "NONE"

        self.monitor = None

    # =====================================================
    # MONITOR SETTER
    # =====================================================
    def set_monitor(self, monitor):
        self.monitor = monitor
        if self.monitor:
            self.monitor.update_status("trade_core", True)

    # =====================================================
    # SAFE SELF HEAL（追加）
    # =====================================================
    def self_heal(self, price_dict):
        # 将来の異常復旧処理
        return

    # =====================================================
    # HEALTH CHECK（追加）
    # =====================================================
    def health_check(self):
        return

    # =====================================================
    # EMERGENCY FLUSH（追加）
    # =====================================================
    def emergency_flush(self):
        return

    # =====================================================
    # LOG WATCH（追加）
    # =====================================================
    def log_watch(self):
        return

    # =====================================================
    # EVENT EMIT
    # =====================================================
    @safe_run
    def emit(self, event: Dict[str, Any]):

        self.event_queue.put(event)

        if self.monitor:
            self.monitor.log_event("EMIT", event)

    # =====================================================
    # EVENT LOOP（修正済み）
    # =====================================================
    @safe_run
    def process_events(self, price_dict: Dict[str, float]):

        while not self.event_queue.empty():

            event = self.event_queue.get()
            etype = event.get("type")

            if etype == EventType.ENTRY:
                self._handle_entry(event)

            elif etype == EventType.POSITION_OPENED:
                self._handle_position_opened(event)

        self._handle_price_update(price_dict)

        # 🔥 修正：安全呼び出し
        if hasattr(self, "self_heal"):
            self.self_heal(price_dict)

        self.health_check()
        self.emergency_flush()
        self.log_watch()

    # =====================================================
    # ENTRY HANDLER
    # =====================================================
    def _handle_entry(self, event):

        now = time.time()

        if now - self.last_entry_time < self.entry_cooldown:
            return

        features = {
            "execution_latency": event.get("latency", 100),
            "retry_count": event.get("retry", 0),
            "state_diff": event.get("state_diff", 0),
            "volatility": event.get("volatility", 10)
        }

        score = self.ai_filter.evaluate(features)
        decision = self.ai_filter.decision(score)

        self.ai_last_score = score
        self.ai_last_decision = decision

        if decision == "BLOCK":
            print(f"[AI BLOCKED] {event['symbol']} score={score}")
            return

        signal = {
            "position_id": str(uuid.uuid4()),
            "symbol": event["symbol"],
            "side": event["side"],
            "qty": event["qty"],
            "price": event["price"],
            "sl": event["sl"],
            "tp": event["tp"]
        }

        if self.execution_engine:
            self.execution_engine.execute_order(signal)

        self.last_entry_time = now

        print(f"[ENTRY SENT] {signal['position_id']}")

    # =====================================================
    # POSITION OPEN
    # =====================================================
    def _handle_position_opened(self, event):

        pid = event["position_id"]

        pos = Position(
            id=pid,
            entry_price=event["entry_price"],
            trade_type=event["side"],
            sl=event["sl"],
            tp=event["tp"],
            volume=event["volume"],
            entry_time=datetime.datetime.now(),
            symbol=event.get("symbol", "BTCUSDT"),
            status=PositionStatus.OPEN
        )

        self.positions[pid] = pos

        print(f"[OPENED SYNC] {pid}")

    # =====================================================
    # PRICE UPDATE
    # =====================================================
    def _handle_price_update(self, price_dict):

        for pid, pos in list(self.positions.items()):

            if pos.status != PositionStatus.OPEN:
                continue

            price = price_dict.get(pos.symbol)
            if price is None:
                continue

            close_reason = None

            if pos.trade_type == "BUY":
                if price <= pos.sl:
                    close_reason = "SL"
                elif price >= pos.tp:
                    close_reason = "TP"
            else:
                if price >= pos.sl:
                    close_reason = "SL"
                elif price <= pos.tp:
                    close_reason = "TP"

            if close_reason:

                pos.status = PositionStatus.CLOSED
                pos.close_price = price

                if self.execution_engine:
                    self.execution_engine.close_order({
                        "position_id": pid,
                        "price": price,
                        "reason": close_reason
                    })

                del self.positions[pid]

                print(f"[CLOSE {close_reason}] {pid}")