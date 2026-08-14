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
            and getattr(bot_manager, "loop_state", None) == "RUNNING"
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
    bot_manager = get_bot_manager()

    if governance_state.get("emergency_state") == "PROCESSING":
        result = unlock_emergency_lock()
        raise HTTPException(
            status_code=409,
            detail=result,
        )

    warnings = []
    last_result = governance_state.get("last_emergency_result")
    if isinstance(last_result, dict):
        if last_result.get("positionRemaining") is True:
            warnings.append("POSITION_REMAINING")
        if last_result.get("stateUnknown") is True:
            warnings.append("PENDING_ORDER_STATE_UNKNOWN")
        diagnostic_reason = (
            last_result.get("error_code")
            or last_result.get("errorCode")
            or last_result.get("reason")
        )
        if (
            isinstance(diagnostic_reason, str)
            and diagnostic_reason.strip()
        ):
            warnings.append(diagnostic_reason)
        diagnostic_message = last_result.get("message")
        if (
            isinstance(diagnostic_message, str)
            and ":" in diagnostic_message
        ):
            message_code = diagnostic_message.rsplit(":", 1)[-1].strip()
            if message_code and message_code.replace("_", "").isalnum():
                warnings.append(message_code)

    if getattr(bot_manager, "engine", None) is None:
        warnings.append("ENGINE_UNAVAILABLE")

    try:
        pending_state = (
            bot_manager.get_authoritative_pending_order_state()
        )
        if pending_state.get("pending_order") is True:
            warnings.append("PENDING_ORDER_REMAINING")
        elif pending_state.get("known") is not True:
            warnings.append("PENDING_ORDER_STATE_UNKNOWN")
    except Exception:
        warnings.append("PENDING_ORDER_STATE_UNKNOWN")

    try:
        bot_manager._running = False
        bot_manager._set_lifecycle_state("STOPPED")
    except Exception:
        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "unlocked": False,
                "reason": "UNLOCK_STATE_UPDATE_FAILED",
                "emergency": build_emergency_status(),
            },
        )

    result = unlock_emergency_lock(warnings=warnings)

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
