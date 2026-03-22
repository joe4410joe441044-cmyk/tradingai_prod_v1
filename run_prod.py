import asyncio
import logging
from Bot.engine.execution_engine import ExecutionEngine
from Bot.core.trade_core import TradeCore
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.engine.market_engine import MarketEngine
from Bot.wrappers.test_signal_generator import TestSignalGenerator

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)

# -------------------------
# 險ｭ螳・
# -------------------------
live_mode = False  # False: 雉・≡譛ｪ謚募・ / True: 螳溷ｼｾ
ws_url = "wss://stream.binance.com:9443/ws/btcusdt@kline_15m"

# -------------------------
# 蛻晄悄蛹・
# -------------------------
exec_engine = ExecutionEngine(live=live_mode)
trade_core = TradeCore(exec_engine)
strategy_wrapper = StrategyWrapper(trade_core)
market_engine = MarketEngine(ws_url, strategy_wrapper)

test_signal_generator = None
if not live_mode:
    test_signal_generator = TestSignalGenerator(strategy_wrapper, interval_sec=10)

# -------------------------
# 荳ｦ陦檎ｨｼ蜒・
# -------------------------
async def main():
    tasks = [market_engine.connect()]
    if test_signal_generator:
        tasks.append(test_signal_generator.run())

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logging.info("BOT謇句虚蛛懈ｭ｢ (Ctrl+C)")
    except Exception as e:
        logging.exception(f"BOT萓句､也匱逕・ {e}")
    finally:
        if test_signal_generator:
            test_signal_generator.stop()
        market_engine.stop()
        logging.info("BOT螳牙・蛛懈ｭ｢螳御ｺ・)

if __name__ == "__main__":
    asyncio.run(main())
