import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from backend.ai_advisor.credential_loader import InjectedCredentialLoader
from backend.ai_advisor.live_connectivity import (
    OPENAI_OFFICIAL_ENDPOINT,
    AtomicOneShotPermit,
    InteractiveConnectivityGate,
    InteractiveConnectivityPolicy,
    LiveConnectivityFailureCode,
    LiveConnectivityGate,
    LiveConnectivityPolicy,
)
from backend.ai_advisor.openai_sdk_transport import OpenAISDKTransport
from backend.ai_advisor.provider_config import ProviderName
from backend.ai_advisor.provider_transport import (
    OpenAITransportConfigurationError,
    OpenAITransportRequest,
    OpenAITransportTimeout,
)
from tests.test_ai_advisor_openai_sdk_transport import (
    FakeClient,
    FakeClientFactory,
    FakeResponse,
    FakeResponses,
)
from tests.test_ai_advisor_provider import connection_config
from tests.test_ai_advisor_provider_contract import fixture_text


def policy(**overrides):
    values = dict(
        endpointEnabled=True,
        networkInvocationAllowed=True,
        liveTestExplicitlyAllowed=True,
        killSwitchActive=False,
        authenticationReady=True,
        providerReady=True,
        credentialReferenceReady=True,
        provider=ProviderName.OPENAI,
        model="openai-advisor-model",
        allowedModels=("openai-advisor-model",),
        providerEndpoint=OPENAI_OFFICIAL_ENDPOINT,
        allowedProviderEndpoints=(OPENAI_OFFICIAL_ENDPOINT,),
        maximumLiveTestRequests=1,
        maximumInputBytes=4096,
        maximumInputTokens=4096,
        maximumOutputTokens=2048,
        timeoutSeconds=30.0,
        retryCount=0,
        streamingAllowed=False,
        toolCallingAllowed=False,
        backgroundInvocationAllowed=False,
        batchInvocationAllowed=False,
    )
    values.update(overrides)
    return LiveConnectivityPolicy(**values)


def interactive_policy(**overrides):
    values = policy().model_dump(
        exclude={"liveTestExplicitlyAllowed", "maximumLiveTestRequests"}
    )
    values["interactiveInvocationExplicitlyAllowed"] = True
    values.update(overrides)
    return InteractiveConnectivityPolicy(**values)


def transport_request(**overrides):
    values = dict(
        model="openai-advisor-model",
        input="fixed offline prompt",
        timeoutSeconds=30.0,
        maxOutputTokens=2048,
        temperature=0.0,
        responseFormat="json_object",
        stream=False,
    )
    values.update(overrides)
    return OpenAITransportRequest(**values)


class LiveConnectivityGateTest(unittest.TestCase):
    def test_interactive_gate_allows_multiple_requests_without_one_shot_permit(self):
        gate = InteractiveConnectivityGate(interactive_policy())
        self.assertFalse(hasattr(gate, "permit"))
        results = [gate.authorize(transport_request()) for _ in range(3)]
        self.assertTrue(all(result.allowed for result in results))

    def test_live_test_permit_does_not_reduce_interactive_capacity(self):
        live_gate = LiveConnectivityGate(policy())
        interactive_gate = InteractiveConnectivityGate(interactive_policy())
        self.assertTrue(live_gate.authorize(transport_request()).allowed)
        self.assertFalse(live_gate.authorize(transport_request()).allowed)
        self.assertTrue(interactive_gate.authorize(transport_request()).allowed)
        self.assertTrue(interactive_gate.authorize(transport_request()).allowed)
        self.assertTrue(interactive_gate.authorize(transport_request()).allowed)
    def test_default_and_each_missing_condition_fail_closed(self):
        cases = (
            (
                {"endpointEnabled": False},
                LiveConnectivityFailureCode.LIVE_DISABLED,
            ),
            (
                {"networkInvocationAllowed": False},
                LiveConnectivityFailureCode.LIVE_DISABLED,
            ),
            (
                {"liveTestExplicitlyAllowed": False},
                LiveConnectivityFailureCode.LIVE_DISABLED,
            ),
            (
                {"authenticationReady": False},
                LiveConnectivityFailureCode.AUTHENTICATION_NOT_READY,
            ),
            (
                {"providerReady": False},
                LiveConnectivityFailureCode.PROVIDER_NOT_READY,
            ),
            (
                {"credentialReferenceReady": False},
                LiveConnectivityFailureCode.CREDENTIAL_NOT_READY,
            ),
            (
                {"allowedModels": ("another-model",)},
                LiveConnectivityFailureCode.MODEL_NOT_ALLOWED,
            ),
            (
                {"providerEndpoint": "https://private.example/v1"},
                LiveConnectivityFailureCode.ENDPOINT_NOT_ALLOWED,
            ),
        )
        for changes, code in cases:
            gate = LiveConnectivityGate(policy(**changes))
            result = gate.authorize_and_acquire(transport_request())
            self.assertFalse(result.allowed)
            self.assertEqual(result.failureCode, code)
            self.assertEqual(gate.permit.consumed, 0)

    def test_kill_switch_has_highest_priority(self):
        gate = LiveConnectivityGate(
            policy(
                killSwitchActive=True,
                endpointEnabled=False,
                networkInvocationAllowed=False,
                liveTestExplicitlyAllowed=False,
                authenticationReady=False,
                providerReady=False,
                credentialReferenceReady=False,
            )
        )
        result = gate.authorize_and_acquire(transport_request(model="wrong-model"))
        self.assertEqual(
            result.failureCode,
            LiveConnectivityFailureCode.KILL_SWITCH_ACTIVE,
        )
        self.assertEqual(gate.permit.consumed, 0)

    def test_model_endpoint_and_token_budgets_are_server_side(self):
        cases = (
            (
                transport_request(model="client-model"),
                LiveConnectivityFailureCode.MODEL_NOT_ALLOWED,
            ),
            (
                transport_request(input="x" * 4097),
                LiveConnectivityFailureCode.TOKEN_BUDGET_INVALID,
            ),
            (
                transport_request(maxOutputTokens=2049),
                LiveConnectivityFailureCode.TOKEN_BUDGET_INVALID,
            ),
            (
                transport_request(timeoutSeconds=29.0),
                LiveConnectivityFailureCode.TOKEN_BUDGET_INVALID,
            ),
        )
        for request, expected in cases:
            result = LiveConnectivityGate(policy()).authorize_and_acquire(request)
            self.assertFalse(result.allowed)
            self.assertEqual(result.failureCode, expected)

    def test_one_shot_permit_is_atomic_and_never_returns(self):
        gate = LiveConnectivityGate(policy())
        barrier = threading.Barrier(2)

        def invoke():
            barrier.wait(timeout=1)
            return gate.authorize_and_acquire(transport_request())

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: invoke(), range(2)))
        self.assertEqual(sum(result.allowed for result in results), 1)
        self.assertEqual(gate.permit.consumed, 1)
        third = gate.authorize_and_acquire(transport_request())
        self.assertFalse(third.allowed)
        self.assertEqual(
            third.failureCode,
            LiveConnectivityFailureCode.REQUEST_BUDGET_EXHAUSTED,
        )

    def test_corrupted_counter_fails_closed(self):
        permit = AtomicOneShotPermit()
        permit._consumed = -5
        gate = LiveConnectivityGate(policy(), permit=permit)
        result = gate.authorize_and_acquire(transport_request())
        self.assertFalse(result.allowed)
        self.assertEqual(
            result.failureCode,
            LiveConnectivityFailureCode.REQUEST_BUDGET_EXHAUSTED,
        )

    def test_policy_and_failure_serialization_exclude_secrets(self):
        secret_endpoint = "https://user:password@private.example"
        value = policy(
            killSwitchActive=True,
            providerEndpoint=secret_endpoint,
            allowedProviderEndpoints=(secret_endpoint,),
        )
        result = LiveConnectivityGate(value).authorize_and_acquire(transport_request())
        rendered = (
            repr(value)
            + value.model_dump_json()
            + repr(result)
            + result.model_dump_json()
        )
        self.assertNotIn("password", rendered)
        self.assertNotIn("private.example", rendered)


