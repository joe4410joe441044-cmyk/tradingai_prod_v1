import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.ai_advisor.api_models import AdvisorAPIConfig
from tests.test_ai_advisor_api import (
    CountingService,
    FixedClock,
    TOKEN,
    client,
    headers,
    payload,
)


class AdvisorAPISecurityTest(unittest.TestCase):
    def test_authentication_failures_never_call_service_or_leak(self):
        cases = (
            {},
            {"Authorization": "Basic value", "Content-Type": "application/json"},
            {"Authorization": "Bearer ", "Content-Type": "application/json"},
            {
                "Authorization": "Bearer wrong-secret-token",
                "Content-Type": "application/json",
            },
            {
                "Authorization": f"Bearer  {TOKEN}",
                "Content-Type": "application/json",
            },
        )
        for request_headers in cases:
            dependency = CountingService()
            api, _, _ = client(service_dependency=dependency)
            response = api.post(
                "/api/ai-advisor/advice",
                content=json.dumps(payload()),
                headers=request_headers,
            )
            self.assertEqual(response.status_code, 401)
            self.assertEqual(dependency.calls, 0)
            self.assertNotIn(TOKEN, response.text)
            self.assertNotIn("wrong-secret-token", response.text)

    def test_duplicate_authorization_header_is_rejected(self):
        dependency = CountingService()
        api, _, _ = client(service_dependency=dependency)
        response = api.post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=[
                ("Authorization", f"Bearer {TOKEN}"),
                ("Authorization", f"Bearer {TOKEN}"),
                ("Content-Type", "application/json; charset=utf-8"),
            ],
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(dependency.calls, 0)

    def test_authorization_denied_and_principal_mismatch(self):
        denied = CountingService()
        api, _, _ = client(service_dependency=denied, allowed=False)
        response = api.post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=headers(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(denied.calls, 0)

        mismatch = CountingService()
        api, _, _ = client(service_dependency=mismatch)
        value = payload()
        value["serviceInput"]["request"]["permissionContext"][
            "principalId"
        ] = "another-principal"
        response = api.post(
            "/api/ai-advisor/advice",
            content=json.dumps(value),
            headers=headers(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(mismatch.calls, 0)

    def test_rate_limit_window_and_principal_key(self):
        clock = FixedClock()
        config = AdvisorAPIConfig(
            enabled=True,
            rateLimitRequests=2,
            rateLimitWindowSeconds=60.0,
        )
        dependency = CountingService()
        api, _, _ = client(
            service_dependency=dependency,
            config=config,
            clock=clock,
        )
        for _ in range(2):
            self.assertEqual(
                api.post(
                    "/api/ai-advisor/advice",
                    content=json.dumps(payload()),
                    headers=headers(),
                ).status_code,
                200,
            )
        limited = api.post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=headers(),
        )
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["retry-after"], "60")
        self.assertEqual(dependency.calls, 2)
        clock.value += 60
        self.assertEqual(
            api.post(
                "/api/ai-advisor/advice",
                content=json.dumps(payload()),
                headers=headers(),
            ).status_code,
            200,
        )

    def test_concurrency_limit_and_release(self):
        entered = threading.Event()
        release = threading.Event()

        class BlockingService(CountingService):
            def generate_response(self, value):
                self.calls += 1
                entered.set()
                release.wait(timeout=2)
                return self.delegate.generate_response(value)

        dependency = BlockingService()
        config = AdvisorAPIConfig(
            enabled=True,
            concurrencyLimit=1,
            concurrencyAcquireTimeoutSeconds=0.001,
        )
        api, _, _ = client(service_dependency=dependency, config=config)

        def invoke():
            return api.post(
                "/api/ai-advisor/advice",
                content=json.dumps(payload()),
                headers=headers(),
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(invoke)
            self.assertTrue(entered.wait(timeout=1))
            second = invoke()
            self.assertEqual(second.status_code, 429)
            self.assertEqual(dependency.calls, 1)
            release.set()
            self.assertEqual(first.result(timeout=2).status_code, 200)
        self.assertEqual(invoke().status_code, 200)

    def test_endpoint_timeout_is_safe_and_holds_slot_until_completion(self):
        release = threading.Event()

        class SlowService(CountingService):
            def generate_response(self, value):
                self.calls += 1
                release.wait(timeout=1)
                return self.delegate.generate_response(value)

        dependency = SlowService()
        config = AdvisorAPIConfig(
            enabled=True,
            endpointTimeoutSeconds=0.005,
            concurrencyLimit=1,
            concurrencyAcquireTimeoutSeconds=0.001,
        )
        api, _, _ = client(service_dependency=dependency, config=config)
        response = api.post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=headers(),
        )
        self.assertEqual(response.status_code, 504)
        self.assertNotIn("SlowService", response.text)
        release.set()


if __name__ == "__main__":
    unittest.main()
