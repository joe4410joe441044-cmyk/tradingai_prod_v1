"""Phase A observational wiring of the Stage 0-5 producers to evidence.

This module connects the existing canonical cycle-evidence foundation
(:mod:`backend.runtime.cycle_evidence`) and the capture orchestrator
(:mod:`backend.runtime.cycle_evidence_capture`) to the TradingAI Stage 0-5
producers:

====== ============================= ==========================================
Stage  Producer (confirmed at HEAD)
====== ============================= ==========================================
0      Parameter context             ``RuntimeParameterSnapshot`` resolution
                                     (``bot_manager._record_observed_parameter_snapshot``)
1      AUTO market selection         ``AutoMarketSelectionRuntime._finish``
2      Market data                   confirmed ``MicrostructureStateBuilder``
                                     output at ``TradingRuntime.process_runtime``
3      Feature / detector input      the same confirmed microstructure state
4      Strategy signal / rejection   ``ExecutionRuntime`` STRATEGY record
5      AI decision (OFF)             ``ExecutionRuntime`` AI record
====== ============================= ==========================================

Authority boundaries (contract § A / § L; producer-wiring audit § 9-§ 11):

- **observation only**: every capture happens *after* the producer result is
  final.  The module never mutates a producer input/output and never
  participates in a selection, strategy, MM, Governance or execution decision.
- **non-interfering**: every public entry point swallows all errors and returns
  a structured :class:`PhaseAObservationResult`.  A capture or store failure can
  never propagate into the trading path or change its result.
- **feature-flagged**: production capture is disabled by default.  When
  ``CYCLE_EVIDENCE_PHASE_A_ENABLED`` is unset the module performs no work,
  creates no store and writes nothing.
- **single store**: it reuses :class:`CycleEvidenceStore`.  No new JSONL store,
  no second schema, no write to the trading trace or the Stage 13 store.
- **no invented identity**: an existing authority ``cycle_id`` is used when it
  exists (Stage 1, AMS).  Otherwise a clearly namespaced ``phase-a:`` correlation
  key is recorded and marked ``PHASE_A_CORRELATION_KEY``; it is never presented
  as an authority ``cycle_id``.
- **explicit availability**: every absent value is represented through the
  canonical availability states — never ``None`` and never a guess.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from backend.runtime.cycle_evidence import (
    AuthorityClass,
    AvailabilityState,
    EvidenceType,
    LifecycleStage,
    SecretPolicy,
    SecretFieldError,
    stable_fingerprint,
)
from backend.runtime.cycle_evidence_capture import (
    CaptureLifecycleState,
    CaptureOutcome,
    CycleEvidenceCapture,
)
from backend.runtime.cycle_evidence_stage_inputs import (
    StageResolutionError,
    resolve_stage,
)
from backend.runtime.cycle_evidence_store import CycleEvidenceStore

# -- feature flag ---------------------------------------------------------

PHASE_A_ENABLED_ENV = "CYCLE_EVIDENCE_PHASE_A_ENABLED"
_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})

# Phase A owns exactly Stages 0-5.  Any other stage is refused.
PHASE_A_STAGES: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
PHASE_A_STAGE_SET = frozenset(PHASE_A_STAGES)

PHASE_A_SOURCE_MODULE = "backend.runtime.cycle_evidence_phase_a"

# Cycle-id provenance marker (payload + link).  It makes the Phase A
# correlation key explicitly *not* an authority cycle id.
CYCLE_ID_SOURCE_AUTHORITY = "AUTHORITY_CYCLE_ID"
CYCLE_ID_SOURCE_PHASE_A = "PHASE_A_CORRELATION_KEY"
PHASE_A_KEY_PREFIX = "phase-a"

# Structured outcomes (never raised).
OUTCOME_DISABLED = "DISABLED"
OUTCOME_CAPTURED = "CAPTURED"
OUTCOME_DUPLICATE = "DUPLICATE"
OUTCOME_CONFLICT = "CONFLICT"
OUTCOME_REJECTED = "REJECTED"
OUTCOME_STORE_ERROR = "STORE_ERROR"
OUTCOME_OUT_OF_PHASE_A_SCOPE = "OUT_OF_PHASE_A_SCOPE"
OUTCOME_MODE_UNRESOLVED = "MODE_UNRESOLVED"
OUTCOME_OBSERVATION_FAILED = "OBSERVATION_FAILED"

REASON_DISABLED = "PHASE_A_CAPTURE_DISABLED"
REASON_OUT_OF_PHASE_A_SCOPE = "STAGE_NOT_IN_PHASE_A_SCOPE"
REASON_MODE_UNRESOLVED = "EXECUTION_MODE_UNRESOLVED"
REASON_INVALID_MODE = "INVALID_EVIDENCE_MODE"
REASON_OBSERVATION_FAILED = "PHASE_A_OBSERVATION_FAILED"

_OUTCOME_BY_CAPTURE = {
    CaptureOutcome.ACCEPTED: OUTCOME_CAPTURED,
    CaptureOutcome.DUPLICATE: OUTCOME_DUPLICATE,
    CaptureOutcome.CONFLICT: OUTCOME_CONFLICT,
    CaptureOutcome.REJECTED: OUTCOME_REJECTED,
    CaptureOutcome.STORE_ERROR: OUTCOME_STORE_ERROR,
}

_store_lock = threading.Lock()
_default_store: Optional[CycleEvidenceStore] = None


# -- feature flag + store resolution --------------------------------------


def phase_a_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return whether observational Phase A capture is explicitly enabled."""

    source = os.environ if env is None else env
    raw = source.get(PHASE_A_ENABLED_ENV)
    return str(raw).strip().lower() in _TRUTHY


