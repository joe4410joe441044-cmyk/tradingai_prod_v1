"""Micro Edge Suitability Deep Analysis Contract.

Reuses existing Production Python Detectors (`MicrostructureStateBuilder`) and
Feature Builder evidence. Never creates a second Micro Edge engine, detector
stack, AI-based score, or heuristic shortcut.

Suitability is a pre-commit gate for Live AUTO. It does not decide BUY/SELL.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Dict, Mapping, Optional, Tuple


# ---------------------------------------------------------------------------
# Reason codes — reuses existing naming patterns
# ---------------------------------------------------------------------------

class MicroEdgeSuitabilityReason(str, Enum):
    SUITABILITY_UNAVAILABLE = "MICRO_EDGE_SUITABILITY_UNAVAILABLE"
    SUITABILITY_STALE = "MICRO_EDGE_SUITABILITY_STALE"
    SUITABILITY_REJECTED = "MICRO_EDGE_SUITABILITY_REJECTED"
    SUITABILITY_MALFORMED = "MICRO_EDGE_SUITABILITY_INVALID"
    SUITABILITY_CANDIDATE_MISMATCH = "MICRO_EDGE_SUITABILITY_CANDIDATE_MISMATCH"
    SUITABILITY_OBSERVATION_MISMATCH = "MICRO_EDGE_SUITABILITY_OBSERVATION_MISMATCH"
    SUITABILITY_CALIBRATION_NOT_READY = "MICRO_EDGE_SUITABILITY_CALIBRATION_NOT_READY"
    SUITABILITY_TIMESTAMP_MISSING = "MICRO_EDGE_SUITABILITY_TIMESTAMP_MISSING"
    SUITABILITY_DETECTOR_INCOMPLETE = "MICRO_EDGE_SUITABILITY_DETECTOR_INCOMPLETE"
    SUITABILITY_DETECTOR_TOXIC = "MICRO_EDGE_SUITABILITY_DETECTOR_TOXIC"


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class MicroEdgeSuitabilityStatus(str, Enum):
    SUITABLE = "SUITABLE"
    UNSUITABLE = "UNSUITABLE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    INVALID = "INVALID"


# ---------------------------------------------------------------------------
# Evidence wrapping existing detector output
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MicroEdgeSuitabilityEvidence:
    candidate_symbol: Optional[str]
    evaluated_at: Optional[datetime]
    calibration_ready: bool
    detector_snapshot: Mapping[str, Any]
    runtime_id: Optional[str] = None
    feature_version: Optional[str] = None

    @staticmethod
    def from_strategy_state(strategy_state, *, candidate_symbol=None,
                            runtime_id=None, feature_version=None):
        selector = strategy_state.get("liquidityInstabilityDebug") or {}
        detector_details = selector.get("detectorDetails") or {}
        timestamp = strategy_state.get("evaluatedAt")
        if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
            evaluated_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        elif isinstance(timestamp, datetime):
            evaluated_at = timestamp
        else:
            evaluated_at = None
        return MicroEdgeSuitabilityEvidence(
            candidate_symbol=candidate_symbol,
            evaluated_at=evaluated_at,
            calibration_ready=bool(selector.get("calibrationReady")),
            detector_snapshot=dict(detector_details),
            runtime_id=runtime_id,
            feature_version=feature_version,
        )

    @staticmethod
    def from_detector_dict(evidence_dict, *, candidate_symbol=None):
        if not isinstance(evidence_dict, Mapping):
            raise TypeError("detector evidence dict required")
        evaluated_at = evidence_dict.get("evaluatedAt")
        if isinstance(evaluated_at, (int, float)) and not isinstance(evaluated_at, bool):
            evaluated_at = datetime.fromtimestamp(evaluated_at, tz=timezone.utc)
        elif isinstance(evaluated_at, datetime):
            evaluated_at = evaluated_at
        elif isinstance(evaluated_at, str):
            try:
                evaluated_at = datetime.fromisoformat(
                    evaluated_at.strip().replace("Z", "+00:00"))
            except (ValueError, TypeError):
                evaluated_at = None
        else:
            evaluated_at = None
        detectors = evidence_dict.get("detectors") or {}
        if isinstance(detectors, Mapping):
            calibration_ready = bool(detectors.get("calibrationReady"))
            detector_snapshot = dict(detectors.get("details") or {})
        else:
            calibration_ready = False
            detector_snapshot = {}
        return MicroEdgeSuitabilityEvidence(
            candidate_symbol=candidate_symbol,
            evaluated_at=evaluated_at,
            calibration_ready=calibration_ready,
            detector_snapshot=detector_snapshot,
            runtime_id=evidence_dict.get("runtimeId"),
            feature_version=evidence_dict.get("featureVersion"),
        )

    def identity_hash(self):
        payload = json.dumps({
            "candidateSymbol": self.candidate_symbol,
            "evaluatedAt": (
                self.evaluated_at.isoformat().replace("+00:00", "Z")
                if isinstance(self.evaluated_at, datetime) else None
            ),
            "calibrationReady": self.calibration_ready,
            "runtimeId": self.runtime_id,
            "version": self.feature_version,
            "detectorContent": sha256(
                json.dumps(
                    dict(self.detector_snapshot or {}),
                    sort_keys=True, separators=(",", ":"),
                ).encode("utf-8"),
            ).hexdigest()[:20],
        }, sort_keys=True, separators=(",", ":"))
        return "micro-edge-evid-" + sha256(
            payload.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Suitability contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MicroEdgeSuitabilityContract:
    candidate_symbol: Optional[str]
    status: MicroEdgeSuitabilityStatus
    reason_codes: Tuple[MicroEdgeSuitabilityReason, ...]
    evaluated_at: Optional[datetime]
    freshness_seconds: Optional[float]
    evidence_identity: Optional[str]
    calibration_ready: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidateSymbol": self.candidate_symbol,
            "suitabilityStatus": self.status.value,
            "reasonCodes": [r.value for r in self.reason_codes],
            "evaluatedAt": (
                self.evaluated_at.isoformat().replace("+00:00", "Z")
                if isinstance(self.evaluated_at, datetime) else None
            ),
            "freshnessSeconds": self.freshness_seconds,
            "evidenceIdentity": self.evidence_identity,
            "calibrationReady": self.calibration_ready,
        }

    @property
    def suitable(self) -> bool:
        return self.status is MicroEdgeSuitabilityStatus.SUITABLE


# ---------------------------------------------------------------------------
# Evaluation function
# ---------------------------------------------------------------------------

def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise TypeError("timezone-aware datetime required")
    return value.astimezone(timezone.utc)


_TOXIC_DETECTOR_KEYS = ("absorption", "stagnantHeavyFlow", "fakePressure")


def _detector_is_toxic(detector_snapshot):
    for key in _TOXIC_DETECTOR_KEYS:
        detector = detector_snapshot.get(key)
        if detector.get("conditionPassed") is True:
            return True
    return False


def _detector_snapshot_complete(detector_snapshot):
    """Match the existing MicrostructureStateBuilder producer contract."""
    if not isinstance(detector_snapshot, Mapping):
        return False
    return all(
        isinstance(detector_snapshot.get(key), Mapping)
        and isinstance(detector_snapshot[key].get("conditionPassed"), bool)
        for key in _TOXIC_DETECTOR_KEYS
    )


def evaluate_micro_edge_suitability(
    evidence,
    *,
    candidate_symbol,
    now,
    max_age_seconds=60,
    observation_id=None,
    requires_calibration=True,
) -> MicroEdgeSuitabilityContract:
    """Evaluate existing detector/feature evidence for AMS candidate eligibility.

    Returns a read-only suitability contract.  Does NOT re-compute detectors,
    re-evaluate strategy, or decide BUY/SELL.

    The existing production detector snapshot is mandatory. If any of
    absorption, stagnant heavy flow, or fake pressure is missing/malformed or
    currently detected, the contract fails closed. This is the
    DEEP_ANALYSIS_GATE and cannot be disabled by a caller.
    """
    now = _utc(now)
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")

    reasons = []

    if not isinstance(evidence, MicroEdgeSuitabilityEvidence):
        return MicroEdgeSuitabilityContract(
            candidate_symbol=candidate_symbol,
            status=MicroEdgeSuitabilityStatus.UNAVAILABLE,
            reason_codes=(MicroEdgeSuitabilityReason.SUITABILITY_UNAVAILABLE,),
            evaluated_at=None, freshness_seconds=None,
            evidence_identity=None, calibration_ready=False,
        )

    evaluated_at = evidence.evaluated_at
    if evaluated_at is None:
        reasons.append(MicroEdgeSuitabilityReason.SUITABILITY_TIMESTAMP_MISSING)

    symbol_match = (
        isinstance(candidate_symbol, str) and candidate_symbol.strip()
        and isinstance(evidence.candidate_symbol, str)
        and candidate_symbol.strip().upper()
        == evidence.candidate_symbol.strip().upper()
    )
    if not symbol_match:
        reasons.append(MicroEdgeSuitabilityReason.SUITABILITY_CANDIDATE_MISMATCH)

    fresh = False
    freshness = None
    if evaluated_at is not None:
        freshness = (now - _utc(evaluated_at)).total_seconds()
        if freshness < 0:
            reasons.append(MicroEdgeSuitabilityReason.SUITABILITY_MALFORMED)
        elif freshness <= max_age_seconds:
            fresh = True
        else:
            reasons.append(MicroEdgeSuitabilityReason.SUITABILITY_STALE)

    calibration_ready = evidence.calibration_ready if requires_calibration else True
    if requires_calibration and not calibration_ready:
        reasons.append(MicroEdgeSuitabilityReason.SUITABILITY_CALIBRATION_NOT_READY)

    if not reasons:
        if not _detector_snapshot_complete(evidence.detector_snapshot):
            reasons.append(
                MicroEdgeSuitabilityReason.SUITABILITY_DETECTOR_INCOMPLETE
            )
        elif _detector_is_toxic(evidence.detector_snapshot):
            reasons.append(MicroEdgeSuitabilityReason.SUITABILITY_DETECTOR_TOXIC)

    if reasons:
        if not isinstance(evidence, MicroEdgeSuitabilityEvidence) or evaluated_at is None:
            status = MicroEdgeSuitabilityStatus.UNAVAILABLE
        elif MicroEdgeSuitabilityReason.SUITABILITY_STALE in reasons:
            status = MicroEdgeSuitabilityStatus.STALE
        elif MicroEdgeSuitabilityReason.SUITABILITY_CANDIDATE_MISMATCH in reasons:
            status = MicroEdgeSuitabilityStatus.INVALID
        elif MicroEdgeSuitabilityReason.SUITABILITY_MALFORMED in reasons:
            status = MicroEdgeSuitabilityStatus.INVALID
        elif MicroEdgeSuitabilityReason.SUITABILITY_TIMESTAMP_MISSING in reasons:
            status = MicroEdgeSuitabilityStatus.UNAVAILABLE
        elif MicroEdgeSuitabilityReason.SUITABILITY_CALIBRATION_NOT_READY in reasons:
            status = MicroEdgeSuitabilityStatus.UNSUITABLE
        elif MicroEdgeSuitabilityReason.SUITABILITY_DETECTOR_INCOMPLETE in reasons:
            status = MicroEdgeSuitabilityStatus.INVALID
        elif MicroEdgeSuitabilityReason.SUITABILITY_DETECTOR_TOXIC in reasons:
            status = MicroEdgeSuitabilityStatus.UNSUITABLE
        else:
            status = MicroEdgeSuitabilityStatus.UNAVAILABLE
    else:
        status = MicroEdgeSuitabilityStatus.SUITABLE

    identity_hash = evidence.identity_hash() if isinstance(
        evidence, MicroEdgeSuitabilityEvidence
    ) else None

    return MicroEdgeSuitabilityContract(
        candidate_symbol=candidate_symbol,
        status=status,
        reason_codes=tuple(dict.fromkeys(reasons)),
        evaluated_at=evaluated_at,
        freshness_seconds=freshness,
        evidence_identity=identity_hash,
        calibration_ready=calibration_ready,
    )


def revalidate_micro_edge_suitability(
    contract,
    *,
    candidate_symbol,
    now,
    max_age_seconds=60,
) -> MicroEdgeSuitabilityContract:
    """Revalidate a previously issued suitability contract for Phase-2.

    The evidence identity is preserved; only freshness and identity are
    re-checked.  If the contract was already unsuitable, this is a no-op
    reproduce of the same status.
    """
    if not isinstance(contract, MicroEdgeSuitabilityContract):
        raise TypeError("MicroEdgeSuitabilityContract required")
    now = _utc(now)
    reasons = []
    if contract.status is not MicroEdgeSuitabilityStatus.SUITABLE:
        if contract.status is MicroEdgeSuitabilityStatus.STALE:
            freshness = (
                contract.freshness_seconds if contract.freshness_seconds is not None
                else float("inf")
            )
            if contract.evaluated_at is not None:
                freshness = (now - _utc(contract.evaluated_at)).total_seconds()
            if freshness < 0:
                reasons.append(MicroEdgeSuitabilityReason.SUITABILITY_MALFORMED)
            elif freshness > max_age_seconds:
                reasons.append(MicroEdgeSuitabilityReason.SUITABILITY_STALE)
        return MicroEdgeSuitabilityContract(
            candidate_symbol=contract.candidate_symbol,
            status=contract.status,
            reason_codes=(
                contract.reason_codes + tuple(dict.fromkeys(reasons))
                if reasons else contract.reason_codes
            ),
            evaluated_at=contract.evaluated_at,
            freshness_seconds=contract.freshness_seconds,
            evidence_identity=contract.evidence_identity,
            calibration_ready=contract.calibration_ready,
        )

    if contract.evaluated_at is None:
        return MicroEdgeSuitabilityContract(
            candidate_symbol=candidate_symbol,
            status=MicroEdgeSuitabilityStatus.UNAVAILABLE,
            reason_codes=(MicroEdgeSuitabilityReason.SUITABILITY_TIMESTAMP_MISSING,),
            evaluated_at=None, freshness_seconds=None,
            evidence_identity=contract.evidence_identity,
            calibration_ready=contract.calibration_ready,
        )

    freshness = (now - _utc(contract.evaluated_at)).total_seconds()
    if freshness < 0 or freshness > max_age_seconds:
        return MicroEdgeSuitabilityContract(
            candidate_symbol=candidate_symbol,
            status=MicroEdgeSuitabilityStatus.STALE,
            reason_codes=(MicroEdgeSuitabilityReason.SUITABILITY_STALE,),
            evaluated_at=contract.evaluated_at,
            freshness_seconds=freshness,
            evidence_identity=contract.evidence_identity,
            calibration_ready=contract.calibration_ready,
        )

    symbol_match = (
        isinstance(candidate_symbol, str) and candidate_symbol.strip()
        and isinstance(contract.candidate_symbol, str)
        and candidate_symbol.strip().upper()
        == contract.candidate_symbol.strip().upper()
    )
    if not symbol_match:
        return MicroEdgeSuitabilityContract(
            candidate_symbol=candidate_symbol,
            status=MicroEdgeSuitabilityStatus.INVALID,
            reason_codes=(MicroEdgeSuitabilityReason.SUITABILITY_CANDIDATE_MISMATCH,),
            evaluated_at=contract.evaluated_at,
            freshness_seconds=freshness,
            evidence_identity=contract.evidence_identity,
            calibration_ready=contract.calibration_ready,
        )

    return MicroEdgeSuitabilityContract(
        candidate_symbol=candidate_symbol,
        status=MicroEdgeSuitabilityStatus.SUITABLE,
        reason_codes=(),
        evaluated_at=contract.evaluated_at,
        freshness_seconds=freshness,
        evidence_identity=contract.evidence_identity,
        calibration_ready=contract.calibration_ready,
    )
