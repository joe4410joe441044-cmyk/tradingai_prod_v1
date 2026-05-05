# -*- coding: utf-8 -*-

from fastapi import APIRouter
from backend.log_store import get_logs  # ← ここを統一

router = APIRouter()

@router.get("/logs")
def read_logs():
    return get_logs()