"""Focused tests: authoritative runtime-context injection into the browser Advisor.

Verifies that the existing authoritative TradingAI runtime snapshot is carried
into the browser conversation context (STOPPED PAPER, MM numeric facts, unknown
preservation, MM/Market authority isolation, freshness and traceability).
"""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.ai_advisor.context_builder import build_advisor_context
from backend.ai_advisor.conversation_models import (
    AdvisorCapability,
    AdvisorContextEnvelope,
    AdvisorConversationMessage,
    AdvisorDataAccessScope,
    AdvisorPermissionContext,
    AdvisorRequest,
    AdvisorRole,
    AdvisorSourceType,
    AuthenticationState,
    AuthorizationState,
)
from backend.ai_advisor.prompt_builder import build_advisor_prompt
from backend.ai_advisor.prompt_models import (
    AdvisorPromptPolicy,
    AdvisorPromptSectionType,
)
from backend.ai_advisor.runtime_reader import RuntimeScalarSnapshot
from backend.ai_advisor.service import build_runtime_response

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()


def stopped_paper_snapshot(**overrides):
    values = {
        "state": "STOPPED",
        "mode": "PAPER",
        "exchange": "kucoin",
        "symbol": "BTCUSDT",
        "loop_enabled": False,
        "loop_state": "STOPPED",
        "auto_trade_enabled": False,
        "emergency_locked": False,
        "emergency_state": "READY",
        "dry_run": True,
        "real_order_allowed": False,
        "source_updated_at": NOW_EPOCH - 1,
        "warnings": (),
        "selection_mode": None,
        "market_ready": False,
        "market_stale": True,
        "live_order_entry_state": "BLOCKED",
        "mm_state": "NORMAL",
        "mm_risk_state": "NORMAL",
        "mm_recommended_action": "CONTINUE",
        "mm_execution_entry_state": "BLOCKED",
        "final_execution_entry_state": "BLOCKED",
        "health_state": "STOPPED",
        "position_state": "FLAT",
        "pending_order_state": "NONE",
        "mm_regime": "CAPITAL_PROTECTION_STANDARD",
        "mm_equity": 7.918,
        "mm_available_capital": 7.918,
        "mm_exposure": 0.0,
        "mm_remaining_exposure": 1.583,
        "mm_position_capacity": 1,
        "mm_remaining_position_capacity": 1,
        "mm_risk_budget": 7.50,
        "mm_drawdown_percent": None,
        "mm_ruin_guard_status": "SIMULATION_MODE",
        "mm_compounding_enabled": False,
        "mm_authority_fresh": True,
        "mm_captured_at": NOW_EPOCH - 1,
    }
    values.update(overrides)
    return RuntimeScalarSnapshot(**values)


def mm_runtime(overrides=None, **kwargs):
    snapshot = stopped_paper_snapshot(
        **kwargs,
    )
    if overrides:
        snapshot = stopped_paper_snapshot(**overrides)
    response = build_runtime_response(
        reader=lambda: snapshot,
        clock=lambda: NOW_EPOCH,
    )
    return build_advisor_context(
        generated_at=NOW,
        permission_context=permission(),
        runtime=response,
        current_message=current_message(
            "Evaluate the current money management posture."
        ),
    )


def permission(**overrides):
    values = dict(
        principalId="principal-1",
        authenticationState=AuthenticationState.AUTHENTICATED,
        authorizationState=AuthorizationState.AUTHORIZED,
        role="USER",
        permissionLevel="READ_ONLY",
        allowedCapabilities=[
            AdvisorCapability.RUNTIME_STATUS_EXPLAIN,
            AdvisorCapability.SPECIFICATION_EXPLAIN,
        ],
        dataAccessScope=[
            AdvisorDataAccessScope.SANITIZED_RUNTIME_SUMMARY,
            AdvisorDataAccessScope.APPROVED_LOCAL_SPECIFICATIONS,
        ],
        policyVersion="1.1",
        trustedServerContext=True,
    )
    values.update(overrides)
    return AdvisorPermissionContext(**values)


def current_message(content="Explain the current state."):
    return AdvisorConversationMessage(
        messageId="message-1",
        role=AdvisorRole.USER,
        content=content,
        createdAt=NOW,
        sourceReferences=(),
    )


def render_runtime_prompt(context: AdvisorContextEnvelope) -> str:
    prompt = build_advisor_prompt(
        request=AdvisorRequest(
            schemaVersion="1.0",
            requestId="request-1",
            messageId="message-1",
            message="Explain the current state.",
            locale="en-US",
            requestedAt=NOW,
            permissionContext=permission(),
            contextEnvelope=context,
            responsePreferences=None,
        ),
        context=context,
        policy=AdvisorPromptPolicy(),
    )
    runtime_section = next(
        item
        for item in prompt.contextSections
        if item.sectionType is AdvisorPromptSectionType.RUNTIME_CONTEXT
    )
    return runtime_section.content


