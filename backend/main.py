# -*- coding: utf-8 -*-

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# =========================
# ログ（最重要）
# =========================
from backend.log_store import add_log

# =========================
# FastAPI本体
# =========================
app = FastAPI()

# =========================
# 起動ログ（STEP1突破用）
# =========================
@app.on_event("startup")
async def startup_event():
    add_log("🔥 API STARTED")

# =========================
# CORS
# =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# APIルーター import
# =========================
from backend.api import bot_api
from backend.api import summary_api
from backend.api import risk as risk_api
from backend.api.trade_preview import router as preview_router
from backend.api import websocket as websocket_api
from backend.api import result as result_api
from backend.api import symbol as symbol_api

# logs router
from backend.api.logs import router as logs_router

# =========================
# MODE / PORTFOLIO
# =========================
from backend.routers.mode import router as mode_router
from backend.routers.portfolio import router as portfolio_router

# =========================
# ROUTER登録
# =========================

# BOT系
app.include_router(bot_api.router, prefix="/api/bot")
app.include_router(summary_api.router, prefix="/api/bot")
app.include_router(result_api.router, prefix="/api/bot")
app.include_router(symbol_api.router, prefix="/api/bot")
app.include_router(mode_router, prefix="/api/bot")
app.include_router(portfolio_router, prefix="/api/bot")

# trade preview
app.include_router(preview_router, prefix="/api/bot")

# risk
try:
    app.include_router(risk_api.router, prefix="/api/bot")
except Exception:
    pass

# WebSocket
app.include_router(websocket_api.router)

# Logs
app.include_router(logs_router)

# =========================
# root
# =========================
@app.get("/")
def root():
    return {"status": "ok"}