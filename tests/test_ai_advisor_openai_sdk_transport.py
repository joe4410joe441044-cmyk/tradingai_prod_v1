import builtins
import json
import socket
import unittest
import urllib.request
from dataclasses import dataclass
from unittest.mock import patch

from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.credential_loader import (
    CredentialFailureCode,
    InjectedCredentialLoader,
)
from backend.ai_advisor.openai_provider import OpenAIProviderAdapter
from backend.ai_advisor.openai_sdk_transport import (
    DefaultOpenAIClientFactory,
    OpenAISDKTransport,
)
from backend.ai_advisor.provider_failure_observation import (
    ProviderFailureStage,
    ProviderSafeReason,
    RecordingProviderFailureObservationSink,
)
from backend.ai_advisor.provider_models import AdvisorProviderFinishReason
from backend.ai_advisor.provider_transport import (
    OpenAITransportAuthenticationError,
    OpenAITransportConfigurationError,
    OpenAITransportConnectionError,
    OpenAITransportInternalError,
    OpenAITransportRateLimitError,
    OpenAITransportRejectedError,
    OpenAITransportRequest,
    OpenAITransportTimeout,
)
from backend.ai_advisor.service_models import (
    AdvisorServiceFailureCode,
    AdvisorServiceStatus,
)
from backend.ai_advisor.usage_observation import (
    RecordingProviderMetadataObservationSink,
    SafeEndpointClassification,
    SafeProviderName,
)
from tests.test_ai_advisor_provider import (
    boundary_config,
    capabilities,
    connection_config,
    model_policy,
)
from tests.test_ai_advisor_provider_contract import fixture_text
from tests.test_ai_advisor_service import service_input


class FakeResponse:
    def __init__(
        self,
        output_text,
        status="completed",
        usage=None,
        *,
        request_id="resp_offline_test",
        model="openai-advisor-model",
    ):
        self.output_text = output_text
        self.status = status
        self.usage = usage
        self._request_id = request_id
        self.model = model


class FakeResponses:
    def __init__(self, response=None, exception=None):
        self.response = response
        self.exception = exception
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exception is not None:
            raise self.exception
        return self.response


class FakeClient:
    def __init__(self, responses):
        self.responses = responses


@dataclass
class FakeClientFactory:
    client: FakeClient
    calls: int = 0
    endpoint: str | None = None
    timeout: float | None = None

    def create(self, *, credential, endpoint, timeout_seconds):
        self.calls += 1
        self.endpoint = endpoint
        self.timeout = timeout_seconds
        self.credentialPresent = credential.is_present
        return self.client


def request():
    return OpenAITransportRequest(
        model="openai-advisor-model",
        input="fixed prompt",
        timeoutSeconds=30.0,
        maxOutputTokens=2048,
        temperature=0.0,
        responseFormat="json_object",
        stream=False,
    )


def transport(
    *,
    response=None,
    exception=None,
    allowed=True,
    loader=None,
    usage_sink=None,
    metadata_sink=None,
    failure_sink=None,
):
    responses = FakeResponses(response=response, exception=exception)
    factory = FakeClientFactory(FakeClient(responses))
    loader = loader or InjectedCredentialLoader(
        {"advisor-openai-primary": "test-credential-value"}
    )
    arguments = dict(
        config=connection_config(),
        credentialLoader=loader,
        clientFactory=factory,
        allowNetworkInvocation=allowed,
    )
    if usage_sink is not None:
        arguments["usageObservationSink"] = usage_sink
    if metadata_sink is not None:
        arguments["metadataObservationSink"] = metadata_sink
    if failure_sink is not None:
        arguments["failureObservationSink"] = failure_sink
    value = OpenAISDKTransport(**arguments)
    return value, loader, factory, responses


