import pandas as pd
import random
from strategies.base_strategy import BaseStrategy
from core.trade_core import StrategyContext

class RSIStrategy(BaseStrategy):

    def __init__(self, trade_core, logger=None):
        super().__init__(trade_core, logger)
        self.df_h1 = pd.DataFrame()

    def on_bar(self, market_data):

        if "H1" in market_data and not market_data["H1"].empty:
            df = market_data["H1"].copy()
            df.columns = [c.lower() for c in df.columns]  # ↁE重要E
            self.df_h1 = df

        if self.df_h1.empty:
            return

        action = random.choice(["BUY", "SELL", None])
        if action is None:
            return

        price = self.df_h1['close'].iloc[-1]

        ctx = StrategyContext(
            strategy_name="RSI",
            trade_type=action,
            entry_price=price,
            stop_loss_price=price - 10 if action == "BUY" else price + 10,
            take_profit_price=price + 20 if action == "BUY" else price - 20
        )

        self.trade_core.try_enter(ctx)
