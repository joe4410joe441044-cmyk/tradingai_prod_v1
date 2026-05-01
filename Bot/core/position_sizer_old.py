# -*- coding: utf-8 -*-

def normalize_qty(symbol: str, qty: float) -> float:
    """
    🔥 取引所仕様に合わせた数量丸め（計算段階）
    """
    if symbol == "XRPUSDT":
        return float(int(qty))
    elif symbol in ["BTCUSDT", "ETHUSDT"]:
        return round(qty, 3)
    elif symbol in ["SOLUSDT", "BNBUSDT"]:
        return round(qty, 2)
    return qty


def calc_position_size(
    balance: float,
    risk_percent: float,
    entry_price: float,
    stop_loss_price: float,
    leverage: float,
    symbol: str,  # 🔥 追加
    min_size: float = 0.0001,
    max_size: float = 1.0,
):
    """
    本番用ロット計算（SLベース）
    """

    if balance <= 0 or entry_price <= 0 or stop_loss_price <= 0:
        return 0.0

    # 許容損失額
    risk_amount = balance * (risk_percent / 100)

    # SL距離
    sl_distance = abs(entry_price - stop_loss_price)

    if sl_distance == 0:
        return 0.0

    # ロット計算
    size = (risk_amount / sl_distance) * leverage

    # 制限
    if size < min_size:
        return 0.0

    if size > max_size:
        size = max_size

    # =========================
    # 🔥 ここが最重要（丸め統一）
    # =========================
    size = normalize_qty(symbol, size)

    return size