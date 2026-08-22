"""MM-5A2 application gate for the shared execution entry boundary."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from threading import RLock
from typing import Optional

from .loss_execution_guard import (
    LossExecutionEntryGuardDispatcher,
    dispatch_money_management_execution_entry_guard,
)
from .loss_execution_guard_models import (
    LossExecutionEntryDecision,
    LossExecutionGuardRequest,
    LossExecutionGuardResult,
    LossExecutionOperation,
)
from .loss_governance_projection_dispatcher import (
    LossGovernanceProjectionDispatcher,
    dispatch_money_management_governance_projection,
)
from .loss_runtime_hook import (
    APPLICATION_STATE_ATTRIBUTE as RUNTIME_HOOK_STATE_ATTRIBUTE,
    MoneyManagementRuntimeHookRegistration,
    register_money_management_runtime_hook,
)
from .loss_runtime_update_dispatcher import LossRuntimeDispatchStatus


APPLICATION_STATE_ATTRIBUTE = "money_management_execution_entry_gate"


class LossExecutionAdmissionReason(str, Enum):
    ENTRY_ALLOWED = "ENTRY_ALLOWED"
    OPERATION_NOT_GUARDED = "OPERATION_NOT_GUARDED"
    EXECUTION_INTENT_INVALID = "EXECUTION_INTENT_INVALID"
    MONEY_MANAGEMENT_BLOCKED = "MONEY_MANAGEMENT_BLOCKED"
    MONEY_MANAGEMENT_RECOVERY_REQUIRED = (
        "MONEY_MANAGEMENT_RECOVERY_REQUIRED"
    )
    MONEY_MANAGEMENT_UNKNOWN = "MONEY_MANAGEMENT_UNKNOWN"
    MONEY_MANAGEMENT_GUARD_INVALID = "MONEY_MANAGEMENT_GUARD_INVALID"


def _datetime(name, value):
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise TypeError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decimal(name, value, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal")
    if not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


def _side(name, value, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    normalized = value.strip().upper()
    if normalized not in ("BUY", "SELL"):
        raise ValueError(f"{name} invalid")
    return normalized


@dataclass(frozen=True)
class LossExecutionIntent:
    requested_side: Optional[str]
    requested_quantity: Optional[Decimal]
    has_position: bool
    position_side: Optional[str] = None
    position_quantity: Optional[Decimal] = None
    reduce_only: bool = False
    close_position: bool = False
    explicit_operation: Optional[LossExecutionOperation] = None

    def __post_init__(self):
        if type(self.has_position) is not bool:
            raise TypeError("has_position must be bool")
        for name in ("reduce_only", "close_position"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be bool")
        object.__setattr__(
            self,
            "requested_side",
            _side("requested_side", self.requested_side, optional=True),
        )
        object.__setattr__(
            self,
            "position_side",
            _side("position_side", self.position_side, optional=True),
        )
        _decimal(
            "requested_quantity",
            self.requested_quantity,
            optional=True,
        )
        _decimal(
            "position_quantity",
            self.position_quantity,
            optional=True,
        )
        if self.explicit_operation is not None:
            object.__setattr__(
                self,
                "explicit_operation",
                LossExecutionOperation(self.explicit_operation),
            )
        if not self.has_position and (
            self.position_side is not None
            or self.position_quantity is not None
        ):
            raise ValueError("position details require a position")


def classify_loss_execution_operation(intent):
    if not isinstance(intent, LossExecutionIntent):
        return None
    explicit = intent.explicit_operation
    if explicit is not None and not explicit.is_new_entry:
        return explicit
    if intent.close_position:
        return (
            LossExecutionOperation.POSITION_CLOSE
            if intent.has_position
            else None
        )
    if intent.reduce_only:
        if (
            not intent.has_position
            or intent.position_side is None
            or intent.requested_side is None
            or intent.requested_side == intent.position_side
        ):
            return None
        return LossExecutionOperation.REDUCE_ONLY
    if intent.has_position:
        return None
    if intent.requested_quantity is None:
        return None
    if intent.requested_side == "BUY":
        derived = LossExecutionOperation.NEW_BUY
        return derived if explicit in (None, derived) else None
    if intent.requested_side == "SELL":
        derived = LossExecutionOperation.NEW_SELL
        return derived if explicit in (None, derived) else None
    return None


@dataclass(frozen=True)
class LossExecutionAdmissionResult:
    operation: Optional[LossExecutionOperation]
    decision: LossExecutionEntryDecision
    allowed: bool
    reason: LossExecutionAdmissionReason
    generated_at: datetime
    revision: Optional[int]
    sequence: Optional[int]
    submitted: bool = False
    accepted: bool = False
    order_created: bool = False
    provider_call: bool = False
    exchange_call: bool = False

    def __post_init__(self):
        if self.operation is not None:
            object.__setattr__(
                self,
                "operation",
                LossExecutionOperation(self.operation),
            )
        object.__setattr__(
            self,
            "decision",
            LossExecutionEntryDecision(self.decision),
        )
        object.__setattr__(
            self,
            "reason",
            LossExecutionAdmissionReason(self.reason),
        )
        for name in (
            "allowed",
            "submitted",
            "accepted",
            "order_created",
            "provider_call",
            "exchange_call",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be bool")
        if self.allowed != (
            self.decision is LossExecutionEntryDecision.ALLOW
        ):
            raise ValueError("admission decision mismatch")
        if self.accepted != self.allowed:
            raise ValueError("admission acceptance mismatch")
        if any(
            (
                self.submitted,
                self.order_created,
                self.provider_call,
                self.exchange_call,
            )
        ):
            raise ValueError("admission result cannot claim execution")
        object.__setattr__(
            self,
            "generated_at",
            _datetime("generated_at", self.generated_at),
        )
        for name in ("revision", "sequence"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 1):
                raise ValueError(f"{name} must be a positive integer")
        if (self.revision is None) != (self.sequence is None):
            raise ValueError("revision and sequence availability mismatch")

    def to_dict(self):
        return {
            "operation": self.operation.value if self.operation else None,
            "decision": self.decision.value,
            "allowed": self.allowed,
            "reason": self.reason.value,
            "generatedAt": self.generated_at.isoformat().replace("+00:00", "Z"),
            "revision": self.revision,
            "sequence": self.sequence,
            "submitted": self.submitted,
            "accepted": self.accepted,
            "orderCreated": self.order_created,
            "providerCall": self.provider_call,
            "exchangeCall": self.exchange_call,
        }


def _admission(operation, decision, reason, at, revision=None, sequence=None):
    allowed = decision is LossExecutionEntryDecision.ALLOW
    return LossExecutionAdmissionResult(
        operation,
        decision,
        allowed,
        reason,
        at,
        revision,
        sequence,
        accepted=allowed,
    )


class MoneyManagementExecutionEntryGate:
    """Refreshes one safe projection, then validates the MM-4K result."""

    def __init__(
        self,
        app,
        guard_dispatcher=None,
        projection_dispatcher=None,
        timestamp_source=None,
        maximum_projection_age=timedelta(seconds=90),
    ):
        self._app = app
        self._guard_dispatcher = (
            guard_dispatcher or LossExecutionEntryGuardDispatcher()
        )
        self._projection_dispatcher = (
            projection_dispatcher or LossGovernanceProjectionDispatcher()
        )
        if not isinstance(
            self._guard_dispatcher, LossExecutionEntryGuardDispatcher
        ):
            raise TypeError("guard dispatcher required")
        if not isinstance(
            self._projection_dispatcher, LossGovernanceProjectionDispatcher
        ):
            raise TypeError("projection dispatcher required")
        self._timestamp_source = timestamp_source or (
            lambda: datetime.now(timezone.utc)
        )
        if not callable(self._timestamp_source):
            raise TypeError("timestamp source required")
        if (
            not isinstance(maximum_projection_age, timedelta)
            or maximum_projection_age.total_seconds() <= 0
        ):
            raise ValueError("maximum projection age must be positive")
        self._maximum_projection_age = maximum_projection_age
        self._lock = RLock()

    def evaluate(self, intent):
        try:
            now = _datetime("generated_at", self._timestamp_source())
        except (TypeError, ValueError):
            now = datetime.now(timezone.utc)
            return _admission(
                None,
                LossExecutionEntryDecision.UNKNOWN,
                LossExecutionAdmissionReason.MONEY_MANAGEMENT_GUARD_INVALID,
                now,
            )
        operation = classify_loss_execution_operation(intent)
        if operation is None:
            return _admission(
                None,
                LossExecutionEntryDecision.UNKNOWN,
                LossExecutionAdmissionReason.EXECUTION_INTENT_INVALID,
                now,
            )
        if not operation.is_new_entry:
            return _admission(
                operation,
                LossExecutionEntryDecision.ALLOW,
                LossExecutionAdmissionReason.OPERATION_NOT_GUARDED,
                now,
            )
        with self._lock:
            try:
                runtime_hook_registration = getattr(
                    getattr(self._app, "state", None),
                    RUNTIME_HOOK_STATE_ATTRIBUTE,
                    None,
                )
                need_reinit = False
                if (
                    not isinstance(
                        runtime_hook_registration,
                        MoneyManagementRuntimeHookRegistration,
                    )
                    or runtime_hook_registration.hook.last_dispatch_status
                    not in (
                        LossRuntimeDispatchStatus.APPLIED,
                        LossRuntimeDispatchStatus.IDEMPOTENT,
                    )
                ):
                    need_reinit = True
                if need_reinit:
                    new_hook = _ensure_valid_runtime_hook(self._app)
                    if new_hook is not None:
                        runtime_hook_registration = new_hook
                    else:
                        return _admission(
                            operation,
                            LossExecutionEntryDecision.UNKNOWN,
                            LossExecutionAdmissionReason.MONEY_MANAGEMENT_UNKNOWN,
                            now,
                        )
                if (
                    not isinstance(
                        runtime_hook_registration,
                        MoneyManagementRuntimeHookRegistration,
                    )
                    or runtime_hook_registration.hook.last_dispatch_status
                    not in (
                        LossRuntimeDispatchStatus.APPLIED,
                        LossRuntimeDispatchStatus.IDEMPOTENT,
                    )
                ):
                    return _admission(
                        operation,
                        LossExecutionEntryDecision.UNKNOWN,
                        LossExecutionAdmissionReason.MONEY_MANAGEMENT_UNKNOWN,
                        now,
                    )
                projected = dispatch_money_management_governance_projection(
                    self._app,
                    self._projection_dispatcher,
                )
                public_snapshot = projected.public_snapshot
                expected_revision = public_snapshot.revision
                expected_sequence = public_snapshot.sequence
                request = LossExecutionGuardRequest(
                    operation,
                    now,
                    expected_revision,
                    expected_sequence,
                    self._maximum_projection_age,
                )
                result = dispatch_money_management_execution_entry_guard(
                    self._app,
                    self._guard_dispatcher,
                    request,
                )
            except Exception:
                return _admission(
                    operation,
                    LossExecutionEntryDecision.UNKNOWN,
                    LossExecutionAdmissionReason.MONEY_MANAGEMENT_UNKNOWN,
                    now,
                )
            if not isinstance(result, LossExecutionGuardResult):
                return _admission(
                    operation,
                    LossExecutionEntryDecision.UNKNOWN,
                    LossExecutionAdmissionReason.MONEY_MANAGEMENT_GUARD_INVALID,
                    now,
                )
            valid = (
                result.operation is operation
                and type(result.allowed) is bool
                and result.allowed
                == (result.decision is LossExecutionEntryDecision.ALLOW)
                and result.generated_at <= now
                and (
                    result.revision is None
                    and result.sequence is None
                    or (
                        type(result.revision) is int
                        and result.revision >= 1
                        and type(result.sequence) is int
                        and result.sequence >= 1
                    )
                )
                and (
                    expected_revision is None
                    or (
                        result.revision == expected_revision
                        and result.sequence == expected_sequence
                    )
                )
            )
            if result.allowed and (
                result.revision is None or result.sequence is None
            ):
                valid = False
            if not valid:
                return _admission(
                    operation,
                    LossExecutionEntryDecision.UNKNOWN,
                    LossExecutionAdmissionReason.MONEY_MANAGEMENT_GUARD_INVALID,
                    now,
                    result.revision,
                    result.sequence,
                )
            reason = {
                LossExecutionEntryDecision.ALLOW:
                    LossExecutionAdmissionReason.ENTRY_ALLOWED,
                LossExecutionEntryDecision.BLOCK:
                    LossExecutionAdmissionReason.MONEY_MANAGEMENT_BLOCKED,
                LossExecutionEntryDecision.RECOVERY_REQUIRED:
                    LossExecutionAdmissionReason.MONEY_MANAGEMENT_RECOVERY_REQUIRED,
                LossExecutionEntryDecision.UNKNOWN:
                    LossExecutionAdmissionReason.MONEY_MANAGEMENT_UNKNOWN,
            }[result.decision]
            return _admission(
                operation,
                result.decision,
                reason,
                result.generated_at,
                result.revision,
                result.sequence,
            )


@dataclass(frozen=True)
class MoneyManagementExecutionEntryGateRegistration:
    gate: MoneyManagementExecutionEntryGate
    bot_manager: object
    registered_at: datetime

    def __post_init__(self):
        if not isinstance(self.gate, MoneyManagementExecutionEntryGate):
            raise TypeError("entry gate required")
        object.__setattr__(
            self,
            "registered_at",
            _datetime("registered_at", self.registered_at),
        )


def register_money_management_execution_entry_gate(
    app,
    bot_manager_factory,
    timestamp_source=None,
):
    state = getattr(app, "state", None)
    existing = getattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    if isinstance(existing, MoneyManagementExecutionEntryGateRegistration):
        return existing
    if state is None or not callable(bot_manager_factory):
        return None
    try:
        bot_manager = bot_manager_factory()
        gate = MoneyManagementExecutionEntryGate(
            app,
            timestamp_source=timestamp_source,
        )
        installed = bot_manager.set_money_management_execution_entry_guard(
            gate.evaluate
        )
        if installed is not True:
            return None
        now = (
            timestamp_source()
            if timestamp_source is not None
            else datetime.now(timezone.utc)
        )
        registration = MoneyManagementExecutionEntryGateRegistration(
            gate,
            bot_manager,
            now,
        )
        setattr(state, APPLICATION_STATE_ATTRIBUTE, registration)
        return registration
    except Exception:
        return None


def _ensure_valid_runtime_hook(app):
    """Ensure a valid MoneyManagementRuntimeHookRegistration exists on app.state."""
    state = getattr(app, "state", None)
    if state is None:
        return None
    hook_registration = getattr(state, "money_management_runtime_hook", None)
    if (
        hook_registration is not None
        and isinstance(hook_registration, MoneyManagementRuntimeHookRegistration)
        and hook_registration.hook is not None
        and hook_registration.hook.last_dispatch_status
        in (
            LossRuntimeDispatchStatus.APPLIED,
            LossRuntimeDispatchStatus.IDEMPOTENT,
        )
    ):
        return hook_registration
    if isinstance(hook_registration, MoneyManagementRuntimeHookRegistration):
        refresh = getattr(hook_registration.hook, "refresh_authority", None)
        try:
            recovered = callable(refresh) and refresh() is True
        except Exception:
            recovered = False
        if recovered and hook_registration.hook.last_dispatch_status in (
            LossRuntimeDispatchStatus.APPLIED,
            LossRuntimeDispatchStatus.IDEMPOTENT,
        ):
            return hook_registration
        return None
    return register_money_management_runtime_hook(
        app,
        getattr(app, "bot_manager", None),
    )


def unregister_money_management_execution_entry_gate(app):
    state = getattr(app, "state", None)
    registration = getattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    if not isinstance(
        registration, MoneyManagementExecutionEntryGateRegistration
    ):
        return False
    try:
        registration.bot_manager.set_money_management_execution_entry_guard(
            None
        )
    except Exception:
        return False
    setattr(state, APPLICATION_STATE_ATTRIBUTE, None)
    return True
