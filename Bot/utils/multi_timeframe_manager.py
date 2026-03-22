# Bot/utils/multi_timeframe_manager.py

import pandas as pd


class MultiTimeFrameManager:
    """
    複数時間足を生成・管理するモジュール
    MarketEngineから呼び出して、戦略に渡す
    """

    def __init__(self, base_timeframe="1m"):
        self.base_timeframe = base_timeframe
        self.data = {}  # {'BTCUSDT': DataFrame}

    def update_candle(self, symbol: str, candle: dict):
        """
        新しいローソク足を追加
        """
        df = self.data.get(symbol, pd.DataFrame())

        new_row = pd.DataFrame([candle])
        df = pd.concat([df, new_row], ignore_index=True)

        self.data[symbol] = df

    def get_timeframe_df(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        任意の時間足に変換して返す
        例: "1m", "5m", "15m", "1h"
        """

        if symbol not in self.data or self.data[symbol].empty:
            return pd.DataFrame()

        # 🔥 フォーマットチェック（事故防止）
        if not isinstance(timeframe, str) or len(timeframe) < 2:
            raise ValueError(f"Invalid timeframe format: {timeframe}")

        df = self.data[symbol].copy()

        # 🔥 カラムチェック（次のKeyError防止）
        required_cols = {'time', 'open', 'high', 'low', 'close', 'volume'}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"Missing columns: {df.columns}")

        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)

        # =========================
        # 🔥 ここが今回の修正ポイント
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
        # OHLCV生成
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
        複数時間足をまとめて取得
        """

        result = {}

        for tf in timeframes:
            try:
                result[tf] = self.get_timeframe_df(symbol, tf)
            except Exception as e:
                print(f"[MTF ERROR] {tf}: {e}")
                result[tf] = pd.DataFrame()

        return result