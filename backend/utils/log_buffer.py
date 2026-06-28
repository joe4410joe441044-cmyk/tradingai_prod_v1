# =========================================
# backend/utils/log_buffer.py
# =========================================

import logging
import os

from collections import deque
from logging.handlers import RotatingFileHandler

# =========================================
# UI LOG BUFFER
# =========================================

# React/UIへ返す用
# 最大200件のみ保持

log_buffer = deque(maxlen=200)

# =========================================
# LOG DIRECTORY
# =========================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(__file__)
    )
)

LOG_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(
    LOG_DIR,
    "tradingai.log"
)

# =========================================
# LOGGER
# =========================================

logger = logging.getLogger("TradingAI")

# handler重複防止
if logger.handlers:
    logger.handlers.clear()

# 本番推奨
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s"
)

# =========================================
# FILE LOGGER
# =========================================

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,   # 10MB
    backupCount=3,
    encoding="utf-8"
)

file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)

# =========================================
# CONSOLE LOGGER
# =========================================

console_handler = logging.StreamHandler()

# VPS本番はWARNING推奨
console_handler.setLevel(logging.WARNING)
console_handler.setFormatter(formatter)

# =========================================
# ADD HANDLERS
# =========================================

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# =========================================
# SYSTEMD SPAM PREVENTION
# =========================================

# root loggerへの伝播停止
# journalctl肥大化抑制

logger.propagate = False

# =========================================
# UI LOG FUNCTION
# =========================================

def add_log(message, level="info"):

    print(
        f"ADD_LOG_CALLED: [{level.upper()}] {message}",
        flush=True
    )

    logger = logging.getLogger("TradingAI")

    if level.lower() == "info":
        logger.info(message)
        
    """
    UI + file logging
    """

    # =====================================
    # AUDIT TRACE (一時追加)
    # =====================================

    print(
        f"ADD_LOG_CALLED: [{level.upper()}] {message}",
        flush=True
    )

    # -------------------------
    # UI BUFFER
    # -------------------------

    log_buffer.append(message)

    # -------------------------
    # LOGGER
    # -------------------------

    level = level.lower()

    if level == "debug":
        logger.debug(message)

    elif level == "warning":
        logger.warning(message)

    elif level == "error":
        logger.error(message)

    else:
        logger.info(message)

# =========================================
# GET LOGS
# =========================================

def get_logs():
    return list(log_buffer)