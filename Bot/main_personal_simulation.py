import asyncio
from datetime import datetime, timedelta
from core.trade_core import TradeCore, BotLogger
from engine.market_engine import MarketEngine
from strategies.fvg_strategy import FVGStrategy
from strategies.rsi_strategy import RSIStrategy

# --------------------------
# 蛻晄悄蛹厄ｼ芋沐･縺薙％菫ｮ豁｣・・
# --------------------------
logger = BotLogger().get_logger()   # 竊・縺薙％驥崎ｦ・ｼ・get_logger()・・

trade_core = TradeCore(logger=logger)

strategies = [
    FVGStrategy(trade_core=trade_core, logger=logger),
    RSIStrategy(trade_core=trade_core, logger=logger)
]

engine = MarketEngine(strategies=strategies, debug=True)

# --------------------------
# 繝繝溘・繝・・繧ｿ逕滓・
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
# 螳溯｡・
# --------------------------
async def run():
    logger.info("=== 繧ｷ繝溘Η繝ｬ繝ｼ繧ｷ繝ｧ繝ｳ髢句ｧ・===")

    candles = generate_candles(200)

    for c in candles:
        engine.process_data(c)

        # 迴ｾ蝨ｨ萓｡譬ｼ繧探radeCore縺ｸ貂｡縺・
        price_dict = {
            c["symbol"]: c["close"]
        }

        trade_core.check_orders(price_dict)

        await asyncio.sleep(0.01)

    logger.info("=== 繧ｷ繝溘Η繝ｬ繝ｼ繧ｷ繝ｧ繝ｳ邨ゆｺ・===")

# --------------------------
# 螳溯｡後お繝ｳ繝医Μ
# --------------------------
if __name__ == "__main__":
    asyncio.run(run())
