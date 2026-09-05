"""D-7 deterministic provenance and drift detection for the Knowledge Core.

INFORMATION_ONLY.  READ_ONLY.  DETERMINISTIC.

D-7 answers, for a provenanced knowledge/evidence item: where it came from,
what authority/truth class it belongs to, when it was observed/loaded, what
source/version/hash supports it, whether the evidence is still current, and
whether the underlying canonical source or runtime contact has changed.

D-7 is a pure view.  It reads existing provenance contracts (the Knowledge Core
``ProvenanceRecord``, D-5 ``runtime.unified_trace.Provenance``, D-6
``supervisor.specialists.SourceReference`` and the Advisor source reference) and
produces a deterministic :class:`DriftAssessment` (+ findings).  It NEVER:

* modifies a source, canonical specification, knowledge record or runtime;
* promotes a lower truth layer upward;
* grants operational, execution, governance, MM or strategy authority
  (``KnowledgeAuthority.INFORMATION_ONLY`` throughout);
* depends on any LLM or provider SDK.

Drift detection evaluates the *relationships* between truth layers.  It does not
rewrite any layer.  ``DRIFTED`` means "the referenced knowledge no longer
matches the current source", not "the new source is wrong"; ``CONFLICTING``
means "incompatible evidence exists", not "pick whichever the model prefers".
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from ._base import stable_json, to_plain_datetime
from .authority import (
    TRUTH_PRIORITY,
    KnowledgeAuthority,
    SourceCategory,
    TruthLevel,
)
from .provenance import ProvenanceRecord

_HASH_PREFIX = "sha256:"
_HASH_HEX_LEN = 64
_HEX_CHARS = "0123456789abcdef"

# --------------------------------------------------------------------------- #
# Drift status vocabulary
# --------------------------------------------------------------------------- #


class DriftStatus(str, Enum):
    """Deterministic drift/currency status.

    Distinct meanings, never collapsed into one generic warning:

    * ``CURRENT``       evidence matches expected provenance and is fresh.
    * ``STALE``         source known but freshness threshold exceeded.
    * ``DRIFTED``       referenced source/version/fingerprint no longer matches
                        the current authoritative source.
    * ``CONFLICTING``   two relevant authority layers give incompatible claims
                        that version/freshness cannot resolve.
    * ``UNKNOWN``       evidence exists but is insufficient to decide safely.
    * ``UNAVAILABLE``   required evidence/source cannot be obtained.
    """

    CURRENT = "CURRENT"
    STALE = "STALE"
    DRIFTED = "DRIFTED"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"


# Fail-closed, deterministic merge rank.  An unresolvable contradiction is the
# strongest signal, then an authoritative source that changed, then entirely
# missing evidence, then stale-but-known, then uncertain, then current.
DRIFT_STATUS_RANK: dict[DriftStatus, int] = {
    DriftStatus.CURRENT: 0,
    DriftStatus.UNKNOWN: 1,
    DriftStatus.STALE: 2,
    DriftStatus.UNAVAILABLE: 3,
    DriftStatus.DRIFTED: 4,
    DriftStatus.CONFLICTING: 5,
}


class SourceKind(str, Enum):
    """The kind of source a drift assessment is comparing.

    Determines which provenance fields are *meaningful* so a universal naive
    dictionary equality is never used.
    """

    STATIC_CANONICAL = "STATIC_CANONICAL"
    CURRENT_RUNTIME = "CURRENT_RUNTIME"
    HISTORICAL_EVIDENCE = "HISTORICAL_EVIDENCE"
    SPECIALIST_FINDING = "SPECIALIST_FINDING"


class TemporalScope(str, Enum):
    """Whether an evidence/authority layer is current or historical.

    Prevents comparing semantically incompatible evidence (e.g. a stopped bot
    now vs a running bot recorded earlier) as if it were a live conflict.
    """

    CURRENT = "CURRENT"
    HISTORICAL = "HISTORICAL"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------- #
# D-7 reason codes (narrow, read-only; kept here and not merged into the
# runtime ReasonCodeCatalog, so the D-1 runtime index stays unchanged).
# --------------------------------------------------------------------------- #

PROVENANCE_SOURCE_MISSING = "PROVENANCE_SOURCE_MISSING"
PROVENANCE_FINGERPRINT_MISMATCH = "PROVENANCE_FINGERPRINT_MISMATCH"
PROVENANCE_VERSION_MISMATCH = "PROVENANCE_VERSION_MISMATCH"
EVIDENCE_STALE = "EVIDENCE_STALE"
AUTHORITY_CONFLICT = "AUTHORITY_CONFLICT"
PROVENANCE_UNKNOWN = "PROVENANCE_UNKNOWN"

D7_REASON_CODES = (
    PROVENANCE_SOURCE_MISSING,
    PROVENANCE_FINGERPRINT_MISMATCH,
    PROVENANCE_VERSION_MISMATCH,
    EVIDENCE_STALE,
    AUTHORITY_CONFLICT,
    PROVENANCE_UNKNOWN,
)

# --------------------------------------------------------------------------- #
# Deterministic source fingerprinting (standard library only, no secrets)
# --------------------------------------------------------------------------- #

# Field-name markers that must never enter a fingerprint allowlist.  This is an
# explicit, typed guard: an allowlist is refused when it names a secret-bearing
# field, so credentials/tokens/keys are never fingerprinted or stored.
_SECRET_FIELD_MARKERS = (
    "apikey", "apisecret", "api_key", "api_secret", "secret", "token",
    "password", "passphrase", "cookie", "authorization", "credential",
    "private_key", "privatekey", "access_key", "accesskey", "refresh_token",
)


def _looks_like_secret_field(name: str) -> bool:
    lowered = name.lower().replace("-", "_").replace(" ", "_").strip("_")
    return any(marker in lowered for marker in _SECRET_FIELD_MARKERS)


def _digest(content: bytes) -> str:
    return _HASH_PREFIX + hashlib.sha256(content).hexdigest()


def fingerprint_bytes(content: bytes) -> str:
    """Deterministic ``sha256:<hex>`` fingerprint of raw bytes."""
    return _digest(content)


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def normalize_value(value: Any) -> Any:
    """Deterministic normalization of a value for fingerprinting.

    Handles nulls, enums, booleans, finite numbers, strings, timezone-aware
    UTC datetimes, mappings (stable key order), ordered and unordered
    collections, sets (stable item order) and read-only dataclasses.  Unknown
    object types raise instead of being hashed in a non-deterministic way.
    """
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return value
    if isinstance(value, datetime):
        return to_plain_datetime(value)
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite numbers are not deterministically fingerprintable")
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): normalize_value(item)
            for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))
        }
    if isinstance(value, (tuple, list)):
        return [normalize_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [normalize_value(item) for item in value]
        return sorted(items, key=_canonical_sort_key)
    if is_dataclass(value):
        return {
            f.name: normalize_value(getattr(value, f.name))
            for f in fields(value)
            if not f.name.startswith("_")
        }
    raise TypeError(
        f"not deterministically fingerprintable: {type(value).__name__}"
    )


def fingerprint_structured(data: Any) -> str:
    """Fingerprint a structured value after deterministic normalization.

    The caller is responsible for passing allowlisted, non-secret content.  For
    a mapping, prefer :func:`fingerprint_fields` which enforces exclusion.
    """
    normalized = normalize_value(data)
    payload = json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return _digest(payload)


def fingerprint_fields(data: Mapping[str, Any], allowlist: Sequence[str]) -> Optional[str]:
    """Fingerprint only the allowlisted fields of a mapping.

    Returns ``None`` when the allowlist is empty or names no present field such
    that there is nothing safe to fingerprint.  The allowlist is validated and
    must not name a secret-bearing field, guaranteeing credential/key/token
    values never enter a fingerprint and are never stored.
    """
    if not isinstance(data, Mapping):
        raise TypeError("fingerprint_fields requires a mapping")
    if not allowlist:
        return None
    for name in allowlist:
        if not isinstance(name, str):
            raise TypeError("allowlist entries must be strings")
        if _looks_like_secret_field(name):
            raise ValueError(f"secret-bearing field refused in allowlist: {name}")
    picked = {str(name): data[name] for name in allowlist if name in data}
    if not picked:
        return None
    return fingerprint_structured(picked)


# --------------------------------------------------------------------------- #
# D-7 typed provenance view and drift records
# --------------------------------------------------------------------------- #


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _coerce_timestamp(value: Any) -> Optional[datetime]:
    """Coerce an ISO string or a datetime into an aware UTC datetime.

    Invalid/naive values yield ``None`` (UNKNOWN); provenance is never invented.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _has_reference(record: Optional[ProvenanceRecord]) -> bool:
    return bool(record and record.source_reference)


