"""Restart-safe anomaly state, deterministic fingerprint and cooldown policy.

Pure contracts only: no clock, no environment, no file/socket/database I/O, no
provider and no trading authority.  Every timestamp is supplied explicitly by
the caller, so serialization and transition decisions are reproducible.
"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from hashlib import sha256
from typing import Literal

from pydantic import Field, computed_field, field_validator, model_validator

from .drift_evaluator import DriftResult
from .monitoring_models import (
    Availability, Contract, Count, Dimension, Freshness, Severity, Token, aware,
)

SCHEMA_VERSION = "1"
FINGERPRINT_VERSION = "anomaly-fingerprint-v1"
COOLDOWN_POLICY_VERSION = "monitoring-cooldown-v1"
UNKNOWN_REVISION = "UNKNOWN"
MAX_OFFENDING_IDENTITY_CHARS = 4096

LifecycleState = Literal[
    "NEW", "ACTIVE", "ESCALATED", "SUPPRESSED", "ACKNOWLEDGED", "RESOLVED", "UNKNOWN",
]
Transition = Literal[
    "CREATED", "REPEATED", "ESCALATED", "SUPPRESSED", "ACKNOWLEDGED", "ACK_REPEAT",
    "RESOLVED", "RECURRED", "DEGRADED", "POLICY_REVISION", "SOURCE_REVISION",
    "NORMAL", "DUPLICATE", "CONFLICT", "NONE",
]
DegradedState = frozenset({"UNKNOWN", "STALE", "PARTIAL", "INSUFFICIENT_DATA"})
SEVERITY_RANK = {"NONE": 0, "INFO": 1, "WARNING": 2, "CRITICAL": 3}
NOTIFIABLE_SEVERITIES = frozenset({"WARNING", "CRITICAL"})
DATETIME_FIELDS = (
    "first_seen_at", "last_seen_at", "last_notified_at", "last_eligible_at",
    "cooldown_until", "acknowledged_at", "resolved_at", "consecutive_normal_since",
)


def normalize_text(value: str) -> str:
    """Canonical NFC + strip; the single normalization used by the fingerprint."""
    return unicodedata.normalize("NFC", value).strip()


_nfc = normalize_text


def _aware_optional(value):
    if value is None:
        return None
    return aware(value)


def severity_rank(severity: str) -> int:
    return SEVERITY_RANK[severity]


def is_degraded(result: DriftResult) -> bool:
    return result.state in DegradedState and result.severity == "NONE"


def schema_family(result: DriftResult) -> str:
    families = sorted({_nfc(p.source_schema) for p in result.provenance})
    return ":".join(families) if families else UNKNOWN_REVISION


def source_revision(result: DriftResult) -> str:
    revisions = sorted({_nfc(s.revision) for s in result.sources})
    return ":".join(revisions) if revisions else UNKNOWN_REVISION


def offending_identity(result: DriftResult) -> str | None:
    """A secret-free digest of the precise integrity offender, if any."""
    if result.metric not in ("source_corruption", "identity_contradiction"):
        return None
    refs = sorted(
        f"{_nfc(s.source)}|{_nfc(s.record_id)}|{_nfc(s.revision)}|{s.digest}" for s in result.sources
    )
    payload = "|".join(refs)[:MAX_OFFENDING_IDENTITY_CHARS]
    return sha256(payload.encode("utf-8")).hexdigest() if payload else None


class AnomalyIdentity(Contract):
    """Canonical, restart-stable anomaly identity (no timestamps or magnitudes)."""

    metric: Token
    metric_version: Token = "1"
    policy_version: Token
    category: Token
    schema_family: Token = UNKNOWN_REVISION
    grouping: tuple[Dimension, ...] = Field(default=(), max_length=16)
    offending_identity: Token | None = None

    @field_validator("grouping")
    @classmethod
    def groups(cls, value):
        normalized = {(_nfc(v.key), _nfc(v.value)) for v in value}
        if len(normalized) != len(value):
            raise ValueError("duplicate grouping key")
        return tuple(
            sorted((Dimension(key=k, value=v) for k, v in normalized), key=lambda d: d.key)
        )

    def _payload(self, *, include_policy: bool) -> dict:
        return {
            "fingerprint_version": FINGERPRINT_VERSION,
            "metric": _nfc(self.metric),
            "metric_version": _nfc(self.metric_version),
            "policy_version": _nfc(self.policy_version) if include_policy else None,
            "category": _nfc(self.category),
            "schema_family": _nfc(self.schema_family),
            "grouping": [[_nfc(d.key), _nfc(d.value)] for d in self.grouping],
            "offending_identity": _nfc(self.offending_identity) if self.offending_identity else None,
        }

    @computed_field
    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self._payload(include_policy=True), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)
        return sha256(payload.encode("utf-8")).hexdigest()

    @property
    def lineage(self) -> str:
        """Identity without the policy version, used only to detect a policy epoch change."""
        payload = json.dumps(self._payload(include_policy=False), sort_keys=True,
                             separators=(",", ":"), ensure_ascii=False)
        return sha256(payload.encode("utf-8")).hexdigest()

    @property
    def family(self) -> str:
        """Lineage without category, used to attach a degraded observation to its episode."""
        payload = self._payload(include_policy=False)
        payload["category"] = None
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return sha256(encoded.encode("utf-8")).hexdigest()


def build_identity(result: DriftResult, *, grouping=(), family: str | None = None) -> AnomalyIdentity:
    return AnomalyIdentity(
        metric=result.metric, metric_version=result.metric_version,
        policy_version=result.policy_version, category=result.category,
        schema_family=family if family is not None else schema_family(result),
        grouping=tuple(grouping), offending_identity=offending_identity(result),
    )


def observation_identity(result: DriftResult, identity: AnomalyIdentity) -> str:
    """Content identity of the physical observation, independent of evaluation replay."""
    payload = json.dumps({
        "identity": identity.canonical_digest(),
        "state": result.state,
        "severity": result.severity,
        "direction": result.direction,
        "current_window": result.current_window.stable_json() if result.current_window else None,
        "sources": [s.stable_json() for s in result.sources],
        "samples": [s.stable_json() for s in result.sample_size],
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(payload.encode("utf-8")).hexdigest()


class CooldownPolicy(Contract):
    """Explicit notification-eligibility policy.  Never affects trading authority."""

    policy_version: Token = COOLDOWN_POLICY_VERSION
    info_seconds: Count = 0
    warning_seconds: Count = 3600
    critical_seconds: Count = 900
    escalation_bypass: bool = True
    acknowledgement_suppression_seconds: Count = 86400
    resolution_consecutive_normal: int = Field(default=3, strict=True, ge=1, le=1000)
    resolution_span_seconds: Count = 120
    unknown_no_resolve: bool = True
    stale_no_resolve: bool = True
    partial_no_resolve: bool = True
    maximum_occurrences: Count = 10**9

    @model_validator(mode="after")
    def ordered(self):
        if self.critical_seconds > self.warning_seconds:
            raise ValueError("critical cooldown must not exceed warning cooldown")
        return self

    def seconds_for(self, severity: str) -> int:
        return {"INFO": self.info_seconds, "WARNING": self.warning_seconds,
                "CRITICAL": self.critical_seconds}.get(severity, 0)

    def suppresses_resolution(self, state: str) -> bool:
        return (state == "UNKNOWN" and self.unknown_no_resolve) or \
               (state == "STALE" and self.stale_no_resolve) or \
               (state == "PARTIAL" and self.partial_no_resolve) or \
               state == "INSUFFICIENT_DATA"


class Acknowledgement(Contract):
    """Explicit operator acknowledgement; no implicit user and no authentication."""

    fingerprint: Token
    acknowledged_at: datetime
    actor: Token
    expected_revision: Count | None = None
    expected_event_id: Token | None = None
    note: Token | None = None
    _aware = field_validator("acknowledged_at")(aware)

    @model_validator(mode="after")
    def revision(self):
        if self.expected_revision is None and self.expected_event_id is None:
            raise ValueError("acknowledgement requires expected_revision or expected_event_id")
        return self


class AnomalyState(Contract):
    """Validated, deterministic, restart-safe anomaly episode state."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    fingerprint: Token
    episode_key: Token
    family: Token
    episode_number: Count = 1
    state_revision: Count = 0
    metric: Token
    metric_version: Token = "1"
    grouping: tuple[Dimension, ...] = Field(default=(), max_length=16)
    policy_version: Token
    source_revision: Token = UNKNOWN_REVISION
    category: Token
    lifecycle_state: LifecycleState
    current_severity: Severity
    highest_severity: Severity
    escalation_version: Count = 0
    first_seen_at: datetime
    last_seen_at: datetime
    occurrence_count: Count
    consecutive_count: Count = 0
    consecutive_normal_count: Count = 0
    consecutive_normal_since: datetime | None = None
    last_evaluation_id: Token
    last_observation_id: Token
    last_content_digest: Token
    last_event_id: Token | None = None
    last_notified_at: datetime | None = None
    last_eligible_at: datetime | None = None
    cooldown_until: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: Token | None = None
    resolved_at: datetime | None = None
    resolution_reason: Token | None = None
    active: bool
    partial_result: bool = False
    freshness: Freshness = "UNKNOWN"
    availability: Availability = "UNAVAILABLE"
    reason_codes: tuple[Token, ...] = ()

    _aware = field_validator(*DATETIME_FIELDS)(_aware_optional)

    @field_validator("grouping")
    @classmethod
    def groups(cls, value):
        if len({v.key for v in value}) != len(value):
            raise ValueError("duplicate grouping key")
        return tuple(sorted(value, key=lambda d: d.key))

    @field_validator("reason_codes")
    @classmethod
    def reasons(cls, value):
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def coherent(self):
        if severity_rank(self.highest_severity) < severity_rank(self.current_severity):
            raise ValueError("current severity exceeds highest severity")
        if self.occurrence_count < 1:
            raise ValueError("occurrence count must be positive")
        if self.consecutive_count > self.occurrence_count:
            raise ValueError("consecutive count exceeds occurrence count")
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("last_seen precedes first_seen")
        if (self.acknowledged_at is None) != (self.acknowledged_by is None):
            raise ValueError("acknowledged_at and acknowledged_by must be set together")
        for stamp in (self.acknowledged_at, self.resolved_at):
            if stamp is not None and stamp < self.first_seen_at:
                raise ValueError("acknowledged/resolved timestamp precedes first_seen")
        if self.lifecycle_state == "RESOLVED":
            if self.active:
                raise ValueError("resolved state cannot remain active")
            if self.resolved_at is None or self.resolution_reason is None:
                raise ValueError("resolved state requires timestamp and reason")
        else:
            if not self.active:
                raise ValueError("only a resolved state may be inactive")
            if self.resolved_at is not None or self.resolution_reason is not None:
                raise ValueError("active state cannot carry resolution")
        if self.lifecycle_state == "NEW" and (self.occurrence_count != 1 or self.episode_number != 1):
            raise ValueError("NEW lifecycle requires first occurrence of the first episode")
        if self.lifecycle_state == "ESCALATED" and self.escalation_version < 1:
            raise ValueError("ESCALATED lifecycle requires an escalation version")
        if self.lifecycle_state == "ACKNOWLEDGED" and self.acknowledged_at is None:
            raise ValueError("ACKNOWLEDGED lifecycle requires acknowledgement")
        if self.lifecycle_state == "UNKNOWN" and not self.reason_codes:
            raise ValueError("UNKNOWN lifecycle requires explicit quality reasons")
        return self

    @property
    def is_normal(self) -> bool:
        """UNKNOWN is never normal; a state is never silently treated as NORMAL."""
        return False

    @property
    def notifiable(self) -> bool:
        return self.active and self.current_severity in NOTIFIABLE_SEVERITIES and \
            self.lifecycle_state not in ("RESOLVED", "UNKNOWN")