def reset_phase_a_store() -> None:
    """Drop the lazily created default store (test/isolation helper)."""

    global _default_store
    with _store_lock:
        _default_store = None


def _resolve_store(store: Optional[CycleEvidenceStore]) -> CycleEvidenceStore:
    """Return the caller store, or lazily create the canonical default store.

    The default store is created only when a capture is actually attempted with
    the flag enabled, so importing this module never creates or writes a file.
    """

    if store is not None:
        if not isinstance(store, CycleEvidenceStore):
            raise TypeError("store must be a CycleEvidenceStore")
        return store
    global _default_store
    with _store_lock:
        if _default_store is None:
            _default_store = CycleEvidenceStore()
        return _default_store


# -- structured result ----------------------------------------------------

@dataclass(frozen=True)
class PhaseAObservationResult:
    """Structured, non-raising outcome of one Phase A observation attempt."""

    stage: Optional[int]
    outcome: str
    reason: str
    enabled: bool = False
    captured: bool = False
    evidence_id: Optional[str] = None
    error: Optional[str] = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.outcome in (OUTCOME_CAPTURED, OUTCOME_DUPLICATE)


@dataclass(frozen=True)
class StageObservation:
    """A pure, already-adapted one-stage observation (no persistence)."""

    stage: int
    evidence_type: EvidenceType
    status: CaptureLifecycleState
    mode: Optional[str]
    payload: Mapping[str, Any]
    availability: Mapping[str, Any] = field(default_factory=dict)
    links: Mapping[str, Any] = field(default_factory=dict)
    symbol: Optional[str] = None
    timeframe: Optional[str] = None
    occurred_at: Optional[str] = None
    event_key: Optional[str] = None
    cycle_id: Optional[str] = None
    cycle_id_source: str = CYCLE_ID_SOURCE_PHASE_A
    correlation_id: Optional[str] = None
    configuration_revision_id: Optional[str] = None
    parameter_revision_id: Optional[str] = None
    stage_name: Optional[str] = None
    source: Optional[Mapping[str, Any]] = None
    authority: AuthorityClass = AuthorityClass.OBSERVATION_READ_ONLY