def _has_authority_metadata(record: ProvenanceRecord) -> bool:
    return bool(record.source_identifier or record.source_subsystem or record.source_timestamp)


@dataclass(frozen=True)
class DriftFinding:
    """A single typed drift/conflict finding.

    Machine-readable ``code`` carries the D-7 reason; prose is bounded to the
    ``reason`` text field.  Authority/truth layer and the authoritative side of
    a conflict are preserved rather than erased.
    """

    code: str
    status: DriftStatus
    reason: str
    expected_reference: Optional[str] = None
    actual_reference: Optional[str] = None
    authority_layer: Optional[TruthLevel] = None
    authoritative_layer: Optional[TruthLevel] = None
    observed_at: Optional[datetime] = None
    source_timestamp: Optional[datetime] = None
    fingerprint_expected: Optional[str] = None
    fingerprint_actual: Optional[str] = None
    version_expected: Optional[str] = None
    version_actual: Optional[str] = None
    warnings: tuple[str, ...] = ()
    confidence: Optional[float] = None


@dataclass(frozen=True)
class DriftAssessment:
    """Deterministic drift result for one provenanced subject.

    INFORMATION_ONLY: it never grants any authority and exposes no mutation.
    """

    subject: str
    source_kind: SourceKind
    status: DriftStatus
    findings: tuple[DriftFinding, ...] = ()
    assessed_at: Optional[datetime] = None

    @property
    def authority(self) -> KnowledgeAuthority:
        return KnowledgeAuthority.INFORMATION_ONLY

    @property
    def grants_any_authority(self) -> bool:
        return False

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.code for f in self.findings))

    def stable_json(self) -> str:
        return stable_json({
            "subject": self.subject,
            "source_kind": self.source_kind.value,
            "status": self.status.value,
            "findings": list(self.findings),
            "assessed_at": self.assessed_at,
            "authority": self.authority.value,
        })


