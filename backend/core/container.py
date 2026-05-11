# -*- coding: utf-8 -*-

import os
from dotenv import load_dotenv
from backend.bot_manager import get_bot_manager
from backend.binance_rest_client import BinanceClient

# =========================
# 🔧 .env 読み込み
# =========================
load_dotenv()

# =========================
# 🔧 Bot
# =========================
bot = get_bot_manager()

# =========================
# 🔑 APIキー取得
# =========================
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

if not api_key or not api_secret:
    raise ValueError("APIキーが未設定")

# =========================
# 🔧 Client
# =========================
client = BinanceClient(
    api_key=api_key,
    api_secret=api_secret
)