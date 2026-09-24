"""Canonical Cycle Evidence Envelope foundation (WORK I P0).

This module is the implementation of the
``WORK_I_CANONICAL_KNOWLEDGE_EVIDENCE_CONTRACT_V1`` canonical evidence
envelope.  It is deliberately observational:

- it never participates in an execution, close, sizing, MM, Governance,
  market-selection or parameter-promotion decision;
- it never writes to any existing canonical store (Stage 13, trading trace,
  parameter revision archive, MM timeline, supervisor SQLite);
- it never invents a value to fill a gap: every absent identifier/value is
  represented through the explicit availability semantics (contract § F);
- it preserves links to the existing canonical records by id rather than
  re-implementing any existing authority (contract § C / § I.8).

The envelope is a shared PAPER/LIVE schema (contract § H).  Persistence for
the envelope lives in :mod:`backend.runtime.cycle_evidence_store`; link
adapters over the existing stores live in
:mod:`backend.runtime.cycle_evidence_links`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, IntEnum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Optional

ENVELOPE_SCHEMA_VERSION = "evidence-envelope/v1"
DEFAULT_AUTHORITY = "RECORDING_AUTHORITY"
DEFAULT_TRUTH_LEVEL = "CURRENT_SOURCE_RUNTIME"
SECRET_REDACTION_RULE = "SECRET_FIELD_SCRUB_V1"

# Bounded payloads (contract § D "bounded, redacted body").
MAX_PAYLOAD_BYTES = 65536
MAX_NESTING_DEPTH = 8
MAX_SEQUENCE_LENGTH = 100

_SECRET_KEY = re.compile(
    r"("
    r"api[_-]?key|apikey|secret|passphrase|password|passwd|"
    r"authorization|bearer|credential|token|"
    r"private[_-]?key|access[_-]?key|"
    r"signed[_-]?request|session[_-]?id|cookie"
    r")",
    re.IGNORECASE,
)


class LifecycleStage(IntEnum):
    """The fifteen canonical lifecycle stages (contract § E, 0–14)."""

    PARAMETER_CONTEXT = 0
    MARKET_SELECTION = 1
    MARKET_DATA = 2
    FEATURE_BUILDER = 3
    MICRO_EDGE_STRATEGY = 4
    AI_DECISION_REVIEW = 5
    MONEY_MANAGEMENT = 6
    GOVERNANCE = 7
    EXECUTION = 8
    POSITION = 9
    EXIT_MONITORING = 10
    SETTLEMENT_EXIT_EXECUTION = 11
    POSITION_CLOSED = 12
    TRADE_PARAMETER_PERFORMANCE = 13
    READY_FOR_NEXT_TRADE = 14


LIFECYCLE_STAGE_NAMES = {int(stage): stage.name for stage in LifecycleStage}
LIFECYCLE_STAGES = tuple(int(stage) for stage in LifecycleStage)


class EvidenceType(str, Enum):
    """Closed domain evidence-type vocabulary (contract § G)."""

    PARAMETER_CONTEXT = "PARAMETER_CONTEXT"
    PARAMETER_REVISION = "PARAMETER_REVISION"
    AUTO_CANDIDATE_SELECTION = "AUTO_CANDIDATE_SELECTION"
    MARKET_CONTEXT = "MARKET_CONTEXT"
    FEATURE_EVIDENCE = "FEATURE_EVIDENCE"
    STRATEGY_SIGNAL = "STRATEGY_SIGNAL"
    AI_DECISION = "AI_DECISION"
    MONEY_MANAGEMENT_DECISION = "MONEY_MANAGEMENT_DECISION"
    GOVERNANCE_DECISION = "GOVERNANCE_DECISION"
    INTENDED_ORDER = "INTENDED_ORDER"
    NORMALIZED_ORDER = "NORMALIZED_ORDER"
    EXCHANGE_REQUEST = "EXCHANGE_REQUEST"
    EXCHANGE_ACK = "EXCHANGE_ACK"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL = "FILL"
    REJECT = "REJECT"
    FEE = "FEE"
    SLIPPAGE = "SLIPPAGE"
    LATENCY = "LATENCY"
    POSITION = "POSITION"
    EXIT_DECISION = "EXIT_DECISION"
    CLOSE_REQUEST = "CLOSE_REQUEST"
    CLOSE_FILL = "CLOSE_FILL"
    GROSS_NET_PNL = "GROSS_NET_PNL"
    RECONCILIATION = "RECONCILIATION"
    FINAL_EXCHANGE_STATE = "FINAL_EXCHANGE_STATE"
    TRADE_PERFORMANCE = "TRADE_PERFORMANCE"
    CYCLE_READINESS = "CYCLE_READINESS"
    PROVENANCE = "PROVENANCE"


DEFAULT_STAGE_BY_EVIDENCE_TYPE = {
    EvidenceType.PARAMETER_CONTEXT: LifecycleStage.PARAMETER_CONTEXT,
    EvidenceType.PARAMETER_REVISION: LifecycleStage.PARAMETER_CONTEXT,
    EvidenceType.AUTO_CANDIDATE_SELECTION: LifecycleStage.MARKET_SELECTION,
    EvidenceType.MARKET_CONTEXT: LifecycleStage.MARKET_DATA,
    EvidenceType.FEATURE_EVIDENCE: LifecycleStage.FEATURE_BUILDER,
    EvidenceType.STRATEGY_SIGNAL: LifecycleStage.MICRO_EDGE_STRATEGY,
    EvidenceType.AI_DECISION: LifecycleStage.AI_DECISION_REVIEW,
    EvidenceType.MONEY_MANAGEMENT_DECISION: LifecycleStage.MONEY_MANAGEMENT,
    EvidenceType.GOVERNANCE_DECISION: LifecycleStage.GOVERNANCE,
    EvidenceType.INTENDED_ORDER: LifecycleStage.EXECUTION,
    EvidenceType.NORMALIZED_ORDER: LifecycleStage.EXECUTION,
    EvidenceType.EXCHANGE_REQUEST: LifecycleStage.EXECUTION,
    EvidenceType.EXCHANGE_ACK: LifecycleStage.EXECUTION,
    EvidenceType.PARTIAL_FILL: LifecycleStage.EXECUTION,
    EvidenceType.FILL: LifecycleStage.EXECUTION,
    EvidenceType.REJECT: LifecycleStage.EXECUTION,
    EvidenceType.FEE: LifecycleStage.EXECUTION,
    EvidenceType.SLIPPAGE: LifecycleStage.EXECUTION,
    EvidenceType.LATENCY: LifecycleStage.EXECUTION,
    EvidenceType.POSITION: LifecycleStage.POSITION,
    EvidenceType.EXIT_DECISION: LifecycleStage.EXIT_MONITORING,
    EvidenceType.CLOSE_REQUEST: LifecycleStage.SETTLEMENT_EXIT_EXECUTION,
    EvidenceType.CLOSE_FILL: LifecycleStage.SETTLEMENT_EXIT_EXECUTION,
    EvidenceType.FINAL_EXCHANGE_STATE: LifecycleStage.POSITION_CLOSED,
    EvidenceType.GROSS_NET_PNL: LifecycleStage.TRADE_PARAMETER_PERFORMANCE,
    EvidenceType.TRADE_PERFORMANCE: LifecycleStage.TRADE_PARAMETER_PERFORMANCE,
    EvidenceType.CYCLE_READINESS: LifecycleStage.READY_FOR_NEXT_TRADE,
}


class EvidenceMode(str, Enum):
    """Shared PAPER/LIVE mode (contract § H)."""

    PAPER = "PAPER"
    LIVE = "LIVE"


class AuthorityClass(str, Enum):
    """Authority classes the envelope may *describe* (contract § A)."""

    OBSERVATION_READ_ONLY = "OBSERVATION_READ_ONLY"
    RECORDING_AUTHORITY = "RECORDING_AUTHORITY"
    RESEARCH_READ_ONLY = "RESEARCH_READ_ONLY"
    CONFIGURATION_AUTHORITY = "CONFIGURATION_AUTHORITY"
    MONEY_MANAGEMENT_AUTHORITY = "MONEY_MANAGEMENT_AUTHORITY"
    GOVERNANCE_AUTHORITY = "GOVERNANCE_AUTHORITY"
    EXECUTION_AUTHORITY = "EXECUTION_AUTHORITY"


class TruthLevel(str, Enum):
    """Truth hierarchy (never inverted) reused from the contract."""

    CANONICAL_SPECIFICATION = "CANONICAL_SPECIFICATION"
    CURRENT_SOURCE_RUNTIME = "CURRENT_SOURCE_RUNTIME"
    VALIDATED_KNOWLEDGE = "VALIDATED_KNOWLEDGE"
    OBSERVATION_FINDING = "OBSERVATION_FINDING"
    HYPOTHESIS = "HYPOTHESIS"


class AvailabilityState(str, Enum):
    """Explicit availability states (contract § F)."""

    VALUE_PRESENT = "VALUE_PRESENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_CAPTURED = "NOT_CAPTURED"
    CAPTURE_FAILED = "CAPTURE_FAILED"
    REDACTED = "REDACTED"
    UNKNOWN = "UNKNOWN"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"


class SecretPolicy(str, Enum):
    """What to do when a secret-like field is detected."""

    REDACT = "REDACT"
    REJECT = "REJECT"


# The nullable / identifier fields that MUST carry an explicit availability
# state.  ``event_id``, ``evidence_id`` and ``recorded_at`` are always present
# and are therefore not availability-tracked.
AVAILABILITY_TRACKED_FIELDS = (
    "symbol",
    "timeframe",
    "occurred_at",
    "cycle_id",
    "trade_id",
    "correlation_id",
    "parent_event_id",
    "configuration_revision_id",
    "parameter_revision_id",
    "source_record_id",
    "task_id",
    "acceptance_id",
    "commit_sha",
)

# Fields that participate in the deterministic logical identity of an
# envelope.  ``payload`` is intentionally excluded so that conflicting content
# under the same identity is detected (contract § I.3).
_IDENTITY_FIELDS = (
    "schema_version",
    "evidence_type",
    "lifecycle_stage",
    "mode",
    "symbol",
    "timeframe",
    "occurred_at",
    "correlation_id",
    "cycle_id",
    "trade_id",
    "configuration_revision_id",
    "parameter_revision_id",
    "source_record_id",
    "parent_event_id",
    "task_id",
    "acceptance_id",
    "commit_sha",
)

_LINK_KEYS = frozenset(
    {
        "parentEventId",
        "sourceRecordId",
        "traceId",
        "decisionId",
        "observationId",
        "runtimeId",
        "orderId",
        "exchangeOrderId",
        "fillId",
        "positionId",
        "tradeId",
        "cycleId",
        "correlationId",
        "configurationRevisionId",
        "parameterRevisionId",
        "taskId",
        "acceptanceId",
        "commitSha",
    }
)


def is_known_link_key(key: Any) -> bool:
    """Return whether ``key`` is a declared canonical link key."""

    return isinstance(key, str) and key in _LINK_KEYS


class CycleEvidenceError(Exception):
    """Base error for the canonical cycle evidence foundation."""


class EnvelopeValidationError(CycleEvidenceError, ValueError):
    """The envelope violates the canonical schema or invariants."""


class SecretFieldError(CycleEvidenceError, ValueError):
    """A secret-like field was present and the policy forbids redaction."""


class IntegrityError(CycleEvidenceError, ValueError):
    """The stored integrity digest does not match the envelope body."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_timestamp(value: Any, field_name: str) -> Optional[str]:
    """Normalize a timestamp to deterministic ISO-8601 UTC, or ``None``."""

    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EnvelopeValidationError(
                f"{field_name} is not a valid ISO-8601 timestamp"
            ) from exc
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        moment = datetime.fromtimestamp(float(value), timezone.utc)
    else:
        raise EnvelopeValidationError(
            f"{field_name} must be an ISO-8601 string, datetime or epoch number"
        )
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonical_json(value: Any) -> str:
    """Deterministic JSON encoding used for hashing and serialization."""

    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, separators=(",", ":")
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_fingerprint(value: Any) -> str:
    """Return the SHA-256 hex digest of the canonical JSON of ``value``."""

    return _sha256_hex(canonical_json(value))


