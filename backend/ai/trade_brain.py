# -*- coding: utf-8


class TradeBrain:

    def __init__(self, lstm_model, llm_engine):

        self.lstm = lstm_model
        self.llm = llm_engine

    # =====================================================
    # DECISION ENGINE
    # =====================================================
    def decide(self, market_data: dict):

        lstm_signal = self.lstm.predict(market_data["features"])
        llm_signal = self.llm.analyze(market_data)

        # =========================
        # CONSENSUS
        # =========================
        if lstm_signal == llm_signal:
            return lstm_signal

        return "HOLD"

    # =====================================================
    # DEBUG
    # =====================================================
    def explain(self, market_data):

        return {
            "lstm": self.lstm.predict(market_data["features"]),
            "llm": self.llm.analyze(market_data)
        }