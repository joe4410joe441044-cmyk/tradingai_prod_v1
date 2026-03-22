import asyncio
from datetime import datetime, timedelta
from core.trade_core import TradeCore, BotLogger
from engine.market_engine import MarketEngine
from strategies.fvg_strategy import FVGStrategy
from strategies.rsi_strategy import RSIStrategy

# --------------------------
# 初期化（🔥ここ修正）
# --------------------------
logger = BotLogger().get_logger()   # ← ここ重要（.get_logger()）

trade_core = TradeCore(logger=logger)

strategies = [
    FVGStrategy(trade_core=trade_core, logger=logger),
    RSIStrategy(trade_core=trade_core, logger=logger)
]

engine = MarketEngine(strategies=strategies, debug=True)

# --------------------------
# ダミーデータ生成
# --------------------------
def generate_candles(num=100):
    candles = []
    price = 30000
    t = datetime.now() - timedelta(minutes=num)

    for _ in range(num):
        candle = {
            "symbol": "BTCUSDT",
            "time": t.strftime("%Y-%m-%d %H:%M:%S"),
            "open": price,
            "high": price + 50,
            "low": price - 50,
            "close": price + 10,
            "volume": 10,
        }
        candles.append(candle)
        price += 5
        t += timedelta(minutes=1)

    return candles

# --------------------------
# 実行
# --------------------------
async def run():
    logger.info("=== シミュレーション開始 ===")

    candles = generate_candles(200)

    for c in candles:
        engine.process_data(c)

        # 現在価格をTradeCoreへ渡す
        price_dict = {
            c["symbol"]: c["close"]
        }

        trade_core.check_orders(price_dict)

        await asyncio.sleep(0.01)

    logger.info("=== シミュレーション終了 ===")

# --------------------------
# 実行エントリ
# --------------------------
if __name__ == "__main__":
    asyncio.run(run())