def merge_status(statuses: Sequence[DriftStatus]) -> DriftStatus:
    """Deterministic merge of multiple finding statuses (fail-closed)."""
    if not statuses:
        return DriftStatus.CURRENT
    return max(statuses, key=lambda item: DRIFT_STATUS_RANK[item])


# --------------------------------------------------------------------------- #
# Deterministic comparison engine (per source kind, never naive dict equality)
# --------------------------------------------------------------------------- #

_SUBJECT_MAX = 128


def _assess_freshness(
    current: ProvenanceRecord,
    assessed_at: Optional[datetime],
    freshness_window_seconds: Optional[float],
) -> list[DriftFinding]:
    findings: list[DriftFinding] = []
    if freshness_window_seconds is None:
        return findings
    if current.source_timestamp is None or assessed_at is None:
        return findings
    assessed = _aware(assessed_at, "assessed_at")
    source_ts = _aware(current.source_timestamp, "source_timestamp")
    age = (assessed - source_ts).total_seconds()
    if age < 0:
        raise ValueError("source_timestamp cannot be in the future")
    if age > freshness_window_seconds:
        findings.append(DriftFinding(
            code=EVIDENCE_STALE,
            status=DriftStatus.STALE,
            reason="freshness threshold exceeded",
            actual_reference=current.source_reference,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            warnings=("FRESHNESS_THRESHOLD_EXCEEDED",),
            confidence=current.confidence,
        ))
    return findings


