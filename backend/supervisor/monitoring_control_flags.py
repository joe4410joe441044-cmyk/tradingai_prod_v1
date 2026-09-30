"""Default-OFF feature flags for the Supervisor monitoring control plane.

Every flag is resolved from an **injected** mapping; this module never reads the
process environment itself.  Missing, empty, malformed or non-truthy values are
disabled.  Resolving a flag creates no task, opens no file and persists nothing.

Preserved defaults (all OFF):

- ``AI_SUPERVISOR_MANUAL_TRIGGER_API_ENABLED``
- ``AI_SUPERVISOR_MONITORING_SCHEDULER_ENABLED``
- ``AI_SUPERVISOR_ALERT_OUTBOX_ENABLED``
- ``AI_ADVISOR_SUPERVISOR_ALERT_EXPLANATION_ENABLED``
"""
from __future__ import annotations

from typing import Mapping

from .monitoring_models import Contract
from .monitoring_scheduler_models import FeatureFlagStatus, resolve_feature_flag_status

MANUAL_TRIGGER_API_FLAG = "AI_SUPERVISOR_MANUAL_TRIGGER_API_ENABLED"
MONITORING_SCHEDULER_FLAG = "AI_SUPERVISOR_MONITORING_SCHEDULER_ENABLED"
ALERT_OUTBOX_FLAG = "AI_SUPERVISOR_ALERT_OUTBOX_ENABLED"
ADVISOR_ALERT_EXPLANATION_FLAG = "AI_ADVISOR_SUPERVISOR_ALERT_EXPLANATION_ENABLED"

ALL_FLAGS = (
    MANUAL_TRIGGER_API_FLAG,
    MONITORING_SCHEDULER_FLAG,
    ALERT_OUTBOX_FLAG,
    ADVISOR_ALERT_EXPLANATION_FLAG,
)


def resolve_flag(environ: Mapping[str, str] | None, name: str) -> FeatureFlagStatus:
    """Resolve one flag from an injected mapping; fail closed to OFF."""

    if environ is None:
        raw = None
    else:
        try:
            raw = environ.get(name)
        except Exception:  # noqa: BLE001 - an unusable mapping is treated as unset
            raw = None
    return resolve_feature_flag_status(raw)


class ControlFlags(Contract):
    """Bounded, secret-free snapshot of every control-plane flag."""

    manual_trigger_api: FeatureFlagStatus
    monitoring_scheduler: FeatureFlagStatus
    alert_outbox: FeatureFlagStatus
    advisor_alert_explanation: FeatureFlagStatus

    @property
    def manual_trigger_enabled(self) -> bool:
        return bool(self.manual_trigger_api.enabled and self.manual_trigger_api.valid)

    @property
    def scheduler_enabled(self) -> bool:
        return bool(self.monitoring_scheduler.enabled and self.monitoring_scheduler.valid)

    @property
    def alert_outbox_enabled(self) -> bool:
        return bool(self.alert_outbox.enabled and self.alert_outbox.valid)

    @property
    def advisor_alert_explanation_enabled(self) -> bool:
        return bool(
            self.advisor_alert_explanation.enabled
            and self.advisor_alert_explanation.valid
        )

    @property
    def all_off(self) -> bool:
        return not (
            self.manual_trigger_enabled
            or self.scheduler_enabled
            or self.alert_outbox_enabled
            or self.advisor_alert_explanation_enabled
        )


def resolve_control_flags(environ: Mapping[str, str] | None) -> ControlFlags:
    """Resolve every flag from an injected mapping.  No task is created."""

    return ControlFlags(
        manual_trigger_api=resolve_flag(environ, MANUAL_TRIGGER_API_FLAG),
        monitoring_scheduler=resolve_flag(environ, MONITORING_SCHEDULER_FLAG),
        alert_outbox=resolve_flag(environ, ALERT_OUTBOX_FLAG),
        advisor_alert_explanation=resolve_flag(environ, ADVISOR_ALERT_EXPLANATION_FLAG),
    )


__all__ = [
    "ADVISOR_ALERT_EXPLANATION_FLAG",
    "ALERT_OUTBOX_FLAG",
    "ALL_FLAGS",
    "ControlFlags",
    "MANUAL_TRIGGER_API_FLAG",
    "MONITORING_SCHEDULER_FLAG",
    "resolve_control_flags",
    "resolve_flag",
]
