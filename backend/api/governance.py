# backend/api/governance.py

from fastapi import APIRouter, HTTPException

from backend.bot_manager import (
    get_bot_manager,
)

from backend.runtime.governance_runtime import (
    EMERGENCY_ACTION_REQUIRED,
    governance_state,
    unlock_emergency_lock,
)

router = APIRouter(
    prefix="/api/governance",
    tags=["governance"],
)


# ============================================================
# MODE
# ============================================================

@router.post("/mode")
async def set_mode(payload: dict):

    governance_state["mode"] = payload.get(
        "mode",
        "SAFE",
    )

    return {
        "success": True,
        "mode": governance_state["mode"],
    }


# ============================================================
# EXECUTION ENABLE
# ============================================================

@router.post("/execution")
async def set_execution(payload: dict):

    enabled = bool(payload.get(
        "enabled",
        False,
    ))

    if enabled:
        if governance_state.get("emergency_stop", False):
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "AUTO_TRADE_BLOCKED_BY_EMERGENCY_LOCK",
                    "execution_enabled": (
                        governance_state["execution_enabled"]
                    ),
                    "emergency_stop": (
                        governance_state["emergency_stop"]
                    ),
                },
            )

        bot_manager = get_bot_manager()
        loop_running = (
            bool(getattr(bot_manager, "_running", False))
            and getattr(bot_manager, "lifecycle_state", None) == "RUNNING"
        )

        if not loop_running:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "AUTO_TRADE_REQUIRES_LOOP_ON",
                    "execution_enabled": (
                        governance_state["execution_enabled"]
                    ),
                },
            )

    governance_state["execution_enabled"] = enabled

    return {
        "success": True,
        "execution_enabled":
            governance_state["execution_enabled"],
    }


# ============================================================
# RISK PROFILE
# ============================================================

@router.post("/risk-profile")
async def set_risk_profile(payload: dict):

    governance_state["risk_profile"] = payload.get(
        "risk_profile",
        "SAFE",
    )

    return {
        "success": True,
        "risk_profile":
            governance_state["risk_profile"],
    }


# ============================================================
# EMERGENCY STOP
# ============================================================

@router.post("/emergency-stop")
async def emergency_stop():

    governance_state["emergency_stop"] = True

    governance_state["execution_enabled"] = False

    governance_state["emergency_state"] = EMERGENCY_ACTION_REQUIRED

    return {
        "success": True,
        "emergency_stop": True,
    }


@router.post("/emergency-orchestrate")
async def emergency_orchestrate():

    bot_manager = get_bot_manager()

    return bot_manager.run_emergency_orchestrator()


@router.post("/emergency/unlock")
async def emergency_unlock():

    result = unlock_emergency_lock()

    if not result.get("success", False):
        raise HTTPException(
            status_code=409,
            detail=result,
        )

    return result


# ============================================================
# STATUS
# ============================================================

@router.get("/status")
async def governance_status():

    return governance_state
