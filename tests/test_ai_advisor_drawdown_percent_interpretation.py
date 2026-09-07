"""Regression matrix: authoritative MM drawdownPercent is ALREADY PERCENT.

The authoritative Money Management chain derives drawdown as
``drawdown_amount / peak_equity * 100``, so ``drawdownPercent`` is a percent
number in the 0..100 range: 0.282405 means 0.282405%, never 28.2405%.

The Advisor must consume that scalar verbatim (no recalculating) and must not
reinterpret it as a fraction (no 100x amplification). An advisor response that
claims ~28.24% for an authoritative 0.282405% is a 100x semantic error and must
fail closed.
"""

import json
import unittest
from dataclasses import replace
from decimal import Decimal
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

DRAWDOWN_VALUES = (0, 0.282405, 1, 10, 100)


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


def mm_context(
    drawdown,
    *,
    risk_state=None,
    available=None,
    metrics_status=None,
    capital=None,
):
    metrics = replace(
        real_stale_paper_metrics(),
        drawdown_percent=Decimal(str(drawdown)),
    )
    projection = real_mm_projection(
        metrics=metrics,
        capital=capital or real_authoritative_capital(),
    )
    if risk_state is not None:
        projection = replace(
            projection,
            risk_state=risk_state,
            available=available if available is not None else True,
            metrics_status=metrics_status or "AVAILABLE",
            safe_reason=None,
            block_reasons=(),
        )
        if risk_state == "UNKNOWN":
            projection = replace(
                projection,
                available=False,
                metrics_status="UNAVAILABLE",
                safe_reason="AUTHORITATIVE_EVALUATION_NOT_ESTABLISHED",
                block_reasons=("TRADING_RUNTIME_METRICS_UNAVAILABLE",),
                execution_entry_allowed=False,
            )
    boundary = SimpleNamespace(get_status=lambda: projection)
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
                "factId": "drawdown",
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


class DrawdownPercentAuthoritativeContractTest(unittest.TestCase):
    def test_context_preserves_authoritative_percent_scalar(self):
        for value in DRAWDOWN_VALUES:
            with self.subTest(value=value):
                mm = mm_context(value).runtimeContext.moneyManagement
                self.assertEqual(mm.drawdownPercent, float(value))

    def test_prompt_renders_explicit_percent_unit_not_100x(self):
        for value in DRAWDOWN_VALUES:
            with self.subTest(value=value):
                content = render_runtime_prompt(mm_context(value))
                percent_marker = f"mmDrawdownPercent={float(value)}%"
                self.assertIn(percent_marker, content, percent_marker)
                if value != 0:
                    self.assertNotIn(
                        f"mmDrawdownPercent={float(value) * 100}%",
                        content,
                    )

    def test_zero_drawdown_is_zero_percent(self):
        mm = mm_context(0).runtimeContext.moneyManagement
        self.assertEqual(mm.drawdownPercent, 0.0)
        result = validate_claim(
            mm_context(0),
            "The current drawdown is approximately 0%.",
        )
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)

    def test_fraction_interpretation_cannot_produce_28_24_for_0_282405(self):
        env = mm_context(0.282405)
        self.assertEqual(env.runtimeContext.moneyManagement.drawdownPercent, 0.282405)
        for statement in (
            "The current drawdown is approximately 28.2405%.",
            "The current drawdown is approximately 28.24%.",
        ):
            with self.subTest(statement=statement):
                result = validate_claim(env, statement)
                self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
                self.assertIn(
                    AdvisorForbiddenClaim.UNGROUNDED_CURRENT_RUNTIME_CLAIM,
                    result.forbiddenClaims,
                )
                self.assertFalse(result.facts)

    def test_correct_percent_interpretation_is_valid(self):
        env = mm_context(0.282405)
        result = validate_claim(
            env,
            "The current drawdown is approximately 0.282405%.",
        )
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)
        self.assertEqual(
            result.facts[0].statement,
            "The current drawdown is approximately 0.282405%.",
        )

    def test_one_percent_is_not_one_hundred_percent(self):
        env = mm_context(1)
        self.assertEqual(env.runtimeContext.moneyManagement.drawdownPercent, 1.0)
        wrong = validate_claim(env, "The current drawdown is approximately 100%.")
        self.assertEqual(wrong.status, AdvisorResponseStatus.REJECTED)
        self.assertFalse(wrong.facts)
        right = validate_claim(env, "The current drawdown is approximately 1%.")
        self.assertEqual(right.status, AdvisorResponseStatus.VALID)

    def test_ten_percent_claim_matches_authoritative_ten(self):
        env = mm_context(10)
        self.assertEqual(env.runtimeContext.moneyManagement.drawdownPercent, 10.0)
        right = validate_claim(env, "The current drawdown is approximately 10%.")
        self.assertEqual(right.status, AdvisorResponseStatus.VALID)

    def test_full_wipeout_hundred_percent_remains_allowed(self):
        env = mm_context(100)
        self.assertEqual(env.runtimeContext.moneyManagement.drawdownPercent, 100.0)
        result = validate_claim(env, "The current drawdown is approximately 100%.")
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)


