import json
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from pydantic import ValidationError

from backend.ai_advisor.conversation_models import (
    MAX_CONVERSATION_MESSAGES,
    MAX_CLAIMS,
    MAX_EVIDENCE,
    MAX_RESPONSE_SECTIONS,
    MAX_SOURCES,
    MAX_USER_MESSAGE_LENGTH,
    MAX_WARNINGS,
    AdvisorCapability,
    AdvisorClaim,
    AdvisorClaimType,
    AdvisorClientRequest,
    AdvisorContextEnvelope,
    AdvisorConversationMessage,
    AdvisorErrorDetail,
    AdvisorEvidence,
    AdvisorFreshnessMetadata,
    AdvisorFreshnessState,
    AdvisorPermissionContext,
    AdvisorRefusal,
    AdvisorRefusalCode,
    AdvisorRequest,
    AdvisorResponse,
    AdvisorResponseCategory,
    AdvisorResponseSection,
    AdvisorResponseStatus,
    AdvisorRole,
    AdvisorSectionType,
    AdvisorSensitiveDataFilterResult,
    AdvisorSourceAuthority,
    AdvisorSourceReference,
    AdvisorSourceType,
    AdvisorValidationErrorDetail,
    AdvisorValidationErrorResponse,
    AdvisorValidationIssue,
    AdvisorWarningCode,
    AuthenticationState,
    AuthorizationState,
    SensitiveFilterStatus,
)
from backend.ai_advisor.conversation_validation import (
    attach_trusted_permission_context,
    parse_untrusted_client_request,
    validate_request_response_pair,
    validate_request_time,
    validate_trusted_request,
)

NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def freshness(**overrides):
    values = {
        "state": AdvisorFreshnessState.FRESH,
        "capturedAt": NOW,
        "sourceUpdatedAt": NOW - timedelta(seconds=1),
        "ageSeconds": 1.0,
        "isLastGood": False,
        "validUntil": NOW + timedelta(seconds=9),
    }
    values.update(overrides)
    return AdvisorFreshnessMetadata(**values)


def source(source_id="runtime-1", **overrides):
    values = {
        "sourceId": source_id,
        "sourceType": AdvisorSourceType.RUNTIME,
        "sourceVersion": "1.0",
        "capturedAt": NOW,
        "freshness": freshness(),
        "authority": AdvisorSourceAuthority.RUNTIME_AUTHORITATIVE,
        "displayLabel": "Advisor Runtime",
    }
    values.update(overrides)
    return AdvisorSourceReference(**values)


def permission(**overrides):
    values = {
        "principalId": "principal-1",
        "authenticationState": AuthenticationState.AUTHENTICATED,
        "authorizationState": AuthorizationState.AUTHORIZED,
        "role": "USER",
        "permissionLevel": "READ_ONLY",
        "allowedCapabilities": [AdvisorCapability.RUNTIME_STATUS_EXPLAIN],
        "policyVersion": "1.1",
        "trustedServerContext": True,
    }
    values.update(overrides)
    return AdvisorPermissionContext(**values)


def context(**overrides):
    values = {
        "schemaVersion": "1.0",
        "capturedAt": NOW,
        "sources": [source()],
        "conversationHistory": [],
        "warnings": [],
    }
    values.update(overrides)
    return AdvisorContextEnvelope(**values)


def request(**overrides):
    values = {
        "schemaVersion": "1.0",
        "requestId": "request-1",
        "conversationId": None,
        "message": "現在のRuntime状態を説明してください。",
        "locale": "ja-JP",
        "requestedAt": NOW,
        "permissionContext": permission(),
        "contextEnvelope": context(),
    }
    values.update(overrides)
    return AdvisorRequest(**values)


def clean_filter():
    return AdvisorSensitiveDataFilterResult(
        status=SensitiveFilterStatus.CLEAN,
        removedCategoryCodes=[],
        contentModified=False,
        blocked=False,
    )


