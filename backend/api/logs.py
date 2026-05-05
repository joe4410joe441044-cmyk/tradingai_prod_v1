# -*- coding: utf-8 -*-

from fastapi import APIRouter
from backend.utils.log_buffer import get_logs

router = APIRouter()

@router.get("/logs")
def read_logs():
    return get_logs()