import json
import unittest

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.api_models import AdvisorAPIConfig
from backend.ai_advisor.api_rate_limit import (
    AdvisorConcurrencyLimiter,
    AdvisorRateLimiter,
)
from backend.ai_advisor.api_security import InjectedBearerAuthenticator
from backend.ai_advisor.openai_provider import OpenAIProviderAdapter
from backend.api.ai_advisor import AdvisorAPIComposition, create_advice_router
from tests.test_ai_advisor_openai_sdk_compatibility import (
    response_fixture,
    sdk_transport,
)
from tests.test_ai_advisor_provider import (
    boundary_config,
    capabilities,
    connection_config,
    model_policy,
)
from tests.test_ai_advisor_provider_contract import fixture_text
from tests.test_ai_advisor_service import service, service_input

TOKEN = "endpoint-test-token"


class FixedClock:
    def __init__(self):
        self.value = 100.0

    def __call__(self):
        return self.value


class CountingService:
    def __init__(self, delegate=None, exception=None):
        self.delegate = delegate or service()
        self.exception = exception
        self.calls = 0

    def generate_response(self, value):
        self.calls += 1
        if self.exception is not None:
            raise self.exception
        return self.delegate.generate_response(value)


def client(
    *,
    service_dependency=None,
    config=None,
    clock=None,
    allowed=True,
):
    config = config or AdvisorAPIConfig(enabled=True)
    clock = clock or FixedClock()
    service_dependency = service_dependency or CountingService()
    composition = AdvisorAPIComposition(
        config=config,
        authenticator=InjectedBearerAuthenticator(
            principalId="principal-1",
            advisorAccessAllowed=allowed,
            _token=TOKEN,
        ),
        service=service_dependency,
        rateLimiter=AdvisorRateLimiter(
            limit=config.rateLimitRequests,
            window_seconds=config.rateLimitWindowSeconds,
            clock=clock,
        ),
        concurrencyLimiter=AdvisorConcurrencyLimiter(
            limit=config.concurrencyLimit,
            acquire_timeout_seconds=config.concurrencyAcquireTimeoutSeconds,
        ),
    )
    app = FastAPI()
    app.include_router(
        create_advice_router(composition),
        prefix="/api/ai-advisor",
    )
    return TestClient(app), service_dependency, clock


def payload():
    return {"serviceInput": service_input().model_dump(mode="json")}


def headers():
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }


class AdvisorAPITest(unittest.TestCase):
    def test_valid_request_returns_projected_response(self):
        api, dependency, _ = client()
        response = api.post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")
        self.assertIn("advisorResponse", response.json())
        self.assertNotIn("providerResponse", response.text)
        self.assertEqual(dependency.calls, 1)

    def test_offline_real_sdk_transport_endpoint_e2e(self):
        sdk, _, _ = sdk_transport(
            lambda request: httpx.Response(
                200,
                json=response_fixture(fixture_text()),
            )
        )
        advisor_service = AdvisorService(
            provider=OpenAIProviderAdapter(connection_config(), sdk),
            providerConfig=boundary_config(),
            modelPolicy=model_policy(),
            capabilities=capabilities(),
        )
        api, _, _ = client(service_dependency=advisor_service)
        response = api.post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "SUCCEEDED")

    def test_content_type_and_malformed_json_fail_before_service(self):
        for content_type, body, expected in (
            ("text/plain", "{}", 415),
            ("multipart/form-data", "{}", 415),
            ("application/x-www-form-urlencoded", "{}", 415),
            ("application/json", "{", 422),
            ("application/json", '{"serviceInput":NaN}', 422),
            (
                "application/json",
                '{"serviceInput":{},"serviceInput":{}}',
                422,
            ),
        ):
            dependency = CountingService()
            api, _, _ = client(service_dependency=dependency)
            request_headers = headers()
            request_headers["Content-Type"] = content_type
            response = api.post(
                "/api/ai-advisor/advice",
                content=body,
                headers=request_headers,
            )
            self.assertEqual(response.status_code, expected)
            self.assertEqual(dependency.calls, 0)

    def test_size_limit_checks_declared_and_actual_body(self):
        body = json.dumps(payload(), separators=(",", ":"))
        exact_config = AdvisorAPIConfig(
            enabled=True,
            maxRequestBytes=len(body.encode()),
        )
        api, dependency, _ = client(config=exact_config)
        exact = api.post(
            "/api/ai-advisor/advice",
            content=body,
            headers=headers(),
        )
        self.assertEqual(exact.status_code, 200)
        self.assertEqual(dependency.calls, 1)

        over = api.post(
            "/api/ai-advisor/advice",
            content=body + " ",
            headers=headers(),
        )
        self.assertEqual(over.status_code, 413)
        self.assertEqual(dependency.calls, 1)
        self.assertNotIn(body[:100], over.text)

    def test_schema_and_public_override_fields_are_rejected(self):
        forbidden = (
            "provider",
            "model",
            "credentialId",
            "apiKey",
            "allowNetworkInvocation",
            "timeout",
            "retry",
            "systemPrompt",
            "tools",
            "executionEnabled",
        )
        for field in forbidden:
            dependency = CountingService()
            api, _, _ = client(service_dependency=dependency)
            value = payload()
            value[field] = "not-allowed"
            response = api.post(
                "/api/ai-advisor/advice",
                content=json.dumps(value),
                headers=headers(),
            )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(dependency.calls, 0)
            self.assertNotIn("not-allowed", response.text)

    def test_domain_failure_mapping_is_fixed(self):
        from backend.ai_advisor.service_models import (
            AdvisorServiceFailure,
            AdvisorServiceFailureCode,
            AdvisorServiceResult,
            AdvisorServiceStatus,
            service_failure_message,
        )

        mappings = {
            AdvisorServiceFailureCode.ADVISOR_INVALID_CONVERSATION: 422,
            AdvisorServiceFailureCode.ADVISOR_CONTEXT_INVALID: 422,
            AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE: 503,
            AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE: 502,
            AdvisorServiceFailureCode.ADVISOR_RESPONSE_INVALID: 502,
        }
        for code, status in mappings.items():
            result = AdvisorServiceResult(
                status=AdvisorServiceStatus.FAILED,
                failure=AdvisorServiceFailure(
                    code=code,
                    safeMessage=service_failure_message(code),
                    retryAllowed=False,
                ),
            )

            class FixedService:
                calls = 0

                def generate_response(self, value):
                    self.calls += 1
                    return result

            dependency = FixedService()
            api, _, _ = client(service_dependency=dependency)
            response = api.post(
                "/api/ai-advisor/advice",
                content=json.dumps(payload()),
                headers=headers(),
            )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["failureCode"], code.value)
            self.assertEqual(dependency.calls, 1)

    def test_endpoint_disabled_and_service_exception_are_safe(self):
        disabled_dependency = CountingService()
        api, _, _ = client(
            config=AdvisorAPIConfig(enabled=False),
            service_dependency=disabled_dependency,
        )
        disabled = api.post("/api/ai-advisor/advice", json=payload())
        self.assertEqual(disabled.status_code, 503)
        self.assertEqual(disabled_dependency.calls, 0)

        secret = "raw-prompt-secret /home/private/advisor.py"
        failing = CountingService(exception=RuntimeError(secret))
        api, _, _ = client(service_dependency=failing)
        response = api.post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=headers(),
        )
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(secret, response.text)
        self.assertEqual(failing.calls, 1)


if __name__ == "__main__":
    unittest.main()
