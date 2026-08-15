"""Offline SDK 2.48.0-shaped response contract regression for the transport.

These tests build real ``openai.types.responses.Response`` objects from the
installed SDK and exercise the transport response-validation path without any
network access. No real provider request is performed.
"""

import unittest

from backend.ai_advisor.provider_failure_observation import (
    ProviderFailureStage,
    ProviderSafeReason,
    RecordingProviderFailureObservationSink,
)
from backend.ai_advisor.provider_transport import OpenAITransportRejectedError
from tests.test_ai_advisor_openai_sdk_transport import (
    FakeResponse,
    request,
    transport,
)
from tests.test_ai_advisor_provider_contract import fixture_text


def build_sdk_response(*, model, status="completed", text='{"ok":true}'):
    """Construct a high-fidelity OpenAI SDK 2.48.0 Response with no I/O."""
    from openai.types.responses import Response

    return Response.model_validate(
        {
            "id": "resp_offline_test",
            "object": "response",
            "created_at": 1755653150.0,
            "status": status,
            "model": model,
            "output": [
                {
                    "id": "msg_offline_test",
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": text,
                            "annotations": [],
                            "logprobs": [],
                        }
                    ],
                }
            ],
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
    )


class OpenAISDKResponseContractTest(unittest.TestCase):
    def test_valid_completed_sdk_response_with_exact_model_is_accepted(self):
        value, _, _, _ = transport(
            response=build_sdk_response(
                model="openai-advisor-model", text=fixture_text()
            )
        )
        result = value.invoke(request())
        self.assertEqual(result["output_text"], fixture_text())
        self.assertEqual(result["finish_reason"], "completed")

    def test_valid_sdk_response_with_dated_snapshot_model_is_accepted(self):
        value, _, _, _ = transport(
            response=build_sdk_response(
                model="openai-advisor-model-2026-01-15", text=fixture_text()
            )
        )
        result = value.invoke(request())
        self.assertEqual(result["output_text"], fixture_text())

    def test_valid_structured_json_text_is_extracted(self):
        value, _, _, _ = transport(
            response=build_sdk_response(
                model="openai-advisor-model", text=fixture_text()
            )
        )
        result = value.invoke(request())
        self.assertEqual(result["output_text"], fixture_text())

    def test_genuinely_different_model_is_rejected(self):
        sink = RecordingProviderFailureObservationSink()
        value, _, _, _ = transport(
            response=build_sdk_response(model="gpt-4o"), failure_sink=sink
        )
        with self.assertRaises(OpenAITransportRejectedError):
            value.invoke(request())
        self.assertEqual(
            sink.observation.safeReason,
            ProviderSafeReason.LIVE_PROVIDER_MODEL_CONTRACT_FAILED,
        )
        self.assertEqual(
            sink.observation.failureStage,
            ProviderFailureStage.RESPONSE_VALIDATION,
        )
        self.assertNotIn("gpt-4o", sink.observation.model_dump_json())

    def test_missing_model_is_rejected(self):
        sink = RecordingProviderFailureObservationSink()
        value, _, _, _ = transport(
            response=FakeResponse(fixture_text(), model=None), failure_sink=sink
        )
        with self.assertRaises(OpenAITransportRejectedError):
            value.invoke(request())
        self.assertEqual(
            sink.observation.safeReason,
            ProviderSafeReason.LIVE_PROVIDER_MODEL_CONTRACT_FAILED,
        )

    def test_incomplete_response_is_rejected(self):
        sink = RecordingProviderFailureObservationSink()
        value, _, _, _ = transport(
            response=build_sdk_response(
                model="openai-advisor-model",
                status="incomplete",
                text=fixture_text(),
            ),
            failure_sink=sink,
        )
        with self.assertRaises(OpenAITransportRejectedError):
            value.invoke(request())
        self.assertEqual(
            sink.observation.safeReason,
            ProviderSafeReason.LIVE_PROVIDER_STATUS_CONTRACT_FAILED,
        )

    def test_failed_response_is_rejected(self):
        value, _, _, _ = transport(
            response=build_sdk_response(
                model="openai-advisor-model", status="failed", text=""
            )
        )
        with self.assertRaises(OpenAITransportRejectedError):
            value.invoke(request())

    def test_missing_output_text_is_rejected(self):
        sink = RecordingProviderFailureObservationSink()
        value, _, _, _ = transport(
            response=FakeResponse(None), failure_sink=sink
        )
        with self.assertRaises(OpenAITransportRejectedError):
            value.invoke(request())
        self.assertEqual(
            sink.observation.safeReason,
            ProviderSafeReason.LIVE_PROVIDER_OUTPUT_TEXT_CONTRACT_FAILED,
        )

    def test_empty_output_text_is_rejected(self):
        value, _, _, _ = transport(response=FakeResponse(" "))
        with self.assertRaises(OpenAITransportRejectedError):
            value.invoke(request())

    def test_wrong_output_type_is_rejected(self):
        value, _, _, _ = transport(response=FakeResponse(1))
        with self.assertRaises(OpenAITransportRejectedError):
            value.invoke(request())


if __name__ == "__main__":
    unittest.main()