class DrawdownPreservationRegressionTest(unittest.TestCase):
    def test_unknown_overall_state_remains_unknown_with_drawdown_present(self):
        env = mm_context(
            0.282405,
            risk_state="UNKNOWN",
            available=False,
            metrics_status="UNAVAILABLE",
        )
        mm = env.runtimeContext.moneyManagement
        self.assertEqual(mm.riskState, "UNKNOWN")
        self.assertFalse(mm.available)
        self.assertEqual(mm.metricsStatus, "UNAVAILABLE")
        self.assertEqual(mm.drawdownPercent, 0.282405)
        result = validate_claim(
            env,
            "The current MM state is UNKNOWN, with approximately 0.282405% drawdown.",
        )
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)

    def test_available_capital_does_not_promote_unknown_to_normal(self):
        env = mm_context(
            0.282405,
            risk_state="UNKNOWN",
            available=False,
            metrics_status="UNAVAILABLE",
        )
        result = validate_claim(env, "The current MM state is NORMAL.")
        self.assertEqual(result.status, AdvisorResponseStatus.REJECTED)
        self.assertIn(
            AdvisorForbiddenClaim.UNGROUNDED_CURRENT_RUNTIME_CLAIM,
            result.forbiddenClaims,
        )

    def test_explicit_authoritative_normal_remains_allowed(self):
        env = mm_context(0.282405, risk_state="NORMAL")
        result = validate_claim(env, "The current MM state is NORMAL.")
        self.assertEqual(result.status, AdvisorResponseStatus.VALID)

    def test_paper_account_capital_authority_preserved(self):
        capital = replace(
            real_authoritative_capital(),
            capital_source="PAPER_ACCOUNT",
            input_authority="PAPER_ACCOUNT",
            equity=100,
            available_capital=100,
        )
        mm = mm_context(0.282405, capital=capital).runtimeContext.moneyManagement
        self.assertEqual(mm.capitalSource, "PAPER_ACCOUNT")
        self.assertEqual(mm.inputAuthority, "PAPER_ACCOUNT")
        self.assertEqual(mm.equity, 100)
        self.assertEqual(mm.availableCapital, 100)
        self.assertEqual(mm.drawdownPercent, 0.282405)

    def test_exposure_semantics_remain_distinct(self):
        mm = mm_context(0.282405).runtimeContext.moneyManagement
        self.assertEqual(mm.exposure, 99.0)
        self.assertEqual(mm.remainingExposure, 1.583673932)
        self.assertEqual(mm.riskBudget, 5.0)
        self.assertNotEqual(mm.exposure, mm.remainingExposure)
        self.assertNotEqual(mm.remainingExposure, mm.riskBudget)
        self.assertNotEqual(mm.exposure, mm.riskBudget)

    def test_broad_runtime_grounding_preserved(self):
        content = render_runtime_prompt(mm_context(0.282405))
        for marker in (
            "botState=STOPPED",
            "mode=PAPER",
            "dryRun=true",
            "realOrderAllowed=false",
            "positionState=FLAT",
            "pendingOrderState=NONE",
        ):
            self.assertIn(marker, content, marker)

    def test_mm_market_isolation_preserved(self):
        envelope = mm_context(0.282405)
        content = render_runtime_prompt(envelope)
        self.assertIn("marketReady=false", content)
        self.assertNotIn("marketReady=true", content)


if __name__ == "__main__":
    unittest.main()
