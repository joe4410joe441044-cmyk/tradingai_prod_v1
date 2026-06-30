# -*- coding: utf-8 -*-

# Bot/utils/multi_timeframe_manager.py



import pandas as pd





class MultiTimeFrameManager:

    """

    EEE

    MarketEngineE

    """



    def __init__(self, base_timeframe="1m"):

        self.base_timeframe = base_timeframe

        self.data = {}  # {'BTCUSDT': DataFrame}



    def update_candle(self, symbol: str, candle: dict):

        """

        

        """

        df = self.data.get(symbol, pd.DataFrame())



        new_row = pd.DataFrame([candle])

        df = pd.concat([df, new_row], ignore_index=True)



        self.data[symbol] = df



    def get_timeframe_df(self, symbol: str, timeframe: str) -> pd.DataFrame:

        """

        E

        E "1m", "5m", "15m", "1h"

        """



        if symbol not in self.data or self.data[symbol].empty:

            return pd.DataFrame()



        #  EE
# EE

        if not isinstance(timeframe, str) or len(timeframe) < 2:

            raise ValueError(f"Invalid timeframe format: {timeframe}")



        df = self.data[symbol].copy()



        #  EEKeyErrorEE

        required_cols = {'time', 'open', 'high', 'low', 'close', 'volume'}

        if not required_cols.issubset(df.columns):

            raise ValueError(f"Missing columns: {df.columns}")



        df['time'] = pd.to_datetime(df['time'])

        df.set_index('time', inplace=True)



        # =========================

        #  E

        # =========================

        unit = timeframe[0].lower()     # m / h / d

        value = int(timeframe[1:])      # 1 / 5 / 15



        tf_map = {

            "m": "min",

            "h": "h",

            "d": "d"

        }



        if unit not in tf_map:

            raise ValueError(f"Unsupported timeframe unit: {unit}")



        resample_rule = f"{value}{tf_map[unit]}"



        # =========================

        # OHLCVE

        # =========================

        ohlc_dict = {

            'open': 'first',

            'high': 'max',

            'low': 'min',

            'close': 'last',

            'volume': 'sum'

        }



        df_resampled = (

            df

            .resample(resample_rule)

            .agg(ohlc_dict)

            .dropna()

            .reset_index()

        )



        return df_resampled



    def get_all_timeframes(self, symbol: str, timeframes: list) -> dict:

        """

        EE

        """



        result = {}



        for tf in timeframes:

            try:

                result[tf] = self.get_timeframe_df(symbol, tf)

            except Exception as e:

                print(f"[MTF ERROR] {tf}: {e}")

                result[tf] = pd.DataFrame()



        return result