def _redact(value: Any, path: str, depth: int = 0, redacted: Optional[list] = None):
    """Return ``(cleaned, redacted_paths)`` dropping secret-like mapping keys."""

    if redacted is None:
        redacted = []
    if depth > MAX_NESTING_DEPTH:
        return "[TRUNCATED]", redacted
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _SECRET_KEY.search(key_text):
                redacted.append(child_path)
                continue
            child, _ = _redact(value[key], child_path, depth + 1, redacted)
            cleaned[key_text] = child
        return cleaned, redacted
    if isinstance(value, (list, tuple)):
        cleaned_list = []
        for index, item in enumerate(value[:MAX_SEQUENCE_LENGTH]):
            child, _ = _redact(item, f"{path}[{index}]", depth + 1, redacted)
            cleaned_list.append(child)
        return cleaned_list, redacted
    if value is None or isinstance(value, (str, int, float, bool)):
        return value, redacted
    return str(value), redacted


def normalize_availability_entry(entry: Any) -> Any:
    """Normalize an availability entry to a state string or a state dict."""

    if isinstance(entry, AvailabilityState):
        return entry.value
    if isinstance(entry, str):
        state = entry.strip().upper()
        if state not in {member.value for member in AvailabilityState}:
            raise EnvelopeValidationError(f"unknown availability state: {entry!r}")
        return state
    if isinstance(entry, Mapping):
        state = entry.get("state")
        normalized_state = normalize_availability_entry(state)
        detail = entry.get("detail")
        output = {"state": normalized_state}
        if detail is not None:
            output["detail"] = str(detail)
        return output
    raise EnvelopeValidationError(f"invalid availability entry: {entry!r}")


