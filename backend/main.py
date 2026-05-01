# -*- coding: utf-8 -*-

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# =========================
# FastAPI本体
# =========================
app = FastAPI()

# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# 🔥 BOT取得（シングルトン）
# =========================
from backend.bot_manager import get_bot_manager

bot = get_bot_manager()

# =========================
# APIルーター import
# =========================
from backend.api import bot_api
from backend.api import summary_api
from backend.api import risk as risk_api
from backend.api.trade_preview import router as preview_router
from backend.api import websocket as websocket_api
from backend.api import result as result_api

# 🔥 追加：symbol API
from backend.api import symbol as symbol_api

# =========================
# ROUTER登録
# =========================
app.include_router(bot_api.router, prefix="/api/bot")
app.include_router(summary_api.router, prefix="/api")

# preview（計算系）
app.include_router(preview_router, prefix="/api/trade")

# risk（任意）
try:
    app.include_router(risk_api.router, prefix="/api/risk")
except Exception:
    pass

# 🔥 result
app.include_router(result_api.router, prefix="/api")

# 🔥 symbol（Apply用）
app.include_router(symbol_api.router, prefix="/api")

# WebSocket
app.include_router(websocket_api.router)

# =========================
# root
# =========================
@app.get("/")
def root():
    return {"status": "ok"}