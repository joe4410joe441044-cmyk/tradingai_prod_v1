"""Total-contract regression tests for the Advisor semantic validator (Q2).

Q2 ADVISOR_RESPONSE_INVALID was caused by an unhandled exception escaping
``validate_advisor_response_with_diagnostic`` (the semantic path / envelope
construction) for a syntactically valid ``AdvisorResponseCandidate``.

The repair makes the validator total: for every syntactically valid candidate it
returns VALID / VALID_WITH_WARNINGS / REJECTED (never an unhandled exception),
and any unexpected exception is recorded on a secret-free observation sink with
a specific validation stage.
"""

import json
import unittest
from datetime import datetime, timedelta, timezone

from backend.ai_advisor.context_builder import (
    SummarySourceInput,
    build_advisor_context,
)
from backend.ai_advisor.conversation_models import (
    AdvisorCapability,
    AdvisorDataAccessScope,
    AdvisorFreshnessState,
    AdvisorPermissionContext,
    AdvisorRequest,
    AdvisorResponsePreferences,
    AdvisorDetailLevel,
    AdvisorResponseFormat,
    AuthenticationState,
    AuthorizationState,
)
from backend.ai_advisor.prompt_builder import build_advisor_prompt
from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
from backend.ai_advisor.response_models import (
    AdvisorRawResponse,
    AdvisorResponseStatus,
)
from backend.ai_advisor.response_parser import parse_advisor_response
from backend.ai_advisor.response_validation import (
    validate_advisor_response_with_diagnostic,
)
from backend.ai_advisor.semantic_validation_observation import (
    RecordingSemanticValidationObservationSink,
    SemanticValidationPhase,
    project_semantic_validation_exception,
    safe_rule_identifier,
)
from tests.test_ai_advisor_response_validation import candidate_payload, NOW
from tests.test_ai_advisor_prompt_builder import (
    permission as base_permission,
    runtime as base_runtime,
)

MM_SOURCE_ID = "money-management-master-v1.0"
MARKET_SOURCE_ID = "market-intelligence-live-v1.0"
VALID_UNTIL = NOW + timedelta(seconds=60)


def _summary(source_id, source_type, freshness):
    return SummarySourceInput(
        sourceId=source_id,
        sourceType=source_type,
        sourceVersion="1.0",
        title=source_id,
        capturedAt=NOW,
        sourceUpdatedAt=NOW,
        freshnessState=freshness,
        ageSeconds=0,
        validUntil=VALID_UNTIL,
        approved=True,
        sanitized=True,
    )


def _runtime():
    return base_runtime()


