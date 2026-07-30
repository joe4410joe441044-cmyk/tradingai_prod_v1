import inspect
import json
import unittest
from dataclasses import dataclass
from unittest.mock import patch

import httpx
import openai
from openai import OpenAI

from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.credential_loader import (
    EphemeralCredential,
    InjectedCredentialLoader,
)
from backend.ai_advisor.openai_provider import OpenAIProviderAdapter
from backend.ai_advisor.provider_failure_observation import (
    ProviderFailureStage,
    ProviderSafeReason,
    RecordingProviderFailureObservationSink,
)
from backend.ai_advisor.openai_sdk_transport import (
    DefaultOpenAIClientFactory,
    OpenAISDKTransport,
)
from backend.ai_advisor.provider_transport import (
    OpenAITransportAuthenticationError,
    OpenAITransportConnectionError,
    OpenAITransportInternalError,
    OpenAITransportRateLimitError,
    OpenAITransportRejectedError,
    OpenAITransportTimeout,
)
from backend.ai_advisor.service_models import (
    AdvisorServiceFailureCode,
    AdvisorServiceStatus,
)
from tests.test_ai_advisor_openai_sdk_transport import request
from tests.test_ai_advisor_provider import (
    boundary_config,
    capabilities,
    connection_config,
    model_policy,
)
from tests.test_ai_advisor_provider_contract import fixture_text
from tests.test_ai_advisor_service import service_input

PINNED_OPENAI_VERSION = "2.48.0"


def response_fixture(
    text,
    *,
    status="completed",
    content_type="output_text",
    extra_outputs=(),
):
    content = (
        {
            "type": "output_text",
            "text": text,
            "annotations": [],
            "logprobs": [],
        }
        if content_type == "output_text"
        else {"type": "refusal", "refusal": text}
    )
    output = [
        {
            "id": "msg_offline_1",
            "type": "message",
            "status": status,
            "role": "assistant",
            "content": [content],
        }
    ]
    for index, extra in enumerate(extra_outputs, start=2):
        output.append(
            {
                "id": f"msg_offline_{index}",
                "type": "message",
                "status": status,
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": extra,
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        )
    return {
        "id": "resp_offline",
        "object": "response",
        "created_at": 0,
        "status": status,
        "background": False,
        "error": None,
        "incomplete_details": (
            {"reason": "max_output_tokens"} if status == "incomplete" else None
        ),
        "instructions": None,
        "max_output_tokens": 2048,
        "model": "openai-advisor-model",
        "output": output,
        "parallel_tool_calls": False,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "service_tier": "default",
        "store": False,
        "temperature": 0.0,
        "text": {"format": {"type": "json_object"}},
        "tool_choice": "auto",
        "tools": [],
        "top_logprobs": 0,
        "top_p": 1.0,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2,
        },
        "metadata": {},
    }


@dataclass
class OfflineSDKClientFactory:
    handler: object
    calls: int = 0

    def create(self, *, credential, endpoint, timeout_seconds):
        self.calls += 1
        transport = httpx.MockTransport(self.handler)
        return OpenAI(
            api_key=credential._consume(),
            base_url=endpoint,
            timeout=timeout_seconds,
            max_retries=0,
            http_client=httpx.Client(
                transport=transport,
                follow_redirects=False,
            ),
        )


def sdk_transport(handler, *, allowed=True, failure_sink=None):
    loader = InjectedCredentialLoader(
        {"advisor-openai-primary": "offline-placeholder-credential"}
    )
    factory = OfflineSDKClientFactory(handler)
    arguments = dict(
        config=connection_config(),
        credentialLoader=loader,
        clientFactory=factory,
        allowNetworkInvocation=allowed,
    )
    if failure_sink is not None:
        arguments["failureObservationSink"] = failure_sink
    value = OpenAISDKTransport(**arguments)
    return value, loader, factory


