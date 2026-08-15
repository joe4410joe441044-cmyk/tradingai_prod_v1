import builtins
import json
import os
import socket
import unittest
from dataclasses import FrozenInstanceError
from datetime import timedelta
from unittest.mock import patch

from pydantic import ValidationError

from backend.ai_advisor.context_builder import SpecificationSourceInput
from backend.ai_advisor.conversation_models import AuthorizationState
from backend.ai_advisor.mock_provider import (
    MockAdvisorProvider,
    MockProviderFixture,
)
from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.provider_failure_observation import (
    ProviderFailureStage,
    RecordingProviderFailureObservationSink,
    ResponseTopLevelType,
    ResponseValidationCode,
)
from backend.ai_advisor.service_models import (
    AdvisorServiceContextInput,
    AdvisorServiceFailureCode,
    AdvisorServiceInput,
    AdvisorServiceResult,
    AdvisorServiceStatus,
)
from backend.ai_advisor.response_safety_observation import (
    OperationalIntentClassification,
    RecordingResponseSafetyRejectionObservationSink,
    ResponseGroundingClassification,
    ResponseSafetyRejectionRule,
    ResponseSafetyViolationCategory,
)
from tests.test_ai_advisor_prompt_builder import (
    NOW,
    conversation,
    make_request,
    runtime,
)
from tests.test_ai_advisor_provider_contract import (
    capabilities,
    config,
    fixture_text,
    model_policy,
)
from tests.test_ai_advisor_response_validation import candidate_payload


def context_input(**overrides):
    values = dict(
        generatedAt=NOW,
        runtime=runtime(),
        runtimeSourceId="advisor-runtime",
        specifications=(
            SpecificationSourceInput(
                sourceId="spec-b",
                sourceVersion="1.1",
                title="Specification B",
                documentPath="docs/ai_advisor/b.md",
                loadedAt=NOW,
                approved=True,
            ),
            SpecificationSourceInput(
                sourceId="spec-a",
                sourceVersion="1.0",
                title="Specification A",
                documentPath="docs/ai_advisor/a.md",
                loadedAt=NOW,
                approved=True,
            ),
        ),
        conversationHistory=(
            conversation("message-a", "Earlier question", 2),
            conversation("message-b", "Later question", 1),
        ),
    )
    values.update(overrides)
    return AdvisorServiceContextInput(**values)


def service_input(request=None, **overrides):
    request = request or make_request()[0]
    values = dict(
        request=request,
        contextInput=context_input(),
        providerRequestId="provider-request-1",
        receivedAt=NOW,
    )
    values.update(overrides)
    return AdvisorServiceInput(**values)


def service(
    response_text=None,
    provider=None,
    provider_config=None,
    failure_sink=None,
    response_safety_sink=None,
):
    provider = provider or MockAdvisorProvider(
        MockProviderFixture(responseText=response_text or fixture_text())
    )
    return AdvisorService(
        provider=provider,
        providerConfig=provider_config or config(),
        modelPolicy=model_policy(),
        capabilities=capabilities(),
        **(
            {"failureObservationSink": failure_sink}
            if failure_sink is not None
            else {}
        ),
        **(
            {"responseSafetyObservationSink": response_safety_sink}
            if response_safety_sink is not None
            else {}
        ),
    )


class RaisingProvider:
    def generate(self, request):
        raise RuntimeError(
            "api_key=SERVICE_SECRET /home/user/private endpoint=https://bad"
        )


class WrongMetadataProvider:
    def __init__(self):
        self.delegate = MockAdvisorProvider(
            MockProviderFixture(responseText=fixture_text())
        )

    def generate(self, request):
        return self.delegate.generate(request).model_copy(
            update={"requestId": "wrong-request"}
        )


