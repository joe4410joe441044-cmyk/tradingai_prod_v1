# -*- coding: utf-8 -*-
from typing import Literal, List, Dict, Optional
from datetime import datetime
import threading
import json
import time
from websocket import WebSocketApp  # websocket-client パッケージが必要

class BotAPI:
    """
    Binance WebSocket対応・本番用BotAPI
    安定したリアルタイム価格更新
    """
    def __init__(
        self,
        symbol: str = "BTCUSDT",
        lot: float = 1.0,
        risk_percent: float = 2.0,
        sl_pips: int = 20,
        strategy: str = "FVG"
    ):
        self.status: Literal["stopped", "running", "emergency"] = "stopped"
        self.symbol: str = symbol.upper()
        self.lot: float = lot
        self.risk_percent: float = risk_percent
        self.sl_pips: int = sl_pips
        self.strategy: str = strategy

        self.positions: List[Dict] = []
        self.pnl_history: List[Dict] = []
        self.status_history: List[str] = []

        # WebSocket管理
        self.price: float = 0.0
        self.ws_app: Optional[WebSocketApp] = None
        self.ws_thread: Optional[threading.Thread] = None
        self._stop_ws_flag: bool = False

    # ----------------------------
    # 内部ログ
    # ----------------------------
    def _log(self, message: str):
        log = f"{datetime.now()} | {message}"
        self.status_history.append(log)
        print(f"[BotAPI] {message}")

    # ----------------------------
    # Bot操作
    # ----------------------------
    def start_bot(self):
        if self.status == "running": return self.status
        self.status = "running"
        self._log(f"START Bot (Symbol={self.symbol}, Lot={self.lot}, Risk={self.risk_percent}%, SL={self.sl_pips}, Strategy={self.strategy})")
        return self.status

    def stop_bot(self):
        if self.status == "stopped": return self.status
        self.status = "stopped"
        self._log("STOP Bot")
        return self.status

    def emergency_stop(self):
        self.status = "emergency"
        self._log("EMERGENCY STOP Bot")
        self.close_all_positions()
        return self.status

    def get_status(self) -> str:
        return self.status

    # ----------------------------
    # 設定管理
    # ----------------------------
    def set_symbol(self, symbol: str):
        self.symbol = symbol.upper()
        self._log(f"Symbol set -> {self.symbol}")
        self.stop_ws()
        self.start_ws()
        return self.symbol

    def set_lot(self, lot: float):
        self.lot = lot
        self._log(f"Lot set -> {lot}")
        return self.lot

    def set_risk(self, risk: float):
        self.risk_percent = risk
        self._log(f"Risk % set -> {risk}")
        return self.risk_percent

    def set_sl(self, sl: int):
        self.sl_pips = sl
        self._log(f"SL Width set -> {sl} pips")
        return self.sl_pips

    def set_strategy(self, strategy: str):
        self.strategy = strategy
        self._log(f"Strategy set -> {strategy}")
        return self.strategy

    # ----------------------------
    # ポジション管理
    # ----------------------------
    def open_position(self, side: Literal["BUY","SELL"]="BUY", price: float=0.0, qty: Optional[float]=None):
        if qty is None: qty = self.lot
        pos = {
            "Symbol": self.symbol,
            "Side": side,
            "Qty": qty,
            "Entry": price,
            "OpenTime": datetime.now(),
            "P/L": 0.0
        }
        self.positions.append(pos)
        self._log(f"OPEN {side} {self.symbol} Qty={qty} Price={price}")
        return pos

    def close_position(self, symbol: str):
        closed = []
        remaining = []
        for pos in self.positions:
            if pos["Symbol"] == symbol:
                pos["CloseTime"] = datetime.now()
                pnl = (self.price - pos["Entry"]) * pos["Qty"] * (1 if pos["Side"]=="BUY" else -1)
                pos["P/L"] = round(pnl, 2)
                self.pnl_history.append(pos)
                closed.append(pos)
                self._log(f"CLOSE {pos['Side']} {symbol} P/L={pos['P/L']}")
            else:
                remaining.append(pos)
        self.positions = remaining
        return closed

    def close_all_positions(self):
        symbols = list(set([p["Symbol"] for p in self.positions]))
        for sym in symbols: self.close_position(sym)
        self._log("ALL POSITIONS CLOSED")
        return self.pnl_history

    # ----------------------------
    # データ取得
    # ----------------------------
    def get_positions(self): return self.positions
    def get_trade_history(self): return self.pnl_history
    def get_status_history(self): return self.status_history
    def get_all_state(self):
        return {
            "status": self.status,
            "symbol": self.symbol,
            "lot": self.lot,
            "risk_percent": self.risk_percent,
            "sl_pips": self.sl_pips,
            "strategy": self.strategy,
            "positions": self.positions,
            "pnl_history": self.pnl_history,
            "price": self.price
        }

    # ----------------------------
    # WebSocket価格更新（本番 Binance 接続）
    # ----------------------------
    def _ws_on_message(self, ws, message):
        data = json.loads(message)
        self.price = float(data['c'])  # Binance ticker price

        # =========================
        # 🔥 Engineへ価格を流す（最重要）
        # =========================
        try:
            from backend.bot_manager import get_bot_manager
            bot = get_bot_manager()
            engine = bot.get_engine()

            if engine:
                engine.on_price(self.price)

        except Exception as e:
            print("[ENGINE PRICE UPDATE ERROR]", e)

        # =========================
        # PnL更新
        # =========================
        for pos in self.positions:
            pos["P/L"] = round(
                (self.price - pos["Entry"]) * pos["Qty"] *
                (1 if pos["Side"]=="BUY" else -1),
                2
            )

    def _ws_on_error(self, ws, error):
        print(f"[WS] Error {self.symbol}: {error}")

    def _ws_on_close(self, ws, close_status_code, close_msg):
        print(f"[WS] Closed {self.symbol}")
        if not self._stop_ws_flag:
            time.sleep(2)
            self.start_ws()

    def _ws_on_open(self, ws):
        print(f"[WS] Connected {self.symbol}")

    def start_ws(self):
        if self.ws_thread and self.ws_thread.is_alive(): return
        self._stop_ws_flag = False
        url = f"wss://stream.binance.com:9443/ws/{self.symbol.lower()}@ticker"
        self.ws_app = WebSocketApp(
            url,
            on_message=self._ws_on_message,
            on_error=self._ws_on_error,
            on_close=self._ws_on_close,
            on_open=self._ws_on_open
        )
        self.ws_thread = threading.Thread(target=self.ws_app.run_forever, daemon=True)
        self.ws_thread.start()
        self._log(f"WebSocket started for {self.symbol}")

    def stop_ws(self):
        self._stop_ws_flag = True
        if self.ws_app:
            self.ws_app.close()
        self._log(f"WebSocket stopping for {self.symbol}")


# ----------------------------
# グローバルBotインスタンス
# ----------------------------
_bot_instance = BotAPI()

def send_bot_command(cmd: str, data=None):
    if cmd == "START":
        res = _bot_instance.start_bot()
        _bot_instance.start_ws()
        return res
    if cmd == "STOP":
        return _bot_instance.stop_bot()
    if cmd == "EMERGENCY_STOP":
        return _bot_instance.emergency_stop()
    if cmd == "SET_SYMBOL" and data:
        _bot_instance.set_symbol(data)
        return _bot_instance.get_all_state()
    if cmd == "SET_LOT" and data: return _bot_instance.set_lot(data)
    if cmd == "SET_RISK" and data: return _bot_instance.set_risk(data)
    if cmd == "SET_SL" and data: return _bot_instance.set_sl(data)
    if cmd == "SET_STRATEGY" and data: return _bot_instance.set_strategy(data)