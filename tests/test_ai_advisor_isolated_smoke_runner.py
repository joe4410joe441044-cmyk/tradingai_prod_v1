import asyncio
import json
import os
import socket
import subprocess
import time
import unittest
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from backend.ai_advisor.credential_loader import InjectedCredentialLoader
from backend.ai_advisor.isolated_smoke_runner import (
    CredentialAvailabilityStatus,
    CredentialReferenceStatus,
    CredentialSourceStatus,
    IsolatedSmokeResult,
    IsolatedSmokeTestRunner,
    SmokePreflightStatus,
    SmokeTestMode,
    build_fixed_synthetic_request,
    inspect_credential_references,
    isolated_failure_shutdown_steps,
    isolated_non_secret_environment,
    main,
    sanitize_safe_result_stream,
    smoke_result_exit_code,
)
from backend.ai_advisor.production_config_loader import (
    EnvironmentProductionConfigLoader,
    InjectedProductionConfigLoader,
)
from backend.ai_advisor.provider_failure_observation import (
    ProviderFailureStage,
    ProviderSafeReason,
    ResponseContractField,
    ResponseTopLevelType,
    ResponseValidationCode,
)
from backend.ai_advisor.provider_transport import OpenAITransportTimeout
from tests.test_ai_advisor_openai_sdk_transport import (
    FakeClient,
    FakeClientFactory,
    FakeResponse,
    FakeResponses,
)
from backend.ai_advisor.usage_observation import (
    AdvisorTokenUsage,
    RecordingUsageObservationSink,
    SafeEndpointClassification,
    SafeProviderName,
    UsageObservation,
    UsageObservationStatus,
    project_sdk_metadata,
    project_sdk_usage,
)

NOW = datetime(2026, 7, 26, 16, tzinfo=timezone.utc)
MODEL = "gpt-4o-mini"


def values(**overrides):
    result = {
        "endpointEnabled": "true",
        "networkInvocationAllowed": "true",
        "liveTestExplicitlyAllowed": "true",
        "liveKillSwitchActive": "false",
        "authenticationCredentialId": "auth-ref",
        "credentialId": "provider-ref",
        "model": MODEL,
        "baseUrl": "https://api.openai.com/v1",
        "liveMaximumOutputTokens": "512",
        "providerTimeoutSeconds": "30",
        "endpointTimeoutSeconds": "35",
    }
    result.update(overrides)
    return result


def response_text():
    return json.dumps(
        {
            "responseVersion": "1.0",
            "requestId": "isolated-smoke-request",
            "promptVersion": "1.0",
            "summary": "This advisor explains information without taking action.",
            "facts": [],
            "inferences": [],
            "unknowns": [],
            "warnings": [],
            "sourceReferences": [],
            "freshnessDisclosures": [],
            "safetyDisclosures": [
                "NO_TOOL_USED",
                "NO_STATE_CHANGED",
                "NO_ACTION_EXECUTED",
                "READ_ONLY",
            ],
        },
        separators=(",", ":"),
    )


def runner(
    config_values=None,
    *,
    approved_models=(MODEL,),
    response=None,
    usage=None,
):
    auth = InjectedCredentialLoader({"auth-ref": "offline-auth-placeholder"})
    provider = InjectedCredentialLoader(
        {"provider-ref": "offline-provider-placeholder"}
    )
    responses = FakeResponses(
        response=FakeResponse(
            response if response is not None else response_text(),
            usage=usage,
            model=MODEL,
        )
    )
    factory = FakeClientFactory(FakeClient(responses))
    value = IsolatedSmokeTestRunner(
        configLoader=InjectedProductionConfigLoader(config_values or values()),
        authenticationCredentialLoader=auth,
        providerCredentialLoader=provider,
        allowedAuthenticationCredentialIds=("auth-ref",),
        allowedProviderCredentialIds=("provider-ref",),
        approvedModels=approved_models,
        clientFactory=factory,
    )
    return value, auth, provider, factory, responses


def approval():
    return "AI-ADV-1E9 LIVE TEST " + "APPROVED: ONE REQUEST"


def smoke_result(
    *,
    mode=SmokeTestMode.LIVE_ONE_SHOT,
    status=SmokePreflightStatus.BLOCKED,
    composition_built=False,
    attempted=False,
    succeeded=False,
    reason="LIVE_ONE_SHOT_FAILED",
):
    return IsolatedSmokeResult(
        mode=mode,
        status=status,
        compositionBuilt=composition_built,
        liveInvocationAttempted=attempted,
        invocationSucceeded=succeeded,
        request_id="resp_offline_test" if succeeded else None,
        model=MODEL if succeeded else None,
        provider=SafeProviderName.OPENAI if succeeded else None,
        endpoint_classification=(
            SafeEndpointClassification.OFFICIAL_OPENAI if succeeded else None
        ),
        safeReasons=(reason,),
    )


