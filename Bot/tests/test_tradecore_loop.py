# -*- coding: utf-8 -*-
import asyncio
import random
from Bot.core.trade_core import TradeCore, StrategyContext
from Bot.engine.execution_engine import ExecutionEngine

# 簡易テスト用 Signal generator（本番は MarketEngine から）
def generate_signal():
    side = random.choice(["BUY", "SELL"])
    price = random.uniform(25000, 30000)
    sl = price - 100 if side=="BUY" else price + 100
    tp = price + 100 if side=="BUY" else price - 100
    return StrategyContext(
        strategy_name="FVGStrategy",
        trade_type=side,
        entry_price=price,
        stop_loss_price=sl,
        take_profit_price=tp
    )

async def test_loop():
    execution_engine = ExecutionEngine(live=False)
    trade_core = TradeCore(execution_engine=execution_engine)

    while True:
        # ① Signal生成
        ctx = generate_signal()

        # ② TradeCoreで建玉作成
        trade_core.try_enter(ctx)

        # ③ 仮価格で決済判定
        price_dict = {"BTCUSDT": random.uniform(25000, 30000)}
        trade_core.check_orders(price_dict)

        # ④ ループ待機
        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(test_loop())