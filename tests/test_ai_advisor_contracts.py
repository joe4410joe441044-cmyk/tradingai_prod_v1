import json
import unittest
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from backend.ai_advisor.conversation_models import (
    AdvisorAuthenticationContext,
    AdvisorAuthorityNotice,
    AdvisorCapability,
    AdvisorContextEnvelope,
    AdvisorDataAccessScope,
    AdvisorFreshnessMetadata,
    AdvisorFreshnessState,
    AdvisorPermissionContext,
    AdvisorRequestType,
    AdvisorRefusalCode,
    AdvisorSensitiveDataFilterResult,
    AdvisorSourceAuthority,
    AdvisorSourceReference,
    AdvisorSourceType,
    AuthenticationState,
    AuthorizationState,
    SensitiveCategory,
    SensitiveClassification,
    SensitiveFilterStatus,
)
from backend.ai_advisor.conversation_validation import (
    parse_untrusted_client_request,
    select_refusal_code,
)

NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)


def permission(**overrides):
    values = dict(
        principalId="principal-1",
        authenticationState=AuthenticationState.AUTHENTICATED,
        authorizationState=AuthorizationState.AUTHORIZED,
        role="USER",
        permissionLevel="READ_ONLY",
        allowedCapabilities=[AdvisorCapability.RUNTIME_STATUS_EXPLAIN],
        dataAccessScope=[AdvisorDataAccessScope.SANITIZED_RUNTIME_SUMMARY],
        policyVersion="1.1",
        trustedServerContext=True,
    )
    values.update(overrides)
    return AdvisorPermissionContext(**values)


def fresh():
    return AdvisorFreshnessMetadata(
        state=AdvisorFreshnessState.FRESH,
        capturedAt=NOW,
        sourceUpdatedAt=NOW - timedelta(seconds=1),
        ageSeconds=1.0,
        isLastGood=False,
        validUntil=NOW + timedelta(seconds=9),
    )


def runtime_source():
    return AdvisorSourceReference(
        sourceId="runtime-1",
        sourceType=AdvisorSourceType.RUNTIME,
        sourceVersion="1.0",
        capturedAt=NOW,
        freshness=fresh(),
        authority=AdvisorSourceAuthority.RUNTIME_AUTHORITATIVE,
        displayLabel="Runtime",
    )