class OpenAISDKTransportTest(unittest.TestCase):
    def test_non_http_failures_emit_fixed_stage_and_reason(self):
        cases = (
            (
                OpenAITransportAuthenticationError("sk-test-DO-NOT-LEAK"),
                ProviderSafeReason.LIVE_PROVIDER_AUTHENTICATION_FAILED,
                ProviderFailureStage.PROVIDER_INVOCATION,
            ),
            (
                OpenAITransportRateLimitError("sk-test-DO-NOT-LEAK"),
                ProviderSafeReason.LIVE_PROVIDER_RATE_OR_QUOTA_LIMITED,
                ProviderFailureStage.PROVIDER_INVOCATION,
            ),
            (
                OpenAITransportTimeout("sk-test-DO-NOT-LEAK"),
                ProviderSafeReason.LIVE_PROVIDER_TIMEOUT,
                ProviderFailureStage.PROVIDER_INVOCATION,
            ),
            (
                OpenAITransportConnectionError("sk-test-DO-NOT-LEAK"),
                ProviderSafeReason.LIVE_PROVIDER_CONNECTION_FAILED,
                ProviderFailureStage.PROVIDER_INVOCATION,
            ),
            (
                RuntimeError("sk-test-DO-NOT-LEAK"),
                ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE,
                ProviderFailureStage.PROVIDER_INVOCATION,
            ),
        )
        for exception, reason, stage in cases:
            with self.subTest(reason=reason):
                sink = RecordingProviderFailureObservationSink()
                value, _, _, responses = transport(
                    exception=exception,
                    failure_sink=sink,
                )
                with self.assertRaises(Exception):
                    value.invoke(request())
                self.assertEqual(len(responses.calls), 1)
                self.assertEqual(sink.observation.safeReason, reason)
                self.assertEqual(sink.observation.failureStage, stage)
                self.assertNotIn(
                    "sk-test-DO-NOT-LEAK",
                    sink.observation.model_dump_json(),
                )

    def test_credential_client_and_response_failures_are_distinct(self):
        credential_sink = RecordingProviderFailureObservationSink()
        loader = InjectedCredentialLoader(
            {},
            fixedFailure=CredentialFailureCode.CREDENTIAL_NOT_FOUND,
        )
        value, _, factory, _ = transport(
            loader=loader,
            failure_sink=credential_sink,
        )
        with self.assertRaises(OpenAITransportConfigurationError):
            value.invoke(request())
        self.assertEqual(factory.calls, 0)
        self.assertEqual(
            credential_sink.observation.safeReason,
            ProviderSafeReason.LIVE_PROVIDER_CREDENTIAL_UNAVAILABLE,
        )
        self.assertEqual(
            credential_sink.observation.failureStage,
            ProviderFailureStage.CREDENTIAL_RESOLUTION,
        )

        class FailingFactory:
            calls = 0

            def create(self, **kwargs):
                self.calls += 1
                raise RuntimeError("sk-test-DO-NOT-LEAK")

        client_sink = RecordingProviderFailureObservationSink()
        client_value = OpenAISDKTransport(
            config=connection_config(),
            credentialLoader=InjectedCredentialLoader(
                {"advisor-openai-primary": "offline-placeholder"}
            ),
            clientFactory=FailingFactory(),
            allowNetworkInvocation=True,
            failureObservationSink=client_sink,
        )
        with self.assertRaises(OpenAITransportConfigurationError):
            client_value.invoke(request())
        self.assertEqual(
            client_sink.observation.safeReason,
            ProviderSafeReason.LIVE_PROVIDER_CLIENT_CONFIGURATION_FAILED,
        )
        self.assertEqual(
            client_sink.observation.failureStage,
            ProviderFailureStage.CLIENT_CREATION,
        )

        response_sink = RecordingProviderFailureObservationSink()
        response_value, _, _, calls = transport(
            response=FakeResponse(" "),
            failure_sink=response_sink,
        )
        with self.assertRaises(OpenAITransportRejectedError):
            response_value.invoke(request())
        self.assertEqual(len(calls.calls), 1)
        self.assertEqual(
            response_sink.observation.safeReason,
            ProviderSafeReason.LIVE_PROVIDER_OUTPUT_TEXT_CONTRACT_FAILED,
        )
        self.assertEqual(
            response_sink.observation.failureStage,
            ProviderFailureStage.RESPONSE_VALIDATION,
        )

    def test_guard_denial_prevents_credential_and_client_access(self):
        value, loader, factory, responses = transport(
            response=FakeResponse(fixture_text()),
            allowed=False,
        )
        with self.assertRaises(OpenAITransportConfigurationError):
            value.invoke(request())
        self.assertEqual(loader.calls, 0)
        self.assertEqual(factory.calls, 0)
        self.assertEqual(responses.calls, [])

    def test_request_mapping_client_factory_and_single_sdk_call(self):
        metadata_sink = RecordingProviderMetadataObservationSink()
        value, loader, factory, responses = transport(
            response=FakeResponse(fixture_text()),
            metadata_sink=metadata_sink,
        )
        result = value.invoke(request())
        self.assertEqual(loader.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertTrue(factory.credentialPresent)
        self.assertEqual(factory.endpoint, "https://api.openai.example/v1")
        self.assertEqual(factory.timeout, 30.0)
        self.assertEqual(len(responses.calls), 1)
        call = responses.calls[0]
        self.assertEqual(call["model"], "openai-advisor-model")
        self.assertEqual(call["input"], "fixed prompt")
        self.assertEqual(call["max_output_tokens"], 2048)
        self.assertEqual(call["temperature"], 0.0)
        self.assertEqual(call["text"], {"format": {"type": "json_object"}})
        self.assertIs(call["stream"], False)
        self.assertIs(call["store"], False)
        self.assertNotIn("tools", call)
        self.assertNotIn("functions", call)
        self.assertEqual(result["output_text"], fixture_text())
        self.assertEqual(metadata_sink.observation.requestId, "resp_offline_test")
        self.assertEqual(metadata_sink.observation.model, "openai-advisor-model")
        self.assertEqual(metadata_sink.observation.provider, SafeProviderName.OPENAI)
        self.assertEqual(
            metadata_sink.observation.endpointClassification,
            SafeEndpointClassification.OFFICIAL_OPENAI,
        )

    def test_metadata_rejects_response_model_mismatch(self):
        sink = RecordingProviderMetadataObservationSink()
        value, _, _, _ = transport(
            response=FakeResponse(fixture_text(), model="unapproved-model"),
            metadata_sink=sink,
        )
        with self.assertRaises(OpenAITransportRejectedError):
            value.invoke(request())
        self.assertIsNone(sink.observation)

    def test_usage_sink_exception_does_not_change_provider_result(self):
        class RaisingSink:
            calls = 0

            def observe(self, observation):
                self.calls += 1
                raise RuntimeError("internal usage sink failure")

        sink = RaisingSink()
        value, loader, factory, responses = transport(
            response=FakeResponse(fixture_text()),
            usage_sink=sink,
        )
        result = value.invoke(request())
        self.assertEqual(result["output_text"], fixture_text())
        self.assertEqual(sink.calls, 1)
        self.assertEqual(loader.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)

    def test_credential_failure_prevents_client_creation(self):
        loader = InjectedCredentialLoader(
            {},
            fixedFailure=CredentialFailureCode.CREDENTIAL_NOT_FOUND,
        )
        value, loader, factory, responses = transport(loader=loader)
        with self.assertRaises(OpenAITransportConfigurationError):
            value.invoke(request())
        self.assertEqual(loader.calls, 1)
        self.assertEqual(factory.calls, 0)
        self.assertEqual(responses.calls, [])

    def test_sdk_exceptions_are_safely_mapped(self):
        exception_types = (
            ("AuthenticationError", OpenAITransportInternalError),
            ("PermissionDeniedError", OpenAITransportInternalError),
            ("RateLimitError", OpenAITransportInternalError),
            ("APITimeoutError", OpenAITransportInternalError),
            ("APIConnectionError", OpenAITransportInternalError),
            ("BadRequestError", OpenAITransportInternalError),
            ("UnexpectedSDKError", OpenAITransportInternalError),
        )
        secret = (
            "sk-test-secret-value Authorization: Bearer fake-token "
            "/home/private/openai/client.py "
            "https://user:password@private.example "
            "raw-provider-response-secret request-id-secret"
        )
        for name, expected in exception_types:
            sdk_exception = type(name, (Exception,), {})(secret)
            value, _, _, _ = transport(exception=sdk_exception)
            with self.assertRaises(expected) as caught:
                value.invoke(request())
            rendered = repr(caught.exception) + str(caught.exception)
            for fragment in (
                "sk-test-secret-value",
                "fake-token",
                "/home/private",
                "private.example",
                "raw-provider-response-secret",
                "request-id-secret",
            ):
                self.assertNotIn(fragment, rendered)

    def test_malformed_and_incomplete_responses_are_fixed_failures(self):
        cases = (
            None,
            FakeResponse(None),
            FakeResponse(1),
            FakeResponse(" "),
            FakeResponse("x" * 64_001),
            FakeResponse(fixture_text(), status="incomplete"),
        )
        for response in cases:
            value, _, _, _ = transport(response=response)
            with self.assertRaises(OpenAITransportRejectedError):
                value.invoke(request())

    def test_fake_client_path_performs_no_real_network(self):
        value, _, _, _ = transport(response=FakeResponse(fixture_text()))
        with (
            patch.object(socket, "socket", side_effect=AssertionError),
            patch.object(socket, "create_connection", side_effect=AssertionError),
            patch.object(urllib.request, "urlopen", side_effect=AssertionError),
        ):
            first = value.invoke(request())
            second = value.invoke(request())
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )

    def test_default_factory_import_is_lazy_and_missing_sdk_is_safe(self):
        factory = DefaultOpenAIClientFactory()
        value, loader, _, _ = transport()
        credential = loader.resolve(
            __import__(
                "tests.test_ai_advisor_credential_loader",
                fromlist=["resolution_input"],
            ).resolution_input(
                source=__import__(
                    "backend.ai_advisor.provider_config",
                    fromlist=["CredentialSource"],
                ).CredentialSource.INJECTED
            )
        ).credential
        real_import = builtins.__import__

        def missing_openai(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("private sdk path")
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=missing_openai):
            with self.assertRaises(OpenAITransportConfigurationError):
                factory.create(
                    credential=credential,
                    endpoint=None,
                    timeout_seconds=30.0,
                )

    def test_service_end_to_end_uses_parser_and_validator(self):
        value, _, _, responses = transport(response=FakeResponse(fixture_text()))
        service = AdvisorService(
            provider=OpenAIProviderAdapter(connection_config(), value),
            providerConfig=boundary_config(),
            modelPolicy=model_policy(),
            capabilities=capabilities(),
        )
        result = service.generate_response(service_input())
        self.assertEqual(result.status, AdvisorServiceStatus.SUCCEEDED)
        self.assertEqual(len(responses.calls), 1)

        malformed, _, _, _ = transport(response=FakeResponse("not json"))
        failed = AdvisorService(
            provider=OpenAIProviderAdapter(connection_config(), malformed),
            providerConfig=boundary_config(),
            modelPolicy=model_policy(),
            capabilities=capabilities(),
        ).generate_response(service_input())
        self.assertEqual(
            failed.failure.code,
            AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE,
        )


if __name__ == "__main__":
    unittest.main()
