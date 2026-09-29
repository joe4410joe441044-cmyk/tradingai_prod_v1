"""Bounded, restart-safe alert outbox models for Supervisor anomaly events.

These models are observational metadata only.  They never carry trading
authority, never trigger delivery and never modify trading/MM/Governance state.
Delivery status is deliberately limited to ``PENDING``/``NOT_CONFIGURED``: this
task implements an internal durable outbox/read model only, with no transport.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from .monitoring_models import Availability, Contract, Count, Freshness, Token, aware

ALERT_SCHEMA_VERSION = "supervisor-monitoring-alert-v1"
ALERT_FINGERPRINT_VERSION = "supervisor-alert-fingerprint-v1"

AlertSeverity = Literal["INFO", "WARNING", "CRITICAL"]
AlertStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED"]
AlertDeliveryStatus = Literal["PENDING", "NOT_CONFIGURED", "DELIVERED", "FAILED"]

SEVERITY_RANK = {"NONE": 0, "INFO": 1, "WARNING": 2, "CRITICAL": 3}

# Proposed cooldown (design V1): WARNING 60 min, CRITICAL 15 min, INFO none.
COOLDOWN_SECONDS = {"INFO": 0, "WARNING": 3600, "CRITICAL": 900}

MAX_REASON_CODES = 32
MAX_PROVENANCE = 32
MAX_ALERT_PAGE = 100


class AlertCandidate(Contract):
    """A bounded anomaly observation proposed for outbox ingestion.

    Derived from a Phase 2 anomaly state/fingerprint; this is not a second
    anomaly-state authority and stores no raw evidence.
    """

    anomaly_fingerprint: Token
    episode_number: Count = 1
    severity: AlertSeverity
    category: Token
    metric: Token
    metric_version: Token = "1"
    policy_version: Token = "supervisor-monitoring-v1"
    scope: Token = "DEFAULT"
    mode: Token = "UNKNOWN"
    symbol: Token | None = None
    observation_id: Token | None = None
    source_revision: Token | None = None
    reason_codes: tuple[Token, ...] = Field(default=(), max_length=MAX_REASON_CODES)
    provenance: tuple[Token, ...] = Field(default=(), max_length=MAX_PROVENANCE)
    freshness: Freshness = "UNKNOWN"
    availability: Availability = "NOT_CAPTURED"
    partial_result: bool = False
    occurred_at: datetime

    _aware = field_validator("occurred_at")(aware)

    @field_validator("reason_codes", "provenance")
    @classmethod
    def _ordered(cls, value):
        return tuple(sorted(set(value)))


class AlertRecord(Contract):
    """Bounded durable alert episode.  Sanitized; no raw evidence or secrets."""

    schema_version: Token = ALERT_SCHEMA_VERSION
    alert_id: Token
    anomaly_fingerprint: Token
    fingerprint_version: Token = ALERT_FINGERPRINT_VERSION
    episode_number: Count
    status: AlertStatus = "OPEN"
    delivery_status: AlertDeliveryStatus = "NOT_CONFIGURED"
    current_severity: AlertSeverity
    highest_severity: AlertSeverity
    category: Token
    metric: Token
    metric_version: Token
    policy_version: Token
    scope: Token
    mode: Token
    symbol: Token | None = None
    observation_id: Token | None = None
    source_revision: Token | None = None
    reason_codes: tuple[Token, ...] = Field(default=(), max_length=MAX_REASON_CODES)
    provenance: tuple[Token, ...] = Field(default=(), max_length=MAX_PROVENANCE)
    freshness: Freshness = "UNKNOWN"
    availability: Availability = "NOT_CAPTURED"
    partial_result: bool = False
    occurrence_count: Count = 1
    first_seen_at: datetime
    last_seen_at: datetime
    cooldown_until: datetime | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None

    _aware = field_validator(
        "first_seen_at", "last_seen_at", "cooldown_until", "acknowledged_at", "resolved_at"
    )(lambda value: None if value is None else aware(value))

    @field_validator("reason_codes", "provenance")
    @classmethod
    def _ordered(cls, value):
        return tuple(sorted(set(value)))


class AlertPage(Contract):
    alerts: tuple[AlertRecord, ...]
    next_cursor: Token | None = None
    order: Literal["NEWEST_FIRST"] = "NEWEST_FIRST"
    corruption_count: Count = 0
    partial_result: bool = False


AlertIngestDecision = Literal[
    "CREATED", "UPDATED", "SUPPRESSED_COOLDOWN", "SUPPRESSED_ACKNOWLEDGED",
    "SUPPRESSED_RESOLVED", "DISABLED", "INVALID",
]


class AlertIngestResult(Contract):
    alert_id: Token | None = None
    decision: AlertIngestDecision
    reason_code: Token
    created_count: Count = 0
    updated_count: Count = 0
    suppressed_count: Count = 0
    delivery_status: AlertDeliveryStatus = "NOT_CONFIGURED"


__all__ = [
    "ALERT_FINGERPRINT_VERSION",
    "ALERT_SCHEMA_VERSION",
    "AlertCandidate",
    "AlertDeliveryStatus",
    "AlertIngestDecision",
    "AlertIngestResult",
    "AlertPage",
    "AlertRecord",
    "AlertSeverity",
    "AlertStatus",
    "COOLDOWN_SECONDS",
    "MAX_ALERT_PAGE",
    "SEVERITY_RANK",
]