def availability_state(entry: Any) -> Optional[str]:
    """Return the state portion of an availability entry."""

    if isinstance(entry, str):
        return entry
    if isinstance(entry, Mapping):
        state = entry.get("state")
        return state if isinstance(state, str) else None
    return None


def availability_detail(entry: Any) -> Optional[str]:
    """Return the detail/reason portion of an availability entry."""

    if isinstance(entry, Mapping):
        detail = entry.get("detail")
        return str(detail) if detail is not None else None
    return None


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Immutable canonical evidence envelope (contract § D)."""

    schema_version: str
    evidence_type: str
    lifecycle_stage: int
    mode: str
    event_id: str
    evidence_id: str
    recorded_at: str
    authority: str
    source: Mapping[str, Any]
    payload: Mapping[str, Any]
    provenance: Mapping[str, Any]
    integrity: Mapping[str, Any]
    availability: Mapping[str, Any]
    redaction: Mapping[str, Any]
    links: Mapping[str, Any] = field(default_factory=dict)
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    occurred_at: Optional[str] = None
    cycle_id: Optional[str] = None
    trade_id: Optional[str] = None
    correlation_id: Optional[str] = None
    parent_event_id: Optional[str] = None
    configuration_revision_id: Optional[str] = None
    parameter_revision_id: Optional[str] = None
    source_record_id: Optional[str] = None
    task_id: Optional[str] = None
    acceptance_id: Optional[str] = None
    commit_sha: Optional[str] = None

    def __post_init__(self) -> None:
        self._validate()

    # -- validation ---------------------------------------------------------

    def _validate(self) -> None:
        if self.schema_version != ENVELOPE_SCHEMA_VERSION:
            raise EnvelopeValidationError(
                f"unsupported schema_version {self.schema_version!r}"
            )
        try:
            EvidenceType(self.evidence_type)
        except ValueError as exc:
            raise EnvelopeValidationError(
                f"unknown evidence_type: {self.evidence_type!r}"
            ) from exc
        if (
            isinstance(self.lifecycle_stage, bool)
            or not isinstance(self.lifecycle_stage, int)
            or int(self.lifecycle_stage) not in LIFECYCLE_STAGES
        ):
            raise EnvelopeValidationError(
                f"lifecycle_stage must be one of 0..14, got {self.lifecycle_stage!r}"
            )
        try:
            EvidenceMode(self.mode)
        except ValueError as exc:
            raise EnvelopeValidationError(
                f"mode must be PAPER or LIVE, got {self.mode!r}"
            ) from exc
        for field_name in ("event_id", "evidence_id", "recorded_at"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value:
                raise EnvelopeValidationError(f"{field_name} must be a non-empty string")
        normalize_timestamp(self.recorded_at, "recorded_at")
        if self.occurred_at is not None:
            normalize_timestamp(self.occurred_at, "occurred_at")
        try:
            AuthorityClass(self.authority)
        except ValueError as exc:
            raise EnvelopeValidationError(
                f"unknown authority: {self.authority!r}"
            ) from exc
        if not isinstance(self.source, Mapping) or not self.source:
            raise EnvelopeValidationError("source must be a non-empty mapping")
        if not isinstance(self.source.get("subsystem"), str) or not self.source.get(
            "subsystem"
        ):
            raise EnvelopeValidationError(
                "source.subsystem must be a non-empty string"
            )
        for field_name in ("payload", "provenance", "integrity", "availability", "redaction", "links"):
            if not isinstance(getattr(self, field_name), Mapping):
                raise EnvelopeValidationError(f"{field_name} must be a mapping")
        for identifier in (
            "cycle_id",
            "trade_id",
            "correlation_id",
            "parent_event_id",
            "configuration_revision_id",
            "parameter_revision_id",
            "source_record_id",
            "task_id",
            "acceptance_id",
            "commit_sha",
        ):
            value = getattr(self, identifier)
            if value is not None and (not isinstance(value, str) or not value):
                raise EnvelopeValidationError(
                    f"{identifier} must be a non-empty string or None"
                )
        for text_field in ("symbol", "timeframe"):
            value = getattr(self, text_field)
            if value is not None and (not isinstance(value, str) or not value):
                raise EnvelopeValidationError(
                    f"{text_field} must be a non-empty string or None"
                )
        for key, value in self.links.items():
            if not isinstance(key, str) or not key:
                raise EnvelopeValidationError("links keys must be non-empty strings")
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise EnvelopeValidationError(
                    f"links.{key} must be a scalar or None"
                )
        self._validate_availability()
        self._validate_integrity()

    def _validate_availability(self) -> None:
        for field_name in AVAILABILITY_TRACKED_FIELDS:
            value = getattr(self, field_name)
            entry = self.availability.get(field_name)
            state = availability_state(entry)
            if value is not None:
                if state is not None and state != AvailabilityState.VALUE_PRESENT.value:
                    raise EnvelopeValidationError(
                        f"{field_name} has a value but availability is {state}"
                    )
                continue
            if entry is None:
                raise EnvelopeValidationError(
                    f"{field_name} is absent and has no explicit availability state"
                )
            if state is None:
                raise EnvelopeValidationError(
                    f"{field_name} has an unreadable availability entry"
                )
            if state == AvailabilityState.VALUE_PRESENT.value:
                raise EnvelopeValidationError(
                    f"{field_name} is absent but availability is VALUE_PRESENT"
                )
            if (
                state == AvailabilityState.CAPTURE_FAILED.value
                and not availability_detail(entry)
            ):
                raise EnvelopeValidationError(
                    f"{field_name} CAPTURE_FAILED requires a detail reason"
                )

    def _validate_integrity(self) -> None:
        algorithm = self.integrity.get("algorithm")
        digest = self.integrity.get("digest")
        if algorithm != "sha256" or not isinstance(digest, str) or not digest:
            raise EnvelopeValidationError(
                "integrity must declare algorithm=sha256 and a digest"
            )
        if digest != self.content_digest():
            raise IntegrityError("envelope integrity digest mismatch")

    # -- canonical bodies / digests ----------------------------------------

    def body(self, *, include_recorded_at: bool = True, include_integrity: bool = False) -> dict:
        data = _compose_body(
            schema_version=self.schema_version,
            evidence_type=self.evidence_type,
            lifecycle_stage=int(self.lifecycle_stage),
            mode=self.mode,
            symbol=self.symbol,
            timeframe=self.timeframe,
            occurred_at=self.occurred_at,
            recorded_at=self.recorded_at,
            cycle_id=self.cycle_id,
            trade_id=self.trade_id,
            event_id=self.event_id,
            evidence_id=self.evidence_id,
            correlation_id=self.correlation_id,
            parent_event_id=self.parent_event_id,
            configuration_revision_id=self.configuration_revision_id,
            parameter_revision_id=self.parameter_revision_id,
            source_record_id=self.source_record_id,
            task_id=self.task_id,
            acceptance_id=self.acceptance_id,
            commit_sha=self.commit_sha,
            authority=self.authority,
            source=self.source,
            payload=self.payload,
            provenance=self.provenance,
            availability=self.availability,
            redaction=self.redaction,
            links=self.links,
            include_recorded_at=include_recorded_at,
        )
        if include_integrity:
            data["integrity"] = dict(self.integrity)
        return data

    def content_digest(self) -> str:
        """SHA-256 over the canonical body (excluding the integrity field)."""

        return _sha256_hex(canonical_json(self.body()))

    def logical_digest(self) -> str:
        """Digest of the logical content, independent of write time/integrity."""

        return _sha256_hex(canonical_json(self.body(include_recorded_at=False)))

    def identity(self) -> dict:
        """Deterministic logical identity (payload excluded)."""

        return {name: self.body().get(name) for name in _IDENTITY_FIELDS}

    def to_dict(self) -> dict:
        return self.body(include_integrity=True)

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceEnvelope":
        if not isinstance(data, Mapping):
            raise EnvelopeValidationError("envelope must be a mapping")
        required = (
            "schema_version",
            "evidence_type",
            "lifecycle_stage",
            "mode",
            "event_id",
            "evidence_id",
            "recorded_at",
            "authority",
            "source",
            "payload",
            "provenance",
            "integrity",
            "availability",
            "redaction",
        )
        missing = [name for name in required if name not in data]
        if missing:
            raise EnvelopeValidationError(
                "missing required envelope fields: " + ", ".join(missing)
            )
        return cls(
            schema_version=data["schema_version"],
            evidence_type=data["evidence_type"],
            lifecycle_stage=data["lifecycle_stage"],
            mode=data["mode"],
            event_id=data["event_id"],
            evidence_id=data["evidence_id"],
            recorded_at=data["recorded_at"],
            authority=data["authority"],
            source=dict(data["source"]),
            payload=dict(data["payload"]),
            provenance=dict(data["provenance"]),
            integrity=dict(data["integrity"]),
            availability=dict(data["availability"]),
            redaction=dict(data["redaction"]),
            links=dict(data.get("links") or {}),
            symbol=data.get("symbol"),
            timeframe=data.get("timeframe"),
            occurred_at=data.get("occurred_at"),
            cycle_id=data.get("cycle_id"),
            trade_id=data.get("trade_id"),
            correlation_id=data.get("correlation_id"),
            parent_event_id=data.get("parent_event_id"),
            configuration_revision_id=data.get("configuration_revision_id"),
            parameter_revision_id=data.get("parameter_revision_id"),
            source_record_id=data.get("source_record_id"),
            task_id=data.get("task_id"),
            acceptance_id=data.get("acceptance_id"),
            commit_sha=data.get("commit_sha"),
        )


def _normalize_stage(value: Any, evidence_type: EvidenceType) -> int:
    if value is None:
        stage = DEFAULT_STAGE_BY_EVIDENCE_TYPE.get(evidence_type)
        if stage is None:
            raise EnvelopeValidationError(
                f"lifecycle_stage is required for evidence_type {evidence_type.value}"
            )
        return int(stage)
    if isinstance(value, LifecycleStage):
        return int(value)
    if isinstance(value, bool):
        raise EnvelopeValidationError("lifecycle_stage must be an integer 0..14")
    if isinstance(value, int):
        if value not in LIFECYCLE_STAGES:
            raise EnvelopeValidationError(f"lifecycle_stage out of range: {value!r}")
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit() and int(text) in LIFECYCLE_STAGES:
            return int(text)
        try:
            return int(LifecycleStage[text.upper()])
        except KeyError as exc:
            raise EnvelopeValidationError(
                f"unknown lifecycle_stage: {value!r}"
            ) from exc
    raise EnvelopeValidationError("lifecycle_stage must be an integer 0..14")


def _normalize_identifier(value: Any, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise EnvelopeValidationError(f"{field_name} must be a string, not a bool")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    raise EnvelopeValidationError(f"{field_name} must be a scalar identifier")


def _compose_body(
    *,
    schema_version: str,
    evidence_type: str,
    lifecycle_stage: int,
    mode: str,
    symbol: Optional[str],
    timeframe: Optional[str],
    occurred_at: Optional[str],
    recorded_at: str,
    cycle_id: Optional[str],
    trade_id: Optional[str],
    event_id: str,
    evidence_id: str,
    correlation_id: Optional[str],
    parent_event_id: Optional[str],
    configuration_revision_id: Optional[str],
    parameter_revision_id: Optional[str],
    source_record_id: Optional[str],
    task_id: Optional[str],
    acceptance_id: Optional[str],
    commit_sha: Optional[str],
    authority: str,
    source: Mapping[str, Any],
    payload: Mapping[str, Any],
    provenance: Mapping[str, Any],
    availability: Mapping[str, Any],
    redaction: Mapping[str, Any],
    links: Mapping[str, Any],
    include_recorded_at: bool = True,
) -> dict:
    data = {
        "schema_version": schema_version,
        "evidence_type": evidence_type,
        "lifecycle_stage": int(lifecycle_stage),
        "mode": mode,
        "symbol": symbol,
        "timeframe": timeframe,
        "occurred_at": occurred_at,
        "recorded_at": recorded_at,
        "cycle_id": cycle_id,
        "trade_id": trade_id,
        "event_id": event_id,
        "evidence_id": evidence_id,
        "correlation_id": correlation_id,
        "parent_event_id": parent_event_id,
        "configuration_revision_id": configuration_revision_id,
        "parameter_revision_id": parameter_revision_id,
        "source_record_id": source_record_id,
        "task_id": task_id,
        "acceptance_id": acceptance_id,
        "commit_sha": commit_sha,
        "authority": authority,
        "source": dict(source),
        "payload": dict(payload),
        "provenance": dict(provenance),
        "availability": dict(availability),
        "redaction": dict(redaction),
        "links": dict(links),
    }
    if not include_recorded_at:
        data.pop("recorded_at", None)
    return data


def _derive_event_id(identity: Mapping[str, Any]) -> str:
    return "evidence-event-" + _sha256_hex(canonical_json(dict(identity)))[:32]


def _derive_evidence_id(identity: Mapping[str, Any]) -> str:
    return "evidence-" + _sha256_hex(canonical_json(dict(identity)))[:32]


def build_envelope(
    *,
    evidence_type: Any,
    mode: Any,
    source: Mapping[str, Any],
    authority: Any = DEFAULT_AUTHORITY,
    payload: Optional[Mapping[str, Any]] = None,
    provenance: Optional[Mapping[str, Any]] = None,
    links: Optional[Mapping[str, Any]] = None,
    availability: Optional[Mapping[str, Any]] = None,
    lifecycle_stage: Any = None,
    symbol: Any = None,
    timeframe: Any = None,
    occurred_at: Any = None,
    recorded_at: Any = None,
    cycle_id: Any = None,
    trade_id: Any = None,
    correlation_id: Any = None,
    parent_event_id: Any = None,
    configuration_revision_id: Any = None,
    parameter_revision_id: Any = None,
    source_record_id: Any = None,
    task_id: Any = None,
    acceptance_id: Any = None,
    commit_sha: Any = None,
    event_id: Any = None,
    evidence_id: Any = None,
    secret_policy: Any = SecretPolicy.REDACT,
    truth_level: Any = DEFAULT_TRUTH_LEVEL,
    verified: bool = False,
) -> EvidenceEnvelope:
    """Build a validated canonical envelope without inventing any value.

    Every absent identifier/value must be accompanied by an explicit
    availability entry; a value present in the source is marked
    ``VALUE_PRESENT``.  Secret-like fields are redacted (default) and recorded
    in the envelope ``redaction`` block.
    """

    try:
        resolved_type = (
            evidence_type
            if isinstance(evidence_type, EvidenceType)
            else EvidenceType(evidence_type)
        )
    except ValueError as exc:
        raise EnvelopeValidationError(
            f"unknown evidence_type: {evidence_type!r}"
        ) from exc
    try:
        resolved_mode = EvidenceMode(
            str(mode).strip().upper() if not isinstance(mode, EvidenceMode) else mode
        )
    except ValueError as exc:
        raise EnvelopeValidationError(f"mode must be PAPER or LIVE, got {mode!r}") from exc
    try:
        resolved_authority = AuthorityClass(
            authority if isinstance(authority, AuthorityClass) else str(authority).strip().upper()
        )
    except ValueError as exc:
        raise EnvelopeValidationError(f"unknown authority: {authority!r}") from exc
    try:
        resolved_truth = TruthLevel(
            truth_level if isinstance(truth_level, TruthLevel) else str(truth_level).strip().upper()
        )
    except ValueError as exc:
        raise EnvelopeValidationError(f"unknown truth_level: {truth_level!r}") from exc
    try:
        resolved_policy = SecretPolicy(
            secret_policy if isinstance(secret_policy, SecretPolicy) else str(secret_policy).strip().upper()
        )
    except ValueError as exc:
        raise EnvelopeValidationError(
            f"unknown secret_policy: {secret_policy!r}"
        ) from exc
    stage = _normalize_stage(lifecycle_stage, resolved_type)

    if not isinstance(source, Mapping) or not source:
        raise EnvelopeValidationError("source must be a non-empty mapping")
    cleaned_source, redacted_source = _redact(source, "source")
    cleaned_payload, redacted_payload = _redact(payload or {}, "payload")
    cleaned_links, redacted_links = _redact(links or {}, "links")
    cleaned_provenance, redacted_provenance = _redact(
        provenance or {}, "provenance"
    )

    redacted_fields = sorted(
        set(redacted_source + redacted_payload + redacted_links + redacted_provenance)
    )
    if redacted_fields and resolved_policy is SecretPolicy.REJECT:
        raise SecretFieldError(
            "secret-like fields rejected: " + ", ".join(redacted_fields)
        )

    encoded_payload = canonical_json(cleaned_payload)
    payload_truncated = False
    if len(encoded_payload.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        cleaned_payload = {
            "truncated": True,
            "originalBytes": len(encoded_payload.encode("utf-8")),
        }
        payload_truncated = True

    resolved_recorded_at = normalize_timestamp(recorded_at, "recorded_at") or _utc_now()
    resolved_occurred_at = normalize_timestamp(occurred_at, "occurred_at")
    resolved_symbol = _normalize_identifier(symbol, "symbol")
    resolved_timeframe = _normalize_identifier(timeframe, "timeframe")
    identifiers = {
        "cycle_id": _normalize_identifier(cycle_id, "cycle_id"),
        "trade_id": _normalize_identifier(trade_id, "trade_id"),
        "correlation_id": _normalize_identifier(correlation_id, "correlation_id"),
        "parent_event_id": _normalize_identifier(parent_event_id, "parent_event_id"),
        "configuration_revision_id": _normalize_identifier(
            configuration_revision_id, "configuration_revision_id"
        ),
        "parameter_revision_id": _normalize_identifier(
            parameter_revision_id, "parameter_revision_id"
        ),
        "source_record_id": _normalize_identifier(source_record_id, "source_record_id"),
        "task_id": _normalize_identifier(task_id, "task_id"),
        "acceptance_id": _normalize_identifier(acceptance_id, "acceptance_id"),
        "commit_sha": _normalize_identifier(commit_sha, "commit_sha"),
    }

    provided_availability = {
        key: normalize_availability_entry(value)
        for key, value in (availability or {}).items()
    }
    resolved_availability: dict[str, Any] = {}
    for field_name in AVAILABILITY_TRACKED_FIELDS:
        value = (
            resolved_symbol
            if field_name == "symbol"
            else resolved_timeframe
            if field_name == "timeframe"
            else resolved_occurred_at
            if field_name == "occurred_at"
            else identifiers.get(field_name)
        )
        if value is not None:
            entry = provided_availability.get(field_name)
            if entry is not None and availability_state(entry) != AvailabilityState.VALUE_PRESENT.value:
                raise EnvelopeValidationError(
                    f"{field_name} has a value but availability is "
                    f"{availability_state(entry)}"
                )
            resolved_availability[field_name] = AvailabilityState.VALUE_PRESENT.value
        else:
            entry = provided_availability.get(field_name)
            if entry is None:
                raise EnvelopeValidationError(
                    f"{field_name} is absent and requires an explicit availability state"
                )
            resolved_availability[field_name] = entry
    for key, value in provided_availability.items():
        if key not in resolved_availability:
            resolved_availability[key] = value

    resolved_event_id = _normalize_identifier(event_id, "event_id")
    identity_for_event = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "evidence_type": resolved_type.value,
        "lifecycle_stage": stage,
        "mode": resolved_mode.value,
        **identifiers,
    }
    if resolved_event_id is None:
        resolved_event_id = _derive_event_id(identity_for_event)

    identity = {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "evidence_type": resolved_type.value,
        "lifecycle_stage": stage,
        "mode": resolved_mode.value,
        "symbol": resolved_symbol,
        "timeframe": resolved_timeframe,
        "occurred_at": resolved_occurred_at,
        "event_id": resolved_event_id,
        **identifiers,
    }
    resolved_evidence_id = _normalize_identifier(evidence_id, "evidence_id")
    if resolved_evidence_id is None:
        resolved_evidence_id = _derive_evidence_id(identity)

    resolved_provenance = {
        "truthLevel": resolved_truth.value,
        "contractVersion": ENVELOPE_SCHEMA_VERSION,
        "verified": bool(verified),
        "sourceReference": identifiers.get("source_record_id"),
    }
    resolved_provenance.update(cleaned_provenance)

    redaction = {
        "applied": bool(redacted_fields) or payload_truncated,
        "fields": redacted_fields,
        "rule": SECRET_REDACTION_RULE,
        "reason": None,
        "payloadTruncated": payload_truncated,
    }

    resolved_links = dict(cleaned_links)
    if identifiers.get("parent_event_id"):
        resolved_links.setdefault("parentEventId", identifiers["parent_event_id"])
    if identifiers.get("source_record_id"):
        resolved_links.setdefault("sourceRecordId", identifiers["source_record_id"])
    if identifiers.get("cycle_id"):
        resolved_links.setdefault("cycleId", identifiers["cycle_id"])
    if identifiers.get("trade_id"):
        resolved_links.setdefault("tradeId", identifiers["trade_id"])
    if identifiers.get("correlation_id"):
        resolved_links.setdefault("correlationId", identifiers["correlation_id"])
    if identifiers.get("configuration_revision_id"):
        resolved_links.setdefault(
            "configurationRevisionId", identifiers["configuration_revision_id"]
        )
    if identifiers.get("parameter_revision_id"):
        resolved_links.setdefault(
            "parameterRevisionId", identifiers["parameter_revision_id"]
        )

    digest = _sha256_hex(
        canonical_json(
            _compose_body(
                schema_version=ENVELOPE_SCHEMA_VERSION,
                evidence_type=resolved_type.value,
                lifecycle_stage=stage,
                mode=resolved_mode.value,
                symbol=resolved_symbol,
                timeframe=resolved_timeframe,
                occurred_at=resolved_occurred_at,
                recorded_at=resolved_recorded_at,
                cycle_id=identifiers["cycle_id"],
                trade_id=identifiers["trade_id"],
                event_id=resolved_event_id,
                evidence_id=resolved_evidence_id,
                correlation_id=identifiers["correlation_id"],
                parent_event_id=identifiers["parent_event_id"],
                configuration_revision_id=identifiers["configuration_revision_id"],
                parameter_revision_id=identifiers["parameter_revision_id"],
                source_record_id=identifiers["source_record_id"],
                task_id=identifiers["task_id"],
                acceptance_id=identifiers["acceptance_id"],
                commit_sha=identifiers["commit_sha"],
                authority=resolved_authority.value,
                source=cleaned_source,
                payload=cleaned_payload,
                provenance=resolved_provenance,
                availability=resolved_availability,
                redaction=redaction,
                links=resolved_links,
            )
        )
    )
    return EvidenceEnvelope(
        schema_version=ENVELOPE_SCHEMA_VERSION,
        evidence_type=resolved_type.value,
        lifecycle_stage=stage,
        mode=resolved_mode.value,
        event_id=resolved_event_id,
        evidence_id=resolved_evidence_id,
        recorded_at=resolved_recorded_at,
        authority=resolved_authority.value,
        source=cleaned_source,
        payload=cleaned_payload,
        provenance=resolved_provenance,
        integrity={
            "algorithm": "sha256",
            "digest": digest,
            "scope": "CANONICAL_BODY",
        },
        availability=resolved_availability,
        redaction=redaction,
        links=resolved_links,
        symbol=resolved_symbol,
        timeframe=resolved_timeframe,
        occurred_at=resolved_occurred_at,
        cycle_id=identifiers["cycle_id"],
        trade_id=identifiers["trade_id"],
        correlation_id=identifiers["correlation_id"],
        parent_event_id=identifiers["parent_event_id"],
        configuration_revision_id=identifiers["configuration_revision_id"],
        parameter_revision_id=identifiers["parameter_revision_id"],
        source_record_id=identifiers["source_record_id"],
        task_id=identifiers["task_id"],
        acceptance_id=identifiers["acceptance_id"],
        commit_sha=identifiers["commit_sha"],
    )


def validate_envelope(value: Any) -> EvidenceEnvelope:
    """Return the value as an envelope, raising a strict validation error."""

    if isinstance(value, EvidenceEnvelope):
        value._validate()
        return value
    if isinstance(value, Mapping):
        return EvidenceEnvelope.from_dict(value)
    raise EnvelopeValidationError("envelope must be an EvidenceEnvelope or mapping")


def secret_fields(value: Iterable[Any] | Mapping[str, Any]) -> list[str]:
    """Return the redacted secret-like paths for an arbitrary structure."""

    _, redacted = _redact(value, "")
    return sorted(set(redacted))
