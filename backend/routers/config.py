from fastapi import APIRouter
from backend.core.config_store import config_store
from backend.utils.log_buffer import logger

router = APIRouter()

@router.post("/config")
def update_config(cfg: dict):

    config_store.update(cfg)

    logger.info("Trading config updated")

    return {"status": "ok"}
