from dotenv import load_dotenv
import os

from backend.execution.bybit_trade import BybitTradeClient

load_dotenv("backend/.env")

client = BybitTradeClient(
    os.getenv("BYBIT_API_KEY"),
    os.getenv("BYBIT_API_SECRET")
)

result = client.execute_order({
    "symbol": "BTCUSDT",
    "side": "BUY",
    "qty": 0.001
})

print(result)