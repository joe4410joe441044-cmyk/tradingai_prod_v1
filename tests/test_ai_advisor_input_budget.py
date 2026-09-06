"""Regression tests for the AI Advisor provider input-budget repair (Q1).

The Q1 ADVISOR_PROVIDER_FAILURE was caused by the fail-closed
``InteractiveConnectivityGate`` rejecting the serialized overall-state prompt
(16,414 bytes) because the default ``liveMaximumInputBytes``/``liveMaximumInputTokens``
budget (16,384) was below it, before any network call.
"""

import json
import unittest
from datetime import datetime, timezone

from backend.ai_advisor.live_connectivity import (
    OPENAI_OFFICIAL_ENDPOINT,
    InteractiveConnectivityGate,
    InteractiveConnectivityPolicy,
    LiveConnectivityFailureCode,
)
from backend.ai_advisor.production_config_loader import (
    EnvironmentProductionConfigLoader,
)
from backend.ai_advisor.production_config_models import (
    AIAdvisorProductionConfig,
    DEFAULT_LIVE_MAX_INPUT_BYTES,
    DEFAULT_LIVE_MAX_INPUT_TOKENS,
    ProductionConfigSource,
)
from backend.ai_advisor.provider_config import ProviderName
from backend.ai_advisor.provider_transport import OpenAITransportRequest

# Canonical serialized prompt sizes reconstructed from the local acceptance
# pipeline (approved specs + representative acceptance runtime snapshot).
Q1_INPUT_BYTES = 16_414
Q2_INPUT_BYTES = 16_345
Q3_INPUT_BYTES = 16_090
OLD_MAX_INPUT_BYTES = 16_384
NEW_MAX_INPUT_BYTES = DEFAULT_LIVE_MAX_INPUT_BYTES


def _policy(input_bytes: int, input_tokens: int) -> InteractiveConnectivityPolicy:
    return InteractiveConnectivityPolicy(
        endpointEnabled=True,
        networkInvocationAllowed=True,
        interactiveInvocationExplicitlyAllowed=True,
        killSwitchActive=False,
        authenticationReady=True,
        providerReady=True,
        credentialReferenceReady=True,
        provider=ProviderName.OPENAI,
        model="gpt-4o-mini",
        allowedModels=("gpt-4o-mini",),
        providerEndpoint=OPENAI_OFFICIAL_ENDPOINT,
        allowedProviderEndpoints=(OPENAI_OFFICIAL_ENDPOINT,),
        maximumInputBytes=input_bytes,
        maximumInputTokens=input_tokens,
        maximumOutputTokens=4096,
        timeoutSeconds=30.0,
        retryCount=0,
        streamingAllowed=False,
        toolCallingAllowed=False,
        backgroundInvocationAllowed=False,
        batchInvocationAllowed=False,
    )


def _request(input_bytes: int) -> OpenAITransportRequest:
    return OpenAITransportRequest(
        model="gpt-4o-mini",
        input="x" * input_bytes,
        timeoutSeconds=30.0,
        maxOutputTokens=4096,
        temperature=0.0,
        responseFormat="json_object",
        stream=False,
    )


class InputBudgetRegressionTest(unittest.TestCase):
    def test_old_default_budget_rejects_q1_size_input(self):
        gate = InteractiveConnectivityGate(
            _policy(OLD_MAX_INPUT_BYTES, OLD_MAX_INPUT_BYTES)
        )
        decision = gate.authorize(_request(Q1_INPUT_BYTES))
        self.assertIs(decision.allowed, False)
        self.assertEqual(decision.failureCode, LiveConnectivityFailureCode.TOKEN_BUDGET_INVALID)

    def test_repaired_default_budget_accepts_q1_size_input(self):
        gate = InteractiveConnectivityGate(
            _policy(NEW_MAX_INPUT_BYTES, NEW_MAX_INPUT_BYTES)
        )
        decision = gate.authorize(_request(Q1_INPUT_BYTES))
        self.assertIs(decision.allowed, True)

    def test_repaired_budget_accepts_all_canonical_question_sizes(self):
        gate = InteractiveConnectivityGate(
            _policy(NEW_MAX_INPUT_BYTES, NEW_MAX_INPUT_BYTES)
        )
        for label, size in (
            ("Q1", Q1_INPUT_BYTES),
            ("Q2", Q2_INPUT_BYTES),
            ("Q3", Q3_INPUT_BYTES),
        ):
            with self.subTest(question=label):
                self.assertIs(gate.authorize(_request(size)).allowed, True)

    def test_oversized_input_is_still_rejected_fail_closed(self):
        gate = InteractiveConnectivityGate(
            _policy(NEW_MAX_INPUT_BYTES, NEW_MAX_INPUT_BYTES)
        )
        oversized = Q1_INPUT_BYTES * 3
        self.assertGreater(oversized, NEW_MAX_INPUT_BYTES)
        decision = gate.authorize(_request(oversized))
        self.assertIs(decision.allowed, False)
        self.assertEqual(decision.failureCode, LiveConnectivityFailureCode.TOKEN_BUDGET_INVALID)

    def test_q1_useful_headroom(self):
        headroom = NEW_MAX_INPUT_BYTES - Q1_INPUT_BYTES
        self.assertGreater(headroom, Q1_INPUT_BYTES // 2)
        self.assertEqual(
            headroom,
            DEFAULT_LIVE_MAX_INPUT_BYTES - Q1_INPUT_BYTES,
        )

    def test_defaults_are_coherent_and_bounded(self):
        self.assertEqual(DEFAULT_LIVE_MAX_INPUT_BYTES, DEFAULT_LIVE_MAX_INPUT_TOKENS)
        self.assertLess(DEFAULT_LIVE_MAX_INPUT_BYTES, 65_536)
        self.assertGreaterEqual(DEFAULT_LIVE_MAX_INPUT_BYTES, 32_768)

    def test_loader_uses_repaired_default_when_environment_absent(self):
        result = EnvironmentProductionConfigLoader(
            environmentReader=lambda name: None
        ).load()
        self.assertTrue(result.succeeded)
        self.assertEqual(
            result.configuration.liveMaximumInputBytes, DEFAULT_LIVE_MAX_INPUT_BYTES
        )
        self.assertEqual(
            result.configuration.liveMaximumInputTokens, DEFAULT_LIVE_MAX_INPUT_TOKENS
        )

    def test_environment_override_still_authoritative(self):
        loaded = EnvironmentProductionConfigLoader(
            environmentReader=lambda name: {
                "AI_ADVISOR_LIVE_MAX_INPUT_BYTES": "24576",
                "AI_ADVISOR_LIVE_MAX_INPUT_TOKENS": "24576",
            }.get(name)
        ).load()
        self.assertTrue(loaded.succeeded)
        self.assertEqual(loaded.configuration.liveMaximumInputBytes, 24_576)

    def test_config_contract_bounds_are_unchanged(self):
        config = AIAdvisorProductionConfig(
            configVersion="ai-advisor-production-config/v1",
            source=ProductionConfigSource.ENVIRONMENT,
            endpointEnabled=True,
            networkInvocationAllowed=True,
            model="gpt-4o-mini",
        )
        self.assertTrue(32768 <= config.liveMaximumInputBytes <= 65_536)
        self.assertTrue(32768 <= config.liveMaximumInputTokens <= 65_536)


if __name__ == "__main__":
    unittest.main()
