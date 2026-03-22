# test_ws_market_engine.py

import json
from binance import ThreadedWebsocketManager
from Bot.engine.market_engine import MarketEngine  # 既存の MarketEngine を使用

# MarketEngine の初期化
market_engine = MarketEngine()

def handle_message(msg):
    """
    Binance WebSocket からのメッセージ処理
    """
    if msg['e'] == 'trade':  # 成行データ
        price = float(msg['p'])
        quantity = float(msg['q'])
        # MarketEngine に渡すサンプル処理
        market_engine.on_trade(price=price, quantity=quantity)
        print(f"[MarketEngine] price: {price}, qty: {quantity}")

def main():
    # Binance WebSocket Manager 初期化
    twm = ThreadedWebsocketManager()
    twm.start()

    # BTCUSDT のリアルタイム取引データを購読
    twm.start_trade_socket(callback=handle_message, symbol='BTCUSDT')

    try:
        print("WebSocket running... Press Ctrl+C to exit")
        while True:
            pass  # 永続的に待機
    except KeyboardInterrupt:
        print("Stopping WebSocket...")
        twm.stop()

if __name__ == "__main__":
    main()