import json
import unittest

from backend.ai_advisor.authoritative_knowledge import (
    load_authoritative_specifications,
)
from backend.ai_advisor.browser_gateway import assemble_browser_service_input
from backend.ai_advisor.prompt_builder import build_advisor_prompt
from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
from backend.ai_advisor.response_models import (
    AdvisorForbiddenClaim,
    AdvisorRawResponse,
    AdvisorResponseIntegrityField,
    AdvisorResponseIntegrityViolationCode,
    AdvisorResponseStatus,
)
from backend.ai_advisor.response_parser import (
    AdvisorResponseParsingError,
    parse_advisor_response,
)
from backend.ai_advisor.response_validation import (
    validate_advisor_response_with_diagnostic,
)
from tests.test_ai_advisor_prompt_builder import NOW


QUESTION_1 = (
    "現在のTradingAIの主要コンポーネントである Market Intelligence、AI Advisor、"
    "Money Management、Market Recorder、Supervisor が、それぞれどのような役割を持ち、"
    "相互にどう関係するのか説明してください。"
)


class GroundedResponseContractAlignmentTest(unittest.TestCase):
    def setUp(self):
        specs = load_authoritative_specifications(strict=True, loaded_at=NOW)
        service_input = assemble_browser_service_input(
            prompt=QUESTION_1,
            principal_id="operator",
            now=NOW,
            request_id="question-1-contract",
            approved_specifications=specs,
        )
        self.request = service_input.request
        self.context = service_input.request.contextEnvelope
        self.prompt = build_advisor_prompt(
            request=self.request,
            context=self.context,
            policy=AdvisorPromptPolicy(),
        )
        self.source_map = {source.sourceId: source for source in self.context.sources}

    def payload(self):
        facts = (
            (
                "mi",
                "Market Intelligenceは市場状態と意思決定の根拠をレビュー可能にします。",
                "market-intelligence-component-v1.0",
            ),
            (
                "advisor",
                "AI Advisorは読み取り専用で調査、分析、説明を行います。",
                "ai-advisor-master-v1.0",
            ),
            (
                "mm",
                "Money Managementは資本配分とリスク制約を扱います。",
                "money-management-master-v1.0",
            ),
            (
                "recorder",
                "Market Recorderは再生可能な市場データを保存します。",
                "market-recorder-master-v1.0",
            ),
            (
                "supervisor",
                "Supervisorは決定論的な権限を置き換えず運用を監督します。",
                "supervisor-master-v1.1",
            ),
        )
        referenced = sorted(source_id for _, _, source_id in facts)
        return {
            "responseVersion": "1.0",
            "requestId": "question-1-contract",
            "promptVersion": "1.0",
            "summary": (
                "各コンポーネントは記録、分析、リスク管理、監督を分担し、"
                "安全境界を保ちます。"
            ),
            "facts": [
                {
                    "factId": fact_id,
                    "statement": statement,
                    "sourceIds": [source_id],
                    "freshness": "NOT_APPLICABLE",
                }
                for fact_id, statement, source_id in facts
            ],
            "inferences": [
                {
                    "inferenceId": "relationship",
                    "statement": "これらは決定論的なGovernanceとExecutionの境界内で連携します。",
                    "basedOnSourceIds": ["tradingai-constitution-v0.1"],
                    "uncertainty": "LOW",
                }
            ],
            "unknowns": [
                {
                    "unknownId": "live-state",
                    "topic": "各コンポーネントの現在の稼働状態",
                    "reason": "INSUFFICIENT_CONTEXT",
                    "requiredSourceType": "RUNTIME",
                }
            ],
            "warnings": [
                {
                    "code": "MISSING_SOURCE",
                    "message": "現在の稼働状態は静的仕様から確認できません。",
                }
            ],
            "sourceReferences": sorted(
                referenced + ["tradingai-constitution-v0.1"]
            ),
            "freshnessDisclosures": [],
            "safetyDisclosures": [
                "READ_ONLY",
                "NO_ACTION_EXECUTED",
                "NO_STATE_CHANGED",
                "NO_TOOL_USED",
                "USER_REVIEW_REQUIRED",
            ],
        }

    def raw(self, payload):
        return AdvisorRawResponse(
            requestId="question-1-contract",
            promptVersion="1.0",
            responseFormatVersion="1.0",
            responseText=json.dumps(
                payload, ensure_ascii=False, separators=(",", ":")
            ),
            receivedAt=NOW,
        )

    def aligned_payload(self):
        payload = self.payload()
        payload["freshnessDisclosures"] = [
            {
                "sourceId": source_id,
                "freshness": self.source_map[source_id].freshness.state.value,
            }
            for source_id in payload["sourceReferences"]
        ]
        return payload

    def validate(self, payload):
        return validate_advisor_response_with_diagnostic(
            raw_response=self.raw(payload),
            request=self.request,
            context=self.context,
            prompt_envelope=self.prompt,
        )

    def test_prompt_and_validator_now_define_the_same_source_closure(self):
        instruction = self.prompt.responseInstruction
        self.assertIn("must contain each distinct sourceId used", instruction)
        self.assertIn("must contain no unused sourceId", instruction)
        self.assertIn("exactly one object for each sourceReferences sourceId", instruction)

    def test_reproduces_old_prompt_valid_but_integrity_invalid_source_shape(self):
        payload = self.aligned_payload()
        unused = "ai-advisor-master-v1.0"
        payload["facts"] = [
            item for item in payload["facts"] if item["factId"] != "advisor"
        ]
        self.assertIn(unused, payload["sourceReferences"])
        outcome = self.validate(payload)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)
        self.assertEqual(
            outcome.integrityDiagnostic.violationCode,
            AdvisorResponseIntegrityViolationCode.
            SOURCE_USAGE_REFERENCE_SET_MISMATCH,
        )
        self.assertEqual(
            outcome.integrityDiagnostic.field,
            AdvisorResponseIntegrityField.SOURCE_REFERENCES,
        )

    def test_aligned_question_1_fixture_passes_parser_grounding_and_safety(self):
        payload = self.aligned_payload()
        parsed = parse_advisor_response(self.raw(payload))
        self.assertEqual(len(parsed.facts), 5)
        outcome = self.validate(payload)
        self.assertIsNone(outcome.integrityDiagnostic)
        self.assertEqual(
            outcome.response.status,
            AdvisorResponseStatus.VALID_WITH_WARNINGS,
        )
        self.assertEqual(len(outcome.response.groundedClaims), 7)
        self.assertEqual(len(outcome.response.actionableUnknowns), 1)
        self.assertEqual(
            outcome.response.actionableUnknowns[0].operationalEffect,
            "NONE",
        )
        self.assertFalse(outcome.response.forbiddenClaims)

    def test_untrusted_source_is_rejected_with_exact_diagnostic(self):
        payload = self.aligned_payload()
        payload["facts"][0]["sourceIds"] = ["provider-invented-source"]
        payload["sourceReferences"][0] = "provider-invented-source"
        payload["freshnessDisclosures"][0] = {
            "sourceId": "provider-invented-source",
            "freshness": "NOT_APPLICABLE",
        }
        outcome = self.validate(payload)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)
        self.assertEqual(
            outcome.integrityDiagnostic.violationCode,
            AdvisorResponseIntegrityViolationCode.SOURCE_REFERENCE_NOT_TRUSTED,
        )

    def test_static_source_cannot_claim_current_live_state(self):
        payload = self.aligned_payload()
        payload["summary"] = "The current Risk State is NORMAL."
        payload["facts"][2]["statement"] = "The current Risk State is NORMAL."
        outcome = self.validate(payload)
        self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)
        self.assertIn(
            AdvisorForbiddenClaim.UNGROUNDED_CURRENT_RUNTIME_CLAIM,
            outcome.response.forbiddenClaims,
        )

    def test_executed_order_and_config_change_claims_remain_rejected(self):
        for summary, claim in (
            (
                "The order has been submitted.",
                AdvisorForbiddenClaim.ORDER_ACTION_CLAIM,
            ),
            (
                "Change risk_percent now.",
                AdvisorForbiddenClaim.BOT_CONTROL_CLAIM,
            ),
        ):
            with self.subTest(claim=claim):
                payload = self.aligned_payload()
                payload["summary"] = summary
                outcome = self.validate(payload)
                self.assertEqual(outcome.response.status, AdvisorResponseStatus.REJECTED)
                self.assertIn(claim, outcome.response.forbiddenClaims)

    def test_malformed_unknown_fails_closed_in_parser(self):
        payload = self.aligned_payload()
        payload["unknowns"][0].pop("topic")
        with self.assertRaises(AdvisorResponseParsingError):
            parse_advisor_response(self.raw(payload))

    def test_valid_partial_grounded_response_is_accepted(self):
        payload = self.aligned_payload()
        payload["facts"] = payload["facts"][:1]
        payload["inferences"] = []
        payload["sourceReferences"] = [payload["facts"][0]["sourceIds"][0]]
        payload["freshnessDisclosures"] = [
            {
                "sourceId": payload["sourceReferences"][0],
                "freshness": "NOT_APPLICABLE",
            }
        ]
        outcome = self.validate(payload)
        self.assertEqual(
            outcome.response.status,
            AdvisorResponseStatus.VALID_WITH_WARNINGS,
        )
        self.assertEqual(len(outcome.response.facts), 1)
        self.assertEqual(len(outcome.response.actionableUnknowns), 1)


if __name__ == "__main__":
    unittest.main()
