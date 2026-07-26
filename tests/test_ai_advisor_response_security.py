import json
import unittest

from pydantic import ValidationError

from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
from backend.ai_advisor.prompt_builder import build_advisor_prompt
from backend.ai_advisor.response_models import (
    REJECTED_SUMMARY,
    AdvisorForbiddenClaim,
    AdvisorResponseEnvelope,
    AdvisorResponseStatus,
    AdvisorSafetyDisclosure,
)
from backend.ai_advisor.response_parser import parse_advisor_response
from backend.ai_advisor.response_validation import validate_advisor_response
from tests.test_ai_advisor_response_validation import (
    candidate_payload,
    raw,
    trusted_inputs,
    validate,
)


class AdvisorResponseSecurityTest(unittest.TestCase):
    def test_duplicate_json_keys_are_rejected_at_every_depth(self):
        payloads = (
            '{"requestId":"request-1","requestId":"attacker"}',
            (
                '{"responseVersion":"1.0","requestId":"request-1",'
                '"promptVersion":"1.0","summary":"a","summary":"b",'
                '"facts":[],"inferences":[],"unknowns":[],"warnings":[],'
                '"sourceReferences":[],"freshnessDisclosures":[],'
                '"safetyDisclosures":[]}'
            ),
            (
                '{"responseVersion":"1.0","requestId":"request-1",'
                '"promptVersion":"1.0","summary":"a",'
                '"facts":[{"factId":"a","factId":"b","statement":"x",'
                '"sourceIds":["advisor-runtime"],"freshness":"FRESH"}],'
                '"inferences":[],"unknowns":[],"warnings":[],'
                '"sourceReferences":["advisor-runtime"],'
                '"freshnessDisclosures":['
                '{"sourceId":"advisor-runtime","freshness":"FRESH"}],'
                '"safetyDisclosures":[]}'
            ),
        )
        for response_text in payloads:
            value = raw(responseText=response_text)
            with self.assertRaises(ValueError) as raised:
                parse_advisor_response(value)
            self.assertEqual(str(raised.exception), "advisor response parsing failed")
            self.assertEqual(validate(value).status, AdvisorResponseStatus.REJECTED)

    def test_non_object_trailing_markdown_bom_and_multiple_documents_fail(self):
        values = (
            "[]",
            '"text"',
            "1",
            "true",
            "null",
            json.dumps(candidate_payload()) + " trailing",
            json.dumps(candidate_payload()) + json.dumps(candidate_payload()),
            "```json\n" + json.dumps(candidate_payload()) + "\n```",
            "\ufeff" + json.dumps(candidate_payload()),
            "/*comment*/" + json.dumps(candidate_payload()),
            "[" * 1500 + "]" * 1500,
        )
        for response_text in values:
            with self.subTest(prefix=response_text[:10]):
                value = raw(responseText=response_text)
                with self.assertRaises(ValueError) as raised:
                    parse_advisor_response(value)
                self.assertEqual(
                    str(raised.exception),
                    "advisor response parsing failed",
                )

    def test_model_copy_and_nested_bypass_are_revalidated(self):
        value = raw().model_copy(update={"responseText": ""})
        request, context, prompt = trusted_inputs()
        with self.assertRaises(ValueError) as raised:
            validate_advisor_response(
                raw_response=value,
                request=request,
                context=context,
                prompt_envelope=prompt,
            )
        self.assertEqual(
            str(raised.exception),
            "advisor response validation input failed",
        )
        invalid_context = context.model_copy(
            update={"sources": context.sources + (context.sources[0],)}
        )
        with self.assertRaises(ValueError) as raised:
            validate_advisor_response(
                raw_response=raw(),
                request=request,
                context=invalid_context,
                prompt_envelope=prompt,
            )
        self.assertEqual(
            str(raised.exception),
            "advisor response validation input failed",
        )

    def test_candidate_and_nested_collections_are_deeply_immutable(self):
        candidate = parse_advisor_response(raw())
        result = validate(raw())
        with self.assertRaises(ValidationError):
            candidate.summary = "changed"
        with self.assertRaises(ValidationError):
            candidate.facts[0].statement = "changed"
        with self.assertRaises(ValidationError):
            candidate.inferences[0].uncertainty = "LOW"
        with self.assertRaises(ValidationError):
            candidate.facts += (candidate.facts[0],)
        with self.assertRaises(ValidationError):
            candidate.inferences += (candidate.inferences[0],)
        with self.assertRaises(ValidationError):
            candidate.sourceReferences += ("extra",)
        with self.assertRaises(ValidationError):
            candidate.freshnessDisclosures += (candidate.freshnessDisclosures[0],)
        with self.assertRaises(ValidationError):
            candidate.safetyDisclosures += (
                AdvisorSafetyDisclosure.USER_REVIEW_REQUIRED,
            )
        with self.assertRaises(ValidationError):
            result.forbiddenClaims += (AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,)

    def test_request_prompt_binding_uses_exact_trusted_values(self):
        request, context, prompt = trusted_inputs()
        cases = (
            (request.model_copy(update={"requestId": "Request-1"}), context, prompt),
            (
                request.model_copy(update={"requestId": "request-1 "}),
                context,
                prompt,
            ),
            (
                request,
                context,
                prompt.model_copy(update={"requestId": "request\u200b-1"}),
            ),
        )
        for changed_request, changed_context, changed_prompt in cases:
            result = validate_advisor_response(
                raw_response=raw(),
                request=changed_request,
                context=changed_context,
                prompt_envelope=changed_prompt,
            )
            self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
            self.assertEqual(result.requestId, changed_request.requestId)
            self.assertEqual(
                result.promptVersion,
                changed_prompt.promptVersion,
            )

        invalid_prompt = prompt.model_copy(update={"promptVersion": "2.0"})
        with self.assertRaises(ValueError) as raised:
            validate_advisor_response(
                raw_response=raw(),
                request=request,
                context=context,
                prompt_envelope=invalid_prompt,
            )
        self.assertEqual(
            str(raised.exception),
            "advisor response validation input failed",
        )

    def test_source_fabrication_variants_fail_exact_matching(self):
        source_ids = (
            "Advisor-runtime",
            "advisor-runtime ",
            "advisor-runt\u0456me",
            "advisor-\u200bruntime",
            "missing-source",
        )
        for source_id in source_ids:
            payload = candidate_payload()
            payload["facts"][0]["sourceIds"] = [source_id]
            payload["facts"][1]["sourceIds"] = [source_id]
            payload["inferences"][0]["basedOnSourceIds"] = [source_id]
            payload["sourceReferences"] = [source_id]
            payload["freshnessDisclosures"] = [
                {"sourceId": source_id, "freshness": "FRESH"}
            ]
            self.assertEqual(
                validate(raw(payload)).status,
                AdvisorResponseStatus.REJECTED,
            )

    def test_unused_source_disclosure_and_missing_used_reference_fail(self):
        missing = candidate_payload()
        missing["sourceReferences"] = ["spec-a"]
        missing["freshnessDisclosures"] = [
            {"sourceId": "spec-a", "freshness": "NOT_APPLICABLE"}
        ]
        duplicate = candidate_payload()
        duplicate["freshnessDisclosures"].append(
            {"sourceId": "advisor-runtime", "freshness": "STALE"}
        )
        undeclared = candidate_payload()
        undeclared["freshnessDisclosures"].append(
            {"sourceId": "spec-b", "freshness": "NOT_APPLICABLE"}
        )
        unused = candidate_payload()
        unused["sourceReferences"].append("spec-b")
        unused["freshnessDisclosures"].append(
            {"sourceId": "spec-b", "freshness": "NOT_APPLICABLE"}
        )
        for payload in (missing, duplicate, undeclared, unused):
            self.assertEqual(
                validate(raw(payload)).status,
                AdvisorResponseStatus.REJECTED,
            )

    def test_english_japanese_and_obfuscated_claims_are_rejected(self):
        claims = (
            "I have executed the trade.",
            "The trade was executed by me.",
            "I ex ecuted the trade.",
            "I exe-cuted the trade.",
            "Order submitted successfully.",
            "Order sub-mitted successfully.",
            "The order is now live.",
            "Position closed.",
            "Auto Trade enabled.",
            "Loop started.",
            "tool\nused",
            "governance\noverridden",
            "I exe\u200bcuted the trade.",
            "Ｉ ｅｘｅｃｕｔｅｄ ｔｈｅ ｔｒａｄｅ.",
            "I &#x65;xecuted the trade.",
            "取引を実行しました",
            "注文を送信しました",
            "ポジションを決済しました",
            "自動売買を有効にしました",
            "ループを開始しました",
            "ガバナンスを上書きしました",
            "APIを呼び出しました",
            "ファイルを読みました",
        )
        for claim in claims:
            payload = candidate_payload()
            payload["summary"] = claim
            result = validate(raw(payload))
            self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
            self.assertNotIn(claim, result.summary)

    def test_negation_and_explanation_are_not_false_execution_claims(self):
        safe_statements = (
            "I did not execute the trade.",
            "No order was submitted.",
            "取引は実行していません。",
            "The Execution component can submit orders.",
            "AI Advisor does not execute trades.",
            "A Loop ON operation exists.",
            "Governance can reject Execution.",
            "注文を送信する機能はExecutionが担当します。",
        )
        for statement in safe_statements:
            payload = candidate_payload()
            payload["summary"] = statement
            result = validate(raw(payload))
            self.assertNotEqual(result.status, AdvisorResponseStatus.REJECTED)

    def test_secret_obfuscation_and_json_escaping_fail_closed(self):
        secrets = (
            "A P I _ K E Y = LEAKVALUE",
            "api-key = LEAKVALUE",
            "KuCoin secret = LEAKVALUE",
            "KuCoin\npassphrase=LEAKVALUE",
            "Authorization: Bearer LEAKVALUE",
            "Pass'word=LEAKVALUE",
            "Your API key is LEAKVALUE",
        )
        for secret in secrets:
            payload = candidate_payload()
            payload["summary"] = secret
            result = validate(raw(payload))
            self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
            self.assertIn(
                AdvisorForbiddenClaim.SECRET_DISCLOSURE_CLAIM,
                result.forbiddenClaims,
            )
            self.assertNotIn("LEAKVALUE", result.model_dump_json())

    def test_encoded_and_obfuscated_paths_fail_closed(self):
        paths = (
            "//server/share/file",
            "%252e%252e%252fsecret",
            ".%2e/secret",
            "..%2fsecret",
            "..%5csecret",
            "..\n/secret",
            "/home/\u200buser/file",
            "&#x2f;home&#x2f;user&#x2f;file",
            '"C:/Users/user/file"',
            r"C:\Users/user\file",
        )
        for path in paths:
            payload = candidate_payload()
            payload["summary"] = path
            result = validate(raw(payload))
            self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
            self.assertNotIn(path, result.model_dump_json())

    def test_multiple_violation_priority_is_input_order_independent(self):
        first = candidate_payload()
        first["summary"] = "I executed the trade. api_key=SECRET"
        first["warnings"] = [
            {"code": "SAFETY_LIMITATION", "message": "/home/user/file"}
        ]
        second = candidate_payload()
        second["summary"] = "api_key=SECRET I executed the trade."
        second["warnings"] = list(reversed(first["warnings"]))
        first_result = validate(raw(first))
        second_result = validate(raw(second))
        self.assertEqual(
            first_result.forbiddenClaims,
            second_result.forbiddenClaims,
        )
        self.assertEqual(
            first_result.primaryRejectionReason,
            AdvisorForbiddenClaim.SECRET_DISCLOSURE_CLAIM,
        )
        self.assertEqual(first_result.model_dump(), second_result.model_dump())

    def test_every_collection_has_stable_ordering(self):
        first = candidate_payload()
        first["inferences"].append(
            {
                "inferenceId": "inference-b",
                "statement": "A second inference.",
                "basedOnSourceIds": ["advisor-runtime"],
                "uncertainty": "MEDIUM",
            }
        )
        first["unknowns"] = [
            {
                "unknownId": "unknown-b",
                "topic": "Unknown B.",
                "reason": "INSUFFICIENT_CONTEXT",
                "requiredSourceType": None,
            },
            {
                "unknownId": "unknown-a",
                "topic": "Unknown A.",
                "reason": "SOURCE_MISSING",
                "requiredSourceType": "MARKET_INTELLIGENCE",
            },
        ]
        first["warnings"] = [
            {"code": "STALE_SOURCE", "message": "Warning B."},
            {"code": "SAFETY_LIMITATION", "message": "Warning A."},
        ]
        second = json.loads(json.dumps(first))
        for name in (
            "facts",
            "inferences",
            "unknowns",
            "warnings",
            "sourceReferences",
            "freshnessDisclosures",
            "safetyDisclosures",
        ):
            second[name].reverse()
        first_result = validate(raw(first))
        second_result = validate(raw(second))
        self.assertEqual(first_result, second_result)
        self.assertEqual(first_result.model_dump(), second_result.model_dump())
        self.assertEqual(
            first_result.model_dump_json(),
            second_result.model_dump_json(),
        )

    def test_fallback_contract_rejects_contamination(self):
        result = validate(raw(responseText="not json"))
        self.assertEqual(result.summary, REJECTED_SUMMARY)
        self.assertFalse(result.facts)
        self.assertFalse(result.inferences)
        self.assertFalse(result.unknowns)
        self.assertFalse(result.warnings)
        self.assertFalse(result.sourceReferences)
        self.assertFalse(result.freshnessDisclosures)
        for disclosure in (
            AdvisorSafetyDisclosure.NO_ACTION_EXECUTED,
            AdvisorSafetyDisclosure.NO_STATE_CHANGED,
            AdvisorSafetyDisclosure.NO_TOOL_USED,
            AdvisorSafetyDisclosure.USER_REVIEW_REQUIRED,
        ):
            self.assertIn(disclosure, result.safetyDisclosures)

        payload = result.model_dump()
        payload["summary"] = "attacker text"
        with self.assertRaises(ValidationError):
            AdvisorResponseEnvelope.model_validate(payload)

    def test_warning_status_requires_actual_warning_content(self):
        result = validate(raw(responseText="not json"))
        payload = result.model_dump()
        payload.update(
            {
                "status": AdvisorResponseStatus.VALID_WITH_WARNINGS,
                "summary": "Safe summary.",
                "forbiddenClaims": (),
                "primaryRejectionReason": None,
            }
        )
        with self.assertRaises(ValidationError):
            AdvisorResponseEnvelope.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
