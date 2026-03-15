import json
import threading
import time
import websocket


class BinanceDataFeed:
    """
    Binance WebSocket DataFeed
    マルチペア対応
    """

    def __init__(self, symbols, timeframe="15m", market_engine=None, logger=None):

        self.symbols = [s.lower() for s in symbols]
        self.timeframe = timeframe

        self.market_engine = market_engine
        self.logger = logger

        self.ws = None
        self.running = False

    # ==============================
    # WebSocket URL生成
    # ==============================
    def _build_ws_url(self):

        streams = "/".join(
            [f"{symbol}@kline_{self.timeframe}" for symbol in self.symbols]
        )

        url = f"wss://stream.binance.com:9443/stream?streams={streams}"

        return url

    # ==============================
    # メッセージ受信
    # ==============================
    def _on_message(self, ws, message):

        try:

            msg = json.loads(message)

            data = msg.get("data", {})
            kline = data.get("k", {})

            if not kline:
                return

            # 確定足のみ処理
            if not kline["x"]:
                return

            market_data = {
                "symbol": kline["s"],
                "open": float(kline["o"]),
                "high": float(kline["h"]),
                "low": float(kline["l"]),
                "close": float(kline["c"]),
                "timeframe": self.timeframe,
                "timestamp": kline["t"],
            }

            if self.market_engine:
                self.market_engine.on_market_data(market_data)

        except Exception as e:

            print(f"DataFeed message error: {e}")

    # ==============================
    # 接続成功
    # ==============================
    def _on_open(self, ws):

        print("Binance WebSocket connected")

        if self.logger:
            try:
                self.logger.log_event("DATAFEED_CONNECTED", "Binance WebSocket")
            except Exception:
                pass

    # ==============================
    # エラー
    # ==============================
    def _on_error(self, ws, error):

        print(f"WebSocket error: {error}")

    # ==============================
    # 接続終了
    # ==============================
    def _on_close(self, ws, close_status_code, close_msg):

        print("Binance WebSocket closed")

    # ==============================
    # 起動
    # ==============================
    def start(self):

        url = self._build_ws_url()

        self.running = True

        def run():

            while self.running:

                try:

                    self.ws = websocket.WebSocketApp(
                        url,
                        on_message=self._on_message,
                        on_error=self._on_error,
                        on_close=self._on_close,
                        on_open=self._on_open,
                    )

                    self.ws.run_forever()

                except Exception as e:

                    print(f"WebSocket reconnect error: {e}")

                time.sleep(5)

        thread = threading.Thread(target=run)
        thread.daemon = True
        thread.start()

    # ==============================
    # 停止
    # ==============================
    def stop(self):

        self.running = False

        if self.ws:
            self.ws.close()
