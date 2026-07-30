import builtins
import json
import os
import socket
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from pydantic import ValidationError

from backend.ai_advisor.context_builder import build_freshness
from backend.ai_advisor.conversation_models import AdvisorFreshnessState
from backend.ai_advisor.prompt_builder import build_advisor_prompt
from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
from backend.ai_advisor.provider_failure_observation import (
    ResponseContractField,
    ResponseTopLevelType,
    ResponseValidationCode,
)
from backend.ai_advisor.response_models import (
    MAX_RAW_RESPONSE_CHARACTERS,
    AdvisorForbiddenClaim,
    AdvisorRawResponse,
    AdvisorResponseCandidate,
    AdvisorResponseEnvelope,
    AdvisorResponseStatus,
    AdvisorSafetyDisclosure,
    AdvisorUnknownReason,
)
from backend.ai_advisor.response_parser import (
    AdvisorResponseParsingError,
    parse_advisor_response,
)
from backend.ai_advisor.response_validation import (
    REJECTED_SUMMARY,
    validate_advisor_response,
)
from tests.test_ai_advisor_prompt_builder import make_request

NOW = datetime(2026, 7, 26, 13, tzinfo=timezone.utc)


def candidate_payload():
    return {
        "responseVersion": "1.0",
        "requestId": "request-1",
        "promptVersion": "1.0",
        "summary": "The bot is running in paper mode.",
        "facts": [
            {
                "factId": "fact-b",
                "statement": "The configured mode is PAPER.",
                "sourceIds": ["advisor-runtime"],
                "freshness": "FRESH",
            },
            {
                "factId": "fact-a",
                "statement": "The runtime state is RUNNING.",
                "sourceIds": ["advisor-runtime"],
                "freshness": "FRESH",
            },
        ],
        "inferences": [
            {
                "inferenceId": "inference-a",
                "statement": "This may be suitable for observation.",
                "basedOnSourceIds": ["spec-a"],
                "uncertainty": "HIGH",
            }
        ],
        "unknowns": [],
        "warnings": [],
        "sourceReferences": ["spec-a", "advisor-runtime"],
        "freshnessDisclosures": [
            {"sourceId": "spec-a", "freshness": "NOT_APPLICABLE"},
            {"sourceId": "advisor-runtime", "freshness": "FRESH"},
        ],
        "safetyDisclosures": [
            "NO_TOOL_USED",
            "NO_STATE_CHANGED",
            "NO_ACTION_EXECUTED",
            "READ_ONLY",
        ],
    }


