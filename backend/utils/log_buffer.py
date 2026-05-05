# backend/utils/log_buffer.py

from collections import deque

# 最大200件保持
log_buffer = deque(maxlen=200)

def add_log(message: str):
    log_buffer.append(message)

def get_logs():
    return list(log_buffer)