class StoppedPaperSnapshotTest(unittest.TestCase):
    def test_context_carries_authoritative_stopped_paper_facts(self):
        context = mm_runtime()
        runtime_context = context.runtimeContext
        self.assertIsNotNone(runtime_context)
        self.assertEqual(runtime_context.state, "STOPPED")
        self.assertEqual(runtime_context.mode, "PAPER")
        self.assertTrue(runtime_context.dryRun)
        self.assertFalse(runtime_context.realOrderAllowed)
        self.assertFalse(runtime_context.loopEnabled)
        self.assertEqual(runtime_context.loopState, "STOPPED")
        self.assertEqual(runtime_context.positionState, "FLAT")
        self.assertEqual(runtime_context.pendingOrderState, "NONE")

    def test_prompt_renders_stopped_paper_facts(self):
        content = render_runtime_prompt(mm_runtime())
        for marker in (
            "botState=STOPPED",
            "mode=PAPER",
            "dryRun=true",
            "realOrderAllowed=false",
            "positionState=FLAT",
            "pendingOrderState=NONE",
        ):
            self.assertIn(marker, content, marker)


class MmRuntimeSnapshotTest(unittest.TestCase):
    def test_context_carries_authoritative_mm_facts(self):
        context = mm_runtime()
        mm = context.runtimeContext.moneyManagement
        self.assertIsNotNone(mm)
        self.assertEqual(mm.mmRegime, "CAPITAL_PROTECTION_STANDARD")
        self.assertEqual(mm.equity, 7.918)
        self.assertEqual(mm.availableCapital, 7.918)
        self.assertEqual(mm.exposure, 0.0)
        self.assertEqual(mm.remainingExposure, 1.583)
        self.assertEqual(mm.positionCapacity, 1)
        self.assertEqual(mm.remainingPositionCapacity, 1)
        self.assertEqual(mm.riskBudget, 7.50)
        self.assertFalse(mm.compoundingEnabled)
        self.assertTrue(mm.authorityFresh)

    def test_prompt_renders_authoritative_mm_facts(self):
        content = render_runtime_prompt(mm_runtime())
        for marker in (
            "mmRegime=CAPITAL_PROTECTION_STANDARD",
            "mmEquity=7.918",
            "mmExposure=0.0",
            "mmRemainingExposure=1.583",
            "mmPositionCapacity=1",
            "mmRemainingPositionCapacity=1",
            "mmRiskBudget=7.5",
        ):
            self.assertIn(marker, content, marker)


class UnknownPreservationTest(unittest.TestCase):
    def test_unknown_mm_values_remain_unknown_not_fabricated(self):
        context = mm_runtime(
            overrides=dict(
                mm_regime=None,
                mm_equity=None,
                mm_risk_budget=None,
                mm_available_capital=None,
                mm_exposure=None,
                mm_remaining_exposure=None,
                mm_position_capacity=None,
                mm_remaining_position_capacity=None,
                mm_authority_fresh=None,
            )
        )
        mm = context.runtimeContext.moneyManagement
        self.assertIsNone(mm.mmRegime)
        self.assertIsNone(mm.equity)
        self.assertIsNone(mm.riskBudget)
        self.assertIsNone(mm.availableCapital)
        self.assertIsNone(mm.exposure)
        self.assertIsNone(mm.remainingExposure)
        self.assertIsNone(mm.positionCapacity)
        self.assertIsNone(mm.remainingPositionCapacity)
        self.assertIsNone(mm.authorityFresh)
        # NORMAL must never be fabricated just because other values are absent.
        self.assertNotIn("mmRegime=NORMAL", render_runtime_prompt(context))

    def test_unknown_position_and_pending_order_stay_unknown(self):
        context = mm_runtime(
            overrides=dict(position_state="UNKNOWN", pending_order_state="UNKNOWN")
        )
        self.assertEqual(context.runtimeContext.positionState, "UNKNOWN")
        self.assertEqual(context.runtimeContext.pendingOrderState, "UNKNOWN")


class MmMarketIsolationTest(unittest.TestCase):
    def test_mm_normal_does_not_imply_market_normal(self):
        context = mm_runtime(
            overrides=dict(
                mm_state="NORMAL",
                mm_risk_state="NORMAL",
                mm_execution_entry_state="ALLOWED",
                mm_authority_fresh=True,
                mm_regime="CAPITAL_PROTECTION_STANDARD",
                mm_equity=100.0,
                mm_exposure=0.0,
                mm_remaining_exposure=50.0,
                mm_remaining_position_capacity=1,
                market_ready=False,
                market_stale=True,
                selection_mode=None,
            )
        )
        market = context.runtimeContext.market
        self.assertIsNotNone(market)
        # MM is healthy/NORMAL but Market authority is separately stale/unready.
        self.assertFalse(market.marketReady)
        self.assertTrue(market.marketStale)
        # The prompt must keep MM and Market facts distinct.
        content = render_runtime_prompt(context)
        self.assertIn("marketReady=false", content)
        self.assertIn("marketStale=true", content)
        self.assertNotIn("marketReady=true", content)


