# run_prod.py
import asyncio
import logging
from Bot.engine.execution_engine import ExecutionEngine
from Bot.core.trade_core import TradeCore
from Bot.wrappers.strategy_wrapper import StrategyWrapper
from Bot.engine.market_engine import MarketEngine

# -------------------------
# ログ設定
# -------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

async def main():
    # -------------------------
    # 設定
    # -------------------------
    live_mode = False  # 実弾は打たない
    ws_url = "wss://stream.binance.com:9443/ws/btcusdt@kline_15m"

    # -------------------------
    # モジュール初期化
    # -------------------------
    exec_engine = ExecutionEngine(live=live_mode)
    trade_core = TradeCore(exec_engine)
    strategy_wrapper = StrategyWrapper(trade_core)
    market_engine = MarketEngine(ws_url, strategy_wrapper)

    # -------------------------
    # 無限ループで自動稼働
    # -------------------------
    while True:
        try:
            await market_engine.connect()
        except asyncio.CancelledError:
            logging.info("BOT停止: キャンセル要求")
            break
        except Exception as e:
            logging.exception(f"BOT例外発生: {e}")
            # 再接続前に少し待機
            await asyncio.sleep(5)
        finally:
            market_engine.stop()
            logging.info("MarketEngine 停止処理完了")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("BOT手動停止 (Ctrl+C)")