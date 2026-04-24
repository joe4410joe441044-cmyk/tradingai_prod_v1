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
# TRADE CORE (AI INTEGRATED + MONITORING)
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

        # =========================
        # MONITOR（追加）
        # =========================
        self.monitor = None

    # =====================================================
    # MONITOR SETTER ★追加
    # =====================================================
    def set_monitor(self, monitor):

        self.monitor = monitor

        if self.monitor:
            self.monitor.update_status("trade_core", True)

    # =====================================================
    # EVENT DISPATCHER
    # =====================================================
    @safe_run
    def emit(self, event: Dict[str, Any]):

        self.event_queue.put(event)

        # ★MONITOR EVENT
        if self.monitor:
            self.monitor.log_event("EMIT", event)

    # =====================================================
    # EVENT LOOP
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

        self.self_heal(price_dict)
        self.health_check()
        self.emergency_flush()
        self.log_watch()

    # =====================================================
    # ENTRY HANDLER + AI FILTER
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
        ai_decision = self.ai_filter.decision(score)

        self.ai_last_score = score
        self.ai_last_decision = ai_decision

        # =========================
        # MONITOR LOG ★追加
        # =========================
        if self.monitor:
            self.monitor.log_event("AI_EVALUATION", {
                "symbol": event["symbol"],
                "score": score,
                "decision": ai_decision
            })

        if ai_decision == "BLOCK":

            self.ai_logger.log_decision(
                symbol=event["symbol"],
                bot_signal="ENTRY_BLOCKED",
                ai_score=score,
                ai_decision=ai_decision,
                final_action="SKIP"
            )

            if self.monitor:
                self.monitor.log_event("ENTRY_BLOCKED", event)

            print(f"[AI BLOCKED] {event['symbol']} score={score}")
            return

        signal = {
            "position_id": str(uuid.uuid4()),
            "symbol": event["symbol"],
            "side": event["side"],
            "qty": event["qty"],
            "price": event["price"],
            "sl": event["sl"],
            "tp": event["tp"],
            "strategy": event.get("strategy", "default"),
            "timeframe": event.get("timeframe", "1m")
        }

        if self.execution_engine:
            self.execution_engine.execute_order(signal)

        self.last_entry_time = now

        # =========================
        # MONITOR ENTRY
        # =========================
        if self.monitor:
            self.monitor.log_event("ENTRY", signal)

        self.ai_logger.log_decision(
            symbol=event["symbol"],
            bot_signal="ENTRY",
            ai_score=score,
            ai_decision=ai_decision,
            final_action="EXECUTE"
        )

        print(f"[ENTRY SENT] {signal['position_id']} AI={score}")

    # =====================================================
    # POSITION OPEN SYNC
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

        # =========================
        # MONITOR OPEN
        # =========================
        if self.monitor:
            self.monitor.log_event("POSITION_OPENED", {"position_id": pid})

        print(f"[OPENED SYNC] {pid}")

    # =====================================================
    # PRICE UPDATE（省略なし）
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

                # =========================
                # MONITOR CLOSE
                # =========================
                if self.monitor:
                    self.monitor.log_event("CLOSE", {
                        "position_id": pid,
                        "reason": close_reason,
                        "price": price
                    })

                del self.positions[pid]

                print(f"[CLOSE {close_reason}] {pid}")