import unittest

from backend.ai_advisor.response_models import (
    AdvisorForbiddenClaim,
    AdvisorResponseStatus,
    AdvisorSafetyDisclosure,
)
from tests.test_ai_advisor_response_validation import candidate_payload, raw, validate


def response_with_summary(summary: str):
    payload = candidate_payload()
    payload["summary"] = summary
    return validate(raw(payload))


class AdvisorAdvisorySafetyContractTest(unittest.TestCase):
    def test_advisory_no_trade_and_read_only_entry_analysis_are_allowed(self):
        statements = (
            "What conditions should make me avoid entering a trade?",
            "Before considering BTCUSDT, inspect Market Intelligence, Money Management, and Market Recorder.",
            "If Money Management is defensive or required market data is unavailable, do not trade.",
            "Do not submit this order if required market data is unavailable.",
            "Never enable live trading when safety state is unknown.",
            "必要な市場データが利用できない場合は、取引を見送ってください。",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                result = response_with_summary(statement)
                self.assertIsNot(result.status, AdvisorResponseStatus.REJECTED)
                self.assertFalse(result.forbiddenClaims)
                for disclosure in (
                    AdvisorSafetyDisclosure.READ_ONLY,
                    AdvisorSafetyDisclosure.NO_ACTION_EXECUTED,
                    AdvisorSafetyDisclosure.NO_STATE_CHANGED,
                    AdvisorSafetyDisclosure.NO_TOOL_USED,
                ):
                    self.assertIn(disclosure, result.safetyDisclosures)

    def test_actual_execution_and_control_claims_remain_rejected(self):
        cases = {
            "Submit this order now.": AdvisorForbiddenClaim.ORDER_ACTION_CLAIM,
            "I executed the trade.": AdvisorForbiddenClaim.EXECUTION_CLAIM,
            "Enable live trading.": AdvisorForbiddenClaim.BOT_CONTROL_CLAIM,
            "Position closed.": AdvisorForbiddenClaim.POSITION_ACTION_CLAIM,
        }
        for statement, expected in cases.items():
            with self.subTest(statement=statement):
                result = response_with_summary(statement)
                self.assertIs(result.status, AdvisorResponseStatus.REJECTED)
                self.assertIn(expected, result.forbiddenClaims)

    def test_ungrounded_current_market_claim_is_rejected(self):
        result = response_with_summary("BTCUSDT is currently bullish.")
        self.assertIs(result.status, AdvisorResponseStatus.REJECTED)
        self.assertIs(
            result.primaryRejectionReason,
            AdvisorForbiddenClaim.UNGROUNDED_CURRENT_MARKET_CLAIM,
        )

    def test_fabricated_source_rejection_is_unchanged(self):
        payload = candidate_payload()
        payload["facts"][0]["sourceIds"] = ["fabricated-market-source"]
        payload["facts"][1]["sourceIds"] = ["fabricated-market-source"]
        payload["inferences"][0]["basedOnSourceIds"] = [
            "fabricated-market-source"
        ]
        payload["sourceReferences"] = ["fabricated-market-source"]
        payload["freshnessDisclosures"] = [
            {"sourceId": "fabricated-market-source", "freshness": "FRESH"}
        ]
        result = validate(raw(payload))
        self.assertIs(result.status, AdvisorResponseStatus.REJECTED)
        self.assertIn(
            AdvisorForbiddenClaim.RESPONSE_CONTRACT_INVALID,
            result.forbiddenClaims,
        )


if __name__ == "__main__":
    unittest.main()
