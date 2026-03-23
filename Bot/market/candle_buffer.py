from collections import deque
import pandas as pd

class CandleBuffer:
    """
    Candle
    SMC / FVG / BOS E
    E (M1, M5, M15, H1, H4) DataFrame
    """

    def __init__(self, maxlen=500):
        #  deque (E)
        self.candles = deque(maxlen=maxlen)

        #  DataFrame E
        self.df_M1 = pd.DataFrame()
        self.df_M5 = pd.DataFrame()
        self.df_M15 = pd.DataFrame()
        self.df_H1 = pd.DataFrame()
        self.df_H4 = pd.DataFrame()

    # ---------------------------------
    # Candle
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

        # deque 
        self.candles.append(candle)

        #  DataFrame 
        df_attr = f"df_{timeframe}"
        if not hasattr(self, df_attr):
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        df = getattr(self, df_attr)
        new_row = pd.DataFrame([candle])
        df = pd.concat([df, new_row], ignore_index=True)
        setattr(self, df_attr, df)

    # ---------------------------------
    # Candle
    # ---------------------------------
    def last(self):
        if len(self.candles) == 0:
            return None
        return self.candles[-1]

    # ---------------------------------
    # 1ECandle
    # ---------------------------------
    def prev(self):
        if len(self.candles) < 2:
            return None
        return self.candles[-2]

    # ---------------------------------
    # EE
    # ---------------------------------
    def get_last(self, n):
        return list(self.candles)[-n:]

    # ---------------------------------
    # 
    # ---------------------------------
    def size(self):
        return len(self.candles)