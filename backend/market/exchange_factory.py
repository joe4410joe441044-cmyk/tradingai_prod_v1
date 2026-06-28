from backend.market.exchanges.kucoin_market_ws import (
    OrderBookWS
)


class ExchangeFactory:

    @staticmethod
    def create_market_ws(
        exchange,
        symbol,
        on_update,
        runtime_id=None,
    ):

        exchange = exchange.lower()

        if exchange == "kucoin":

            return OrderBookWS(
                symbol=symbol,
                on_update=on_update,
                runtime_id=runtime_id,
            )

        raise ValueError(
            f"Unsupported exchange: {exchange}"
        )