class LiveGateTransportIntegrationTest(unittest.TestCase):
    def build(self, gate, *, response=None, exception=None):
        loader = InjectedCredentialLoader(
            {"advisor-openai-primary": "offline-provider-placeholder"}
        )
        responses = FakeResponses(response=response, exception=exception)
        factory = FakeClientFactory(FakeClient(responses))
        transport = OpenAISDKTransport(
            config=connection_config(
                endpoint=OPENAI_OFFICIAL_ENDPOINT,
                maxOutputTokens=2048,
            ),
            credentialLoader=loader,
            clientFactory=factory,
            allowNetworkInvocation=True,
            liveConnectivityGate=gate,
        )
        return transport, loader, factory, responses

    def test_denial_happens_before_credential_and_provider(self):
        gate = LiveConnectivityGate(policy(liveTestExplicitlyAllowed=False))
        value, loader, factory, responses = self.build(gate)
        with self.assertRaises(OpenAITransportConfigurationError):
            value.invoke(transport_request())
        self.assertEqual(loader.calls, 0)
        self.assertEqual(factory.calls, 0)
        self.assertEqual(responses.calls, [])
        self.assertEqual(gate.permit.consumed, 0)

    def test_all_conditions_allow_exactly_one_provider_call(self):
        gate = LiveConnectivityGate(policy())
        value, loader, factory, responses = self.build(
            gate,
            response=FakeResponse(fixture_text()),
        )
        result = value.invoke(transport_request())
        self.assertEqual(result["output_text"], fixture_text())
        self.assertEqual(loader.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)
        with self.assertRaises(OpenAITransportConfigurationError):
            value.invoke(transport_request())
        self.assertEqual(loader.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)

    def test_exception_consumes_permit_without_retry_or_return(self):
        gate = LiveConnectivityGate(policy())
        value, loader, factory, responses = self.build(
            gate,
            exception=RuntimeError(
                "sk-test-secret /home/private provider-response-secret"
            ),
        )
        with self.assertRaises(Exception) as caught:
            value.invoke(transport_request())
        rendered = repr(caught.exception) + str(caught.exception)
        self.assertNotIn("sk-test-secret", rendered)
        self.assertNotIn("/home/private", rendered)
        self.assertEqual(gate.permit.consumed, 1)
        self.assertEqual(len(responses.calls), 1)
        with self.assertRaises(OpenAITransportConfigurationError):
            value.invoke(transport_request())
        self.assertEqual(len(responses.calls), 1)

    def test_timeout_consumes_permit_without_retry_or_return(self):
        gate = LiveConnectivityGate(policy())
        value, loader, factory, responses = self.build(
            gate,
            exception=OpenAITransportTimeout("offline timeout"),
        )
        with self.assertRaises(OpenAITransportTimeout):
            value.invoke(transport_request())
        self.assertEqual(gate.permit.consumed, 1)
        self.assertEqual(loader.calls, 1)
        self.assertEqual(factory.calls, 1)
        self.assertEqual(len(responses.calls), 1)
        with self.assertRaises(OpenAITransportConfigurationError):
            value.invoke(transport_request())
        self.assertEqual(len(responses.calls), 1)


if __name__ == "__main__":
    unittest.main()