def _assess_static_canonical(
    subject: str,
    expected: ProvenanceRecord,
    current: ProvenanceRecord,
    assessed_at: Optional[datetime],
    freshness_window_seconds: Optional[float],
) -> DriftAssessment:
    findings: list[DriftFinding] = []
    if not _has_reference(current):
        findings.append(DriftFinding(
            code=PROVENANCE_SOURCE_MISSING,
            status=DriftStatus.UNAVAILABLE,
            reason="expected canonical source is unavailable",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.CANONICAL_SPECIFICATION,
            observed_at=current.observed_at,
        ))
        return DriftAssessment(subject, SourceKind.STATIC_CANONICAL, DriftStatus.UNAVAILABLE,
                               findings=tuple(findings), assessed_at=assessed_at)

    fingerprint_mismatch = bool(
        expected.content_hash and current.content_hash
        and expected.content_hash != current.content_hash
    )
    version_mismatch = bool(
        expected.version and current.version and expected.version != current.version
    )
    can_score = fingerprint_mismatch or version_mismatch or (
        (expected.content_hash and current.content_hash)
        or (expected.version and current.version)
    )

    if fingerprint_mismatch:
        findings.append(DriftFinding(
            code=PROVENANCE_FINGERPRINT_MISMATCH,
            status=DriftStatus.DRIFTED,
            reason="canonical source fingerprint changed",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.CANONICAL_SPECIFICATION,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            fingerprint_expected=expected.content_hash,
            fingerprint_actual=current.content_hash,
            version_expected=expected.version,
            version_actual=current.version,
            warnings=("SOURCE_CHANGED",),
            confidence=current.confidence,
        ))
    elif version_mismatch:
        findings.append(DriftFinding(
            code=PROVENANCE_VERSION_MISMATCH,
            status=DriftStatus.DRIFTED,
            reason="canonical source version changed",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.CANONICAL_SPECIFICATION,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            version_expected=expected.version,
            version_actual=current.version,
            warnings=("SOURCE_CHANGED",),
            confidence=current.confidence,
        ))

    findings.extend(_assess_freshness(current, assessed_at, freshness_window_seconds))

    if not can_score:
        findings.append(DriftFinding(
            code=PROVENANCE_UNKNOWN,
            status=DriftStatus.UNKNOWN,
            reason="cannot determine whether canonical source changed",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.CANONICAL_SPECIFICATION,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            warnings=("FINGERPRINT_INDETERMINATE",),
            confidence=current.confidence,
        ))

    status = merge_status([f.status for f in findings]) if findings else DriftStatus.CURRENT
    return DriftAssessment(subject, SourceKind.STATIC_CANONICAL, status,
                           findings=tuple(findings), assessed_at=assessed_at)


def _assess_current_runtime(
    subject: str,
    expected: ProvenanceRecord,
    current: ProvenanceRecord,
    assessed_at: Optional[datetime],
    freshness_window_seconds: Optional[float],
) -> DriftAssessment:
    findings: list[DriftFinding] = []
    if not _has_reference(current):
        findings.append(DriftFinding(
            code=PROVENANCE_SOURCE_MISSING,
            status=DriftStatus.UNAVAILABLE,
            reason="required runtime source is missing",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.CURRENT_SOURCE_RUNTIME,
            observed_at=current.observed_at,
        ))
        return DriftAssessment(subject, SourceKind.CURRENT_RUNTIME, DriftStatus.UNAVAILABLE,
                               findings=tuple(findings), assessed_at=assessed_at)

    # Freshness is the meaningful runtime comparison; dynamic values are never
    # fingerprinted, so a normal value change can never become DRIFTED here.
    findings.extend(_assess_freshness(current, assessed_at, freshness_window_seconds))

    if not _has_authority_metadata(current):
        findings.append(DriftFinding(
            code=PROVENANCE_UNKNOWN,
            status=DriftStatus.UNKNOWN,
            reason="runtime evidence lacks authority metadata",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.CURRENT_SOURCE_RUNTIME,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            warnings=("RUNTIME_AUTHORITY_UNKNOWN",),
            confidence=current.confidence,
        ))

    status = merge_status([f.status for f in findings]) if findings else DriftStatus.CURRENT
    return DriftAssessment(subject, SourceKind.CURRENT_RUNTIME, status,
                           findings=tuple(findings), assessed_at=assessed_at)


