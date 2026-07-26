import builtins
import json
import os
import socket
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from unittest.mock import patch

from pydantic import ValidationError

from backend.ai_advisor.mock_provider import (
    MockAdvisorProvider,
    MockProviderFixture,
)
from backend.ai_advisor.provider_adapter import (
    AdvisorProvider,
    build_provider_request,
)
from backend.ai_advisor.provider_models import (
    MAX_PROVIDER_OUTPUT_CHARACTERS,
    MAX_TIMEOUT_SECONDS,
    MIN_TIMEOUT_SECONDS,
    AdvisorDisabledPolicy,
    AdvisorModelPolicy,
    AdvisorProviderCapabilities,
    AdvisorProviderCode,
    AdvisorProviderConfig,
    AdvisorProviderErrorCode,
    AdvisorProviderFailure,
    AdvisorProviderFinishReason,
    AdvisorProviderReceivedAt,
    AdvisorProviderRequest,
    AdvisorProviderResponse,
    AdvisorProviderResponseFormat,
    AdvisorRetryPolicy,
)
from backend.ai_advisor.provider_validation import validate_provider_response
from backend.ai_advisor.response_models import (
    AdvisorRawResponse,
    AdvisorResponseStatus,
)
from backend.ai_advisor.response_validation import validate_advisor_response
from tests.test_ai_advisor_response_validation import (
    candidate_payload,
    trusted_inputs,
)

NOW = datetime(2026, 7, 26, 14, tzinfo=timezone.utc)


def model_policy():
    return AdvisorModelPolicy(
        provider=AdvisorProviderCode.MOCK,
        allowedModelIds=("mock-advisor-v1",),
        defaultModelId="mock-advisor-v1",
    )


def capabilities():
    return AdvisorProviderCapabilities(
        provider=AdvisorProviderCode.MOCK,
        supportsTextGeneration=True,
        supportsStrictJson=True,
        supportsToolCalling=False,
        supportsFunctionCalling=False,
        supportsStreaming=False,
        supportsImages=False,
        supportsFiles=False,
    )


def config(**overrides):
    values = dict(
        configVersion="ai-advisor-provider-config/v1",
        provider=AdvisorProviderCode.MOCK,
        modelId="mock-advisor-v1",
        timeoutSeconds=30,
        maxOutputCharacters=MAX_PROVIDER_OUTPUT_CHARACTERS,
        retryPolicy=AdvisorRetryPolicy.NO_RETRY,
        responseFormat=AdvisorProviderResponseFormat.STRICT_JSON,
    )
    values.update(overrides)
    return AdvisorProviderConfig(**values)


def provider_request(**overrides):
    request, _, prompt = trusted_inputs()
    values = dict(
        request=request,
        prompt_envelope=prompt,
        config=config(),
        model_policy=model_policy(),
        capabilities=capabilities(),
        provider_request_id="provider-request-1",
    )
    values.update(overrides)
    return build_provider_request(**values)


