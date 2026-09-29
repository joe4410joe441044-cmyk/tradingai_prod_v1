"""Application-side Supervisor monitoring control plane composition.

This module wires the default-OFF Supervisor monitoring control plane for the
FastAPI application.  Composition is deliberately side-effect free at import:

- no Production file, SQLite database, lock or outbox is opened or created at
  import;
- no monitoring run happens at startup while flags are OFF;
- optional dependencies are constructed lazily and their failures become bounded
  health unavailability rather than startup failure.

Preserved truths: ``PRODUCTION_ACTIVATION_ALLOWED=NO``,
``PRODUCTION_AUTHORIZATION_SOURCE`` is resolved through the server-configured
capability mapping, and Production activation eligibility remains ``BLOCKED``.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import Field, field_validator

from .monitoring_alert_service import MonitoringAlertService
from .monitoring_control_flags import ControlFlags, resolve_control_flags
from .monitoring_models import Contract, Count, Token, aware
from .monitoring_scheduler import SchedulerRuntimeHealth
from .supervisor_authorization import (
    SupervisorAuthorizationAuthority,
    load_supervisor_authorization_config,
)
from .supervisor_trigger_service import SupervisorTriggerService

CONTROL_PLANE_SCHEMA_VERSION = "supervisor-monitoring-control-plane-v1"
PRODUCTION_ACTIVATION_ELIGIBILITY = "BLOCKED"
CROSS_PROCESS_SAFETY = "NOT_GUARANTEED_PRODUCTION_ACTIVATION_BLOCKED"

TRIGGER_DB_PATH_ENV = "AI_SUPERVISOR_MONITORING_TRIGGER_DB_PATH"
TRIGGER_LOCK_PATH_ENV = "AI_SUPERVISOR_MONITORING_TRIGGER_LOCK_PATH"
TRIGGER_AUDIT_PATH_ENV = "AI_SUPERVISOR_MONITORING_TRIGGER_AUDIT_PATH"
ALERT_DB_PATH_ENV = "AI_SUPERVISOR_MONITORING_ALERT_DB_PATH"
STATE_JOURNAL_PATH_ENV = "AI_SUPERVISOR_MONITORING_STATE_JOURNAL_PATH"

_MAX_PATH_LENGTH = 1024


def _optional_path(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > _MAX_PATH_LENGTH or "\n" in text or "\r" in text:
        return None
    if not Path(text).is_absolute():
        return None
    return text


class ControlPlaneConfig(Contract):
    """Server-owned monitoring paths.  Never request-controlled."""

    trigger_db_path: str | None = Field(default=None, max_length=_MAX_PATH_LENGTH)
    trigger_lock_path: str | None = Field(default=None, max_length=_MAX_PATH_LENGTH)
    trigger_audit_path: str | None = Field(default=None, max_length=_MAX_PATH_LENGTH)
    alert_db_path: str | None = Field(default=None, max_length=_MAX_PATH_LENGTH)
    state_journal_path: str | None = Field(default=None, max_length=_MAX_PATH_LENGTH)


class ControlPlaneStatus(Contract):
    """Bounded, sanitized control-plane health projection for GET routes."""

    schema_version: Token = CONTROL_PLANE_SCHEMA_VERSION
    generated_at: datetime
    manual_trigger_enabled: bool = False
    manual_trigger_valid: bool = True
    manual_trigger_configured: bool = False
    scheduler_enabled: bool = False
    scheduler_valid: bool = True
    scheduler_configured: bool = False
    scheduler_connected: bool = False
    alert_outbox_enabled: bool = False
    alert_outbox_valid: bool = True
    alert_store_configured: bool = False
    advisor_alert_explanation_enabled: bool = False
    authorization_availability: Token = "NOT_CONFIGURED"
    capability_mapping_configured: bool = False
    idempotency_store_configured: bool = False
    ownership_lock_configured: bool = False
    audit_store_configured: bool = False
    pending_alert_count: Count = 0
    scheduler_health: SchedulerRuntimeHealth | None = None
    cross_process_safety: Token = CROSS_PROCESS_SAFETY
    production_activation_eligibility: Token = PRODUCTION_ACTIVATION_ELIGIBILITY
    production_activation_allowed: bool = False

    _aware = field_validator("generated_at")(aware)


class SupervisorControlPlane:
    """Composition holder for the default-OFF Supervisor monitoring control plane."""

    def __init__(
        self,
        *,
        flags: ControlFlags,
        authorization: SupervisorAuthorizationAuthority,
        config: ControlPlaneConfig | None = None,
        trigger_service: SupervisorTriggerService | None = None,
        alert_service: MonitoringAlertService | None = None,
        scheduler=None,
        scheduler_runner_configured: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._flags = flags
        self._authorization = authorization
        self._config = config if config is not None else ControlPlaneConfig()
        self._trigger_service = trigger_service
        self._alert_service = alert_service
        self._scheduler = scheduler
        self._scheduler_runner_configured = bool(scheduler_runner_configured)
        self._clock = clock if clock is not None else (
            lambda: datetime.now(timezone.utc)
        )

    # -- accessors -----------------------------------------------------------

    @property
    def flags(self) -> ControlFlags:
        return self._flags

    @property
    def authorization(self) -> SupervisorAuthorizationAuthority:
        return self._authorization

    @property
    def config(self) -> ControlPlaneConfig:
        return self._config

    @property
    def trigger_service(self) -> SupervisorTriggerService | None:
        if not self._flags.manual_trigger_enabled:
            return None
        return self._trigger_service

    @property
    def alert_service(self) -> MonitoringAlertService | None:
        return self._alert_service

    @property
    def scheduler(self):
        return self._scheduler

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> bool:
        scheduler = self._scheduler
        if scheduler is None:
            return False
        try:
            return bool(scheduler.start())
        except Exception:  # noqa: BLE001 - startup must never fail on optional monitoring
            return False

    def stop(self, timeout: float | None = None) -> bool:
        scheduler = self._scheduler
        if scheduler is None:
            return True
        try:
            return bool(scheduler.stop(timeout))
        except Exception:  # noqa: BLE001
            return False

    # -- status --------------------------------------------------------------

    def status(self) -> ControlPlaneStatus:
        flags = self._flags
        alert_service = self._alert_service
        scheduler_health = None
        scheduler_configured = self._scheduler is not None
        scheduler_connected = False
        if self._scheduler is not None:
            try:
                scheduler_health = self._scheduler.health(now=aware(self._clock()))
                scheduler_connected = bool(scheduler_health.thread_active)
            except Exception:  # noqa: BLE001 - health must never break reads
                scheduler_health = None
        pending = 0
        if alert_service is not None and alert_service.configured:
            try:
                pending = alert_service.pending_count()
            except Exception:  # noqa: BLE001
                pending = 0
        return ControlPlaneStatus(
            generated_at=aware(self._clock()),
            manual_trigger_enabled=flags.manual_trigger_enabled,
            manual_trigger_valid=bool(flags.manual_trigger_api.valid),
            manual_trigger_configured=self._trigger_service is not None,
            scheduler_enabled=flags.scheduler_enabled,
            scheduler_valid=bool(flags.monitoring_scheduler.valid),
            scheduler_configured=scheduler_configured,
            scheduler_connected=scheduler_connected,
            alert_outbox_enabled=flags.alert_outbox_enabled,
            alert_outbox_valid=bool(flags.alert_outbox.valid),
            alert_store_configured=bool(
                alert_service is not None and alert_service.configured
            ),
            advisor_alert_explanation_enabled=(
                flags.advisor_alert_explanation_enabled
            ),
            authorization_availability=self._authorization.availability,
            capability_mapping_configured=self._authorization.configured,
            idempotency_store_configured=self._config.trigger_db_path is not None,
            ownership_lock_configured=self._config.trigger_lock_path is not None,
            audit_store_configured=self._config.trigger_audit_path is not None,
            pending_alert_count=pending,
            scheduler_health=scheduler_health,
            cross_process_safety=CROSS_PROCESS_SAFETY,
            production_activation_eligibility=PRODUCTION_ACTIVATION_ELIGIBILITY,
            production_activation_allowed=False,
        )

    # -- construction --------------------------------------------------------

    @classmethod
    def from_environ(
        cls,
        environ=None,
        *,
        trigger_service: SupervisorTriggerService | None = None,
        alert_service: MonitoringAlertService | None = None,
        scheduler=None,
        scheduler_runner_configured: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> "SupervisorControlPlane":
        if environ is None:
            environ = os.environ
        flags = resolve_control_flags(environ)
        authorization = SupervisorAuthorizationAuthority(
            load_supervisor_authorization_config(environ)
        )
        try:
            config = ControlPlaneConfig(
                trigger_db_path=_optional_path(environ.get(TRIGGER_DB_PATH_ENV)),
                trigger_lock_path=_optional_path(environ.get(TRIGGER_LOCK_PATH_ENV)),
                trigger_audit_path=_optional_path(environ.get(TRIGGER_AUDIT_PATH_ENV)),
                alert_db_path=_optional_path(environ.get(ALERT_DB_PATH_ENV)),
                state_journal_path=_optional_path(environ.get(STATE_JOURNAL_PATH_ENV)),
            )
        except Exception:  # noqa: BLE001
            config = ControlPlaneConfig()
        return cls(
            flags=flags, authorization=authorization, config=config,
            trigger_service=trigger_service, alert_service=alert_service,
            scheduler=scheduler, scheduler_runner_configured=scheduler_runner_configured,
            clock=clock,
        )


_control_plane: SupervisorControlPlane | None = None


def get_control_plane(environ=None) -> SupervisorControlPlane:
    """Process-wide control plane, built lazily and side-effect free."""

    global _control_plane
    if _control_plane is None:
        _control_plane = SupervisorControlPlane.from_environ(environ)
    return _control_plane


def reset_control_plane(value: SupervisorControlPlane | None = None) -> None:
    """Test/composition hook to replace the singleton."""

    global _control_plane
    _control_plane = value


__all__ = [
    "ALERT_DB_PATH_ENV",
    "CONTROL_PLANE_SCHEMA_VERSION",
    "ControlPlaneConfig",
    "ControlPlaneStatus",
    "CROSS_PROCESS_SAFETY",
    "PRODUCTION_ACTIVATION_ELIGIBILITY",
    "STATE_JOURNAL_PATH_ENV",
    "SupervisorControlPlane",
    "TRIGGER_AUDIT_PATH_ENV",
    "TRIGGER_DB_PATH_ENV",
    "TRIGGER_LOCK_PATH_ENV",
    "get_control_plane",
    "reset_control_plane",
]