def success_response(**overrides):
    values = {
        "schemaVersion": "1.0",
        "requestId": "request-1",
        "responseId": "response-1",
        "conversationId": None,
        "status": AdvisorResponseStatus.SUCCESS,
        "category": AdvisorResponseCategory.STATUS_EXPLANATION,
        "summary": "Runtimeは記録上RUNNINGです。",
        "sections": [],
        "claims": [
            AdvisorClaim(
                claimId="claim-1",
                claimType=AdvisorClaimType.FACT,
                text="記録上の状態はRUNNINGです。",
                sourceIds=["runtime-1"],
                evidenceIds=[],
                freshnessState=AdvisorFreshnessState.FRESH,
            )
        ],
        "evidence": [],
        "sourceReferences": [source()],
        "warnings": [],
        "sensitiveDataFilter": clean_filter(),
        "createdAt": NOW,
        "policyVersion": "1.1",
    }
    values.update(overrides)
    return AdvisorResponse(**values)


class RequestContractTest(unittest.TestCase):
    def test_valid_request_and_maximum_message(self):
        self.assertTrue(request().permissionContext.conversationAllowed)
        self.assertEqual(
            len(request(message="x" * MAX_USER_MESSAGE_LENGTH).message), 8_000
        )

    def test_empty_blank_oversize_control_locale_naive_and_extra_rejected(self):
        invalid_messages = ("", "   ", "x" * (MAX_USER_MESSAGE_LENGTH + 1), "x\0y")
        for message in invalid_messages:
            with self.subTest(message=repr(message[:10])):
                with self.assertRaises(ValidationError):
                    request(message=message)
        with self.assertRaises(ValidationError):
            request(locale="fr-FR")
        with self.assertRaises(ValidationError):
            request(requestedAt=NOW.replace(tzinfo=None))
        with self.assertRaises(ValidationError):
            AdvisorRequest(**{**request().model_dump(), "apiKey": "secret"})

    def test_request_id_and_conversation_id_are_bounded_non_authoritative_ids(self):
        with self.assertRaises(ValidationError):
            request(requestId="bad\nid")
        with self.assertRaises(ValidationError):
            request(conversationId="")

    def test_future_request_validation_is_deterministic(self):
        validate_request_time(request(), now=NOW)
        with self.assertRaises(ValueError):
            validate_request_time(
                request(requestedAt=NOW + timedelta(seconds=301)),
                now=NOW,
            )


class PermissionContractTest(unittest.TestCase):
    def test_authenticated_authorized_read_only(self):
        trusted = permission()
        validate_trusted_request(request(permissionContext=trusted))
        self.assertEqual(trusted.permissionLevel, "READ_ONLY")

    def test_unauthenticated_denied_and_unknown_fail_closed(self):
        cases = (
            permission(
                principalId=None,
                authenticationState=AuthenticationState.UNAUTHENTICATED,
                authorizationState=AuthorizationState.DENIED,
            ),
            permission(
                principalId=None,
                authenticationState=AuthenticationState.UNKNOWN,
                authorizationState=AuthorizationState.UNKNOWN,
            ),
            permission(authorizationState=AuthorizationState.DENIED),
        )
        for item in cases:
            with self.subTest(item=item):
                with self.assertRaises(ValueError):
                    validate_trusted_request(request(permissionContext=item))

    def test_principal_and_auth_cross_field_invariants(self):
        with self.assertRaises(ValidationError):
            permission(principalId=None)
        with self.assertRaises(ValidationError):
            permission(
                authenticationState=AuthenticationState.UNAUTHENTICATED,
                authorizationState=AuthorizationState.AUTHORIZED,
            )

    def test_forbidden_capability_and_client_self_assertion_rejected(self):
        payload = permission().model_dump(mode="json")
        payload["allowedCapabilities"] = ["ORDER_CREATE"]
        with self.assertRaises(ValidationError):
            AdvisorPermissionContext.model_validate(payload)
        client_payload = request().model_dump(mode="json")
        with self.assertRaises(ValidationError):
            parse_untrusted_client_request(json.dumps(client_payload))
        client_payload.pop("permissionContext")
        client_request = parse_untrusted_client_request(json.dumps(client_payload))
        self.assertIsInstance(client_request, AdvisorClientRequest)
        internal = attach_trusted_permission_context(client_request, permission())
        self.assertTrue(internal.permissionContext.conversationAllowed)
        payload = permission().model_dump(mode="json")
        payload["trustedServerContext"] = False
        with self.assertRaises(ValidationError):
            AdvisorPermissionContext.model_validate(payload)


