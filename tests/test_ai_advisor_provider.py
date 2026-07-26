import builtins
import json
import math
import os
import socket
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.openai_provider import (
    OpenAIProviderAdapter,
    OpenAIProviderFailureCode,
    OpenAIProviderInvocationError,
)
from backend.ai_advisor.provider_config import (
    MAX_PROVIDER_OUTPUT_TOKENS,
    MAX_PROVIDER_TIMEOUT_SECONDS,
    MIN_PROVIDER_TIMEOUT_SECONDS,
    CredentialReference,
    CredentialSource,
    ProviderConnectionConfig,
    ProviderName,
    ProviderResponseFormat,
)
from backend.ai_advisor.provider_models import (
    AdvisorModelPolicy,
    AdvisorProviderCapabilities,
    AdvisorProviderCode,
    AdvisorProviderConfig,
    AdvisorProviderResponseFormat,
    AdvisorRetryPolicy,
)
from backend.ai_advisor.provider_registry import ProviderRegistry
from backend.ai_advisor.provider_transport import (
    DeterministicOpenAITransport,
    OpenAITransportAuthenticationError,
    OpenAITransportConnectionError,
    OpenAITransportRateLimitError,
    OpenAITransportTimeout,
)
from backend.ai_advisor.service_models import (
    AdvisorServiceFailureCode,
    AdvisorServiceStatus,
)
from tests.test_ai_advisor_provider_contract import fixture_text
from tests.test_ai_advisor_service import service_input


def connection_config(**overrides):
    values = dict(
        configVersion="ai-advisor-provider-connection/v1",
        provider=ProviderName.OPENAI,
        model="openai-advisor-model",
        credentialReference=CredentialReference(
            credentialId="advisor-openai-primary",
            source=CredentialSource.INJECTED,
        ),
        endpoint="https://api.openai.example/v1",
        timeoutSeconds=30.0,
        maxOutputTokens=2048,
        temperature=0.0,
        responseFormat=ProviderResponseFormat.STRICT_JSON,
        enabled=True,
    )
    values.update(overrides)
    return ProviderConnectionConfig(**values)


def boundary_config():
    return AdvisorProviderConfig(
        configVersion="ai-advisor-provider-config/v1",
        provider=AdvisorProviderCode.OPENAI,
        modelId="openai-advisor-model",
        timeoutSeconds=30,
        maxOutputCharacters=32_000,
        retryPolicy=AdvisorRetryPolicy.NO_RETRY,
        responseFormat=AdvisorProviderResponseFormat.STRICT_JSON,
    )


def model_policy():
    return AdvisorModelPolicy(
        provider=AdvisorProviderCode.OPENAI,
        allowedModelIds=("openai-advisor-model",),
        defaultModelId="openai-advisor-model",
    )


def capabilities():
    return AdvisorProviderCapabilities(
        provider=AdvisorProviderCode.OPENAI,
        supportsTextGeneration=True,
        supportsStrictJson=True,
        supportsToolCalling=False,
        supportsFunctionCalling=False,
        supportsStreaming=False,
        supportsImages=False,
        supportsFiles=False,
    )


class ProviderConfigurationTest(unittest.TestCase):
    def test_configuration_is_frozen_strict_and_stable(self):
        value = connection_config()
        serialized = value.model_dump_json()
        self.assertEqual(
            serialized,
            ProviderConnectionConfig.model_validate_json(serialized).model_dump_json(),
        )
        with self.assertRaises(ValidationError):
            connection_config(enabled=1)
        with self.assertRaises(ValidationError):
            connection_config(extra=True)
        with self.assertRaises(ValidationError):
            value.model = "changed"

    def test_configuration_boundaries_and_non_finite_values(self):
        for timeout in (
            MIN_PROVIDER_TIMEOUT_SECONDS,
            MAX_PROVIDER_TIMEOUT_SECONDS,
        ):
            self.assertEqual(
                connection_config(timeoutSeconds=timeout).timeoutSeconds, timeout
            )
        for timeout in (0.0, 121.0, math.nan, math.inf):
            with self.assertRaises(ValidationError):
                connection_config(timeoutSeconds=timeout)
        for temperature in (-0.1, 2.1, math.nan, math.inf):
            with self.assertRaises(ValidationError):
                connection_config(temperature=temperature)
        with self.assertRaises(ValidationError):
            connection_config(maxOutputTokens=MAX_PROVIDER_OUTPUT_TOKENS + 1)
        with self.assertRaises(ValidationError):
            connection_config(model=" ")

    def test_credentials_are_references_and_endpoint_rejects_auth(self):
        value = connection_config()
        rendered = repr(value) + value.model_dump_json()
        self.assertNotIn("apiKey", rendered)
        self.assertNotIn("secretValue", rendered)
        with self.assertRaises(ValidationError):
            connection_config(endpoint="https://user:secret@example.test/v1")
        with self.assertRaises(ValidationError):
            CredentialReference(credentialId=" ", source=CredentialSource.INJECTED)

    def test_unknown_and_disabled_provider_are_rejected(self):
        with self.assertRaises(ValidationError):
            connection_config(provider="UNKNOWN")
        disabled = connection_config(
            provider=ProviderName.DISABLED,
            enabled=False,
            credentialReference=None,
        )
        registry = ProviderRegistry({})
        with self.assertRaisesRegex(ValueError, "disabled"):
            registry.resolve(disabled)


