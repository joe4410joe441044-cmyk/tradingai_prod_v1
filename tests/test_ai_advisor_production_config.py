import json
import os
import unittest
from unittest.mock import patch

from backend.ai_advisor.production_config_loader import (
    ENVIRONMENT_KEYS,
    EnvironmentProductionConfigLoader,
    InjectedProductionConfigLoader,
)
from backend.ai_advisor.production_config_models import (
    ProductionConfigFailureCode,
    ProductionConfigSource,
)


class ProductionConfigTest(unittest.TestCase):
    def test_safe_default_is_disabled_without_environment_reads_at_import(self):
        calls = []
        loader = EnvironmentProductionConfigLoader(
            environmentReader=lambda name: calls.append(name) or None
        )
        result = loader.load()
        self.assertTrue(result.succeeded)
        self.assertFalse(result.configuration.endpointEnabled)
        self.assertFalse(result.configuration.networkInvocationAllowed)
        self.assertEqual(
            result.configuration.source, ProductionConfigSource.ENVIRONMENT
        )
        self.assertEqual(set(calls), set(ENVIRONMENT_KEYS.values()))

    def test_strict_boolean_policy(self):
        for accepted, expected in (("true", True), ("false", False)):
            result = InjectedProductionConfigLoader(
                {"endpointEnabled": accepted}
            ).load()
            self.assertTrue(result.succeeded)
            self.assertIs(result.configuration.endpointEnabled, expected)
        for rejected in (
            "TRUE",
            "False",
            "1",
            "0",
            "yes",
            "no",
            " ",
            "",
        ):
            result = InjectedProductionConfigLoader(
                {"endpointEnabled": rejected}
            ).load()
            self.assertFalse(result.succeeded)
            self.assertEqual(
                result.failureCode,
                ProductionConfigFailureCode.AI_ADVISOR_CONFIG_INVALID,
            )

    def test_valid_offline_and_live_reference_configuration(self):
        offline = InjectedProductionConfigLoader(
            {
                "endpointEnabled": "true",
                "networkInvocationAllowed": "false",
                "authenticationCredentialId": "auth-ref",
                "model": "openai-advisor-model",
            }
        ).load()
        self.assertTrue(offline.succeeded)
        self.assertTrue(offline.configuration.endpointEnabled)
        self.assertFalse(offline.configuration.networkInvocationAllowed)

        live = InjectedProductionConfigLoader(
            {
                "endpointEnabled": "true",
                "networkInvocationAllowed": "true",
                "authenticationCredentialId": "auth-ref",
                "credentialId": "provider-ref",
                "model": "openai-advisor-model",
                "baseUrl": "https://api.openai.example/v1",
            }
        ).load()
        self.assertTrue(live.succeeded)
        self.assertTrue(live.configuration.networkInvocationAllowed)

    def test_invalid_numeric_and_unknown_configuration_fail_closed(self):
        cases = (
            {"providerTimeoutSeconds": "0"},
            {
                "providerTimeoutSeconds": "30",
                "endpointTimeoutSeconds": "30",
            },
            {"rateLimitMaxRequests": "0"},
            {"concurrencyLimit": "0"},
            {"requestSizeLimitBytes": "0"},
            {"providerTimeoutSeconds": "30.5"},
            {"unknownField": "value"},
            {
                "endpointEnabled": "false",
                "networkInvocationAllowed": "true",
            },
        )
        for values in cases:
            result = InjectedProductionConfigLoader(values).load()
            self.assertFalse(result.succeeded)
            self.assertIsNone(result.configuration)

    def test_environment_is_not_mutated_and_only_fixed_keys_are_read(self):
        before = dict(os.environ)
        with patch.dict(
            os.environ,
            {
                "AI_ADVISOR_ENDPOINT_ENABLED": "false",
                "UNRELATED_SECRET": "must-not-be-read",
            },
            clear=True,
        ):
            result = EnvironmentProductionConfigLoader().load()
        self.assertTrue(result.succeeded)
        self.assertEqual(before, dict(os.environ))

    def test_secret_references_and_base_url_are_not_serialized(self):
        secret = "sk-test-provider-secret"
        result = InjectedProductionConfigLoader(
            {
                "endpointEnabled": "true",
                "networkInvocationAllowed": "true",
                "authenticationCredentialId": "auth-reference-secret",
                "credentialId": "provider-reference-secret",
                "baseUrl": "https://private-provider.example/v1",
            }
        ).load()
        rendered = (
            repr(result)
            + result.model_dump_json()
            + repr(result.configuration)
            + result.configuration.model_dump_json()
        )
        for forbidden in (
            secret,
            "auth-reference-secret",
            "provider-reference-secret",
            "private-provider.example",
        ):
            self.assertNotIn(forbidden, rendered)
        json.loads(result.model_dump_json())


if __name__ == "__main__":
    unittest.main()
