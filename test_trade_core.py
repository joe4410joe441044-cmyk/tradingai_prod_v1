from Bot.core.trade_core import TradeCore

# ダミーExecutionEngine
class DummyEngine:
    def execute_order(self, signal):
        print("[DUMMY EXECUTE]", signal)

    def close_order(self, signal):
        print("[DUMMY CLOSE]", signal)


engine = DummyEngine()
bot = TradeCore(execution_engine=engine)


# =========================
# 1. エントリーイベント
# =========================
bot.emit({
    "type": "ENTRY",
    "symbol": "BTCUSDT",
    "side": "BUY",
    "qty": 0.001,
    "price": 40000,
    "sl": 39000,
    "tp": 41000
})

# キュー処理
bot.process_events({"BTCUSDT": 40000})


# =========================
# 2. TPテスト
# =========================
bot.process_events({"BTCUSDT": 41000})


# =========================
# 3. SLテスト
# =========================
bot.process_events({"BTCUSDT": 38000})