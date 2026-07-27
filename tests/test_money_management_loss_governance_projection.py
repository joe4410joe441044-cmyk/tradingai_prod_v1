import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

from backend.money_management.enums import RiskState
from backend.money_management.loss_governance_projection import (
    build_loss_governance_projection,
)
from backend.money_management.loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernanceBoundaryReason,
    LossGovernanceProjectionBuildInput,
)
from backend.money_management.loss_reason_models import (
    BlockReason,
    DiagnosticReason,
    HoldReason,
    LossReasonContract,
    ReasonCode,
    RecommendedAction,
    WarningReason,
)
from backend.money_management.loss_runtime_integration_models import (
    GovernanceProjection,
)


NOW = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)


def decision(
    state=RiskState.NORMAL,
    action=RecommendedAction.CONTINUE,
    primary=ReasonCode.NONE,
    warnings=(),
    holds=(),
    blocks=(),
    diagnostics=(),
    fail_closed=False,
):
    return LossReasonContract(
        "money-management-loss-reason/v1",
        NOW,
        state,
        action,
        primary,
        tuple(warnings),
        tuple(holds),
        tuple(blocks),
        tuple(diagnostics),
        (),
        (),
        fail_closed,
    )


def build(value, loss_state, recovery=False):
    return build_loss_governance_projection(
        LossGovernanceProjectionBuildInput(
            value, loss_state, recovery, NOW
        )
    )


class GovernanceProjectionBuilderTests(unittest.TestCase):
    def test_allow_projection(self):
        source = decision()
        before = source.to_dict()
        projection = build(source, GovernanceProjection.CONTINUE)
        self.assertEqual(projection.entry_permission, LossEntryPermission.ALLOW)
        self.assertTrue(projection.new_entry_allowed)
        self.assertIsNone(projection.block_reason)
        self.assertEqual(projection.risk_state, RiskState.NORMAL)
        self.assertEqual(projection.loss_state, GovernanceProjection.CONTINUE)
        self.assertEqual(source.to_dict(), before)

    def test_block_projection_reuses_existing_block_reason(self):
        source = decision(
            RiskState.LOCKED,
            RecommendedAction.BLOCK_EXECUTION,
            ReasonCode.DAILY_LOSS_BLOCK,
            blocks=(BlockReason.DAILY_LOSS_BLOCK,),
            fail_closed=False,
        )
        projection = build(source, GovernanceProjection.BLOCK_EXECUTION)
        self.assertEqual(projection.entry_permission, LossEntryPermission.BLOCK)
        self.assertFalse(projection.new_entry_allowed)
        self.assertIs(
            projection.block_reason, BlockReason.DAILY_LOSS_BLOCK
        )
        self.assertEqual(projection.risk_state, RiskState.LOCKED)

    def test_hold_projection_reuses_existing_hold_reason(self):
        source = decision(
            RiskState.DEFENSIVE,
            RecommendedAction.HOLD_NEW_ENTRIES,
            ReasonCode.MULTIPLE_LOSS_WARNINGS,
            warnings=(
                WarningReason.DAILY_LOSS_WARNING,
                WarningReason.WEEKLY_LOSS_WARNING,
            ),
            holds=(HoldReason.MULTIPLE_LOSS_WARNINGS,),
        )
        projection = build(source, GovernanceProjection.HOLD_NEW_ENTRIES)
        self.assertEqual(projection.entry_permission, LossEntryPermission.BLOCK)
        self.assertIs(
            projection.block_reason, HoldReason.MULTIPLE_LOSS_WARNINGS
        )

    def test_recovery_projection_overrides_decision(self):
        projection = build(
            decision(),
            GovernanceProjection.RECOVERY_REQUIRED,
            recovery=True,
        )
        self.assertEqual(
            projection.entry_permission,
            LossEntryPermission.RECOVERY_REQUIRED,
        )
        self.assertFalse(projection.new_entry_allowed)
        self.assertIs(
            projection.block_reason,
            LossGovernanceBoundaryReason.RECOVERY_REQUIRED,
        )
        self.assertTrue(projection.recovery_required)

    def test_missing_or_fail_closed_decision_is_unknown(self):
        missing = build(None, GovernanceProjection.CONTINUE)
        unsafe = build(
            decision(
                RiskState.LOCKED,
                RecommendedAction.BLOCK_EXECUTION,
                ReasonCode.DRAWDOWN_PERCENT_UNKNOWN,
                blocks=(BlockReason.DRAWDOWN_PERCENT_UNKNOWN,),
                diagnostics=(DiagnosticReason.HIGH_WATER_MARK_ZERO,),
                fail_closed=True,
            ),
            GovernanceProjection.BLOCK_EXECUTION,
        )
        for projection in (missing, unsafe):
            self.assertEqual(
                projection.entry_permission, LossEntryPermission.UNKNOWN
            )
            self.assertFalse(projection.new_entry_allowed)
            self.assertIs(
                projection.block_reason,
                LossGovernanceBoundaryReason.UNKNOWN_STATE,
            )
            self.assertIn(
                DiagnosticReason.METRIC_UNAVAILABLE,
                projection.diagnostic_reasons,
            )

    def test_unknown_restrictive_state_without_reason_fails_closed(self):
        projection = build(
            decision(),
            GovernanceProjection.BLOCK_EXECUTION,
        )
        self.assertEqual(
            projection.entry_permission, LossEntryPermission.UNKNOWN
        )

    def test_deterministic_immutable_and_safe_serialization(self):
        source = decision()
        first = build(source, GovernanceProjection.CONTINUE)
        second = build(source, GovernanceProjection.CONTINUE)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertNotIn("snapshot", first.to_dict())
        self.assertNotIn("exception", first.to_dict())
        with self.assertRaises(FrozenInstanceError):
            first.new_entry_allowed = False


if __name__ == "__main__":
    unittest.main()