class FreshnessTraceabilityTest(unittest.TestCase):
    def test_runtime_source_has_identity_and_freshness(self):
        context = mm_runtime()
        source = next(
            item for item in context.sources if item.sourceType is AdvisorSourceType.RUNTIME
        )
        self.assertEqual(source.authority.value, "RUNTIME_AUTHORITATIVE")
        self.assertIsNotNone(source.freshness.capturedAt)
        self.assertIn(source.freshness.state.value, {"FRESH", "STALE", "UNKNOWN"})
        self.assertEqual(context.runtimeContext.sourceId, source.sourceId)

    def test_runtime_freshness_not_never_applicable(self):
        context = mm_runtime()
        source = next(
            item for item in context.sources if item.sourceType is AdvisorSourceType.RUNTIME
        )
        self.assertNotEqual(source.freshness.state.value, "NOT_APPLICABLE")
        self.assertIn(source.freshness.state.value, {"FRESH", "STALE", "UNKNOWN"})


class ReadOnlyAssemblyTest(unittest.TestCase):
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_reader_only_reads_no_mutation_methods(self, existing):
        manager = SimpleNamespace(
            _running=False,
            lifecycle_state="STOPPED",
            config={"mode": "paper", "dry_run": True},
            exchange_name="kucoin",
            symbol="BTCUSDT",
            selection_mode=None,
            market_ready=False,
            last_update_time=None,
            exchange_client_ready=False,
            exchange_auth_ready=False,
            balance_check_ok=False,
            position_check_ok=False,
            pending_order=False,
            state=SimpleNamespace(
                runtime_metrics={"last_bot_update": NOW_EPOCH - 1},
                position_state="FLAT",
            ),
            get_result=Mock(side_effect=AssertionError("must not call get_result")),
            get_status=Mock(side_effect=AssertionError("must not call get_status")),
            _get_real_account_snapshot=Mock(
                side_effect=AssertionError("must not refresh account")
            ),
            set_config=Mock(side_effect=AssertionError("must not mutate config")),
            start=Mock(side_effect=AssertionError("must not start")),
            stop=Mock(side_effect=AssertionError("must not stop")),
        )
        existing.return_value = manager
        from backend.ai_advisor.runtime_reader import read_runtime_scalars

        snapshot = read_runtime_scalars(mm_boundary_provider=lambda: None)
        self.assertEqual(snapshot.position_state, "FLAT")
        self.assertEqual(snapshot.pending_order_state, "NONE")
        manager.get_result.assert_not_called()
        manager.get_status.assert_not_called()
        manager._get_real_account_snapshot.assert_not_called()
        manager.set_config.assert_not_called()
        manager.start.assert_not_called()
        manager.stop.assert_not_called()


class SpecificationGroundingTest(unittest.TestCase):
    def test_specification_grounding_remains_valid(self):
        context = build_advisor_context(
            generated_at=NOW,
            permission_context=permission(),
            specifications=(
                SimpleNamespace(
                    sourceId="spec-a",
                    sourceVersion="1.0",
                    title="Canonical Specification A",
                    documentPath="docs/ai_advisor/a.md",
                    loadedAt=NOW,
                    contentHash="sha256:" + "a" * 64,
                    approved=True,
                    authorityLevel="FEATURE_SPEC",
                    topics=("entryPermission",),
                    excerpt=(
                        "MM NORMAL does not imply Market NORMAL; Market state "
                        "requires separate Market authority."
                    ),
                ),
            ),
            current_message=current_message(
                "Explain MM and Market authority separation."
            ),
        )
        prompt = build_advisor_prompt(
            request=AdvisorRequest(
                schemaVersion="1.0",
                requestId="request-1",
                messageId="message-1",
                message="Explain MM and Market authority separation.",
                locale="en-US",
                requestedAt=NOW,
                permissionContext=permission(),
                contextEnvelope=context,
                responsePreferences=None,
            ),
            context=context,
            policy=AdvisorPromptPolicy(),
        )
        spec_section = next(
            item
            for item in prompt.contextSections
            if item.sectionType is AdvisorPromptSectionType.SPECIFICATION_REFERENCE
        )
        self.assertIn("Canonical Specification A", spec_section.content)
        self.assertIn(
            "Market authority", spec_section.content
        )


if __name__ == "__main__":
    unittest.main()