def _assess_historical_evidence(
    subject: str,
    expected: ProvenanceRecord,
    current: ProvenanceRecord,
    assessed_at: Optional[datetime],
    freshness_window_seconds: Optional[float],
    completeness: Optional[str],
) -> DriftAssessment:
    findings: list[DriftFinding] = []
    if not _has_reference(current):
        findings.append(DriftFinding(
            code=PROVENANCE_SOURCE_MISSING,
            status=DriftStatus.UNAVAILABLE,
            reason="historical evidence is unavailable",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.OBSERVATION_FINDING,
            observed_at=current.observed_at,
        ))
        return DriftAssessment(subject, SourceKind.HISTORICAL_EVIDENCE, DriftStatus.UNAVAILABLE,
                               findings=tuple(findings), assessed_at=assessed_at)

    label = (completeness or "").upper()
    if not label:
        findings.append(DriftFinding(
            code=PROVENANCE_UNKNOWN,
            status=DriftStatus.UNKNOWN,
            reason="historical trace completeness unknown",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.OBSERVATION_FINDING,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            warnings=("TRACE_COMPLETENESS_UNKNOWN",),
        ))
    elif label in {"PARTIAL", "AMBIGUOUS"}:
        findings.append(DriftFinding(
            code=PROVENANCE_UNKNOWN,
            status=DriftStatus.UNKNOWN,
            reason=f"historical evidence is {label.lower()}",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.OBSERVATION_FINDING,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            warnings=(f"TRACE_{label}",),
        ))
    elif label == "UNAVAILABLE":
        findings.append(DriftFinding(
            code=PROVENANCE_SOURCE_MISSING,
            status=DriftStatus.UNAVAILABLE,
            reason="historical evidence is unavailable",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.OBSERVATION_FINDING,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            warnings=("TRACE_UNAVAILABLE",),
        ))
    else:  # COMPLETE
        findings.extend(_assess_freshness(current, assessed_at, freshness_window_seconds))

    status = merge_status([f.status for f in findings]) if findings else DriftStatus.CURRENT
    return DriftAssessment(subject, SourceKind.HISTORICAL_EVIDENCE, status,
                           findings=tuple(findings), assessed_at=assessed_at)


def _assess_specialist_finding(
    subject: str,
    expected: ProvenanceRecord,
    current: ProvenanceRecord,
    assessed_at: Optional[datetime],
    freshness_window_seconds: Optional[float],
) -> DriftAssessment:
    findings: list[DriftFinding] = []
    if not _has_reference(current):
        findings.append(DriftFinding(
            code=PROVENANCE_SOURCE_MISSING,
            status=DriftStatus.UNAVAILABLE,
            reason="specialist evidence is missing",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.OBSERVATION_FINDING,
            observed_at=current.observed_at,
        ))
        return DriftAssessment(subject, SourceKind.SPECIALIST_FINDING, DriftStatus.UNAVAILABLE,
                               findings=tuple(findings), assessed_at=assessed_at)

    findings.extend(_assess_freshness(current, assessed_at, freshness_window_seconds))
    if current.freshness is None:
        findings.append(DriftFinding(
            code=PROVENANCE_UNKNOWN,
            status=DriftStatus.UNKNOWN,
            reason="specialist evidence freshness unknown",
            expected_reference=expected.source_reference,
            actual_reference=current.source_reference,
            authority_layer=TruthLevel.OBSERVATION_FINDING,
            observed_at=current.observed_at,
            source_timestamp=current.source_timestamp,
            warnings=("EVIDENCE_FRESHNESS_UNKNOWN",),
            confidence=current.confidence,
        ))

    status = merge_status([f.status for f in findings]) if findings else DriftStatus.CURRENT
    return DriftAssessment(subject, SourceKind.SPECIALIST_FINDING, status,
                           findings=tuple(findings), assessed_at=assessed_at)


def assess_provenance(
    *,
    subject: str,
    source_kind: SourceKind,
    expected: ProvenanceRecord,
    current: Optional[ProvenanceRecord],
    assessed_at: Optional[datetime] = None,
    freshness_window_seconds: Optional[float] = None,
    completeness: Optional[str] = None,
) -> DriftAssessment:
    """Deterministic comparison of expected vs current provenance.

    Only fields that are meaningful for ``source_kind`` are compared:

    * static canonical source -> fingerprint/version drift + freshness;
    * current runtime        -> freshness / source authority / runtime id
      (dynamic values are deliberately NOT fingerprinted);
    * historical evidence    -> trace provenance / completeness / freshness;
    * specialist finding     -> underlying evidence provenance + freshness.

    ``current=None``, or a record with no source reference, means the source is
    unavailable and yields ``UNAVAILABLE``.  Assessment is non-mutating.
    """
    if not isinstance(source_kind, SourceKind):
        raise TypeError("typed SourceKind required")
    if not subject:
        raise ValueError("subject is required")
    subject_ref = subject[: _SUBJECT_MAX]
    if assessed_at is not None:
        assessed_at = _aware(assessed_at, "assessed_at")
    effective_current = current or ProvenanceRecord(
        truth_level=TruthLevel.OBSERVATION_FINDING,
        source_category=SourceCategory.HISTORY,
        source_reference="",
    )

    if source_kind is SourceKind.STATIC_CANONICAL:
        return _assess_static_canonical(subject_ref, expected, effective_current,
                                        assessed_at, freshness_window_seconds)
    if source_kind is SourceKind.CURRENT_RUNTIME:
        return _assess_current_runtime(subject_ref, expected, effective_current,
                                       assessed_at, freshness_window_seconds)
    if source_kind is SourceKind.HISTORICAL_EVIDENCE:
        return _assess_historical_evidence(subject_ref, expected, effective_current,
                                           assessed_at, freshness_window_seconds, completeness)
    return _assess_specialist_finding(subject_ref, expected, effective_current,
                                      assessed_at, freshness_window_seconds)


