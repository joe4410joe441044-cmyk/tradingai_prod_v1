import json
import unittest

from pydantic import ValidationError

from backend.ai_advisor.provider_failure_observation import (
    ProviderFailureObservation,
    ProviderFailureCategory,
    ProviderErrorCode,
    ProviderErrorType,
    ProviderFailureStage,
    ProviderSafeReason,
    RecordingProviderFailureObservationSink,
    StructuredLoggingProviderFailureObservationSink,
    ResponseContractField,
    ResponseTopLevelType,
    ResponseValidationCode,
)


class ProviderFailureObservationTest(unittest.TestCase):
    def test_allowlisted_observation_is_fixed_json_and_secret_free(self):
        observation = ProviderFailureObservation(
            safeReason=ProviderSafeReason.LIVE_PROVIDER_AUTHENTICATION_FAILED,
            failureStage=ProviderFailureStage.PROVIDER_INVOCATION,
            httpStatus=401,
            liveInvocationAttempted=True,
        )
        rendered = observation.model_dump_json()
        self.assertEqual(json.loads(rendered)["httpStatus"], 401)
        self.assertNotIn("message", rendered.lower())
        self.assertNotIn("exception", rendered.lower())
        self.assertNotIn("sk-test-DO-NOT-LEAK", rendered)

    def test_unknown_fallback_has_no_untrusted_fields(self):
        observation = ProviderFailureObservation(
            safeReason=ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE,
            failureStage=ProviderFailureStage.UNKNOWN,
            liveInvocationAttempted=True,
        )
        self.assertIsNone(observation.httpStatus)
        self.assertFalse(observation.retryPerformed)
        self.assertEqual(observation.providerRequestUpperBound, 1)
        self.assertFalse(observation.invocationSucceeded)

    def test_status_is_optional_but_strictly_bounded(self):
        for value in (0, 399, 600, "401", True):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    ProviderFailureObservation(
                        safeReason=ProviderSafeReason.LIVE_PROVIDER_BAD_REQUEST,
                        failureStage=ProviderFailureStage.PROVIDER_INVOCATION,
                        httpStatus=value,
                        liveInvocationAttempted=True,
                    )

        for patch in (
            {"providerRequestUpperBound": 2},
            {"retryPerformed": True},
            {"invocationSucceeded": True},
        ):
            with self.subTest(patch=patch):
                with self.assertRaises(ValidationError):
                    ProviderFailureObservation(
                        safeReason=ProviderSafeReason.LIVE_PROVIDER_BAD_REQUEST,
                        failureStage=ProviderFailureStage.PROVIDER_INVOCATION,
                        liveInvocationAttempted=True,
                        **patch,
                    )

    def test_recording_sink_is_single_assignment(self):
        sink = RecordingProviderFailureObservationSink()
        first = ProviderFailureObservation(
            safeReason=ProviderSafeReason.LIVE_PROVIDER_TIMEOUT,
            failureStage=ProviderFailureStage.PROVIDER_INVOCATION,
            liveInvocationAttempted=True,
        )
        second = ProviderFailureObservation(
            safeReason=ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE,
            failureStage=ProviderFailureStage.UNKNOWN,
            liveInvocationAttempted=True,
        )
        sink.observe(first)
        sink.observe(second)
        self.assertEqual(sink.observation, first)

    def test_response_diagnostic_is_fixed_allowlisted_and_bounded(self):
        observation = ProviderFailureObservation(
            safeReason=ProviderSafeReason.LIVE_PROVIDER_RESPONSE_CONTRACT_FAILED,
            failureStage=ProviderFailureStage.RESPONSE_VALIDATION,
            httpStatus=502,
            liveInvocationAttempted=True,
            parseSucceeded=False,
            validationCode=ResponseValidationCode.REQUIRED_FIELD_MISSING,
            topLevelType=ResponseTopLevelType.OBJECT,
            invalidField=ResponseContractField.SUMMARY,
            missingFields=(ResponseContractField.SUMMARY,),
        )
        rendered = observation.model_dump_json()
        self.assertIn('"validationCode":"REQUIRED_FIELD_MISSING"', rendered)
        self.assertIn('"missingFields":["summary"]', rendered)
        for forbidden in ("raw", "exception", "actualValue", "secret-value"):
            self.assertNotIn(forbidden, rendered)

        invalid_values = (
            {"validationCode": "ARBITRARY"},
            {"invalidField": "attacker-controlled-field"},
            {"missingFields": ("attacker-controlled-field",)},
            {"missingFields": (ResponseContractField.SUMMARY,) * 2},
        )
        for changed in invalid_values:
            values = observation.model_dump()
            values.update(changed)
            with self.subTest(changed=changed):
                with self.assertRaises(ValidationError):
                    ProviderFailureObservation.model_validate(values)

    def test_non_response_observation_rejects_parser_diagnostics(self):
        with self.assertRaises(ValidationError):
            ProviderFailureObservation(
                safeReason=ProviderSafeReason.LIVE_PROVIDER_TIMEOUT,
                failureStage=ProviderFailureStage.PROVIDER_INVOCATION,
                liveInvocationAttempted=True,
                parseSucceeded=False,
                validationCode=ResponseValidationCode.JSON_DECODE_FAILED,
                topLevelType=ResponseTopLevelType.UNKNOWN,
            )


    def test_structured_logging_sink_serializes_only_allowlisted_fields(self):
        class FakeLogger:
            def __init__(self):
                self.calls = []

            def warning(self, template, payload):
                self.calls.append((template, payload))

        logger = FakeLogger()
        sink = StructuredLoggingProviderFailureObservationSink(logger=logger)
        sink.observe(ProviderFailureObservation(
            model="gpt-test",
            requestId="request-safe-1",
            providerRequestId="provider-safe-1",
            category=ProviderFailureCategory.STRUCTURED_OUTPUT_OR_RESPONSE_FORMAT,
            safeReason=ProviderSafeReason.LIVE_PROVIDER_BAD_REQUEST,
            failureStage=ProviderFailureStage.PROVIDER_INVOCATION,
            httpStatus=400,
            providerErrorType=ProviderErrorType.INVALID_REQUEST_ERROR,
            providerErrorCode=ProviderErrorCode.INVALID_RESPONSE_FORMAT,
            retryable=False,
            durationMilliseconds=17,
            liveInvocationAttempted=True,
        ))
        self.assertEqual(len(logger.calls), 1)
        rendered = logger.calls[0][1]
        decoded = json.loads(rendered)
        self.assertEqual(decoded["model"], "gpt-test")
        self.assertEqual(decoded["requestId"], "request-safe-1")
        self.assertEqual(decoded["providerErrorCode"], "invalid_response_format")
        for sentinel in (
            "FAKE_OPENAI_KEY_DO_NOT_LEAK",
            "FAKE_AUTH_TOKEN_DO_NOT_LEAK",
            "FAKE_SESSION_DO_NOT_LEAK",
            "FAKE_PROMPT_DO_NOT_LEAK",
            "FAKE_PROVIDER_BODY_DO_NOT_LEAK",
            "Authorization",
        ):
            self.assertNotIn(sentinel, rendered)

    def test_observation_rejects_unallowlisted_provider_metadata(self):
        values = dict(
            safeReason=ProviderSafeReason.LIVE_PROVIDER_UNKNOWN_FAILURE,
            failureStage=ProviderFailureStage.UNKNOWN,
            liveInvocationAttempted=True,
        )
        for field, sentinel in (
            ("providerErrorType", "FAKE_AUTH_TOKEN_DO_NOT_LEAK"),
            ("providerErrorCode", "FAKE_PROVIDER_BODY_DO_NOT_LEAK"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    ProviderFailureObservation(**values, **{field: sentinel})


if __name__ == "__main__":
    unittest.main()