class OpenAIProviderTest(unittest.TestCase):
    def adapter(self, response=None, exception=None):
        transport = DeterministicOpenAITransport(response=response, exception=exception)
        return OpenAIProviderAdapter(connection_config(), transport), transport

    def request(self):
        from backend.ai_advisor.prompt_builder import build_advisor_prompt
        from backend.ai_advisor.provider_adapter import build_provider_request
        from backend.ai_advisor.prompt_models import AdvisorPromptPolicy

        service_value = service_input()
        prompt = build_advisor_prompt(
            request=service_value.request,
            context=service_value.request.contextEnvelope,
            policy=AdvisorPromptPolicy(),
        )
        return build_provider_request(
            request=service_value.request,
            prompt_envelope=prompt,
            config=boundary_config(),
            model_policy=model_policy(),
            capabilities=capabilities(),
            provider_request_id=service_value.providerRequestId,
        )

    def test_request_mapping_response_mapping_and_single_call(self):
        adapter, transport = self.adapter(
            {"output_text": fixture_text(), "finish_reason": "completed"}
        )
        request = self.request()
        response = adapter.generate(request)
        self.assertEqual(len(transport.calls), 1)
        mapped = transport.calls[0]
        self.assertEqual(mapped.model, "openai-advisor-model")
        self.assertEqual(mapped.timeoutSeconds, 30.0)
        self.assertEqual(mapped.responseFormat, "json_object")
        self.assertIs(mapped.stream, False)
        self.assertNotIn("tools", mapped.model_dump())
        self.assertNotIn("functions", mapped.model_dump())
        self.assertEqual(response.responseText, fixture_text())

    def test_malformed_provider_responses_are_safely_rejected(self):
        for response in (None, {}, {"output_text": ""}, {"output_text": 1}):
            adapter, _ = self.adapter(response)
            with self.assertRaises(OpenAIProviderInvocationError) as caught:
                adapter.generate(self.request())
            self.assertEqual(
                caught.exception.code,
                OpenAIProviderFailureCode.MALFORMED_PROVIDER_RESPONSE,
            )

    def test_transport_failures_are_normalized_without_leakage(self):
        cases = (
            (
                OpenAITransportTimeout("fake-secret-value"),
                OpenAIProviderFailureCode.TIMEOUT,
            ),
            (
                OpenAITransportAuthenticationError("Authorization: Bearer fake-token"),
                OpenAIProviderFailureCode.AUTHENTICATION_FAILURE,
            ),
            (
                OpenAITransportRateLimitError("https://private-provider.example"),
                OpenAIProviderFailureCode.RATE_LIMITED,
            ),
            (
                OpenAITransportConnectionError("/api/private/path"),
                OpenAIProviderFailureCode.CONNECTION_FAILURE,
            ),
            (
                RuntimeError("fake-secret-value"),
                OpenAIProviderFailureCode.INTERNAL_PROVIDER_FAILURE,
            ),
        )
        for exception, code in cases:
            adapter, _ = self.adapter(exception=exception)
            with self.assertRaises(OpenAIProviderInvocationError) as caught:
                adapter.generate(self.request())
            self.assertEqual(caught.exception.code, code)
            rendered = repr(caught.exception) + str(caught.exception)
            for secret in (
                "fake-secret-value",
                "fake-token",
                "/api/private/path",
                "private-provider.example",
            ):
                self.assertNotIn(secret, rendered)

    def test_registry_is_deterministic_and_does_not_mutate_input(self):
        created = []

        def factory(config):
            adapter = OpenAIProviderAdapter(
                config,
                DeterministicOpenAITransport(response={"output_text": fixture_text()}),
            )
            created.append(adapter)
            return adapter

        factories = {ProviderName.OPENAI: factory}
        registry = ProviderRegistry(factories)
        factories.clear()
        config = connection_config()
        before = config.model_dump_json()
        self.assertIsInstance(registry.resolve(config), OpenAIProviderAdapter)
        self.assertIsInstance(registry.resolve(config), OpenAIProviderAdapter)
        self.assertEqual(config.model_dump_json(), before)
        self.assertEqual(len(created), 2)

    def test_service_end_to_end_preserves_parser_and_validator(self):
        adapter, transport = self.adapter(
            {"output_text": fixture_text(), "finish_reason": "completed"}
        )
        service = AdvisorService(
            provider=adapter,
            providerConfig=boundary_config(),
            modelPolicy=model_policy(),
            capabilities=capabilities(),
        )
        result = service.generate_response(service_input())
        self.assertEqual(result.status, AdvisorServiceStatus.SUCCEEDED)
        self.assertEqual(len(transport.calls), 1)

        malformed, _ = self.adapter({"output_text": "not json"})
        failed = AdvisorService(
            provider=malformed,
            providerConfig=boundary_config(),
            modelPolicy=model_policy(),
            capabilities=capabilities(),
        ).generate_response(service_input())
        self.assertEqual(
            failed.failure.code,
            AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE,
        )

    def test_no_implicit_io_or_nondeterministic_sources(self):
        adapter, _ = self.adapter({"output_text": fixture_text()})
        with (
            patch.object(builtins, "open", side_effect=AssertionError),
            patch.object(os, "getenv", side_effect=AssertionError),
            patch.object(socket, "socket", side_effect=AssertionError),
            patch("time.sleep", side_effect=AssertionError),
        ):
            first = adapter.generate(self.request())
            second = adapter.generate(self.request())
        self.assertEqual(first, second)
        self.assertEqual(first.model_dump_json(), second.model_dump_json())


if __name__ == "__main__":
    unittest.main()
