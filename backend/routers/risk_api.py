# -*- coding: utf-8 -*-
from fastapi import APIRouter

router = APIRouter()


def register_risk_routes(app, execution_engine):

    @router.get("/risk/status")
    def risk_status():
        return execution_engine.risk.status()

    @router.post("/risk/kill")
    def kill_risk():
        execution_engine.risk.kill_switch("manual_api")
        return {"status": "killed"}

    @router.post("/risk/enable")
    def enable_risk():
        execution_engine.risk.enable()
        return {"status": "enabled"}

    app.include_router(router, prefix="/api")