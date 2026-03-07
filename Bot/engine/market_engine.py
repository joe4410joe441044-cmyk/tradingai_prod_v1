import random
import pandas as pd


class MarketEngine:

    def __init__(self, start_price: float = 2000, trade_core=None):

        self.current_price = start_price
        self.trade_core = trade_core
        self.tick_count = 0

        # -----------------------------
        # buffers
        # -----------------------------

        self.m1_buffer = []
        self.m15_buffer = []
        self.h1_buffer = []

        # -----------------------------
        # DataFrames
        # -----------------------------

        self.m1 = pd.DataFrame(columns=["Open", "High", "Low", "Close"])
        self.m15 = pd.DataFrame(columns=["Open", "High", "Low", "Close"])
        self.h1 = pd.DataFrame(columns=["Open", "High", "Low", "Close"])
        self.h4 = pd.DataFrame(columns=["Open", "High", "Low", "Close"])

    # =====================================================
    # Tick生成
    # =====================================================

    def tick(self):

        change = random.uniform(-0.5, 0.5)

        self.current_price += change

        self.tick_count += 1

        if self.trade_core:
            self.trade_core.update_equity(self.trade_core.equity)

        return self.current_price

    # =====================================================
    # M1生成
    # =====================================================

    def update_m1(self, price):

        self.m1_buffer.append(price)

        # 10tick = 1 candle
        if len(self.m1_buffer) >= 10:

            o = self.m1_buffer[0]
            h = max(self.m1_buffer)
            l = min(self.m1_buffer)
            c = self.m1_buffer[-1]

            row = {"Open": o, "High": h, "Low": l, "Close": c}

            self.m1.loc[len(self.m1)] = row

            self.m1_buffer = []

            # buffer for M15
            self.m15_buffer.append(row)

            self._limit_df(self.m1)

            self._update_m15()

    # =====================================================
    # M15生成
    # =====================================================

    def _update_m15(self):

        if len(self.m15_buffer) >= 15:

            df = pd.DataFrame(self.m15_buffer[-15:])

            row = {
                "Open": df["Open"].iloc[0],
                "High": df["High"].max(),
                "Low": df["Low"].min(),
                "Close": df["Close"].iloc[-1]
            }

            self.m15.loc[len(self.m15)] = row

            self.h1_buffer.append(row)

            self._limit_df(self.m15)

            self._update_h1()

    # =====================================================
    # H1生成
    # =====================================================

    def _update_h1(self):

        if len(self.h1_buffer) >= 4:

            df = pd.DataFrame(self.h1_buffer[-4:])

            row = {
                "Open": df["Open"].iloc[0],
                "High": df["High"].max(),
                "Low": df["Low"].min(),
                "Close": df["Close"].iloc[-1]
            }

            self.h1.loc[len(self.h1)] = row

            self._limit_df(self.h1)

            self._update_h4()

    # =====================================================
    # H4生成
    # =====================================================

    def _update_h4(self):

        if len(self.h1) >= 4:

            df = self.h1.tail(4)

            row = {
                "Open": df["Open"].iloc[0],
                "High": df["High"].max(),
                "Low": df["Low"].min(),
                "Close": df["Close"].iloc[-1]
            }

            self.h4.loc[len(self.h4)] = row

            self._limit_df(self.h4)

    # =====================================================
    # DataFrame制限
    # =====================================================

    def _limit_df(self, df, max_rows=500):

        if len(df) > max_rows:
            df.drop(index=df.index[:-max_rows], inplace=True)
            df.reset_index(drop=True, inplace=True)

    # =====================================================
    # BOT用データ取得
    # =====================================================

    def get_market_data(self):

        price = self.tick()

        self.update_m1(price)

        return {
            "price": price,
            "m1": self.m1,
            "m15": self.m15,
            "h1": self.h1,
            "h4": self.h4
        }