def assess_authority_conflict(
    *,
    subject: str,
    claim_a: Any,
    claim_b: Any,
    temporal_scope_a: TemporalScope,
    temporal_scope_b: TemporalScope,
    provenance_a: ProvenanceRecord,
    provenance_b: ProvenanceRecord,
) -> Optional[DriftFinding]:
    """Authority-aware conflict detection.

    A conflict is only reported when BOTH layers are current and their claims
    are genuinely incompatible.  Two current layers of incompatible authority
    are reported as ``CONFLICTING`` with ``authoritative_layer`` set to the
    higher-priority truth level (so an observation can never override a
    canonical specification).  A historical layer is never allowed to conflict
    with a current runtime layer: that is a temporal difference, not a
    contradiction, and it returns ``None``.
    """
    if (
        temporal_scope_a is TemporalScope.HISTORICAL
        or temporal_scope_b is TemporalScope.HISTORICAL
    ):
        return None
    if (
        temporal_scope_a is not TemporalScope.CURRENT
        or temporal_scope_b is not TemporalScope.CURRENT
    ):
        return None
    if claim_a == claim_b:
        return None

    winner = (
        provenance_a
        if TRUTH_PRIORITY[provenance_a.truth_level] < TRUTH_PRIORITY[provenance_b.truth_level]
        else provenance_b
    )
    return DriftFinding(
        code=AUTHORITY_CONFLICT,
        status=DriftStatus.CONFLICTING,
        reason="incompatible current authority claims",
        expected_reference=provenance_a.source_reference,
        actual_reference=provenance_b.source_reference,
        authority_layer=provenance_a.truth_level,
        authoritative_layer=winner.truth_level,
        observed_at=provenance_a.observed_at,
        source_timestamp=provenance_a.source_timestamp,
        warnings=("AUTHORITY_CONFLICT",),
        confidence=provenance_a.confidence,
    )


def build_conflicting_assessment(
    subject: str,
    finding: DriftFinding,
    *,
    assessed_at: Optional[datetime] = None,
) -> DriftAssessment:
    """Wrap a single conflict finding into a typed CONFLICTING assessment."""
    if assessed_at is not None:
        assessed_at = _aware(assessed_at, "assessed_at")
    return DriftAssessment(
        subject=subject[: _SUBJECT_MAX],
        source_kind=SourceKind.STATIC_CANONICAL,
        status=DriftStatus.CONFLICTING,
        findings=(finding,),
        assessed_at=assessed_at,
    )


# --------------------------------------------------------------------------- #
# Converters from the existing provenance contracts (no parallel system)
# --------------------------------------------------------------------------- #


