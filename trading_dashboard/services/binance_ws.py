import asyncio
import websockets
import json
from decimal import Decimal
from services.bot_api import _bot_instance

BINANCE_WS_BASE = "wss://stream.binance.com:9443/ws"

class BinanceWSClient:
    """
    Binance WebSocket クライアント（本番接続）
    - 複数シンボル購読可
    - 最新価格を保持
    - BotAPI positions の PnL をリアルタイム更新
    """
    def __init__(self, symbol: str):
        self.symbol = symbol.lower()
        self.url = f"{BINANCE_WS_BASE}/{self.symbol}@trade"
        self.price = Decimal("0")

    async def connect(self):
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    print(f"[WS] Connected to {self.url}")
                    await self._listen(ws)
            except Exception as e:
                print(f"[WS] Error {self.symbol}: {e}")
                await asyncio.sleep(2)  # 再接続待機

    async def _listen(self, ws):
        async for message in ws:
            data = json.loads(message)
            self.price = Decimal(data["p"])
            self._update_positions()

    def _update_positions(self):
        for pos in _bot_instance.positions:
            if pos["Symbol"].lower() == self.symbol:
                entry = Decimal(str(pos["Entry"]))
                qty   = Decimal(str(pos["Qty"]))
                if pos["Side"].upper() == "BUY":
                    pos["P/L"] = float((self.price - entry) * qty)
                else:
                    pos["P/L"] = float((entry - self.price) * qty)