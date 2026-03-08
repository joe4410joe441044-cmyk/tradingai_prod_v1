import os

class BybitConfig:
    API_KEY = os.getenv("BYBIT_API_KEY")
    API_SECRET = os.getenv("BYBIT_API_SECRET")

    BASE_URL = "https://api.bybit.com"

    # linear / spot
    MARKET_TYPE = "linear"

    # リスク制御
    MAX_DD_PERCENT = 10
    SAFE_MODE = True
