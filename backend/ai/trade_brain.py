# -*- coding: utf-8 -*-

import time

from backend.utils.log_buffer import runtime_debug


class TradeBrain:

    def __init__(self, lstm_model, llm_engine):

        self.lstm = lstm_model
        self.llm = llm_engine

        # AIイベント履歴（UI用）
        self.events = []

        # 最大保持数
        self.max_events = 200

    # =====================================================
    # DECISION ENGINE（完全版）
    # =====================================================
    def decide(self, market_data: dict):

        features = market_data.get("features", [])

        if not features:

            runtime_debug("TradeBrain decision skipped: no features")

            return None

        lstm_signal = self.lstm.predict(features)

        llm_signal = self.llm.analyze(market_data)

        if lstm_signal == llm_signal:
            decision = lstm_signal
            confidence = 1.0
        else:
            decision = "HOLD"
            confidence = 0.5

        runtime_debug(
            "TradeBrain decision lstm=%s llm=%s match=%s decision=%s",
            lstm_signal,
            llm_signal,
            lstm_signal == llm_signal,
            decision,
        )

        # =========================
        # ★ 強化イベント（UI完全対応）
        # =========================
        event = {
            "time": time.time(),
            "type": decision,
            "stage": "CONSENSUS",
            "symbol": market_data.get("symbol", "UNKNOWN"),
            "action": decision,
            "reason": f"LSTM={lstm_signal}, LLM={llm_signal}",
            "confidence": confidence,
            "data": {
                "lstm": lstm_signal,
                "llm": llm_signal,
                "price": market_data.get("price", 0)
            }
        }

        self._add_event(event)

        return decision

    # =====================================================
    # DEBUG / EXPLAIN
    # =====================================================
    def explain(self, market_data):

        features = market_data.get("features", [])

        if not features:
            return {}

        lstm_signal = self.lstm.predict(features)
        llm_signal = self.llm.analyze(market_data)

        explanation = {
            "lstm": lstm_signal,
            "llm": llm_signal
        }

        # ★ UI対応イベント
        self._add_event({
            "time": time.time(),
            "type": "EXPLAIN",
            "stage": "DEBUG",
            "symbol": market_data.get("symbol", "UNKNOWN"),
            "action": "EXPLAIN",
            "reason": f"LSTM={lstm_signal}, LLM={llm_signal}",
            "confidence": None,
            "data": explanation
        })

        return explanation

    # =====================================================
    # EVENT SYSTEM
    # =====================================================
    def _add_event(self, event: dict):

        # 必須キー補完（安全）
        event.setdefault("time", time.time())
        event.setdefault("type", "INFO")
        event.setdefault("stage", "UNKNOWN")
        event.setdefault("symbol", "UNKNOWN")
        event.setdefault("action", event.get("type"))
        event.setdefault("reason", "")
        event.setdefault("confidence", None)
        event.setdefault("data", {})

        self.events.append(event)

        # メモリ制御
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

    def get_events(self, limit=50):
        return self.events[-limit:]
