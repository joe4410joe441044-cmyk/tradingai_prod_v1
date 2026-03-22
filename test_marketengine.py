import asyncio
from Bot.engine.market_engine import MarketEngine
from Bot.wrappers.dummy_strategy import DummyStrategy

TEST_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"

async def main():
    strategy = DummyStrategy()
    engine = MarketEngine(ws_url=TEST_WS_URL, strategy_wrapper=strategy, debug=True)
    
    task = asyncio.create_task(engine.connect())
    await asyncio.sleep(10)
    engine.stop()
    await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())