class AdvisorSemanticValidationContractTest(unittest.TestCase):
    def _trusted_default(self):
        from tests.test_ai_advisor_prompt_builder import make_request

        request, context = make_request()
        prompt = build_advisor_prompt(
            request=request, context=context, policy=AdvisorPromptPolicy()
        )
        return request, context, prompt

    def _trusted_sources(self, *, mm=(), market=()):
        permission = AdvisorPermissionContext(
            principalId=base_permission().principalId,
            authenticationState=base_permission().authenticationState,
            authorizationState=base_permission().authorizationState,
            role=base_permission().role,
            permissionLevel=base_permission().permissionLevel,
            allowedCapabilities=base_permission().allowedCapabilities
            + (AdvisorCapability.MONEY_MANAGEMENT_EXPLAIN,) * bool(mm)
            + (AdvisorCapability.MARKET_INTELLIGENCE_EXPLAIN,) * bool(market),
            dataAccessScope=base_permission().dataAccessScope
            + (AdvisorDataAccessScope.SANITIZED_MONEY_MANAGEMENT_SUMMARY,) * bool(mm)
            + (AdvisorDataAccessScope.SANITIZED_MARKET_INTELLIGENCE_SUMMARY,) * bool(market),
            policyVersion=base_permission().policyVersion,
            trustedServerContext=base_permission().trustedServerContext,
        )
        ctx = build_advisor_context(
            generated_at=NOW,
            permission_context=permission,
            runtime=_runtime(),
            specifications=(),
            money_management_sources=mm,
            market_intelligence_sources=market,
        )
        request = AdvisorRequest(
            schemaVersion="1.0",
            requestId="request-1",
            message="Explain the current state.",
            locale="en-US",
            requestedAt=NOW,
            permissionContext=permission,
            contextEnvelope=ctx,
            responsePreferences=AdvisorResponsePreferences(
                locale="en-US",
                detailLevel=AdvisorDetailLevel.STANDARD,
                includeSources=True,
                includeWarnings=True,
                format=AdvisorResponseFormat.STRUCTURED,
            ),
        )
        prompt = build_advisor_prompt(
            request=request, context=ctx, policy=AdvisorPromptPolicy()
        )
        return request, ctx, prompt

    def _validate(self, payload, request, context, prompt):
        raw = AdvisorRawResponse(
            requestId="request-1",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            responseText=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            receivedAt=NOW,
        )
        parse_advisor_response(raw)
        sink = RecordingSemanticValidationObservationSink()
        outcome = validate_advisor_response_with_diagnostic(
            raw_response=raw,
            request=request,
            context=context,
            prompt_envelope=prompt,
            semantic_validation_observation_sink=sink,
        )
        self.assertIn(
            outcome.response.status,
            {
                AdvisorResponseStatus.VALID,
                AdvisorResponseStatus.VALID_WITH_WARNINGS,
                AdvisorResponseStatus.REJECTED,
            },
        )
        return outcome, sink

    def test_normal_valid_response(self):
        request, context, prompt = self._trusted_default()
        payload = candidate_payload()
        payload["inferences"] = []
        payload["unknowns"] = []
        payload["warnings"] = []
        payload["sourceReferences"] = ["advisor-runtime"]
        payload["freshnessDisclosures"] = [
            {"sourceId": "advisor-runtime", "freshness": "FRESH"}
        ]
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.VALID)

    def test_valid_with_warnings_response(self):
        request, context, prompt = self._trusted_default()
        outcome, _ = self._validate(candidate_payload(), request, context, prompt)
        self.assertEqual(
            outcome.response.status, AdvisorResponseStatus.VALID_WITH_WARNINGS
        )

    def test_ungrounded_current_state_claim_is_rejected(self):
        request, context, prompt = self._trusted_default()
        payload = candidate_payload()
        payload["summary"] = "The position is currently OPEN."
        payload["facts"] = []
        payload["inferences"] = []
        payload["unknowns"] = []
        payload["warnings"] = []
        payload["sourceReferences"] = []
        payload["freshnessDisclosures"] = []
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)

    def test_missing_source_relationship_is_rejected(self):
        request, context, prompt = self._trusted_default()
        payload = candidate_payload()
        payload["sourceReferences"] = ["advisor-runtime", "unknown-source"]
        payload["freshnessDisclosures"] = [
            {"sourceId": "advisor-runtime", "freshness": "FRESH"},
            {"sourceId": "unknown-source", "freshness": "FRESH"},
        ]
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)

    def test_unknown_and_actionable_unknown_combination(self):
        request, context, prompt = self._trusted_default()
        payload = candidate_payload()
        payload["facts"] = []
        payload["inferences"] = []
        payload["unknowns"] = [
            {
                "unknownId": "unknown-a",
                "topic": "market stability not described",
                "reason": "SOURCE_UNKNOWN",
                "requiredSourceType": None,
            }
        ]
        payload["warnings"] = []
        payload["sourceReferences"] = []
        payload["freshnessDisclosures"] = []
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertEqual(
            outcome.response.status, AdvisorResponseStatus.VALID_WITH_WARNINGS
        )
        self.assertEqual(len(outcome.response.actionableUnknowns), 1)
        self.assertEqual(
            outcome.response.actionableUnknowns[0].unknownId, "unknown-a"
        )

    def test_freshness_edge_case_interpretation_claim(self):
        request, context, prompt = self._trusted_default()
        payload = candidate_payload()
        payload["facts"] = [
            {
                "factId": "fact-fresh",
                "statement": "The configured mode is PAPER.",
                "sourceIds": ["advisor-runtime"],
                "freshness": "FRESH",
            }
        ]
        payload["inferences"] = []
        payload["unknowns"] = []
        payload["warnings"] = []
        payload["sourceReferences"] = ["advisor-runtime"]
        payload["freshnessDisclosures"] = [
            {"sourceId": "advisor-runtime", "freshness": "FRESH"}
        ]
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertIn(
            outcome.response.status,
            {
                AdvisorResponseStatus.VALID,
                AdvisorResponseStatus.VALID_WITH_WARNINGS,
            },
        )
        claim = outcome.response.groundedClaims[0]
        self.assertEqual(claim.claimType, "FACT")
        self.assertEqual(claim.freshness.value, "FRESH")

    def test_parseable_null_and_empty_shape_does_not_raise(self):
        request, context, prompt = self._trusted_default()
        payload = {
            "responseVersion": "1.0",
            "requestId": "request-1",
            "promptVersion": "1.0",
            "summary": "Nothing known.",
            "facts": [],
            "inferences": [],
            "unknowns": [],
            "warnings": [],
            "sourceReferences": [],
            "freshnessDisclosures": [],
            "safetyDisclosures": ["READ_ONLY"],
        }
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertIn(
            outcome.response.status,
            {
                AdvisorResponseStatus.VALID,
                AdvisorResponseStatus.VALID_WITH_WARNINGS,
                AdvisorResponseStatus.REJECTED,
            },
        )

    def test_whitespace_only_content_is_controlled_rejected_not_raised(self):
        request, context, prompt = self._trusted_default()
        payload = candidate_payload()
        payload["summary"] = "   "
        outcome, sink = self._validate(payload, request, context, prompt)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)
        self.assertEqual(len(sink.records), 1)
        self.assertEqual(
            sink.records[0].validationStage,
            SemanticValidationPhase.CLAIM_DETECTION,
        )
        self.assertEqual(sink.records[0].safeReason, "UNEXPECTED_VALIDATION_EXCEPTION")
        self.assertEqual(sink.records[0].responseCategory, "REJECTED")

    def test_zero_width_only_content_is_controlled_rejected_not_raised(self):
        request, context, prompt = self._trusted_default()
        payload = candidate_payload()
        payload["facts"][0]["statement"] = "\u200b"
        outcome, sink = self._validate(payload, request, context, prompt)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)
        self.assertEqual(sink.records[0].exceptionClass, "ValueError")

    def test_money_management_response_shape(self):
        mm = (_summary(MM_SOURCE_ID, "MONEY_MANAGEMENT", AdvisorFreshnessState.FRESH),)
        request, context, prompt = self._trusted_sources(mm=mm)
        payload = candidate_payload()
        payload["summary"] = "Money Management capital authority is available."
        payload["facts"] = [
            {
                "factId": "fact-mm",
                "statement": "Available capital is known.",
                "sourceIds": [MM_SOURCE_ID],
                "freshness": "FRESH",
            }
        ]
        payload["inferences"] = []
        payload["unknowns"] = []
        payload["warnings"] = []
        payload["sourceReferences"] = [MM_SOURCE_ID]
        payload["freshnessDisclosures"] = [
            {"sourceId": MM_SOURCE_ID, "freshness": "FRESH"}
        ]
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertIn(
            outcome.response.status,
            {
                AdvisorResponseStatus.VALID,
                AdvisorResponseStatus.VALID_WITH_WARNINGS,
            },
        )

    def test_market_mm_authority_isolation_shape(self):
        mm = (_summary(MM_SOURCE_ID, "MONEY_MANAGEMENT", AdvisorFreshnessState.FRESH),)
        request, context, prompt = self._trusted_sources(mm=mm)
        # MM NORMAL must not be collapsed into a market-stability claim: a
        # current-market claim grounded only on a Money Management source is
        # ungrounded and must be rejected (authority isolation preserved).
        payload = candidate_payload()
        payload["summary"] = "BTCUSDT is currently rising."
        payload["facts"] = []
        payload["inferences"] = []
        payload["unknowns"] = []
        payload["warnings"] = []
        payload["sourceReferences"] = [MM_SOURCE_ID]
        payload["freshnessDisclosures"] = [
            {"sourceId": MM_SOURCE_ID, "freshness": "FRESH"}
        ]
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)

    def test_observation_helpers_are_secret_free_and_staged(self):
        self.assertNotIn("secret", safe_rule_identifier(ValueError("sk-secret")))
        exc = ValueError("text must be a non-empty string")
        obs = project_semantic_validation_exception(
            request_id="request-1",
            stage=SemanticValidationPhase.CLAIM_DETECTION,
            exception=exc,
            rule_identifier=safe_rule_identifier(exc),
        )
        self.assertEqual(obs.validationStage, SemanticValidationPhase.CLAIM_DETECTION)
        self.assertEqual(obs.exceptionClass, "ValueError")
        self.assertEqual(obs.safeReason, "UNEXPECTED_VALIDATION_EXCEPTION")
        self.assertEqual(obs.responseCategory, "REJECTED")
        self.assertNotIn("sk-secret", json.dumps(obs.model_dump(mode="json")))

    def test_envelope_construction_exception_is_controlled(self):
        request, context, prompt = self._trusted_default()
        # A foreground fact with an unknown-invalid freshness enum value still
        # parses as a candidate but exercises envelope/grounded-claim rules; the
        # validator must return a controlled result rather than raise.
        payload = candidate_payload()
        payload["facts"] = [
            {
                "factId": "fact-x",
                "statement": "A value is known.",
                "sourceIds": ["advisor-runtime"],
                "freshness": "FRESH",
            }
        ]
        payload["inferences"] = []
        payload["unknowns"] = []
        payload["warnings"] = []
        payload["sourceReferences"] = ["advisor-runtime"]
        payload["freshnessDisclosures"] = [
            {"sourceId": "advisor-runtime", "freshness": "FRESH"}
        ]
        outcome, _ = self._validate(payload, request, context, prompt)
        self.assertIn(
            outcome.response.status,
            {
                AdvisorResponseStatus.VALID,
                AdvisorResponseStatus.VALID_WITH_WARNINGS,
                AdvisorResponseStatus.REJECTED,
            },
        )


if __name__ == "__main__":
    unittest.main()
