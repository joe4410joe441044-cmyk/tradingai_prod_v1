import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.ai_advisor.api_models import AdvisorAPIConfig
from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.api_security import InjectedBearerAuthenticator
from backend.ai_advisor.models import AdvisorRuntimeResponse, Freshness
from backend.ai_advisor.runtime_reader import (
    RuntimeScalarSnapshot,
    read_runtime_scalars,
)
from backend.ai_advisor.service import build_runtime_response
from backend.api.ai_advisor import (
    AdvisorAPIComposition,
    UnavailableAdvisorService,
    advisor_runtime,
    create_runtime_router,
)

NOW = 1_700_000_000.0
TOKEN = "runtime-test-token"


def runtime_client(*, enabled=True, allowed=True):
    config = AdvisorAPIConfig(enabled=enabled)
    composition = AdvisorAPIComposition(
        config=config,
        authenticator=InjectedBearerAuthenticator(
            principalId="runtime-operator",
            advisorAccessAllowed=allowed,
            _token=TOKEN,
        ),
        service=UnavailableAdvisorService(),
        rateLimiter=AdvisorRateLimiter(
            limit=config.rateLimitRequests,
            window_seconds=config.rateLimitWindowSeconds,
            clock=lambda: NOW,
        ),
        concurrencyLimiter=AdvisorConcurrencyLimiter(
            limit=config.concurrencyLimit,
            acquire_timeout_seconds=config.concurrencyAcquireTimeoutSeconds,
        ),
    )
    app = FastAPI()
    app.include_router(
        create_runtime_router(composition),
        prefix="/api/ai-advisor",
    )
    return TestClient(app)


def scalar_snapshot(**overrides):
    values = {
        "state": "RUNNING",
        "mode": "PAPER",
        "exchange": "kucoin",
        "symbol": "BTCUSDT",
        "loop_enabled": True,
        "loop_state": "RUNNING",
        "auto_trade_enabled": False,
        "emergency_locked": False,
        "emergency_state": "READY",
        "dry_run": True,
        "real_order_allowed": False,
        "source_updated_at": NOW - 5,
        "warnings": (),
    }
    values.update(overrides)
    return RuntimeScalarSnapshot(**values)


class AdvisorRuntimeReaderTest(unittest.TestCase):
    @patch(
        "backend.ai_advisor.runtime_reader.get_existing_bot_manager",
        return_value=None,
    )
    def test_manager_absent_returns_partial_without_creation(self, existing):
        snapshot = read_runtime_scalars()

        existing.assert_called_once_with()
        self.assertEqual(snapshot.state, "NOT_CONNECTED")
        self.assertEqual(snapshot.loop_state, "NOT_CONNECTED")
        self.assertIn("MANAGER_NOT_CONNECTED", snapshot.warnings)

    @patch(
        "backend.ai_advisor.runtime_reader.governance_state",
        {
            "execution_enabled": "true",
            "emergency_stop": 1,
            "emergency_state": "READY",
        },
    )
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_strict_bool_rejects_truthy_non_booleans(self, existing):
        manager = SimpleNamespace(
            _running="true",
            lifecycle_state="RUNNING",
            config={"mode": "live", "dry_run": "false"},
            exchange_name="kucoin",
            symbol="BTCUSDT",
            exchange_client_ready=True,
            exchange_auth_ready=True,
            balance_check_ok=True,
            position_check_ok=True,
            state=SimpleNamespace(runtime_metrics={"last_bot_update": NOW}),
        )
        existing.return_value = manager

        snapshot = read_runtime_scalars()

        self.assertFalse(snapshot.loop_enabled)
        self.assertEqual(snapshot.state, "UNKNOWN")
        self.assertFalse(snapshot.auto_trade_enabled)
        self.assertFalse(snapshot.emergency_locked)
        self.assertFalse(snapshot.dry_run)
        self.assertFalse(snapshot.real_order_allowed)
        self.assertIn("DRY_RUN_INVALID", snapshot.warnings)

    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_unknown_enums_fail_closed(self, existing):
        existing.return_value = SimpleNamespace(
            _running=False,
            lifecycle_state="BROKEN",
            config={"mode": "unexpected", "dry_run": True},
            exchange_name="kucoin",
            symbol="BTCUSDT",
            state=SimpleNamespace(runtime_metrics={"last_bot_update": NOW}),
        )

        snapshot = read_runtime_scalars()

        self.assertEqual(snapshot.loop_state, "UNKNOWN")
        self.assertIsNone(snapshot.mode)
        self.assertIn("LOOP_STATE_UNKNOWN", snapshot.warnings)
        self.assertIn("MODE_UNKNOWN", snapshot.warnings)

    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_partial_data_is_null_or_warned_without_refresh(self, existing):
        manager = SimpleNamespace(
            _running=False,
            lifecycle_state=None,
            config=None,
            exchange_name=None,
            symbol=None,
            state=None,
        )
        existing.return_value = manager

        snapshot = read_runtime_scalars()

        self.assertIsNone(snapshot.mode)
        self.assertIsNone(snapshot.exchange)
        self.assertIsNone(snapshot.symbol)
        self.assertIn("CONFIG_UNAVAILABLE", snapshot.warnings)
        self.assertIn("SOURCE_TIMESTAMP_MISSING", snapshot.warnings)

    @patch("requests.sessions.Session.request")
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_reader_does_not_call_runtime_network_or_refresh_methods(
        self,
        existing,
        network_request,
    ):
        manager = SimpleNamespace(
            _running=True,
            lifecycle_state="RUNNING",
            config={"mode": "paper", "dry_run": True},
            exchange_name="kucoin",
            symbol="BTCUSDT",
            exchange_client_ready=False,
            exchange_auth_ready=False,
            balance_check_ok=False,
            position_check_ok=False,
            state=SimpleNamespace(runtime_metrics={"last_bot_update": NOW}),
            get_result=Mock(side_effect=AssertionError("must not be called")),
            get_status=Mock(side_effect=AssertionError("must not be called")),
            _get_real_account_snapshot=Mock(
                side_effect=AssertionError("must not be called")
            ),
        )
        existing.return_value = manager
        before = dict(manager.state.runtime_metrics)

        read_runtime_scalars()

        manager.get_result.assert_not_called()
        manager.get_status.assert_not_called()
        manager._get_real_account_snapshot.assert_not_called()
        network_request.assert_not_called()
        self.assertEqual(manager.state.runtime_metrics, before)


