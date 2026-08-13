"""Explicit domain ownership and deterministic authority conflict detection."""

from datetime import datetime

from .contracts import SnapshotWarning
from .failure_codes import SupervisorFailureCode


DOMAIN_AUTHORITY = (
    ("bot", "BOT_MANAGER_STATUS"),
    ("loop", "BOT_MANAGER_STATUS"),
    ("trade", "BOT_MANAGER_STATUS"),
    ("governance", "GOVERNANCE_RUNTIME"),
    ("emergency", "GOVERNANCE_RUNTIME"),
    ("execution", "BOT_MANAGER_STATUS"),
    ("market", "BOT_MANAGER_STATUS"),
    ("decision", "BOT_MANAGER_STATUS"),
    ("health", "BACKEND_HEALTH_PRODUCER"),
    ("moneyManagement", "MONEY_MANAGEMENT_HTTP_BOUNDARY"),
)

CRITICAL_DOMAINS = ("governance", "emergency", "moneyManagement", "health")


def warning(
    code: SupervisorFailureCode,
    domain: str,
    field: str,
    message: str,
    source_evaluated_at: datetime | None,
) -> SnapshotWarning:
    return SnapshotWarning(
        code=code,
        domain=domain,
        field=field,
        message=message,
        sourceEvaluatedAt=source_evaluated_at,
    )


def values_conflict(owner_value: object, secondary_value: object) -> bool:
    """Null/absent secondary evidence does not invent a conflict."""
    return owner_value is not None and secondary_value is not None and owner_value != secondary_value


def deduplicate_warnings(values: list[SnapshotWarning]) -> tuple[SnapshotWarning, ...]:
    unique = {
        (item.code.value, item.domain, item.field, item.message,
         item.sourceEvaluatedAt.isoformat() if item.sourceEvaluatedAt else ""): item
        for item in values
    }
    return tuple(unique[key] for key in sorted(unique))
