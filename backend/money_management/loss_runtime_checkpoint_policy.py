"""MM-4E deterministic checkpoint policy."""
from .loss_runtime_coordination_models import (
    LossLimitCheckpointPolicyDecision,
    RuntimeOperationType,
)
from .loss_runtime_integration_models import RuntimeLifecycle, SaveTrigger
from .loss_runtime_store_models import LossLimitRuntimeSnapshot


_PRIORITY = (
    SaveTrigger.RUNTIME_SHUTDOWN,
    SaveTrigger.LOCKED,
    SaveTrigger.ACCOUNTING_REBASE,
    SaveTrigger.PERIOD_ROLLOVER,
    SaveTrigger.STATE_TRANSITION,
    SaveTrigger.INITIAL_STATE_CREATED,
    SaveTrigger.REASON_CHANGED,
    SaveTrigger.METRIC_CHANGED,
    SaveTrigger.MANUAL_CHECKPOINT,
)
_MANDATORY = frozenset(
    (
        SaveTrigger.INITIAL_STATE_CREATED,
        SaveTrigger.STATE_TRANSITION,
        SaveTrigger.LOCKED,
        SaveTrigger.PERIOD_ROLLOVER,
        SaveTrigger.ACCOUNTING_REBASE,
        SaveTrigger.RUNTIME_SHUTDOWN,
    )
)


def build_loss_limit_checkpoint_policy_decision(
    operation_type,
    runtime_result_status,
    snapshot,
    save_required,
    save_triggers,
):
    operation = RuntimeOperationType(operation_type)
    if not isinstance(runtime_result_status, str) or not runtime_result_status:
        raise ValueError("runtime result status required")
    if snapshot is not None and not isinstance(snapshot, LossLimitRuntimeSnapshot):
        raise TypeError("snapshot invalid")
    if type(save_required) is not bool:
        raise TypeError("save_required must be bool")
    triggers = tuple(SaveTrigger(item) for item in save_triggers)
    if len(triggers) != len(set(triggers)):
        raise ValueError("duplicate save trigger")
    if snapshot is not None and tuple(snapshot.save_triggers) != triggers:
        raise ValueError("snapshot trigger mismatch")
    if runtime_result_status not in ("SUCCEEDED", "IDEMPOTENT"):
        return LossLimitCheckpointPolicyDecision(False, None, False, False)
    if operation is RuntimeOperationType.MANUAL_CHECKPOINT:
        return LossLimitCheckpointPolicyDecision(
            True, SaveTrigger.MANUAL_CHECKPOINT, False, True
        )
    if snapshot is None:
        raise ValueError("successful runtime result requires snapshot")
    candidates = [trigger for trigger in _PRIORITY if trigger in triggers]
    # An idempotent operation may retry an explicit checkpoint after a prior
    # durability failure. The checkpoint coordinator decides saved vs unsaved.
    required = save_required or (runtime_result_status == "IDEMPOTENT" and bool(candidates))
    if not required:
        return LossLimitCheckpointPolicyDecision(False, None, False, True)
    if not candidates:
        raise ValueError("save required without trigger")
    trigger = candidates[0]
    if operation is RuntimeOperationType.STARTUP and trigger is not SaveTrigger.INITIAL_STATE_CREATED:
        raise ValueError("invalid startup checkpoint trigger")
    if operation is RuntimeOperationType.STOP and (
        snapshot.lifecycle is not RuntimeLifecycle.STOPPED
        or trigger is not SaveTrigger.RUNTIME_SHUTDOWN
    ):
        raise ValueError("invalid shutdown checkpoint")
    return LossLimitCheckpointPolicyDecision(
        True, trigger, trigger in _MANDATORY, True
    )
