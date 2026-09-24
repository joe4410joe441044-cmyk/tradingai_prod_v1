"""Read-only link adapters from existing canonical stores to evidence envelopes.

These adapters convert an *already read* canonical record (Stage 13 completed
trade, trading-trace event, parameter revision) into a canonical evidence
envelope.  They are link/projection helpers (contract § I.1): they read no
store themselves, write nothing, and never re-implement an existing authority.

Every missing value becomes an explicit availability state.  A value that is
not present in the source is never guessed.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.runtime.cycle_evidence import (
    AVAILABILITY_TRACKED_FIELDS,
    AuthorityClass,
    AvailabilityState,
    EvidenceEnvelope,
    EvidenceType,
    LifecycleStage,
    TruthLevel,
    build_envelope,
)

# Trading-trace stage → canonical lifecycle stage / evidence type.  The trace
# vocabulary is reused verbatim; it is never re-implemented.
TRACE_STAGE_TO_LIFECYCLE = {
    "MARKET": LifecycleStage.MARKET_DATA,
    "DETECTOR": LifecycleStage.FEATURE_BUILDER,
    "FEATURE": LifecycleStage.FEATURE_BUILDER,
    "STRATEGY": LifecycleStage.MICRO_EDGE_STRATEGY,
    "AI": LifecycleStage.AI_DECISION_REVIEW,
    "MONEY_MANAGEMENT": LifecycleStage.MONEY_MANAGEMENT,
    "GOVERNANCE": LifecycleStage.GOVERNANCE,
    "EXECUTION": LifecycleStage.EXECUTION,
    "POSITION": LifecycleStage.POSITION,
    "RESULT": LifecycleStage.TRADE_PARAMETER_PERFORMANCE,
    "HISTORY": LifecycleStage.TRADE_PARAMETER_PERFORMANCE,
}

TRACE_STAGE_TO_EVIDENCE_TYPE = {
    "MARKET": EvidenceType.MARKET_CONTEXT,
    "DETECTOR": EvidenceType.FEATURE_EVIDENCE,
    "FEATURE": EvidenceType.FEATURE_EVIDENCE,
    "STRATEGY": EvidenceType.STRATEGY_SIGNAL,
    "AI": EvidenceType.AI_DECISION,
    "MONEY_MANAGEMENT": EvidenceType.MONEY_MANAGEMENT_DECISION,
    "GOVERNANCE": EvidenceType.GOVERNANCE_DECISION,
    "EXECUTION": EvidenceType.NORMALIZED_ORDER,
    "POSITION": EvidenceType.POSITION,
    "RESULT": EvidenceType.TRADE_PERFORMANCE,
    "HISTORY": EvidenceType.TRADE_PERFORMANCE,
}


def _first(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def _availability(absent_states: Mapping[str, str], presents: Mapping[str, Any]) -> dict:
    """Build the availability map for absent tracked fields.

    Present fields are omitted so the builder marks them ``VALUE_PRESENT``; an
    absent field defaults to ``NOT_CAPTURED`` unless the caller declares a more
    specific state (e.g. ``NOT_APPLICABLE``).
    """

    availability: dict[str, Any] = {}
    for field_name in AVAILABILITY_TRACKED_FIELDS:
        if presents.get(field_name) is not None:
            continue
        availability[field_name] = absent_states.get(
            field_name, AvailabilityState.NOT_CAPTURED.value
        )
    return availability


def completed_trade_evidence(
    record: Mapping[str, Any],
    *,
    mode: Optional[str] = None,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
    truth_level: Any = TruthLevel.CURRENT_SOURCE_RUNTIME,
    verified: bool = False,
) -> EvidenceEnvelope:
    """Project one canonical Stage 13 completed-trade record into an envelope.

    The Stage 13 record remains the canonical trade history authority; this
    envelope only references it (``source_record_id`` = ``recordId``) and
    preserves the cycle/trade/revision links it already declares.
    """

    if not isinstance(record, Mapping):
        raise TypeError("record must be a mapping")
    resolved_mode = _first(record, "mode", "scope")
    if isinstance(resolved_mode, str):
        resolved_mode = resolved_mode.strip().upper()
    if mode is not None:
        resolved_mode = str(mode).strip().upper()
    if resolved_mode not in ("PAPER", "LIVE"):
        raise ValueError("completed-trade evidence requires mode PAPER or LIVE")

    trade_id = _first(record, "tradeId", "positionId")
    cycle_id = _first(record, "cycleId", "rankingCycleId")
    correlation_id = record.get("traceId")
    configuration_revision_id = record.get("configuredRevision")
    parameter_revision_id = _first(
        record, "effectiveRevision", "parameterRevision"
    )
    source_record_id = record.get("recordId")
    occurred_at = _first(record, "exitTimestamp", "entryTimestamp")

    presents = {
        "symbol": record.get("symbol"),
        "timeframe": record.get("timeframe"),
        "occurred_at": occurred_at,
        "cycle_id": cycle_id,
        "trade_id": trade_id,
        "correlation_id": correlation_id,
        "parent_event_id": None,
        "configuration_revision_id": configuration_revision_id,
        "parameter_revision_id": parameter_revision_id,
        "source_record_id": source_record_id,
        "task_id": task_id,
        "acceptance_id": acceptance_id,
        "commit_sha": commit_sha,
    }
    absent_states = {
        "timeframe": AvailabilityState.NOT_APPLICABLE.value,
        "parent_event_id": AvailabilityState.NOT_APPLICABLE.value,
    }

    payload = {
        "realizedPnl": record.get("realizedPnl"),
        "netPnL": _first(record, "netPnL", "realizedPnl"),
        "entryPrice": record.get("entryPrice"),
        "exitPrice": record.get("exitPrice"),
        "quantity": record.get("quantity"),
        "notional": record.get("notional"),
        "holdingMs": record.get("holdingMs"),
        "side": record.get("side"),
        "exitReason": record.get("exitReason"),
        "parameterSetId": record.get("parameterSetId"),
        "featureContract": record.get("featureContract"),
        "realizedPnlAuthoritative": record.get("realizedPnlAuthoritative"),
        "controlSource": record.get("controlSource"),
        "origin": record.get("origin"),
        "scope": record.get("scope"),
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    links = {
        "sourceRecordId": source_record_id,
        "traceId": correlation_id,
        "positionId": record.get("positionId"),
        "runtimeId": record.get("runtimeId"),
        "tradeId": trade_id,
        "cycleId": cycle_id,
    }
    links = {key: value for key, value in links.items() if value is not None}

    return build_envelope(
        evidence_type=EvidenceType.TRADE_PERFORMANCE,
        lifecycle_stage=LifecycleStage.TRADE_PARAMETER_PERFORMANCE,
        mode=resolved_mode,
        source={
            "subsystem": "STAGE_13_TRADE_HISTORY",
            "module": "backend.runtime.parameter_performance",
        },
        authority=AuthorityClass.OBSERVATION_READ_ONLY,
        payload=payload,
        links=links,
        availability=_availability(absent_states, presents),
        symbol=record.get("symbol"),
        timeframe=record.get("timeframe"),
        occurred_at=occurred_at,
        recorded_at=recorded_at,
        cycle_id=cycle_id,
        trade_id=trade_id,
        correlation_id=correlation_id,
        configuration_revision_id=configuration_revision_id,
        parameter_revision_id=parameter_revision_id,
        source_record_id=source_record_id,
        task_id=task_id,
        acceptance_id=acceptance_id,
        commit_sha=commit_sha,
        event_id=(
            f"stage13-event-{source_record_id}" if source_record_id else None
        ),
        truth_level=truth_level,
        verified=verified,
    )


def parameter_revision_evidence(
    parameter_set: Any,
    *,
    mode: Optional[str] = None,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
    truth_level: Any = TruthLevel.CANONICAL_SPECIFICATION,
    verified: bool = True,
) -> EvidenceEnvelope:
    """Project one canonical parameter revision into an envelope.

    The immutable revision archive remains the authority.  The envelope stores
    a content digest and the revision identity — never a second copy of the
    revision (contract § I.8).
    """

    if hasattr(parameter_set, "to_dict"):
        data = dict(parameter_set.to_dict())
    elif isinstance(parameter_set, Mapping):
        data = dict(parameter_set)
    else:
        raise TypeError("parameter_set must be a StrategyParameterSet or mapping")

    scope = str(data.get("scope") or "").strip().upper()
    resolved_mode = mode
    if resolved_mode is None and scope in ("PAPER", "LIVE"):
        resolved_mode = scope
    if resolved_mode is None:
        raise ValueError("mode is required when the parameter scope is BOTH")
    effective_revision = data.get("effectiveRevision")
    configured_revision = data.get("configuredRevision")

    from backend.runtime.cycle_evidence import stable_fingerprint

    parameters = data.get("parameters") or {}
    parameter_digest = stable_fingerprint(dict(parameters))

    payload = {
        "parameterSetId": data.get("parameterSetId"),
        "scope": data.get("scope"),
        "status": data.get("status"),
        "source": data.get("source"),
        "configuredRevision": configured_revision,
        "effectiveRevision": effective_revision,
        "parameterNames": sorted(str(name) for name in parameters),
        "parameterDigest": parameter_digest,
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    presents = {
        "symbol": None,
        "timeframe": None,
        "occurred_at": _first(data, "effectiveFrom", "updatedAt"),
        "cycle_id": None,
        "trade_id": None,
        "correlation_id": None,
        "parent_event_id": None,
        "configuration_revision_id": configured_revision,
        "parameter_revision_id": effective_revision,
        "source_record_id": data.get("parameterSetId"),
        "task_id": task_id,
        "acceptance_id": acceptance_id,
        "commit_sha": commit_sha,
    }
    absent_states = {
        "symbol": AvailabilityState.NOT_APPLICABLE.value,
        "timeframe": AvailabilityState.NOT_APPLICABLE.value,
        "cycle_id": AvailabilityState.NOT_APPLICABLE.value,
        "trade_id": AvailabilityState.NOT_APPLICABLE.value,
        "correlation_id": AvailabilityState.NOT_APPLICABLE.value,
        "parent_event_id": AvailabilityState.NOT_APPLICABLE.value,
    }

    return build_envelope(
        evidence_type=EvidenceType.PARAMETER_REVISION,
        lifecycle_stage=LifecycleStage.PARAMETER_CONTEXT,
        mode=resolved_mode,
        source={
            "subsystem": "PARAMETER_REVISION_ARCHIVE",
            "module": "backend.strategy.parameters.revision_archive",
        },
        authority=AuthorityClass.CONFIGURATION_AUTHORITY,
        payload=payload,
        links={
            "sourceRecordId": data.get("parameterSetId"),
            "configurationRevisionId": configured_revision,
            "parameterRevisionId": effective_revision,
        },
        availability=_availability(absent_states, presents),
        occurred_at=presents["occurred_at"],
        recorded_at=recorded_at,
        configuration_revision_id=configured_revision,
        parameter_revision_id=effective_revision,
        source_record_id=data.get("parameterSetId"),
        task_id=task_id,
        acceptance_id=acceptance_id,
        commit_sha=commit_sha,
        event_id=(
            f"param-revision-{scope}-{effective_revision}"
            if effective_revision is not None
            else None
        ),
        truth_level=truth_level,
        verified=verified,
    )


def trace_event_evidence(
    event: Mapping[str, Any],
    *,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
    truth_level: Any = TruthLevel.CURRENT_SOURCE_RUNTIME,
    verified: bool = False,
) -> EvidenceEnvelope:
    """Project one existing trading-trace event into an envelope.

    The trace writer remains canonical; this envelope references the event's
    ``eventId`` and ``traceId`` and never creates a second trace/trade store.
    """

    if not isinstance(event, Mapping):
        raise TypeError("event must be a mapping")
    stage = str(event.get("stage") or "").strip().upper()
    lifecycle = TRACE_STAGE_TO_LIFECYCLE.get(stage)
    evidence_type = TRACE_STAGE_TO_EVIDENCE_TYPE.get(stage)
    if lifecycle is None or evidence_type is None:
        raise ValueError(f"unknown trading-trace stage: {event.get('stage')!r}")
    metadata = event.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}

    trade_id = metadata.get("tradeId") or metadata.get("positionId")
    cycle_id = metadata.get("cycleId") or metadata.get("rankingCycleId")
    configuration_revision_id = metadata.get("configuredRevision")
    parameter_revision_id = metadata.get("effectiveRevision") or metadata.get(
        "parameterRevision"
    )
    event_id_value = event.get("eventId")
    correlation_id = event.get("traceId")

    presents = {
        "symbol": event.get("symbol"),
        "timeframe": event.get("timeframe"),
        "occurred_at": event.get("timestamp"),
        "cycle_id": cycle_id,
        "trade_id": trade_id,
        "correlation_id": correlation_id,
        "parent_event_id": None,
        "configuration_revision_id": configuration_revision_id,
        "parameter_revision_id": parameter_revision_id,
        "source_record_id": event_id_value,
        "task_id": task_id,
        "acceptance_id": acceptance_id,
        "commit_sha": commit_sha,
    }
    absent_states = {"parent_event_id": AvailabilityState.NOT_APPLICABLE.value}

    payload = {
        "stage": stage,
        "status": event.get("status"),
        "reasonCode": event.get("reasonCode"),
        "metadata": dict(metadata),
    }
    payload = {key: value for key, value in payload.items() if value is not None}

    links = {
        "traceId": correlation_id,
        "sourceRecordId": event_id_value,
        "runtimeId": event.get("runtimeId"),
        "observationId": event.get("observationId"),
        "decisionId": event.get("decisionId"),
        "orderId": metadata.get("orderId"),
        "exchangeOrderId": metadata.get("exchangeOrderId"),
        "positionId": metadata.get("positionId"),
        "tradeId": trade_id,
        "cycleId": cycle_id,
    }
    links = {key: value for key, value in links.items() if value is not None}

    return build_envelope(
        evidence_type=evidence_type,
        lifecycle_stage=lifecycle,
        mode=event.get("mode"),
        source={
            "subsystem": "TRADING_TRACE",
            "module": "backend.runtime.trading_trace",
        },
        authority=AuthorityClass.OBSERVATION_READ_ONLY,
        payload=payload,
        links=links,
        availability=_availability(absent_states, presents),
        symbol=event.get("symbol"),
        timeframe=event.get("timeframe"),
        occurred_at=event.get("timestamp"),
        recorded_at=recorded_at,
        cycle_id=cycle_id,
        trade_id=trade_id,
        correlation_id=correlation_id,
        configuration_revision_id=configuration_revision_id,
        parameter_revision_id=parameter_revision_id,
        source_record_id=event_id_value,
        task_id=task_id,
        acceptance_id=acceptance_id,
        commit_sha=commit_sha,
        event_id=(
            f"trace-event-{event_id_value}" if event_id_value else None
        ),
        truth_level=truth_level,
        verified=verified,
    )
