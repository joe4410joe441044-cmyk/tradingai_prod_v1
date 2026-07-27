"""MM-4J pure builder for governance-facing loss projections."""

from .enums import RiskState
from .loss_governance_projection_models import (
    LossEntryPermission,
    LossGovernanceBoundaryReason,
    LossGovernanceProjection,
    LossGovernanceProjectionBuildInput,
)
from .loss_reason_models import RecommendedAction
from .loss_runtime_integration_models import GovernanceProjection


def _unknown(generated_at, diagnostics=()):
    from .loss_reason_models import DiagnosticReason

    reasons = tuple(diagnostics)
    if DiagnosticReason.METRIC_UNAVAILABLE not in reasons:
        reasons += (DiagnosticReason.METRIC_UNAVAILABLE,)
    return LossGovernanceProjection(
        LossEntryPermission.UNKNOWN,
        False,
        LossGovernanceBoundaryReason.UNKNOWN_STATE,
        None,
        None,
        False,
        reasons,
        generated_at,
    )


def build_loss_governance_projection(build_input):
    """Map an existing loss decision to a projection without risk evaluation."""

    if not isinstance(build_input, LossGovernanceProjectionBuildInput):
        raise TypeError("governance projection input required")
    decision = build_input.decision
    loss_state = build_input.loss_state
    if (
        build_input.recovery_required
        or loss_state is GovernanceProjection.RECOVERY_REQUIRED
    ):
        diagnostics = decision.diagnostic_reasons if decision is not None else ()
        return LossGovernanceProjection(
            LossEntryPermission.RECOVERY_REQUIRED,
            False,
            LossGovernanceBoundaryReason.RECOVERY_REQUIRED,
            decision.decision_state if decision is not None else None,
            GovernanceProjection.RECOVERY_REQUIRED,
            True,
            diagnostics,
            build_input.generated_at,
        )
    if decision is None or loss_state is None or decision.fail_closed:
        return _unknown(
            build_input.generated_at,
            decision.diagnostic_reasons if decision is not None else (),
        )

    if (
        loss_state is GovernanceProjection.CONTINUE
        and decision.recommended_action
        in (RecommendedAction.CONTINUE, RecommendedAction.REDUCE_RISK)
        and decision.decision_state is not RiskState.LOCKED
    ):
        return LossGovernanceProjection(
            LossEntryPermission.ALLOW,
            True,
            None,
            decision.decision_state,
            loss_state,
            False,
            decision.diagnostic_reasons,
            build_input.generated_at,
        )

    if loss_state in (
        GovernanceProjection.HOLD_NEW_ENTRIES,
        GovernanceProjection.BLOCK_EXECUTION,
    ):
        if not decision.block_reasons and not decision.hold_reasons:
            return _unknown(build_input.generated_at, decision.diagnostic_reasons)
        reason = (
            decision.block_reasons[0]
            if decision.block_reasons
            else decision.hold_reasons[0]
        )
        return LossGovernanceProjection(
            LossEntryPermission.BLOCK,
            False,
            reason,
            decision.decision_state,
            loss_state,
            False,
            decision.diagnostic_reasons,
            build_input.generated_at,
        )

    return _unknown(build_input.generated_at, decision.diagnostic_reasons)