class SourceAndContextContractTest(unittest.TestCase):
    def test_source_and_last_good(self):
        item = source()
        self.assertEqual(item.sourceType, AdvisorSourceType.RUNTIME)
        last_good = freshness(
            state=AdvisorFreshnessState.LAST_GOOD,
            isLastGood=True,
            sourceUpdatedAt=NOW - timedelta(minutes=2),
            ageSeconds=120.0,
            validUntil=None,
            lastGoodAt=NOW - timedelta(minutes=2),
            currentReadFailedAt=NOW,
            failureReason="CURRENT_READ_FAILED",
            staleWarning="Historical value only.",
        )
        self.assertEqual(last_good.state, AdvisorFreshnessState.LAST_GOOD)

    def test_source_unknown_type_timestamp_freshness_and_extra_rejected(self):
        payload = source().model_dump(mode="json")
        payload["sourceType"] = "EXTERNAL_WEB"
        with self.assertRaises(ValidationError):
            AdvisorSourceReference.model_validate(payload)
        payload = source().model_dump(mode="json")
        payload["capturedAt"] = "not-a-time"
        with self.assertRaises(ValidationError):
            AdvisorSourceReference.model_validate(payload)
        payload = freshness().model_dump(mode="json")
        payload["state"] = "CURRENT"
        with self.assertRaises(ValidationError):
            AdvisorFreshnessMetadata.model_validate(payload)
        with self.assertRaises(ValidationError):
            freshness(
                state=AdvisorFreshnessState.LAST_GOOD,
                sourceUpdatedAt=None,
                ageSeconds=None,
                isLastGood=True,
            )
        with self.assertRaises(ValidationError):
            AdvisorSourceReference(**{**source().model_dump(), "raw": {}})

    def test_future_timestamp_fails_to_unknown(self):
        with self.assertRaises(ValidationError):
            freshness(sourceUpdatedAt=NOW + timedelta(seconds=1))
        unknown = freshness(
            state=AdvisorFreshnessState.UNKNOWN,
            sourceUpdatedAt=NOW + timedelta(seconds=1),
            ageSeconds=None,
            validUntil=None,
            reason="SOURCE_TIMESTAMP_IN_FUTURE",
        )
        self.assertEqual(unknown.state, AdvisorFreshnessState.UNKNOWN)

    def test_context_limits_duplicate_and_unknown_references(self):
        too_many = [source(f"source-{index}") for index in range(MAX_SOURCES + 1)]
        with self.assertRaises(ValidationError):
            context(sources=too_many)
        with self.assertRaises(ValidationError):
            context(sources=[source(), source()])
        message = AdvisorConversationMessage(
            messageId="message-1",
            role=AdvisorRole.USER,
            content="hello",
            createdAt=NOW,
            sourceReferences=["missing"],
        )
        with self.assertRaises(ValidationError):
            context(conversationHistory=[message])
        with self.assertRaises(ValidationError):
            AdvisorContextEnvelope(**{**context().model_dump(), "rawRuntime": {}})


class ConversationContractTest(unittest.TestCase):
    def message(self, index, **overrides):
        values = {
            "messageId": f"message-{index}",
            "role": AdvisorRole.USER if index % 2 == 0 else AdvisorRole.ADVISOR,
            "content": "hello",
            "createdAt": NOW - timedelta(seconds=MAX_CONVERSATION_MESSAGES - index),
            "sourceReferences": [],
        }
        values.update(overrides)
        return AdvisorConversationMessage(**values)

    def test_valid_history_and_role_restriction(self):
        history = [self.message(0), self.message(1)]
        self.assertEqual(
            len(context(conversationHistory=history).conversationHistory), 2
        )
        payload = self.message(0).model_dump(mode="json")
        payload["role"] = "SYSTEM"
        with self.assertRaises(ValidationError):
            AdvisorConversationMessage.model_validate(payload)

    def test_history_count_total_duplicate_order_future_and_extra(self):
        with self.assertRaises(ValidationError):
            context(
                conversationHistory=[
                    self.message(index)
                    for index in range(MAX_CONVERSATION_MESSAGES + 1)
                ]
            )
        large = [self.message(index, content="x" * 8_000) for index in range(6)]
        with self.assertRaises(ValidationError):
            context(conversationHistory=large)
        with self.assertRaises(ValidationError):
            context(conversationHistory=[self.message(0), self.message(0)])
        with self.assertRaises(ValidationError):
            context(conversationHistory=[self.message(1), self.message(0)])
        with self.assertRaises(ValidationError):
            context(conversationHistory=[self.message(0, createdAt=NOW + timedelta(1))])
        with self.assertRaises(ValidationError):
            AdvisorConversationMessage(**{**self.message(0).model_dump(), "tool": {}})


