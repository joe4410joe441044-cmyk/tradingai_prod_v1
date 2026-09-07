"""Regression matrix for preserving authoritative overall MM state."""

import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from backend.ai_advisor.conversation_models import AdvisorRequest
from backend.ai_advisor.prompt_builder import build_advisor_prompt
from backend.ai_advisor.prompt_models import AdvisorPromptPolicy
from backend.ai_advisor.response_models import (
    AdvisorForbiddenClaim,
    AdvisorRawResponse,
    AdvisorResponseStatus,
)
from backend.ai_advisor.response_validation import validate_advisor_response
from backend.ai_advisor.runtime_reader import read_runtime_scalars
from backend.ai_advisor.service import build_runtime_response
from tests.test_ai_advisor_runtime_injection import (
    NOW,
    NOW_EPOCH,
    context,
    permission,
    real_authoritative_capital,
    real_mm_projection,
    real_stale_paper_metrics,
    render_runtime_prompt,
)


def manager():
    return SimpleNamespace(
        _running=False,
        lifecycle_state="STOPPED",
        config={"mode": "paper", "dry_run": True},
        exchange_name="kucoin",
        symbol="BTCUSDT",
        market_ready=False,
        active_symbol="BTCUSDT",
        exchange_client_ready=False,
        exchange_auth_ready=False,
        balance_check_ok=False,
        position_check_ok=False,
        pending_order=False,
        state=SimpleNamespace(
            runtime_metrics={"last_bot_update": NOW_EPOCH - 1},
            position_state="FLAT",
        ),
    )


def paper_capital():
    return replace(
        real_authoritative_capital(),
        capital_source="PAPER_ACCOUNT",
        input_authority="PAPER_ACCOUNT",
        equity=100,
        available_capital=100,
        risk_budget=5,
        remaining_exposure=20,
        authority_fresh=True,
    )


def projection(risk_state, *, available=True, metrics_status="AVAILABLE"):
    kwargs = {
        "risk_state": risk_state,
        "available": available,
        "metrics_status": metrics_status,
        "safe_reason": None,
        "block_reasons": (),
        "execution_entry_allowed": risk_state == "NORMAL",
        "capital_eligibility": paper_capital(),
    }
    if risk_state == "UNKNOWN":
        kwargs.update(
            safe_reason="AUTHORITATIVE_EVALUATION_NOT_ESTABLISHED",
            block_reasons=("TRADING_RUNTIME_METRICS_UNAVAILABLE",),
            execution_entry_allowed=False,
        )
    return replace(real_mm_projection(), **kwargs)


def runtime_context(mm_projection):
    boundary = SimpleNamespace(get_status=lambda: mm_projection)
    with patch(
        "backend.ai_advisor.runtime_reader.get_existing_bot_manager",
        return_value=manager(),
    ):
        snapshot = read_runtime_scalars(mm_boundary_provider=lambda: boundary)
    response = build_runtime_response(reader=lambda: snapshot, clock=lambda: NOW_EPOCH)
    return context(response)


def validate_claim(envelope, statement):
    request = AdvisorRequest(
        schemaVersion="1.0",
        requestId="request-1",
        messageId="message-1",
        message="What is the current MM state?",
        locale="en-US",
        requestedAt=NOW,
        permissionContext=permission(),
        contextEnvelope=envelope,
        responsePreferences=None,
    )
    prompt = build_advisor_prompt(
        request=request,
        context=envelope,
        policy=AdvisorPromptPolicy(),
    )
    payload = {
        "responseVersion": "1.0",
        "requestId": "request-1",
        "promptVersion": "1.0",
        "summary": statement,
        "facts": [
            {
                "factId": "mm-state",
                "statement": statement,
                "sourceIds": ["advisor-runtime"],
                "freshness": "FRESH",
            }
        ],
        "inferences": [],
        "unknowns": [],
        "warnings": [],
        "sourceReferences": ["advisor-runtime"],
        "freshnessDisclosures": [
            {"sourceId": "advisor-runtime", "freshness": "FRESH"}
        ],
        "safetyDisclosures": [
            "READ_ONLY",
            "NO_ACTION_EXECUTED",
            "NO_STATE_CHANGED",
            "NO_TOOL_USED",
        ],
    }
    raw = AdvisorRawResponse(
        requestId="request-1",
        promptVersion="1.0",
        responseFormatVersion="1.0",
        responseText=json.dumps(payload, separators=(",", ":")),
        receivedAt=NOW,
    )
    return validate_advisor_response(
        raw_response=raw,
        request=request,
        context=envelope,
        prompt_envelope=prompt,
    )


