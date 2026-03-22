# Bot/utils/multi_timeframe_manager.py

import pandas as pd


class MultiTimeFrameManager:
    """
    隍・焚譎る俣雜ｳ繧堤函謌舌・邂｡逅・☆繧九Δ繧ｸ繝･繝ｼ繝ｫ
    MarketEngine縺九ｉ蜻ｼ縺ｳ蜃ｺ縺励※縲∵姶逡･縺ｫ貂｡縺・
    """

    def __init__(self, base_timeframe="1m"):
        self.base_timeframe = base_timeframe
        self.data = {}  # {'BTCUSDT': DataFrame}

    def update_candle(self, symbol: str, candle: dict):
        """
        譁ｰ縺励＞繝ｭ繝ｼ繧ｽ繧ｯ雜ｳ繧定ｿｽ蜉
        """
        df = self.data.get(symbol, pd.DataFrame())

        new_row = pd.DataFrame([candle])
        df = pd.concat([df, new_row], ignore_index=True)

        self.data[symbol] = df

    def get_timeframe_df(self, symbol: str, timeframe: str) -> pd.DataFrame:
        """
        莉ｻ諢上・譎る俣雜ｳ縺ｫ螟画鋤縺励※霑斐☆
        萓・ "1m", "5m", "15m", "1h"
        """

        if symbol not in self.data or self.data[symbol].empty:
            return pd.DataFrame()

        # 櫨 繝輔か繝ｼ繝槭ャ繝医メ繧ｧ繝・け・井ｺ区腐髦ｲ豁｢・・
        if not isinstance(timeframe, str) or len(timeframe) < 2:
            raise ValueError(f"Invalid timeframe format: {timeframe}")

        df = self.data[symbol].copy()

        # 櫨 繧ｫ繝ｩ繝繝√ぉ繝・け・域ｬ｡縺ｮKeyError髦ｲ豁｢・・
        required_cols = {'time', 'open', 'high', 'low', 'close', 'volume'}
        if not required_cols.issubset(df.columns):
            raise ValueError(f"Missing columns: {df.columns}")

        df['time'] = pd.to_datetime(df['time'])
        df.set_index('time', inplace=True)

        # =========================
        # 櫨 縺薙％縺御ｻ雁屓縺ｮ菫ｮ豁｣繝昴う繝ｳ繝・
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
        # OHLCV逕滓・
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
        隍・焚譎る俣雜ｳ繧偵∪縺ｨ繧√※蜿門ｾ・
        """

        result = {}

        for tf in timeframes:
            try:
                result[tf] = self.get_timeframe_df(symbol, tf)
            except Exception as e:
                print(f"[MTF ERROR] {tf}: {e}")
                result[tf] = pd.DataFrame()

        return result
