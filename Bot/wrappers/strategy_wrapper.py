from typing import List
import logging
from Bot.core.trade_core import StrategyContext, TradeCore


class StrategyWrapper:
    """複数戦略を統括し、TradeCoreに委譲する"""

    def __init__(self, core: TradeCore):
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
        """
        market_data: pandas.Series (open, high, low, close)
        """

        for strat in self.strategies:

            # 任意：FVGなどの内部更新
            if hasattr(strat, "detect_fvg"):
                try:
                    strat.detect_fvg()
                except Exception as e:
                    logging.error(f"detect_fvg error: {e}")

            # シグナル生成
            if not hasattr(strat, "generate_signals"):
                continue

            try:
                signals = strat.generate_signals(market_data)
            except Exception as e:
                logging.error(f"generate_signals error: {e}")
                continue

            if not signals:
                continue

            for s in signals:
                try:
                    ctx = StrategyContext(
                        strategy_name=s.get("strategy_name", "UNKNOWN"),
                        trade_type=s["trade_type"],
                        entry_price=s["entry_price"],
                        stop_loss_price=s["stop_loss_price"],
                        take_profit_price=s["take_profit_price"],
                        partial_close_percent=s.get("partial_close_percent", 0),
                        reason=s.get("reason", "")
                    )

                    # 🔥 ここが重要：TradeCoreへ直接渡す
                    self.core.try_enter(ctx)

                except Exception as e:
                    logging.error(f"signal processing error: {e}")

        # 🔥 価格更新（SL/TP判定）
        try:
            price_dict = {
                "BTCUSDT": float(market_data["close"])
            }
            self.core.update_positions(price_dict)
        except Exception as e:
            logging.error(f"update_positions error: {e}")

    # ---------------------------------
    # TestSignalGenerator 用
    # ---------------------------------
    def on_test_signal(self, trade_type, entry_price, stop_loss_price, take_profit_price, volume):
        if not self.core.can_trade():
            logging.info("[TradeCore] cannot trade, skipping")
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