class StateEvent(Contract):
    """One append-only journal record carrying the resulting state snapshot."""

    schema_version: Literal["1"] = SCHEMA_VERSION
    occurred_at: datetime
    fingerprint: Token
    episode_number: Count
    evaluation_id: Token
    observation_id: Token
    transition: Transition
    notification_eligible: bool
    suppression_reason: Token | None = None
    reason_codes: tuple[Token, ...] = ()
    state: AnomalyState
    _aware = field_validator("occurred_at")(aware)

    @field_validator("reason_codes")
    @classmethod
    def reasons(cls, value):
        return tuple(sorted(set(value)))

    @computed_field
    @property
    def event_id(self) -> str:
        payload = json.dumps({
            "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.isoformat(),
            "fingerprint": self.fingerprint,
            "episode_number": self.episode_number,
            "evaluation_id": self.evaluation_id,
            "transition": self.transition,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return sha256(payload.encode("utf-8")).hexdigest()

    def content_digest(self) -> str:
        return self.canonical_digest()


class TransitionResult(Contract):
    fingerprint: Token
    episode_key: Token
    transition: Transition
    previous: AnomalyState | None = None
    state: AnomalyState | None = None
    notification_eligible: bool = False
    suppression_reason: Token | None = None
    reason_codes: tuple[Token, ...] = ()
    persistence_required: bool = False
    conflict: bool = False
    duplicate: bool = False

    @field_validator("reason_codes")
    @classmethod
    def reasons(cls, value):
        return tuple(sorted(set(value)))


class Suppression(Contract):
    fingerprint: Token
    severity: Severity
    reason: Token


class CorruptRecord(Contract):
    position: Count
    reason: Token


class RecoveryResult(Contract):
    states: tuple[AnomalyState, ...] = ()
    event_ids: tuple[Token, ...] = ()
    records_read: Count = 0
    bytes_read: Count = 0
    corruption_count: Count = 0
    duplicate_events: Count = 0
    partial: bool = False
    exists: bool = False
    warnings: tuple[Token, ...] = ()
    corrupted: tuple[CorruptRecord, ...] = ()

    @field_validator("warnings", "event_ids")
    @classmethod
    def ordered(cls, value):
        return tuple(sorted(set(value)))


class MonitoringCycleResult(Contract):
    states: tuple[AnomalyState, ...] = ()
    transitions: tuple[TransitionResult, ...] = ()
    eligible_for_notification: tuple[Token, ...] = ()
    suppressed: tuple[Suppression, ...] = ()
    events: tuple[StateEvent, ...] = ()
    warnings: tuple[Token, ...] = ()
    recovery: RecoveryResult | None = None

    @field_validator("eligible_for_notification", "warnings")
    @classmethod
    def ordered(cls, value):
        return tuple(sorted(set(value)))
