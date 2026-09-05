"""Durable, fail-closed SQLite persistence for Knowledge Evolution objects.

PERSISTENCE_ONLY.  The store is the foundation that lets D-8 Knowledge Evolution
objects survive restart.  It is NOT an operational authority and it never
controls TradingAI runtime, execution, strategy, money management, canonical
specification or any live/paper state.

Authority contract of this module:

    Knowledge Store Authority      = PERSISTENCE_ONLY
    Operational Authority          = NONE
    Execution Authority            = NONE
    Strategy / MM / Canonical Mutation = NONE
    Live / Paper / Loop / Auto Trade = NONE
    LLM / provider authority        = NONE (HUMAN_REVIEW_REQUIRED preserved)

The store deliberately REUSES the deterministic D-1/D-7 serialization and
fingerprinting helpers (``knowledge_core._base.stable_json`` and
``knowledge_core.drift.fingerprint_structured``) rather than introducing a
parallel hashing framework.

Safety rules
------------
- SQLite only, under a SEPARATE knowledge database (never the advisor
  conversation DB or the supervisor audit DB).
- ``PRAGMA foreign_keys=ON`` on every connection.
- ``isolation_level=None`` + ``BEGIN IMMEDIATE`` / ``COMMIT`` / ``ROLLBACK``.
- Bounded every read (``limit``) and every persisted collection/sub-collection.
- Append-only Human Review (no UPDATE / DELETE; protected by SQL triggers).
- No physical delete for Validated Knowledge or Human Review.
- Deterministic-id conflict detection: identical content is idempotent,
  conflicting content is FAIL_CLOSED.
- Review subject fingerprints bind approval to the exact Hypothesis + Validation
  so changed content invalidates a stale approval.
- Knowledge Store failure is isolated: it never reaches trading execution.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

from backend.knowledge_core._base import stable_json
from backend.knowledge_core.authority import SourceCategory, TruthLevel
from backend.knowledge_core.drift import (
    DriftAssessment,
    DriftFinding,
    DriftStatus,
    SourceKind,
    fingerprint_structured,
)
from backend.knowledge_core.provenance import ProvenanceRecord
from backend.knowledge_evolution._base import (
    MAX_D8_COUNTEREVIDENCE_IDS,
    MAX_D8_EVIDENCE_IDS,
    MAX_D8_FINDING_IDS,
    MAX_D8_LIMITATIONS,
    MAX_D8_PATTERN_IDS,
    MAX_D8_REASON_CODES,
    MAX_D8_SOURCE_REFERENCES,
    MAX_D8_WARNINGS,
)
from backend.knowledge_evolution.experience import ExperienceType
from backend.knowledge_evolution.finding import (
    Finding,
    FindingStatus,
)
from backend.knowledge_evolution.human_review import HumanReview, ReviewDecision
from backend.knowledge_evolution.hypothesis import (
    Hypothesis,
    HypothesisStatus,
    advance_hypothesis as d8_advance_hypothesis,
)
from backend.knowledge_evolution.investigation import (
    InvestigationFilter,
    InvestigationRequest,
)
from backend.knowledge_evolution.knowledge import (
    ValidatedKnowledge,
    ValidatedKnowledgeStatus,
    promote_to_validated_knowledge as d8_promote_to_validated_knowledge,
)
from backend.knowledge_evolution.pattern import (
    EvidenceStrength,
    Pattern,
    PatternStatus,
    PatternType,
    resolve_evidence_strength,
)
from backend.knowledge_evolution.validation import (
    AcceptanceCriterion,
    Relation,
    Validation,
    ValidationEvidence,
    ValidationMetric,
    ValidationMethod,
    ValidationResult,
)
from backend.runtime.unified_trace import (
    Provenance,
    SourceSubsystem,
    TraceCompleteness,
)

# --------------------------------------------------------------------------- #
# Store-level bounds / constants
# --------------------------------------------------------------------------- #

# Separate knowledge database.  Never advisor_conversations.sqlite3 and never
# supervisor_audit.sqlite3.
DEFAULT_KNOWLEDGE_STORE_PATH = Path("logs/runtime/tradingai_knowledge.sqlite3")

# Current schema version.  Any newer/unknown version FAILS CLOSED.
SCHEMA_VERSION = 1

# Bounded read projection limit.
MAX_READ_LIMIT = 200
DEFAULT_READ_LIMIT = 100

# Operator scope policy is NOT resolved in this foundation.  It is preserved as
# a neutral metadata label so future scoping can be added without a policy now.
OPERATOR_SCOPE_POLICY_UNRESOLVED = "OPERATOR_SCOPE_POLICY_UNRESOLVED"

# Safe operator/reviewer/persistence-identifier validation (matches advisor
# convention) plus the ``:`` used by deterministic IDs (``scope:sha256hex``).
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$")

# High-confidence secret markers; detected as whole tokens so ordinary trading
# prose is never redacted.
_SECRET_PATTERN = re.compile(
    r"\b("
    + "|".join(
        re.escape(m)
        for m in (
            "API_KEY",
            "APISECRET",
            "PRIVATE_KEY",
            "SECRET_KEY",
            "PASSPHRASE",
            "PASSWORD",
            "AUTHORIZATION",
            "CREDENTIAL",
            "COOKIE",
            "BEARER_TOKEN",
        )
    )
    + r")\b",
    re.IGNORECASE,
)

# SQLite trigger names used to enforce append-only / no-physical-delete.
_TRIGGER_REVIEW_UPDATE = "trg_human_review_no_update"
_TRIGGER_REVIEW_DELETE = "trg_human_review_no_delete"
_TRIGGER_KNOWLEDGE_DELETE = "trg_validated_knowledge_no_delete"

_SECRET_MARKERS = (
    "API_KEY",
    "APISECRET",
    "PRIVATE_KEY",
    "SECRET_KEY",
    "PASSPHRASE",
    "PASSWORD",
    "AUTHORIZATION",
    "CREDENTIAL",
    "COOKIE",
    "BEARER_TOKEN",
)


# --------------------------------------------------------------------------- #
# Typed store failure codes
# --------------------------------------------------------------------------- #


class KnowledgeStoreErrorCode(str, Enum):
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    OPERATOR_ACTION_REQUIRED = "OPERATOR_ACTION_REQUIRED"
    INPUT_INVALID = "INPUT_INVALID"
    NOT_FOUND = "NOT_FOUND"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    FOREIGN_KEY_VIOLATION = "FOREIGN_KEY_VIOLATION"
    CORRUPT_RECORD = "CORRUPT_RECORD"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    REVIEW_NOT_APPROVED = "REVIEW_NOT_APPROVED"
    REVIEW_VALIDATION_MISMATCH = "REVIEW_VALIDATION_MISMATCH"
    STALE_REVIEW = "STALE_REVIEW"
    PROMOTION_BLOCKED = "PROMOTION_BLOCKED"
    APPEND_ONLY_VIOLATION = "APPEND_ONLY_VIOLATION"


class KnowledgeStoreError(Exception):
    """Typed, safe persistence failure.  Never contains secret-bearing rows."""

    def __init__(self, code: KnowledgeStoreErrorCode, safe_message: str):
        super().__init__(f"knowledge store: {safe_message}")
        self.code = code
        self.safe_message = safe_message


def _raise(code: KnowledgeStoreErrorCode, message: str) -> None:
    raise KnowledgeStoreError(code, message)


# --------------------------------------------------------------------------- #
# Deterministic fingerprint of the review subject (Hypothesis + Validation)
# --------------------------------------------------------------------------- #


def review_subject_fingerprint(hypothesis: Hypothesis, validation: Validation) -> str:
    """Bind an approval to the immutable Hypothesis + Validation subject.

    Only deterministic, stored content is fingerprinted; volatile runtime values
    (timestamps, lifecycle status) are deliberately excluded so a review remains
    valid for the exact content the operator reviewed.
    """
    payload = {
        "hypothesis": {
            "hypothesisId": hypothesis.hypothesis_id,
            "statement": hypothesis.statement,
            "derivedFromFindingIds": sorted(_dedupe(hypothesis.derived_from_finding_ids)),
            "supportingPatternIds": sorted(_dedupe(hypothesis.supporting_pattern_ids)),
            "expectedEffect": hypothesis.expected_effect,
            "validationCriteria": sorted(tuple(v) for v in hypothesis.validation_criteria),
            "requiredEvidence": sorted(_dedupe(hypothesis.required_evidence)),
        },
        "validation": {
            "validationId": validation.validation_id,
            "hypothesisId": validation.hypothesis_id,
            "method": validation.method.value,
            "criteria": sorted(c.to_tuple() for c in validation.acceptance_criteria),
            "sampleSize": validation.sample_size,
            "supportCount": validation.support_count,
            "counterexampleCount": validation.counterexample_count,
            "result": validation.result.value,
            "datasetReferences": sorted(_dedupe(validation.evidence.dataset_references)),
        },
    }
    return fingerprint_structured(payload)


def _dedupe(items):
    seen = {}
    for item in items:
        if item not in seen:
            seen[item] = None
    return tuple(seen.keys())


# --------------------------------------------------------------------------- #
# Sanitization + bounded-text helpers
# --------------------------------------------------------------------------- #


def sanitize_text(value: str, *, limit: int) -> str:
    """Bound and redact a free-text human field before it is persisted.

    Secret-bearing free text is replaced with a neutral marker rather than
    persisted.  Ordinary prose is passed through unchanged.
    """
    text = str(value or "").strip()
    if "\x00" in text:
        raise ValueError("NUL is not allowed")
    if _SECRET_PATTERN.search(text):
        return "[REDACTED]"
    return text[:limit]


def _safe_identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _raise(KnowledgeStoreErrorCode.INPUT_INVALID, f"{name} is invalid")
    if not _IDENTIFIER.fullmatch(value):
        _raise(KnowledgeStoreErrorCode.INPUT_INVALID, f"{name} is invalid")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_iso(value: str) -> str:
    return str(value or "")[:64]


# --------------------------------------------------------------------------- #
# Plain<->typed serialization helpers (deterministic, allowlisted fields)
# --------------------------------------------------------------------------- #


def _date(value):
    if value is None:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _prov_record_from_plain(data: Mapping[str, Any]) -> ProvenanceRecord:
    return ProvenanceRecord(
        truth_level=TruthLevel(data["truth_level"]),
        source_category=SourceCategory(data["source_category"]),
        source_reference=data.get("source_reference") or "",
        source_path=data.get("source_path"),
        symbol=data.get("symbol"),
        version=data.get("version"),
        content_hash=data.get("content_hash"),
        verified=bool(data.get("verified", False)),
        notes=data.get("notes") or "",
        source_subsystem=data.get("source_subsystem"),
        source_type=data.get("source_type"),
        source_identifier=data.get("source_identifier"),
        observed_at=_date(data.get("observed_at")),
        source_timestamp=_date(data.get("source_timestamp")),
        loaded_at=_date(data.get("loaded_at")),
        freshness=data.get("freshness"),
        confidence=data.get("confidence"),
        warnings=tuple(data.get("warnings") or ()),
    )


def _runtime_prov_from_plain(data: Mapping[str, Any]) -> Provenance:
    return Provenance(
        source_subsystem=SourceSubsystem(data["source_subsystem"]),
        source_type=data["source_type"] or "",
        source_identifier=data["source_identifier"] or "",
        timestamp=data.get("timestamp"),
        linkage_method=data.get("linkage_method") or "EVIDENCE_REFERENCE",
        confidence=data.get("confidence"),
    )


def _crit_from_plain(data: Mapping[str, Any]) -> AcceptanceCriterion:
    return AcceptanceCriterion(
        metric=ValidationMetric(data["metric"]),
        relation=Relation(data["relation"]),
        threshold=float(data["threshold"]),
    )


def _evidence_from_plain(data: Mapping[str, Any]) -> ValidationEvidence:
    return ValidationEvidence(
        sample_size=int(data["sample_size"]),
        support_count=int(data["support_count"]),
        counterexample_count=int(data["counterexample_count"]),
        method=ValidationMethod(data["method"]),
        dataset_references=tuple(data.get("dataset_references") or ()),
        time_range=data.get("time_range"),
        source_references=tuple(
            _runtime_prov_from_plain(p) for p in (data.get("source_references") or ())
        ),
        available=bool(data.get("available", True)),
    )


def _drift_finding_from_plain(data: Mapping[str, Any]) -> DriftFinding:
    return DriftFinding(
        code=data["code"],
        status=DriftStatus(data["status"]),
        reason=data.get("reason") or "",
        expected_reference=data.get("expected_reference"),
        actual_reference=data.get("actual_reference"),
        authority_layer=TruthLevel(data["authority_layer"]) if data.get("authority_layer") else None,
        authoritative_layer=TruthLevel(data["authoritative_layer"])
        if data.get("authoritative_layer")
        else None,
        observed_at=_date(data.get("observed_at")),
        source_timestamp=_date(data.get("source_timestamp")),
        fingerprint_expected=data.get("fingerprint_expected"),
        fingerprint_actual=data.get("fingerprint_actual"),
        version_expected=data.get("version_expected"),
        version_actual=data.get("version_actual"),
        warnings=tuple(data.get("warnings") or ()),
        confidence=data.get("confidence"),
    )


def _drift_from_plain(data: Mapping[str, Any]) -> DriftAssessment:
    return DriftAssessment(
        subject=data["subject"],
        source_kind=SourceKind(data["source_kind"]),
        status=DriftStatus(data["status"]),
        findings=tuple(_drift_finding_from_plain(f) for f in (data.get("findings") or ())),
        assessed_at=_date(data.get("assessed_at")),
    )


def _filter_from_plain(data: Mapping[str, Any]) -> InvestigationFilter:
    return InvestigationFilter(
        symbol=data.get("symbol"),
        mode=data.get("mode"),
        started_from=data.get("started_from"),
        started_to=data.get("started_to"),
        trace_ids=tuple(data.get("trace_ids") or ()),
        decision_ids=tuple(data.get("decision_ids") or ()),
        trade_ids=tuple(data.get("trade_ids") or ()),
        experience_types=tuple(ExperienceType(t) for t in (data.get("experience_types") or ())),
        reason_codes=tuple(data.get("reason_codes") or ()),
        outcomes=tuple(data.get("outcomes") or ()),
        completeness=tuple(TraceCompleteness(c) for c in (data.get("completeness") or ())),
        drift_statuses=tuple(DriftStatus(s) for s in (data.get("drift_statuses") or ())),
    )


def _decode_investigation(payload: Mapping[str, Any]) -> InvestigationRequest:
    return InvestigationRequest(
        investigation_id=payload["investigation_id"],
        question=payload["question"],
        criterion=_filter_from_plain(payload["criterion"]),
        provenance=_prov_record_from_plain(payload["provenance"]),
        limit=int(payload.get("limit", 100)),
        warnings=tuple(payload.get("warnings") or ()),
    )


def _decode_pattern(payload: Mapping[str, Any]) -> Pattern:
    return Pattern(
        pattern_id=payload["pattern_id"],
        pattern_type=PatternType(payload["pattern_type"]),
        description=payload["description"] or "",
        support_count=int(payload["support_count"]),
        sample_size=int(payload["sample_size"]),
        counterexample_count=int(payload["counterexample_count"]),
        supporting_experience_ids=tuple(payload.get("supporting_experience_ids") or ()),
        counterexample_experience_ids=tuple(payload.get("counterexample_experience_ids") or ()),
        source_references=tuple(
            _runtime_prov_from_plain(p) for p in (payload.get("source_references") or ())
        ),
        provenance=_prov_record_from_plain(payload["provenance"]),
        evidence_strength=EvidenceStrength(payload["evidence_strength"]),
        status=PatternStatus(payload["status"]),
        causal_claim=bool(payload.get("causal_claim", False)),
        warnings=tuple(payload.get("warnings") or ()),
    )


def _decode_finding(payload: Mapping[str, Any]) -> Finding:
    return Finding(
        finding_id=payload["finding_id"],
        investigation_id=payload["investigation_id"],
        statement=payload["statement"],
        supporting_evidence_ids=tuple(payload.get("supporting_evidence_ids") or ()),
        counterevidence_ids=tuple(payload.get("counterevidence_ids") or ()),
        reason_codes=tuple(payload.get("reason_codes") or ()),
        source_references=tuple(
            _runtime_prov_from_plain(p) for p in (payload.get("source_references") or ())
        ),
        provenance=_prov_record_from_plain(payload["provenance"]),
        evidence_strength=EvidenceStrength(payload["evidence_strength"]),
        status=FindingStatus(payload["status"]),
        limitations=tuple(payload.get("limitations") or ()),
        warnings=tuple(payload.get("warnings") or ()),
    )


def _decode_hypothesis(payload: Mapping[str, Any]) -> Hypothesis:
    criteria = tuple(tuple(v) for v in (payload.get("validation_criteria") or ()))
    return Hypothesis(
        hypothesis_id=payload["hypothesis_id"],
        statement=payload["statement"],
        derived_from_finding_ids=tuple(payload.get("derived_from_finding_ids") or ()),
        supporting_pattern_ids=tuple(payload.get("supporting_pattern_ids") or ()),
        expected_effect=payload.get("expected_effect") or "",
        validation_criteria=criteria,
        required_evidence=tuple(payload.get("required_evidence") or ()),
        status=HypothesisStatus(payload["status"]),
        provenance=_prov_record_from_plain(payload["provenance"]),
        limitations=tuple(payload.get("limitations") or ()),
        warnings=tuple(payload.get("warnings") or ()),
        strategy_mutation=bool(payload.get("strategy_mutation", False)),
    )


def _decode_validation(payload: Mapping[str, Any]) -> Validation:
    return Validation(
        validation_id=payload["validation_id"],
        hypothesis_id=payload["hypothesis_id"],
        method=ValidationMethod(payload["method"]),
        evidence=_evidence_from_plain(payload["evidence"]),
        acceptance_criteria=tuple(
            _crit_from_plain(c) for c in (payload.get("acceptance_criteria") or ())
        ),
        metrics=dict(payload.get("metrics") or {}),
        sample_size=int(payload["sample_size"]),
        support_count=int(payload["support_count"]),
        counterexample_count=int(payload["counterexample_count"]),
        result=ValidationResult(payload["result"]),
        provenance=_prov_record_from_plain(payload["provenance"]),
        limitations=tuple(payload.get("limitations") or ()),
        warnings=tuple(payload.get("warnings") or ()),
    )


def _decode_review(payload: Mapping[str, Any]) -> HumanReview:
    return HumanReview(
        review_id=payload["review_id"],
        hypothesis_id=payload["hypothesis_id"],
        decision=ReviewDecision(payload["decision"]),
        reviewer=payload["reviewer"],
        reviewed_at=payload["reviewed_at"],
        notes=payload.get("notes") or "",
        provenance=_prov_record_from_plain(payload["provenance"]),
    )


def _decode_knowledge(payload: Mapping[str, Any]) -> ValidatedKnowledge:
    drift = _drift_from_plain(payload["drift"]) if payload.get("drift") else None
    return ValidatedKnowledge(
        knowledge_id=payload["knowledge_id"],
        statement=payload["statement"],
        origin_hypothesis_id=payload["origin_hypothesis_id"],
        validation_references=tuple(payload.get("validation_references") or ()),
        human_review_reference=payload["human_review_reference"],
        provenance=_prov_record_from_plain(payload["provenance"]),
        version=payload["version"],
        created_at=payload["created_at"],
        limitations=tuple(payload.get("limitations") or ()),
        scope=payload.get("scope") or "",
        status=ValidatedKnowledgeStatus(payload["status"]),
        drift=drift,
        warnings=tuple(payload.get("warnings") or ()),
    )


# --------------------------------------------------------------------------- #
# Bounded collection validation helpers (shape + bounds)
# --------------------------------------------------------------------------- #


def _validate_bounded_array(value: Any, *, name: str, limit: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, f"{name} is not an array")
    items = [str(item) for item in value]
    if len(items) > limit:
        _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, f"{name} exceeds bound")
    return tuple(items)


def _bounds_for_finding(payload: Mapping[str, Any]) -> None:
    _validate_bounded_array(
        payload.get("supporting_evidence_ids", ()), name="supporting_evidence_ids",
        limit=MAX_D8_EVIDENCE_IDS,
    )
    _validate_bounded_array(
        payload.get("counterevidence_ids", ()), name="counterevidence_ids",
        limit=MAX_D8_COUNTEREVIDENCE_IDS,
    )
    _validate_bounded_array(
        payload.get("reason_codes", ()), name="reason_codes",
        limit=MAX_D8_REASON_CODES,
    )
    _validate_bounded_array(
        payload.get("limitations", ()), name="limitations",
        limit=MAX_D8_LIMITATIONS,
    )
    _validate_bounded_array(
        payload.get("source_references", ()), name="source_references",
        limit=MAX_D8_SOURCE_REFERENCES,
    )


def _bounds_for_pattern(payload: Mapping[str, Any]) -> None:
    _validate_bounded_array(
        payload.get("supporting_experience_ids", ()), name="supporting_experience_ids",
        limit=MAX_D8_EVIDENCE_IDS,
    )
    _validate_bounded_array(
        payload.get("counterexample_experience_ids", ()), name="counterexample_experience_ids",
        limit=MAX_D8_COUNTEREVIDENCE_IDS,
    )
    _validate_bounded_array(
        payload.get("source_references", ()), name="source_references",
        limit=MAX_D8_SOURCE_REFERENCES,
    )


def _bounds_for_hypothesis(payload: Mapping[str, Any]) -> None:
    _validate_bounded_array(
        payload.get("derived_from_finding_ids", ()), name="derived_from_finding_ids",
        limit=MAX_D8_FINDING_IDS,
    )
    _validate_bounded_array(
        payload.get("supporting_pattern_ids", ()), name="supporting_pattern_ids",
        limit=MAX_D8_PATTERN_IDS,
    )
    _validate_bounded_array(
        payload.get("required_evidence", ()), name="required_evidence",
        limit=MAX_D8_EVIDENCE_IDS,
    )
    if len(payload.get("validation_criteria", ())) > 40:
        _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "validation_criteria exceeds bound")


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #


class KnowledgeEvolutionStore:
    """Durable, typed, fail-closed persistence for Knowledge Evolution.

    The store is intentionally NOT a general database API.  It exposes only
    the persistence operations this foundation requires and never exposes raw
    SQL, filesystem paths or any runtime-mutation capability.

    It is a PERSISTENCE_ONLY authority: it cannot start/stop/place orders, cannot
    mutate strategy / MM / execution, cannot write Canonical Specification, and
    cannot invoke any LLM / provider.
    """

    def __init__(
        self,
        path=DEFAULT_KNOWLEDGE_STORE_PATH,
        *,
        max_read_limit: int = MAX_READ_LIMIT,
        default_read_limit: int = DEFAULT_READ_LIMIT,
    ):
        self.path = Path(path)
        self.max_read_limit = int(max_read_limit)
        self.default_read_limit = int(default_read_limit)
        self._lock = threading.RLock()
        self._initialize()

    # -- lifecycle ----------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _initialize(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                version = self._read_schema_version(db)
                if version is None:
                    self._create_schema(db)
                    self._write_schema_version(db, SCHEMA_VERSION)
                elif version == SCHEMA_VERSION:
                    self._create_schema(db)
                else:
                    _raise(
                        KnowledgeStoreErrorCode.OPERATOR_ACTION_REQUIRED,
                        f"unsupported schema version {version}; expected {SCHEMA_VERSION}",
                    )
                db.execute("COMMIT")
        except KnowledgeStoreError:
            raise
        except (OSError, sqlite3.Error) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "knowledge store unavailable")

    def _read_schema_version(self, db) -> Optional[int]:
        if not self._table_exists(db, "_schema_meta"):
            return None
        row = db.execute(
            "SELECT value FROM _schema_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "schema_version is not an integer")

    def _write_schema_version(self, db, version: int) -> None:
        db.execute(
            "INSERT INTO _schema_meta(key, value) VALUES('schema_version', ?)",
            (str(version),),
        )

    def _table_exists(self, db, name: str) -> bool:
        row = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None

    def _create_schema(self, db) -> None:
        db.execute(
            "CREATE TABLE IF NOT EXISTS _schema_meta ("
            "key TEXT NOT NULL PRIMARY KEY,"
            "value TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS investigations ("
            "investigation_id TEXT NOT NULL PRIMARY KEY,"
            "question TEXT NOT NULL,"
            "result_limit INTEGER NOT NULL,"
            "scope_policy TEXT NOT NULL,"
            "payload TEXT NOT NULL,"
            "created_at TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS patterns ("
            "pattern_id TEXT NOT NULL PRIMARY KEY,"
            "status TEXT NOT NULL,"
            "evidence_strength TEXT NOT NULL,"
            "sample_size INTEGER NOT NULL,"
            "support_count INTEGER NOT NULL,"
            "counterexample_count INTEGER NOT NULL,"
            "scope_policy TEXT NOT NULL,"
            "payload TEXT NOT NULL,"
            "created_at TEXT NOT NULL)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS findings ("
            "finding_id TEXT NOT NULL PRIMARY KEY,"
            "investigation_id TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "evidence_strength TEXT NOT NULL,"
            "scope_policy TEXT NOT NULL,"
            "payload TEXT NOT NULL,"
            "created_at TEXT NOT NULL,"
            "FOREIGN KEY(investigation_id) REFERENCES investigations(investigation_id))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS hypotheses ("
            "hypothesis_id TEXT NOT NULL PRIMARY KEY,"
            "status TEXT NOT NULL,"
            "statement TEXT NOT NULL,"
            "scope_policy TEXT NOT NULL,"
            "payload TEXT NOT NULL,"
            "created_at TEXT NOT NULL,"
            "updated_at TEXT NOT NULL,"
            "superseded_by TEXT)"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS hypothesis_transitions ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT,"
            "hypothesis_id TEXT NOT NULL,"
            "from_status TEXT NOT NULL,"
            "to_status TEXT NOT NULL,"
            "transitioned_at TEXT NOT NULL,"
            "FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(hypothesis_id))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS validations ("
            "validation_id TEXT NOT NULL PRIMARY KEY,"
            "hypothesis_id TEXT NOT NULL,"
            "method TEXT NOT NULL,"
            "result TEXT NOT NULL,"
            "scope_policy TEXT NOT NULL,"
            "payload TEXT NOT NULL,"
            "created_at TEXT NOT NULL,"
            "FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(hypothesis_id))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS human_reviews ("
            "review_id TEXT NOT NULL PRIMARY KEY,"
            "hypothesis_id TEXT NOT NULL,"
            "validation_id TEXT NOT NULL,"
            "decision TEXT NOT NULL,"
            "reviewer TEXT NOT NULL,"
            "reviewed_at TEXT NOT NULL,"
            "subject_fingerprint TEXT NOT NULL,"
            "payload TEXT NOT NULL,"
            "created_at TEXT NOT NULL,"
            "FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(hypothesis_id),"
            "FOREIGN KEY(validation_id) REFERENCES validations(validation_id))"
        )
        db.execute(
            "CREATE TABLE IF NOT EXISTS validated_knowledge ("
            "knowledge_id TEXT NOT NULL PRIMARY KEY,"
            "hypothesis_id TEXT NOT NULL,"
            "validation_id TEXT NOT NULL,"
            "review_id TEXT NOT NULL,"
            "status TEXT NOT NULL,"
            "version TEXT NOT NULL,"
            "payload TEXT NOT NULL,"
            "created_at TEXT NOT NULL,"
            "FOREIGN KEY(hypothesis_id) REFERENCES hypotheses(hypothesis_id),"
            "FOREIGN KEY(validation_id) REFERENCES validations(validation_id),"
            "FOREIGN KEY(review_id) REFERENCES human_reviews(review_id))"
        )
        self._create_append_only_triggers(db)

    def _create_append_only_triggers(self, db) -> None:
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS {_TRIGGER_REVIEW_UPDATE} "
            "BEFORE UPDATE ON human_reviews "
            "BEGIN SELECT RAISE(ABORT, 'append-only human review: UPDATE forbidden'); END"
        )
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS {_TRIGGER_REVIEW_DELETE} "
            "BEFORE DELETE ON human_reviews "
            "BEGIN SELECT RAISE(ABORT, 'append-only human review: DELETE forbidden'); END"
        )
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS {_TRIGGER_KNOWLEDGE_DELETE} "
            "BEFORE DELETE ON validated_knowledge "
            "BEGIN SELECT RAISE(ABORT, 'validated knowledge: DELETE forbidden'); END"
        )

    @property
    def schema_version(self) -> int:
        return SCHEMA_VERSION

    def close(self) -> None:
        """Close the store.  No persistent resources are held across calls."""
        return None

    # -- low-level transaction helpers -------------------------------------

    def _transaction(self):
        return _store_transaction(self._connect, self._lock)

    # -- Investigation ------------------------------------------------------

    def save_investigation(self, request: InvestigationRequest) -> str:
        if not isinstance(request, InvestigationRequest):
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "typed InvestigationRequest required")
        investigation_id = _safe_identifier(request.investigation_id, "investigationId")
        payload_data = _investigation_to_plain(request)
        payload = stable_json(payload_data)
        try:
            with self._transaction() as db:
                existing = db.execute(
                    "SELECT payload FROM investigations WHERE investigation_id=?",
                    (investigation_id,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != payload:
                        _raise(
                            KnowledgeStoreErrorCode.DUPLICATE_CONFLICT,
                            "investigation id re-used with different content",
                        )
                else:
                    db.execute(
                        "INSERT INTO investigations"
                        "(investigation_id,question,result_limit,scope_policy,payload,created_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (
                            investigation_id,
                            payload_data["question"],
                            int(request.limit),
                            OPERATOR_SCOPE_POLICY_UNRESOLVED,
                            payload,
                            _now(),
                        ),
                    )
        except KnowledgeStoreError:
            raise
        except sqlite3.IntegrityError as error:
            _raise(KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION, "investigation insert conflict")
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "investigation store unavailable")
        return investigation_id

    def get_investigation(self, investigation_id: str) -> Optional[InvestigationRequest]:
        investigation_id = _safe_identifier(investigation_id, "investigationId")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload FROM investigations WHERE investigation_id=?",
                    (investigation_id,),
                ).fetchone()
            if row is None:
                return None
            return _decode_investigation(_load_json(row[0]))
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "investigation payload corrupt")

    # -- Pattern ------------------------------------------------------------

    def save_pattern(self, pattern: Pattern) -> str:
        if not isinstance(pattern, Pattern):
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "typed Pattern required")
        pattern_id = _safe_identifier(pattern.pattern_id, "patternId")
        normalized = _normalize_pattern(pattern)
        payload_data = _pattern_to_plain(normalized)
        _bounds_for_pattern(payload_data)
        payload = stable_json(payload_data)
        try:
            with self._transaction() as db:
                existing = db.execute(
                    "SELECT payload FROM patterns WHERE pattern_id=?", (pattern_id,)
                ).fetchone()
                if existing is not None and existing[0] != payload:
                    _raise(
                        KnowledgeStoreErrorCode.DUPLICATE_CONFLICT,
                        "pattern id re-used with different content",
                    )
                if existing is None:
                    db.execute(
                        "INSERT INTO patterns"
                        "(pattern_id,status,evidence_strength,sample_size,"
                        "support_count,counterexample_count,scope_policy,payload,created_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            pattern_id,
                            normalized.status.value,
                            normalized.evidence_strength.value,
                            normalized.sample_size,
                            normalized.support_count,
                            normalized.counterexample_count,
                            OPERATOR_SCOPE_POLICY_UNRESOLVED,
                            payload,
                            _now(),
                        ),
                    )
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "pattern store unavailable")
        return pattern_id

    def get_pattern(self, pattern_id: str) -> Optional[Pattern]:
        pattern_id = _safe_identifier(pattern_id, "patternId")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload FROM patterns WHERE pattern_id=?", (pattern_id,)
                ).fetchone()
            if row is None:
                return None
            payload = _load_json(row[0])
            _bounds_for_pattern(payload)
            pattern = _decode_pattern(payload)
            # Recompute derived status/strength; never allow a singleton to be
            # silently reloaded as a repeated pattern.
            return _normalize_pattern(pattern)
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "pattern payload corrupt")

    # -- Finding ------------------------------------------------------------

    def save_finding(self, finding: Finding) -> str:
        if not isinstance(finding, Finding):
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "typed Finding required")
        finding_id = _safe_identifier(finding.finding_id, "findingId")
        investigation_id = _safe_identifier(finding.investigation_id, "investigationId")
        payload_data = _finding_to_plain(finding)
        _bounds_for_finding(payload_data)
        payload = stable_json(payload_data)
        try:
            with self._transaction() as db:
                if db.execute(
                    "SELECT 1 FROM investigations WHERE investigation_id=?",
                    (investigation_id,),
                ).fetchone() is None:
                    _raise(
                        KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION,
                        "orphan finding rejected: investigation does not exist",
                    )
                existing = db.execute(
                    "SELECT payload FROM findings WHERE finding_id=?", (finding_id,)
                ).fetchone()
                if existing is not None and existing[0] != payload:
                    _raise(
                        KnowledgeStoreErrorCode.DUPLICATE_CONFLICT,
                        "finding id re-used with different content",
                    )
                if existing is None:
                    db.execute(
                        "INSERT INTO findings"
                        "(finding_id,investigation_id,status,evidence_strength,"
                        "scope_policy,payload,created_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            finding_id,
                            investigation_id,
                            finding.status.value,
                            finding.evidence_strength.value,
                            OPERATOR_SCOPE_POLICY_UNRESOLVED,
                            payload,
                            _now(),
                        ),
                    )
        except KnowledgeStoreError:
            raise
        except sqlite3.IntegrityError as error:
            _raise(KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION, "finding references missing investigation")
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "finding store unavailable")
        return finding_id

    def get_finding(self, finding_id: str) -> Optional[Finding]:
        finding_id = _safe_identifier(finding_id, "findingId")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload FROM findings WHERE finding_id=?", (finding_id,)
                ).fetchone()
            if row is None:
                return None
            payload = _load_json(row[0])
            _bounds_for_finding(payload)
            finding = _decode_finding(payload)
            # Orphan prevention: a finding whose investigation is missing must
            # not silently load as fully valid.
            self._assert_finding_investigation_exists(finding)
            return finding
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "finding payload corrupt")

    def _assert_finding_investigation_exists(self, finding: Finding) -> None:
        try:
            with self._connect() as db:
                exists = db.execute(
                    "SELECT 1 FROM investigations WHERE investigation_id=?",
                    (finding.investigation_id,),
                ).fetchone()
            if exists is None:
                _raise(
                    KnowledgeStoreErrorCode.CORRUPT_RECORD,
                    "orphan finding: investigation is missing",
                )
        except KnowledgeStoreError:
            raise
        except sqlite3.Error as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "finding store unavailable")

    # -- Hypothesis ---------------------------------------------------------

    def create_hypothesis(self, hypothesis: Hypothesis) -> str:
        if not isinstance(hypothesis, Hypothesis):
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "typed Hypothesis required")
        if hypothesis.status is not HypothesisStatus.PROPOSED:
            _raise(
                KnowledgeStoreErrorCode.INPUT_INVALID,
                "a hypothesis must be created in PROPOSED state",
            )
        hypothesis_id = _safe_identifier(hypothesis.hypothesis_id, "hypothesisId")
        payload_data = _hypothesis_to_plain(hypothesis)
        _bounds_for_hypothesis(payload_data)
        payload = stable_json(payload_data)
        created = _now()
        try:
            with self._transaction() as db:
                existing = db.execute(
                    "SELECT payload FROM hypotheses WHERE hypothesis_id=?",
                    (hypothesis_id,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != payload:
                        _raise(
                            KnowledgeStoreErrorCode.DUPLICATE_CONFLICT,
                            "hypothesis id re-used with different content",
                        )
                else:
                    db.execute(
                        "INSERT INTO hypotheses"
                        "(hypothesis_id,status,statement,scope_policy,payload,"
                        "created_at,updated_at,superseded_by) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            hypothesis_id,
                            hypothesis.status.value,
                            hypothesis.statement,
                            OPERATOR_SCOPE_POLICY_UNRESOLVED,
                            payload,
                            created,
                            created,
                            None,
                        ),
                    )
        except KnowledgeStoreError:
            raise
        except sqlite3.IntegrityError as error:
            _raise(KnowledgeStoreErrorCode.DUPLICATE_CONFLICT, "hypothesis insert conflict")
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "hypothesis store unavailable")
        return hypothesis_id

    def get_hypothesis(self, hypothesis_id: str) -> Optional[Hypothesis]:
        hypothesis_id = _safe_identifier(hypothesis_id, "hypothesisId")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload FROM hypotheses WHERE hypothesis_id=?",
                    (hypothesis_id,),
                ).fetchone()
            if row is None:
                return None
            payload = _load_json(row[0])
            _bounds_for_hypothesis(payload)
            return _decode_hypothesis(payload)
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "hypothesis payload corrupt")

    def transition_hypothesis(
        self,
        hypothesis_id: str,
        target: HypothesisStatus,
        *,
        transitioned_at: Optional[str] = None,
        require_criteria_if_ready: bool = True,
    ) -> Hypothesis:
        """Deterministically advance a hypothesis through the D-8 lifecycle.

        The store applies the SAME transition rules as ``advance_hypothesis`` and
        appends a durable append-only transition-history record.  It can never
        bypass the D-8 gate.
        """
        hypothesis_id = _safe_identifier(hypothesis_id, "hypothesisId")
        if not isinstance(target, HypothesisStatus):
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "target must be a HypothesisStatus")
        now = transitioned_at or _now()
        previous = self.get_hypothesis(hypothesis_id)
        if previous is None:
            _raise(KnowledgeStoreErrorCode.NOT_FOUND, "hypothesis not found")
        try:
            advanced = d8_advance_hypothesis(
                previous, target, require_criteria_if_ready=require_criteria_if_ready
            )
        except ValueError as error:
            _raise(KnowledgeStoreErrorCode.INVALID_TRANSITION, "illegal hypothesis transition")
        payload_data = _hypothesis_to_plain(advanced)
        payload = stable_json(payload_data)
        try:
            with self._transaction() as db:
                if previous.status is not target:
                    db.execute(
                        "INSERT INTO hypothesis_transitions"
                        "(hypothesis_id,from_status,to_status,transitioned_at)"
                        " VALUES(?,?,?,?)",
                        (hypothesis_id, previous.status.value, target.value, now),
                    )
                db.execute(
                    "UPDATE hypotheses SET status=?,payload=?,updated_at=?,"
                    "superseded_by=? WHERE hypothesis_id=?",
                    (
                        target.value,
                        payload,
                        now,
                        target.value if target is HypothesisStatus.SUPERSEDED else None,
                        hypothesis_id,
                    ),
                )
        except KnowledgeStoreError:
            raise
        except sqlite3.Error as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "hypothesis transition failed")
        return self.get_hypothesis(hypothesis_id)

    def list_hypothesis_transitions(
        self,
        hypothesis_id: str,
        *,
        limit: Optional[int] = None,
    ) -> tuple[dict[str, str], ...]:
        hypothesis_id = _safe_identifier(hypothesis_id, "hypothesisId")
        limit = self._bounded_limit(limit)
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT hypothesis_id,from_status,to_status,transitioned_at "
                    "FROM hypothesis_transitions WHERE hypothesis_id=? "
                    "ORDER BY seq ASC LIMIT ?",
                    (hypothesis_id, limit),
                ).fetchall()
            return tuple(
                {
                    "hypothesisId": row[0],
                    "fromStatus": row[1],
                    "toStatus": row[2],
                    "transitionedAt": row[3],
                }
                for row in rows
            )
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "transition history unavailable")

    # -- Validation ---------------------------------------------------------

    def save_validation(self, validation: Validation) -> str:
        if not isinstance(validation, Validation):
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "typed Validation required")
        validation_id = _safe_identifier(validation.validation_id, "validationId")
        hypothesis_id = _safe_identifier(validation.hypothesis_id, "hypothesisId")
        payload_data = _validation_to_plain(validation)
        payload = stable_json(payload_data)
        try:
            with self._transaction() as db:
                if db.execute(
                    "SELECT 1 FROM hypotheses WHERE hypothesis_id=?",
                    (hypothesis_id,),
                ).fetchone() is None:
                    raise KnowledgeStoreError(
                        KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION,
                        "validation references missing hypothesis",
                    )
                existing = db.execute(
                    "SELECT payload FROM validations WHERE validation_id=?",
                    (validation_id,),
                ).fetchone()
                if existing is not None and existing[0] != payload:
                    _raise(
                        KnowledgeStoreErrorCode.DUPLICATE_CONFLICT,
                        "validation id re-used with different content",
                    )
                if existing is None:
                    db.execute(
                        "INSERT INTO validations"
                        "(validation_id,hypothesis_id,method,result,scope_policy,payload,created_at)"
                        " VALUES(?,?,?,?,?,?,?)",
                        (
                            validation_id,
                            hypothesis_id,
                            validation.method.value,
                            validation.result.value,
                            OPERATOR_SCOPE_POLICY_UNRESOLVED,
                            payload,
                            _now(),
                        ),
                    )
        except KnowledgeStoreError:
            raise
        except sqlite3.IntegrityError as error:
            _raise(KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION, "validation references missing hypothesis")
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "validation store unavailable")
        return validation_id

    def get_validation(self, validation_id: str) -> Optional[Validation]:
        validation_id = _safe_identifier(validation_id, "validationId")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload FROM validations WHERE validation_id=?",
                    (validation_id,),
                ).fetchone()
            if row is None:
                return None
            payload = _load_json(row[0])
            validation = _decode_validation(payload)
            if len(validation.acceptance_criteria) > 40:
                _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "acceptance_criteria exceeds bound")
            return validation
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "validation payload corrupt")

    # -- Human Review (APPEND-ONLY) -----------------------------------------

    def append_human_review(
        self,
        review: HumanReview,
        *,
        validation: Validation,
    ) -> str:
        """Persist a Human Review, pinning it to the reviewed Validation.

        The approval is recorded as an APPEND-ONLY record.  The store never
        fabricates reviewer identity and never treats provider output as human
        approval.  A review may only be recorded if the persisted Hypothesis and
        the pinned Validation both exist and belong together.
        """
        if not isinstance(review, HumanReview):
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "typed HumanReview required")
        if not isinstance(validation, Validation):
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "typed Validation required")
        if review.decision is not ReviewDecision.APPROVED and review.decision not in {
            ReviewDecision.REJECTED,
            ReviewDecision.NEEDS_MORE_EVIDENCE,
        }:
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "review decision is invalid")
        review_id = _safe_identifier(review.review_id, "reviewId")
        hypothesis_id = _safe_identifier(review.hypothesis_id, "hypothesisId")
        reviewer = _safe_identifier(review.reviewer, "reviewer")
        validation_id = _safe_identifier(validation.validation_id, "validationId")

        hypothesis = self.get_hypothesis(hypothesis_id)
        if hypothesis is None:
            _raise(KnowledgeStoreErrorCode.NOT_FOUND, "hypothesis not found for review")
        # The review pins the PERSISTED validation (the authority for approval).
        persisted_validation = self.get_validation(validation_id)
        if persisted_validation is None:
            _raise(KnowledgeStoreErrorCode.NOT_FOUND, "validation not found for review")
        if validation.hypothesis_id != hypothesis_id:
            _raise(
                KnowledgeStoreErrorCode.REVIEW_VALIDATION_MISMATCH,
                "validation does not belong to review hypothesis",
            )
        if persisted_validation.hypothesis_id != hypothesis_id:
            _raise(
                KnowledgeStoreErrorCode.REVIEW_VALIDATION_MISMATCH,
                "validation does not belong to review hypothesis",
            )
        fingerprint = review_subject_fingerprint(hypothesis, persisted_validation)
        payload_data = _review_to_plain(review)
        payload = stable_json(payload_data)
        created = _now()
        try:
            with self._transaction() as db:
                existing = db.execute(
                    "SELECT payload,subject_fingerprint,validation_id,reviewer "
                    "FROM human_reviews WHERE review_id=?",
                    (review_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing[0] == payload
                        and existing[1] == fingerprint
                        and existing[2] == validation_id
                        and existing[3] == reviewer
                    ):
                        return review_id
                    _raise(
                        KnowledgeStoreErrorCode.DUPLICATE_CONFLICT,
                        "review id re-used with different content",
                    )
                db.execute(
                    "INSERT INTO human_reviews"
                    "(review_id,hypothesis_id,validation_id,decision,reviewer,"
                    "reviewed_at,subject_fingerprint,payload,created_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        review_id,
                        hypothesis_id,
                        validation_id,
                        review.decision.value,
                        reviewer,
                        _to_iso(review.reviewed_at),
                        fingerprint,
                        payload,
                        created,
                    ),
                )
        except KnowledgeStoreError:
            raise
        except sqlite3.IntegrityError as error:
            _raise(
                KnowledgeStoreErrorCode.FOREIGN_KEY_VIOLATION,
                "review references missing hypothesis/validation",
            )
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "human review store unavailable")
        return review_id

    def get_human_review(self, review_id: str) -> Optional[HumanReview]:
        review_id = _safe_identifier(review_id, "reviewId")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload FROM human_reviews WHERE review_id=?", (review_id,)
                ).fetchone()
            if row is None:
                return None
            return _decode_review(_load_json(row[0]))
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "human review payload corrupt")

    def _review_metadata(self, review_id: str) -> Optional[dict[str, Any]]:
        review_id = _safe_identifier(review_id, "reviewId")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT hypothesis_id,validation_id,decision,reviewer,subject_fingerprint "
                    "FROM human_reviews WHERE review_id=?",
                    (review_id,),
                ).fetchone()
            if row is None:
                return None
            return {
                "hypothesis_id": row[0],
                "validation_id": row[1],
                "decision": row[2],
                "reviewer": row[3],
                "subject_fingerprint": row[4],
            }
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "human review store unavailable")

    def list_human_reviews(
        self,
        hypothesis_id: Optional[str] = None,
        *,
        limit: Optional[int] = None,
    ) -> tuple[dict[str, Any], ...]:
        limit = self._bounded_limit(limit)
        where = ""
        args: list[Any] = []
        if hypothesis_id is not None:
            where = " WHERE hypothesis_id=?"
            args.append(_safe_identifier(hypothesis_id, "hypothesisId"))
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT review_id,hypothesis_id,validation_id,decision,reviewer,"
                    "reviewed_at,subject_fingerprint FROM human_reviews"
                    + where
                    + " ORDER BY created_at ASC LIMIT ?",
                    (*args, limit),
                ).fetchall()
            return tuple(
                {
                    "reviewId": row[0],
                    "hypothesisId": row[1],
                    "validationId": row[2],
                    "decision": row[3],
                    "reviewer": row[4],
                    "reviewedAt": row[5],
                    "subjectFingerprint": row[6],
                }
                for row in rows
            )
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "human review list unavailable")

    # -- Atomic promotion ---------------------------------------------------

    def promote_to_validated_knowledge(
        self,
        *,
        hypothesis_id: str,
        validation_id: str,
        review_id: str,
        version: str = "1.0",
        created_at: str = "",
        scope: str = "",
        limitations=(),
        drift=None,
    ) -> ValidatedKnowledge:
        """Atomically promote to Validated Knowledge (P0 invariant).

        Single SQLite transaction.  All gates verified inside the transaction:
        SUPPORTED Hypothesis + SUPPORTED Validation (belonging to that
        hypothesis) + APPROVED HumanReview (pinning that validation) + matching
        review-subject fingerprint => ValidatedKnowledge.  Any failure ROLLBACKs.

        Returns the promoted object; there is no partial Validated Knowledge.
        """
        hypothesis_id = _safe_identifier(hypothesis_id, "hypothesisId")
        validation_id = _safe_identifier(validation_id, "validationId")
        review_id = _safe_identifier(review_id, "reviewId")
        try:
            with self._transaction() as db:
                hypothesis = self._load_hypothesis_by_id(db, hypothesis_id)
                if hypothesis is None:
                    _raise(KnowledgeStoreErrorCode.NOT_FOUND, "hypothesis not found")
                if hypothesis.status is not HypothesisStatus.SUPPORTED:
                    _raise(
                        KnowledgeStoreErrorCode.PROMOTION_BLOCKED,
                        "promotion requires SUPPORTED hypothesis",
                    )
                validation = self._load_validation_by_id(db, validation_id)
                if validation is None:
                    _raise(KnowledgeStoreErrorCode.NOT_FOUND, "validation not found")
                if validation.result is not ValidationResult.SUPPORTED:
                    _raise(
                        KnowledgeStoreErrorCode.PROMOTION_BLOCKED,
                        "promotion requires SUPPORTED validation",
                    )
                if validation.hypothesis_id != hypothesis_id:
                    _raise(
                        KnowledgeStoreErrorCode.PROMOTION_BLOCKED,
                        "validation does not belong to hypothesis",
                    )
                review_meta = self._load_review_meta_by_id(db, review_id)
                if review_meta is None:
                    _raise(KnowledgeStoreErrorCode.NOT_FOUND, "human review not found")
                if review_meta["decision"] != ReviewDecision.APPROVED.value:
                    _raise(
                        KnowledgeStoreErrorCode.REVIEW_NOT_APPROVED,
                        "promotion requires APPROVED human review",
                    )
                if review_meta["hypothesis_id"] != hypothesis_id:
                    _raise(
                        KnowledgeStoreErrorCode.REVIEW_VALIDATION_MISMATCH,
                        "review does not belong to hypothesis",
                    )
                if review_meta["validation_id"] != validation_id:
                    _raise(
                        KnowledgeStoreErrorCode.REVIEW_VALIDATION_MISMATCH,
                        "review does not pin this validation",
                    )
                review = _decode_review(_load_json_db(db, "human_reviews", "review_id", review_id))
                current_fingerprint = review_subject_fingerprint(hypothesis, validation)
                if current_fingerprint != review_meta["subject_fingerprint"]:
                    _raise(
                        KnowledgeStoreErrorCode.STALE_REVIEW,
                        "review subject does not match current hypothesis/validation",
                    )
                promoted = d8_promote_to_validated_knowledge(
                    hypothesis,
                    validation,
                    review,
                    version=version,
                    created_at=created_at,
                    scope=scope,
                    limitations=limitations,
                    drift=drift,
                )
                knowledge_id = promoted.knowledge_id
                self._insert_validated_knowledge(db, promoted, hypothesis_id, validation_id, review_id)
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError) as error:
            _raise(KnowledgeStoreErrorCode.STORE_UNAVAILABLE, "knowledge store unavailable")
        return self.get_validated_knowledge(knowledge_id)

    # -- Validated Knowledge -------------------------------------------------

    def get_validated_knowledge(self, knowledge_id: str) -> Optional[ValidatedKnowledge]:
        knowledge_id = _safe_identifier(knowledge_id, "knowledgeId")
        try:
            with self._connect() as db:
                row = db.execute(
                    "SELECT payload FROM validated_knowledge WHERE knowledge_id=?",
                    (knowledge_id,),
                ).fetchone()
            if row is None:
                return None
            return _decode_knowledge(_load_json(row[0]))
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "validated knowledge payload corrupt")

    def list_validated_knowledge(
        self,
        hypothesis_id: Optional[str] = None,
        *,
        limit: Optional[int] = None,
    ) -> tuple[ValidatedKnowledge, ...]:
        limit = self._bounded_limit(limit)
        where = ""
        args: list[Any] = []
        if hypothesis_id is not None:
            where = " WHERE hypothesis_id=?"
            args.append(_safe_identifier(hypothesis_id, "hypothesisId"))
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT payload FROM validated_knowledge"
                    + where
                    + " ORDER BY created_at ASC LIMIT ?",
                    (*args, limit),
                ).fetchall()
            return tuple(_decode_knowledge(_load_json(row[0])) for row in rows)
        except KnowledgeStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError, KeyError) as error:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "validated knowledge list corrupt")

    # -- internal loaders (single-connection, for atomic transactions) ------

    def _load_hypothesis_by_id(self, db, hypothesis_id):
        row = db.execute(
            "SELECT payload FROM hypotheses WHERE hypothesis_id=?", (hypothesis_id,)
        ).fetchone()
        if row is None:
            return None
        payload = _load_json(row[0])
        _bounds_for_hypothesis(payload)
        return _decode_hypothesis(payload)

    def _load_validation_by_id(self, db, validation_id):
        row = db.execute(
            "SELECT payload FROM validations WHERE validation_id=?", (validation_id,)
        ).fetchone()
        if row is None:
            return None
        validation = _decode_validation(_load_json(row[0]))
        if len(validation.acceptance_criteria) > 40:
            _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "acceptance_criteria exceeds bound")
        return validation

    def _load_review_meta_by_id(self, db, review_id):
        row = db.execute(
            "SELECT hypothesis_id,validation_id,decision,reviewer,subject_fingerprint "
            "FROM human_reviews WHERE review_id=?",
            (review_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "hypothesis_id": row[0],
            "validation_id": row[1],
            "decision": row[2],
            "reviewer": row[3],
            "subject_fingerprint": row[4],
        }

    def _insert_validated_knowledge(
        self, db, promoted, hypothesis_id, validation_id, review_id
    ) -> None:
        payload_data = _knowledge_to_plain(promoted)
        payload = stable_json(payload_data)
        existing = db.execute(
            "SELECT payload FROM validated_knowledge WHERE knowledge_id=?",
            (promoted.knowledge_id,),
        ).fetchone()
        if existing is not None and existing[0] != payload:
            _raise(
                KnowledgeStoreErrorCode.DUPLICATE_CONFLICT,
                "validated knowledge id re-used with different content",
            )
        if existing is None:
            db.execute(
                "INSERT INTO validated_knowledge"
                "(knowledge_id,hypothesis_id,validation_id,review_id,status,version,payload,created_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (
                    promoted.knowledge_id,
                    hypothesis_id,
                    validation_id,
                    review_id,
                    promoted.status.value,
                    promoted.version,
                    payload,
                    _now(),
                ),
            )

    # -- generic helpers ----------------------------------------------------

    def _bounded_limit(self, limit: Optional[int]) -> int:
        if limit is None:
            return self.default_read_limit
        if not isinstance(limit, int) or limit < 1:
            _raise(KnowledgeStoreErrorCode.INPUT_INVALID, "limit must be a positive integer")
        return min(limit, self.max_read_limit)

    def foreign_keys_enabled(self) -> bool:
        """True if ``PRAGMA foreign_keys`` is enforced on store connections."""
        try:
            with self._connect() as db:
                return int(db.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        except (sqlite3.Error, OSError):
            return False

    def evidence_authority(self) -> str:
        """The Knowledge Store carries NO authoritative trading-history record."""
        return "PERSISTENCE_ONLY"

    def has_experience_table(self) -> bool:
        """True only if an Experience table was created (it MUST NOT be)."""
        try:
            with self._connect() as db:
                return (
                    self._table_exists(db, "experiences")
                    or self._table_exists(db, "experience_records")
                )
        except sqlite3.Error:
            return False

    def authoritative_authority_report(self) -> dict[str, str]:
        """Deterministic authority report consumed by tests / operator tools."""
        return {
            "TradingTraceStore": "AUTHORITATIVE_HISTORICAL_TRACE",
            "ExperienceRecord": "EVIDENCE_ONLY_REBUILDABLE",
            "KnowledgeStore": "PERSISTENCE_ONLY",
            "Operational": "NONE",
            "Execution": "NONE",
            "Strategy": "NONE",
            "MM": "NONE",
            "Canonical": "NONE",
        }


# --------------------------------------------------------------------------- #
# Plain serializers (object -> deterministic plain dict used for payloads)
# --------------------------------------------------------------------------- #


def _investigation_to_plain(value: InvestigationRequest) -> dict[str, Any]:
    return {
        "investigation_id": value.investigation_id,
        "question": sanitize_text(value.question, limit=512),
        "criterion": _filter_to_plain(value.criterion),
        "provenance": _prov_record_to_plain(value.provenance),
        "limit": int(value.limit),
        "warnings": list(value.warnings),
    }


def _prov_record_to_plain(record: ProvenanceRecord) -> dict[str, Any]:
    return {
        "truth_level": record.truth_level.value,
        "source_category": record.source_category.value,
        "source_reference": record.source_reference,
        "source_path": record.source_path,
        "symbol": record.symbol,
        "version": record.version,
        "content_hash": record.content_hash,
        "verified": record.verified,
        "notes": record.notes,
        "source_subsystem": record.source_subsystem,
        "source_type": record.source_type,
        "source_identifier": record.source_identifier,
        "observed_at": record.observed_at.isoformat() if record.observed_at else None,
        "source_timestamp": record.source_timestamp.isoformat() if record.source_timestamp else None,
        "loaded_at": record.loaded_at.isoformat() if record.loaded_at else None,
        "freshness": record.freshness,
        "confidence": record.confidence,
        "warnings": list(record.warnings),
    }


def _runtime_prov_to_plain(value: Provenance) -> dict[str, Any]:
    return {
        "source_subsystem": value.source_subsystem.value,
        "source_type": value.source_type,
        "source_identifier": value.source_identifier,
        "timestamp": value.timestamp,
        "linkage_method": value.linkage_method,
        "confidence": value.confidence,
    }


def _filter_to_plain(value: InvestigationFilter) -> dict[str, Any]:
    return {
        "symbol": value.symbol,
        "mode": value.mode,
        "started_from": value.started_from,
        "started_to": value.started_to,
        "trace_ids": list(value.trace_ids),
        "decision_ids": list(value.decision_ids),
        "trade_ids": list(value.trade_ids),
        "experience_types": [t.value for t in value.experience_types],
        "reason_codes": list(value.reason_codes),
        "outcomes": list(value.outcomes),
        "completeness": [c.value for c in value.completeness],
        "drift_statuses": [d.value for d in value.drift_statuses],
    }


def _crit_to_plain(value: AcceptanceCriterion) -> dict[str, Any]:
    return {"metric": value.metric.value, "relation": value.relation.value, "threshold": value.threshold}


def _evidence_to_plain(value: ValidationEvidence) -> dict[str, Any]:
    return {
        "sample_size": value.sample_size,
        "support_count": value.support_count,
        "counterexample_count": value.counterexample_count,
        "method": value.method.value,
        "dataset_references": list(value.dataset_references),
        "time_range": value.time_range,
        "source_references": [_runtime_prov_to_plain(p) for p in value.source_references],
        "available": value.available,
    }


def _drift_to_plain(value: DriftAssessment) -> dict[str, Any]:
    return {
        "subject": value.subject,
        "source_kind": value.source_kind.value,
        "status": value.status.value,
        "findings": [_drift_finding_to_plain(f) for f in value.findings],
        "assessed_at": value.assessed_at.isoformat() if value.assessed_at else None,
    }


def _drift_finding_to_plain(value: DriftFinding) -> dict[str, Any]:
    def _tl(value):
        return value.value if value else None

    return {
        "code": value.code,
        "status": value.status.value,
        "reason": value.reason,
        "expected_reference": value.expected_reference,
        "actual_reference": value.actual_reference,
        "authority_layer": _tl(value.authority_layer),
        "authoritative_layer": _tl(value.authoritative_layer),
        "observed_at": value.observed_at.isoformat() if value.observed_at else None,
        "source_timestamp": value.source_timestamp.isoformat() if value.source_timestamp else None,
        "fingerprint_expected": value.fingerprint_expected,
        "fingerprint_actual": value.fingerprint_actual,
        "version_expected": value.version_expected,
        "version_actual": value.version_actual,
        "warnings": list(value.warnings),
        "confidence": value.confidence,
    }


def _pattern_to_plain(value: Pattern) -> dict[str, Any]:
    return {
        "pattern_id": value.pattern_id,
        "pattern_type": value.pattern_type.value,
        "description": sanitize_text(value.description, limit=512),
        "support_count": value.support_count,
        "sample_size": value.sample_size,
        "counterexample_count": value.counterexample_count,
        "supporting_experience_ids": list(value.supporting_experience_ids),
        "counterexample_experience_ids": list(value.counterexample_experience_ids),
        "source_references": [_runtime_prov_to_plain(p) for p in value.source_references],
        "provenance": _prov_record_to_plain(value.provenance),
        "evidence_strength": value.evidence_strength.value,
        "status": value.status.value,
        "causal_claim": value.causal_claim,
        "warnings": list(value.warnings),
    }


def _finding_to_plain(value: Finding) -> dict[str, Any]:
    return {
        "finding_id": value.finding_id,
        "investigation_id": value.investigation_id,
        "statement": sanitize_text(value.statement, limit=512),
        "supporting_evidence_ids": list(value.supporting_evidence_ids),
        "counterevidence_ids": list(value.counterevidence_ids),
        "reason_codes": list(value.reason_codes),
        "source_references": [_runtime_prov_to_plain(p) for p in value.source_references],
        "provenance": _prov_record_to_plain(value.provenance),
        "evidence_strength": value.evidence_strength.value,
        "status": value.status.value,
        "limitations": list(value.limitations),
        "warnings": list(value.warnings),
    }


def _hypothesis_to_plain(value: Hypothesis) -> dict[str, Any]:
    return {
        "hypothesis_id": value.hypothesis_id,
        "statement": sanitize_text(value.statement, limit=512),
        "derived_from_finding_ids": list(value.derived_from_finding_ids),
        "supporting_pattern_ids": list(value.supporting_pattern_ids),
        "expected_effect": sanitize_text(value.expected_effect, limit=512),
        "validation_criteria": [list(v) for v in value.validation_criteria],
        "required_evidence": list(value.required_evidence),
        "status": value.status.value,
        "provenance": _prov_record_to_plain(value.provenance),
        "limitations": list(value.limitations),
        "warnings": list(value.warnings),
        "strategy_mutation": value.strategy_mutation,
    }


def _validation_to_plain(value: Validation) -> dict[str, Any]:
    return {
        "validation_id": value.validation_id,
        "hypothesis_id": value.hypothesis_id,
        "method": value.method.value,
        "evidence": _evidence_to_plain(value.evidence),
        "acceptance_criteria": [_crit_to_plain(c) for c in value.acceptance_criteria],
        "metrics": dict(value.metrics),
        "sample_size": value.sample_size,
        "support_count": value.support_count,
        "counterexample_count": value.counterexample_count,
        "result": value.result.value,
        "provenance": _prov_record_to_plain(value.provenance),
        "limitations": list(value.limitations),
        "warnings": list(value.warnings),
    }


def _review_to_plain(value: HumanReview) -> dict[str, Any]:
    return {
        "review_id": value.review_id,
        "hypothesis_id": value.hypothesis_id,
        "decision": value.decision.value,
        "reviewer": value.reviewer,
        "reviewed_at": value.reviewed_at,
        "notes": sanitize_text(value.notes, limit=512),
        "provenance": _prov_record_to_plain(value.provenance),
    }


def _knowledge_to_plain(value: ValidatedKnowledge) -> dict[str, Any]:
    return {
        "knowledge_id": value.knowledge_id,
        "statement": sanitize_text(value.statement, limit=512),
        "origin_hypothesis_id": value.origin_hypothesis_id,
        "validation_references": list(value.validation_references),
        "human_review_reference": value.human_review_reference,
        "provenance": _prov_record_to_plain(value.provenance),
        "version": value.version,
        "created_at": value.created_at,
        "limitations": list(value.limitations),
        "scope": value.scope,
        "status": value.status.value,
        "drift": _drift_to_plain(value.drift) if value.drift is not None else None,
        "warnings": list(value.warnings),
    }


# --------------------------------------------------------------------------- #
# Pattern derived-value guard (singleton must never become a repeated pattern)
# --------------------------------------------------------------------------- #


def _derive_pattern_status(support_count: int, sample_size: int) -> PatternStatus:
    if sample_size <= 1:
        return PatternStatus.SINGLETON
    if sample_size >= 2 and support_count >= 2:
        return PatternStatus.REPEATED
    return PatternStatus.SINGLETON


def _normalize_pattern(pattern: Pattern) -> Pattern:
    """Recompute derived status/strength and enforce the singleton guard.

    Never trusts corrupted persisted derived values; a singleton can never be
    reloaded as a repeated pattern and EvidenceStrength is always a categorical
    label (never statistical / causal certainty).
    """
    strength = resolve_evidence_strength(
        pattern.support_count, pattern.sample_size, pattern.counterexample_count
    )
    status = _derive_pattern_status(pattern.support_count, pattern.sample_size)
    warnings = list(pattern.warnings)
    if pattern.sample_size <= 1 and pattern.support_count >= 1:
        if "SINGLE_EVENT_NOT_REPEATED_PATTERN" not in warnings:
            warnings.append("SINGLE_EVENT_NOT_REPEATED_PATTERN")
    if pattern.evidence_strength is not strength or pattern.status is not status:
        if "DERIVED_VALUE_RECOMPUTED" not in warnings:
            warnings.append("DERIVED_VALUE_RECOMPUTED")
    return replace(
        pattern,
        evidence_strength=strength,
        status=status,
        warnings=tuple(warnings)[:MAX_D8_WARNINGS],
    )


def _load_json(text: str) -> dict[str, Any]:
    value = json.loads(text)
    if not isinstance(value, dict):
        _raise(KnowledgeStoreErrorCode.CORRUPT_RECORD, "payload is not a mapping")
    return value


def _load_json_db(db, table: str, pk_col: str, pk_value: str) -> dict[str, Any]:
    row = db.execute(
        f"SELECT payload FROM {table} WHERE {pk_col}=?", (pk_value,)
    ).fetchone()
    if row is None:
        _raise(KnowledgeStoreErrorCode.NOT_FOUND, f"{table} record not found")
    return _load_json(row[0])


class _store_transaction:
    """Context manager that begins a SQLite transaction and commits/rolls back."""

    def __init__(self, connect, lock):
        self._connect = connect
        self._lock = lock
        self._db = None

    def __enter__(self):
        self._lock.acquire()
        self._db = self._connect()
        self._db.execute("BEGIN IMMEDIATE")
        return self._db

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._db.execute("COMMIT")
            else:
                self._db.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        finally:
            self._db.close()
            self._lock.release()
        return False


__all__ = [
    "DEFAULT_KNOWLEDGE_STORE_PATH",
    "KnowledgeEvolutionStore",
    "KnowledgeStoreError",
    "KnowledgeStoreErrorCode",
    "OPERATOR_SCOPE_POLICY_UNRESOLVED",
    "SCHEMA_VERSION",
    "review_subject_fingerprint",
    "sanitize_text",
]
