from collections import deque


class CandleBuffer:
    """
    Candle履歴を保持するクラス
    SMC / FVG / BOS 検出用
    """

    def __init__(self, maxlen=500):

        # ローソク保存
        self.candles = deque(maxlen=maxlen)

    # ---------------------------------
    # Candle追加
    # ---------------------------------
    def add_candle(self, candle):

        """
        candle format

        {
            "symbol": "BTCUSDT",
            "open": 100,
            "high": 110,
            "low": 95,
            "close": 108,
            "timestamp": 123456
        }
        """

        self.candles.append(candle)

    # ---------------------------------
    # 最新Candle
    # ---------------------------------
    def last(self):

        if len(self.candles) == 0:
            return None

        return self.candles[-1]

    # ---------------------------------
    # 1つ前のCandle
    # ---------------------------------
    def prev(self):

        if len(self.candles) < 2:
            return None

        return self.candles[-2]

    # ---------------------------------
    # 指定数取得
    # ---------------------------------
    def get_last(self, n):

        return list(self.candles)[-n:]

    # ---------------------------------
    # サイズ
    # ---------------------------------
    def size(self):

        return len(self.candles)