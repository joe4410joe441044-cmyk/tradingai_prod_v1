import json
import unittest

import httpx
import openai

from backend.ai_advisor.provider_failure_observation import (
    ProviderErrorType,
    ProviderFailureCategory,
    RecordingProviderFailureObservationSink,
)
from tests.test_ai_advisor_openai_sdk_compatibility import request, sdk_transport


SENTINELS = (
    "FAKE_OPENAI_KEY_DO_NOT_LEAK",
    "FAKE_AUTH_TOKEN_DO_NOT_LEAK",
    "FAKE_SESSION_DO_NOT_LEAK",
    "FAKE_PROMPT_DO_NOT_LEAK",
    "FAKE_PROVIDER_BODY_DO_NOT_LEAK",
    "Authorization",
)


class BoundedFailureObservabilityTest(unittest.TestCase):
    def test_sdk_http_classification_metadata_correlation_and_sentinels(self):
        cases = (
            (401, "authentication_error", None, ProviderFailureCategory.AUTHENTICATION),
            (403, "permission_error", None, ProviderFailureCategory.PERMISSION),
            (429, "rate_limit_error", None, ProviderFailureCategory.RATE_LIMIT),
            (400, "invalid_request_error", None, ProviderFailureCategory.INVALID_REQUEST),
            (404, "invalid_request_error", "model_not_found", ProviderFailureCategory.MODEL_NOT_FOUND_OR_UNAVAILABLE),
            (500, "server_error", None, ProviderFailureCategory.PROVIDER_SERVER_ERROR),
            (400, "invalid_request_error", "invalid_response_format", ProviderFailureCategory.STRUCTURED_OUTPUT_OR_RESPONSE_FORMAT),
        )
        for status, error_type, error_code, category in cases:
            with self.subTest(category=category):
                sink = RecordingProviderFailureObservationSink()

                def handler(http_request):
                    return httpx.Response(status, json={"error": {
                        "message": "FAKE_PROMPT_DO_NOT_LEAK FAKE_OPENAI_KEY_DO_NOT_LEAK",
                        "type": error_type,
                        "code": error_code,
                        "Authorization": "Bearer FAKE_AUTH_TOKEN_DO_NOT_LEAK",
                        "session": "FAKE_SESSION_DO_NOT_LEAK",
                    }})

                value, _, _ = sdk_transport(handler, failure_sink=sink)
                trusted = request().model_copy(update={
                    "requestId": "request-safe-1",
                    "providerRequestId": "provider-safe-1",
                })
                with self.assertRaises(Exception):
                    value.invoke(trusted)
                observation = sink.observation
                self.assertEqual(observation.category, category)
                self.assertEqual(observation.httpStatus, status)
                self.assertEqual(observation.model, "openai-advisor-model")
                self.assertEqual(observation.requestId, "request-safe-1")
                self.assertEqual(observation.providerRequestId, "provider-safe-1")
                self.assertIsNotNone(observation.durationMilliseconds)
                self.assertEqual(observation.providerErrorType, ProviderErrorType(error_type))
                if error_code is not None:
                    self.assertEqual(observation.providerErrorCode.value, error_code)
                rendered = observation.model_dump_json()
                for sentinel in SENTINELS:
                    self.assertNotIn(sentinel, rendered)

    def test_timeout_network_and_unknown_never_serialize_raw_exception(self):
        cases = (
            (
                httpx.ReadTimeout(
                    "FAKE_PROVIDER_BODY_DO_NOT_LEAK",
                    request=httpx.Request("POST", "https://offline.invalid"),
                ),
                ProviderFailureCategory.TIMEOUT,
            ),
            (
                httpx.ConnectError(
                    "FAKE_AUTH_TOKEN_DO_NOT_LEAK",
                    request=httpx.Request("POST", "https://offline.invalid"),
                ),
                ProviderFailureCategory.NETWORK_OR_TRANSPORT,
            ),
            (
                openai.OpenAIError(
                    "FAKE_PROMPT_DO_NOT_LEAK FAKE_SESSION_DO_NOT_LEAK"
                ),
                ProviderFailureCategory.UNKNOWN_PROVIDER_FAILURE,
            ),
        )
        for failure, category in cases:
            with self.subTest(category=category):
                sink = RecordingProviderFailureObservationSink()

                def handler(http_request):
                    raise failure

                value, _, _ = sdk_transport(handler, failure_sink=sink)
                with self.assertRaises(Exception):
                    value.invoke(request())
                observation = sink.observation
                self.assertEqual(observation.category, category)
                rendered = json.dumps(observation.model_dump(mode="json"))
                for sentinel in SENTINELS:
                    self.assertNotIn(sentinel, rendered)


if __name__ == "__main__":
    unittest.main()