class OverallMmAuthorityProjectionTest(unittest.TestCase):
    def test_unknown_overall_authority_is_projected_beside_available_capital(self):
        envelope = runtime_context(
            projection("UNKNOWN", available=False, metrics_status="UNAVAILABLE")
        )
        mm = envelope.runtimeContext.moneyManagement

        self.assertEqual(mm.capitalAuthority, "MONEY_MANAGEMENT")
        self.assertEqual(mm.capitalSource, "PAPER_ACCOUNT")
        self.assertEqual(mm.equity, 100)
        self.assertEqual(mm.availableCapital, 100)
        self.assertEqual(mm.remainingExposure, 20)
        self.assertEqual(mm.positionCapacity, 1)
        self.assertEqual(mm.remainingPositionCapacity, 1)
        self.assertEqual(mm.riskBudget, 5)
        self.assertFalse(mm.compoundingEnabled)
        self.assertEqual(mm.riskState, "UNKNOWN")
        self.assertFalse(mm.available)
        self.assertEqual(mm.metricsStatus, "UNAVAILABLE")
        self.assertEqual(
            mm.safeReason, "AUTHORITATIVE_EVALUATION_NOT_ESTABLISHED"
        )
        self.assertEqual(
            mm.blockReasons, ("TRADING_RUNTIME_METRICS_UNAVAILABLE",)
        )
        self.assertFalse(mm.executionEntryAllowed)

    def test_prompt_keeps_capital_and_overall_authorities_separate(self):
        content = render_runtime_prompt(
            runtime_context(
                projection("UNKNOWN", available=False, metrics_status="UNAVAILABLE")
            )
        )
        for marker in (
            "mmCapitalAuthority=MONEY_MANAGEMENT",
            "mmCapitalSource=PAPER_ACCOUNT",
            "mmEquity=100.0",
            "mmAvailableCapital=100.0",
            "mmRiskState=UNKNOWN",
            "mmAvailable=false",
            "mmMetricsStatus=UNAVAILABLE",
            "mmSafeReason=AUTHORITATIVE_EVALUATION_NOT_ESTABLISHED",
            "mmBlockReasons=TRADING_RUNTIME_METRICS_UNAVAILABLE",
            "mmExecutionEntryAllowed=false",
        ):
            self.assertIn(marker, content, marker)

    def test_exposure_risk_and_capacity_semantics_remain_distinct(self):
        mm = runtime_context(projection("UNKNOWN")).runtimeContext.moneyManagement
        self.assertEqual(mm.exposure, 99)
        self.assertEqual(mm.remainingExposure, 20)
        self.assertEqual(mm.riskBudget, 5)
        self.assertEqual(mm.positionCapacity, 1)
        self.assertEqual(mm.remainingPositionCapacity, 1)

    def test_paper_capital_authority_wins_over_real_account_reference(self):
        metrics = replace(
            real_stale_paper_metrics(),
            equity=999,
            available_capital=999,
            risk_budget_remaining=999,
        )
        value = replace(
            projection("UNKNOWN"),
            metrics=metrics,
            capital_eligibility=paper_capital(),
        )
        mm = runtime_context(value).runtimeContext.moneyManagement
        self.assertEqual(mm.capitalSource, "PAPER_ACCOUNT")
        self.assertEqual(mm.inputAuthority, "PAPER_ACCOUNT")
        self.assertEqual(mm.equity, 100)
        self.assertEqual(mm.availableCapital, 100)
        self.assertEqual(mm.riskBudget, 5)


class OverallMmSemanticValidationTest(unittest.TestCase):
    def test_unknown_with_available_capital_rejects_false_current_normal(self):
        envelope = runtime_context(
            projection("UNKNOWN", available=False, metrics_status="UNAVAILABLE")
        )
        result = validate_claim(envelope, "The current MM state is NORMAL.")
        self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
        self.assertIn(
            AdvisorForbiddenClaim.UNGROUNDED_CURRENT_RUNTIME_CLAIM,
            result.forbiddenClaims,
        )
        self.assertFalse(result.facts)

    def test_unknown_with_full_remaining_exposure_stays_unknown(self):
        envelope = runtime_context(projection("UNKNOWN"))
        self.assertEqual(
            envelope.runtimeContext.moneyManagement.remainingExposure, 20
        )
        result = validate_claim(envelope, "The current MM state is UNKNOWN.")
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)

    def test_static_normal_definition_cannot_override_runtime_unknown(self):
        envelope = runtime_context(projection("UNKNOWN"))
        result = validate_claim(
            envelope,
            "Static Knowledge defines NORMAL; the current MM state is NORMAL.",
        )
        self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)

    def test_authoritative_normal_allows_current_normal(self):
        result = validate_claim(
            runtime_context(projection("NORMAL")),
            "The current MM state is NORMAL.",
        )
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)
        self.assertEqual(result.facts[0].statement, "The current MM state is NORMAL.")

    def test_authoritative_caution_is_preserved(self):
        envelope = runtime_context(projection("CAUTION"))
        self.assertEqual(envelope.runtimeContext.moneyManagement.riskState, "CAUTION")
        result = validate_claim(envelope, "The current MM state is CAUTION.")
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)

    def test_authoritative_protection_is_preserved_not_normalized(self):
        envelope = runtime_context(projection("CAPITAL_PROTECTION_STANDARD"))
        self.assertEqual(
            envelope.runtimeContext.moneyManagement.riskState,
            "CAPITAL_PROTECTION_STANDARD",
        )
        result = validate_claim(
            envelope,
            "The current MM state is CAPITAL_PROTECTION_STANDARD.",
        )
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)
        self.assertNotIn("NORMAL", result.facts[0].statement)


if __name__ == "__main__":
    unittest.main()