class RevisedContractTest(unittest.TestCase):
    def test_contract_is_frozen_and_permission_flags_are_fixed(self):
        item = permission()
        self.assertTrue(item.readOnly)
        self.assertTrue(item.explanationOnly)
        self.assertFalse(item.executionAllowed)
        self.assertFalse(item.governanceOverrideAllowed)
        self.assertFalse(item.moneyManagementOverrideAllowed)
        self.assertFalse(item.strategyOverrideAllowed)
        with self.assertRaises(ValidationError):
            permission(executionAllowed=True)
        with self.assertRaises(ValidationError):
            item.executionAllowed = True

    def test_authentication_states_fail_closed(self):
        for state in (
            AuthenticationState.UNAUTHENTICATED,
            AuthenticationState.UNKNOWN,
            AuthenticationState.EXPIRED,
            AuthenticationState.INVALID,
        ):
            context = AdvisorAuthenticationContext(state=state, reason=state.value)
            self.assertNotEqual(context.state, AuthenticationState.AUTHENTICATED)
        with self.assertRaises(ValidationError):
            AdvisorAuthenticationContext(state=AuthenticationState.EXPIRED)

    def test_data_scope_and_capability_are_allowlists(self):
        with self.assertRaises(ValidationError):
            permission(allowedCapabilities=["SUBMIT_ORDER"])
        with self.assertRaises(ValidationError):
            permission(dataAccessScope=["RAW_API_KEYS"])

    def test_source_path_is_logical_approved_and_safe(self):
        specification = AdvisorSourceReference(
            sourceId="spec-1",
            sourceType=AdvisorSourceType.SPECIFICATION,
            sourceVersion="1.1",
            capturedAt=NOW,
            freshness=fresh(),
            authority=AdvisorSourceAuthority.SPECIFICATION_AUTHORITATIVE,
            displayLabel="Advisor specification",
            documentPath="docs/ai_advisor/spec.md",
            approved=True,
        )
        self.assertFalse(specification.documentPath.startswith("/"))
        for path in ("/etc/passwd", "docs/../.env", "private/spec.md"):
            with self.subTest(path=path):
                with self.assertRaises(ValidationError):
                    specification.model_copy(
                        update={"documentPath": path}
                    ).model_validate(
                        {**specification.model_dump(), "documentPath": path}
                    )

    def test_last_good_requires_failure_metadata(self):
        with self.assertRaises(ValidationError):
            AdvisorFreshnessMetadata(
                state=AdvisorFreshnessState.LAST_GOOD,
                capturedAt=NOW,
                sourceUpdatedAt=NOW - timedelta(minutes=1),
                ageSeconds=60.0,
                isLastGood=True,
            )
        value = AdvisorFreshnessMetadata(
            state=AdvisorFreshnessState.LAST_GOOD,
            capturedAt=NOW,
            sourceUpdatedAt=NOW - timedelta(minutes=1),
            ageSeconds=60.0,
            isLastGood=True,
            lastGoodAt=NOW - timedelta(minutes=1),
            currentReadFailedAt=NOW,
            failureReason="READ_FAILED",
            staleWarning="Historical value only.",
        )
        self.assertTrue(value.isLastGood)

    def test_sensitive_secret_is_blocked_and_never_stored(self):
        result = AdvisorSensitiveDataFilterResult(
            status=SensitiveFilterStatus.BLOCKED,
            removedCategoryCodes=[SensitiveCategory.API_CREDENTIAL],
            contentModified=False,
            blocked=True,
            inputClassification=SensitiveClassification.SECRET,
            outputClassification=SensitiveClassification.INTERNAL,
            reason="SECRET_INPUT",
        )
        payload = result.model_dump(mode="json")
        self.assertNotIn("secretValue", payload)
        with self.assertRaises(ValidationError):
            AdvisorSensitiveDataFilterResult(
                status=SensitiveFilterStatus.CLEAN,
                removedCategoryCodes=[],
                contentModified=False,
                blocked=False,
                inputClassification=SensitiveClassification.SECRET,
                outputClassification=SensitiveClassification.INTERNAL,
            )

    def test_authority_notice_is_permanently_false(self):
        notice = AdvisorAuthorityNotice()
        self.assertFalse(notice.authoritative)
        self.assertFalse(notice.executionAuthority)
        self.assertFalse(notice.governanceAuthority)
        self.assertFalse(notice.moneyManagementAuthority)
        self.assertFalse(notice.strategyAuthority)
        with self.assertRaises(ValidationError):
            AdvisorAuthorityNotice(executionAuthority=True)

    def test_unknown_request_type_and_client_permission_injection_rejected(self):
        envelope = AdvisorContextEnvelope(
            schemaVersion="1.0",
            capturedAt=NOW,
            sources=[runtime_source()],
        )
        payload = {
            "schemaVersion": "1.0",
            "requestId": "request-1",
            "message": "Explain status.",
            "requestType": "EXECUTE",
            "locale": "en-US",
            "requestedAt": NOW.isoformat(),
            "contextEnvelope": envelope.model_dump(mode="json"),
        }
        with self.assertRaises(ValidationError):
            parse_untrusted_client_request(json.dumps(payload))
        payload["requestType"] = AdvisorRequestType.EXPLAIN.value
        payload["permissionContext"] = permission().model_dump(mode="json")
        with self.assertRaises(ValidationError):
            parse_untrusted_client_request(json.dumps(payload))

    def test_serialization_is_stable_and_has_no_execution_fields(self):
        first = permission().model_dump_json()
        second = permission().model_dump_json()
        self.assertEqual(first, second)
        for forbidden in ("orderPayload", "command", "endpoint", "apiKey"):
            self.assertNotIn(forbidden, first)

    def test_refusal_priority_is_deterministic(self):
        candidates = (
            AdvisorRefusalCode.PROMPT_INJECTION_SUSPECTED,
            AdvisorRefusalCode.GOVERNANCE_OVERRIDE_NOT_ALLOWED,
            AdvisorRefusalCode.AUTHENTICATION_REQUIRED,
        )
        self.assertEqual(
            select_refusal_code(candidates),
            AdvisorRefusalCode.AUTHENTICATION_REQUIRED,
        )
        self.assertEqual(
            select_refusal_code(tuple(reversed(candidates))),
            AdvisorRefusalCode.AUTHENTICATION_REQUIRED,
        )


if __name__ == "__main__":
    unittest.main()
