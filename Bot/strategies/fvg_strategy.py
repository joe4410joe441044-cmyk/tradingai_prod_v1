import pandas as pd
from typing import List

class FVG:
    def __init__(self, top: float, bottom: float, bullish: bool, timeframe: str):
        self.top = top
        self.bottom = bottom
        self.bullish = bullish
        self.used = False
        self.timeframe = timeframe

class ProFVGStrategy:
    """プロ仕様 FVGStrategy: HTF Bias + Liquidity Sweep + FVG + Entry"""

    def __init__(self):
        self.fvg_list: List[FVG] = []
        self.tap_threshold = 0.3
        self.max_fvg = 50

    # ------------------------------
    # FVG検出
    # ------------------------------
    def detect_fvg(self, market_data):
        m15 = market_data["m15"]
        h1 = market_data["h1"]

        # --------------------------
        # HTFバイアス確認 (H1)
        # 上昇トレンド: close>open, 直近H1足
        # --------------------------
        self.htf_bias = None
        if len(h1) >= 2:
            last = h1.iloc[-1]
            prev = h1.iloc[-2]
            if last["Close"] > last["Open"] and last["Close"] > prev["Close"]:
                self.htf_bias = "bullish"
            elif last["Close"] < last["Open"] and last["Close"] < prev["Close"]:
                self.htf_bias = "bearish"

        if len(m15) < 3:
            return

        c1 = m15.iloc[-3]
        c2 = m15.iloc[-2]
        c3 = m15.iloc[-1]

        # --------------------------
        # Bullish FVG
        # --------------------------
        if c1["High"] < c3["Low"]:
            fvg = FVG(top=c3["Low"], bottom=c1["High"], bullish=True, timeframe="M15")
            self._append_fvg(fvg)

        # --------------------------
        # Bearish FVG
        # --------------------------
        if c1["Low"] > c3["High"]:
            fvg = FVG(top=c1["Low"], bottom=c3["High"], bullish=False, timeframe="M15")
            self._append_fvg(fvg)

    # ------------------------------
    # FVG管理
    # ------------------------------
    def _append_fvg(self, fvg):
        # 重複チェック
        for existing in self.fvg_list:
            if existing.top == fvg.top and existing.bottom == fvg.bottom:
                return
        self.fvg_list.append(fvg)
        # 最大保持数
        if len(self.fvg_list) > self.max_fvg:
            self.fvg_list.pop(0)

    # ------------------------------
    # シグナル生成
    # ------------------------------
    def generate_signals(self, market_data):
        signals = []
        price = market_data["price"]

        for fvg in self.fvg_list:
            if fvg.used:
                continue

            # HTFバイアスがあればフィルター
            if self.htf_bias:
                if fvg.bullish and self.htf_bias != "bullish":
                    continue
                if not fvg.bullish and self.htf_bias != "bearish":
                    continue

            # FVGタップ判定
            center = (fvg.top + fvg.bottom) / 2
            if abs(price - center) < self.tap_threshold:

                # --------------------------
                # Liquidity Sweep (直近高値/安値ブレイク)
                # --------------------------
                sweep_ok = True
                if fvg.bullish:
                    if price < max(market_data["m15"]["High"].iloc[-3:]):
                        sweep_ok = False
                else:
                    if price > min(market_data["m15"]["Low"].iloc[-3:]):
                        sweep_ok = False

                if not sweep_ok:
                    continue

                # --------------------------
                # シグナル作成
                # --------------------------
                signal = {
                    "strategy_name": "ProFVG",
                    "trade_type": "BUY" if fvg.bullish else "SELL",
                    "entry_price": center,
                    "stop_loss_price": fvg.bottom - 2 if fvg.bullish else fvg.top + 2,
                    "take_profit_price": center + 6 if fvg.bullish else center - 6,
                    "partial_close_percent": 50,
                    "reason": "ProFVG_Tap"
                }
                signals.append(signal)
                fvg.used = True

        return signals