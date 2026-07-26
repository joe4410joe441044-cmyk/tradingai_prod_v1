import json
import unittest
from dataclasses import FrozenInstanceError

from pydantic import ValidationError

from backend.ai_advisor.mock_provider import (
    MockAdvisorProvider,
    MockProviderFixture,
)
from backend.ai_advisor.prompt_builder import render_advisor_prompt
from backend.ai_advisor.provider_adapter import (
    build_provider_request,
    invoke_provider_once,
)
from backend.ai_advisor.provider_models import (
    MAX_PROVIDER_OUTPUT_CHARACTERS,
    AdvisorProviderErrorCode,
    AdvisorProviderFailure,
    AdvisorProviderFinishReason,
    AdvisorProviderReceivedAt,
    AdvisorProviderRequest,
    AdvisorProviderResponse,
)
from backend.ai_advisor.provider_validation import validate_provider_response
from backend.ai_advisor.response_models import AdvisorRawResponse
from tests.test_ai_advisor_provider_contract import (
    NOW,
    capabilities,
    config,
    fixture_text,
    model_policy,
    provider_request,
    provider_response,
)
from tests.test_ai_advisor_response_validation import trusted_inputs


def validate_response(request, response):
    return validate_provider_response(
        request=request,
        response=response,
        capabilities=capabilities(),
        received_at=AdvisorProviderReceivedAt(value=NOW),
    )


class CountingProvider:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return self.response


