from fastapi import APIRouter

router = APIRouter()

engine = None  # 起動時に注入する


def set_engine(e):
    global engine
    engine = e


# =========================
# 更新（設定変更）
# =========================
@router.post("/update")
def update_risk(config: dict):
    if not engine:
        return {"error": "engine not set"}

    r = engine.risk

    try:
        if "max_drawdown_pct" in config:
            r.max_drawdown_pct = float(config["max_drawdown_pct"])

        if "max_loss_streak" in config:
            r.max_consecutive_losses = int(config["max_loss_streak"])

    except Exception as e:
        return {"error": str(e)}

    return {"status": "updated"}


# =========================
# リセット
# =========================
@router.post("/reset")
def reset_risk():
    if not engine:
        return {"error": "engine not set"}

    try:
        engine.risk.reset()
    except Exception as e:
        return {"error": str(e)}

    return {
        "status": "reset",
        "kill_switch": False
    }


# =========================
# 状態取得
# =========================
@router.get("/status")
def get_risk_status():
    if not engine:
        return {"error": "engine not set"}

    r = engine.risk

    return {
        "kill_switch": r.trading_disabled,
        "reason": r.kill_reason,
        "max_drawdown_pct": r.max_drawdown_pct,
        "max_loss_streak": r.max_consecutive_losses,
        "consecutive_losses": r.consecutive_losses,
        "peak_equity": r.peak_equity
    }


# =========================
# 🔥 DD強制テスト（今回の核心）
# =========================
@router.post("/force_dd")
def force_dd(data: dict):
    if not engine:
        return {"error": "engine not set"}

    r = engine.risk

    try:
        initial = float(data.get("initial", 1000))
        current = float(data.get("current", 800))

        # 初期化
        r.initial_equity = initial
        r.peak_equity = initial

        # DD発生
        r.update_equity(current)

    except Exception as e:
        return {"error": str(e)}

    return {
        "status": "ok",
        "kill_switch": r.trading_disabled,
        "reason": r.kill_reason
    }