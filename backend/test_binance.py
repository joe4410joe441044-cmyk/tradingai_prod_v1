from binance_client import BinanceClient
from trade_core import TradeCore

# Binance APIキーは小LOT用アカウントを使用
binance = BinanceClient(api_key="mOe3Cg2P1tMR2DDN1b4tlxmRk8rU04rXV3WsetNfoEosTzp3GeZ4EpCyOER3nLCL", api_secret="y35IZdh883LJWQiMvvNcKzPdC93HdVWk3ieD5DTPADtxUkWCEVenr4O5N4IqYtuf")
core = TradeCore(binance)

# 小LOTテスト
core.try_enter("BTCUSDT", "BUY", 0.001)
core.try_exit("BTCUSDT", "SELL", 0.001)