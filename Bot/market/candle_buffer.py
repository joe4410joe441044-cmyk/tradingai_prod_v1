from collections import deque
import pandas as pd

class CandleBuffer:
    """
    Candle履歴を保持するクラス
    SMC / FVG / BOS 検出用
    各時間足 (M1, M5, M15, H1, H4) のDataFrameも保持
    """

    def __init__(self, maxlen=500):
        # 単一ローソク足 deque (必要に応じて)
        self.candles = deque(maxlen=maxlen)

        # 時間足ごとの DataFrame 初期化
        self.df_M1 = pd.DataFrame()
        self.df_M5 = pd.DataFrame()
        self.df_M15 = pd.DataFrame()
        self.df_H1 = pd.DataFrame()
        self.df_H4 = pd.DataFrame()

    # ---------------------------------
    # Candle追加
    # ---------------------------------
    def add_candle(self, candle, timeframe="M1"):
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
        timeframe: "M1", "M5", "M15", "H1", "H4"
        """

        # deque に追加
        self.candles.append(candle)

        # 時間足 DataFrame に追加
        df_attr = f"df_{timeframe}"
        if not hasattr(self, df_attr):
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        df = getattr(self, df_attr)
        new_row = pd.DataFrame([candle])
        df = pd.concat([df, new_row], ignore_index=True)
        setattr(self, df_attr, df)

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