def raw(payload=None, **overrides):
    values = dict(
        requestId="request-1",
        promptVersion="1.0",
        responseFormatVersion="1.0",
        responseText=json.dumps(
            candidate_payload() if payload is None else payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        receivedAt=NOW,
    )
    values.update(overrides)
    return AdvisorRawResponse(**values)


def trusted_inputs():
    request, context = make_request()
    prompt = build_advisor_prompt(
        request=request,
        context=context,
        policy=AdvisorPromptPolicy(),
    )
    return request, context, prompt


def validate(value):
    request, context, prompt = trusted_inputs()
    return validate_advisor_response(
        raw_response=value,
        request=request,
        context=context,
        prompt_envelope=prompt,
    )


class AdvisorResponseValidationTest(unittest.TestCase):
    def test_strict_json_parser_accepts_only_complete_contract(self):
        parsed = parse_advisor_response(raw())
        self.assertIsInstance(parsed, AdvisorResponseCandidate)
        self.assertIsInstance(parsed.facts, tuple)
        invalid = (
            "not json",
            "{",
            "[]",
            json.dumps({"responseVersion": "1.0"}),
            json.dumps({**candidate_payload(), "extra": True}),
            json.dumps({**candidate_payload(), "facts": "wrong"}),
        )
        for text in invalid:
            with self.subTest(text=text[:20]):
                value = raw(responseText=text)
                with self.assertRaises(ValueError) as raised:
                    parse_advisor_response(value)
                self.assertEqual(
                    str(raised.exception),
                    "advisor response parsing failed",
                )
        with self.assertRaises(ValidationError):
            raw(responseText="")

    def test_parser_failures_have_only_fixed_allowlisted_diagnostics(self):
        missing = candidate_payload()
        missing.pop("summary")
        unexpected = {**candidate_payload(), "untrusted-secret-key": "secret-value"}
        wrong_type = {**candidate_payload(), "summary": 7}
        enum_mismatch = candidate_payload()
        enum_mismatch["facts"][0]["freshness"] = "FRESH_SECRET_VALUE"
        null_value = {**candidate_payload(), "summary": None}
        nested = candidate_payload()
        nested["facts"][0].pop("factId")
        constrained = {**candidate_payload(), "summary": ""}
        cases = (
            (
                "not-json-secret",
                ResponseValidationCode.JSON_DECODE_FAILED,
                ResponseTopLevelType.UNKNOWN,
                None,
                (),
            ),
            (
                '{"summary":"one","summary":"two"}',
                ResponseValidationCode.DUPLICATE_KEY,
                ResponseTopLevelType.UNKNOWN,
                None,
                (),
            ),
            (
                "[]",
                ResponseValidationCode.TOP_LEVEL_NOT_OBJECT,
                ResponseTopLevelType.ARRAY,
                None,
                (),
            ),
            (
                json.dumps(missing),
                ResponseValidationCode.REQUIRED_FIELD_MISSING,
                ResponseTopLevelType.OBJECT,
                ResponseContractField.SUMMARY,
                (ResponseContractField.SUMMARY,),
            ),
            (
                json.dumps(unexpected),
                ResponseValidationCode.UNEXPECTED_FIELD,
                ResponseTopLevelType.OBJECT,
                ResponseContractField.UNKNOWN_OR_UNEXPECTED,
                (),
            ),
            (
                json.dumps(wrong_type),
                ResponseValidationCode.FIELD_TYPE_INVALID,
                ResponseTopLevelType.OBJECT,
                ResponseContractField.SUMMARY,
                (),
            ),
            (
                json.dumps(enum_mismatch),
                ResponseValidationCode.ENUM_VALUE_INVALID,
                ResponseTopLevelType.OBJECT,
                ResponseContractField.FACTS,
                (),
            ),
            (
                json.dumps(null_value),
                ResponseValidationCode.NULL_NOT_ALLOWED,
                ResponseTopLevelType.OBJECT,
                ResponseContractField.SUMMARY,
                (),
            ),
            (
                json.dumps(nested),
                ResponseValidationCode.NESTED_SCHEMA_INVALID,
                ResponseTopLevelType.OBJECT,
                ResponseContractField.FACTS,
                (),
            ),
            (
                json.dumps(constrained),
                ResponseValidationCode.CONSTRAINT_VIOLATION,
                ResponseTopLevelType.OBJECT,
                ResponseContractField.SUMMARY,
                (),
            ),
        )
        for text, code, top_level, invalid_field, missing_fields in cases:
            with self.subTest(code=code):
                with self.assertRaises(AdvisorResponseParsingError) as raised:
                    parse_advisor_response(raw(responseText=text))
                error = raised.exception
                self.assertEqual(str(error), "advisor response parsing failed")
                self.assertFalse(error.diagnostic.parseSucceeded)
                self.assertEqual(error.diagnostic.validationCode, code)
                self.assertEqual(error.diagnostic.topLevelType, top_level)
                self.assertEqual(error.diagnostic.invalidField, invalid_field)
                self.assertEqual(error.diagnostic.missingFields, missing_fields)
                rendered = error.diagnostic.model_dump_json()
                for forbidden in (
                    "secret-value",
                    "untrusted-secret-key",
                    "FRESH_SECRET_VALUE",
                    "not-json-secret",
                ):
                    self.assertNotIn(forbidden, rendered)

    def test_validated_response_is_typed_sorted_and_warning_status(self):
        result = validate(raw())
        self.assertEqual(result.status, AdvisorResponseStatus.VALID_WITH_WARNINGS)
        self.assertEqual(
            tuple(item.factId for item in result.facts),
            ("fact-a", "fact-b"),
        )
        self.assertEqual(result.sourceReferences, ("advisor-runtime", "spec-a"))
        self.assertEqual(result.forbiddenClaims, ())
        for disclosure in (
            AdvisorSafetyDisclosure.READ_ONLY,
            AdvisorSafetyDisclosure.NO_ACTION_EXECUTED,
            AdvisorSafetyDisclosure.NO_STATE_CHANGED,
            AdvisorSafetyDisclosure.NO_TOOL_USED,
        ):
            self.assertIn(disclosure, result.safetyDisclosures)

    def test_valid_status_has_no_warning_unknown_or_inference(self):
        payload = candidate_payload()
        payload["inferences"] = []
        payload["sourceReferences"] = ["advisor-runtime"]
        payload["freshnessDisclosures"] = [
            {"sourceId": "advisor-runtime", "freshness": "FRESH"}
        ]
        result = validate(raw(payload))
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)
        self.assertFalse(result.validationWarnings)

    def test_request_and_prompt_mismatch_are_rejected(self):
        cases = (
            raw(requestId="other-request"),
            raw({**candidate_payload(), "requestId": "other-request"}),
            raw(promptVersion="2.0"),
            raw({**candidate_payload(), "promptVersion": "2.0"}),
        )
        for value in cases:
            with self.subTest(value=value.requestId):
                result = validate(value)
                self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
                self.assertEqual(
                    result.primaryRejectionReason,
                    AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,
                )
                self.assertEqual(result.requestId, "request-1")
                self.assertEqual(result.promptVersion, "1.0")

    def test_unknown_source_and_freshness_contradiction_are_rejected(self):
        unknown = candidate_payload()
        unknown["sourceReferences"] = ["fabricated"]
        unknown["freshnessDisclosures"] = [
            {"sourceId": "fabricated", "freshness": "FRESH"}
        ]
        unknown["facts"][0]["sourceIds"] = ["fabricated"]
        unknown["facts"][1]["sourceIds"] = ["fabricated"]
        unknown["inferences"][0]["basedOnSourceIds"] = ["fabricated"]
        contradiction = candidate_payload()
        contradiction["freshnessDisclosures"][1]["freshness"] = "STALE"
        for payload in (unknown, contradiction):
            with self.subTest(payload=payload["sourceReferences"]):
                result = validate(raw(payload))
                self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)

    def test_all_freshness_states_are_preserved_from_context(self):
        request, context, _ = trusted_inputs()
        freshness_values = {
            AdvisorFreshnessState.FRESH: build_freshness(
                state=AdvisorFreshnessState.FRESH,
                captured_at=context.capturedAt,
                source_updated_at=context.capturedAt - timedelta(seconds=1),
                age_seconds=1.0,
                valid_until=context.capturedAt + timedelta(seconds=1),
            ),
            AdvisorFreshnessState.STALE: build_freshness(
                state=AdvisorFreshnessState.STALE,
                captured_at=context.capturedAt,
                source_updated_at=context.capturedAt - timedelta(seconds=2),
                age_seconds=2.0,
            ),
            AdvisorFreshnessState.EXPIRED: build_freshness(
                state=AdvisorFreshnessState.EXPIRED,
                captured_at=context.capturedAt,
                source_updated_at=context.capturedAt - timedelta(seconds=3),
                age_seconds=3.0,
            ),
            AdvisorFreshnessState.UNKNOWN: build_freshness(
                state=AdvisorFreshnessState.UNKNOWN,
                captured_at=context.capturedAt,
                source_updated_at=None,
                age_seconds=None,
                reason="UNKNOWN_SOURCE_TIME",
            ),
            AdvisorFreshnessState.LAST_GOOD: build_freshness(
                state=AdvisorFreshnessState.LAST_GOOD,
                captured_at=context.capturedAt,
                source_updated_at=context.capturedAt - timedelta(seconds=4),
                age_seconds=4.0,
                last_good_at=context.capturedAt - timedelta(seconds=4),
                current_read_failed_at=context.capturedAt,
                failure_reason="CURRENT_READ_FAILED",
                stale_warning="LAST_GOOD_NOT_CURRENT",
            ),
            AdvisorFreshnessState.NOT_APPLICABLE: build_freshness(
                state=AdvisorFreshnessState.NOT_APPLICABLE,
                captured_at=context.capturedAt,
                source_updated_at=None,
                age_seconds=None,
                reason="VERSIONED_SPECIFICATION",
            ),
        }
        for state, freshness in freshness_values.items():
            sources = tuple(
                (
                    source.model_copy(update={"freshness": freshness})
                    if source.sourceId == "spec-a"
                    else source
                )
                for source in context.sources
            )
            changed_context = context.model_copy(update={"sources": sources})
            changed_request = request.model_copy(
                update={"contextEnvelope": changed_context}
            )
            prompt = build_advisor_prompt(
                request=changed_request,
                context=changed_context,
                policy=AdvisorPromptPolicy(),
            )
            payload = candidate_payload()
            payload["facts"] = [
                {
                    "factId": "fact-a",
                    "statement": "The source has the disclosed freshness.",
                    "sourceIds": ["spec-a"],
                    "freshness": state.value,
                }
            ]
            payload["inferences"] = []
            payload["sourceReferences"] = ["spec-a"]
            payload["freshnessDisclosures"] = [
                {"sourceId": "spec-a", "freshness": state.value}
            ]
            result = validate_advisor_response(
                raw_response=raw(payload),
                request=changed_request,
                context=changed_context,
                prompt_envelope=prompt,
            )
            self.assertEqual(result.status, AdvisorResponseStatus.VALID)
            self.assertEqual(result.facts[0].freshness, state)
            self.assertEqual(result.freshnessDisclosures[0].freshness, state)

    def test_duplicate_ids_and_references_are_rejected(self):
        mutations = []
        duplicate_fact = candidate_payload()
        duplicate_fact["facts"][1]["factId"] = duplicate_fact["facts"][0]["factId"]
        mutations.append(duplicate_fact)
        duplicate_source = candidate_payload()
        duplicate_source["sourceReferences"] = [
            "advisor-runtime",
            "advisor-runtime",
        ]
        mutations.append(duplicate_source)
        for payload in mutations:
            self.assertEqual(
                validate(raw(payload)).status,
                AdvisorResponseStatus.REJECTED,
            )

    def test_all_unknown_reason_enums_parse_without_inference(self):
        for reason in AdvisorUnknownReason:
            payload = candidate_payload()
            payload["facts"] = []
            payload["inferences"] = []
            payload["sourceReferences"] = []
            payload["freshnessDisclosures"] = []
            payload["unknowns"] = [
                {
                    "unknownId": "unknown-a",
                    "topic": "Current value is unavailable.",
                    "reason": reason.value,
                    "requiredSourceType": None,
                }
            ]
            result = validate(raw(payload))
            self.assertEqual(result.status, AdvisorResponseStatus.VALID_WITH_WARNINGS)
            self.assertEqual(result.unknowns[0].reason, reason)
            self.assertFalse(result.facts)

    def test_forbidden_claims_are_classified_and_rejected(self):
        cases = {
            "I executed the trade.": AdvisorForbiddenClaim.EXECUTION_CLAIM,
            "The order has been submitted.": AdvisorForbiddenClaim.ORDER_ACTION_CLAIM,
            "I cancelled the order.": AdvisorForbiddenClaim.ORDER_ACTION_CLAIM,
            "I closed the position.": AdvisorForbiddenClaim.POSITION_ACTION_CLAIM,
            "I enabled Auto Trade.": AdvisorForbiddenClaim.BOT_CONTROL_CLAIM,
            "I started the Loop.": AdvisorForbiddenClaim.BOT_CONTROL_CLAIM,
            "I overrode Governance.": AdvisorForbiddenClaim.GOVERNANCE_OVERRIDE_CLAIM,
            "I used the shell.": AdvisorForbiddenClaim.TOOL_USE_CLAIM,
            "I read the local file.": AdvisorForbiddenClaim.FILESYSTEM_ACCESS_CLAIM,
            "I called the API.": AdvisorForbiddenClaim.NETWORK_ACCESS_CLAIM,
            "I am authorized to execute.": AdvisorForbiddenClaim.AUTHORITY_ESCALATION_CLAIM,
        }
        for statement, code in cases.items():
            with self.subTest(code=code):
                payload = candidate_payload()
                payload["summary"] = statement
                result = validate(raw(payload))
                self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
                self.assertIn(code, result.forbiddenClaims)
                self.assertNotIn(statement, result.summary)

    def test_secret_and_path_never_reach_response_exception_or_fallback(self):
        values = (
            "api_key=SECRET_RESPONSE_VALUE",
            "sk-abcdefghijklmnopqrstuvwxyz",
            "Bearer SECRET_RESPONSE_VALUE",
            "/home/user/private.txt",
            r"C:\Users\user\private.txt",
            r"\\server\share\private.txt",
            "file:///home/user/private.txt",
            "docs/../../etc/passwd",
            "docs/%2e%2e/secret",
        )
        for value in values:
            with self.subTest(kind=value[:4]):
                payload = candidate_payload()
                payload["summary"] = value
                result = validate(raw(payload))
                serialized = result.model_dump_json()
                self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
                self.assertNotIn(value, serialized)
                self.assertNotIn("SECRET_RESPONSE_VALUE", serialized)
                self.assertEqual(result.summary, REJECTED_SUMMARY)

    def test_secret_detection_covers_every_free_text_field(self):
        secret = "api_key=ALL_FIELD_SECRET_VALUE"
        payloads = []
        for field in ("summary",):
            payload = candidate_payload()
            payload[field] = secret
            payloads.append(payload)
        payload = candidate_payload()
        payload["facts"][0]["statement"] = secret
        payloads.append(payload)
        payload = candidate_payload()
        payload["inferences"][0]["statement"] = secret
        payloads.append(payload)
        payload = candidate_payload()
        payload["unknowns"] = [
            {
                "unknownId": "unknown-a",
                "topic": secret,
                "reason": "INSUFFICIENT_CONTEXT",
                "requiredSourceType": None,
            }
        ]
        payloads.append(payload)
        payload = candidate_payload()
        payload["warnings"] = [{"code": "SAFETY_LIMITATION", "message": secret}]
        payloads.append(payload)
        payload = candidate_payload()
        payload["sourceReferences"] = [secret]
        payload["freshnessDisclosures"] = [{"sourceId": secret, "freshness": "FRESH"}]
        payloads.append(payload)
        payload = candidate_payload()
        payload["summary"] = "Your API key is ALL_FIELD_SECRET_VALUE"
        payloads.append(payload)
        for payload in payloads:
            result = validate(raw(payload))
            serialized = result.model_dump_json()
            self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
            self.assertIn(
                AdvisorForbiddenClaim.SECRET_DISCLOSURE_CLAIM,
                result.forbiddenClaims,
            )
            self.assertNotIn("ALL_FIELD_SECRET_VALUE", serialized)

    def test_malformed_secret_json_returns_safe_fallback(self):
        value = raw(responseText='{"summary":"api_key=RAW_SECRET_VALUE"')
        result = validate(value)
        self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
        self.assertNotIn("RAW_SECRET_VALUE", result.model_dump_json())

    def test_fallback_is_fixed_empty_and_deterministic(self):
        value = raw(responseText="not json")
        first = validate(value)
        second = validate(value)
        self.assertEqual(first, second)
        self.assertEqual(first.model_dump_json(), second.model_dump_json())
        self.assertEqual(first.summary, REJECTED_SUMMARY)
        self.assertFalse(first.facts)
        self.assertFalse(first.inferences)
        self.assertFalse(first.sourceReferences)
        self.assertIn(
            AdvisorSafetyDisclosure.NO_ACTION_EXECUTED,
            first.safetyDisclosures,
        )

    def test_ordering_is_independent_of_provider_array_order(self):
        first = candidate_payload()
        second = deepcopy(first)
        second["facts"].reverse()
        second["sourceReferences"].reverse()
        second["freshnessDisclosures"].reverse()
        second["safetyDisclosures"].reverse()
        self.assertEqual(validate(raw(first)), validate(raw(second)))

    def test_serialization_round_trip_preserves_model_and_rendered_data(self):
        result = validate(raw())
        from_json = AdvisorResponseEnvelope.model_validate_json(
            result.model_dump_json()
        )
        from_dict = AdvisorResponseEnvelope.model_validate(result.model_dump())
        self.assertEqual(from_json, result)
        self.assertEqual(from_dict, result)
        self.assertEqual(from_json.model_dump_json(), result.model_dump_json())
        self.assertIsInstance(from_json.facts, tuple)

    def test_contract_is_deeply_frozen_extra_forbidden_and_datetime_strict(self):
        value = raw()
        result = validate(value)
        with self.assertRaises(ValidationError):
            value.requestId = "changed"
        with self.assertRaises(ValidationError):
            result.summary = "changed"
        with self.assertRaises(ValidationError):
            result.facts += (result.facts[0],)
        with self.assertRaises(ValidationError):
            result.facts[0].statement = "changed"
        with self.assertRaises(ValidationError):
            AdvisorRawResponse(
                requestId="request-1",
                promptVersion="1.0",
                responseFormatVersion="1.0",
                responseText="{}",
                receivedAt=datetime(2026, 1, 1),
            )
        payload = result.model_dump()
        payload["extra"] = True
        with self.assertRaises(ValidationError):
            AdvisorResponseEnvelope.model_validate(payload)

    def test_size_boundaries_reject_without_truncation(self):
        base = dict(
            requestId="request-1",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            receivedAt=NOW,
        )
        for length in (
            MAX_RAW_RESPONSE_CHARACTERS - 1,
            MAX_RAW_RESPONSE_CHARACTERS,
        ):
            self.assertEqual(
                len(AdvisorRawResponse(responseText="x" * length, **base).responseText),
                length,
            )
        with self.assertRaises(ValidationError):
            AdvisorRawResponse(
                responseText="x" * (MAX_RAW_RESPONSE_CHARACTERS + 1),
                **base,
            )
        payload = candidate_payload()
        payload["summary"] = "x" * 8001
        self.assertEqual(validate(raw(payload)).status, AdvisorResponseStatus.REJECTED)

    def test_collection_statement_and_enum_boundaries_fail_closed(self):
        payloads = []
        empty_fact = candidate_payload()
        empty_fact["facts"][0]["statement"] = ""
        payloads.append(empty_fact)
        invalid_enum = candidate_payload()
        invalid_enum["inferences"][0]["uncertainty"] = "CERTAIN"
        payloads.append(invalid_enum)
        too_many_facts = candidate_payload()
        too_many_facts["facts"] = [
            {
                "factId": f"fact-{index}",
                "statement": "Fact.",
                "sourceIds": ["advisor-runtime"],
                "freshness": "FRESH",
            }
            for index in range(33)
        ]
        payloads.append(too_many_facts)
        too_many_inferences = candidate_payload()
        too_many_inferences["inferences"] = [
            {
                "inferenceId": f"inference-{index}",
                "statement": "Inference.",
                "basedOnSourceIds": ["advisor-runtime"],
                "uncertainty": "HIGH",
            }
            for index in range(17)
        ]
        payloads.append(too_many_inferences)
        too_many_unknowns = candidate_payload()
        too_many_unknowns["unknowns"] = [
            {
                "unknownId": f"unknown-{index}",
                "topic": "Unknown.",
                "reason": "INSUFFICIENT_CONTEXT",
                "requiredSourceType": None,
            }
            for index in range(17)
        ]
        payloads.append(too_many_unknowns)
        too_many_warnings = candidate_payload()
        too_many_warnings["warnings"] = [
            {"code": "SAFETY_LIMITATION", "message": f"Warning {index}"}
            for index in range(33)
        ]
        payloads.append(too_many_warnings)
        for payload in payloads:
            result = validate(raw(payload))
            self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
            self.assertEqual(
                result.primaryRejectionReason,
                AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,
            )

    def test_input_isolation_and_side_effect_freedom(self):
        value = raw()
        request, context, prompt = trusted_inputs()
        before = (
            value.model_dump_json(),
            request.model_dump_json(),
            context.model_dump_json(),
            prompt.model_dump_json(),
        )
        with (
            patch.object(builtins, "open", side_effect=AssertionError("open")),
            patch.object(os, "getenv", side_effect=AssertionError("environment")),
            patch.object(socket, "socket", side_effect=AssertionError("network")),
        ):
            validate_advisor_response(
                raw_response=value,
                request=request,
                context=context,
                prompt_envelope=prompt,
            )
        after = (
            value.model_dump_json(),
            request.model_dump_json(),
            context.model_dump_json(),
            prompt.model_dump_json(),
        )
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
