import builtins
import json
import socket
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ai_advisor.credential_loader import InjectedCredentialLoader
from backend.ai_advisor.production_composition import (
    build_ai_advisor_production_composition,
)
from backend.ai_advisor.production_config_loader import (
    InjectedProductionConfigLoader,
)
from backend.ai_advisor.production_config_models import (
    ProductionReadinessStatus,
)
from backend.api.ai_advisor import create_advice_router
from tests.test_ai_advisor_api import headers, payload
from tests.test_ai_advisor_openai_sdk_transport import (
    FakeClient,
    FakeClientFactory,
    FakeResponse,
    FakeResponses,
)
from tests.test_ai_advisor_provider_contract import fixture_text

AUTH_TOKEN = "production-test-auth-token"


def configuration_values(*, enabled=True, network=False, **overrides):
    values = {
        "endpointEnabled": "true" if enabled else "false",
        "networkInvocationAllowed": "true" if network else "false",
        "authenticationCredentialId": "auth-ref",
        "credentialId": "provider-ref",
        "model": "openai-advisor-model",
        "baseUrl": "https://api.openai.com/v1",
        "principalId": "principal-1",
    }
    values.update(overrides)
    return values


def build(values, *, auth_loader=None, provider_loader=None, client_factory=None):
    return build_ai_advisor_production_composition(
        config_loader=InjectedProductionConfigLoader(values),
        authentication_credential_loader=auth_loader
        or InjectedCredentialLoader({"auth-ref": AUTH_TOKEN}),
        provider_credential_loader=provider_loader
        or InjectedCredentialLoader({"provider-ref": "offline-provider-placeholder"}),
        allowed_authentication_credential_ids=("auth-ref",),
        allowed_provider_credential_ids=("provider-ref",),
        client_factory=client_factory,
        clock=lambda: 100.0,
    )


def endpoint_client(result):
    app = FastAPI()
    app.include_router(
        create_advice_router(result.apiComposition),
        prefix="/api/ai-advisor",
    )
    return TestClient(app)


def production_headers():
    value = headers()
    value["Authorization"] = f"Bearer {AUTH_TOKEN}"
    return value


