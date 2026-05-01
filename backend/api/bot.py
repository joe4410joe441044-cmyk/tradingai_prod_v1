from fastapi import APIRouter
from backend.bot_manager import bot_manager

router = APIRouter()


@router.post("/start")
def start_bot(config: dict):

    # =========================
    # 🔥 受信ログ（最重要）
    # =========================
    print("🔥 START CONFIG RECEIVED:", config)

    engine = bot_manager.get_engine()

    # =========================
    # 🔥 config反映
    # =========================
    try:
        engine.set_config(config)
        print("🔥 ENGINE CONFIG APPLIED")
    except Exception as e:
        print("[CONFIG APPLY ERROR]", e)

    # =========================
    # 🔥 KillSwitchリセット
    # =========================
    try:
        if hasattr(engine, "risk"):
            if hasattr(engine.risk, "reset"):
                engine.risk.reset()
            else:
                engine.risk.kill_switch.active = False
                engine.risk.kill_switch.reason = None
                engine.risk.consecutive_losses = 0

        print("🔥 RISK RESET DONE")

    except Exception as e:
        print("[RISK RESET ERROR]", e)

    # =========================
    # 🔥 起動
    # =========================
    result = bot_manager.start()

    print("🔥 BOT START RESULT:", result)

    return result


@router.post("/stop")
def stop_bot():

    print("🛑 STOP REQUEST")

    result = bot_manager.stop()

    print("🛑 BOT STOP RESULT:", result)

    return result