def _field(source: Any, *candidates: str) -> Any:
    """Read a field from a mapping or an attribute-bearing object.

    Accepts a plain dict (e.g. ``model_dump()`` / ``to_dict()``) or a dataclass /
    pydantic object, so the D-5, D-6 and Advisor contracts all translate into the
    D-7 provenance view without a parallel system.
    """
    if isinstance(source, Mapping):
        for name in candidates:
            if name in source:
                return source[name]
        return None
    for name in candidates:
        value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def provenance_from_trace(
    value: Any,
    *,
    truth_level: TruthLevel = TruthLevel.OBSERVATION_FINDING,
    source_reference: Optional[str] = None,
    notes: str = "",
) -> ProvenanceRecord:
    """Build a D-7 provenance view from a D-5 ``unified_trace.Provenance``."""
    source = value.to_dict() if hasattr(value, "to_dict") else value
    subsystem = _field(source, "source_subsystem", "sourceSubsystem")
    if subsystem is not None and hasattr(subsystem, "value"):
        subsystem = subsystem.value
    source_type = _field(source, "source_type", "sourceType")
    identifier = _field(source, "source_identifier", "sourceIdentifier")
    timestamp = _field(source, "timestamp")
    linkage = _field(source, "linkage_method", "linkageMethod")
    confidence = _field(source, "confidence")
    reference = source_reference or f"{source_type or 'EVIDENCE'}:{identifier or ''}"
    return ProvenanceRecord(
        truth_level=truth_level,
        source_category=SourceCategory.HISTORY,
        source_reference=reference,
        source_subsystem=str(subsystem or "UNKNOWN"),
        source_type=str(source_type or "EVIDENCE"),
        source_identifier=str(identifier or ""),
        source_timestamp=_coerce_timestamp(timestamp),
        notes=notes or str(linkage or "EVIDENCE_REFERENCE"),
    )


def provenance_from_specialist(
    value: Any,
    *,
    truth_level: TruthLevel = TruthLevel.OBSERVATION_FINDING,
) -> ProvenanceRecord:
    """Build a D-7 provenance view from a D-6 ``SourceReference``."""
    source = value.model_dump() if hasattr(value, "model_dump") else value
    subsystem = _field(source, "sourceSubsystem")
    source_type = _field(source, "sourceType")
    identifier = _field(source, "sourceIdentifier")
    timestamp = _field(source, "timestamp")
    linkage = _field(source, "linkageMethod")
    return ProvenanceRecord(
        truth_level=truth_level,
        source_category=SourceCategory.HISTORY,
        source_reference=f"{source_type or 'EVIDENCE'}:{identifier or ''}",
        source_subsystem=str(subsystem or "UNKNOWN"),
        source_type=str(source_type or "EVIDENCE"),
        source_identifier=str(identifier or ""),
        source_timestamp=_coerce_timestamp(timestamp),
        notes=str(linkage or "EVIDENCE_REFERENCE"),
    )


def provenance_from_advisor(
    value: Any,
    *,
    truth_level: TruthLevel = TruthLevel.CURRENT_SOURCE_RUNTIME,
) -> ProvenanceRecord:
    """Build a D-7 provenance view from an Advisor source reference."""
    source = value.model_dump() if hasattr(value, "model_dump") else value
    source_type = _field(source, "sourceType")
    source_id = _field(source, "sourceId")
    source_version = _field(source, "sourceVersion")
    content_hash = _field(source, "contentHash")
    document_path = _field(source, "documentPath")
    captured_at = _field(source, "capturedAt")
    return ProvenanceRecord(
        truth_level=truth_level,
        source_category=(
            SourceCategory.SPECIFICATION
            if str(source_type or "") == "SPECIFICATION"
            else SourceCategory.RUNTIME
        ),
        source_reference=str(source_id or ""),
        source_path=document_path,
        version=str(source_version) if source_version is not None else None,
        content_hash=content_hash,
        source_identifier=str(source_id or ""),
        source_timestamp=_coerce_timestamp(captured_at),
    )


def provenance_from_knowledge(record: ProvenanceRecord) -> ProvenanceRecord:
    """Return the Knowledge Core provenance view unchanged (already typed)."""
    return record


__all__ = [
    "D7_REASON_CODES",
    "DRIFT_STATUS_RANK",
    "AUTHORITY_CONFLICT",
    "EVIDENCE_STALE",
    "PROVENANCE_FINGERPRINT_MISMATCH",
    "PROVENANCE_SOURCE_MISSING",
    "PROVENANCE_UNKNOWN",
    "PROVENANCE_VERSION_MISMATCH",
    "DriftAssessment",
    "DriftFinding",
    "DriftStatus",
    "SourceKind",
    "TemporalScope",
    "assess_authority_conflict",
    "assess_provenance",
    "build_conflicting_assessment",
    "fingerprint_bytes",
    "fingerprint_fields",
    "fingerprint_structured",
    "merge_status",
    "normalize_value",
    "provenance_from_advisor",
    "provenance_from_knowledge",
    "provenance_from_specialist",
    "provenance_from_trace",
]
