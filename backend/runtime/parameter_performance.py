"""Stage 13 completed-trade parameter-performance record (E-PERF-2).

This module is the durable, observational Work E history that connects a
completed trade to the parameter authority it was observed under.  It is
deliberately small and non-authoritative:

- it never participates in an execution, close, sizing, MM, Governance or
  market-selection decision;
- writing a record can never change trading behavior (best-effort, read-only
  for every consumer);
- it does not rank, score or recommend a parameter revision.

Mixed parameter semantics are preserved explicitly.  The entry snapshot is the
authority resolved at the entry decision boundary.  Only the exit-threshold
parameters were consumed as an immutable entry snapshot by the exit evaluator;
the remaining parameters were read from the current runtime authority during
the trade and are NOT represented as frozen values.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional
from uuid import uuid4

STAGE13_SCHEMA_VERSION = 1
PARAMETER_PERFORMANCE_PATH_ENV = "PARAMETER_PERFORMANCE_PATH"
DEFAULT_PARAMETER_PERFORMANCE_PATH = "logs/runtime/parameter_performance.jsonl"

# Parameters consumed as an immutable ENTRY snapshot (the exit evaluator reads
# the position's bound snapshot, not the current cycle authority).
ENTRY_SNAPSHOT_PARAMETERS = (
    "minimumHoldMs",
    "maximumHoldMs",
    "exitMomentumMinimum",
    "exitLiquidityQualityMinimum",
    "exitSpreadQualityMinimum",
)

# Parameters read from the CURRENT runtime authority during the trade (entry
# gates and per-cycle feature recomputation).  They must not be presented as
# frozen entry values.
DYNAMIC_AUTHORITY_PARAMETERS = (
    "minimumCompositeScore",
    "maximumStrategySpreadPct",
    "momentumWindowSeconds",
    "minimumStrategyConfidence",
    "momentumMinimumWarmupSeconds",
    "absorptionVolumePercentile",
    "liquidityQualityPercentile",
)

PARAMETER_SNAPSHOT_SEMANTICS = "ENTRY_AUTHORITY_AT_DECISION_BOUNDARY"
PARAMETER_SEMANTICS_NOTE = (
    "parameterSnapshot is the canonical parameter authority resolved at the "
    "ENTRY decision boundary. entrySnapshotParameters were consumed as an "
    "immutable entry snapshot by the exit evaluator; dynamicAuthorityParameters "
    "were read from the current runtime authority during the trade and were NOT "
    "frozen at entry."
)

# ---------------------------------------------------------------------------
# Durable provenance / eligibility contract
# ---------------------------------------------------------------------------
# A completed-trade record carries an explicit ``origin`` so the read layer can
# distinguish a real Production runtime trade from a test / fixture / synthetic
# record WITHOUT ever inferring provenance from the tradeId string and WITHOUT
# assuming PAPER == TEST.  A Production PAPER simulation trade is valid
# Production history.
#
#   origin = "PRODUCTION"      -> real runtime completed trade
#   origin = "NON_PRODUCTION"  -> test / fixture / synthetic / non-production
#
# The origin is resolved once, at write time, from an explicit, injectable
# signal.  It is never recomputed at read time.  ``PARAMETER_PERFORMANCE_ORIGIN``
# is the explicit override; otherwise ``TEST_MODE`` marks non-production.  The
# production service does not set TEST_MODE, so runtime records default to
# PRODUCTION.
#
# Records persisted before this field existed have ``origin`` absent.  They are
# treated as legacy and are eligible for Production Parameter Performance only
# when they carry a provable parameter revision identity (an integer
# ``effectiveRevision``).  That deterministic rule preserves the confirmed real
# PAPER R3 records while excluding the confirmed legacy null-revision test
# records.  It is not tradeId-based and does not make the null-revision test
# records eligible.
ORIGIN_FIELD = "origin"
ORIGIN_ENV = "PARAMETER_PERFORMANCE_ORIGIN"
ORIGIN_PRODUCTION = "PRODUCTION"
ORIGIN_NON_PRODUCTION = "NON_PRODUCTION"
SUPPORTED_ORIGINS = (ORIGIN_PRODUCTION, ORIGIN_NON_PRODUCTION)

# ---------------------------------------------------------------------------
# Control-source contract
# ---------------------------------------------------------------------------
# A completed-trade record carries an explicit ``controlSource`` describing who
# controlled the ENTRY of the trade:
#
#   controlSource = "BOT"     -> automatic strategy entry (default runtime)
#   controlSource = "MANUAL"  -> human MANUAL entry authority
#
# The value is normalized once, at write time, from an explicit source field.
# It is never inferred from the tradeId string and it is never recomputed at
# read time.  Legacy records written before this field existed have no
# ``controlSource``; they are reported as unavailable rather than assumed BOT.
CONTROL_SOURCE_FIELD = "controlSource"
CONTROL_SOURCE_BOT = "BOT"
CONTROL_SOURCE_MANUAL = "MANUAL"
SUPPORTED_CONTROL_SOURCES = (CONTROL_SOURCE_BOT, CONTROL_SOURCE_MANUAL)
_CONTROL_SOURCE_MANUAL_ALIASES = ("MANUAL", "HUMAN")
_CONTROL_SOURCE_BOT_ALIASES = ("BOT", "AUTO", "AUTOMATIC", "STRATEGY")


def resolve_record_origin() -> str:
    """Resolve the durable origin for a newly written completed-trade record."""

    explicit = os.environ.get(ORIGIN_ENV)
    if isinstance(explicit, str):
        normalized = explicit.strip().upper()
        if normalized in SUPPORTED_ORIGINS:
            return normalized
    test_mode = str(os.environ.get("TEST_MODE", "")).strip().lower()
    if test_mode not in ("", "0", "false", "no", "off"):
        return ORIGIN_NON_PRODUCTION
    return ORIGIN_PRODUCTION


def is_production_eligible(record: Mapping[str, Any]) -> bool:
    """Return whether a completed-trade record is Production Parameter evidence.

    Deterministic and durable:

    - explicit ``origin == "PRODUCTION"`` is eligible;
    - explicit ``origin == "NON_PRODUCTION"`` is never eligible;
    - a legacy record (no ``origin``) is eligible only when it carries a
      provable integer ``effectiveRevision`` (revision identity).  This is the
      backward-compatible rule for records written before provenance existed.

    Provenance is never inferred from ``tradeId`` naming.
    """

    if not isinstance(record, Mapping):
        return False
    origin = record.get(ORIGIN_FIELD)
    if origin == ORIGIN_PRODUCTION:
        return True
    if ORIGIN_FIELD in record:
        # Explicit TEST/unknown provenance must never use the legacy rule.
        return False
    revision = record.get("effectiveRevision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        return False
    return True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parameter_values(snapshot: Any) -> Optional[dict]:
    if not isinstance(snapshot, Mapping):
        return None
    parameters = snapshot.get("parameters")
    if not isinstance(parameters, Mapping):
        return None
    values = {}
    for name, entry in parameters.items():
        if isinstance(entry, Mapping):
            values[str(name)] = entry.get("value")
        else:
            values[str(name)] = entry
    return values or None


def _first(record: Mapping[str, Any], keys) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None:
            return value
    return None


def normalize_control_source(record: Mapping[str, Any]) -> str:
    """Normalize the entry control source to ``BOT`` / ``MANUAL`` / ``UNKNOWN``.

    Accepts the canonical ``controlSource`` plus the engine's ``entryAuthority``
    / ``entry_authority`` signals.  An absent or unrecognized value returns
    ``UNKNOWN`` (unavailable); it is never guessed.
    """

    if not isinstance(record, Mapping):
        return "UNKNOWN"
    raw = _first(
        record,
        (
            CONTROL_SOURCE_FIELD,
            "control_source",
            "entryAuthority",
            "entry_authority",
        ),
    )
    if not isinstance(raw, str):
        return "UNKNOWN"
    normalized = raw.strip().upper()
    if normalized in _CONTROL_SOURCE_MANUAL_ALIASES:
        return CONTROL_SOURCE_MANUAL
    if normalized in _CONTROL_SOURCE_BOT_ALIASES:
        return CONTROL_SOURCE_BOT
    return "UNKNOWN"


def build_completed_trade_record(
    source_record: Mapping[str, Any],
    *,
    recorded_at: Optional[str] = None,
    origin: Optional[str] = None,
) -> Optional[dict]:
    """Build one Stage 13 record from an engine closed-trade record.

    ``source_record`` is the engine ``history_record`` (PAPER) or ``live_record``
    (LIVE).  No value is invented: absent fields stay ``None`` and parameter
    context is only populated from the entry snapshot that was actually bound to
    the position.
    """

    if not isinstance(source_record, Mapping):
        return None

    resolved_origin = origin
    if isinstance(resolved_origin, str):
        resolved_origin = resolved_origin.strip().upper()
    if resolved_origin not in SUPPORTED_ORIGINS:
        resolved_origin = resolve_record_origin()

    snapshot = source_record.get("parameterSnapshot")
    if not isinstance(snapshot, Mapping):
        snapshot = None
    values = _parameter_values(snapshot) if snapshot is not None else None
    parameter_available = bool(snapshot) and values is not None

    mode = str(source_record.get("mode") or "").strip().lower() or None
    scope = _first(source_record, ("parameterScope", "scope", "canonicalScope"))
    if scope is None and mode in ("paper", "live"):
        scope = mode.upper()
    if isinstance(scope, str):
        scope = scope.strip().upper()
        if scope not in ("PAPER", "LIVE"):
            scope = mode.upper() if mode in ("paper", "live") else scope

    effective_revision = _first(
        source_record, ("effectiveRevision", "parameterRevision")
    )
    configured_revision = source_record.get("configuredRevision")
    control_source = normalize_control_source(source_record)

    entry_timestamp = _first(source_record, ("openedAt", "entry_time"))
    exit_timestamp = _first(source_record, ("closedAt", "exit_time"))
    holding_ms = None
    if isinstance(entry_timestamp, (int, float)) and isinstance(
        exit_timestamp, (int, float)
    ):
        holding_ms = max(0.0, (float(exit_timestamp) - float(entry_timestamp)) * 1000.0)

    quantity = _first(source_record, ("qty", "quantity", "coin_qty"))
    entry_price = _first(source_record, ("entryPrice", "entry_price"))
    exit_price = _first(source_record, ("exitPrice", "exit_price"))
    notional = None
    if isinstance(quantity, (int, float)) and isinstance(exit_price, (int, float)):
        notional = float(quantity) * float(exit_price)

    if mode == "live":
        realized_pnl = _first(
            source_record, ("realizedPnl", "estimatedPnl", "pnl")
        )
        authoritative = bool(
            source_record.get("realizedPnlAuthoritative") is True
        )
    else:
        realized_pnl = _first(source_record, ("realizedPnl", "pnl"))
        authoritative = realized_pnl is not None

    context = None
    if snapshot is not None:
        context = {
            key: snapshot.get(key)
            for key in (
                "schemaVersion",
                "calibrationId",
                "scope",
                "authority",
                "canonicalScope",
                "parameterSetId",
                "configuredRevision",
                "effectiveRevision",
                "source",
                "featureContract",
                "capturedAt",
                "authorityStatus",
                "storeStatus",
                "parameterSetStatus",
            )
            if snapshot.get(key) is not None
        }

    return {
        "schemaVersion": STAGE13_SCHEMA_VERSION,
        "recordId": f"stage13-{uuid4()}",
        "origin": resolved_origin,
        "tradeId": _first(source_record, ("tradeId", "positionId")),
        "traceId": source_record.get("traceId"),
        "positionId": _first(source_record, ("positionId", "order_id")),
        "scope": scope,
        "mode": mode,
        "symbol": source_record.get("symbol"),
        "side": source_record.get("side"),
        "controlSource": control_source,
        "parameterSetId": source_record.get("parameterSetId"),
        "configuredRevision": configured_revision,
        "effectiveRevision": effective_revision,
        "parameterRevision": effective_revision,
        "parameterContextAvailable": parameter_available,
        "parameterSnapshot": values,
        "parameterContext": context,
        "parameterSnapshotSemantics": PARAMETER_SNAPSHOT_SEMANTICS,
        "entrySnapshotParameters": list(ENTRY_SNAPSHOT_PARAMETERS),
        "dynamicAuthorityParameters": list(DYNAMIC_AUTHORITY_PARAMETERS),
        "parameterSemanticsNote": PARAMETER_SEMANTICS_NOTE,
        "entryTimestamp": entry_timestamp,
        "exitTimestamp": exit_timestamp,
        "holdingMs": holding_ms,
        "entryPrice": entry_price,
        "exitPrice": exit_price,
        "quantity": quantity,
        "notional": notional,
        "realizedPnl": realized_pnl,
        "realizedPnlAuthoritative": authoritative,
        "exitReason": _first(source_record, ("reason", "exitReason")),
        "featureContract": source_record.get("featureContract"),
        "runtimeId": source_record.get("runtimeId"),
        "contextKey": source_record.get("contextKey"),
        "recordedAt": recorded_at or _utc_now(),
    }


class ParameterPerformanceStore:
    """Append-only, restart-safe durable store for Stage 13 records."""

    def __init__(self, path):
        self.path = Path(path)
        self.persist_errors = 0

    def append(self, record: Mapping[str, Any]) -> bool:
        if not isinstance(record, Mapping):
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(
                dict(record),
                sort_keys=True,
                ensure_ascii=True,
                separators=(",", ":"),
            )
            fd = os.open(
                self.path,
                os.O_CREAT | os.O_APPEND | os.O_WRONLY,
                0o600,
            )
            try:
                os.write(fd, (line + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            return True
        except (OSError, TypeError, ValueError):
            self.persist_errors += 1
            return False

    def load(self) -> list:
        if not self.path.exists():
            return []
        rows = []
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if (
                        isinstance(record, dict)
                        and record.get("schemaVersion")
                        == STAGE13_SCHEMA_VERSION
                    ):
                        rows.append(record)
        except OSError:
            return []
        return rows

    def history(
        self,
        *,
        scope: Optional[str] = None,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
        revision: Optional[int] = None,
        parameter_set_id: Optional[str] = None,
    ) -> list:
        """Read boundary for E-PERF-3 (read-only, deterministic ordering)."""

        normalized_scope = scope.strip().upper() if isinstance(scope, str) else None
        normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) else None
        normalized_mode = mode.strip().lower() if isinstance(mode, str) else None
        rows = []
        for record in self.load():
            if normalized_scope is not None and record.get("scope") != normalized_scope:
                continue
            if normalized_symbol is not None and str(
                record.get("symbol") or ""
            ).upper() != normalized_symbol:
                continue
            if normalized_mode is not None and record.get("mode") != normalized_mode:
                continue
            if revision is not None and record.get("effectiveRevision") != revision:
                continue
            if parameter_set_id is not None and record.get(
                "parameterSetId"
            ) != parameter_set_id:
                continue
            rows.append(record)
        return rows

    def revisions(self) -> list:
        """Return distinct observed revision summaries (read-only)."""

        summaries: dict = {}
        for record in self.load():
            key = (record.get("scope"), record.get("effectiveRevision"))
            entry = summaries.get(key)
            if entry is None:
                entry = {
                    "scope": record.get("scope"),
                    "effectiveRevision": record.get("effectiveRevision"),
                    "parameterSetId": record.get("parameterSetId"),
                    "featureContract": record.get("featureContract"),
                    "parameterSnapshot": record.get("parameterSnapshot"),
                    "observedTradeCount": 0,
                }
                summaries[key] = entry
            entry["observedTradeCount"] += 1
        return [
            summaries[key]
            for key in sorted(
                summaries,
                key=lambda item: (
                    str(item[0]),
                    item[1] if isinstance(item[1], int) else -1,
                ),
            )
        ]


def default_parameter_performance_store() -> ParameterPerformanceStore:
    path = os.environ.get(
        PARAMETER_PERFORMANCE_PATH_ENV,
        DEFAULT_PARAMETER_PERFORMANCE_PATH,
    )
    return ParameterPerformanceStore(path)


def record_completed_trade(
    source_record: Mapping[str, Any],
    *,
    recorded_at: Optional[str] = None,
    origin: Optional[str] = None,
) -> bool:
    """Best-effort durable recording of one completed trade.

    Recording must never affect the trading path; failures are counted and
    swallowed.
    """

    try:
        record = build_completed_trade_record(
            source_record, recorded_at=recorded_at, origin=origin
        )
        if record is None:
            return False
        return default_parameter_performance_store().append(record)
    except Exception:
        return False