class ClaimAndResponseContractTest(unittest.TestCase):
    def test_fact_inference_unknown_and_confidence(self):
        self.assertEqual(success_response().claims[0].claimType, AdvisorClaimType.FACT)
        with self.assertRaises(ValidationError):
            AdvisorClaim(
                claimId="fact",
                claimType=AdvisorClaimType.FACT,
                text="fact",
                sourceIds=[],
                freshnessState=AdvisorFreshnessState.FRESH,
            )
        inference = AdvisorClaim(
            claimId="inference",
            claimType=AdvisorClaimType.INFERENCE,
            text="uncertain inference",
            confidence=Decimal("0.5"),
            sourceIds=["runtime-1"],
            freshnessState=AdvisorFreshnessState.STALE,
        )
        self.assertEqual(inference.confidence, Decimal("0.5"))
        for value in (Decimal("-0.1"), Decimal("1.1"), Decimal("NaN")):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    AdvisorClaim(
                        claimId="inference",
                        claimType=AdvisorClaimType.INFERENCE,
                        text="inference",
                        confidence=value,
                        sourceIds=["runtime-1"],
                        freshnessState=AdvisorFreshnessState.FRESH,
                    )
        unknown = AdvisorClaim(
            claimId="unknown",
            claimType=AdvisorClaimType.UNKNOWN,
            text="unknown",
            sourceIds=[],
            freshnessState=AdvisorFreshnessState.UNKNOWN,
        )
        self.assertEqual(unknown.claimType, AdvisorClaimType.UNKNOWN)

    def test_success_partial_insufficient_refused_and_error(self):
        success_response()
        success_response(status=AdvisorResponseStatus.PARTIAL)
        success_response(
            status=AdvisorResponseStatus.INSUFFICIENT_DATA,
            category=AdvisorResponseCategory.INSUFFICIENT_DATA,
        )
        refusal = AdvisorRefusal(
            code=AdvisorRefusalCode.MUTATION_NOT_ALLOWED,
            message="AI Advisor cannot mutate runtime state.",
            policyRule="READ_ONLY",
            safeAlternative="Review the authorized Dashboard status.",
            retryable=False,
        )
        success_response(
            status=AdvisorResponseStatus.REFUSED,
            category=AdvisorResponseCategory.SAFETY_REFUSAL,
            refusal=refusal,
            claims=[],
        )
        error = AdvisorErrorDetail(
            code="ADVISOR_INTERNAL_ERROR",
            message="The request could not be processed.",
            retryable=True,
            requestId="request-1",
            occurredAt=NOW.isoformat(),
        )
        success_response(
            status=AdvisorResponseStatus.ERROR,
            category=AdvisorResponseCategory.INTERNAL_ERROR,
            error=error,
            claims=[],
        )

    def test_refusal_error_and_dangling_reference_invariants(self):
        with self.assertRaises(ValidationError):
            success_response(status=AdvisorResponseStatus.REFUSED, claims=[])
        with self.assertRaises(ValidationError):
            success_response(status=AdvisorResponseStatus.ERROR, claims=[])
        dangling = (
            success_response().claims[0].model_copy(update={"sourceIds": ["missing"]})
        )
        with self.assertRaises(ValidationError):
            success_response(claims=[dangling])
        section = AdvisorResponseSection(
            sectionType=AdvisorSectionType.EVIDENCE,
            title="Evidence",
            body="Evidence summary.",
            claimIds=["missing"],
            sourceIds=["runtime-1"],
        )
        with self.assertRaises(ValidationError):
            success_response(sections=[section])

    def test_request_response_correlation(self):
        validate_request_response_pair(request(), success_response())
        with self.assertRaises(ValueError):
            validate_request_response_pair(
                request(),
                success_response(requestId="other"),
            )

    def test_safe_alternative_cannot_direct_mutation(self):
        with self.assertRaises(ValidationError):
            AdvisorRefusal(
                code=AdvisorRefusalCode.ORDER_OPERATION_NOT_ALLOWED,
                message="Order operations are unavailable.",
                policyRule="READ_ONLY",
                safeAlternative="Send the order through the API.",
                retryable=False,
            )

    def test_response_collection_and_total_character_limits(self):
        with self.assertRaises(ValidationError):
            success_response(
                warnings=[AdvisorWarningCode.SOURCE_OMITTED] * (MAX_WARNINGS + 1)
            )
        sections = [
            AdvisorResponseSection(
                sectionType=AdvisorSectionType.EXPLANATION,
                title=f"Section {index}",
                body="body",
            )
            for index in range(MAX_RESPONSE_SECTIONS + 1)
        ]
        with self.assertRaises(ValidationError):
            success_response(sections=sections)
        claims = [
            AdvisorClaim(
                claimId=f"claim-{index}",
                claimType=AdvisorClaimType.UNKNOWN,
                text="unknown",
                freshnessState=AdvisorFreshnessState.UNKNOWN,
            )
            for index in range(MAX_CLAIMS + 1)
        ]
        with self.assertRaises(ValidationError):
            success_response(claims=claims)
        evidence = [
            AdvisorEvidence(
                evidenceId=f"evidence-{index}",
                sourceId="runtime-1",
                description="evidence",
            )
            for index in range(MAX_EVIDENCE + 1)
        ]
        with self.assertRaises(ValidationError):
            success_response(evidence=evidence)
        oversized_sections = [
            AdvisorResponseSection(
                sectionType=AdvisorSectionType.EXPLANATION,
                title=f"Long {index}",
                body="x" * 8_000,
            )
            for index in range(5)
        ]
        with self.assertRaises(ValidationError):
            success_response(sections=oversized_sections, claims=[])


