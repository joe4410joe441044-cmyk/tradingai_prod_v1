from fastapi import APIRouter
from backend.core.config_store import config_store

router = APIRouter()

@router.post("/config")
def update_config(cfg: dict):

    config_store.update(cfg)

    print("🔥 CONFIG UPDATED:", cfg)

    return {"status": "ok"}