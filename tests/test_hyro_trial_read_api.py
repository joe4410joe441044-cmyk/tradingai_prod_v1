from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.hyro_trial_read import create_hyro_trial_read_router
from backend.auth.csrf import CSRF_TOKEN_COOKIE, CSRF_TOKEN_HEADER, OperatorCsrfProtection
from backend.prop_trading.hyro_trial_read_service import HyroTrialReadError


PATH = "/api/prop-accounts/hyro-trial/refresh"


class Service:
    def __init__(self, result=None, error=None):
        self.result = result or {
            "id": "hyro-issued-trial-redacted",
            "updatedAt": "2026-11-15T12:00:00Z",
            "metrics": {"currentEquity": 25000},
        }
        self.error = error
        self.calls = 0

    def refresh(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def app_for(service, *, authenticated=True, csrf=True):
    app = FastAPI()
    if authenticated:
        @app.middleware("http")
        async def inject_operator(request: Request, call_next):
            request.scope["operator_session"] = {
                "identity": "operator",
                "session_id": "fixture",
                "created_at": 1,
                "expires_at": 9999999999,
            }
            return await call_next(request)
    app.include_router(create_hyro_trial_read_router(service))
    if csrf:
        app.add_middleware(OperatorCsrfProtection, csrf_required_paths=frozenset({PATH}))
    return app


def request(client):
    client.cookies.set(CSRF_TOKEN_COOKIE, "fixture-csrf")
    return client.post(
        PATH,
        headers={
            "Origin": "http://testserver",
            CSRF_TOKEN_HEADER: "fixture-csrf",
        },
    )


def test_refresh_requires_operator_csrf_and_same_origin():
    service = Service()
    unauthenticated = TestClient(app_for(service, authenticated=False, csrf=False))
    response = unauthenticated.post(PATH, headers={"Origin": "http://testserver"})
    assert response.status_code == 401
    assert service.calls == 0

    protected = TestClient(app_for(service))
    assert protected.post(PATH, headers={"Origin": "http://testserver"}).status_code == 403
    assert service.calls == 0

    protected.cookies.set(CSRF_TOKEN_COOKIE, "fixture-csrf")
    wrong_origin = protected.post(
        PATH,
        headers={"Origin": "https://outside.invalid", CSRF_TOKEN_HEADER: "fixture-csrf"},
    )
    assert wrong_origin.status_code == 403
    assert wrong_origin.json()["error"]["code"] == "ORIGIN_REJECTED"
    assert service.calls == 0


def test_refresh_returns_only_service_projection_and_safe_error_code():
    service = Service()
    response = request(TestClient(app_for(service)))
    assert response.status_code == 200
    assert response.json() == {"ok": True, "challenge": service.result}
    assert service.calls == 1

    failed = Service(error=HyroTrialReadError("HYRO_TRIAL_REFRESH_IN_PROGRESS", 409))
    response = request(TestClient(app_for(failed)))
    assert response.status_code == 409
    assert response.json() == {
        "ok": False,
        "error": {"code": "HYRO_TRIAL_REFRESH_IN_PROGRESS"},
    }
