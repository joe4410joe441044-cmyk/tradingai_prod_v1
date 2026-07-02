from backend.market.exchanges.binance_market_ws import (
    OrderBookWS as BinanceOrderBookWS,
)
from backend.market.exchanges.kucoin_market_ws import (
    OrderBookWS as KuCoinFuturesOrderBookWS,
    normalize_futures_symbol,
)


class ExchangeFactory:

    ORDERBOOK_SOURCES = {
        "binance": "binance",
        "kucoin": "kucoin_futures",
    }

    @classmethod
    def normalize_exchange(cls, exchange):

        normalized = str(exchange or "kucoin").strip().lower()

        if normalized not in cls.ORDERBOOK_SOURCES:
            raise ValueError(
                f"Unsupported exchange: {normalized}"
            )

        return normalized

    @classmethod
    def describe_orderbook(cls, exchange, symbol):

        exchange = cls.normalize_exchange(exchange)
        display_symbol = str(symbol).strip().upper()

        if exchange == "kucoin":
            orderbook_symbol = normalize_futures_symbol(
                display_symbol
            )
        else:
            orderbook_symbol = display_symbol.lower()

        return {
            "exchange": exchange,
            "orderbookSource": cls.ORDERBOOK_SOURCES[exchange],
            "orderbookSymbol": orderbook_symbol,
        }

    @staticmethod
    def create_market_ws(
        exchange,
        symbol,
        on_update,
        runtime_id=None,
    ):

        exchange = ExchangeFactory.normalize_exchange(exchange)

        if exchange == "kucoin":

            return KuCoinFuturesOrderBookWS(
                symbol=symbol,
                on_update=on_update,
                runtime_id=runtime_id,
            )

        if exchange == "binance":

            return BinanceOrderBookWS(
                symbol=symbol,
                on_update=on_update,
                runtime_id=runtime_id,
            )