class SerializationAndSecurityTest(unittest.TestCase):
    def test_json_round_trip_enum_utc_decimal_null_and_determinism(self):
        item = success_response()
        first = item.model_dump_json()
        second = item.model_dump_json()
        self.assertEqual(first, second)
        restored = AdvisorResponse.model_validate_json(first)
        self.assertEqual(restored, item)
        payload = item.model_dump(mode="json")
        self.assertEqual(payload["status"], "SUCCESS")
        self.assertTrue(payload["createdAt"].endswith("Z"))
        self.assertIsNone(payload["conversationId"])

    def test_sensitive_result_never_contains_removed_values(self):
        fields = set(AdvisorSensitiveDataFilterResult.model_fields)
        self.assertEqual(
            fields,
            {
                "status",
                "removedCategoryCodes",
                "contentModified",
                "blocked",
                "inputClassification",
                "outputClassification",
                "reason",
            },
        )

    def test_validation_error_contract_has_no_raw_or_internal_detail(self):
        issue = AdvisorValidationIssue(
            path=["message"],
            code="INVALID_MESSAGE",
            message="Message validation failed.",
        )
        response = AdvisorValidationErrorResponse(
            error=AdvisorValidationErrorDetail(
                code="ADVISOR_REQUEST_INVALID",
                message="The request was invalid.",
                retryable=False,
                requestId="request-1",
                occurredAt=NOW.isoformat(),
                issues=[issue],
            )
        )
        payload = response.model_dump(mode="json")
        self.assertEqual(payload["error"]["issues"][0]["path"], ["message"])
        self.assertNotIn("input", payload["error"]["issues"][0])
        self.assertNotIn("stack", payload["error"])

    def test_execution_secret_and_raw_payload_fields_are_absent_and_rejected(self):
        response_fields = set(AdvisorResponse.model_fields)
        for field in (
            "order",
            "orderPayload",
            "command",
            "executionCommand",
            "endpoint",
            "method",
            "headers",
            "apiKey",
            "shellCommand",
            "gitCommand",
            "deployCommand",
        ):
            self.assertNotIn(field, response_fields)
            with self.assertRaises(ValidationError):
                AdvisorResponse(**{**success_response().model_dump(), field: {}})

    def test_validation_error_does_not_need_raw_value_envelope(self):
        with self.assertRaises(ValidationError) as raised:
            request(message="")
        error = raised.exception.errors(include_input=False)
        self.assertNotIn("input", error[0])


if __name__ == "__main__":
    unittest.main()
