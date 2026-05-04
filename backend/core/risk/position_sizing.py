# -*- coding: utf-8 -*-

import math


def _get_precision(step_size: float) -> int:
    """
    step_size から小数点精度を取得
    例:
    0.001 → 3
    0.01  → 2
    1     → 0
    """
    step_str = f"{step_size:.10f}".rstrip("0")
    if "." in step_str:
        return len(step_str.split(".")[1])
    return 0


def calculate_qty(
    balance: float,
    risk_percent: float,
    leverage: float,
    price: float,
    min_qty: float,
    step_size: float
):
    # =========================
    # ❗ 入力チェック
    # =========================
    if price <= 0 or balance <= 0:
        return {
            "valid": False,
            "reason": "invalid_input",
            "qty": 0
        }

    # =========================
    # 🎯 基本計算
    # =========================
    risk_amount = balance * (risk_percent / 100)
    position_size = risk_amount * leverage
    raw_qty = position_size / price

    # =========================
    # ❗ 最小数量チェック（先にやる）
    # =========================
    if raw_qty < min_qty:
        return {
            "valid": False,
            "reason": "below_min_qty",
            "qty": 0,
            "min_qty": min_qty,
            "raw_qty": raw_qty
        }

    # =========================
    # 🔧 step_size に合わせて切り捨て
    # =========================
    factor = 1 / step_size
    qty = math.floor(raw_qty * factor) / factor

    # =========================
    # 🔧 精度調整（step_size基準）
    # =========================
    precision = _get_precision(step_size)
    qty = round(qty, precision)

    # =========================
    # ❗ 最低注文金額（軽チェック）
    # =========================
    notional = qty * price

    if notional < 5:
        return {
            "valid": False,
            "reason": "too_small_position",
            "qty": qty,
            "notional": notional
        }

    # =========================
    # ❗ 最終チェック
    # =========================
    if qty <= 0:
        return {
            "valid": False,
            "reason": "qty_zero",
            "qty": 0
        }

    return {
        "valid": True,
        "qty": float(qty),
        "risk_amount": risk_amount,
        "position_size": position_size,
        "notional": notional,
        "raw_qty": raw_qty
    }