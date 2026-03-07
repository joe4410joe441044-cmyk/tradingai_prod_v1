from typing import List


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
    # BOTループから呼ばれる
    # ---------------------------------
    def on_bar(self, market_data):

        for strat in self.strategies:

            # FVG検出などの前処理
            if hasattr(strat, "detect_fvg"):
                strat.detect_fvg()

            # シグナル取得
            if hasattr(strat, "generate_signals"):
                signals = strat.generate_signals(market_data)
            else:
                continue

            # Coreへ委譲
            for s in signals:

                from Bot.core.trade_core import StrategyContext

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

        # ポジション更新
        self.core.update_positions()