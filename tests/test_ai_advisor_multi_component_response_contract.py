import json
import unittest

from backend.ai_advisor.advisor_service import AdvisorService
from backend.ai_advisor.browser_gateway import assemble_browser_service_input
from backend.ai_advisor.mock_provider import MockAdvisorProvider, MockProviderFixture
from backend.ai_advisor.service_models import AdvisorServiceStatus
from tests.test_ai_advisor_prompt_builder import NOW
from tests.test_ai_advisor_provider_contract import capabilities, config, model_policy


QUESTION = (
    "現在のTradingAIの主要コンポーネントである Market Intelligence、AI Advisor、"
    "Money Management、Market Recorder、Supervisor が、それぞれどのような役割を持ち、"
    "相互にどう関係するのか説明してください。"
)


class MultiComponentResponseContractRegressionTest(unittest.TestCase):
    def test_source_less_multi_component_answer_is_accepted_without_claiming_facts(self):
        service_input = assemble_browser_service_input(
            prompt=QUESTION,
            principal_id="operator-1",
            now=NOW,
            request_id="request-1",
        )
        payload = {
            "responseVersion": "1.0",
            "requestId": "request-1",
            "promptVersion": "1.0",
            "summary": "利用可能な承認済み資料がないため、構成の詳細は確認できません。",
            "facts": [{
                "factId": "fact-1",
                "statement": "根拠のない構成説明",
                "sourceIds": [],
                "freshness": "UNKNOWN",
            }],
            "inferences": [],
            "unknowns": [{
                "unknownId": "unknown-1",
                "topic": "TradingAIコンポーネントの役割と関係",
                "reason": "SOURCE_MISSING",
                "requiredSourceType": "SPECIFICATION",
            }],
            "warnings": [{"code": "MISSING_SOURCE"}],
            "sourceReferences": [],
            "freshnessDisclosures": [],
            "safetyDisclosures": [
                "READ_ONLY",
                "NO_ACTION_EXECUTED",
                "NO_STATE_CHANGED",
                "NO_TOOL_USED",
            ],
        }
        provider = MockAdvisorProvider(
            MockProviderFixture(responseText=json.dumps(payload, ensure_ascii=False))
        )
        advisor = AdvisorService(
            provider=provider,
            providerConfig=config(),
            modelPolicy=model_policy(),
            capabilities=capabilities(),
        )

        result = advisor.generate_response(service_input)

        self.assertEqual(result.status, AdvisorServiceStatus.SUCCEEDED)
        self.assertEqual(result.response.summary, payload["summary"])
        self.assertEqual(result.response.facts, ())
        self.assertEqual(result.response.sourceReferences, ())

    def test_claimed_source_is_not_normalized_into_success(self):
        service_input = assemble_browser_service_input(
            prompt=QUESTION,
            principal_id="operator-1",
            now=NOW,
            request_id="request-1",
        )
        payload = {
            "responseVersion": "1.0",
            "requestId": "request-1",
            "promptVersion": "1.0",
            "summary": "unsupported",
            "facts": [{
                "factId": "fact-1",
                "statement": "fabricated",
                "sourceIds": ["fabricated-source"],
                "freshness": "FRESH",
            }],
            "inferences": [],
            "unknowns": [],
            "warnings": [],
            "sourceReferences": ["fabricated-source"],
            "freshnessDisclosures": [{
                "sourceId": "fabricated-source",
                "freshness": "FRESH",
            }],
            "safetyDisclosures": ["READ_ONLY"],
        }
        advisor = AdvisorService(
            provider=MockAdvisorProvider(
                MockProviderFixture(responseText=json.dumps(payload))
            ),
            providerConfig=config(),
            modelPolicy=model_policy(),
            capabilities=capabilities(),
        )

        result = advisor.generate_response(service_input)

        self.assertEqual(result.status, AdvisorServiceStatus.SUCCEEDED)
        self.assertEqual(result.response.status.value, "REJECTED")
        self.assertEqual(result.response.sourceReferences, ())


if __name__ == "__main__":
    unittest.main()
