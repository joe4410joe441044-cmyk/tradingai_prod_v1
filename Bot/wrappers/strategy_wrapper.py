from typing import List
import logging
from Bot.core.trade_core import StrategyContext

class StrategyWrapper:
    """複数戦略を統括し、Coreに委譲する汎用ラッパー"""

    def __init__(self, core):
        self.core = core
        self.strategies: List = []

    # ---------------------------------
    # 戦略登録
    # ---------------------------------
    def register_strategy(self, strategy):
        self.strategies.append(strategy)

    # ---------------------------------
    # ローソク足確定時に呼ばれる
    # ---------------------------------
    def on_bar(self, market_data):
        for strat in self.strategies:
            if hasattr(strat, "detect_fvg"):
                strat.detect_fvg()
            if hasattr(strat, "generate_signals"):
                signals = strat.generate_signals(market_data)
            else:
                continue

            for s in signals:
                ctx = StrategyContext(
                    strategy_name=s["strategy_name"],
                    trade_type=s["trade_type"],
                    entry_price=s["entry_price"],
                    stop_loss_price=s["stop_loss_price"],
                    take_profit_price=s["take_profit_price"],
                    partial_close_percent=s.get("partial_close_percent", 0),
                    reason=s.get("reason", "")
                )
                self.core.try_enter(ctx)

        self.core.update_positions()

    # ---------------------------------
    # TestSignalGenerator 用
    # ---------------------------------
    def on_test_signal(self, trade_type, entry_price, stop_loss_price, take_profit_price, volume):
        if not self.core.can_open_new_position():
            logging.info("[TradeCore] max_concurrent_positions reached, skipping")
            return

        ctx = StrategyContext(
            strategy_name="TEST",
            trade_type=trade_type,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price,
            partial_close_percent=0,
            reason="TestSignal"
        )
        self.core.try_enter(ctx)