# test_ws_market_engine_safe_fixed.py

from binance import ThreadedWebsocketManager
from Bot.engine.market_engine import MarketEngine

# -----------------------------
# サンプル用戦略ラッパー（安全モード）
# -----------------------------
class DummyStrategyWrapper:
    def on_trade(self, price, quantity):
        print(f"[Sample DummyStrategy] price={price}, qty={quantity}")

# -----------------------------
# サンプル用 MarketEngine
# -----------------------------
class SampleMarketEngine(MarketEngine):
    def __init__(self, ws_url):
        self.strategy_wrapper = DummyStrategyWrapper()  # 内部保持
        super().__init__(ws_url, self.strategy_wrapper)

    # ←ここを追加
    def on_trade(self, price, quantity):
        """WebSocket からのデータを戦略に渡す"""
        self.strategy_wrapper.on_trade(price, quantity)

# -----------------------------
# WebSocket テスト関数
# -----------------------------
def run_sample_ws_test(symbol="BTCUSDT"):
    ws_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@trade"
    sample_engine = SampleMarketEngine(ws_url)

    def handle_message(msg):
        if msg['e'] == 'trade':
            price = float(msg['p'])
            quantity = float(msg['q'])
            sample_engine.on_trade(price, quantity)

    twm = ThreadedWebsocketManager()
    twm.start()
    twm.start_trade_socket(callback=handle_message, symbol=symbol)

    print(f"[Sample] WebSocket running for {symbol}... Ctrl+C to stop")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("[Sample] Stopping WebSocket...")
        twm.stop()

# -----------------------------
# 実行用
# -----------------------------
if __name__ == "__main__":
    run_sample_ws_test("BTCUSDT")