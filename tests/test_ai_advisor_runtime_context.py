"""D-3 focused tests: read-only TradingAI runtime context for the AI Advisor."""

import unittest
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError

from backend.ai_advisor.browser_gateway import assemble_browser_service_input
from backend.ai_advisor.context_builder import (
    build_advisor_context,
    build_runtime_context,
)
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
from backend.ai_advisor.models import (
    AdvisorAuthorityStatus,
    AdvisorBotStatus,
    AdvisorExecutionEntryState,
    AdvisorHealthStatus,
    AdvisorMarketStatus,
    AdvisorMoneyManagementStatus,
    AdvisorOperationStatus,
    AdvisorRuntimeMetadata,
    AdvisorRuntimeResponse,
    AdvisorSafetyStatus,
    Freshness,
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
from backend.api.ai_advisor import apply_authoritative_runtime

NOW = datetime(2026, 7, 25, 12, tzinfo=timezone.utc)
NOW_EPOCH = NOW.timestamp()


class FakeBoundary:
    def __init__(self, **status_fields):
        self._status = status_fields

    def get_status(self):
        return SimpleNamespace(**self._status)


def mm_boundary(**overrides):
    values = dict(
        lifecycle_state="RUNNING",
        risk_state="NORMAL",
        recommended_action="CONTINUE",
        execution_entry_allowed=True,
    )
    values.update(overrides)
    return FakeBoundary(**values)


def manager(**overrides):
    runtime_metrics = overrides.pop(
        "runtime_metrics", {"last_bot_update": time.time() - 5}
    )
    values = dict(
        _running=True,
        lifecycle_state="RUNNING",
        config={
            "mode": "paper",
            "dry_run": True,
            "liveOrderEntryAllowed": False,
            "executionEntryAllowed": False,
        },
        exchange_name="kucoin",
        symbol="BTCUSDT",
        selection_mode="AUTO",
        market_ready=True,
        last_update_time=time.time() - 1,
        exchange_client_ready=True,
        exchange_auth_ready=True,
        balance_check_ok=True,
        position_check_ok=True,
        state=SimpleNamespace(runtime_metrics=runtime_metrics),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def runtime(**overrides):
    values = dict(
        bot=AdvisorBotStatus(
            state="RUNNING",
            mode="PAPER",
            exchange="kucoin",
            symbol="BTCUSDT",
        ),
        operation=AdvisorOperationStatus(
            loopEnabled=True,
            loopState="RUNNING",
            autoTradeEnabled=True,
        ),
        safety=AdvisorSafetyStatus(
            emergencyLocked=False,
            emergencyState="READY",
            dryRun=True,
            realOrderAllowed=False,
        ),
        market=AdvisorMarketStatus(
            selectionMode="AUTO",
            marketReady=True,
            marketStale=False,
        ),
        authority=AdvisorAuthorityStatus(
            liveOrderEntryState=AdvisorExecutionEntryState.BLOCKED,
            finalExecutionEntryState=AdvisorExecutionEntryState.ALLOWED,
            mmExecutionEntryState=AdvisorExecutionEntryState.ALLOWED,
        ),
        moneyManagement=AdvisorMoneyManagementStatus(
            state="RUNNING",
            riskState="NORMAL",
            recommendedAction="CONTINUE",
            executionEntryState=AdvisorExecutionEntryState.ALLOWED,
        ),
        health=AdvisorHealthStatus(healthState="HEALTHY"),
        runtime=AdvisorRuntimeMetadata(
            capturedAt=NOW.isoformat(),
            sourceUpdatedAt=(NOW - timedelta(seconds=1)).isoformat(),
            freshness=Freshness.FRESH,
        ),
        warnings=[],
    )
    values.update(overrides)
    return AdvisorRuntimeResponse(**values)


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


def current_message(content="Explain why entry is blocked."):
    return AdvisorConversationMessage(
        messageId="message-1",
        role=AdvisorRole.USER,
        content=content,
        createdAt=NOW,
        sourceReferences=(),
    )


class RuntimeReaderMappingTest(unittest.TestCase):
    @patch(
        "backend.ai_advisor.runtime_reader.governance_state",
        {
            "execution_enabled": True,
            "emergency_stop": False,
            "emergency_state": "READY",
        },
    )
    @patch(
        "backend.ai_advisor.runtime_reader.get_existing_bot_manager"
    )
    def test_full_paper_runtime_fields_map(self, existing):
        existing.return_value = manager()
        snapshot = read_runtime_scalars(
            mm_boundary_provider=lambda: mm_boundary()
        )

        self.assertEqual(snapshot.state, "RUNNING")
        self.assertEqual(snapshot.mode, "PAPER")
        self.assertTrue(snapshot.dry_run)
        self.assertTrue(snapshot.loop_enabled)
        self.assertEqual(snapshot.loop_state, "RUNNING")
        self.assertTrue(snapshot.auto_trade_enabled)
        self.assertFalse(snapshot.emergency_locked)
        self.assertEqual(snapshot.emergency_state, "READY")
        self.assertEqual(snapshot.selection_mode, "AUTO")
        self.assertTrue(snapshot.market_ready)
        self.assertFalse(snapshot.market_stale)
        self.assertEqual(snapshot.live_order_entry_state, "BLOCKED")
        self.assertEqual(snapshot.mm_state, "RUNNING")
        self.assertEqual(snapshot.mm_risk_state, "NORMAL")
        self.assertEqual(snapshot.mm_recommended_action, "CONTINUE")
        self.assertEqual(snapshot.mm_execution_entry_state, "ALLOWED")
        self.assertEqual(snapshot.final_execution_entry_state, "ALLOWED")
        self.assertEqual(snapshot.health_state, "HEALTHY")

    @patch(
        "backend.ai_advisor.runtime_reader.governance_state",
        {
            "execution_enabled": True,
            "emergency_stop": False,
            "emergency_state": "READY",
        },
    )
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_live_order_entry_state_armed(self, existing):
        existing.return_value = manager(
            config={
                "mode": "live",
                "dry_run": False,
                "liveOrderEntryAllowed": True,
                "executionEntryAllowed": True,
            }
        )
        snapshot = read_runtime_scalars(
            mm_boundary_provider=lambda: mm_boundary()
        )
        self.assertEqual(snapshot.live_order_entry_state, "ALLOWED")

    @patch(
        "backend.ai_advisor.runtime_reader.governance_state",
        {
            "execution_enabled": False,
            "emergency_stop": True,
            "emergency_state": "LOCKED",
        },
    )
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_final_entry_is_derived_from_authoritative_gates(self, existing):
        existing.return_value = manager(
            config={
                "mode": "paper",
                "dry_run": True,
                "liveOrderEntryAllowed": False,
            }
        )
        snapshot = read_runtime_scalars(
            mm_boundary_provider=lambda: mm_boundary()
        )
        self.assertTrue(snapshot.loop_enabled)
        self.assertFalse(snapshot.auto_trade_enabled)
        self.assertTrue(snapshot.emergency_locked)
        self.assertEqual(snapshot.final_execution_entry_state, "BLOCKED")

    @patch(
        "backend.ai_advisor.runtime_reader.governance_state",
        {
            "execution_enabled": True,
            "emergency_stop": False,
            "emergency_state": "READY",
        },
    )
    @patch(
        "backend.ai_advisor.runtime_reader.backend_config.ALLOW_LIVE",
        True,
    )
    @patch(
        "backend.ai_advisor.runtime_reader.backend_config.TRADE_MODE",
        "live",
    )
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_live_authority_gate_reads_real_order_allowed(self, existing):
        existing.return_value = manager(
            config={
                "mode": "live",
                "dry_run": False,
                "liveOrderEntryAllowed": True,
                "executionEntryAllowed": True,
            }
        )
        snapshot = read_runtime_scalars(
            mm_boundary_provider=lambda: mm_boundary()
        )
        self.assertEqual(snapshot.mode, "LIVE")
        self.assertFalse(snapshot.dry_run)
        self.assertTrue(snapshot.real_order_allowed)
        self.assertEqual(snapshot.live_order_entry_state, "ALLOWED")
        self.assertEqual(snapshot.final_execution_entry_state, "ALLOWED")


    def test_mm_and_final_entry_permissions_are_distinct(self):
        value = runtime()
        context, _, _ = build_runtime_context(
            value,
            source_id="advisor-runtime",
            generated_at=NOW,
        )
        self.assertIsNotNone(context.authority)
        self.assertIsNotNone(context.moneyManagement)
        self.assertEqual(
            context.authority.mmExecutionEntryState,
            context.moneyManagement.executionEntryState,
        )
        self.assertEqual(
            context.authority.finalExecutionEntryState,
            AdvisorExecutionEntryState.ALLOWED,
        )
        self.assertEqual(
            context.authority.mmExecutionEntryState,
            AdvisorExecutionEntryState.ALLOWED,
        )
        self.assertEqual(
            context.authority.liveOrderEntryState,
            AdvisorExecutionEntryState.BLOCKED,
        )
        self.assertNotEqual(
            context.authority.finalExecutionEntryState,
            context.authority.liveOrderEntryState,
        )


class RuntimeUnavailableTest(unittest.TestCase):
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_absent_manager_is_explicit_not_connected(self, existing):
        existing.return_value = None
        snapshot = read_runtime_scalars()
        self.assertEqual(snapshot.state, "NOT_CONNECTED")
        self.assertEqual(snapshot.mm_execution_entry_state, "UNAVAILABLE")
        self.assertEqual(snapshot.final_execution_entry_state, "UNKNOWN")
        self.assertEqual(snapshot.health_state, "STOPPED")
        self.assertIn("MM_BOUNDARY_UNAVAILABLE", snapshot.warnings)

    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_mm_boundary_not_registered_is_unavailable_not_blocked(self, existing):
        existing.return_value = manager()
        snapshot = read_runtime_scalars(mm_boundary_provider=lambda: None)
        self.assertEqual(snapshot.mm_execution_entry_state, "UNAVAILABLE")
        self.assertEqual(snapshot.mm_state, None)
        self.assertIn("MM_BOUNDARY_NOT_REGISTERED", snapshot.warnings)

    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_mm_projection_failure_is_unavailable_not_blocked(self, existing):
        existing.return_value = manager()

        def failing():
            raise RuntimeError("mm projection failed")

        snapshot = read_runtime_scalars(mm_boundary_provider=failing)
        self.assertEqual(snapshot.mm_execution_entry_state, "UNAVAILABLE")
        self.assertIn("MM_BOUNDARY_READ_FAILED", snapshot.warnings)

    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_mm_unknown_entry_value_is_unknown_without_false_hint(self, existing):
        existing.return_value = manager()
        snapshot = read_runtime_scalars(
            mm_boundary_provider=lambda: mm_boundary(
                execution_entry_allowed=None
            )
        )
        self.assertEqual(snapshot.mm_execution_entry_state, "UNKNOWN")
        self.assertEqual(snapshot.final_execution_entry_state, "UNKNOWN")


class ReaderIsolationTest(unittest.TestCase):
    @patch("backend.ai_advisor.runtime_reader.get_existing_bot_manager")
    def test_reader_never_mutates_manager_when_reading_market_and_mm(
        self,
        existing,
    ):
        state = SimpleNamespace(
            runtime_metrics={"last_bot_update": time.time() - 5}
        )
        manager_value = manager(state=state)
        manager_value.get_result = Mock(
            side_effect=AssertionError("must not call get_result")
        )
        manager_value.get_status = Mock(
            side_effect=AssertionError("must not call get_status")
        )
        manager_value._get_real_account_snapshot = Mock(
            side_effect=AssertionError("must not refresh account")
        )
        manager_value.set_config = Mock(
            side_effect=AssertionError("must not mutate config")
        )
        existing.return_value = manager_value
        before = dict(state.runtime_metrics)

        snapshot = read_runtime_scalars(
            mm_boundary_provider=lambda: mm_boundary()
        )

        manager_value.get_result.assert_not_called()
        manager_value.get_status.assert_not_called()
        manager_value._get_real_account_snapshot.assert_not_called()
        manager_value.set_config.assert_not_called()
        self.assertEqual(state.runtime_metrics, before)
        self.assertEqual(snapshot.mm_execution_entry_state, "ALLOWED")


class RuntimeFreshnessTest(unittest.TestCase):

    def test_stale_source_is_explicit(self):
        value = runtime(
            runtime=AdvisorRuntimeMetadata(
                capturedAt=NOW.isoformat(),
                sourceUpdatedAt=(NOW - timedelta(seconds=11)).isoformat(),
                freshness=Freshness.STALE,
            )
        )
        context, source, warnings = build_runtime_context(
            value,
            source_id="advisor-runtime",
            generated_at=NOW,
        )
        self.assertEqual(source.freshness.state, "STALE")
        self.assertIn("STALE_SOURCE", [w.value for w in warnings])

    def test_missing_source_timestamp_is_unknown(self):
        value = runtime(
            runtime=AdvisorRuntimeMetadata(
                capturedAt=NOW.isoformat(),
                sourceUpdatedAt=None,
                freshness=Freshness.UNKNOWN,
            )
        )
        _, source, _ = build_runtime_context(
            value,
            source_id="advisor-runtime",
            generated_at=NOW,
        )
        self.assertEqual(source.freshness.state, "UNKNOWN")


class SanitizationTest(unittest.TestCase):
    def test_context_excludes_secrets_callables_and_operational_objects(self):
        value = runtime()
        context, _, _ = build_runtime_context(
            value,
            source_id="advisor-runtime",
            generated_at=NOW,
        )
        payload = context.model_dump(mode="json")
        serialized = str(payload).lower()
        for forbidden in (
            "apikey",
            "api_secret",
            "cookie",
            "csrf",
            "password",
            "passphrase",
            "access_token",
            "refresh_token",
            "bearer ",
            "-----begin",
            "authorization",
            "/home/",
            "credential",
        ):
            self.assertNotIn(forbidden, serialized)
        for field_name, field_value in context.__dict__.items():
            self.assertFalse(callable(field_value), field_name)
        for operator_method in (
            "get_status",
            "start,",
            "submit_order",
            "create_order",
            "cancel_order",
        ):
            self.assertNotIn(operator_method, serialized)

    def test_runtime_response_never_exposes_operational_boundary_object(self):
        value = runtime()
        dump = value.model_dump(mode="json")
        serialized = str(dump)
        self.assertNotIn("get_status", serialized)
        self.assertNotIn("money_management_http_boundary", serialized)
        self.assertNotIn("apiKey", serialized)
        self.assertNotIn("secret", serialized)


class AuthorityProofTest(unittest.TestCase):
    def test_runtime_context_has_no_mutation_field_or_method(self):
        value = runtime()
        context, _, _ = build_runtime_context(
            value,
            source_id="advisor-runtime",
            generated_at=NOW,
        )
        forbidden_verbs = {
            "start",
            "stop",
            "enable",
            "disable",
            "submit",
            "cancel",
            "replace",
            "unlock",
            "approve",
            "configure",
            "set_risk",
            "change_mode",
            "create_order",
            "execute",
        }
        fields = {name for name in type(context).model_fields}
        attrs = {name for name in dir(context)}
        for verb in forbidden_verbs:
            self.assertNotIn(verb, fields)
            self.assertNotIn(verb, attrs)

    def test_context_models_are_immutable(self):
        value = runtime()
        context, _, _ = build_runtime_context(
            value,
            source_id="advisor-runtime",
            generated_at=NOW,
        )
        with self.assertRaises((ValidationError, ValueError, TypeError)):
            context.state = "STOPPED"


class BehaviorDistinctionTest(unittest.TestCase):
    def build_prompt(self, value):
        context = build_advisor_context(
            generated_at=NOW,
            permission_context=permission(),
            runtime=value,
            current_message=current_message(),
        )
        return build_advisor_prompt(
            request=AdvisorRequest(
                schemaVersion="1.0",
                requestId="request-1",
                messageId="message-1",
                message="Explain why entry is blocked.",
                locale="en-US",
                requestedAt=NOW,
                permissionContext=permission(),
                contextEnvelope=context,
                responsePreferences=None,
            ),
            context=context,
            policy=AdvisorPromptPolicy(),
        )

    def test_scenarios_render_distinct_runtime_evidence(self):
        bot_stopped = runtime(
            bot=AdvisorBotStatus(
                state="STOPPED",
                mode="PAPER",
                exchange="kucoin",
                symbol="BTCUSDT",
            ),
            health=AdvisorHealthStatus(healthState="STOPPED"),
        )
        mm_blocks = runtime(
            authority=AdvisorAuthorityStatus(
                liveOrderEntryState=AdvisorExecutionEntryState.BLOCKED,
                finalExecutionEntryState=AdvisorExecutionEntryState.BLOCKED,
                mmExecutionEntryState=AdvisorExecutionEntryState.BLOCKED,
            ),
            moneyManagement=AdvisorMoneyManagementStatus(
                state="RUNNING",
                riskState="LOCKED",
                recommendedAction="BLOCK_EXECUTION",
                executionEntryState=AdvisorExecutionEntryState.BLOCKED,
            ),
        )
        market_stale = runtime(
            market=AdvisorMarketStatus(
                selectionMode="AUTO",
                marketReady=False,
                marketStale=True,
            ),
            health=AdvisorHealthStatus(healthState="DEGRADED"),
        )
        permission_unknown = runtime(
            authority=AdvisorAuthorityStatus(
                liveOrderEntryState=AdvisorExecutionEntryState.UNKNOWN,
                finalExecutionEntryState=AdvisorExecutionEntryState.UNKNOWN,
                mmExecutionEntryState=AdvisorExecutionEntryState.UNKNOWN,
            ),
            moneyManagement=AdvisorMoneyManagementStatus(
                state=None,
                riskState=None,
                recommendedAction=None,
                executionEntryState=AdvisorExecutionEntryState.UNKNOWN,
            ),
        )
        for value, marker in (
            (bot_stopped, "botState=STOPPED"),
            (mm_blocks, "mmEntryState=BLOCKED"),
            (market_stale, "marketStale=true"),
            (permission_unknown, "finalExecutionEntryState=UNKNOWN"),
        ):
            prompt = self.build_prompt(value)
            runtime_section = next(
                item
                for item in prompt.contextSections
                if item.sectionType is AdvisorPromptSectionType.RUNTIME_CONTEXT
            )
            self.assertIn(marker, runtime_section.content, marker)


class KnowledgeSeparationTest(unittest.TestCase):
    def test_runtime_context_is_not_canonical_specification(self):
        context = build_advisor_context(
            generated_at=NOW,
            permission_context=permission(),
            runtime=runtime(),
            current_message=current_message(),
        )
        runtime_section = next(
            item
            for item in context.sources
            if item.sourceType is AdvisorSourceType.RUNTIME
        )
        self.assertEqual(
            runtime_section.authority.value, "RUNTIME_AUTHORITATIVE"
        )

    def test_prompt_keeps_runtime_and_knowledge_sections_separate(self):
        value = runtime()
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
                    topics=("executionEntryAllowed",),
                    excerpt=(
                        "Canonical meaning of executionEntryAllowed is defined "
                        "by specification."),
                ),
            ),
            runtime=value,
            current_message=current_message(),
        )
        prompt = build_advisor_prompt(
            request=AdvisorRequest(
                schemaVersion="1.0",
                requestId="request-1",
                messageId="message-1",
                message="Explain entry.",
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
        spec_section = next(
            item
            for item in prompt.contextSections
            if item.sectionType
            is AdvisorPromptSectionType.SPECIFICATION_REFERENCE
        )
        self.assertIn("botState=RUNNING", runtime_section.content)
        self.assertIn("CURRENT RUNTIME", runtime_section.title.upper())
        self.assertNotIn("Canonical meaning of executionEntryAllowed",
                         runtime_section.content)
        self.assertIn("Canonical Specification A", spec_section.content)
        self.assertNotIn("botState=RUNNING", spec_section.content)


class BrowserServerRuntimeTest(unittest.TestCase):
    def test_browser_input_carries_server_runtime_context(self):
        service_input = assemble_browser_service_input(
            prompt="Explain the runtime.",
            principal_id="operator-1",
            now=NOW,
            runtime=runtime(),
        )
        self.assertIsNotNone(service_input.contextInput.runtime)
        self.assertIsNotNone(
            service_input.request.contextEnvelope.runtimeContext
        )
        runtime_context = service_input.request.contextEnvelope.runtimeContext
        self.assertEqual(
            runtime_context.authority.mmExecutionEntryState, "ALLOWED"
        )
        self.assertEqual(
            runtime_context.authority.finalExecutionEntryState, "ALLOWED"
        )

    def test_apply_authoritative_runtime_overrides_client_runtime(self):
        client_runtime = runtime(
            authority=AdvisorAuthorityStatus(
                liveOrderEntryState=AdvisorExecutionEntryState.ALLOWED,
                finalExecutionEntryState=AdvisorExecutionEntryState.ALLOWED,
                mmExecutionEntryState=AdvisorExecutionEntryState.ALLOWED,
            ),
            moneyManagement=AdvisorMoneyManagementStatus(
                state="RUNNING",
                riskState="NORMAL",
                recommendedAction="CONTINUE",
                executionEntryState=AdvisorExecutionEntryState.ALLOWED,
            ),
        )
        service_input = assemble_browser_service_input(
            prompt="Override me.",
            principal_id="operator-1",
            now=NOW,
            runtime=client_runtime,
        )
        server_runtime = runtime(
            authority=AdvisorAuthorityStatus(
                liveOrderEntryState=AdvisorExecutionEntryState.BLOCKED,
                finalExecutionEntryState=AdvisorExecutionEntryState.BLOCKED,
                mmExecutionEntryState=AdvisorExecutionEntryState.BLOCKED,
            ),
            moneyManagement=AdvisorMoneyManagementStatus(
                state="RUNNING",
                riskState="LOCKED",
                recommendedAction="BLOCK_EXECUTION",
                executionEntryState=AdvisorExecutionEntryState.BLOCKED,
            ),
        )
        with patch(
            "backend.api.ai_advisor.build_authoritative_runtime",
            return_value=server_runtime,
        ):
            applied = apply_authoritative_runtime(
                service_input, SimpleNamespace()
            )
        self.assertEqual(
            applied.contextInput.runtime.authority.finalExecutionEntryState,
            AdvisorExecutionEntryState.BLOCKED,
        )
        self.assertEqual(
            applied.request.contextEnvelope.runtimeContext.authority.finalExecutionEntryState,
            "BLOCKED",
        )

    def test_runtime_read_failure_degrades_browser_feature_without_serving(self):
        service_input = assemble_browser_service_input(
            prompt="Explain the runtime.",
            principal_id="operator-1",
            now=NOW,
            runtime=runtime(),
        )
        with patch(
            "backend.api.ai_advisor.build_authoritative_runtime",
            side_effect=RuntimeError("boom"),
        ):
            applied = apply_authoritative_runtime(
                service_input, SimpleNamespace()
            )
        self.assertIsNone(applied.contextInput.runtime)
        self.assertIsNone(applied.request.contextEnvelope.runtimeContext)


if __name__ == "__main__":
    unittest.main()