def fixture_text(payload=None):
    return json.dumps(
        candidate_payload() if payload is None else payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def provider_response(
    request=None,
    *,
    finish_reason=AdvisorProviderFinishReason.COMPLETED,
    response_text=None,
):
    request = request or provider_request()
    return MockAdvisorProvider(
        MockProviderFixture(
            responseText=response_text or fixture_text(),
            finishReason=finish_reason,
        )
    ).generate(request)


class AdvisorProviderContractTest(unittest.TestCase):
    def test_config_model_policy_and_capabilities_are_closed(self):
        value = config()
        policy = model_policy()
        caps = capabilities()
        self.assertEqual(value.provider, AdvisorProviderCode.MOCK)
        self.assertEqual(value.modelId, "mock-advisor-v1")
        self.assertEqual(policy.defaultModelId, "mock-advisor-v1")
        self.assertFalse(caps.supportsToolCalling)
        self.assertFalse(caps.supportsFunctionCalling)
        self.assertFalse(caps.supportsStreaming)
        self.assertFalse(caps.supportsFiles)
        self.assertFalse(caps.supportsImages)
        for overrides in (
            {"provider": "UNKNOWN"},
            {"modelId": "unknown-model"},
            {"configVersion": "v2"},
            {"extra": True},
        ):
            with self.assertRaises(ValidationError):
                config(**overrides)

    def test_model_allowlist_rejects_unknown_duplicate_and_default_mismatch(self):
        invalid = (
            {
                "provider": AdvisorProviderCode.MOCK,
                "allowedModelIds": ("unknown",),
                "defaultModelId": "mock-advisor-v1",
            },
            {
                "provider": AdvisorProviderCode.MOCK,
                "allowedModelIds": ("mock-advisor-v1", "mock-advisor-v1"),
                "defaultModelId": "mock-advisor-v1",
            },
        )
        for payload in invalid:
            with self.assertRaises(ValidationError):
                AdvisorModelPolicy(**payload)

    def test_timeout_strict_boundaries(self):
        for value in (MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS):
            self.assertEqual(config(timeoutSeconds=value).timeoutSeconds, value)
        for value in (
            MIN_TIMEOUT_SECONDS - 1,
            MAX_TIMEOUT_SECONDS + 1,
            1.0,
            True,
            "1",
        ):
            with self.assertRaises(ValidationError):
                config(timeoutSeconds=value)

    def test_output_character_boundaries(self):
        for value in (1, MAX_PROVIDER_OUTPUT_CHARACTERS):
            self.assertEqual(
                config(maxOutputCharacters=value).maxOutputCharacters,
                value,
            )
        with self.assertRaises(ValidationError):
            config(maxOutputCharacters=0)
        with self.assertRaises(ValidationError):
            config(maxOutputCharacters=MAX_PROVIDER_OUTPUT_CHARACTERS + 1)

    def test_request_is_exact_prompt_binding_with_disabled_capabilities(self):
        request, _, prompt = trusted_inputs()
        result = provider_request()
        from backend.ai_advisor.prompt_builder import render_advisor_prompt

        self.assertEqual(result.requestId, request.requestId)
        self.assertEqual(result.promptVersion, prompt.promptVersion)
        self.assertEqual(result.renderedPrompt, render_advisor_prompt(prompt))
        self.assertEqual(
            result.toolCallingPolicy,
            AdvisorDisabledPolicy.DISABLED,
        )
        self.assertEqual(
            result.functionCallingPolicy,
            AdvisorDisabledPolicy.DISABLED,
        )
        self.assertEqual(result.streamingPolicy, AdvisorDisabledPolicy.DISABLED)
        self.assertEqual(result.retryPolicy, AdvisorRetryPolicy.NO_RETRY)

    def test_request_binding_and_capability_bypass_fail_closed(self):
        request, _, prompt = trusted_inputs()
        wrong_prompt = prompt.model_copy(update={"requestId": "wrong"})
        with self.assertRaises(ValueError):
            provider_request(prompt_envelope=wrong_prompt)
        bad_caps = capabilities().model_copy(update={"supportsToolCalling": True})
        with self.assertRaises(ValueError):
            provider_request(capabilities=bad_caps)
        bad_config = config().model_copy(update={"retryPolicy": "RETRY"})
        with self.assertRaises(ValueError):
            provider_request(config=bad_config)
        changed_request = request.model_copy(update={"requestId": "wrong"})
        with self.assertRaises(ValueError):
            build_provider_request(
                request=changed_request,
                prompt_envelope=prompt,
                config=config(),
                model_policy=model_policy(),
                capabilities=capabilities(),
                provider_request_id="provider-request-1",
            )

    def test_request_and_response_extra_action_fields_are_rejected(self):
        request_payload = provider_request().model_dump()
        response_payload = provider_response().model_dump()
        for field in (
            "toolCalls",
            "functionCalls",
            "requiredAction",
            "commands",
            "actions",
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    AdvisorProviderRequest.model_validate(
                        {**request_payload, field: ()}
                    )
                with self.assertRaises(ValidationError):
                    AdvisorProviderResponse.model_validate(
                        {**response_payload, field: ()}
                    )

    def test_mock_provider_is_protocol_deterministic_and_non_mutating(self):
        request = provider_request()
        fixture = MockProviderFixture(responseText=fixture_text())
        provider = MockAdvisorProvider(fixture)
        self.assertIsInstance(provider, AdvisorProvider)
        before = request.model_dump_json()
        first = provider.generate(request)
        second = provider.generate(request)
        self.assertEqual(first, second)
        self.assertEqual(first.model_dump_json(), second.model_dump_json())
        self.assertEqual(request.model_dump_json(), before)
        with self.assertRaises(FrozenInstanceError):
            fixture.responseText = "changed"
        with self.assertRaises(ValidationError):
            first.responseText = "changed"

    def test_provider_response_metadata_binding(self):
        request = provider_request()
        base = provider_response(request)
        attacks = (
            {"providerRequestId": "wrong"},
            {"requestId": "wrong"},
            {"promptVersion": "wrong"},
            {"modelId": "wrong"},
        )
        for attack in attacks:
            result = validate_provider_response(
                request=request,
                response=base.model_copy(update=attack),
                capabilities=capabilities(),
                received_at=AdvisorProviderReceivedAt(value=NOW),
            )
            self.assertIsInstance(result, AdvisorProviderFailure)
            self.assertFalse(result.retryAllowed)
            self.assertNotIn("wrong", result.safeMessage)
        with self.assertRaises(ValueError) as raised:
            validate_provider_response(
                request=request,
                response=base.model_copy(update={"provider": "OPENAI"}),
                capabilities=capabilities(),
                received_at=AdvisorProviderReceivedAt(value=NOW),
            )
        self.assertEqual(
            str(raised.exception),
            "advisor provider response validation failed",
        )

    def test_finish_reason_mapping_never_passes_incomplete_text(self):
        request = provider_request()
        expected = {
            AdvisorProviderFinishReason.OUTPUT_LIMIT: (
                AdvisorProviderErrorCode.INCOMPLETE_RESPONSE
            ),
            AdvisorProviderFinishReason.CONTENT_FILTERED: (
                AdvisorProviderErrorCode.CONTENT_FILTERED
            ),
            AdvisorProviderFinishReason.PROVIDER_ERROR: (
                AdvisorProviderErrorCode.PROVIDER_UNAVAILABLE
            ),
            AdvisorProviderFinishReason.CANCELLED: (
                AdvisorProviderErrorCode.INCOMPLETE_RESPONSE
            ),
            AdvisorProviderFinishReason.UNKNOWN: (
                AdvisorProviderErrorCode.INCOMPLETE_RESPONSE
            ),
        }
        for reason, code in expected.items():
            response = provider_response(request, finish_reason=reason)
            result = validate_provider_response(
                request=request,
                response=response,
                capabilities=capabilities(),
                received_at=AdvisorProviderReceivedAt(value=NOW),
            )
            self.assertIsInstance(result, AdvisorProviderFailure)
            self.assertEqual(result.errorCode, code)
            self.assertNotIn(response.responseText, result.model_dump_json())

    def test_completed_response_converts_to_raw_with_explicit_time(self):
        request = provider_request()
        response = provider_response(request)
        result = validate_provider_response(
            request=request,
            response=response,
            capabilities=capabilities(),
            received_at=AdvisorProviderReceivedAt(value=NOW),
        )
        self.assertIsInstance(result, AdvisorRawResponse)
        self.assertEqual(result.requestId, request.requestId)
        self.assertEqual(result.promptVersion, request.promptVersion)
        self.assertEqual(result.responseText, response.responseText)
        self.assertEqual(result.receivedAt, NOW)
        with self.assertRaises(ValidationError):
            AdvisorProviderReceivedAt(value=datetime(2026, 1, 1))

    def test_provider_output_too_large_returns_safe_failure(self):
        request = provider_request(
            config=config(maxOutputCharacters=10),
        )
        response = provider_response(request, response_text="x" * 11)
        result = validate_provider_response(
            request=request,
            response=response,
            capabilities=capabilities(),
            received_at=AdvisorProviderReceivedAt(value=NOW),
        )
        self.assertEqual(
            result.errorCode,
            AdvisorProviderErrorCode.OUTPUT_TOO_LARGE,
        )
        self.assertNotIn("x" * 11, result.model_dump_json())

    def test_provider_failure_is_frozen_fixed_and_serializable(self):
        failure = AdvisorProviderFailure(
            errorCode=AdvisorProviderErrorCode.PROVIDER_UNAVAILABLE,
            safeMessage="advisor provider unavailable",
            retryAllowed=False,
        )
        from_json = AdvisorProviderFailure.model_validate_json(
            failure.model_dump_json()
        )
        from_dict = AdvisorProviderFailure.model_validate(failure.model_dump())
        self.assertEqual(from_json, failure)
        self.assertEqual(from_dict, failure)
        with self.assertRaises(ValidationError):
            failure.retryAllowed = True
        with self.assertRaises(ValidationError):
            AdvisorProviderFailure(
                errorCode=AdvisorProviderErrorCode.PROVIDER_UNAVAILABLE,
                safeMessage="raw provider detail",
                retryAllowed=False,
            )

    def test_all_provider_models_round_trip(self):
        request = provider_request()
        response = provider_response(request)
        values = (
            config(),
            model_policy(),
            capabilities(),
            request,
            response,
            AdvisorProviderReceivedAt(value=NOW),
        )
        for value in values:
            model_type = type(value)
            self.assertEqual(
                model_type.model_validate_json(value.model_dump_json()),
                value,
            )
            self.assertEqual(model_type.model_validate(value.model_dump()), value)
            with self.assertRaises(ValidationError):
                value.model_config = {}

    def test_end_to_end_mock_boundary_valid_and_hostile_responses(self):
        advisor_request, context, prompt = trusted_inputs()
        request = provider_request()
        payloads = (
            (candidate_payload(), AdvisorResponseStatus.VALID_WITH_WARNINGS),
            ({"broken": True}, AdvisorResponseStatus.REJECTED),
            (
                {
                    **candidate_payload(),
                    "sourceReferences": ["fabricated-source"],
                    "freshnessDisclosures": [
                        {
                            "sourceId": "fabricated-source",
                            "freshness": "FRESH",
                        }
                    ],
                },
                AdvisorResponseStatus.REJECTED,
            ),
            (
                {
                    **candidate_payload(),
                    "summary": "I executed the trade.",
                },
                AdvisorResponseStatus.REJECTED,
            ),
            (
                {
                    **candidate_payload(),
                    "summary": "api_key=BOUNDARY_SECRET",
                },
                AdvisorResponseStatus.REJECTED,
            ),
            (
                {
                    **candidate_payload(),
                    "summary": "/home/user/private.txt",
                },
                AdvisorResponseStatus.REJECTED,
            ),
        )
        for payload, expected_status in payloads:
            response = provider_response(
                request,
                response_text=fixture_text(payload),
            )
            raw_response = validate_provider_response(
                request=request,
                response=response,
                capabilities=capabilities(),
                received_at=AdvisorProviderReceivedAt(value=NOW),
            )
            result = validate_advisor_response(
                raw_response=raw_response,
                request=advisor_request,
                context=context,
                prompt_envelope=prompt,
            )
            self.assertEqual(result.status, expected_status)
            self.assertNotIn("BOUNDARY_SECRET", result.model_dump_json())

        malformed_response = provider_response(request, response_text="{")
        malformed_raw = validate_provider_response(
            request=request,
            response=malformed_response,
            capabilities=capabilities(),
            received_at=AdvisorProviderReceivedAt(value=NOW),
        )
        malformed_result = validate_advisor_response(
            raw_response=malformed_raw,
            request=advisor_request,
            context=context,
            prompt_envelope=prompt,
        )
        self.assertEqual(
            malformed_result.status,
            AdvisorResponseStatus.REJECTED,
        )

    def test_side_effect_freedom_and_determinism(self):
        request = provider_request()
        provider = MockAdvisorProvider(MockProviderFixture(responseText=fixture_text()))
        with (
            patch.object(builtins, "open", side_effect=AssertionError("open")),
            patch.object(os, "getenv", side_effect=AssertionError("environment")),
            patch.object(socket, "socket", side_effect=AssertionError("network")),
        ):
            responses = tuple(provider.generate(request) for _ in range(3))
            results = tuple(
                validate_provider_response(
                    request=request,
                    response=response,
                    capabilities=capabilities(),
                    received_at=AdvisorProviderReceivedAt(value=NOW),
                )
                for response in responses
            )
        self.assertEqual(responses, (responses[0],) * 3)
        self.assertEqual(results, (results[0],) * 3)


if __name__ == "__main__":
    unittest.main()
