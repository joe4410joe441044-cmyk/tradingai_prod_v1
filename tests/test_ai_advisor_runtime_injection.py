"""Focused tests: current-main-native authoritative runtime-context injection.

Verifies that the authoritative TradingAI runtime facts are carried into the
browser Advisor conversation context under the CURRENT main architecture:

- STOPPED PAPER grounding (Test A)
- MM runtime numeric grounding (Test B)
- exposure semantic separation (Test C)
- unknown preservation (Test D)
- MM / Market authority isolation (Test E)
- freshness / traceability (Test F)
- read-only assembly (Test G)
- specification grounding remains valid (Test H)
"""

import unittest
from datetime import datetime, timezone
from decimal import Decimal
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
from backend.ai_advisor.runtime_reader import (
    RuntimeScalarSnapshot,
    read_runtime_scalars,
)
from backend.ai_advisor.service import build_runtime_response
from backend.money_management.capital_eligibility import CapitalEligibilityContract
from backend.money_management.loss_http_api import (
    MoneyManagementConfigurationResponse,
    MoneyManagementMetricsResponse,
    MoneyManagementStatusResponse,
)

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
        "position_state": "FLAT",
        "pending_order_state": "NONE",
        "market_ready": False,
        "market_symbol": "BTCUSDT",
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
            AdvisorCapability.SYSTEM_GUIDANCE,
        ],
        dataAccessScope=[
            AdvisorDataAccessScope.SANITIZED_RUNTIME_SUMMARY,
            AdvisorDataAccessScope.APPROVED_LOCAL_SPECIFICATIONS,
            AdvisorDataAccessScope.PUBLIC_UI_NAVIGATION,
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


def context(runtime_response, **overrides):
    return build_advisor_context(
        generated_at=NOW,
        permission_context=permission(),
        runtime=runtime_response,
        current_message=current_message(
            overrides.pop("message", "Explain the current state.")
        ),
        **overrides,
    )


def response_from_snapshot(snapshot):
    return build_runtime_response(
        reader=lambda: snapshot,
        clock=lambda: NOW_EPOCH,
    )


def render_runtime_prompt(envelope: AdvisorContextEnvelope) -> str:
    prompt = build_advisor_prompt(
        request=AdvisorRequest(
            schemaVersion="1.0",
            requestId="request-1",
            messageId="message-1",
            message="Explain the current state.",
            locale="en-US",
            requestedAt=NOW,
            permissionContext=permission(),
            contextEnvelope=envelope,
            responsePreferences=None,
        ),
        context=envelope,
        policy=AdvisorPromptPolicy(),
    )
    runtime_section = next(
        item
        for item in prompt.contextSections
        if item.sectionType is AdvisorPromptSectionType.RUNTIME_CONTEXT
    )
    return runtime_section.content


class StoppedPaperGroundingTest(unittest.TestCase):
    def test_context_carries_authoritative_stopped_paper_facts(self):
        runtime_context = context(response_from_snapshot(stopped_paper_snapshot())).runtimeContext
        self.assertIsNotNone(runtime_context)
        self.assertEqual(runtime_context.state, "STOPPED")
        self.assertEqual(runtime_context.mode, "PAPER")
        self.assertTrue(runtime_context.dryRun)
        self.assertFalse(runtime_context.realOrderAllowed)
        self.assertFalse(runtime_context.loopEnabled)
        self.assertEqual(runtime_context.loopState, "STOPPED")
        self.assertFalse(runtime_context.autoTradeEnabled)
        self.assertEqual(runtime_context.positionState, "FLAT")
        self.assertEqual(runtime_context.pendingOrderState, "NONE")

    def test_prompt_renders_stopped_paper_facts(self):
        envelope = context(response_from_snapshot(stopped_paper_snapshot()))
        content = render_runtime_prompt(envelope)
        for marker in (
            "botState=STOPPED",
            "mode=PAPER",
            "dryRun=true",
            "realOrderAllowed=false",
            "positionState=FLAT",
            "pendingOrderState=NONE",
        ):
            self.assertIn(marker, content, marker)


class MmRuntimeGroundingTest(unittest.TestCase):
    def test_context_carries_distinct_authoritative_mm_facts(self):
        runtime_context = context(
            response_from_snapshot(stopped_paper_snapshot())
        ).runtimeContext
        mm = runtime_context.moneyManagement
        self.assertIsNotNone(mm)
        self.assertEqual(mm.regime, "CAPITAL_PROTECTION_STANDARD")
        self.assertEqual(mm.equity, 7.918)
        self.assertEqual(mm.availableCapital, 7.918)
        self.assertEqual(mm.exposure, 0.0)
        self.assertEqual(mm.remainingExposure, 1.583)
        self.assertEqual(mm.positionCapacity, 1)
        self.assertEqual(mm.remainingPositionCapacity, 1)
        self.assertEqual(mm.riskBudget, 7.50)
        self.assertFalse(mm.compoundingEnabled)
        self.assertTrue(mm.authorityFresh)
        self.assertIsNone(mm.drawdownPercent)

    def test_prompt_renders_distinct_mm_facts(self):
        envelope = context(response_from_snapshot(stopped_paper_snapshot()))
        content = render_runtime_prompt(envelope)
        for marker in (
            "mmRegime=CAPITAL_PROTECTION_STANDARD",
            "mmExposure=0.0",
            "mmRemainingExposure=1.583",
            "mmPositionCapacity=1",
            "mmRemainingPositionCapacity=1",
            "mmRiskBudget=7.5",
            "mmEquity=7.918",
            "mmAvailableCapital=7.918",
        ):
            self.assertIn(marker, content, marker)


class ExposureSemanticsTest(unittest.TestCase):
    def test_exposure_remaining_exposure_and_risk_budget_are_distinct_fields(self):
        mm = context(
            response_from_snapshot(stopped_paper_snapshot())
        ).runtimeContext.moneyManagement
        self.assertEqual(mm.exposure, 0.0)
        self.assertEqual(mm.remainingExposure, 1.583)
        self.assertEqual(mm.riskBudget, 7.50)
        self.assertNotEqual(mm.exposure, mm.remainingExposure)
        self.assertNotEqual(mm.remainingExposure, mm.riskBudget)
        self.assertNotEqual(mm.exposure, mm.riskBudget)
        # Prompt preserves every distinct semantic, never collapsed into "risk".
        content = render_runtime_prompt(
            context(response_from_snapshot(stopped_paper_snapshot()))
        )
        self.assertIn("mmExposure=", content)
        self.assertIn("mmRemainingExposure=", content)
        self.assertIn("mmRiskBudget=", content)


class UnknownPreservationTest(unittest.TestCase):
    def test_missing_mm_values_remain_unknown_not_fabricated(self):
        snapshot = stopped_paper_snapshot(
            mm_regime=None,
            mm_equity=None,
            mm_available_capital=None,
            mm_exposure=None,
            mm_remaining_exposure=None,
            mm_position_capacity=None,
            mm_remaining_position_capacity=None,
            mm_risk_budget=None,
            mm_authority_fresh=None,
        )
        mm = context(response_from_snapshot(snapshot)).runtimeContext.moneyManagement
        self.assertIsNone(mm.regime)
        self.assertIsNone(mm.equity)
        self.assertIsNone(mm.riskBudget)
        self.assertIsNone(mm.availableCapital)
        self.assertIsNone(mm.exposure)
        self.assertIsNone(mm.remainingExposure)
        self.assertIsNone(mm.positionCapacity)
        self.assertIsNone(mm.remainingPositionCapacity)
        self.assertIsNone(mm.authorityFresh)
        content = render_runtime_prompt(context(response_from_snapshot(snapshot)))
        self.assertNotIn("mmRegime=NORMAL", content)

    def test_unknown_position_and_pending_order_stay_unknown(self):
        snapshot = stopped_paper_snapshot(
            position_state="UNKNOWN", pending_order_state="UNKNOWN"
        )
        runtime_context = context(response_from_snapshot(snapshot)).runtimeContext
        self.assertEqual(runtime_context.positionState, "UNKNOWN")
        self.assertEqual(runtime_context.pendingOrderState, "UNKNOWN")


class MmMarketIsolationTest(unittest.TestCase):
    def test_mm_normal_does_not_imply_market_normal(self):
        snapshot = stopped_paper_snapshot(
            mm_regime="CAPITAL_PROTECTION_STANDARD",
            mm_equity=100.0,
            mm_exposure=0.0,
            mm_remaining_exposure=50.0,
            mm_remaining_position_capacity=1,
            mm_authority_fresh=True,
            market_ready=False,
        )
        runtime_context = context(response_from_snapshot(snapshot)).runtimeContext
        market = runtime_context.market
        self.assertIsNotNone(market)
        self.assertFalse(market.ready)
        # MM is healthy but Market authority is separately unready.
        content = render_runtime_prompt(context(response_from_snapshot(snapshot)))
        self.assertIn("marketReady=false", content)
        self.assertNotIn("marketReady=true", content)


class FreshnessTraceabilityTest(unittest.TestCase):
    def test_runtime_source_has_identity_and_freshness(self):
        envelope = context(response_from_snapshot(stopped_paper_snapshot()))
        source = next(
            item
            for item in envelope.sources
            if item.sourceType is AdvisorSourceType.RUNTIME
        )
        self.assertEqual(source.authority.value, "RUNTIME_AUTHORITATIVE")
        self.assertIsNotNone(source.freshness.capturedAt)
        self.assertIn(source.freshness.state.value, {"FRESH", "STALE", "UNKNOWN"})
        self.assertEqual(envelope.runtimeContext.sourceId, source.sourceId)

    def test_runtime_freshness_not_not_applicable(self):
        envelope = context(response_from_snapshot(stopped_paper_snapshot()))
        source = next(
            item
            for item in envelope.sources
            if item.sourceType is AdvisorSourceType.RUNTIME
        )
        self.assertNotEqual(source.freshness.state.value, "NOT_APPLICABLE")


class ReadOnlyAssemblyTest(unittest.TestCase):
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_reader_only_reads_no_mutation_methods(self, existing):
        manager = SimpleNamespace(
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

        snapshot = read_runtime_scalars(mm_boundary_provider=lambda: None)
        self.assertEqual(snapshot.position_state, "FLAT")
        self.assertEqual(snapshot.pending_order_state, "NONE")
        manager.get_result.assert_not_called()
        manager.get_status.assert_not_called()
        manager._get_real_account_snapshot.assert_not_called()
        manager.set_config.assert_not_called()
        manager.start.assert_not_called()
        manager.stop.assert_not_called()


def real_config_response():
    return MoneyManagementConfigurationResponse(
        available=True,
        enabled=True,
        daily_warning_percent=Decimal("0"),
        daily_block_percent=Decimal("0"),
        weekly_warning_percent=Decimal("0"),
        weekly_block_percent=Decimal("0"),
        monthly_warning_percent=Decimal("0"),
        monthly_block_percent=Decimal("0"),
        maximum_drawdown_percent=Decimal("0"),
        total_exposure_percent=Decimal("20"),
        risk_per_trade_percent=Decimal("1"),
        maximum_position_notional=Decimal("1.583673932"),
        single_symbol_exposure_percent=Decimal("20"),
        maximum_leverage=Decimal("1"),
        compounding_enabled=False,
        revision=1,
        source="test",
        updated_at=NOW,
    )


def real_authoritative_capital():
    """Authoritative current-main ``CapitalEligibilityContract`` (Production-like)."""
    return CapitalEligibilityContract(
        capital_authority="MONEY_MANAGEMENT",
        equity=Decimal("7.91836966"),
        available_capital=Decimal("7.91836966"),
        mm_mode="MANUAL",
        mm_regime="CAPITAL_PROTECTION_STANDARD",
        risk_budget=Decimal("5.00"),
        max_position_notional=Decimal("1.583673932"),
        total_exposure_percent=Decimal("20"),
        max_total_exposure=Decimal("1.583673932"),
        remaining_exposure=Decimal("1.583673932"),
        theoretical_max_concurrent_positions=1,
        executable_max_concurrent_positions=1,
        remaining_position_capacity=1,
        ruin_guard_status="UNAVAILABLE",
        compounding_enabled=False,
        policy_version="v1",
        evaluated_at=NOW,
        authority_fresh=True,
        execution_entry_allowed=True,
        capital_source="REAL_LIVE_ACCOUNT",
        input_authority="REAL_LIVE_ACCOUNT",
    )


def real_stale_paper_metrics():
    """Stale fallback metrics that must NEVER override authoritative capital."""
    return MoneyManagementMetricsResponse(
        status="AVAILABLE",
        equity=Decimal("100.0"),
        available_capital=Decimal("100.0"),
        peak_equity=None,
        drawdown_amount=None,
        drawdown_percent=None,
        daily_pnl=None,
        weekly_pnl=None,
        monthly_pnl=None,
        daily_trade_count=None,
        weekly_trade_count=None,
        monthly_trade_count=None,
        open_exposure=Decimal("99.0"),
        exposure_limit=None,
        total_exposure_percent=None,
        max_total_exposure_amount=None,
        remaining_exposure_amount=None,
        exposure_utilization=None,
        open_position_state="UNKNOWN",
        risk_utilization=None,
        risk_limit_amount=None,
        current_risk_amount=None,
        reserved_risk_amount=None,
        risk_budget_remaining=Decimal("0.5"),
        recommended_position_notional=None,
        recommended_position_quantity=None,
        generated_at=NOW,
    )


def real_mm_projection(*, capital=None, metrics=None):
    """Construct a REAL ``MoneyManagementStatusResponse`` (no ``.capital``)."""
    return MoneyManagementStatusResponse(
        available=True,
        enabled=True,
        lifecycle_state="STOPPED",
        risk_state="CAPITAL_PROTECTION_STANDARD",
        recommended_action="HOLD",
        execution_entry_allowed=False,
        warning_reasons=(),
        hold_reasons=(),
        block_reasons=(),
        diagnostic_reasons=(),
        metrics_status="AVAILABLE",
        projection_status="AVAILABLE",
        recovery_required=False,
        safe_reason=None,
        generated_at=NOW,
        revision=1,
        sequence=1,
        configuration_revision=1,
        metrics=metrics or real_stale_paper_metrics(),
        configuration=real_config_response(),
        capital_eligibility=capital or real_authoritative_capital(),
        cash_flow_authority=None,
    )


def real_mm_boundary(*, capital=None, metrics=None):
    """A boundary whose ``get_status`` yields the real projection shape."""
    projection = real_mm_projection(capital=capital, metrics=metrics)
    return SimpleNamespace(get_status=lambda: projection)


class MmSourceProjectionTest(unittest.TestCase):
    def test_reads_mm_facts_from_existing_projection_without_recalculating(self):
        capital = real_authoritative_capital()
        metrics = real_stale_paper_metrics()
        boundary = SimpleNamespace(
            get_status=lambda: real_mm_projection(capital=capital, metrics=metrics)
        )
        manager = SimpleNamespace(
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
        with patch(
            "backend.ai_advisor.runtime_reader.get_existing_bot_manager",
            return_value=manager,
        ):
            snapshot = read_runtime_scalars(mm_boundary_provider=lambda: boundary)

        self.assertEqual(snapshot.mm_regime, "CAPITAL_PROTECTION_STANDARD")
        self.assertEqual(snapshot.mm_equity, 7.91836966)
        self.assertEqual(snapshot.mm_available_capital, 7.91836966)
        self.assertEqual(snapshot.mm_exposure, 99.0)
        self.assertEqual(snapshot.mm_remaining_exposure, 1.583673932)
        self.assertEqual(snapshot.mm_position_capacity, 1)
        self.assertEqual(snapshot.mm_remaining_position_capacity, 1)
        self.assertEqual(snapshot.mm_risk_budget, 5.0)
        self.assertEqual(snapshot.mm_ruin_guard_status, "UNAVAILABLE")
        self.assertIs(snapshot.mm_compounding_enabled, False)
        self.assertIs(snapshot.mm_authority_fresh, True)
        self.assertEqual(snapshot.market_ready, False)


class RealMmProjectionRegressionTest(unittest.TestCase):
    """Proves the Advisor reads the REAL current-main MM projection shape."""

    def test_real_projection_shape_has_no_capital_compatibility_attribute(self):
        projection = real_mm_projection()

        self.assertFalse(hasattr(projection, "capital"))
        self.assertTrue(hasattr(projection, "capital_eligibility"))
        self.assertIsInstance(projection.capital_eligibility, CapitalEligibilityContract)
        self.assertIsInstance(projection.metrics, MoneyManagementMetricsResponse)

    def test_authoritative_capital_values_win_over_stale_paper_metrics(self):
        boundary = real_mm_boundary(
            capital=real_authoritative_capital(),
            metrics=real_stale_paper_metrics(),
        )
        manager = SimpleNamespace(
            _running=True,
            lifecycle_state="RUNNING",
            config={"mode": "paper", "dry_run": True},
            exchange_name="kucoin",
            symbol="BTCUSDT",
            market_ready=True,
            active_symbol="FTMUSDT",
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
        with patch(
            "backend.ai_advisor.runtime_reader.get_existing_bot_manager",
            return_value=manager,
        ):
            snapshot = read_runtime_scalars(mm_boundary_provider=lambda: boundary)

        self.assertEqual(snapshot.mm_equity, 7.91836966)
        self.assertEqual(snapshot.mm_available_capital, 7.91836966)
        self.assertEqual(snapshot.mm_risk_budget, 5.0)
        self.assertEqual(snapshot.mm_remaining_exposure, 1.583673932)

        self.assertNotEqual(snapshot.mm_equity, 100.0)
        self.assertNotEqual(snapshot.mm_available_capital, 100.0)
        self.assertNotEqual(snapshot.mm_risk_budget, 0.5)

    def test_exposure_semantics_remain_distinct(self):
        with patch(
            "backend.ai_advisor.runtime_reader.get_existing_bot_manager",
            return_value=SimpleNamespace(
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
            ),
        ):
            snapshot = read_runtime_scalars(
                mm_boundary_provider=lambda: real_mm_boundary()
            )

        self.assertNotEqual(snapshot.mm_exposure, snapshot.mm_remaining_exposure)
        self.assertEqual(snapshot.mm_exposure, 99.0)
        self.assertEqual(snapshot.mm_remaining_exposure, 1.583673932)

    def test_mm_authority_does_not_contaminate_market_and_unknown_fails_closed(self):
        manager = SimpleNamespace(
            _running=False,
            lifecycle_state="STOPPED",
            config={"mode": "paper", "dry_run": True},
            exchange_name="kucoin",
            symbol="BTCUSDT",
            market_ready=True,
            active_symbol="FTMUSDT",
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
        with patch(
            "backend.ai_advisor.runtime_reader.get_existing_bot_manager",
            return_value=manager,
        ):
            snapshot = read_runtime_scalars(
                mm_boundary_provider=lambda: real_mm_boundary()
            )

        self.assertEqual(snapshot.mm_regime, "CAPITAL_PROTECTION_STANDARD")
        self.assertNotEqual(snapshot.mm_regime, "NORMAL")
        self.assertEqual(snapshot.market_ready, True)
        self.assertEqual(snapshot.market_symbol, "FTMUSDT")
        self.assertIsNone(snapshot.mm_drawdown_percent)


class SpecificationGroundingTest(unittest.TestCase):
    def test_specification_grounding_remains_valid(self):
        envelope = build_advisor_context(
            generated_at=NOW,
            permission_context=permission(),
            runtime=response_from_snapshot(stopped_paper_snapshot()),
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
                contextEnvelope=envelope,
                responsePreferences=None,
            ),
            context=envelope,
            policy=AdvisorPromptPolicy(),
        )
        spec_section = next(
            item
            for item in prompt.contextSections
            if item.sectionType is AdvisorPromptSectionType.SPECIFICATION_REFERENCE
        )
        self.assertIn("Canonical Specification A", spec_section.content)
        self.assertIn("Market authority", spec_section.content)


if __name__ == "__main__":
    unittest.main()