# -- small helpers --------------------------------------------------------


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _as_mapping(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            data = to_dict()
        except Exception:  # noqa: BLE001 - a broken producer is not our failure
            return {}
        return dict(data) if isinstance(data, Mapping) else {}
    return {}


def _text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _compact(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded, JSON-friendly view of a possibly large structure."""

    if depth > 3:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        bounded: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item))[:25]:
            bounded[str(key)] = _compact(value[key], depth=depth + 1)
        return bounded
    if isinstance(value, (list, tuple)):
        return [_compact(item, depth=depth + 1) for item in value[:25]]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _present(mapping: Mapping[str, Any]) -> dict:
    return {key: value for key, value in mapping.items() if value is not None}


def _fingerprint(value: Any, *, fallback: str) -> str:
    try:
        return stable_fingerprint(value)
    except Exception:  # noqa: BLE001 - a non-canonical value never blocks capture
        return fallback


def _normalize_evidence_mode(value: Any) -> Optional[str]:
    text = str(value or "").strip().upper()
    if text in ("PAPER", "AUTO_PAPER", "PAPER_ONLY"):
        return "PAPER"
    if text in ("LIVE", "AUTO_LIVE", "LIVE_ONLY"):
        return "LIVE"
    return None


def build_phase_a_cycle_key(
    stage: Any,
    *,
    authority_cycle_id: Any = None,
    trace_id: Any = None,
    discriminator: Any = None,
) -> tuple[Optional[str], str]:
    """Return ``(cycle_key, cycle_id_source)`` without inventing authority ids."""

    authority = _text(authority_cycle_id)
    if authority is not None:
        return authority, CYCLE_ID_SOURCE_AUTHORITY
    try:
        stage_number = int(stage)
    except (TypeError, ValueError):
        stage_number = -1
    parts = [PHASE_A_KEY_PREFIX, f"s{stage_number}"]
    trace = _text(trace_id)
    if trace is not None:
        parts.append(f"t{trace}")
    disc = _text(discriminator)
    if disc is not None:
        parts.append(disc)
    if len(parts) == 2:
        parts.append("unidentified")
    return ":".join(parts), CYCLE_ID_SOURCE_PHASE_A


# -- Stage 0: Parameter context -------------------------------------------


def parameter_context_observation(
    scope: Any,
    snapshot: Any,
    *,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> StageObservation:
    """Link a resolved canonical parameter snapshot without duplicating it."""

    data = _as_mapping(snapshot)
    parameters = data.get("parameters")
    parameter_digest = None
    parameter_names: list[str] = []
    if isinstance(parameters, Mapping):
        try:
            parameter_digest = stable_fingerprint(
                {str(name): value for name, value in parameters.items()}
            )
        except Exception:  # noqa: BLE001
            parameter_digest = None
        parameter_names = sorted(str(name) for name in parameters)

    parameter_set_id = _first(data, "parameterSetId", "parameter_set_id")
    configured = _first(data, "configuredRevision", "configured_revision")
    effective = _first(data, "effectiveRevision", "effective_revision")
    occurred = _first(data, "capturedAt", "updatedAt", "effectiveFrom")
    mode = _normalize_evidence_mode(scope)

    payload = _present(
        {
            "parameterSetId": parameter_set_id,
            "scope": data.get("scope"),
            "source": data.get("source"),
            "configuredRevision": configured,
            "effectiveRevision": effective,
            "authorityStatus": data.get("authorityStatus"),
            "storeStatus": data.get("storeStatus"),
            "parameterSetStatus": data.get("parameterSetStatus"),
            "featureContract": data.get("featureContract"),
            "capturedAt": data.get("capturedAt"),
            "parameterDigest": parameter_digest,
            "parameterNames": parameter_names or None,
            "strategyRevision": None,
        }
    )
    cycle_key, source = build_phase_a_cycle_key(
        0, discriminator=f"{scope}-{parameter_set_id}-{effective}"
    )
    return StageObservation(
        stage=int(LifecycleStage.PARAMETER_CONTEXT),
        evidence_type=EvidenceType.PARAMETER_REVISION,
        status=CaptureLifecycleState.COMPLETED,
        mode=mode,
        payload=payload,
        availability={
            "symbol": AvailabilityState.NOT_APPLICABLE.value,
            "timeframe": AvailabilityState.NOT_APPLICABLE.value,
            "trade_id": AvailabilityState.NOT_APPLICABLE.value,
            "correlation_id": AvailabilityState.NOT_APPLICABLE.value,
            "strategyRevision": AvailabilityState.NOT_CAPTURED.value,
            "parameterDigest": (
                AvailabilityState.NOT_CAPTURED.value
                if parameter_digest is None
                else AvailabilityState.VALUE_PRESENT.value
            ),
        },
        links=_present(
            {
                "configurationRevisionId": configured,
                "parameterRevisionId": effective,
                "sourceRecordId": parameter_set_id,
                "parameterSetId": parameter_set_id,
            }
        ),
        occurred_at=occurred,
        event_key=f"parameter-context-{scope}-{effective}-{parameter_set_id}",
        cycle_id=cycle_key,
        cycle_id_source=source,
        configuration_revision_id=configured,
        parameter_revision_id=effective,
        source={
            "subsystem": "PARAMETER_CONTEXT",
            "module": "backend.strategy.parameters.resolver",
        },
        stage_name="PARAMETER_CONTEXT",
        authority=AuthorityClass.OBSERVATION_READ_ONLY,
    )


# -- Stage 1: AUTO market selection ---------------------------------------


def _market_selection_status(status: Any) -> CaptureLifecycleState:
    text = str(status or "").strip().upper()
    if text in ("COMPLETED", "NO_SWITCH_REQUIRED"):
        return CaptureLifecycleState.COMPLETED
    if text in ("NO_ELIGIBLE_MARKET", "NO_RANKABLE_MARKET", "SWITCH_BLOCKED"):
        return CaptureLifecycleState.REJECTED
    if text == "FAILED":
        return CaptureLifecycleState.FAILED
    return CaptureLifecycleState.PARTIAL


def market_selection_observation(
    result: Any,
    *,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> StageObservation:
    """Observe one finalized AMS cycle result; never re-selects a market."""

    data = _as_mapping(result)
    cycle_id = _first(data, "autoSelectionCycleId", "auto_selection_cycle_id")
    mode = _normalize_evidence_mode(data.get("mode"))
    status = _market_selection_status(data.get("status"))
    selected = _first(
        data,
        "finalActiveSymbol",
        "currentActiveSymbol",
        "proposedSymbol",
        "topCandidateSymbol",
    )
    reason_codes = data.get("reasonCodes")
    if isinstance(reason_codes, (list, tuple)):
        reason_codes = [str(item) for item in reason_codes]
    elif reason_codes is None:
        reason_codes = None
    else:
        reason_codes = [str(reason_codes)]

    payload = _present(
        {
            "autoSelectionCycleId": cycle_id,
            "mode": data.get("mode"),
            "status": data.get("status"),
            "currentActiveSymbol": data.get("currentActiveSymbol"),
            "topCandidateSymbol": data.get("topCandidateSymbol"),
            "proposedSymbol": data.get("proposedSymbol"),
            "finalActiveSymbol": data.get("finalActiveSymbol"),
            "selectedSymbol": selected,
            "selectionMode": data.get("mode"),
            "scannerCycleId": data.get("scannerCycleId"),
            "rankingCycleId": data.get("rankingCycleId"),
            "auditEventId": data.get("auditEventId"),
            "selectionProposalId": data.get("selectionProposalId"),
            "switchTransactionId": data.get("switchTransactionId"),
            "reasonCodes": reason_codes,
            "startedAt": data.get("startedAt"),
            "evaluatedAt": data.get("evaluatedAt"),
        }
    )
    occurred = _first(data, "evaluatedAt", "startedAt")
    return StageObservation(
        stage=int(LifecycleStage.MARKET_SELECTION),
        evidence_type=EvidenceType.AUTO_CANDIDATE_SELECTION,
        status=status,
        mode=mode,
        payload=payload,
        availability={
            "timeframe": AvailabilityState.NOT_APPLICABLE.value,
            "trade_id": AvailabilityState.NOT_APPLICABLE.value,
            "correlation_id": AvailabilityState.NOT_CAPTURED.value,
        },
        links=_present(
            {
                "cycleId": cycle_id,
                "sourceRecordId": cycle_id,
                "scannerCycleId": data.get("scannerCycleId"),
                "rankingCycleId": data.get("rankingCycleId"),
                "selectionProposalId": data.get("selectionProposalId"),
                "switchTransactionId": data.get("switchTransactionId"),
            }
        ),
        symbol=selected,
        occurred_at=occurred,
        event_key=f"market-selection-{cycle_id}",
        cycle_id=cycle_id,
        cycle_id_source=(
            CYCLE_ID_SOURCE_AUTHORITY if cycle_id else CYCLE_ID_SOURCE_PHASE_A
        ),
        source={
            "subsystem": "AUTO_MARKET_SELECTION",
            "module": "backend.auto_market_selection.auto_selection_runtime",
        },
        stage_name="MARKET_SELECTION",
    )


# -- Stage 2: Market data -------------------------------------------------


_MARKET_CONTEXT_FIELDS = (
    "buyPressure",
    "sellPressure",
    "pressureDiff",
    "strategyBidTotal",
    "strategyAskTotal",
    "strategyTotalVolume",
    "spread",
    "minIncludedBid",
    "maxIncludedAsk",
    "orderbookAggregationMode",
    "orderbookAggregationDepth",
)


def market_context_observation(
    microstructure_state: Any,
    *,
    runtime: Any = None,
    mode: Any = None,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> StageObservation:
    """Observe confirmed market-data metadata; no raw order book is copied."""

    data = _as_mapping(microstructure_state)
    resolved_mode = _normalize_evidence_mode(mode) or _resolve_runtime_mode(runtime)
    symbol = _first(data, "symbol", "activeSymbol")
    timeframe = data.get("timeframe")
    market = {key: data.get(key) for key in _MARKET_CONTEXT_FIELDS}
    parameters = data.get("parameterAuthority")
    if isinstance(parameters, Mapping):
        market["parameterSetId"] = parameters.get("parameterSetId")
        market["effectiveRevision"] = parameters.get("effectiveRevision")
    payload = _present(
        {
            "symbol": symbol,
            "marketFields": _present(market) or None,
            "runtimeId": data.get("runtimeId"),
            "marketDataSource": None,
            "marketUpdateTime": None,
            "marketFreshness": None,
        }
    )
    discriminator = (
        _fingerprint(_present(market), fallback="unfingerprintable-market")
        if market
        else "no-market-fields"
    )
    cycle_key, source = build_phase_a_cycle_key(
        2, discriminator=discriminator[:24]
    )
    return StageObservation(
        stage=int(LifecycleStage.MARKET_DATA),
        evidence_type=EvidenceType.MARKET_CONTEXT,
        status=CaptureLifecycleState.COMPLETED,
        mode=resolved_mode,
        payload=payload,
        availability={
            "timeframe": AvailabilityState.NOT_APPLICABLE.value,
            "trade_id": AvailabilityState.NOT_APPLICABLE.value,
            "correlation_id": AvailabilityState.NOT_CAPTURED.value,
            "parent_event_id": AvailabilityState.NOT_APPLICABLE.value,
            "marketDataSource": AvailabilityState.NOT_CAPTURED.value,
            "marketUpdateTime": AvailabilityState.NOT_CAPTURED.value,
            "marketFreshness": AvailabilityState.NOT_CAPTURED.value,
        },
        links=_present(
            {
                "runtimeId": data.get("runtimeId"),
                "parameterRevisionId": (
                    parameters.get("effectiveRevision")
                    if isinstance(parameters, Mapping)
                    else None
                ),
            }
        ),
        symbol=symbol,
        timeframe=timeframe,
        event_key=f"market-context-{discriminator[:24]}",
        cycle_id=cycle_key,
        cycle_id_source=source,
        parameter_revision_id=(
            _text(parameters.get("effectiveRevision"))
            if isinstance(parameters, Mapping)
            else None
        ),
        source={
            "subsystem": "MICROSTRUCTURE_MARKET_DATA",
            "module": "backend.aggregation.MicrostructureStateBuilder",
        },
        stage_name="MARKET_DATA",
    )


# -- Stage 3: Feature / detector input ------------------------------------


_FEATURE_FIELDS = (
    "featureContract",
    "imbalanceStrength",
    "momentumPersistence",
    "normalizedMomentum",
    "momentumDirection",
    "directionPurity",
    "normalizedSpreadQuality",
    "normalizedLiquidityQuality",
    "triggeredReasons",
)


def feature_evidence_observation(
    microstructure_state: Any,
    *,
    runtime: Any = None,
    mode: Any = None,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> StageObservation:
    """Observe confirmed feature/detector output; detectors are not re-run."""

    data = _as_mapping(microstructure_state)
    resolved_mode = _normalize_evidence_mode(mode) or _resolve_runtime_mode(runtime)
    symbol = _first(data, "symbol", "activeSymbol")
    features = _present({key: data.get(key) for key in _FEATURE_FIELDS})
    detector_details = data.get("detectorDetails")
    momentum_features = data.get("strategyMomentumFeatures")
    payload = _present(
        {
            "symbol": symbol,
            "features": features or None,
            "detectorDetails": (
                _compact(detector_details) if detector_details is not None else None
            ),
            "strategyMomentumFeatures": (
                _compact(momentum_features) if momentum_features is not None else None
            ),
            "runtimeId": data.get("runtimeId"),
        }
    )
    discriminator = (
        _fingerprint(features, fallback="unfingerprintable-features")
        if features
        else "no-feature-fields"
    )
    cycle_key, source = build_phase_a_cycle_key(
        3, discriminator=discriminator[:24]
    )
    return StageObservation(
        stage=int(LifecycleStage.FEATURE_BUILDER),
        evidence_type=EvidenceType.FEATURE_EVIDENCE,
        status=CaptureLifecycleState.COMPLETED,
        mode=resolved_mode,
        payload=payload,
        availability={
            "timeframe": AvailabilityState.NOT_APPLICABLE.value,
            "trade_id": AvailabilityState.NOT_APPLICABLE.value,
            "correlation_id": AvailabilityState.NOT_CAPTURED.value,
            "parent_event_id": AvailabilityState.NOT_APPLICABLE.value,
            "detectorDetails": (
                AvailabilityState.NOT_CAPTURED.value
                if detector_details is None
                else AvailabilityState.VALUE_PRESENT.value
            ),
        },
        links=_present({"runtimeId": data.get("runtimeId")}),
        symbol=symbol,
        timeframe=data.get("timeframe"),
        event_key=f"feature-evidence-{discriminator[:24]}",
        cycle_id=cycle_key,
        cycle_id_source=source,
        source={
            "subsystem": "MICROSTRUCTURE_FEATURES",
            "module": "backend.aggregation.MicrostructureStateBuilder",
        },
        stage_name="FEATURE_BUILDER",
    )


# -- Stage 4: Strategy signal ---------------------------------------------


_STRATEGY_FIELDS = (
    "decision",
    "direction",
    "confidence",
    "executionAllowed",
    "suppressionReason",
    "reasonCode",
    "featureContract",
    "normalizedMomentum",
    "momentumDirection",
    "directionPurity",
    "entryReadiness",
    "parameterAuthority",
)


def strategy_signal_observation(
    strategy_state: Any,
    *,
    trace_id: Any = None,
    mode: Any = None,
    symbol: Any = None,
    status: Any = None,
    reason: Any = None,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> StageObservation:
    """Observe a finalized strategy signal/rejection; never alters it."""

    data = _as_mapping(strategy_state)
    resolved_mode = _normalize_evidence_mode(mode)
    resolved_symbol = _text(symbol) or _first(data, "symbol", "activeSymbol")
    trace = _text(trace_id) or _text(data.get("traceId"))
    parameters = data.get("parameterAuthority")
    parameter_revision = None
    configuration_revision = None
    if isinstance(parameters, Mapping):
        parameter_revision = _text(parameters.get("effectiveRevision"))
        configuration_revision = _text(parameters.get("configuredRevision"))
    payload = _present(
        {
            "decision": _first(data, "decision", "direction"),
            "direction": data.get("direction"),
            "status": status,
            "confidence": data.get("confidence"),
            "executionAllowed": data.get("executionAllowed"),
            "suppressionReason": _first(data, "suppressionReason", "reasonCode"),
            "reason": _text(reason),
            "signal": _compact(
                _present({key: data.get(key) for key in _STRATEGY_FIELDS})
            ),
            "strategyRevision": None,
        }
    )
    status_state = (
        CaptureLifecycleState.BLOCKED
        if str(status or "").strip().upper() in ("HOLD", "BLOCKED", "REJECTED")
        else CaptureLifecycleState.COMPLETED
    )
    cycle_key, source = build_phase_a_cycle_key(4, trace_id=trace)
    return StageObservation(
        stage=int(LifecycleStage.MICRO_EDGE_STRATEGY),
        evidence_type=EvidenceType.STRATEGY_SIGNAL,
        status=status_state,
        mode=resolved_mode,
        payload=payload,
        availability={
            "timeframe": AvailabilityState.NOT_APPLICABLE.value,
            "trade_id": AvailabilityState.NOT_CAPTURED.value,
            "strategyRevision": AvailabilityState.NOT_CAPTURED.value,
        },
        links=_present(
            {
                "traceId": trace,
                "parameterRevisionId": parameter_revision,
                "configurationRevisionId": configuration_revision,
            }
        ),
        symbol=resolved_symbol,
        event_key=f"strategy-signal-{trace}" if trace else None,
        cycle_id=cycle_key,
        cycle_id_source=source,
        correlation_id=trace,
        configuration_revision_id=configuration_revision,
        parameter_revision_id=parameter_revision,
        source={
            "subsystem": "MICRO_EDGE_STRATEGY",
            "module": "backend.strategy.MicrostructureEdgeStrategy",
        },
        stage_name="MICRO_EDGE_STRATEGY",
    )


# -- Stage 5: AI decision (TradingAI OFF) ---------------------------------


def ai_decision_observation(
    *,
    trace_id: Any = None,
    mode: Any = None,
    symbol: Any = None,
    recorded_at: Optional[str] = None,
    task_id: Optional[str] = None,
    acceptance_id: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> StageObservation:
    """Observe the constant TradingAI OFF decision (no AI authority exists)."""

    resolved_mode = _normalize_evidence_mode(mode)
    trace = _text(trace_id)
    cycle_key, source = build_phase_a_cycle_key(5, trace_id=trace)
    return StageObservation(
        stage=int(LifecycleStage.AI_DECISION_REVIEW),
        evidence_type=EvidenceType.AI_DECISION,
        status=CaptureLifecycleState.COMPLETED,
        mode=resolved_mode,
        payload={
            "mode": "OFF",
            "implementationStatus": "NOT_INSTALLED",
            "required": False,
            "fallback": None,
            "reasonCode": "TRADING_AI_OFF",
            "aiRuntimeReached": False,
            "strategyRevision": None,
        },
        availability={
            "timeframe": AvailabilityState.NOT_APPLICABLE.value,
            "trade_id": AvailabilityState.NOT_CAPTURED.value,
            "strategyRevision": AvailabilityState.NOT_CAPTURED.value,
        },
        links=_present({"traceId": trace}),
        symbol=_text(symbol),
        event_key=f"ai-decision-{trace}" if trace else None,
        cycle_id=cycle_key,
        cycle_id_source=source,
        correlation_id=trace,
        source={
            "subsystem": "AI_DECISION",
            "module": "backend.runtime.ExecutionRuntime",
        },
        stage_name="AI_DECISION_REVIEW",
    )


# -- runtime mode resolution ----------------------------------------------


def _resolve_runtime_mode(runtime: Any) -> Optional[str]:
    """Resolve PAPER/LIVE from a runtime without falling back to a guess."""

    if runtime is None:
        return None
    execution_runtime = getattr(runtime, "execution_runtime", runtime)
    resolver = getattr(execution_runtime, "_authoritative_execution_mode", None)
    if not callable(resolver):
        return None
    try:
        return _normalize_evidence_mode(resolver())
    except Exception:  # noqa: BLE001
        return None


# -- capture core (never raises) ------------------------------------------


def capture_stage_observation(
    observation: StageObservation,
    *,
    store: Optional[CycleEvidenceStore] = None,
    enabled: Optional[bool] = None,
    secret_policy: Any = SecretPolicy.REDACT,
) -> PhaseAObservationResult:
    """Public, non-raising entry point for a pre-adapted observation."""

    return _capture_observation(
        observation, store=store, enabled=enabled, secret_policy=secret_policy
    )


def _capture_observation(
    observation: StageObservation,
    *,
    store: Optional[CycleEvidenceStore] = None,
    enabled: Optional[bool] = None,
    secret_policy: Any = SecretPolicy.REDACT,
) -> PhaseAObservationResult:
    """Persist one adapted observation; all errors become structured results."""

    stage_number: Optional[int] = observation.stage
    try:
        resolved_enabled = phase_a_enabled() if enabled is None else bool(enabled)
        if not resolved_enabled:
            return PhaseAObservationResult(
                stage=stage_number,
                outcome=OUTCOME_DISABLED,
                reason=REASON_DISABLED,
                enabled=False,
            )

        try:
            definition = resolve_stage(
                stage=observation.stage, stage_name=observation.stage_name
            )
        except StageResolutionError as exc:
            return PhaseAObservationResult(
                stage=stage_number,
                outcome=OUTCOME_REJECTED,
                reason="STAGE_RESOLUTION_FAILED",
                enabled=True,
                error=str(exc),
            )
        stage_number = definition.number
        if definition.number not in PHASE_A_STAGE_SET:
            return PhaseAObservationResult(
                stage=definition.number,
                outcome=OUTCOME_OUT_OF_PHASE_A_SCOPE,
                reason=REASON_OUT_OF_PHASE_A_SCOPE,
                enabled=True,
            )
        if observation.mode not in ("PAPER", "LIVE"):
            return PhaseAObservationResult(
                stage=definition.number,
                outcome=OUTCOME_MODE_UNRESOLVED,
                reason=REASON_INVALID_MODE,
                enabled=True,
            )
        if not isinstance(observation.cycle_id, str) or not observation.cycle_id:
            return PhaseAObservationResult(
                stage=definition.number,
                outcome=OUTCOME_REJECTED,
                reason="CYCLE_KEY_REQUIRED",
                enabled=True,
            )

        payload = dict(observation.payload)
        payload.setdefault("evidencePhase", "PHASE_A")
        payload["cycleIdSource"] = observation.cycle_id_source

        links = dict(observation.links)
        if observation.cycle_id_source == CYCLE_ID_SOURCE_PHASE_A:
            links.setdefault("phaseACorrelationKey", observation.cycle_id)

        resolved_store = _resolve_store(store)
        session = CycleEvidenceCapture(
            resolved_store,
            cycle_id=observation.cycle_id,
            mode=observation.mode,
            correlation_id=observation.correlation_id,
            symbol=observation.symbol,
            timeframe=observation.timeframe,
            configuration_revision_id=observation.configuration_revision_id,
            parameter_revision_id=observation.parameter_revision_id,
            authority=observation.authority,
            secret_policy=secret_policy,
        )
        result = session.capture_stage(
            definition.number,
            evidence_type=observation.evidence_type,
            status=observation.status,
            stage_name=definition.name,
            payload=payload,
            availability=dict(observation.availability),
            links=links,
            occurred_at=observation.occurred_at,
            event_key=observation.event_key,
            source=observation.source,
            authority=observation.authority,
            secret_policy=secret_policy,
        )
        return PhaseAObservationResult(
            stage=definition.number,
            outcome=_OUTCOME_BY_CAPTURE.get(result.outcome, OUTCOME_REJECTED),
            reason=result.reason,
            enabled=True,
            captured=result.persisted,
            evidence_id=result.evidence_id,
            error=result.error,
        )
    except SecretFieldError as exc:
        return PhaseAObservationResult(
            stage=stage_number,
            outcome=OUTCOME_REJECTED,
            reason="SECRET_FIELD_REJECTED",
            enabled=True,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - observation must never propagate
        return PhaseAObservationResult(
            stage=stage_number,
            outcome=OUTCOME_OBSERVATION_FAILED,
            reason=REASON_OBSERVATION_FAILED,
            enabled=True,
            error=str(exc),
        )


# -- public, non-raising entry points -------------------------------------


def _disabled(stage: Optional[int]) -> PhaseAObservationResult:
    return PhaseAObservationResult(
        stage=stage, outcome=OUTCOME_DISABLED, reason=REASON_DISABLED, enabled=False
    )


def observe_parameter_context(scope, snapshot, **kwargs) -> PhaseAObservationResult:
    store = kwargs.pop("store", None)
    enabled = kwargs.pop("enabled", None)
    if not (phase_a_enabled() if enabled is None else bool(enabled)):
        return _disabled(0)
    try:
        return _capture_observation(
            parameter_context_observation(scope, snapshot, **kwargs),
            store=store,
            enabled=True,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(0, exc, enabled)


def observe_market_selection(result, **kwargs) -> PhaseAObservationResult:
    store = kwargs.pop("store", None)
    enabled = kwargs.pop("enabled", None)
    if not (phase_a_enabled() if enabled is None else bool(enabled)):
        return _disabled(1)
    try:
        return _capture_observation(
            market_selection_observation(result, **kwargs),
            store=store,
            enabled=True,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(1, exc, enabled)


def observe_market_context(microstructure_state, **kwargs) -> PhaseAObservationResult:
    store = kwargs.pop("store", None)
    enabled = kwargs.pop("enabled", None)
    if not (phase_a_enabled() if enabled is None else bool(enabled)):
        return _disabled(2)
    try:
        return _capture_observation(
            market_context_observation(microstructure_state, **kwargs),
            store=store,
            enabled=True,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(2, exc, enabled)


def observe_feature_evidence(microstructure_state, **kwargs) -> PhaseAObservationResult:
    store = kwargs.pop("store", None)
    enabled = kwargs.pop("enabled", None)
    if not (phase_a_enabled() if enabled is None else bool(enabled)):
        return _disabled(3)
    try:
        return _capture_observation(
            feature_evidence_observation(microstructure_state, **kwargs),
            store=store,
            enabled=True,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(3, exc, enabled)


def observe_strategy_signal(strategy_state, **kwargs) -> PhaseAObservationResult:
    store = kwargs.pop("store", None)
    enabled = kwargs.pop("enabled", None)
    if not (phase_a_enabled() if enabled is None else bool(enabled)):
        return _disabled(4)
    try:
        return _capture_observation(
            strategy_signal_observation(strategy_state, **kwargs),
            store=store,
            enabled=True,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(4, exc, enabled)


def observe_ai_decision(**kwargs) -> PhaseAObservationResult:
    store = kwargs.pop("store", None)
    enabled = kwargs.pop("enabled", None)
    if not (phase_a_enabled() if enabled is None else bool(enabled)):
        return _disabled(5)
    try:
        return _capture_observation(
            ai_decision_observation(**kwargs),
            store=store,
            enabled=True,
        )
    except Exception as exc:  # noqa: BLE001
        return _failed(5, exc, enabled)


def _failed(stage: Optional[int], exc: Exception, enabled: Optional[bool]) -> PhaseAObservationResult:
    return PhaseAObservationResult(
        stage=stage,
        outcome=OUTCOME_OBSERVATION_FAILED,
        reason=REASON_OBSERVATION_FAILED,
        enabled=bool(enabled),
        error=str(exc),
    )