class IsolatedSmokeRunnerTest(unittest.TestCase):
    def test_import_uses_stdio_only_without_touching_repository_logging(self):
        source = """
import logging.handlers
import os

def reject_file_logging(*args, **kwargs):
    raise AssertionError("repository file logging attempted")

os.makedirs = reject_file_logging
logging.handlers.RotatingFileHandler = reject_file_logging
import backend.ai_advisor.isolated_smoke_runner
from backend.utils.log_buffer import logger
logger.warning("ISOLATED_STDERR_READY")
print("ISOLATED_IMPORT_READY")
"""
        environment = os.environ.copy()
        environment["TRADINGAI_ISOLATED_STDIO_ONLY"] = "true"
        completed = subprocess.run(
            [os.sys.executable, "-c", source],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=environment,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "ISOLATED_IMPORT_READY")
        self.assertIn("ISOLATED_STDERR_READY", completed.stderr)
        self.assertNotIn("repository file logging attempted", completed.stderr)

    def test_normal_import_retains_production_file_logging_default(self):
        source = """
import logging
import logging.handlers
import os

calls = []

class RecordingHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__()
        calls.append(("file", args[0]))

os.makedirs = lambda path, exist_ok=False: calls.append(("directory", path))
logging.handlers.RotatingFileHandler = RecordingHandler
os.environ.pop("TRADINGAI_ISOLATED_STDIO_ONLY", None)
import backend.utils.log_buffer
assert [kind for kind, _ in calls] == ["directory", "file"]
print("PRODUCTION_FILE_LOGGING_READY")
"""
        completed = subprocess.run(
            [os.sys.executable, "-c", source],
            cwd=os.path.dirname(os.path.dirname(__file__)),
            env=os.environ.copy(),
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(
            completed.stdout.strip(),
            "PRODUCTION_FILE_LOGGING_READY",
        )
        self.assertEqual(completed.stderr, "")

    def test_default_is_dry_run_with_no_credentials_client_or_network(self):
        value, auth, provider, factory, responses = runner()
        with (
            patch.object(socket, "socket", side_effect=AssertionError),
            patch.object(socket, "create_connection", side_effect=AssertionError),
            patch.object(socket, "getaddrinfo", side_effect=AssertionError),
            patch(
                "backend.ai_advisor.live_connectivity."
                "AtomicOneShotPermit.try_acquire",
                side_effect=AssertionError,
            ),
        ):
            result = value.run(generated_at=NOW)
        self.assertEqual(result.mode, SmokeTestMode.DRY_RUN)
        self.assertEqual(
            result.status,
            SmokePreflightStatus.READY_FOR_CONFIGURATION,
        )
        self.assertEqual(auth.calls, 0)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(factory.calls, 0)
        self.assertEqual(len(responses.calls), 0)

    def test_synthetic_request_is_fixed_minimal_and_has_no_override_fields(self):
        first = build_fixed_synthetic_request(generated_at=NOW)
        second = build_fixed_synthetic_request(generated_at=NOW)
        self.assertEqual(first, second)
        self.assertIsNone(first.contextInput.runtime)
        self.assertEqual(first.contextInput.specifications, ())
        self.assertEqual(first.contextInput.marketIntelligenceSources, ())
        self.assertEqual(first.contextInput.moneyManagementSources, ())
        self.assertEqual(first.contextInput.conversationHistory, ())
        self.assertIsNone(first.contextInput.currentMessage)
        serialized = first.model_dump_json()
        for forbidden in (
            '"model"',
            "maxOutputTokens",
            "baseUrl",
            "BUY",
            "SELL",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_model_endpoint_and_output_budget_fail_closed(self):
        cases = (
            (
                values(model="openai-advisor-model"),
                (MODEL,),
                SmokePreflightStatus.MODEL_DECISION_REQUIRED,
            ),
            (values(), (), SmokePreflightStatus.MODEL_DECISION_REQUIRED),
            (values(model="not-approved"), (MODEL,), SmokePreflightStatus.BLOCKED),
            (
                values(baseUrl="https://example.invalid/v1"),
                (MODEL,),
                SmokePreflightStatus.BLOCKED,
            ),
            (
                values(liveMaximumOutputTokens="1025"),
                (MODEL,),
                SmokePreflightStatus.BLOCKED,
            ),
            (
                values(liveMaximumOutputTokens="1024"),
                (MODEL,),
                SmokePreflightStatus.BLOCKED,
            ),
            (
                values(liveMaximumOutputTokens="0"),
                (MODEL,),
                SmokePreflightStatus.CONFIGURATION_INVALID,
            ),
        )
        for config, approved, expected in cases:
            with self.subTest(expected=expected, config=config):
                value, auth, provider, factory, _ = runner(
                    config,
                    approved_models=approved,
                )
                result = value.run(generated_at=NOW)
                self.assertEqual(result.status, expected)
                self.assertEqual(auth.calls, 0)
                self.assertEqual(provider.calls, 0)
                self.assertEqual(factory.calls, 0)

    def test_live_requires_exact_transient_approval_before_configuration(self):
        class ExplodingLoader:
            def load(self):
                raise AssertionError("configuration must not be read")

        value, *_ = runner()
        value.configLoader = ExplodingLoader()
        result = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval="almost",
        )
        self.assertEqual(result.status, SmokePreflightStatus.BLOCKED)
        self.assertEqual(result.safeReasons, ("LIVE_APPROVAL_REQUIRED",))

    def test_live_kill_switch_precedes_model_and_credentials(self):
        value, auth, provider, factory, _ = runner(
            values(
                liveKillSwitchActive="true",
                model="openai-advisor-model",
            ),
            approved_models=(),
        )
        result = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval=approval(),
        )
        self.assertEqual(result.safeReasons, ("KILL_SWITCH_ACTIVE",))
        self.assertEqual(auth.calls, 0)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(factory.calls, 0)

    def test_mock_live_path_uses_composition_gate_once_and_no_retry(self):
        value, auth, provider, factory, responses = runner()
        first = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval=approval(),
        )
        second = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval=approval(),
        )
        self.assertTrue(first.invocationSucceeded)
        self.assertFalse(second.invocationSucceeded)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)
        self.assertEqual(auth.calls, 4)
        provider_call = responses.calls[0]
        self.assertEqual(provider_call["max_output_tokens"], 512)
        self.assertEqual(provider_call["timeout"], 30.0)
        self.assertFalse(provider_call["stream"])
        self.assertFalse(provider_call["store"])

    def test_live_failure_projects_only_fixed_observation_fields(self):
        value, _, provider, factory, responses = runner()
        responses.exception = OpenAITransportTimeout(
            "sk-test-DO-NOT-LEAK Authorization: Bearer private"
        )
        result = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval=approval(),
        )
        self.assertFalse(result.invocationSucceeded)
        self.assertEqual(
            result.safeReasons,
            (ProviderSafeReason.LIVE_PROVIDER_TIMEOUT.value,),
        )
        self.assertEqual(
            result.failureStage,
            ProviderFailureStage.PROVIDER_INVOCATION,
        )
        self.assertIsNone(result.httpStatus)
        self.assertEqual(result.providerRequestUpperBound, 1)
        self.assertFalse(result.retryPerformed)
        self.assertIsNone(result.request_id)
        self.assertEqual(result.model, MODEL)
        self.assertEqual(result.provider, SafeProviderName.OPENAI)
        self.assertEqual(
            result.endpoint_classification,
            SafeEndpointClassification.OFFICIAL_OPENAI,
        )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)
        rendered = result.model_dump_json()
        self.assertNotIn("sk-test-DO-NOT-LEAK", rendered)
        self.assertNotIn("Authorization", rendered)
        self.assertNotIn("private", rendered)

    def test_live_parser_failure_is_response_contract_classification(self):
        value, _, provider, factory, responses = runner(
            response="not json sk-test-DO-NOT-LEAK"
        )
        result = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval=approval(),
        )
        self.assertEqual(
            result.safeReasons,
            (ProviderSafeReason.LIVE_PROVIDER_RESPONSE_CONTRACT_FAILED.value,),
        )
        self.assertEqual(
            result.failureStage,
            ProviderFailureStage.RESPONSE_VALIDATION,
        )
        self.assertEqual(result.httpStatus, 502)
        self.assertFalse(result.parseSucceeded)
        self.assertEqual(
            result.validationCode,
            ResponseValidationCode.JSON_DECODE_FAILED,
        )
        self.assertEqual(result.topLevelType, ResponseTopLevelType.UNKNOWN)
        self.assertIsNone(result.invalidField)
        self.assertEqual(result.missingFields, ())
        self.assertEqual(provider.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)
        self.assertNotIn(
            "sk-test-DO-NOT-LEAK",
            result.model_dump_json(),
        )

    def test_live_missing_field_projects_only_allowlisted_diagnosis(self):
        payload = json.loads(response_text())
        payload.pop("summary")
        payload["untrusted-extra-secret"] = "sk-test-DO-NOT-LEAK"
        value, _, provider, factory, responses = runner(
            response=json.dumps(payload),
        )
        result = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval=approval(),
        )
        self.assertEqual(
            result.validationCode,
            ResponseValidationCode.REQUIRED_FIELD_MISSING,
        )
        self.assertEqual(result.topLevelType, ResponseTopLevelType.OBJECT)
        self.assertEqual(result.invalidField, ResponseContractField.SUMMARY)
        self.assertEqual(
            result.missingFields,
            (ResponseContractField.SUMMARY,),
        )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)
        rendered = result.model_dump_json()
        self.assertNotIn("untrusted-extra-secret", rendered)
        self.assertNotIn("sk-test-DO-NOT-LEAK", rendered)

    def test_exception_has_no_retry_and_result_is_secret_safe(self):
        value, auth, provider, factory, responses = runner(
            response="{",
        )
        result = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval=approval(),
        )
        self.assertFalse(result.invocationSucceeded)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)
        rendered = repr(value) + repr(result) + result.model_dump_json()
        for forbidden in (
            "offline-auth-placeholder",
            "offline-provider-placeholder",
            "auth-ref",
            "provider-ref",
            "api_key",
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(auth.calls, 2)

    def test_existing_endpoint_rejects_auth_and_authorization_before_provider(self):
        value, auth, provider, factory, responses = runner()
        composition, config, failure = value._load_and_validate(
            SmokeTestMode.LIVE_ONE_SHOT
        )
        self.assertIsNone(failure)
        service_input = build_fixed_synthetic_request(
            generated_at=NOW,
            principal_id=config.principalId,
        )
        for header in ("", "Bearer invalid"):
            with self.subTest(header=header):
                succeeded = asyncio.run(
                    value._post_in_process(
                        composition=composition,
                        service_input=service_input,
                        authorization_header=header,
                    )
                )
                self.assertFalse(succeeded)
        mismatched = build_fixed_synthetic_request(
            generated_at=NOW,
            principal_id="different-principal",
        )
        succeeded = asyncio.run(
            value._post_in_process(
                composition=composition,
                service_input=mismatched,
                authorization_header="Bearer offline-auth-placeholder",
            )
        )
        self.assertFalse(succeeded)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(factory.calls, 0)
        self.assertEqual(len(responses.calls), 0)
        self.assertEqual(auth.calls, 2)

        denied, denied_auth, denied_provider, denied_factory, denied_responses = runner(
            values(advisorAccessAllowed="false")
        )
        denied_composition, denied_config, denied_failure = denied._load_and_validate(
            SmokeTestMode.LIVE_ONE_SHOT
        )
        self.assertIsNone(denied_failure)
        denied_input = build_fixed_synthetic_request(
            generated_at=NOW,
            principal_id=denied_config.principalId,
        )
        succeeded = asyncio.run(
            denied._post_in_process(
                composition=denied_composition,
                service_input=denied_input,
                authorization_header="Bearer offline-auth-placeholder",
            )
        )
        self.assertFalse(succeeded)
        self.assertEqual(denied_auth.calls, 1)
        self.assertEqual(denied_provider.calls, 0)
        self.assertEqual(denied_factory.calls, 0)
        self.assertEqual(len(denied_responses.calls), 0)

    def test_authenticated_asgi_usage_is_internal_and_strict(self):
        usage = SimpleNamespace(
            input_tokens=20,
            output_tokens=12,
            total_tokens=32,
        )
        value, auth, provider, factory, responses = runner(usage=usage)
        result = value.run(
            mode=SmokeTestMode.LIVE_ONE_SHOT,
            generated_at=NOW,
            live_approval=approval(),
        )
        self.assertTrue(result.invocationSucceeded)
        self.assertEqual(result.usageStatus, UsageObservationStatus.AVAILABLE)
        self.assertEqual(result.request_id, "resp_offline_test")
        self.assertEqual(result.model, MODEL)
        self.assertEqual(result.provider, SafeProviderName.OPENAI)
        self.assertEqual(
            result.endpoint_classification,
            SafeEndpointClassification.OFFICIAL_OPENAI,
        )
        self.assertEqual(
            result.usage,
            AdvisorTokenUsage(
                inputTokens=20,
                outputTokens=12,
                totalTokens=32,
            ),
        )
        self.assertEqual(auth.calls, 2)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)
        self.assertNotIn("usage", response_text())

    def test_safe_result_sanitizer_accepts_metadata_and_fails_closed(self):
        valid = smoke_result(
            status=SmokePreflightStatus.READY_FOR_CONFIGURATION,
            composition_built=True,
            attempted=True,
            succeeded=True,
            reason="LIVE_ONE_SHOT_COMPLETE",
        ).model_copy(
            update={
                "request_id": "resp_safe_123",
                "model": MODEL,
                "provider": SafeProviderName.OPENAI,
                "endpoint_classification": (SafeEndpointClassification.OFFICIAL_OPENAI),
            }
        )
        output = StringIO()
        self.assertEqual(
            sanitize_safe_result_stream(
                StringIO(valid.model_dump_json() + "\n"),
                output,
            ),
            0,
        )
        recovered = json.loads(output.getvalue())
        self.assertEqual(recovered["recoveryStatus"], "RECOVERED")
        projection = recovered["safeProjection"]
        self.assertEqual(projection["request_id"], "resp_safe_123")
        self.assertEqual(projection["model"], MODEL)
        self.assertEqual(projection["provider"], "openai")
        self.assertEqual(
            projection["endpoint_classification"],
            "official_openai",
        )

        base = valid.model_dump(mode="json")
        unsafe_cases = (
            {**base, "unknownField": "value"},
            {**base, "request_id": "sk-" + "A" * 40},
            {**base, "request_id": "Authorization"},
            {**base, "request_id": "x" * 129},
            {**base, "request_id": 1},
            {**base, "model": ["gpt-4o-mini"]},
            {**base, "provider": "https://api.openai.com/v1?token=x"},
            {
                **base,
                "endpoint_classification": "https://api.openai.com/v1?token=x",
            },
            {**base, "prompt": "private prompt"},
            {**base, "responseBody": "private response"},
        )
        for unsafe in unsafe_cases:
            with self.subTest(fields=tuple(unsafe)):
                output = StringIO()
                self.assertEqual(
                    sanitize_safe_result_stream(
                        StringIO(json.dumps(unsafe) + "\n"),
                        output,
                    ),
                    22,
                )
                rejected = json.loads(output.getvalue())
                self.assertEqual(
                    rejected["recoveryStatus"],
                    "UNSAFE_OR_UNKNOWN_FIELD_REJECTED",
                )
                self.assertEqual(rejected["safeProjection"], {})

    def test_usage_missing_invalid_and_sink_single_assignment(self):
        missing = project_sdk_usage(SimpleNamespace(usage=None))
        self.assertEqual(
            missing.status,
            UsageObservationStatus.USAGE_UNAVAILABLE,
        )
        invalid_values = (
            SimpleNamespace(input_tokens=True, output_tokens=1, total_tokens=2),
            SimpleNamespace(input_tokens=-1, output_tokens=1, total_tokens=0),
            SimpleNamespace(input_tokens=1, output_tokens="1", total_tokens=2),
            SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=3),
        )
        for usage in invalid_values:
            with self.subTest(usage=usage):
                projected = project_sdk_usage(SimpleNamespace(usage=usage))
                self.assertEqual(
                    projected.status,
                    UsageObservationStatus.USAGE_UNAVAILABLE,
                )
        with self.assertRaises(ValidationError):
            AdvisorTokenUsage(inputTokens=True, outputTokens=1, totalTokens=2)
        sink = RecordingUsageObservationSink()
        sink.observe(missing)
        with self.assertRaises(ValueError):
            sink.observe(missing)

    def test_provider_metadata_projection_never_copies_unsafe_identifier(self):
        safe = project_sdk_metadata(
            SimpleNamespace(_request_id="req_safe_123"),
            model=MODEL,
        )
        self.assertEqual(safe.requestId, "req_safe_123")
        unsafe = project_sdk_metadata(
            SimpleNamespace(_request_id="sk-" + "A" * 40),
            model=MODEL,
        )
        self.assertIsNone(unsafe.requestId)
        self.assertEqual(unsafe.model, MODEL)
        self.assertEqual(unsafe.provider, SafeProviderName.OPENAI)
        self.assertEqual(
            unsafe.endpointClassification,
            SafeEndpointClassification.OFFICIAL_OPENAI,
        )

    def test_cli_defaults_to_dry_run_and_prints_only_safe_result(self):
        output = StringIO()
        with (
            patch("sys.stdout", output),
            patch.object(socket, "socket", side_effect=AssertionError),
            patch.object(socket, "create_connection", side_effect=AssertionError),
            patch.object(socket, "getaddrinfo", side_effect=AssertionError),
        ):
            exit_code = main([])
        rendered = output.getvalue()
        self.assertNotEqual(exit_code, 0)
        self.assertIn('"mode":"DRY_RUN"', rendered)
        self.assertIn('"status":"CREDENTIAL_REFERENCE_NOT_READY"', rendered)
        for forbidden in (
            "offline-auth-placeholder",
            "offline-provider-placeholder",
            "Authorization",
            "Bearer ",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_cli_live_approval_missing_blocks_without_waiting_or_building(self):
        output = StringIO()
        with (
            patch("sys.stdout", output),
            patch.object(
                IsolatedSmokeTestRunner,
                "run",
                side_effect=AssertionError("runner must not be built"),
            ),
        ):
            exit_code = main(["--mode", "LIVE_ONE_SHOT"])
        self.assertNotEqual(exit_code, 0)
        self.assertIn('"safeReasons":["LIVE_APPROVAL_REQUIRED"]', output.getvalue())

    def test_cli_live_approval_invalid_blocks_before_runner(self):
        output = StringIO()
        with (
            patch("sys.stdout", output),
            patch.object(
                IsolatedSmokeTestRunner,
                "run",
                side_effect=AssertionError("runner must not be built"),
            ),
        ):
            exit_code = main(
                [
                    "--mode",
                    "LIVE_ONE_SHOT",
                    "--live-one-shot-approval",
                    "invalid",
                ]
            )
        self.assertNotEqual(exit_code, 0)
        self.assertIn('"safeReasons":["LIVE_APPROVAL_REQUIRED"]', output.getvalue())

    def test_cli_empty_and_whitespace_approval_block_without_stdin_or_network(self):
        class RejectingInput:
            def read(self, *args, **kwargs):
                raise AssertionError("stdin read is forbidden")

            def readline(self, *args, **kwargs):
                raise AssertionError("stdin readline is forbidden")

        invalid_values = (
            "",
            " ",
            approval() + " ",
            " " + approval(),
            approval() + "\n",
        )
        for invalid in invalid_values:
            with self.subTest(repr=repr(invalid)):
                output = StringIO()
                error = StringIO()
                started = time.monotonic()
                with (
                    patch("sys.stdout", output),
                    patch("sys.stderr", error),
                    patch("sys.stdin", RejectingInput()),
                    patch.object(
                        IsolatedSmokeTestRunner,
                        "run",
                        side_effect=AssertionError("runner must not be built"),
                    ),
                    patch.object(
                        socket,
                        "socket",
                        side_effect=AssertionError("network forbidden"),
                    ),
                    patch.object(
                        socket,
                        "create_connection",
                        side_effect=AssertionError("network forbidden"),
                    ),
                    patch.object(
                        socket,
                        "getaddrinfo",
                        side_effect=AssertionError("network forbidden"),
                    ),
                ):
                    exit_code = main(
                        [
                            "--mode",
                            "LIVE_ONE_SHOT",
                            "--live-one-shot-approval",
                            invalid,
                        ]
                    )
                self.assertLess(time.monotonic() - started, 1.0)
                self.assertNotEqual(exit_code, 0)
                self.assertIn(
                    '"safeReasons":["LIVE_APPROVAL_REQUIRED"]',
                    output.getvalue(),
                )
                self.assertNotIn(approval(), output.getvalue())
                self.assertNotIn(approval(), error.getvalue())

    def test_cli_exact_single_live_approval_reaches_runner_once(self):
        output = StringIO()
        approved = smoke_result(
            status=SmokePreflightStatus.BLOCKED,
            reason="KILL_SWITCH_ACTIVE",
        )
        with (
            patch("sys.stdout", output),
            patch.object(
                IsolatedSmokeTestRunner,
                "run",
                return_value=approved,
            ) as run,
        ):
            exit_code = main(
                [
                    "--mode",
                    "LIVE_ONE_SHOT",
                    "--live-one-shot-approval",
                    approval(),
                ]
            )
        self.assertNotEqual(exit_code, 0)
        run.assert_called_once()
        self.assertEqual(run.call_args.kwargs["live_approval"], approval())
        self.assertNotIn(approval(), output.getvalue())

    def test_cli_duplicate_live_approval_blocks_before_runner(self):
        output = StringIO()
        with (
            patch("sys.stdout", output),
            patch.object(
                IsolatedSmokeTestRunner,
                "run",
                side_effect=AssertionError("runner must not be built"),
            ),
        ):
            exit_code = main(
                [
                    "--mode",
                    "LIVE_ONE_SHOT",
                    "--live-one-shot-approval",
                    approval(),
                    "--live-one-shot-approval",
                    approval(),
                ]
            )
        self.assertNotEqual(exit_code, 0)
        self.assertIn('"safeReasons":["LIVE_APPROVAL_REQUIRED"]', output.getvalue())

    def test_cli_rejects_live_approval_for_non_live_mode(self):
        output = StringIO()
        with (
            patch("sys.stdout", output),
            patch.object(
                IsolatedSmokeTestRunner,
                "run",
                side_effect=AssertionError("runner must not be built"),
            ),
        ):
            exit_code = main(
                [
                    "--mode",
                    "DRY_RUN",
                    "--live-one-shot-approval",
                    approval(),
                ]
            )
        self.assertNotEqual(exit_code, 0)
        self.assertIn(
            '"safeReasons":["LIVE_APPROVAL_NOT_ALLOWED"]',
            output.getvalue(),
        )

    def test_exit_code_zero_is_limited_to_completed_results(self):
        completed = (
            smoke_result(
                mode=SmokeTestMode.DRY_RUN,
                status=SmokePreflightStatus.READY_FOR_CONFIGURATION,
                composition_built=True,
                reason="DRY_RUN_COMPLETE",
            ),
            smoke_result(
                status=SmokePreflightStatus.READY_FOR_CONFIGURATION,
                composition_built=True,
                attempted=True,
                succeeded=True,
                reason="LIVE_ONE_SHOT_COMPLETE",
            ),
            smoke_result(
                status=SmokePreflightStatus.READY_FOR_CONFIGURATION,
                composition_built=True,
                attempted=True,
                succeeded=True,
                reason="USAGE_UNAVAILABLE",
            ),
        )
        for result in completed:
            with self.subTest(result=result):
                self.assertEqual(smoke_result_exit_code(result), 0)

        non_successes = (
            (SmokePreflightStatus.BLOCKED, "LIVE_APPROVAL_REQUIRED"),
            (SmokePreflightStatus.BLOCKED, "CREDENTIAL_NOT_PRESENT"),
            (SmokePreflightStatus.BLOCKED, "KILL_SWITCH_ACTIVE"),
            (SmokePreflightStatus.BLOCKED, "ONE_SHOT_PERMIT_DENIED"),
            (SmokePreflightStatus.BLOCKED, "TIMEOUT"),
            (SmokePreflightStatus.BLOCKED, "PROVIDER_FAILED"),
            (SmokePreflightStatus.BLOCKED, "VALIDATION_FAILED"),
            (SmokePreflightStatus.BLOCKED, "MALFORMED_RESPONSE"),
            (SmokePreflightStatus.CONFIGURATION_INVALID, "CONFIGURATION_INVALID"),
            (
                SmokePreflightStatus.CREDENTIAL_REFERENCE_NOT_READY,
                "CREDENTIAL_REFERENCE_NOT_READY",
            ),
            (SmokePreflightStatus.MODEL_DECISION_REQUIRED, "MODEL_DECISION_REQUIRED"),
        )
        for status, reason in non_successes:
            with self.subTest(status=status, reason=reason):
                self.assertNotEqual(
                    smoke_result_exit_code(smoke_result(status=status, reason=reason)),
                    0,
                )

        inconsistent_ready = smoke_result(
            status=SmokePreflightStatus.READY_FOR_CONFIGURATION,
            composition_built=True,
            attempted=True,
            succeeded=False,
            reason="LIVE_ONE_SHOT_FAILED",
        )
        self.assertNotEqual(smoke_result_exit_code(inconsistent_ready), 0)

    def test_cli_unexpected_exception_is_safe_json_and_nonzero(self):
        output = StringIO()
        error = StringIO()
        secret = "sk-offline-unexpected-secret"
        with (
            patch("sys.stdout", output),
            patch("sys.stderr", error),
            patch.object(
                IsolatedSmokeTestRunner,
                "run",
                side_effect=RuntimeError(secret),
            ),
        ):
            exit_code = main([])
        rendered = output.getvalue()
        self.assertNotEqual(exit_code, 0)
        self.assertIn('"status":"BLOCKED"', rendered)
        self.assertIn('"safeReasons":["UNEXPECTED_FAILURE"]', rendered)
        self.assertNotIn(secret, rendered)
        self.assertNotIn(secret, error.getvalue())
        self.assertNotIn("Traceback", rendered + error.getvalue())

    def test_process_scoped_mapping_is_fixed_and_does_not_mutate_environment(self):
        keys = (
            "AI_ADVISOR_ENDPOINT_ENABLED",
            "AI_ADVISOR_NETWORK_ALLOWED",
            "AI_ADVISOR_LIVE_TEST_ALLOWED",
            "AI_ADVISOR_LIVE_KILL_SWITCH",
            "AI_ADVISOR_AUTH_CREDENTIAL_ID",
            "AI_ADVISOR_CREDENTIAL_ID",
            "AI_ADVISOR_MODEL",
            "AI_ADVISOR_BASE_URL",
            "AI_ADVISOR_LIVE_MAX_OUTPUT_TOKENS",
            "AI_ADVISOR_PROVIDER_TIMEOUT_SECONDS",
            "AI_ADVISOR_ENDPOINT_TIMEOUT_SECONDS",
        )
        before = {key: os.environ.get(key) for key in keys}
        mapping = isolated_non_secret_environment()
        self.assertEqual(mapping["AI_ADVISOR_MODEL"], "gpt-4o-mini")
        self.assertEqual(mapping["AI_ADVISOR_LIVE_MAX_OUTPUT_TOKENS"], "512")
        self.assertEqual(
            mapping["AI_ADVISOR_BASE_URL"],
            "https://api.openai.com/v1",
        )
        self.assertEqual(mapping["AI_ADVISOR_ENDPOINT_ENABLED"], "true")
        self.assertEqual(mapping["AI_ADVISOR_NETWORK_ALLOWED"], "true")
        self.assertEqual(mapping["AI_ADVISOR_LIVE_TEST_ALLOWED"], "true")
        self.assertEqual(mapping["AI_ADVISOR_LIVE_KILL_SWITCH"], "false")
        with self.assertRaises(TypeError):
            mapping["AI_ADVISOR_MODEL"] = "changed"
        self.assertEqual(
            {key: os.environ.get(key) for key in keys},
            before,
        )

    def test_reference_preflight_never_resolves_secret_and_is_unverified(self):
        mapping = isolated_non_secret_environment()
        loaded = EnvironmentProductionConfigLoader(environmentReader=mapping.get).load()
        self.assertTrue(loaded.succeeded)
        preflight = inspect_credential_references(
            configuration=loaded.configuration,
            allowed_authentication_ids=("AI_ADVISOR_AUTH_TOKEN",),
            allowed_provider_ids=("OPENAI_API_KEY",),
        )
        self.assertEqual(
            preflight.authenticationReference,
            CredentialReferenceStatus.REFERENCE_ALLOWED,
        )
        self.assertEqual(
            preflight.providerReference,
            CredentialReferenceStatus.REFERENCE_ALLOWED,
        )
        self.assertEqual(
            preflight.authenticationSource,
            CredentialSourceStatus.SOURCE_AVAILABLE,
        )
        self.assertEqual(
            preflight.providerSource,
            CredentialSourceStatus.SOURCE_AVAILABLE,
        )
        self.assertEqual(
            preflight.authenticationAvailability,
            CredentialAvailabilityStatus.AVAILABILITY_UNVERIFIED,
        )
        self.assertEqual(
            preflight.providerAvailability,
            CredentialAvailabilityStatus.AVAILABILITY_UNVERIFIED,
        )
        rendered = preflight.model_dump_json()
        self.assertNotIn("AI_ADVISOR_AUTH_TOKEN", rendered)
        self.assertNotIn("OPENAI_API_KEY", rendered)

    def test_failure_shutdown_sequence_is_deterministic_and_forbids_retry(self):
        first = isolated_failure_shutdown_steps()
        second = isolated_failure_shutdown_steps()
        self.assertEqual(first, second)
        self.assertEqual(first[0], "DO_NOT_RETRY")
        self.assertIn("DO_NOT_REGENERATE_PERMIT", first)
        self.assertIn("TERMINATE_ISOLATED_PROCESS", first)
        self.assertNotIn("RETRY", first[1:])


if __name__ == "__main__":
    unittest.main()
