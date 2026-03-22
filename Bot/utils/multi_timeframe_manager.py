import pandas as pd

class MultiTimeFrameManager:
    """
    複数時間足を生成・管理するモジュール
    MarketEngineから呼び出して、戦略に渡す
    """

    def __init__(self, base_timeframe="1m"):
        self.base_timeframe = base_timeframe
        self.data = {}  # 各シンボルの生足データ {'BTCUSDT': pd.DataFrame, ...}

    def update_candle(self, symbol: str, candle: dict):
        """
        1分足などの新しいローソク足を追加
        candle = {'time': ..., 'open': ..., 'high': ..., 'low': ..., 'close': ..., 'volume': ...}
        """
        df = self.data.get(symbol, pd.DataFrame())
        new_row = pd.DataFrame([candle])
        df = pd.concat([df, new_row], ignore_index=True)
        self.data[symbol] = df

    def get_timeframe_df(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        任意の時間足に変換して返す
        timeframe例: "5m", "15m", "1h"
        """
        if symbol not in self.data or self.data[symbol].empty:
            return pd.DataFrame()

        df = self.data[symbol].copy()
        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)

        # リサンプリング
        tf_map = {
            "m": "min",
            "h": "h",
            "d": "d"
        }
        unit = timeframe[-1]
        value = int(timeframe[:-1])
        resample_rule = f"{value}{tf_map[unit]}"

        ohlc_dict = {
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }

        df_resampled = df.resample(resample_rule).agg(ohlc_dict).dropna().reset_index()
        return df_resampled

    def get_all_timeframes(self, symbol: str, timeframes: list) -> dict:
        """
        複数時間足をまとめて取得
        """
        result = {}
        for tf in timeframes:
            result[tf] = self.get_timeframe_df(symbol, tf)
        return result