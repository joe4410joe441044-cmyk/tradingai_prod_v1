from fastapi import APIRouter

from backend.bot_manager.bot_manager import get_bot_manager


router = APIRouter(prefix="/api/runtime")


@router.get("/stopped-paper-snapshot-status")
def stopped_paper_snapshot_status():
    """Return validation metadata without rebinding or exposing evidence."""

    return get_bot_manager().get_stopped_paper_snapshot_status()


@router.post("/stopped-paper-safety/refresh")
def refresh_stopped_paper_safety_authority():
    """Explicitly revalidate stopped-PAPER safety without starting trading."""

    return get_bot_manager().refresh_stopped_paper_safety_authority()
