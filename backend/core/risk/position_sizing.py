# -*- coding: utf-8 -*-

import math


def calculate_qty(
    balance: float,
    risk_percent: float,
    leverage: float,
    price: float,
    min_qty: float,
    step_size: float
):
    if price <= 0 or balance <= 0:
        return {
            "valid": False,
            "reason": "invalid_input",
            "qty": 0
        }

    risk_amount = balance * (risk_percent / 100)
    position_size = risk_amount * leverage
    raw_qty = position_size / price

    qty = math.floor(raw_qty / step_size) * step_size

    if qty < min_qty:
        return {
            "valid": False,
            "reason": "qty_below_min",
            "qty": 0,
            "min_qty": min_qty,
            "raw_qty": raw_qty
        }

    qty = float(f"{qty:.8f}")

    return {
        "valid": True,
        "qty": qty,
        "risk_amount": risk_amount,
        "position_size": position_size,
        "raw_qty": raw_qty
    }