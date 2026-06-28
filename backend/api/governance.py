# backend/api/governance.py

from fastapi import APIRouter

from backend.runtime.governance_runtime import (
    governance_state,
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

    governance_state["execution_enabled"] = payload.get(
        "enabled",
        False,
    )

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

    return {
        "success": True,
        "emergency_stop": True,
    }


# ============================================================
# STATUS
# ============================================================

@router.get("/status")
async def governance_status():

    return governance_state