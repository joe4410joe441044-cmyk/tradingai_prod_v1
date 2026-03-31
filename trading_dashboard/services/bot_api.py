# -*- coding: utf-8 -*-
from typing import Literal, List, Dict, Optional
from datetime import datetime


class BotAPI:
    """
    強化版 BotAPI（実運用対応）
    - 状態管理: stopped / running / emergency
    - シンボル管理（UI連携）
    - ポジション管理
    - PnL履歴管理
    - ログ管理
    """

    def __init__(self, lot: float = 1.0):
        self.status: Literal["stopped", "running", "emergency"] = "stopped"
        self.symbol: str = "BTCUSDT"
        self.lot: float = lot

        self.positions: List[Dict] = []
        self.pnl_history: List[Dict] = []
        self.status_history: List[str] = []

    # =========================
    # 内部ログ
    # =========================
    def _log(self, message: str):
        log = f"{datetime.now()} | {message}"
        self.status_history.append(log)
        print(f"[BotAPI] {message}")

    # =========================
    # Bot 操作
    # =========================
    def start_bot(self):
        if self.status == "running":
            return self.status

        self.status = "running"
        self._log(f"START (Symbol={self.symbol}, Lot={self.lot})")
        return self.status

    def stop_bot(self):
        if self.status == "stopped":
            return self.status

        self.status = "stopped"
        self._log("STOP")
        return self.status

    def emergency_stop(self):
        self.status = "emergency"
        self._log("EMERGENCY STOP")

        # 全ポジションクローズ
        self.close_all_positions()
        return self.status

    def get_status(self) -> str:
        return self.status

    # =========================
    # シンボル管理（UI連携）
    # =========================
    def set_symbol(self, symbol: str):
        self.symbol = symbol
        self._log(f"SYMBOL CHANGE -> {symbol}")
        return self.symbol

    def get_symbol(self) -> str:
        return self.symbol

    # =========================
    # ポジション管理
    # =========================
    def open_position(
        self,
        symbol: Optional[str] = None,
        side: Literal["BUY", "SELL"] = "BUY",
        price: float = 0.0,
        qty: Optional[float] = None,
    ):
        if symbol is None:
            symbol = self.symbol

        if qty is None:
            qty = self.lot

        pos = {
            "Symbol": symbol,
            "Side": side,
            "Qty": qty,
            "Entry": price,
            "OpenTime": datetime.now(),
        }

        self.positions.append(pos)
        self._log(f"OPEN {side} {symbol} Qty={qty} Price={price}")

        return pos

    def close_position(self, symbol: str):
        closed_positions = []
        remaining_positions = []

        for pos in self.positions:
            if pos["Symbol"] == symbol:
                # モックPnL（後で実価格に置き換え）
                pnl = (pos["Entry"] * pos["Qty"]) * (
                    1 if pos["Side"] == "BUY" else -1
                ) * 0.01

                pos["CloseTime"] = datetime.now()
                pos["P/L"] = round(pnl, 2)

                self.pnl_history.append(pos)
                closed_positions.append(pos)

                self._log(
                    f"CLOSE {pos['Side']} {symbol} P/L={pos['P/L']}"
                )
            else:
                remaining_positions.append(pos)

        self.positions = remaining_positions
        return closed_positions

    def close_all_positions(self):
        symbols = list(set([pos["Symbol"] for pos in self.positions]))

        for symbol in symbols:
            self.close_position(symbol)

        self._log("ALL POSITIONS CLOSED")
        return self.pnl_history

    # =========================
    # データ取得
    # =========================
    def get_positions(self) -> List[Dict]:
        return self.positions

    def get_trade_history(self) -> List[Dict]:
        return self.pnl_history

    def get_status_history(self) -> List[str]:
        return self.status_history

    def get_all_state(self) -> Dict:
        """
        UIやAPI用まとめ取得
        """
        return {
            "status": self.status,
            "symbol": self.symbol,
            "positions": self.positions,
            "pnl_history": self.pnl_history,
        }