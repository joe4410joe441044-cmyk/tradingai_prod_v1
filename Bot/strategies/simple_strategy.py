from DryRun.Bot.core.trade_core import StrategyContext

class SimpleStrategy:

    def __init__(self):
        self.name = "SIMPLE"

    def evaluate(self, price: float):

        if price <= 100:
            return StrategyContext(
                strategy_name=self.name,
                trade_type="LONG",
                entry_price=price,
                stop_loss_price=price - 10,
                take_profit_price=price + 20,
                reason="Price <= 100"
            )

        return None