class AdvisorServiceTest(unittest.TestCase):
    def test_normal_end_to_end_returns_typed_response(self):
        result = service().generate_response(service_input())
        self.assertEqual(result.status, AdvisorServiceStatus.SUCCEEDED)
        self.assertIsNotNone(result.response)
        self.assertIsNone(result.failure)

    def test_safe_rejected_advisor_response_is_service_success(self):
        payload = candidate_payload()
        payload["summary"] = "I executed the trade."
        result = service(fixture_text(payload)).generate_response(service_input())
        self.assertEqual(result.status, AdvisorServiceStatus.SUCCEEDED)
        self.assertEqual(result.response.status.value, "REJECTED")

    def test_advisory_rejection_observation_is_bounded_and_content_free(self):
        sink = RecordingResponseSafetyRejectionObservationSink()
        payload = candidate_payload()
        payload["summary"] = "Submit this order now."
        result = service(
            fixture_text(payload),
            response_safety_sink=sink,
        ).generate_response(service_input())
        self.assertEqual(result.response.status.value, "REJECTED")
        self.assertEqual(len(sink.records), 1)
        observation = sink.records[0]
        self.assertEqual(observation.rejectionCode.value, "ORDER_ACTION_CLAIM")
        self.assertIs(
            observation.rejectionRule,
            ResponseSafetyRejectionRule.ORDER_ACTION_PATTERN,
        )
        self.assertIs(
            observation.violationCategory,
            ResponseSafetyViolationCategory.OPERATIONAL_ACTION,
        )
        self.assertIs(
            observation.operationalIntent,
            OperationalIntentClassification.ACTION_OR_EXECUTION,
        )
        self.assertIs(
            observation.groundingClassification,
            ResponseGroundingClassification.NOT_APPLICABLE,
        )
        rendered = observation.model_dump_json()
        for forbidden in (
            "Submit this order",
            "responseText",
            "api_key",
            "Authorization",
            "cookie",
        ):
            self.assertNotIn(forbidden, rendered)
        with self.assertRaises(ValidationError):
            type(observation).model_validate(
                {**observation.model_dump(), "requestId": "api_key=SECRET"}
            )

    def test_conversation_failure_mapping(self):
        request, _ = make_request()
        denied = request.permissionContext.model_copy(
            update={"authorizationState": AuthorizationState.DENIED}
        )
        changed = request.model_copy(update={"permissionContext": denied})
        result = service().generate_response(service_input(request=changed))
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_INVALID_CONVERSATION,
        )

    def test_context_failure_mapping_and_provider_not_called(self):
        class CountingProvider:
            calls = 0

            def generate(self, request):
                self.calls += 1
                raise AssertionError("provider must not be called")

        provider = CountingProvider()
        changed_context = context_input(generatedAt=NOW + timedelta(seconds=1))
        result = service(provider=provider).generate_response(
            service_input(contextInput=changed_context)
        )
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_CONTEXT_INVALID,
        )
        self.assertEqual(provider.calls, 0)

        bypassed_context = context_input().model_copy(
            update={"generatedAt": "not-a-datetime"}
        )
        bypassed_input = service_input().model_copy(
            update={"contextInput": bypassed_context}
        )
        bypassed_result = service().generate_response(bypassed_input)
        self.assert_failure(
            bypassed_result,
            AdvisorServiceFailureCode.ADVISOR_CONTEXT_INVALID,
        )

    def test_prompt_failure_mapping(self):
        request, _ = make_request(message="api_key=PROMPT_SECRET_VALUE")
        result = service().generate_response(service_input(request=request))
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_PROMPT_INVALID,
        )
        self.assertNotIn("PROMPT_SECRET_VALUE", result.model_dump_json())

    def test_provider_request_failure_mapping(self):
        bad_config = config().model_copy(update={"retryPolicy": "RETRY"})
        result = service(provider_config=bad_config).generate_response(service_input())
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_PROVIDER_REQUEST_INVALID,
        )

    def test_provider_invocation_failure_is_redacted(self):
        result = service(provider=RaisingProvider()).generate_response(service_input())
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE,
        )
        serialized = result.model_dump_json()
        for secret in ("SERVICE_SECRET", "/home/user/private", "https://bad"):
            self.assertNotIn(secret, serialized)

    def test_provider_validation_failure_mapping(self):
        result = service(provider=WrongMetadataProvider()).generate_response(
            service_input()
        )
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_PROVIDER_FAILURE,
        )

    def test_provider_response_exception_mapping(self):
        with patch(
            "backend.ai_advisor.advisor_service.validate_provider_response",
            side_effect=ValueError("raw provider metadata"),
        ):
            result = service().generate_response(service_input())
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_PROVIDER_RESPONSE_INVALID,
        )
        self.assertNotIn("raw provider metadata", result.model_dump_json())

    def test_parser_failure_mapping_without_json_repair(self):
        sink = RecordingProviderFailureObservationSink()
        result = service("{", failure_sink=sink).generate_response(service_input())
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE,
        )
        observation = sink.observation
        self.assertIsNotNone(observation)
        self.assertEqual(
            observation.failureStage,
            ProviderFailureStage.RESPONSE_VALIDATION,
        )
        self.assertFalse(observation.parseSucceeded)
        self.assertEqual(
            observation.validationCode,
            ResponseValidationCode.JSON_DECODE_FAILED,
        )
        self.assertEqual(
            observation.topLevelType,
            ResponseTopLevelType.UNKNOWN,
        )
        self.assertEqual(observation.httpStatus, 502)
        rendered = observation.model_dump_json()
        self.assertNotIn("responseText", rendered)
        self.assertNotIn("rawResponse", rendered)

    def test_semantic_rejection_does_not_emit_parser_observation(self):
        sink = RecordingProviderFailureObservationSink()
        payload = candidate_payload()
        payload["summary"] = "I executed the trade."
        result = service(
            fixture_text(payload),
            failure_sink=sink,
        ).generate_response(service_input())
        self.assertEqual(result.status, AdvisorServiceStatus.SUCCEEDED)
        self.assertEqual(result.response.status.value, "REJECTED")
        self.assertIsNone(sink.observation)

    def test_parser_observation_sink_failure_preserves_safe_failure(self):
        class RaisingSink:
            def observe(self, observation):
                raise RuntimeError("sk-test-sink-secret")

        result = service("{", failure_sink=RaisingSink()).generate_response(
            service_input()
        )
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_PARSE_FAILURE,
        )
        self.assertNotIn("sk-test-sink-secret", result.model_dump_json())

    def test_response_validation_exception_mapping(self):
        with patch(
            "backend.ai_advisor.advisor_service.validate_advisor_response",
            side_effect=ValueError("raw response validation detail"),
        ):
            result = service().generate_response(service_input())
        self.assert_failure(
            result,
            AdvisorServiceFailureCode.ADVISOR_RESPONSE_INVALID,
        )
        self.assertNotIn(
            "raw response validation detail",
            result.model_dump_json(),
        )

    def test_context_and_request_are_reference_only(self):
        value = service_input()
        before = value.model_dump_json()
        service().generate_response(value)
        self.assertEqual(value.model_dump_json(), before)

    def test_result_contract_is_frozen_and_round_trips(self):
        result = service().generate_response(service_input())
        from_json = AdvisorServiceResult.model_validate_json(result.model_dump_json())
        from_dict = AdvisorServiceResult.model_validate(result.model_dump())
        self.assertEqual(from_json, result)
        self.assertEqual(from_dict, result)
        with self.assertRaises(ValidationError):
            result.status = AdvisorServiceStatus.FAILED
        with self.assertRaises(FrozenInstanceError):
            service().providerConfig = config()

    def test_determinism(self):
        value = service_input()
        results = tuple(service().generate_response(value) for _ in range(3))
        self.assertEqual(results, (results[0],) * 3)
        self.assertEqual(
            tuple(item.model_dump_json() for item in results),
            (results[0].model_dump_json(),) * 3,
        )

    def test_no_side_effect(self):
        with (
            patch.object(builtins, "open", side_effect=AssertionError("open")),
            patch.object(os, "getenv", side_effect=AssertionError("environment")),
            patch.object(socket, "socket", side_effect=AssertionError("network")),
        ):
            result = service().generate_response(service_input())
        self.assertEqual(result.status, AdvisorServiceStatus.SUCCEEDED)

    def assert_failure(self, result, code):
        self.assertEqual(result.status, AdvisorServiceStatus.FAILED)
        self.assertIsNone(result.response)
        self.assertIsNotNone(result.failure)
        self.assertEqual(result.failure.code, code)
        self.assertFalse(result.failure.retryAllowed)


if __name__ == "__main__":
    unittest.main()