class OpenAISDKCompatibilityTest(unittest.TestCase):
    def test_http_failures_emit_only_allowlisted_observations(self):
        cases = (
            (400, ProviderSafeReason.LIVE_PROVIDER_BAD_REQUEST),
            (401, ProviderSafeReason.LIVE_PROVIDER_AUTHENTICATION_FAILED),
            (403, ProviderSafeReason.LIVE_PROVIDER_PERMISSION_DENIED),
            (429, ProviderSafeReason.LIVE_PROVIDER_RATE_OR_QUOTA_LIMITED),
            (500, ProviderSafeReason.LIVE_PROVIDER_SERVER_ERROR),
        )
        for status, reason in cases:
            with self.subTest(status=status):
                calls = 0
                sink = RecordingProviderFailureObservationSink()

                def handler(http_request):
                    nonlocal calls
                    calls += 1
                    return httpx.Response(
                        status,
                        json={
                            "error": {
                                "message": "sk-test-DO-NOT-LEAK",
                                "type": "private",
                                "code": "private",
                            }
                        },
                        headers={"x-request-id": "private-request-id"},
                    )

                value, _, _ = sdk_transport(
                    handler,
                    failure_sink=sink,
                )
                with self.assertRaises(Exception):
                    value.invoke(request())
                self.assertEqual(calls, 1)
                observation = sink.observation
                self.assertEqual(observation.safeReason, reason)
                self.assertEqual(
                    observation.failureStage,
                    ProviderFailureStage.PROVIDER_INVOCATION,
                )
                self.assertEqual(observation.httpStatus, status)
                rendered = observation.model_dump_json()
                self.assertNotIn("sk-test-DO-NOT-LEAK", rendered)
                self.assertNotIn("private-request-id", rendered)

    def test_default_factory_explicitly_disables_redirects_and_retries(self):
        http_client = object()
        sdk_client = object()
        with (
            patch(
                "openai.DefaultHttpxClient",
                return_value=http_client,
            ) as http_factory,
            patch("openai.OpenAI", return_value=sdk_client) as sdk_factory,
        ):
            result = DefaultOpenAIClientFactory().create(
                credential=EphemeralCredential("offline-secret"),
                endpoint="https://api.openai.com/v1",
                timeout_seconds=30.0,
            )
        self.assertIs(result, sdk_client)
        http_factory.assert_called_once_with(
            timeout=30.0,
            follow_redirects=False,
        )
        self.assertEqual(sdk_factory.call_args.kwargs["max_retries"], 0)
        self.assertIs(sdk_factory.call_args.kwargs["http_client"], http_client)

    def test_pinned_dependency_and_public_signatures(self):
        self.assertEqual(openai.__version__, PINNED_OPENAI_VERSION)
        client_parameters = inspect.signature(OpenAI).parameters
        for name in ("api_key", "base_url", "timeout", "max_retries", "http_client"):
            self.assertIn(name, client_parameters)
        client = OpenAI(api_key="offline-placeholder", max_retries=0)
        try:
            parameters = inspect.signature(client.responses.create).parameters
        finally:
            client.close()
        for name in (
            "model",
            "input",
            "max_output_tokens",
            "temperature",
            "text",
            "stream",
            "store",
            "timeout",
        ):
            self.assertIn(name, parameters)

    def test_real_sdk_serialization_and_response_parsing_are_offline(self):
        observed = {}

        def handler(http_request):
            observed["method"] = http_request.method
            observed["url"] = str(http_request.url)
            observed["authorizationPresent"] = "authorization" in http_request.headers
            observed["body"] = json.loads(http_request.content)
            return httpx.Response(200, json=response_fixture(fixture_text()))

        value, loader, factory = sdk_transport(handler)
        result = value.invoke(request())
        self.assertEqual(loader.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(observed["method"], "POST")
        self.assertEqual(
            observed["url"],
            "https://api.openai.example/v1/responses",
        )
        self.assertTrue(observed["authorizationPresent"])
        body = observed["body"]
        self.assertEqual(body["model"], "openai-advisor-model")
        self.assertEqual(body["input"], "fixed prompt")
        self.assertEqual(body["max_output_tokens"], 2048)
        self.assertEqual(body["temperature"], 0.0)
        self.assertIs(body["stream"], False)
        self.assertIs(body["store"], False)
        self.assertEqual(body["text"], {"format": {"type": "json_object"}})
        self.assertNotIn("tools", body)
        self.assertNotIn("functions", body)
        self.assertEqual(result["output_text"], fixture_text())

    def test_guard_denial_never_constructs_real_sdk_client(self):
        calls = 0

        def handler(http_request):
            nonlocal calls
            calls += 1
            raise AssertionError("offline handler must not be reached")

        value, loader, factory = sdk_transport(handler, allowed=False)
        with self.assertRaises(Exception):
            value.invoke(request())
        self.assertEqual(loader.calls, 0)
        self.assertEqual(factory.calls, 0)
        self.assertEqual(calls, 0)

    def test_real_sdk_has_no_retry_for_http_errors(self):
        for status, expected in (
            (400, OpenAITransportRejectedError),
            (401, OpenAITransportAuthenticationError),
            (403, OpenAITransportRejectedError),
            (429, OpenAITransportRateLimitError),
            (500, OpenAITransportRejectedError),
        ):
            calls = 0

            def handler(http_request):
                nonlocal calls
                calls += 1
                return httpx.Response(
                    status,
                    json={
                        "error": {
                            "message": "offline failure",
                            "type": "offline_error",
                            "code": "offline",
                        }
                    },
                    headers={"x-request-id": "offline-request"},
                )

            value, _, _ = sdk_transport(handler)
            with self.assertRaises(expected):
                value.invoke(request())
            self.assertEqual(calls, 1)

    def test_real_sdk_redirects_fail_closed_without_second_request(self):
        locations = (
            "https://outside.example/collect/offline-location-secret",
            "https://api.openai.example/v1/responses/redirected",
        )
        for status in (301, 302, 307, 308):
            for location in locations:
                with self.subTest(status=status, location=location):
                    calls = 0

                    def handler(http_request):
                        nonlocal calls
                        calls += 1
                        return httpx.Response(
                            status,
                            headers={"location": location},
                            json={
                                "error": {
                                    "message": "offline-provider-body-secret",
                                }
                            },
                        )

                    value, _, _ = sdk_transport(handler)
                    with self.assertRaises(
                        OpenAITransportRejectedError
                    ) as caught:
                        value.invoke(request())
                    self.assertEqual(calls, 1)
                    rendered = repr(caught.exception) + str(caught.exception)
                    self.assertNotIn(location, rendered)
                    self.assertNotIn("offline-location-secret", rendered)
                    self.assertNotIn("offline-provider-body-secret", rendered)
                    self.assertNotIn("offline-placeholder-credential", rendered)

    def test_real_sdk_base_exception_is_safe_internal_failure(self):
        class RaisingResponses:
            def create(self, **kwargs):
                raise openai.OpenAIError(
                    "sk-test-secret-value /home/private request-id-secret"
                )

        class Client:
            responses = RaisingResponses()

        @dataclass
        class Factory:
            def create(self, **kwargs):
                return Client()

        value = OpenAISDKTransport(
            config=connection_config(),
            credentialLoader=InjectedCredentialLoader(
                {"advisor-openai-primary": "offline-placeholder-credential"}
            ),
            clientFactory=Factory(),
            allowNetworkInvocation=True,
        )
        with self.assertRaises(OpenAITransportInternalError) as caught:
            value.invoke(request())
        rendered = repr(caught.exception) + str(caught.exception)
        self.assertNotIn("sk-test-secret-value", rendered)
        self.assertNotIn("/home/private", rendered)
        self.assertNotIn("request-id-secret", rendered)

    def test_real_sdk_has_no_retry_for_connection_or_timeout(self):
        for sdk_error, expected in (
            (
                httpx.ConnectError(
                    "offline connection",
                    request=httpx.Request("POST", "https://offline.invalid"),
                ),
                OpenAITransportConnectionError,
            ),
            (
                httpx.ReadTimeout(
                    "offline timeout",
                    request=httpx.Request("POST", "https://offline.invalid"),
                ),
                OpenAITransportTimeout,
            ),
        ):
            calls = 0

            def handler(http_request):
                nonlocal calls
                calls += 1
                raise sdk_error

            value, _, _ = sdk_transport(handler)
            with self.assertRaises(expected):
                value.invoke(request())
            self.assertEqual(calls, 1)

    def test_real_sdk_response_edge_cases_are_fixed(self):
        cases = (
            response_fixture(""),
            response_fixture(fixture_text(), status="incomplete"),
            response_fixture("offline refusal", content_type="refusal"),
            {**response_fixture(fixture_text()), "output": []},
        )
        for fixture in cases:
            value, _, _ = sdk_transport(
                lambda http_request, fixture=fixture: httpx.Response(200, json=fixture)
            )
            with self.assertRaises(OpenAITransportRejectedError):
                value.invoke(request())

        joined = response_fixture("first", extra_outputs=("second",))
        value, _, _ = sdk_transport(
            lambda http_request: httpx.Response(200, json=joined)
        )
        self.assertEqual(value.invoke(request())["output_text"], "firstsecond")

    def test_real_sdk_offline_service_end_to_end(self):
        def make_service(text):
            value, _, _ = sdk_transport(
                lambda http_request: httpx.Response(200, json=response_fixture(text))
            )
            return AdvisorService(
                provider=OpenAIProviderAdapter(connection_config(), value),
                providerConfig=boundary_config(),
                modelPolicy=model_policy(),
                capabilities=capabilities(),
            )

        success = make_service(fixture_text()).generate_response(service_input())
        self.assertEqual(success.status, AdvisorServiceStatus.SUCCEEDED)
        malformed = make_service("not json").generate_response(service_input())
        self.assertEqual(
            malformed.failure.code,
            AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE,
        )


if __name__ == "__main__":
    unittest.main()