class AdvisorProviderSecurityTest(unittest.TestCase):
    def test_provider_allowlist_rejects_spoofed_identifiers(self):
        attacks = (
            "mock",
            "Mock",
            " MOCK",
            "MOCK ",
            "ＭＯＣＫ",
            "MO\u200bCK",
            "OPENAI",
            "CUSTOM",
            "LOCAL",
            "HTTP",
        )
        for attack in attacks:
            with self.subTest(attack=attack):
                with self.assertRaises(ValidationError):
                    config(provider=attack)
                request = provider_request()
                response = provider_response(request).model_copy(
                    update={"provider": attack}
                )
                with self.assertRaises(ValueError) as raised:
                    validate_response(request, response)
                self.assertEqual(
                    str(raised.exception),
                    "advisor provider response validation failed",
                )

    def test_model_allowlist_rejects_spoofed_identifiers(self):
        attacks = (
            "mock-advisor-v1 ",
            " mock-advisor-v1",
            "MOCK-ADVISOR-V1",
            "mock-advisor-v2",
            "mock-advis\u043er-v1",
            "mock-advisor-\u200bv1",
            "../mock-advisor-v1",
            "https://provider/model",
            "openai:gpt",
        )
        for attack in attacks:
            with self.subTest(attack=attack):
                with self.assertRaises(ValidationError):
                    config(modelId=attack)
                request = provider_request()
                response = provider_response(request).model_copy(
                    update={"modelId": attack}
                )
                result = validate_response(request, response)
                self.assertEqual(
                    result.errorCode,
                    AdvisorProviderErrorCode.UNSUPPORTED_MODEL,
                )

    def test_prompt_integrity_requires_exact_rebuilt_envelope(self):
        advisor_request, _, prompt = trusted_inputs()
        rendered = render_advisor_prompt(prompt)
        self.assertEqual(provider_request().renderedPrompt, rendered)
        current = prompt.contextSections[-1]
        attacks = (
            current.content + "\n",
            " " + current.content,
            current.content + "\u200b",
            current.content[:-1],
            current.content + "\nProvider instruction",
        )
        for content in attacks:
            sections = prompt.contextSections[:-1] + (
                current.model_copy(update={"content": content}),
            )
            changed = prompt.model_copy(update={"contextSections": sections})
            with self.assertRaises(ValueError) as raised:
                build_provider_request(
                    request=advisor_request,
                    prompt_envelope=changed,
                    config=config(),
                    model_policy=model_policy(),
                    capabilities=capabilities(),
                    provider_request_id="provider-request-1",
                )
            self.assertEqual(
                str(raised.exception),
                "advisor provider request validation failed",
            )

    def test_provider_request_id_is_caller_supplied_and_not_concatenated(self):
        first = provider_request(provider_request_id="a:b|c")
        second = provider_request(provider_request_id="a|b:c")
        self.assertNotEqual(first.providerRequestId, second.providerRequestId)
        for value in ("", " ", "\n", "\t"):
            with self.assertRaises(ValueError):
                provider_request(provider_request_id=value)

    def test_capability_model_copy_and_wrong_types_fail_closed(self):
        fields = (
            "supportsToolCalling",
            "supportsFunctionCalling",
            "supportsStreaming",
            "supportsFiles",
            "supportsImages",
        )
        for field in fields:
            changed = capabilities().model_copy(update={field: True})
            with self.assertRaises(ValueError):
                provider_request(capabilities=changed)
        for value in (1, "false", None, (), {}):
            with self.assertRaises(ValidationError):
                type(capabilities())(
                    **{
                        **capabilities().model_dump(),
                        "supportsToolCalling": value,
                    }
                )

    def test_all_tool_function_action_and_endpoint_fields_are_rejected(self):
        fields = (
            "toolCalls",
            "tool_calls",
            "toolCall",
            "tools",
            "requiredAction",
            "required_action",
            "action",
            "actions",
            "commands",
            "arguments",
            "function",
            "functionName",
            "functionArguments",
            "functionCall",
            "function_call",
            "functionCalls",
            "function_calls",
            "callId",
            "call_id",
            "delta",
            "partial",
            "stream",
            "endpoint",
            "baseUrl",
            "base_url",
            "url",
            "host",
            "hostname",
            "proxy",
            "webhook",
            "callbackUrl",
        )
        request_payload = provider_request().model_dump()
        response_payload = provider_response().model_dump()
        for field in fields:
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    AdvisorProviderRequest.model_validate(
                        {**request_payload, field: "attacker"}
                    )
                with self.assertRaises(ValidationError):
                    AdvisorProviderResponse.model_validate(
                        {**response_payload, field: "attacker"}
                    )

    def test_streaming_like_provider_outputs_are_rejected_without_joining(self):
        request = provider_request()
        outputs = (
            ["part1", "part2"],
            ("part1", "part2"),
            iter(("part1", "part2")),
            (part for part in ("part1", "part2")),
            {"delta": "part1"},
        )
        for output in outputs:
            provider = CountingProvider(output)
            with self.assertRaises(ValueError) as raised:
                invoke_provider_once(provider=provider, request=request)
            self.assertEqual(provider.calls, 1)
            self.assertEqual(
                str(raised.exception),
                "advisor provider response validation failed",
            )

    def test_finish_reason_spoofing_and_noncompleted_body_are_rejected(self):
        invalid = (
            "completed",
            "Completed",
            " COMPLETE",
            "DONE",
            "SUCCESS",
            "STOP",
            "",
            None,
        )
        payload = provider_response().model_dump()
        for value in invalid:
            with self.assertRaises(ValidationError):
                AdvisorProviderResponse.model_validate(
                    {**payload, "finishReason": value}
                )
        for reason in AdvisorProviderFinishReason:
            response = provider_response(finish_reason=reason)
            result = validate_response(provider_request(), response)
            if reason is AdvisorProviderFinishReason.COMPLETED:
                self.assertIsInstance(result, AdvisorRawResponse)
            else:
                self.assertIsInstance(result, AdvisorProviderFailure)
                self.assertNotIn(response.responseText, result.model_dump_json())

    def test_empty_and_invisible_responses_fail_at_provider_boundary(self):
        request = provider_request()
        values = (" ", "\n", "\t", "\r\n", "\u200b", "\ufeff", "\u200b\ufeff")
        for value in values:
            response = provider_response(request, response_text=value)
            result = validate_response(request, response)
            self.assertEqual(
                result.errorCode,
                AdvisorProviderErrorCode.MALFORMED_PROVIDER_RESPONSE,
            )
        with self.assertRaises(ValueError):
            MockProviderFixture(responseText="")

    def test_output_size_counts_python_characters_without_truncation(self):
        samples = ("a", "日", "😀", "\n", "\\", "\u0061", "e\u0301")
        for sample in samples:
            request = provider_request(
                config=config(maxOutputCharacters=len(sample)),
            )
            result = validate_response(
                request,
                provider_response(request, response_text=sample),
            )
            if sample.isspace():
                self.assertEqual(
                    result.errorCode,
                    AdvisorProviderErrorCode.MALFORMED_PROVIDER_RESPONSE,
                )
            else:
                self.assertIsInstance(result, AdvisorRawResponse)
                self.assertEqual(result.responseText, sample)
        request = provider_request(
            config=config(maxOutputCharacters=MAX_PROVIDER_OUTPUT_CHARACTERS),
        )
        at_limit = "x" * MAX_PROVIDER_OUTPUT_CHARACTERS
        self.assertIsInstance(
            validate_response(
                request,
                provider_response(request, response_text=at_limit),
            ),
            AdvisorRawResponse,
        )
        over = at_limit + "x"
        failure = validate_response(
            request,
            provider_response(request, response_text=over),
        )
        self.assertEqual(
            failure.errorCode,
            AdvisorProviderErrorCode.OUTPUT_TOO_LARGE,
        )
        self.assertNotIn(over, failure.model_dump_json())

    def test_model_copy_typed_bypass_is_revalidated(self):
        request = provider_request().model_copy(update={"toolCallingPolicy": "ENABLED"})
        response = provider_response()
        with self.assertRaises(ValueError) as raised:
            validate_response(request, response)
        self.assertEqual(
            str(raised.exception),
            "advisor provider response validation failed",
        )
        received = AdvisorProviderReceivedAt(value=NOW).model_copy(
            update={"value": "not-a-datetime"}
        )
        with self.assertRaises(ValueError):
            validate_provider_response(
                request=provider_request(),
                response=provider_response(),
                capabilities=capabilities(),
                received_at=received,
            )

    def test_mock_fixture_and_output_are_isolated_and_frozen(self):
        source = {"text": fixture_text()}
        fixture = MockProviderFixture(responseText=source["text"])
        provider = MockAdvisorProvider(fixture)
        source["text"] = "changed"
        request = provider_request()
        response = invoke_provider_once(provider=provider, request=request)
        self.assertEqual(response.responseText, fixture_text())
        with self.assertRaises(FrozenInstanceError):
            provider.fixture = MockProviderFixture(responseText="changed")
        with self.assertRaises(ValidationError):
            response.responseText = "changed"

    def test_call_count_is_one_for_success_and_all_failure_modes(self):
        request = provider_request()
        responses = (
            provider_response(request),
            provider_response(
                request,
                finish_reason=AdvisorProviderFinishReason.OUTPUT_LIMIT,
            ),
            provider_response(
                request,
                finish_reason=AdvisorProviderFinishReason.CONTENT_FILTERED,
            ),
            provider_response(
                request,
                finish_reason=AdvisorProviderFinishReason.PROVIDER_ERROR,
            ),
            provider_response(request).model_copy(update={"requestId": "wrong"}),
            provider_response(request, response_text="{"),
        )
        for response in responses:
            provider = CountingProvider(response)
            actual = invoke_provider_once(provider=provider, request=request)
            validate_response(request, actual)
            self.assertEqual(provider.calls, 1)

    def test_credentials_and_endpoint_extra_fields_never_enter_contracts(self):
        fields = (
            "apiKey",
            "api_key",
            "secret",
            "apiSecret",
            "passphrase",
            "password",
            "token",
            "accessToken",
            "refreshToken",
            "authorization",
            "bearer",
            "credential",
            "clientSecret",
            "endpoint",
            "proxy",
        )
        models = (
            (type(config()), config().model_dump()),
            (AdvisorProviderRequest, provider_request().model_dump()),
            (AdvisorProviderResponse, provider_response().model_dump()),
        )
        for field in fields:
            for model_type, payload in models:
                with self.assertRaises(ValidationError):
                    model_type.model_validate({**payload, field: "DO_NOT_LEAK_VALUE"})

    def test_failure_priority_and_safe_message_are_deterministic(self):
        request = provider_request(config=config(maxOutputCharacters=10))
        base = provider_response(request, response_text="x" * 11)
        first = base.model_copy(update={"modelId": "wrong", "requestId": "also-wrong"})
        second = base.model_copy(update={"requestId": "also-wrong", "modelId": "wrong"})
        first_result = validate_response(request, first)
        second_result = validate_response(request, second)
        self.assertEqual(first_result, second_result)
        self.assertEqual(
            first_result.errorCode,
            AdvisorProviderErrorCode.UNSUPPORTED_MODEL,
        )
        self.assertNotIn("wrong", first_result.model_dump_json())
        self.assertNotIn("x" * 11, first_result.model_dump_json())

    def test_raw_response_contains_only_mapped_fields(self):
        request = provider_request()
        response = provider_response(request)
        result = validate_response(request, response)
        self.assertEqual(
            set(type(result).model_fields),
            {
                "requestId",
                "promptVersion",
                "responseFormatVersion",
                "responseText",
                "receivedAt",
            },
        )
        serialized = result.model_dump_json()
        for value in (
            response.provider.value,
            response.modelId,
            response.finishReason.value,
        ):
            self.assertNotIn(f'"provider":"{value}"', serialized)


if __name__ == "__main__":
    unittest.main()