class ProductionCompositionTest(unittest.TestCase):
    def test_disabled_composition_resolves_no_credentials(self):
        auth = InjectedCredentialLoader({"auth-ref": AUTH_TOKEN})
        provider = InjectedCredentialLoader(
            {"provider-ref": "offline-provider-placeholder"}
        )
        result = build(
            configuration_values(enabled=False),
            auth_loader=auth,
            provider_loader=provider,
        )
        self.assertTrue(result.succeeded)
        self.assertEqual(result.readiness.status, ProductionReadinessStatus.DISABLED)
        self.assertFalse(result.operationalStatus.enabled)
        self.assertEqual(auth.calls, 0)
        self.assertEqual(provider.calls, 0)
        response = endpoint_client(result).post(
            "/api/ai-advisor/advice",
            json=payload(),
        )
        self.assertEqual(response.status_code, 503)

    def test_offline_composition_resolves_auth_per_request_only(self):
        auth = InjectedCredentialLoader({"auth-ref": AUTH_TOKEN})
        provider = InjectedCredentialLoader(
            {"provider-ref": "offline-provider-placeholder"}
        )
        result = build(
            configuration_values(network=False),
            auth_loader=auth,
            provider_loader=provider,
        )
        self.assertEqual(
            result.readiness.status,
            ProductionReadinessStatus.READY_OFFLINE,
        )
        self.assertTrue(result.readiness.endpointAvailable)
        self.assertFalse(result.readiness.networkInvocationAvailable)
        self.assertEqual(auth.calls, 0)
        self.assertEqual(provider.calls, 0)
        response = endpoint_client(result).post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=production_headers(),
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(auth.calls, 1)
        self.assertEqual(provider.calls, 0)

    def test_live_ready_build_performs_no_credential_or_client_call(self):
        auth = InjectedCredentialLoader({"auth-ref": AUTH_TOKEN})
        provider = InjectedCredentialLoader(
            {"provider-ref": "offline-provider-placeholder"}
        )
        factory = FakeClientFactory(
            FakeClient(FakeResponses(response=FakeResponse(fixture_text())))
        )
        with (
            patch.object(socket, "socket", side_effect=AssertionError),
            patch.object(socket, "create_connection", side_effect=AssertionError),
        ):
            first = build(
                configuration_values(network=True),
                auth_loader=auth,
                provider_loader=provider,
                client_factory=factory,
            )
            second = build(
                configuration_values(network=True),
                auth_loader=auth,
                provider_loader=provider,
                client_factory=factory,
            )
        self.assertEqual(
            first.readiness.status,
            ProductionReadinessStatus.READY_LIVE,
        )
        self.assertEqual(first.readiness, second.readiness)
        self.assertEqual(first.operationalStatus, second.operationalStatus)
        self.assertEqual(auth.calls, 0)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(factory.calls, 0)

    def test_live_ready_offline_client_endpoint_succeeds(self):
        auth = InjectedCredentialLoader({"auth-ref": AUTH_TOKEN})
        provider = InjectedCredentialLoader(
            {"provider-ref": "offline-provider-placeholder"}
        )
        responses = FakeResponses(response=FakeResponse(fixture_text()))
        factory = FakeClientFactory(FakeClient(responses))
        result = build(
            configuration_values(
                network=True,
                liveTestExplicitlyAllowed="true",
                liveKillSwitchActive="false",
            ),
            auth_loader=auth,
            provider_loader=provider,
            client_factory=factory,
        )
        response = endpoint_client(result).post(
            "/api/ai-advisor/advice",
            content=json.dumps(payload()),
            headers=production_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(auth.calls, 1)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)

    def test_missing_references_have_fixed_readiness(self):
        missing_auth = build(
            {
                "endpointEnabled": "true",
                "networkInvocationAllowed": "false",
            }
        )
        self.assertEqual(
            missing_auth.readiness.status,
            ProductionReadinessStatus.AUTHENTICATION_UNAVAILABLE,
        )
        self.assertFalse(missing_auth.readiness.endpointAvailable)

        missing_provider = build(
            {
                "endpointEnabled": "true",
                "networkInvocationAllowed": "true",
                "authenticationCredentialId": "auth-ref",
            }
        )
        self.assertEqual(
            missing_provider.readiness.status,
            ProductionReadinessStatus.CREDENTIAL_UNAVAILABLE,
        )
        self.assertFalse(missing_provider.readiness.networkInvocationAvailable)

    def test_invalid_and_composition_failure_are_safe(self):
        invalid = build({"endpointEnabled": "TRUE"})
        self.assertFalse(invalid.succeeded)
        self.assertEqual(
            invalid.readiness.status,
            ProductionReadinessStatus.CONFIGURATION_INVALID,
        )

        failed = build(
            configuration_values(
                network=True,
                baseUrl="https://user:password@private.example",
            )
        )
        self.assertFalse(failed.succeeded)
        rendered = (
            repr(failed)
            + repr(failed.readiness)
            + failed.operationalStatus.model_dump_json()
            + str(failed.safeMessage)
        )
        for fragment in (
            "password",
            "private.example",
            "auth-ref",
            "provider-ref",
        ):
            self.assertNotIn(fragment, rendered)

    def test_module_import_and_composition_do_not_read_environment(self):
        with (
            patch.object(builtins, "open", side_effect=AssertionError),
            patch.object(os := __import__("os"), "getenv", side_effect=AssertionError),
            patch.object(socket, "socket", side_effect=AssertionError),
        ):
            result = build(configuration_values(network=False))
        self.assertEqual(
            result.readiness.status,
            ProductionReadinessStatus.READY_OFFLINE,
        )


if __name__ == "__main__":
    unittest.main()
