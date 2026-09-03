from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from Bot.engine.execution_engine import ExecutionEngine
from backend.portfolio.portfolio_manager import PortfolioManager
from backend.routers import positions as positions_router


class PriceManager:
    def get_current_price(self):
        return 100.0


@pytest.fixture
def client():
    previous_engine = positions_router.engine
    app = FastAPI()
    app.include_router(positions_router.router, prefix="/api")
    try:
        yield TestClient(app)
    finally:
        positions_router.set_engine(previous_engine)


def paper_engine():
    engine = ExecutionEngine(
        portfolio=PortfolioManager(1000.0), price_manager=PriceManager()
    )
    engine.symbol = "BTCUSDT"
    return engine


def error_execution(response):
    assert response.status_code == 200
    payload = response.json()
    assert payload["positions"] == []
    assert payload["execution"]["status"] == "ERROR"
    assert payload["execution"]["authoritativeRuntimeState"] == "ERROR"
    assert payload["execution"]["runtimeSynchronizationState"] == "OFFLINE"
    return payload["execution"]


def test_positions_without_attached_engine_preserves_stopped_contract(client):
    positions_router.set_engine(None)
    response = client.get("/api/positions")
    assert response.status_code == 200
    assert response.json() == {
        "positions": [],
        "execution": {
            "status": "STOPPED",
            "execution_mode": "SIMULATION",
            "real_order_allowed": False,
            "ws_connected": False,
            "position_active": False,
            "executionAuthorityScore": 0,
            "authoritativeRuntimeState": "STOPPED",
            "runtimeSynchronizationState": "OFFLINE",
        },
    }


def test_positions_accepts_actual_execution_engine_interface(client):
    engine = paper_engine()
    positions_router.set_engine(engine)
    response = client.get("/api/positions")
    assert not hasattr(engine, "get_status")
    assert response.status_code == 200
    assert response.json()["execution"]["status"] == "STOPPED"
    assert "get_status" not in str(response.json())


def test_positions_attached_engine_flat_is_empty(client):
    engine = paper_engine()
    engine.actual_position = None
    positions_router.set_engine(engine)
    payload = client.get("/api/positions").json()
    assert payload["positions"] == []
    assert payload["execution"]["actual_position"] is None


def test_positions_normalizes_authoritative_engine_position(client):
    engine = paper_engine()
    engine.actual_position = {
        "symbol": "ETHUSDT", "side": "BUY", "entry_price": 2500.0,
        "pnl": 12.5, "qty": 0.4,
    }
    positions_router.set_engine(engine)
    payload = client.get("/api/positions").json()
    assert payload["positions"] == [{
        "symbol": "ETHUSDT", "side": "BUY", "entry": 2500.0,
        "pnl": 12.5, "size": 0.4,
    }]
    assert payload["execution"]["actual_position"] == engine.actual_position


@pytest.mark.parametrize("result", [None, [], "unavailable", {}])
def test_positions_malformed_engine_result_fails_closed(client, result):
    class MalformedEngine:
        actual_position = {
            "symbol": "FAKEUSDT", "side": "BUY", "entry_price": 1.0,
            "pnl": 99.0, "qty": 1.0,
        }

        def get_result(self):
            return result

    positions_router.set_engine(MalformedEngine())
    execution = error_execution(client.get("/api/positions"))
    assert "invalid data" in execution["error"]


def test_positions_unavailable_engine_result_fails_closed(client):
    class UnavailableEngine:
        def get_result(self):
            raise RuntimeError("runtime unavailable")

    positions_router.set_engine(UnavailableEngine())
    execution = error_execution(client.get("/api/positions"))
    assert execution["error"] == "runtime unavailable"


def test_positions_malformed_authoritative_position_fails_closed(client):
    engine = paper_engine()
    engine.actual_position = {}
    positions_router.set_engine(engine)
    execution = error_execution(client.get("/api/positions"))
    assert "position result is invalid" in execution["error"]
