# test_ws_market_engine_full.py

import json
from binance import ThreadedWebsocketManager

# === 本番用 MarketEngine と戦略ラッパー ===
from Bot.engine.market_engine import MarketEngine
from Bot.strategy.strategy_wrapper import StrategyWrapper  # 本番戦略

# === サンプル用 MarketEngine（安全モード） ===
class DummyStrategyWrapper:
    """サンプル用: print のみ"""
    def on_trade(self, price, quantity):
        print(f"[Sample DummyStrategy] price={price}, qty={quantity}")

class SampleMarketEngine(MarketEngine):
    """サンプル用 MarketEngine"""
    def __init__(self, ws_url):
        strategy_wrapper = DummyStrategyWrapper()
        super().__init__(ws_url, strategy_wrapper)

# =========================
#  WebSocket 接続テスト用関数
# =========================
def run_sample_ws_test(symbol="BTCUSDT"):
    """
    SampleMarketEngine を使って WebSocket データ受信テスト
    """
    ws_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@trade"
    sample_engine = SampleMarketEngine(ws_url)

    def handle_message(msg):
        if msg['e'] == 'trade':
            price = float(msg['p'])
            quantity = float(msg['q'])
            # SampleMarketEngine に渡す
            sample_engine.on_trade(price, quantity)

    # Binance ThreadedWebsocketManager を開始
    twm = ThreadedWebsocketManager()
    twm.start()

    # Trade Stream を購読
    twm.start_trade_socket(callback=handle_message, symbol=symbol)

    print(f"[Sample] WebSocket running for {symbol}... Ctrl+C to stop")
    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("[Sample] Stopping WebSocket...")
        twm.stop()

# =========================
# 実行用
# =========================
if __name__ == "__main__":
    # ここを True にすると本番用 MarketEngine を使った接続も可能
    use_production = False

    if use_production:
        # ⚠ 本番用 MarketEngine (注文やシグナル処理あり)
        ws_url = "wss://stream.binance.com:9443/ws/btcusdt@trade"
        strategy_wrapper = StrategyWrapper()
        prod_engine = MarketEngine(ws_url, strategy_wrapper)
        print("[Production] MarketEngine initialized. WebSocket running...")
        # 実際の本番処理は prod_engine 内で WebSocket を自動開始する想定
    else:
        # 安全モードのサンプル MarketEngine で WebSocket テスト
        run_sample_ws_test("BTCUSDT")