from fastapi import APIRouter, Depends

from backend.bot_manager.bot_manager import get_bot_manager
from backend.auth.dependencies import require_operator_session


router = APIRouter(prefix="/api/runtime")


@router.get("/stopped-paper-snapshot-status")
def stopped_paper_snapshot_status():
    """Return validation metadata without rebinding or exposing evidence."""

    return get_bot_manager().get_stopped_paper_snapshot_status()


@router.post("/stopped-paper-safety/refresh")
def refresh_stopped_paper_safety_authority(
    _operator: str = Depends(require_operator_session),
):
    """Explicitly revalidate stopped-PAPER safety without starting trading."""

    return get_bot_manager().refresh_stopped_paper_safety_authority()


@router.post("/paper-auto/start")
def start_paper_auto_selection(
    _operator: str = Depends(require_operator_session),
):
    """Enable the attached PAPER AUTO lifecycle; no cycle runs implicitly."""

    return get_bot_manager().start_auto_market_selection_runtime()


@router.get("/paper-auto/status")
def paper_auto_selection_status():
    """Project the attached singleton lifecycle control status."""

    return get_bot_manager().get_auto_market_selection_runtime_status()


@router.post("/paper-auto/cycle")
def run_paper_auto_selection_cycle(
    _operator: str = Depends(require_operator_session),
):
    """Run one selection cycle through the attached singleton lifecycle."""

    return get_bot_manager().run_auto_market_selection_cycle()


@router.post("/paper-auto/stop")
def stop_paper_auto_selection(
    _operator: str = Depends(require_operator_session),
):
    """Disable PAPER AUTO without interrupting an in-flight safe transaction."""

    return get_bot_manager().stop_auto_market_selection_runtime()
