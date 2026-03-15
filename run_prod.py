import logging
from Bot.utils.logger import BotLogger
from typing import Optional

# Binance import は live=True の場合のみ
try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceOrderException
except ImportError:
    Client = None

class ExecutionEngine:
    """
    本番用 Execution Engine
    - live=True: Binance 注文を実行
    - live=False: 注文はログに記録するだけ（資金未投入用）
    """

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None,
                 logger: Optional[logging.Logger] = None, live: bool = False):
        self.live = live
        self.logger = logger or BotLogger("ExecutionEngine").get_logger()
        self.client = None

        if live:
            if Client is None:
                raise ImportError("binance package not installed")
            if not api_key or not api_secret:
                raise ValueError("API key/secret required for live mode")
            self.client = Client(api_key, api_secret)
            self.logger.info("ExecutionEngine initialized in LIVE mode")
        else:
            self.logger.info("ExecutionEngine initialized in SIMULATION mode (no real orders)")

    def place_order(self, symbol: str, side: str, order_type: str, quantity: float, price: float = None, **kwargs):
        side_upper = side.upper()
        if side_upper not in ["BUY", "SELL"]:
            self.logger.error(f"Invalid order side: {side}")
            return None

        if self.live:
            try:
                if order_type.upper() == "MARKET":
                    order = self.client.create_order(
                        symbol=symbol,
                        side=side_upper,
                        type="MARKET",
                        quantity=quantity,
                        **kwargs
                    )
                elif order_type.upper() == "LIMIT":
                    order = self.client.create_order(
                        symbol=symbol,
                        side=side_upper,
                        type="LIMIT",
                        timeInForce="GTC",
                        quantity=quantity,
                        price=str(price),
                        **kwargs
                    )
                else:
                    self.logger.error(f"Unsupported order type: {order_type}")
                    return None
                self.logger.info(f"[LIVE] Order placed: {order}")
                return order
            except BinanceAPIException as e:
                self.logger.error(f"BinanceAPIException: {e}")
            except BinanceOrderException as e:
                self.logger.error(f"BinanceOrderException: {e}")
            except Exception as e:
                self.logger.error(f"Unknown exception during order: {e}")
            return None
        else:
            self.logger.info(f"[SIMULATION] Order simulated: {side_upper} {symbol} qty={quantity} price={price} kwargs={kwargs}")
            return {"symbol": symbol, "side": side_upper, "quantity": quantity, "price": price, "simulated": True}

    def cancel_order(self, symbol: str, orderId: int):
        if self.live:
            try:
                result = self.client.cancel_order(symbol=symbol, orderId=orderId)
                self.logger.info(f"[LIVE] Order canceled: {result}")
                return result
            except Exception as e:
                self.logger.error(f"Cancel order failed: {e}")
                return None
        else:
            self.logger.info(f"[SIMULATION] Cancel order simulated: {symbol} orderId={orderId}")
            return {"symbol": symbol, "orderId": orderId, "simulated": True}