from pybit.unified_trading import HTTP


class BybitClient:

    def __init__(self, api_key, api_secret, testnet=False):
        self.session = HTTP(
            testnet=testnet,
            api_key=api_key,
            api_secret=api_secret
        )

    # -------------------------
    # 残高取得
    # -------------------------
    def get_balance(self):
        res = self.session.get_wallet_balance(accountType="UNIFIED")
        balance = float(res["result"]["list"][0]["totalEquity"])
        return balance

    # -------------------------
    # 全ポジション取得
    # -------------------------
    def get_all_positions(self):
        res = self.session.get_positions(category="linear")
        return res["result"]["list"]

    # -------------------------
    # 🔥 全ポジションクローズ
    # -------------------------
    def close_all_positions(self):
        positions = self.get_all_positions()

        for pos in positions:
            size = float(pos["size"])
            if size == 0:
                continue

            symbol = pos["symbol"]
            side = pos["side"]

            close_side = "Sell" if side == "Buy" else "Buy"

            print(f"Force closing {symbol} {size}")

            self.session.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=size,
                reduceOnly=True
            )
