from backend.ws.orderbook_ws import OrderBookWS


def on_update(bids, asks):
    print("BID:", bids[:1], "ASK:", asks[:1])


ws = OrderBookWS("btcusdt", on_update)
ws.start()

import time
while True:
    time.sleep(1)