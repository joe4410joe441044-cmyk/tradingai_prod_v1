"""Canonical cycle-evidence capture orchestrator (WORK I P0).

This module assembles the evidence of one trading cycle across all fifteen
canonical lifecycle stages and persists it through the existing
:class:`~backend.runtime.cycle_evidence_store.CycleEvidenceStore`.

Authority boundaries (contract § A / § I / § L):

- the orchestrator is **observational only**: it builds and stores evidence and
  never participates in an execution, close, sizing, MM, Governance,
  market-selection or parameter-promotion decision;
- it does **not** read or write any existing canonical store (Stage 13, trading
  trace, revision archive, MM timeline, supervisor SQLite).  Evidence is supplied
  by the caller (or a read-only link adapter) and only the cycle-evidence store
  is written;
- it never invents a value: an absent identifier/value is written as ``None``
  with an explicit availability state;
- it creates no second store and is never wired into the production runtime by
  this task.

Lifecycle per stage:

``NOT_STARTED`` → ``STARTED`` → ``PARTIAL`` → ``COMPLETED`` / ``BLOCKED`` /
``REJECTED`` / ``FAILED``.  The four terminal states are *finalized*: a
different capture for a finalized stage fails closed, while an exact idempotent
retry returns ``DUPLICATE`` without a second write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, FrozenSet, Mapping, Optional, Sequence

from backend.runtime.cycle_evidence import (
    AVAILABILITY_TRACKED_FIELDS,
    AuthorityClass,
    AvailabilityState,
    EnvelopeValidationError,
    EvidenceEnvelope,
    EvidenceMode,
    EvidenceType,
    SecretFieldError,
    SecretPolicy,
    TruthLevel,
    availability_state,
    build_envelope,
    normalize_availability_entry,
    normalize_timestamp,
)
from backend.runtime.cycle_evidence_stage_inputs import (
    CANONICAL_STAGE_ORDER,
    STAGE_DEFINITIONS,
    StageDefinition,
    StageMismatchError,
    StageResolutionError,
    resolve_stage,
)
from backend.runtime.cycle_evidence_store import AppendOutcome, CycleEvidenceStore

CAPTURE_SOURCE = {
    "subsystem": "CYCLE_EVIDENCE_CAPTURE",
    "module": "backend.runtime.cycle_evidence_capture",
}

# Reserved payload keys owned by the orchestrator.  Caller payload keys with the
# same name are overwritten (the orchestrator's identity wins).
RESERVED_PAYLOAD_KEYS = (
    "captureStatus",
    "stageNumber",
    "stageName",
    "sourceAuthority",
    "capturedAt",
    "parameterRevision",
    "strategyRevision",
)

# Capture result reason codes.
REASON_OK = "OK"
REASON_DUPLICATE = "DUPLICATE_EVIDENCE"
REASON_CONFLICT = "CONFLICTING_CONTENT"
REASON_STAGE_MISMATCH = "STAGE_NUMBER_NAME_MISMATCH"
REASON_STAGE_UNKNOWN = "STAGE_UNKNOWN"
REASON_EVIDENCE_TYPE_MISMATCH = "EVIDENCE_TYPE_NOT_ALLOWED_FOR_STAGE"
REASON_INVALID_TRANSITION = "INVALID_STAGE_TRANSITION"
REASON_FINALIZED = "STAGE_FINALIZED"
REASON_OUT_OF_ORDER = "STAGE_OUT_OF_ORDER"
REASON_INVALID_STATUS = "INVALID_CAPTURE_STATUS"
REASON_BUILD_REJECTED = "EVIDENCE_BUILD_REJECTED"
REASON_STORE_FAILED = "STORE_WRITE_FAILED"


class CaptureLifecycleState(str, Enum):
    """Per-stage capture lifecycle (contract requirement C)."""

    NOT_STARTED = "NOT_STARTED"
    STARTED = "STARTED"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


TERMINAL_CAPTURE_STATES: FrozenSet[CaptureLifecycleState] = frozenset(
    {
        CaptureLifecycleState.COMPLETED,
        CaptureLifecycleState.BLOCKED,
        CaptureLifecycleState.REJECTED,
        CaptureLifecycleState.FAILED,
    }
)

_ALLOWED_TRANSITIONS: Mapping[CaptureLifecycleState, FrozenSet[CaptureLifecycleState]] = {
    CaptureLifecycleState.NOT_STARTED: frozenset(
        {
            CaptureLifecycleState.STARTED,
            CaptureLifecycleState.PARTIAL,
            CaptureLifecycleState.COMPLETED,
            CaptureLifecycleState.BLOCKED,
            CaptureLifecycleState.REJECTED,
            CaptureLifecycleState.FAILED,
        }
    ),
    CaptureLifecycleState.STARTED: frozenset(
        {
            CaptureLifecycleState.STARTED,
            CaptureLifecycleState.PARTIAL,
            CaptureLifecycleState.COMPLETED,
            CaptureLifecycleState.BLOCKED,
            CaptureLifecycleState.REJECTED,
            CaptureLifecycleState.FAILED,
        }
    ),
    CaptureLifecycleState.PARTIAL: frozenset(
        {
            CaptureLifecycleState.PARTIAL,
            CaptureLifecycleState.COMPLETED,
            CaptureLifecycleState.BLOCKED,
            CaptureLifecycleState.REJECTED,
            CaptureLifecycleState.FAILED,
        }
    ),
    CaptureLifecycleState.COMPLETED: frozenset(),
    CaptureLifecycleState.BLOCKED: frozenset(),
    CaptureLifecycleState.REJECTED: frozenset(),
    CaptureLifecycleState.FAILED: frozenset(),
}


class CaptureOutcome(str, Enum):
    """Coarse outcome of one capture attempt."""

    ACCEPTED = "ACCEPTED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    REJECTED = "REJECTED"
    STORE_ERROR = "STORE_ERROR"


@dataclass(frozen=True)
class CaptureResult:
    """Structured result — a persistence failure is never swallowed."""

    outcome: CaptureOutcome
    reason: str
    stage: Optional[int]
    stage_name: Optional[str]
    state: CaptureLifecycleState
    evidence_id: Optional[str] = None
    append_outcome: Optional[AppendOutcome] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.outcome is CaptureOutcome.ACCEPTED

    @property
    def persisted(self) -> bool:
        return self.outcome in (CaptureOutcome.ACCEPTED, CaptureOutcome.DUPLICATE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_state(value: Any) -> CaptureLifecycleState:
    if isinstance(value, CaptureLifecycleState):
        return value
    return CaptureLifecycleState(str(value).strip().upper())


class CycleEvidenceCapture:
    """Assemble and persist the canonical evidence of one trading cycle."""

    def __init__(
        self,
        store: CycleEvidenceStore,
        *,
        cycle_id: Any,
        mode: Any,
        correlation_id: Any = None,
        trade_id: Any = None,
        symbol: Any = None,
        timeframe: Any = None,
        configuration_revision_id: Any = None,
        parameter_revision_id: Any = None,
        strategy_revision: Any = None,
        task_id: Any = None,
        acceptance_id: Any = None,
        commit_sha: Any = None,
        authority: Any = AuthorityClass.RECORDING_AUTHORITY,
        secret_policy: Any = SecretPolicy.REDACT,
        enforce_sequential: bool = False,
    ):
        if not isinstance(store, CycleEvidenceStore):
            raise TypeError("store must be a CycleEvidenceStore")
        if not isinstance(cycle_id, str) or not cycle_id.strip():
            raise ValueError("cycle_id must be a non-empty string")
        try:
            resolved_mode = EvidenceMode(
                str(mode).strip().upper() if not isinstance(mode, EvidenceMode) else mode
            )
        except ValueError as exc:
            raise ValueError("mode must be PAPER or LIVE") from exc
        self._store = store
        self.cycle_id = cycle_id.strip()
        self.mode = resolved_mode.value
        self.correlation_id = _optional_text(correlation_id)
        self.trade_id = _optional_text(trade_id)
        self.symbol = _optional_text(symbol)
        self.timeframe = _optional_text(timeframe)
        self.configuration_revision_id = _optional_text(configuration_revision_id)
        self.parameter_revision_id = _optional_text(parameter_revision_id)
        self.strategy_revision = _optional_text(strategy_revision)
        self.task_id = _optional_text(task_id)
        self.acceptance_id = _optional_text(acceptance_id)
        self.commit_sha = _optional_text(commit_sha)
        self.authority = _resolve_authority(authority)
        self.secret_policy = _resolve_secret_policy(secret_policy)
        self.enforce_sequential = bool(enforce_sequential)
        self._states: dict[int, CaptureLifecycleState] = {
            number: CaptureLifecycleState.NOT_STARTED for number in CANONICAL_STAGE_ORDER
        }
        self._evidence_ids: dict[int, list[str]] = {
            number: [] for number in CANONICAL_STAGE_ORDER
        }

    # -- state inspection ---------------------------------------------------

    @property
    def store(self) -> CycleEvidenceStore:
        return self._store

    def states(self) -> dict[int, CaptureLifecycleState]:
        return dict(self._states)

    def state_of(self, stage: Any) -> CaptureLifecycleState:
        definition = resolve_stage(stage=stage)
        return self._states[definition.number]

    def is_stage_finalized(self, stage: Any) -> bool:
        return self.state_of(stage) in TERMINAL_CAPTURE_STATES

    def captured_stages(self) -> list[int]:
        return [
            number
            for number in CANONICAL_STAGE_ORDER
            if self._states[number] is not CaptureLifecycleState.NOT_STARTED
        ]

    def next_expected_stage(self) -> Optional[int]:
        for number in CANONICAL_STAGE_ORDER:
            if self._states[number] is not CaptureLifecycleState.COMPLETED:
                return number
        return None

    def is_cycle_complete(self) -> bool:
        return all(
            self._states[number] is CaptureLifecycleState.COMPLETED
            for number in CANONICAL_STAGE_ORDER
        )

    def has_failed_stage(self) -> bool:
        return any(
            self._states[number]
            in (
                CaptureLifecycleState.BLOCKED,
                CaptureLifecycleState.REJECTED,
                CaptureLifecycleState.FAILED,
            )
            for number in CANONICAL_STAGE_ORDER
        )

    def evidence_ids(self, stage: Any) -> list[str]:
        definition = resolve_stage(stage=stage)
        return list(self._evidence_ids[definition.number])

    def summary(self) -> dict:
        return {
            "cycleId": self.cycle_id,
            "mode": self.mode,
            "symbol": self.symbol,
            "correlationId": self.correlation_id,
            "tradeId": self.trade_id,
            "isComplete": self.is_cycle_complete(),
            "nextExpectedStage": self.next_expected_stage(),
            "stages": [
                {
                    "number": number,
                    "name": STAGE_DEFINITIONS[number].name,
                    "state": self._states[number].value,
                }
                for number in CANONICAL_STAGE_ORDER
            ],
        }

    # -- envelope construction (pure) --------------------------------------

    def build_stage_envelope(
        self,
        stage: Any,
        *,
        evidence_type: Any,
        status: Any,
        stage_name: Any = None,
        payload: Optional[Mapping[str, Any]] = None,
        occurred_at: Any = None,
        recorded_at: Any = None,
        authority: Any = None,
        source: Optional[Mapping[str, Any]] = None,
        availability: Optional[Mapping[str, Any]] = None,
        links: Optional[Mapping[str, Any]] = None,
        source_record_id: Any = None,
        event_key: Any = None,
        trade_id: Any = None,
        correlation_id: Any = None,
        symbol: Any = None,
        timeframe: Any = None,
        parameter_revision_id: Any = None,
        configuration_revision_id: Any = None,
        truth_level: Any = TruthLevel.CURRENT_SOURCE_RUNTIME,
        verified: bool = False,
        secret_policy: Any = None,
    ) -> EvidenceEnvelope:
        """Build (but do not persist) one stage evidence envelope."""

        definition = resolve_stage(stage=stage, stage_name=stage_name)
        resolved_type = _resolve_evidence_type(evidence_type)
        if resolved_type not in definition.evidence_types:
            raise EnvelopeValidationError(
                f"{resolved_type.value} is not allowed for stage "
                f"{definition.number} {definition.name}"
            )
        return self._build_envelope(
            definition,
            resolved_type=resolved_type,
            status=_coerce_state(status),
            payload=payload,
            occurred_at=occurred_at,
            recorded_at=recorded_at,
            authority=authority,
            source=source,
            availability=availability,
            links=links,
            source_record_id=source_record_id,
            event_key=event_key,
            trade_id=trade_id,
            correlation_id=correlation_id,
            symbol=symbol,
            timeframe=timeframe,
            parameter_revision_id=parameter_revision_id,
            configuration_revision_id=configuration_revision_id,
            truth_level=truth_level,
            verified=verified,
            secret_policy=secret_policy,
        )

    def _build_envelope(
        self,
        definition: StageDefinition,
        *,
        resolved_type: EvidenceType,
        status: CaptureLifecycleState,
        payload: Optional[Mapping[str, Any]] = None,
        occurred_at: Any = None,
        recorded_at: Any = None,
        authority: Any = None,
        source: Optional[Mapping[str, Any]] = None,
        availability: Optional[Mapping[str, Any]] = None,
        links: Optional[Mapping[str, Any]] = None,
        source_record_id: Any = None,
        event_key: Any = None,
        trade_id: Any = None,
        correlation_id: Any = None,
        symbol: Any = None,
        timeframe: Any = None,
        parameter_revision_id: Any = None,
        configuration_revision_id: Any = None,
        truth_level: Any = TruthLevel.CURRENT_SOURCE_RUNTIME,
        verified: bool = False,
        secret_policy: Any = None,
    ) -> EvidenceEnvelope:
        resolved_recorded_at = normalize_timestamp(recorded_at, "recorded_at") or _utc_now()
        resolved_authority = (
            self.authority if authority is None else _resolve_authority(authority)
        )
        resolved_policy = (
            self.secret_policy
            if secret_policy is None
            else _resolve_secret_policy(secret_policy)
        )
        resolved_parameter_revision = (
            self.parameter_revision_id if parameter_revision_id is None else _optional_text(parameter_revision_id)
        ) or None
        resolved_configuration_revision = (
            self.configuration_revision_id
            if configuration_revision_id is None
            else _optional_text(configuration_revision_id)
        ) or None
        resolved_trade_id = self.trade_id if trade_id is None else _optional_text(trade_id)
        resolved_correlation = (
            self.correlation_id if correlation_id is None else _optional_text(correlation_id)
        )
        resolved_symbol = self.symbol if symbol is None else _optional_text(symbol)
        resolved_timeframe = self.timeframe if timeframe is None else _optional_text(timeframe)
        resolved_source_record = _optional_text(source_record_id)

        presents = {
            "symbol": resolved_symbol,
            "timeframe": resolved_timeframe,
            "occurred_at": occurred_at,
            "cycle_id": self.cycle_id,
            "trade_id": resolved_trade_id,
            "correlation_id": resolved_correlation,
            "parent_event_id": None,
            "configuration_revision_id": resolved_configuration_revision,
            "parameter_revision_id": resolved_parameter_revision,
            "source_record_id": resolved_source_record,
            "task_id": self.task_id,
            "acceptance_id": self.acceptance_id,
            "commit_sha": self.commit_sha,
        }
        resolved_availability = _merge_availability(presents, availability)

        resolved_payload = dict(payload or {})
        reserved = {
            "captureStatus": status.value,
            "stageNumber": definition.number,
            "stageName": definition.name,
            "sourceAuthority": resolved_authority.value,
        }
        # ``captured_at`` is the envelope's durable ``recorded_at``.  An explicit
        # caller-supplied timestamp is additionally encoded for self-description;
        # it is never auto-filled with a varying write clock, so an idempotent
        # retry of the same logical capture stays byte-identical.
        if recorded_at is not None:
            reserved["capturedAt"] = resolved_recorded_at
        if resolved_parameter_revision is not None:
            reserved["parameterRevision"] = resolved_parameter_revision
        if self.strategy_revision is not None:
            reserved["strategyRevision"] = self.strategy_revision
        resolved_payload.update(reserved)

        resolved_source = dict(CAPTURE_SOURCE)
        if source:
            resolved_source.update(source)

        resolved_links = dict(links or {})
        if source_record_id is not None:
            resolved_links.setdefault("sourceRecordId", source_record_id)

        event_id = _derive_event_id(
            self.cycle_id, definition.number, status, event_key or resolved_type.value
        )

        return build_envelope(
            evidence_type=resolved_type,
            lifecycle_stage=definition.number,
            mode=self.mode,
            source=resolved_source,
            authority=resolved_authority,
            payload=resolved_payload,
            provenance={
                "truthLevel": _resolve_truth_level(truth_level).value,
                "captureOrchestrator": "cycle_evidence_capture/v1",
            },
            links=resolved_links,
            availability=resolved_availability,
            symbol=resolved_symbol,
            timeframe=resolved_timeframe,
            occurred_at=occurred_at,
            recorded_at=resolved_recorded_at,
            cycle_id=self.cycle_id,
            trade_id=resolved_trade_id,
            correlation_id=resolved_correlation,
            configuration_revision_id=resolved_configuration_revision,
            parameter_revision_id=resolved_parameter_revision,
            source_record_id=resolved_source_record,
            task_id=self.task_id,
            acceptance_id=self.acceptance_id,
            commit_sha=self.commit_sha,
            event_id=event_id,
            secret_policy=resolved_policy,
            truth_level=truth_level,
            verified=verified,
        )

    # -- capture (persist) --------------------------------------------------

    def capture_stage(
        self,
        stage: Any,
        *,
        evidence_type: Any,
        status: Any,
        stage_name: Any = None,
        **kwargs: Any,
    ) -> CaptureResult:
        """Validate, build and idempotently persist one stage evidence record."""

        try:
            definition = resolve_stage(stage=stage, stage_name=stage_name)
        except StageMismatchError as exc:
            return self._rejected(None, None, REASON_STAGE_MISMATCH, str(exc))
        except StageResolutionError as exc:
            return self._rejected(None, None, REASON_STAGE_UNKNOWN, str(exc))

        try:
            resolved_status = _coerce_state(status)
        except ValueError:
            return self._rejected(
                definition.number, definition.name, REASON_INVALID_STATUS, str(status)
            )

        try:
            resolved_type = _resolve_evidence_type(evidence_type)
        except EnvelopeValidationError as exc:
            return self._rejected(
                definition.number, definition.name, REASON_EVIDENCE_TYPE_MISMATCH, str(exc)
            )
        if resolved_type not in definition.evidence_types:
            return self._rejected(
                definition.number,
                definition.name,
                REASON_EVIDENCE_TYPE_MISMATCH,
                f"{resolved_type.value} not allowed for stage {definition.number}",
            )

        current = self._states[definition.number]
        if self.enforce_sequential and current is CaptureLifecycleState.NOT_STARTED:
            if any(
                self._states[number] is CaptureLifecycleState.NOT_STARTED
                for number in range(definition.number)
            ):
                return self._rejected(
                    definition.number,
                    definition.name,
                    REASON_OUT_OF_ORDER,
                    f"stage {definition.number} captured before earlier stages",
                )

        try:
            envelope = self._build_envelope(
                definition,
                resolved_type=resolved_type,
                status=resolved_status,
                **kwargs,
            )
        except (EnvelopeValidationError, SecretFieldError, ValueError, TypeError) as exc:
            return self._rejected(
                definition.number, definition.name, REASON_BUILD_REJECTED, str(exc)
            )

        if current in TERMINAL_CAPTURE_STATES:
            existing = self._store.get(envelope.evidence_id)
            if existing is not None:
                try:
                    prior = EvidenceEnvelope.from_dict(existing)
                except Exception:  # noqa: BLE001 - unreadable prior is a conflict
                    return self._conflict(definition, envelope, current)
                if prior.logical_digest() == envelope.logical_digest():
                    return CaptureResult(
                        outcome=CaptureOutcome.DUPLICATE,
                        reason=REASON_DUPLICATE,
                        stage=definition.number,
                        stage_name=definition.name,
                        state=current,
                        evidence_id=envelope.evidence_id,
                        append_outcome=AppendOutcome.DUPLICATE,
                    )
                return self._conflict(definition, envelope, current)
            return self._rejected(
                definition.number,
                definition.name,
                REASON_FINALIZED,
                f"stage {definition.number} is finalized as {current.value}",
            )

        if resolved_status not in _ALLOWED_TRANSITIONS[current]:
            return self._rejected(
                definition.number,
                definition.name,
                REASON_INVALID_TRANSITION,
                f"{current.value} -> {resolved_status.value} is not allowed",
            )

        try:
            append_result = self._store.append(envelope)
        except Exception as exc:  # noqa: BLE001 - never swallow a store failure
            return CaptureResult(
                outcome=CaptureOutcome.STORE_ERROR,
                reason=REASON_STORE_FAILED,
                stage=definition.number,
                stage_name=definition.name,
                state=current,
                evidence_id=envelope.evidence_id,
                error=str(exc),
            )

        if append_result.outcome is AppendOutcome.WRITTEN:
            self._states[definition.number] = resolved_status
            self._evidence_ids[definition.number].append(envelope.evidence_id)
            return CaptureResult(
                outcome=CaptureOutcome.ACCEPTED,
                reason=REASON_OK,
                stage=definition.number,
                stage_name=definition.name,
                state=resolved_status,
                evidence_id=envelope.evidence_id,
                append_outcome=append_result.outcome,
            )
        if append_result.outcome is AppendOutcome.DUPLICATE:
            self._states[definition.number] = resolved_status
            self._evidence_ids[definition.number].append(envelope.evidence_id)
            return CaptureResult(
                outcome=CaptureOutcome.DUPLICATE,
                reason=REASON_DUPLICATE,
                stage=definition.number,
                stage_name=definition.name,
                state=resolved_status,
                evidence_id=envelope.evidence_id,
                append_outcome=append_result.outcome,
            )
        if append_result.outcome is AppendOutcome.CONFLICT:
            return self._conflict(definition, envelope, current)
        return CaptureResult(
            outcome=CaptureOutcome.STORE_ERROR,
            reason=REASON_STORE_FAILED,
            stage=definition.number,
            stage_name=definition.name,
            state=current,
            evidence_id=envelope.evidence_id,
            append_outcome=append_result.outcome,
            error=append_result.error,
        )

    def capture_many(self, items: Sequence[Mapping[str, Any]]) -> list[CaptureResult]:
        """Capture multiple stage items in canonical stage order."""

        ordered = sorted(
            items,
            key=lambda item: resolve_stage(
                stage=item.get("stage"), stage_name=item.get("stage_name")
            ).number,
        )
        results: list[CaptureResult] = []
        for item in ordered:
            request = dict(item)
            stage = request.pop("stage", None)
            results.append(self.capture_stage(stage, **request))
        return results

    # -- restart ------------------------------------------------------------

    @classmethod
    def resume(
        cls,
        store: CycleEvidenceStore,
        cycle_id: str,
        *,
        mode: Any = None,
        **identity: Any,
    ) -> "CycleEvidenceCapture":
        """Rebuild capture state from the durable store (restart recovery)."""

        records = [
            item.record
            for item in store.iter_records()
            if item.valid and item.record.get("cycle_id") == cycle_id
        ]
        first = records[0] if records else {}
        resolved_mode = mode if mode is not None else first.get("mode")
        if resolved_mode is None:
            raise ValueError("cannot resume: mode unknown and no stored records")
        session = cls(store, cycle_id=cycle_id, mode=resolved_mode, **_resume_identity(first, identity))
        for record in records:
            payload = record.get("payload")
            if not isinstance(payload, Mapping):
                continue
            stage = record.get("lifecycle_stage")
            raw_status = payload.get("captureStatus")
            if not isinstance(stage, int) or stage not in CANONICAL_STAGE_ORDER:
                continue
            try:
                state = _coerce_state(raw_status)
            except ValueError:
                continue
            session._states[stage] = state
            evidence_id = record.get("evidence_id")
            if isinstance(evidence_id, str):
                session._evidence_ids[stage].append(evidence_id)
        return session

    # -- helpers ------------------------------------------------------------

    def _rejected(
        self,
        stage: Optional[int],
        stage_name: Optional[str],
        reason: str,
        error: Optional[str],
    ) -> CaptureResult:
        state = (
            self._states.get(stage, CaptureLifecycleState.NOT_STARTED)
            if stage is not None
            else CaptureLifecycleState.NOT_STARTED
        )
        return CaptureResult(
            outcome=CaptureOutcome.REJECTED,
            reason=reason,
            stage=stage,
            stage_name=stage_name,
            state=state,
            error=error,
        )

    def _conflict(
        self, definition: StageDefinition, envelope: EvidenceEnvelope, state: CaptureLifecycleState
    ) -> CaptureResult:
        return CaptureResult(
            outcome=CaptureOutcome.CONFLICT,
            reason=REASON_CONFLICT,
            stage=definition.number,
            stage_name=definition.name,
            state=state,
            evidence_id=envelope.evidence_id,
            append_outcome=AppendOutcome.CONFLICT,
        )


def capture_cycle_evidence(
    store: CycleEvidenceStore,
    *,
    cycle_id: str,
    mode: Any,
    items: Sequence[Mapping[str, Any]],
    **session_kwargs: Any,
) -> list[CaptureResult]:
    """Convenience: build a session and capture the supplied stage items."""

    session = CycleEvidenceCapture(store, cycle_id=cycle_id, mode=mode, **session_kwargs)
    return session.capture_many(items)


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("identifier must not be a bool")
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    raise ValueError(f"identifier must be a scalar, got {type(value).__name__}")


def _resolve_evidence_type(value: Any) -> EvidenceType:
    try:
        return value if isinstance(value, EvidenceType) else EvidenceType(value)
    except ValueError as exc:
        raise EnvelopeValidationError(f"unknown evidence_type: {value!r}") from exc


def _resolve_authority(value: Any) -> AuthorityClass:
    try:
        return (
            value
            if isinstance(value, AuthorityClass)
            else AuthorityClass(str(value).strip().upper())
        )
    except ValueError as exc:
        raise EnvelopeValidationError(f"unknown authority: {value!r}") from exc


def _resolve_truth_level(value: Any) -> TruthLevel:
    try:
        return value if isinstance(value, TruthLevel) else TruthLevel(str(value).strip().upper())
    except ValueError as exc:
        raise EnvelopeValidationError(f"unknown truth_level: {value!r}") from exc


def _resolve_secret_policy(value: Any) -> SecretPolicy:
    try:
        return value if isinstance(value, SecretPolicy) else SecretPolicy(str(value).strip().upper())
    except ValueError as exc:
        raise EnvelopeValidationError(f"unknown secret_policy: {value!r}") from exc


def _merge_availability(
    presents: Mapping[str, Any], override: Optional[Mapping[str, Any]]
) -> dict:
    normalized = {
        key: normalize_availability_entry(value)
        for key, value in (override or {}).items()
    }
    availability: dict[str, Any] = {}
    for field_name in AVAILABILITY_TRACKED_FIELDS:
        if presents.get(field_name) is not None:
            if field_name in normalized and availability_state(
                normalized[field_name]
            ) != AvailabilityState.VALUE_PRESENT.value:
                raise EnvelopeValidationError(
                    f"{field_name} has a value but availability is "
                    f"{availability_state(normalized[field_name])}"
                )
            continue
        if field_name in normalized:
            availability[field_name] = normalized[field_name]
        elif field_name in ("timeframe", "parent_event_id"):
            availability[field_name] = AvailabilityState.NOT_APPLICABLE.value
        else:
            availability[field_name] = AvailabilityState.NOT_CAPTURED.value
    for key, value in normalized.items():
        if key not in AVAILABILITY_TRACKED_FIELDS:
            availability[key] = value
    return availability


def _derive_event_id(cycle_id: str, stage: int, status: CaptureLifecycleState, event_key: str) -> str:
    return f"capture-{cycle_id}-{stage}-{status.value.lower()}-{event_key}"


def _resume_identity(first: Mapping[str, Any], explicit: Mapping[str, Any]) -> dict:
    payload = first.get("payload")
    if not isinstance(payload, Mapping):
        payload = {}

    def choose(field_name: str, record_key: Optional[str] = None):
        if field_name in explicit and explicit[field_name] is not None:
            return explicit[field_name]
        return first.get(record_key or field_name)

    return {
        "symbol": choose("symbol"),
        "timeframe": choose("timeframe"),
        "correlation_id": choose("correlation_id"),
        "trade_id": choose("trade_id"),
        "configuration_revision_id": choose("configuration_revision_id"),
        "parameter_revision_id": choose("parameter_revision_id"),
        "strategy_revision": explicit.get("strategy_revision") or payload.get(
            "strategyRevision"
        ),
        "task_id": choose("task_id"),
        "acceptance_id": choose("acceptance_id"),
        "commit_sha": choose("commit_sha"),
    }
