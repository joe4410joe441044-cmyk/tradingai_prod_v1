# -*- coding: utf-8 -*-
import asyncio
import functools
import traceback


# =========================
# ① safe_run（落ちない）
# =========================
def safe_run(func):
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                print(f"[ERROR] {func.__name__}: {e}")
                traceback.print_exc()
        return wrapper
    else:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                print(f"[ERROR] {func.__name__}: {e}")
                traceback.print_exc()
        return wrapper


# =========================
# ② check_connections（検知）
# =========================
def check_connections(trade_core):
    errors = []

    if trade_core is None:
        errors.append("TradeCore is None")

    elif trade_core.execution_engine is None:
        errors.append("ExecutionEngine is None")

    return errors


# =========================
# ③ ensure_connections（復旧）
# =========================
def ensure_connections(trade_core, execution_engine):
    if trade_core is None:
        return

    if trade_core.execution_engine is None:
        print("[FIX] Reconnecting ExecutionEngine")
        trade_core.execution_engine = execution_engine


# =========================
# ④ safe_task（async保護）
# =========================
def safe_task(coro):
    async def runner():
        try:
            await coro
        except Exception as e:
            print(f"[TASK ERROR] {e}")
            traceback.print_exc()
    return asyncio.create_task(runner())