# backend/api/governance.py

from fastapi import APIRouter, HTTPException

from backend.bot_manager import (
    get_bot_manager,
)

from backend.runtime.governance_runtime import (
    EMERGENCY_ACTION_REQUIRED,
    build_emergency_status,
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

    result = bot_manager.run_emergency_orchestrator()

    if result.get("error_code") == "EMERGENCY_ALREADY_RUNNING":
        raise HTTPException(
            status_code=409,
            detail={
                "success": False,
                "reason": "PROCESSING",
                "emergency": build_emergency_status(),
            },
        )

    return result


@router.post("/emergency/unlock")
async def emergency_unlock():

    try:
        bot_manager = get_bot_manager()
        pending_order = (
            bot_manager.get_authoritative_pending_order_state()
        )
    except Exception:
        pending_order = {
            "pending_order": True,
            "safe": False,
            "reason": "PENDING_ORDER_READ_FAILED",
        }

    result = unlock_emergency_lock(
        pending_order=pending_order,
    )

    if not result.get("success", False):
        raise HTTPException(
            status_code=409,
            detail=result,
        )

    return result


@router.post("/emergency/retry")
async def emergency_retry():

    bot_manager = get_bot_manager()
    result = bot_manager.retry_emergency_orchestrator()

    if result.get("retry_rejected") is True:
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
