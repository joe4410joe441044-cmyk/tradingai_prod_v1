import json
import os
import pickle
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from backend.ai_advisor.credential_loader import (
    CredentialFailureCode,
    CredentialResolutionInput,
    CredentialResolutionStatus,
    EnvironmentCredentialLoader,
    InjectedCredentialLoader,
)
from backend.ai_advisor.provider_config import (
    CredentialReference,
    CredentialSource,
    ProviderName,
)
from backend.ai_advisor.provider_invocation_guard import (
    InvocationGuardInput,
    InvocationGuardReason,
    evaluate_invocation_guard,
)


def resolution_input(source=CredentialSource.ENVIRONMENT, **overrides):
    values = dict(
        credentialReference=CredentialReference(
            credentialId="AI_ADVISOR_OPENAI_API_KEY",
            source=source,
        ),
        provider=ProviderName.OPENAI,
        allowEnvironmentRead=source is CredentialSource.ENVIRONMENT,
    )
    values.update(overrides)
    return CredentialResolutionInput(**values)


class CredentialLoaderTest(unittest.TestCase):
    def test_environment_loader_reads_only_explicit_allowlisted_reference(self):
        key = "AI_ADVISOR_OPENAI_API_KEY"
        before = dict(os.environ)
        with patch.dict(os.environ, {key: "test-credential-value"}, clear=False):
            loader = EnvironmentCredentialLoader((key,))
            result = loader.resolve(resolution_input())
        self.assertEqual(result.status, CredentialResolutionStatus.SUCCEEDED)
        self.assertTrue(result.credential.is_present)
        for rendered in (repr(result), str(result), repr(result.credential)):
            self.assertNotIn("test-credential-value", rendered)
        self.assertEqual({k: v for k, v in before.items()}, dict(os.environ))

    def test_environment_failure_modes_are_typed_and_safe(self):
        cases = (
            (
                EnvironmentCredentialLoader(
                    ("AI_ADVISOR_OPENAI_API_KEY",), lambda name: None
                ),
                resolution_input(),
                CredentialFailureCode.CREDENTIAL_NOT_FOUND,
            ),
            (
                EnvironmentCredentialLoader(
                    ("AI_ADVISOR_OPENAI_API_KEY",), lambda name: " "
                ),
                resolution_input(),
                CredentialFailureCode.CREDENTIAL_EMPTY,
            ),
            (
                EnvironmentCredentialLoader(
                    ("AI_ADVISOR_OPENAI_API_KEY",), lambda name: "value"
                ),
                resolution_input(source=CredentialSource.INJECTED),
                CredentialFailureCode.CREDENTIAL_SOURCE_NOT_ALLOWED,
            ),
            (
                EnvironmentCredentialLoader(
                    ("OTHER_ALLOWED_ID",), lambda name: "value"
                ),
                resolution_input(),
                CredentialFailureCode.CREDENTIAL_ACCESS_DENIED,
            ),
            (
                EnvironmentCredentialLoader(
                    ("AI_ADVISOR_OPENAI_API_KEY",), lambda name: "value"
                ),
                resolution_input(allowEnvironmentRead=False),
                CredentialFailureCode.CREDENTIAL_ACCESS_DENIED,
            ),
        )
        for loader, value, code in cases:
            result = loader.resolve(value)
            self.assertEqual(result.failureCode, code)
            self.assertEqual(result.safeMessage, "advisor credential unavailable")
            self.assertNotIn("AI_ADVISOR_OPENAI_API_KEY", repr(result))

    def test_injected_loader_count_failure_and_non_serializable_credential(self):
        secret = "sk-test-secret-value"
        loader = InjectedCredentialLoader({"AI_ADVISOR_OPENAI_API_KEY": secret})
        value = resolution_input(source=CredentialSource.INJECTED)
        before = value.model_dump_json()
        result = loader.resolve(value)
        self.assertEqual(loader.calls, 1)
        self.assertEqual(value.model_dump_json(), before)
        self.assertEqual(result.status, CredentialResolutionStatus.SUCCEEDED)
        self.assertNotIn(secret, repr(loader) + repr(result) + str(result.credential))
        with self.assertRaises(TypeError):
            pickle.dumps(result.credential)
        with self.assertRaises(TypeError):
            json.dumps(result.credential)

        failing = InjectedCredentialLoader(
            {},
            fixedFailure=CredentialFailureCode.CREDENTIAL_INTERNAL_FAILURE,
        )
        failure = failing.resolve(value)
        self.assertEqual(failing.calls, 1)
        self.assertEqual(
            failure.failureCode,
            CredentialFailureCode.CREDENTIAL_INTERNAL_FAILURE,
        )

    def test_resolution_input_is_frozen_strict_and_unknown_fields_fail(self):
        value = resolution_input()
        with self.assertRaises(ValidationError):
            resolution_input(allowEnvironmentRead=1)
        with self.assertRaises(ValidationError):
            CredentialResolutionInput(
                **value.model_dump(),
                unexpected=True,
            )
        with self.assertRaises(ValidationError):
            value.provider = ProviderName.MOCK


class InvocationGuardTest(unittest.TestCase):
    def valid_input(self, **overrides):
        values = dict(
            providerEnabled=True,
            provider=ProviderName.OPENAI,
            networkInvocationAllowed=True,
            credentialResolved=True,
            transportConfigured=True,
            configurationValid=True,
        )
        values.update(overrides)
        return InvocationGuardInput(**values)

    def test_all_conditions_required_and_result_is_deterministic(self):
        allowed = evaluate_invocation_guard(self.valid_input())
        self.assertTrue(allowed.allowed)
        self.assertEqual(allowed.reasonCode, InvocationGuardReason.ALLOWED)
        cases = (
            (
                {"networkInvocationAllowed": False},
                InvocationGuardReason.NETWORK_INVOCATION_DISABLED,
            ),
            ({"providerEnabled": False}, InvocationGuardReason.PROVIDER_DISABLED),
            (
                {"provider": ProviderName.MOCK},
                InvocationGuardReason.PROVIDER_NOT_OPENAI,
            ),
            (
                {"credentialResolved": False},
                InvocationGuardReason.CREDENTIAL_UNAVAILABLE,
            ),
            (
                {"transportConfigured": False},
                InvocationGuardReason.TRANSPORT_UNAVAILABLE,
            ),
            (
                {"configurationValid": False},
                InvocationGuardReason.CONFIGURATION_INVALID,
            ),
        )
        for changes, reason in cases:
            value = self.valid_input(**changes)
            first = evaluate_invocation_guard(value)
            second = evaluate_invocation_guard(value)
            self.assertFalse(first.allowed)
            self.assertEqual(first.reasonCode, reason)
            self.assertEqual(first, second)

    def test_guard_strict_bool_and_fail_closed(self):
        with self.assertRaises(ValidationError):
            self.valid_input(networkInvocationAllowed=1)
        bypassed = self.valid_input().model_copy(update={"configurationValid": "true"})
        result = evaluate_invocation_guard(bypassed)
        self.assertFalse(result.allowed)
        self.assertEqual(
            result.reasonCode,
            InvocationGuardReason.CONFIGURATION_INVALID,
        )


if __name__ == "__main__":
    unittest.main()