class AdvisorRuntimeServiceTest(unittest.TestCase):
    def test_full_response_matches_allowlist_and_model(self):
        response = build_runtime_response(
            reader=lambda: scalar_snapshot(),
            clock=lambda: NOW,
        )
        payload = response.model_dump(mode="json")

        self.assertEqual(
            set(payload),
            {"bot", "operation", "safety", "runtime", "warnings"},
        )
        self.assertEqual(payload["runtime"]["freshness"], "FRESH")
        AdvisorRuntimeResponse.model_validate_json(response.model_dump_json())

    def test_freshness_boundary_and_stale(self):
        fresh = build_runtime_response(
            reader=lambda: scalar_snapshot(source_updated_at=NOW - 10),
            clock=lambda: NOW,
        )
        stale = build_runtime_response(
            reader=lambda: scalar_snapshot(source_updated_at=NOW - 10.001),
            clock=lambda: NOW,
        )

        self.assertEqual(fresh.runtime.freshness, Freshness.FRESH)
        self.assertEqual(stale.runtime.freshness, Freshness.STALE)
        self.assertIn("RUNTIME_STALE", stale.warnings)

    def test_missing_or_future_timestamp_is_unknown(self):
        missing = build_runtime_response(
            reader=lambda: scalar_snapshot(source_updated_at=None),
            clock=lambda: NOW,
        )
        future = build_runtime_response(
            reader=lambda: scalar_snapshot(source_updated_at=NOW + 1),
            clock=lambda: NOW,
        )

        self.assertEqual(missing.runtime.freshness, Freshness.UNKNOWN)
        self.assertIsNone(missing.runtime.sourceUpdatedAt)
        self.assertEqual(future.runtime.freshness, Freshness.UNKNOWN)
        self.assertIn("SOURCE_TIMESTAMP_IN_FUTURE", future.warnings)

    def test_non_finite_timestamps_are_unknown(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                response = build_runtime_response(
                    reader=lambda value=value: scalar_snapshot(source_updated_at=value),
                    clock=lambda: NOW,
                )
                self.assertEqual(response.runtime.freshness, Freshness.UNKNOWN)
                self.assertIsNone(response.runtime.sourceUpdatedAt)

    def test_response_model_rejects_extra_fields_and_non_strict_bool(self):
        payload = build_runtime_response(
            reader=lambda: scalar_snapshot(),
            clock=lambda: NOW,
        ).model_dump(mode="json")
        payload["secret"] = "must-not-pass"
        payload["safety"]["dryRun"] = "true"

        with self.assertRaises(ValidationError):
            AdvisorRuntimeResponse.model_validate(payload)

    def test_allowlist_excludes_secrets_accounts_orders_and_positions(self):
        payload = build_runtime_response(
            reader=lambda: scalar_snapshot(),
            clock=lambda: NOW,
        ).model_dump_json()

        for forbidden in (
            "secret",
            "credential",
            "apiKey",
            "account",
            "order",
            "position",
        ):
            self.assertNotIn(forbidden, payload)


class AdvisorRuntimeApiTest(unittest.TestCase):
    @patch("backend.api.ai_advisor.build_runtime_response")
    def test_runtime_route_fails_closed_before_reader(self, build):
        api = runtime_client()

        for headers in (
            {},
            {"Authorization": "Bearer wrong"},
            [
                ("Authorization", f"Bearer {TOKEN}"),
                ("Authorization", f"Bearer {TOKEN}"),
            ],
        ):
            response = api.get("/api/ai-advisor/runtime", headers=headers)
            self.assertEqual(response.status_code, 401)

        self.assertEqual(
            runtime_client(allowed=False)
            .get(
                "/api/ai-advisor/runtime",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            .status_code,
            403,
        )
        self.assertEqual(
            runtime_client(enabled=False).get("/api/ai-advisor/runtime").status_code,
            503,
        )
        build.assert_not_called()

    @patch("backend.api.ai_advisor.build_runtime_response")
    def test_runtime_route_accepts_authorized_operator(self, build):
        build.return_value = build_runtime_response(
            reader=lambda: scalar_snapshot(),
            clock=lambda: NOW,
        )

        response = runtime_client().get(
            "/api/ai-advisor/runtime",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )

        self.assertEqual(response.status_code, 200)
        build.assert_called_once_with()

    @patch(
        "backend.api.ai_advisor.build_runtime_response",
        side_effect=RuntimeError("internal secret detail"),
    )
    def test_error_contract_hides_internal_exception(self, _build):
        response = advisor_runtime()

        self.assertIsInstance(response, JSONResponse)
        self.assertEqual(response.status_code, 500)
        body = response.body.decode()
        self.assertIn("ADVISOR_RUNTIME_UNAVAILABLE", body)
        self.assertIn('"retryable":true', body)
        self.assertIn("requestId", body)
        self.assertIn("occurredAt", body)
        self.assertNotIn("internal secret detail", body)


if __name__ == "__main__":
    unittest.main()
