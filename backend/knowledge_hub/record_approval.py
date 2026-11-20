"""Record-level approval, secret disposition, redaction, and manual review.

The existing BC-11D approval binds a source-file selection to one isolated
store. That contract is necessary but not sufficient: one source file may hold
several content records. This module adds an explicit per-content-record
decision layer. A source-file approval never bypasses these decisions, and a
record is import-eligible only when its decisions, secret findings, redaction
state, and manual-review state all agree.

No secret value is stored or returned. A finding is represented by its
identifier, category, severity, and a decision record only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from .security import secret_bytes


AUDIT_SCHEMA_VERSION = "tradingai-record-approval-audit/v1"
RECORD_DECISION_SCHEMA_VERSION = "tradingai-record-approval-decision/v1"
OPERATOR_DECISION_SCHEMA_VERSION = "tradingai-operator-record-decisions/v1"

FINDING_REDACTED = "REDACTED"
FINDING_FALSE_POSITIVE_REVIEWED = "FALSE_POSITIVE_REVIEWED"
FINDING_EXCLUDED = "EXCLUDED"
FINDING_PENDING = "PENDING_OPERATOR_REVIEW"
RESOLVING_FINDING_DISPOSITIONS = frozenset(
    {FINDING_REDACTED, FINDING_FALSE_POSITIVE_REVIEWED, FINDING_EXCLUDED}
)
FINDING_DISPOSITIONS = frozenset(
    {
        FINDING_REDACTED,
        FINDING_FALSE_POSITIVE_REVIEWED,
        FINDING_EXCLUDED,
        FINDING_PENDING,
    }
)

RECORD_APPROVED = "APPROVED"
RECORD_REJECTED = "REJECTED"
RECORD_EXCLUDED = "EXCLUDED"
RECORD_NEEDS_REDACTION = "NEEDS_REDACTION"
RECORD_PENDING = "PENDING"
RECORD_STATES = frozenset(
    {RECORD_APPROVED, RECORD_REJECTED, RECORD_EXCLUDED, RECORD_NEEDS_REDACTION, RECORD_PENDING}
)

MANUAL_PENDING = "PENDING"
MANUAL_APPROVED = "APPROVED"
MANUAL_REJECTED = "REJECTED"
MANUAL_NEEDS_REDACTION = "NEEDS_REDACTION"
MANUAL_EXCLUDED = "EXCLUDED"
MANUAL_NOT_REQUIRED = "NOT_REQUIRED"
MANUAL_STATES = frozenset(
    {
        MANUAL_PENDING,
        MANUAL_APPROVED,
        MANUAL_REJECTED,
        MANUAL_NEEDS_REDACTION,
        MANUAL_EXCLUDED,
        MANUAL_NOT_REQUIRED,
    }
)

_REDACTION_PATTERNS = (
    (re.compile(r"(?i)\bapi[_-]?key\s*[:=]\s*\S+"), "API_KEY [REDACTED:API_KEY]"),
    (
        re.compile(r"(?i)\b(?:secret|password|passwd)\s*[:=]\s*\S+"),
        "CREDENTIAL [REDACTED:CREDENTIAL]",
    ),
    (re.compile(r"(?i)\btoken\s*[:=]\s*\S+"), "TOKEN [REDACTED:TOKEN]"),
    (
        re.compile(r"(?i)\bauthorization\s*:\s*bearer\s+\S+"),
        "AUTHORIZATION [REDACTED:BEARER]",
    ),
    (re.compile(r"(?i)\bset-cookie\s*:.*$", re.MULTILINE), "SET_COOKIE [REDACTED:COOKIE]"),
    (
        re.compile(
            r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----.*?"
            r"-----END (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED:PRIVATE_KEY]",
    ),
)


class ApprovalError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class OperatorAuthorization:
    authorization_id: str
    authority: str
    issued_at: str
    authorized: bool = True
    scope: frozenset[str] | None = None

    def covers(self, record_id: str | None) -> bool:
        if self.scope is None or record_id is None:
            return True
        return record_id in self.scope


@dataclass(frozen=True)
class SecretFinding:
    finding_id: str
    record_id: str
    category: str
    severity: str = "UNKNOWN"
    redaction_required: bool = True
    manual_review_required: bool = False
    source_file: str | None = None
    provenance: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "record_id": self.record_id,
            "category": self.category,
            "severity": self.severity,
            "redaction_required": self.redaction_required,
            "manual_review_required": self.manual_review_required,
            "source_file": self.source_file,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class FindingDisposition:
    finding_id: str
    record_id: str
    category: str
    disposition: str
    decision_authority: str
    decided_at: str
    provenance: Mapping[str, str] = field(default_factory=dict)
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "record_id": self.record_id,
            "category": self.category,
            "disposition": self.disposition,
            "decision_authority": self.decision_authority,
            "decided_at": self.decided_at,
            "provenance": dict(self.provenance),
            "note": self.note,
        }


@dataclass(frozen=True)
class ManualReviewDecision:
    record_id: str
    state: str
    reason: str
    decision_authority: str
    decided_at: str
    source_provenance: Mapping[str, str] = field(default_factory=dict)
    history: tuple[Mapping[str, str], ...] = ()
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "state": self.state,
            "reason": self.reason,
            "decision_authority": self.decision_authority,
            "decided_at": self.decided_at,
            "source_provenance": dict(self.source_provenance),
            "history": [dict(item) for item in self.history],
            "note": self.note,
        }


@dataclass(frozen=True)
class RedactionCandidate:
    record_id: str
    original_content_hash: str
    sanitized_content: str
    sanitized_content_hash: str
    finding_ids: tuple[str, ...]
    redacted_count: int
    redaction_labels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "original_content_hash": self.original_content_hash,
            "sanitized_content_hash": self.sanitized_content_hash,
            "finding_ids": list(self.finding_ids),
            "redacted_count": self.redacted_count,
            "redaction_labels": list(self.redaction_labels),
        }


@dataclass(frozen=True)
class RedactionApproval:
    record_id: str
    original_content_hash: str
    sanitized_content_hash: str
    finding_ids: tuple[str, ...]
    method: str
    decision_authority: str
    decided_at: str
    provenance: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "original_content_hash": self.original_content_hash,
            "sanitized_content_hash": self.sanitized_content_hash,
            "finding_ids": list(self.finding_ids),
            "method": self.method,
            "decision_authority": self.decision_authority,
            "decided_at": self.decided_at,
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class RecordDecision:
    record_id: str
    content_hash: str
    state: str
    decision_authority: str
    decided_at: str
    source_file: str | None = None
    workstream: str | None = None
    finding_ids: tuple[str, ...] = ()
    manual_review_state: str = MANUAL_NOT_REQUIRED
    redaction_required: bool = False
    sanitized_content_hash: str | None = None
    reason: str = ""
    provenance: Mapping[str, str] = field(default_factory=dict)
    history: tuple[Mapping[str, Any], ...] = ()

    def identity(self) -> tuple[Any, ...]:
        return (
            self.record_id,
            self.content_hash,
            self.state,
            self.source_file,
            self.workstream,
            tuple(sorted(self.finding_ids)),
            self.manual_review_state,
            self.redaction_required,
            self.sanitized_content_hash,
            self.reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RECORD_DECISION_SCHEMA_VERSION,
            "record_id": self.record_id,
            "content_hash": self.content_hash,
            "state": self.state,
            "decision_authority": self.decision_authority,
            "decided_at": self.decided_at,
            "source_file": self.source_file,
            "workstream": self.workstream,
            "finding_ids": list(self.finding_ids),
            "manual_review_state": self.manual_review_state,
            "redaction_required": self.redaction_required,
            "sanitized_content_hash": self.sanitized_content_hash,
            "reason": self.reason,
            "provenance": dict(self.provenance),
            "history": [dict(item) for item in self.history],
        }


@dataclass(frozen=True)
class EligibilityResult:
    record_id: str | None
    content_hash: str | None
    eligible: bool
    code: str
    reasons: tuple[str, ...]
    source_file: str | None = None
    workstream: str | None = None
    redaction_required: bool = False
    sanitized_content_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "content_hash": self.content_hash,
            "eligible": self.eligible,
            "code": self.code,
            "reasons": list(self.reasons),
            "source_file": self.source_file,
            "workstream": self.workstream,
            "redaction_required": self.redaction_required,
            "sanitized_content_hash": self.sanitized_content_hash,
        }


def _require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalError(code)
    return value.strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact_content(text: str) -> RedactionCandidate:
    """Return a sanitized candidate. This does not approve anything."""

    if not isinstance(text, str):
        raise ApprovalError("CONTENT_INVALID")
    sanitized = text
    labels: list[str] = []
    count = 0
    for pattern, replacement in _REDACTION_PATTERNS:
        sanitized, replaced = pattern.subn(replacement, sanitized)
        count += replaced
        if replaced:
            labels.append(replacement)
    if secret_bytes(sanitized.encode("utf-8")):
        raise ApprovalError("REDACTION_INCOMPLETE")
    return RedactionCandidate(
        record_id="",
        original_content_hash=_sha256(text),
        sanitized_content=sanitized,
        sanitized_content_hash=_sha256(sanitized),
        finding_ids=(),
        redacted_count=count,
        redaction_labels=tuple(labels),
    )


def prepare_redaction(
    record_id: str,
    text: str,
    finding_ids: Sequence[str],
) -> RedactionCandidate:
    candidate = redact_content(text)
    return RedactionCandidate(
        record_id=_require_text(record_id, "RECORD_ID_REQUIRED"),
        original_content_hash=candidate.original_content_hash,
        sanitized_content=candidate.sanitized_content,
        sanitized_content_hash=candidate.sanitized_content_hash,
        finding_ids=tuple(str(item) for item in finding_ids),
        redacted_count=candidate.redacted_count,
        redaction_labels=candidate.redaction_labels,
    )


class ApprovalLedger:
    """Explicit decision ledger. Nothing resolves without authorization."""

    def __init__(self, *, authorized_authorities: frozenset[str] = frozenset({"OPERATOR"})) -> None:
        self._authorized_authorities = frozenset(authorized_authorities)
        self._findings: dict[str, SecretFinding] = {}
        self._dispositions: dict[str, FindingDisposition] = {}
        self._manual: dict[str, ManualReviewDecision] = {}
        self._redactions: dict[str, RedactionApproval] = {}
        self._records: dict[str, RecordDecision] = {}
        self._by_hash: dict[str, str] = {}
        self._audit: list[dict[str, Any]] = []
        self._audit_seen: set[str] = set()

    def _require_authorization(
        self,
        authorization: OperatorAuthorization | None,
        *,
        record_id: str | None,
        code: str = "AUTHORIZATION_REQUIRED",
    ) -> OperatorAuthorization:
        if authorization is None or authorization.authorized is not True:
            raise ApprovalError(code)
        authority = _require_text(authorization.authority, "AUTHORITY_REQUIRED")
        _require_text(authorization.authorization_id, "AUTHORIZATION_ID_REQUIRED")
        _require_text(authorization.issued_at, "AUTHORIZATION_TIMESTAMP_REQUIRED")
        if authority not in self._authorized_authorities:
            raise ApprovalError("AUTHORITY_NOT_AUTHORIZED")
        if not authorization.covers(record_id):
            raise ApprovalError("AUTHORIZATION_SCOPE_DENIED")
        return authorization

    def _append_audit(self, event: Mapping[str, Any]) -> None:
        payload = dict(event)
        payload.setdefault("schema_version", AUDIT_SCHEMA_VERSION)
        payload["sequence"] = len(self._audit) + 1
        fingerprint = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if fingerprint in self._audit_seen:
            return
        self._audit_seen.add(fingerprint)
        self._audit.append(payload)

    def register_finding(self, finding: SecretFinding) -> SecretFinding:
        for key in ("finding_id", "record_id", "category"):
            if not getattr(finding, key):
                raise ApprovalError("FINDING_INVALID")
        existing = self._findings.get(finding.finding_id)
        if existing is not None:
            if existing != finding:
                raise ApprovalError("CONFLICTING_FINDING")
            return existing
        self._findings[finding.finding_id] = finding
        self._append_audit(
            {
                "event": "FINDING_REGISTERED",
                "record_id": finding.record_id,
                "finding_id": finding.finding_id,
                "category": finding.category,
                "severity": finding.severity,
                "provenance": dict(finding.provenance),
            }
        )
        return finding

    def findings_for(self, record_id: str) -> tuple[SecretFinding, ...]:
        return tuple(
            finding for finding in self._findings.values() if finding.record_id == record_id
        )

    def dispose_finding(
        self,
        disposition: FindingDisposition,
        authorization: OperatorAuthorization | None = None,
    ) -> FindingDisposition:
        if disposition.disposition not in FINDING_DISPOSITIONS:
            raise ApprovalError("FINDING_DISPOSITION_INVALID")
        finding = self._findings.get(disposition.finding_id)
        if finding is None:
            raise ApprovalError("FINDING_NOT_FOUND")
        if finding.record_id != disposition.record_id or finding.category != disposition.category:
            raise ApprovalError("FINDING_DISPOSITION_MISMATCH")
        resolved = disposition.disposition in RESOLVING_FINDING_DISPOSITIONS
        if resolved:
            self._require_authorization(authorization, record_id=disposition.record_id)
            authority = authorization.authority
        else:
            authority = disposition.decision_authority or "PENDING_OPERATOR_REVIEW"
        _require_text(disposition.decided_at, "DECISION_TIMESTAMP_REQUIRED")
        existing = self._dispositions.get(disposition.finding_id)
        if existing is not None:
            if existing.to_dict() == disposition.to_dict():
                return existing
            raise ApprovalError("CONFLICTING_FINDING_DISPOSITION")
        self._dispositions[disposition.finding_id] = disposition
        self._append_audit(
            {
                "event": "FINDING_DISPOSITION",
                "record_id": disposition.record_id,
                "finding_id": disposition.finding_id,
                "category": disposition.category,
                "disposition": disposition.disposition,
                "resolved": resolved,
                "decision_authority": authority,
                "decided_at": disposition.decided_at,
                "provenance": dict(disposition.provenance),
            }
        )
        return disposition

    def record_manual_review(
        self,
        decision: ManualReviewDecision,
        authorization: OperatorAuthorization | None = None,
    ) -> ManualReviewDecision:
        if decision.state not in MANUAL_STATES:
            raise ApprovalError("MANUAL_REVIEW_STATE_INVALID")
        _require_text(decision.record_id, "RECORD_ID_REQUIRED")
        _require_text(decision.reason, "MANUAL_REVIEW_REASON_REQUIRED")
        _require_text(decision.decided_at, "DECISION_TIMESTAMP_REQUIRED")
        if decision.state not in {MANUAL_PENDING, MANUAL_NOT_REQUIRED}:
            self._require_authorization(authorization, record_id=decision.record_id)
            authority = authorization.authority
        else:
            authority = decision.decision_authority or "PENDING_OPERATOR_REVIEW"
        existing = self._manual.get(decision.record_id)
        if existing is not None:
            if existing.state == decision.state and existing.reason == decision.reason:
                return existing
            history = existing.history + (existing.to_dict(),)
            decision = ManualReviewDecision(
                record_id=decision.record_id,
                state=decision.state,
                reason=decision.reason,
                decision_authority=authority,
                decided_at=decision.decided_at,
                source_provenance=decision.source_provenance,
                history=history,
                note=decision.note,
            )
        self._manual[decision.record_id] = decision
        self._append_audit(
            {
                "event": "MANUAL_REVIEW",
                "record_id": decision.record_id,
                "state": decision.state,
                "reason": decision.reason,
                "decision_authority": authority,
                "decided_at": decision.decided_at,
                "source_provenance": dict(decision.source_provenance),
            }
        )
        return decision

    def record_redaction(
        self,
        approval: RedactionApproval,
        authorization: OperatorAuthorization | None = None,
    ) -> RedactionApproval:
        self._require_authorization(authorization, record_id=approval.record_id)
        _require_text(approval.original_content_hash, "CONTENT_HASH_REQUIRED")
        _require_text(approval.sanitized_content_hash, "SANITIZED_HASH_REQUIRED")
        _require_text(approval.method, "REDACTION_METHOD_REQUIRED")
        _require_text(approval.decided_at, "DECISION_TIMESTAMP_REQUIRED")
        if not approval.finding_ids:
            raise ApprovalError("REDACTION_FINDING_REQUIRED")
        for finding_id in approval.finding_ids:
            finding = self._findings.get(finding_id)
            if finding is None:
                raise ApprovalError("FINDING_NOT_FOUND")
            disposition = self._dispositions.get(finding_id)
            if disposition is None or disposition.disposition != FINDING_REDACTED:
                raise ApprovalError("REDACTION_FINDING_NOT_RESOLVED")
        existing = self._redactions.get(approval.record_id)
        if existing is not None:
            if existing.to_dict() == approval.to_dict():
                return existing
            raise ApprovalError("CONFLICTING_REDACTION_APPROVAL")
        self._redactions[approval.record_id] = approval
        self._append_audit(
            {
                "event": "REDACTION_APPROVED",
                "record_id": approval.record_id,
                "original_content_hash": approval.original_content_hash,
                "sanitized_content_hash": approval.sanitized_content_hash,
                "finding_ids": list(approval.finding_ids),
                "method": approval.method,
                "decision_authority": authorization.authority,
                "decided_at": approval.decided_at,
                "provenance": dict(approval.provenance),
            }
        )
        return approval

    def decide_record(
        self,
        decision: RecordDecision,
        authorization: OperatorAuthorization | None = None,
    ) -> RecordDecision:
        self._require_authorization(authorization, record_id=decision.record_id)
        if decision.state not in RECORD_STATES:
            raise ApprovalError("RECORD_STATE_INVALID")
        _require_text(decision.record_id, "RECORD_ID_REQUIRED")
        _require_text(decision.content_hash, "CONTENT_HASH_REQUIRED")
        _require_text(decision.decided_at, "DECISION_TIMESTAMP_REQUIRED")
        if decision.state == RECORD_APPROVED:
            self._validate_approval_requirements(decision)
        existing = self._records.get(decision.record_id)
        if existing is not None:
            if existing.identity() == decision.identity():
                return existing
            if existing.content_hash != decision.content_hash:
                raise ApprovalError("RECORD_CONTENT_HASH_CHANGED")
            decision = RecordDecision(
                record_id=decision.record_id,
                content_hash=decision.content_hash,
                state=decision.state,
                decision_authority=authorization.authority,
                decided_at=decision.decided_at,
                source_file=decision.source_file,
                workstream=decision.workstream,
                finding_ids=decision.finding_ids,
                manual_review_state=decision.manual_review_state,
                redaction_required=decision.redaction_required,
                sanitized_content_hash=decision.sanitized_content_hash,
                reason=decision.reason,
                provenance=decision.provenance,
                history=existing.history + (existing.to_dict(),),
            )
        else:
            decision = RecordDecision(
                record_id=decision.record_id,
                content_hash=decision.content_hash,
                state=decision.state,
                decision_authority=authorization.authority,
                decided_at=decision.decided_at,
                source_file=decision.source_file,
                workstream=decision.workstream,
                finding_ids=decision.finding_ids,
                manual_review_state=decision.manual_review_state,
                redaction_required=decision.redaction_required,
                sanitized_content_hash=decision.sanitized_content_hash,
                reason=decision.reason,
                provenance=decision.provenance,
                history=decision.history,
            )
        self._records[decision.record_id] = decision
        self._by_hash[decision.content_hash] = decision.record_id
        self._append_audit(
            {
                "event": "RECORD_DECISION",
                "record_id": decision.record_id,
                "content_hash": decision.content_hash,
                "state": decision.state,
                "decision_authority": authorization.authority,
                "decided_at": decision.decided_at,
                "source_file": decision.source_file,
                "workstream": decision.workstream,
                "manual_review_state": decision.manual_review_state,
                "redaction_required": decision.redaction_required,
                "reason": decision.reason,
                "provenance": dict(decision.provenance),
            }
        )
        return decision

    def _effective_manual_state(self, decision: RecordDecision) -> str:
        manual = self._manual.get(decision.record_id)
        return manual.state if manual is not None else decision.manual_review_state

    def _validate_approval_requirements(self, decision: RecordDecision) -> None:
        findings = self.findings_for(decision.record_id)
        unresolved: list[str] = []
        excluded: list[str] = []
        redaction_required = bool(decision.redaction_required)
        manual_review_required = decision.manual_review_state in {
            MANUAL_PENDING,
            MANUAL_NEEDS_REDACTION,
        }
        for finding in findings:
            redaction_required = redaction_required or finding.redaction_required
            manual_review_required = manual_review_required or finding.manual_review_required
            disposition = self._dispositions.get(finding.finding_id)
            if disposition is None or disposition.disposition == FINDING_PENDING:
                unresolved.append(finding.finding_id)
            elif disposition.disposition == FINDING_EXCLUDED:
                excluded.append(finding.finding_id)
        if unresolved:
            raise ApprovalError("UNRESOLVED_SECRET_FINDING")
        if excluded:
            raise ApprovalError("FINDING_EXCLUDED")
        if redaction_required:
            redaction = self._redactions.get(decision.record_id)
            if redaction is None:
                raise ApprovalError("REDACTION_REQUIRED")
            if (
                decision.sanitized_content_hash
                and redaction.sanitized_content_hash != decision.sanitized_content_hash
            ):
                raise ApprovalError("REDACTION_HASH_MISMATCH")
        if manual_review_required:
            effective_manual = self._effective_manual_state(decision)
            if effective_manual != MANUAL_APPROVED:
                raise ApprovalError("MANUAL_REVIEW_PENDING")

    def decision_for(
        self,
        *,
        content_hash: str | None = None,
        record_id: str | None = None,
    ) -> RecordDecision | None:
        if record_id is not None and record_id in self._records:
            return self._records[record_id]
        if content_hash is not None:
            key = self._by_hash.get(content_hash)
            if key is not None:
                return self._records.get(key)
        return None

    def evaluate(
        self,
        *,
        content_hash: str | None = None,
        record_id: str | None = None,
        source_file: str | None = None,
        require_sanitized: bool = False,
    ) -> EligibilityResult:
        decision = self.decision_for(content_hash=content_hash, record_id=record_id)
        if decision is None:
            return EligibilityResult(
                record_id=record_id,
                content_hash=content_hash,
                eligible=False,
                code="RECORD_NOT_APPROVED",
                reasons=("RECORD_NOT_APPROVED",),
            )
        reasons: list[str] = []
        if content_hash is not None and decision.content_hash != content_hash:
            reasons.append("CONTENT_HASH_MISMATCH")
        if decision.source_file and source_file and decision.source_file != source_file:
            reasons.append("SOURCE_FILE_MISMATCH")
        if decision.state == RECORD_REJECTED:
            reasons.append("RECORD_REJECTED")
        elif decision.state == RECORD_EXCLUDED:
            reasons.append("RECORD_EXCLUDED")
        elif decision.state == RECORD_NEEDS_REDACTION:
            reasons.append("RECORD_NEEDS_REDACTION")
        elif decision.state != RECORD_APPROVED:
            reasons.append("RECORD_NOT_APPROVED")
        redaction_required = bool(decision.redaction_required) or require_sanitized
        for finding in self.findings_for(decision.record_id):
            redaction_required = redaction_required or finding.redaction_required
            disposition = self._dispositions.get(finding.finding_id)
            if disposition is None or disposition.disposition == FINDING_PENDING:
                reasons.append("UNRESOLVED_SECRET_FINDING")
            elif disposition.disposition == FINDING_EXCLUDED:
                reasons.append("FINDING_EXCLUDED")
        sanitized_hash = None
        if redaction_required:
            redaction = self._redactions.get(decision.record_id)
            if redaction is None:
                reasons.append("REDACTION_REQUIRED")
            else:
                sanitized_hash = redaction.sanitized_content_hash
                if (
                    decision.sanitized_content_hash
                    and decision.sanitized_content_hash != redaction.sanitized_content_hash
                ):
                    reasons.append("REDACTION_HASH_MISMATCH")
        effective_manual = self._effective_manual_state(decision)
        if effective_manual == MANUAL_PENDING:
            reasons.append("MANUAL_REVIEW_PENDING")
        elif effective_manual == MANUAL_NEEDS_REDACTION:
            reasons.append("MANUAL_REVIEW_NEEDS_REDACTION")
        elif effective_manual == MANUAL_REJECTED:
            reasons.append("MANUAL_REVIEW_REJECTED")
        elif effective_manual == MANUAL_EXCLUDED:
            reasons.append("MANUAL_REVIEW_EXCLUDED")
        if reasons:
            return EligibilityResult(
                record_id=decision.record_id,
                content_hash=decision.content_hash,
                eligible=False,
                code=reasons[0],
                reasons=tuple(dict.fromkeys(reasons)),
                source_file=decision.source_file,
                workstream=decision.workstream,
                redaction_required=redaction_required,
                sanitized_content_hash=sanitized_hash,
            )
        return EligibilityResult(
            record_id=decision.record_id,
            content_hash=decision.content_hash,
            eligible=True,
            code="ELIGIBLE",
            reasons=(),
            source_file=decision.source_file,
            workstream=decision.workstream,
            redaction_required=redaction_required,
            sanitized_content_hash=sanitized_hash,
        )

    def apply_operator_decisions(
        self,
        proposed_decisions: Mapping[str, Any],
        operator_decisions: Mapping[str, Any] | None,
        authorization: OperatorAuthorization | None,
    ) -> dict[str, Any]:
        auth = self._require_authorization(authorization, record_id=None)
        if not isinstance(proposed_decisions, Mapping):
            raise ApprovalError("PROPOSED_DECISION_INVALID")
        if not proposed_decisions.get("entries"):
            raise ApprovalError("PROPOSED_DECISION_INVALID")
        if not operator_decisions:
            return {
                "status": "NO_AUTHORITATIVE_OPERATOR_DECISION",
                "applied": 0,
                "skipped": 0,
                "records": [],
                "import_ready": False,
            }
        if operator_decisions.get("schema_version") != OPERATOR_DECISION_SCHEMA_VERSION:
            raise ApprovalError("OPERATOR_DECISION_SCHEMA_MISMATCH")
        if operator_decisions.get("authoritative") is not True:
            raise ApprovalError("OPERATOR_DECISION_NOT_AUTHORITATIVE")
        if operator_decisions.get("authorization_id") != auth.authorization_id:
            raise ApprovalError("OPERATOR_AUTHORIZATION_MISMATCH")
        raw_records = operator_decisions.get("decisions")
        if not isinstance(raw_records, list) or not raw_records:
            raise ApprovalError("OPERATOR_DECISION_EMPTY")
        proposed: dict[str, Mapping[str, Any]] = {}
        for entry in proposed_decisions["entries"]:
            if not isinstance(entry, Mapping):
                continue
            if entry.get("contentHash"):
                proposed[f"hash:{entry['contentHash']}"] = entry
            if entry.get("recordId"):
                proposed[f"id:{entry['recordId']}"] = entry
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        applied = skipped = 0
        for raw in raw_records:
            if not isinstance(raw, Mapping):
                raise ApprovalError("OPERATOR_DECISION_INVALID")
            content_hash = raw.get("contentHash") or raw.get("content_hash")
            record_id = raw.get("recordId") or raw.get("record_id")
            state_code = raw.get("decision") or raw.get("state")
            if not content_hash and not record_id:
                raise ApprovalError("OPERATOR_DECISION_RECORD_REQUIRED")
            entry = None
            if content_hash:
                entry = proposed.get(f"hash:{content_hash}")
            if entry is None and record_id:
                entry = proposed.get(f"id:{record_id}")
            if entry is None:
                raise ApprovalError("PROPOSED_RECORD_NOT_FOUND")
            proposed_hash = entry.get("contentHash")
            proposed_id = entry.get("recordId")
            if content_hash and proposed_hash and content_hash != proposed_hash:
                raise ApprovalError("PROPOSED_CONTENT_HASH_MISMATCH")
            if record_id and proposed_id and record_id != proposed_id:
                raise ApprovalError("PROPOSED_RECORD_ID_MISMATCH")
            final_id = proposed_id or record_id
            final_hash = proposed_hash or content_hash
            if final_id in seen:
                raise ApprovalError("DUPLICATE_OPERATOR_DECISION")
            seen.add(final_id)
            state = _operator_state(state_code)
            source_paths = entry.get("source_paths") or entry.get("sourcePaths") or []
            source_file = str(source_paths[0]) if source_paths else None
            workstream = entry.get("sourceWorkstream") or entry.get("workstream")
            findings = self.findings_for(final_id)
            finding_ids = tuple(finding.finding_id for finding in findings)
            decision = RecordDecision(
                record_id=final_id,
                content_hash=final_hash,
                state=state,
                decision_authority=auth.authority,
                decided_at=auth.issued_at,
                source_file=source_file,
                workstream=workstream,
                finding_ids=finding_ids,
                manual_review_state=(
                    MANUAL_PENDING if entry.get("manualReviewRequired") else MANUAL_NOT_REQUIRED
                ),
                redaction_required=bool(entry.get("redactionRequired")),
                reason=str(raw.get("reason") or "EXPLICIT_OPERATOR_DECISION"),
                provenance={
                    "proposed_task_id": str(proposed_decisions.get("task_id", "")),
                    "authorization_id": auth.authorization_id,
                    "source": "OPERATOR_DECISION_APPLICATION",
                },
            )
            existing = self._records.get(final_id)
            applied_decision = self.decide_record(decision, auth)
            if existing is not None and existing.identity() == applied_decision.identity():
                skipped += 1
            else:
                applied += 1
            results.append(applied_decision.to_dict())
        return {
            "status": "APPLIED" if applied else "ALREADY_APPLIED",
            "applied": applied,
            "skipped": skipped,
            "records": results,
            "import_ready": False,
        }

    def audit_events(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(event) for event in self._audit)

    def snapshot(self) -> dict[str, Any]:
        return {
            "findings": [finding.to_dict() for finding in self._findings.values()],
            "dispositions": [item.to_dict() for item in self._dispositions.values()],
            "manual_review": [item.to_dict() for item in self._manual.values()],
            "redactions": [item.to_dict() for item in self._redactions.values()],
            "records": [item.to_dict() for item in self._records.values()],
            "audit": [dict(event) for event in self._audit],
        }

    def load_snapshot(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise ApprovalError("LEDGER_SNAPSHOT_INVALID")
        for raw in payload.get("findings", []):
            self.register_finding(
                SecretFinding(
                    finding_id=str(raw["finding_id"]),
                    record_id=str(raw["record_id"]),
                    category=str(raw["category"]),
                    severity=str(raw.get("severity", "UNKNOWN")),
                    redaction_required=bool(raw.get("redaction_required", True)),
                    manual_review_required=bool(raw.get("manual_review_required", False)),
                    source_file=raw.get("source_file"),
                    provenance=dict(raw.get("provenance") or {}),
                )
            )
        for raw in payload.get("dispositions", []):
            disposition = FindingDisposition(
                finding_id=str(raw["finding_id"]),
                record_id=str(raw["record_id"]),
                category=str(raw["category"]),
                disposition=str(raw["disposition"]),
                decision_authority=str(raw.get("decision_authority", "")),
                decided_at=str(raw.get("decided_at", "")),
                provenance=dict(raw.get("provenance") or {}),
                note=raw.get("note"),
            )
            if disposition.disposition not in FINDING_DISPOSITIONS:
                raise ApprovalError("FINDING_DISPOSITION_INVALID")
            self._dispositions[disposition.finding_id] = disposition
        for raw in payload.get("manual_review", []):
            manual = ManualReviewDecision(
                record_id=str(raw["record_id"]),
                state=str(raw["state"]),
                reason=str(raw.get("reason", "")),
                decision_authority=str(raw.get("decision_authority", "")),
                decided_at=str(raw.get("decided_at", "")),
                source_provenance=dict(raw.get("source_provenance") or {}),
                history=tuple(raw.get("history") or ()),
                note=raw.get("note"),
            )
            if manual.state not in MANUAL_STATES:
                raise ApprovalError("MANUAL_REVIEW_STATE_INVALID")
            self._manual[manual.record_id] = manual
        for raw in payload.get("redactions", []):
            self._redactions[str(raw["record_id"])] = RedactionApproval(
                record_id=str(raw["record_id"]),
                original_content_hash=str(raw["original_content_hash"]),
                sanitized_content_hash=str(raw["sanitized_content_hash"]),
                finding_ids=tuple(raw.get("finding_ids") or ()),
                method=str(raw.get("method", "")),
                decision_authority=str(raw.get("decision_authority", "")),
                decided_at=str(raw.get("decided_at", "")),
                provenance=dict(raw.get("provenance") or {}),
            )
        for raw in payload.get("records", []):
            decision = RecordDecision(
                record_id=str(raw["record_id"]),
                content_hash=str(raw["content_hash"]),
                state=str(raw["state"]),
                decision_authority=str(raw.get("decision_authority", "")),
                decided_at=str(raw.get("decided_at", "")),
                source_file=raw.get("source_file"),
                workstream=raw.get("workstream"),
                finding_ids=tuple(raw.get("finding_ids") or ()),
                manual_review_state=str(raw.get("manual_review_state", MANUAL_NOT_REQUIRED)),
                redaction_required=bool(raw.get("redaction_required", False)),
                sanitized_content_hash=raw.get("sanitized_content_hash"),
                reason=str(raw.get("reason", "")),
                provenance=dict(raw.get("provenance") or {}),
                history=tuple(raw.get("history") or ()),
            )
            self._records[decision.record_id] = decision
            self._by_hash[decision.content_hash] = decision.record_id

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        if target.is_symlink():
            raise ApprovalError("LEDGER_SYMLINK_REJECTED")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True), encoding="utf-8")
        return target


def index_manifest_records(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Map content hash to record identity using an existing manifest."""

    if not isinstance(payload, Mapping):
        raise ApprovalError("MANIFEST_INVALID")
    entries = payload.get("records")
    if entries is None:
        entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ApprovalError("MANIFEST_INVALID")
    index: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        content_hash = entry.get("contentHash") or entry.get("content_hash")
        record_id = entry.get("recordId") or entry.get("record_id")
        if not content_hash or not record_id:
            continue
        source_paths = entry.get("source_paths") or entry.get("sourcePaths") or []
        index[str(content_hash)] = {
            "record_id": str(record_id),
            "source_file": str(source_paths[0]) if source_paths else None,
            "workstream": entry.get("sourceWorkstream") or entry.get("workstream"),
        }
    if not index:
        raise ApprovalError("MANIFEST_INVALID")
    return index


def seed_pending_findings(
    ledger: ApprovalLedger,
    findings: Sequence[Mapping[str, Any]],
    record_index: Mapping[str, Mapping[str, Any]],
    *,
    provenance: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Register existing findings as unresolved. This resolves nothing."""

    registered: list[str] = []
    for raw in findings:
        if not isinstance(raw, Mapping):
            raise ApprovalError("FINDING_INVALID")
        content_hash = raw.get("contentHash") or raw.get("content_hash")
        identity = record_index.get(str(content_hash or ""))
        if identity is None:
            raise ApprovalError("FINDING_RECORD_NOT_FOUND")
        category = str(raw.get("secret_type") or raw.get("category") or "UNKNOWN")
        severity = str(raw.get("severity") or "UNKNOWN").upper()
        redaction_required = severity in {"HIGH", "CRITICAL"} or category in {
            "PASSWORD",
            "SESSION_COOKIE",
            "BEARER_TOKEN",
            "PRIVATE_KEY",
            "API_KEY",
        }
        finding = SecretFinding(
            finding_id=str(raw.get("finding_id") or raw.get("findingId")),
            record_id=str(identity["record_id"]),
            category=category,
            severity=severity,
            redaction_required=redaction_required,
            manual_review_required=not redaction_required,
            source_file=identity.get("source_file"),
            provenance=dict(provenance or {}),
        )
        ledger.register_finding(finding)
        ledger.dispose_finding(
            FindingDisposition(
                finding_id=finding.finding_id,
                record_id=finding.record_id,
                category=finding.category,
                disposition=FINDING_PENDING,
                decision_authority="PENDING_OPERATOR_REVIEW",
                decided_at=now_iso(),
                provenance=dict(provenance or {}),
            )
        )
        registered.append(finding.finding_id)
    return tuple(registered)


def seed_pending_manual_reviews(
    ledger: ApprovalLedger,
    queue: Sequence[Mapping[str, Any]],
    record_index: Mapping[str, Mapping[str, Any]],
    *,
    provenance: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Register existing manual-review rows as PENDING. This approves nothing."""

    registered: list[str] = []
    for raw in queue:
        if not isinstance(raw, Mapping):
            raise ApprovalError("MANUAL_REVIEW_INVALID")
        content_hash = raw.get("contentHash") or raw.get("content_hash")
        identity = record_index.get(str(content_hash or ""))
        if identity is None:
            raise ApprovalError("MANUAL_REVIEW_RECORD_NOT_FOUND")
        decision = ManualReviewDecision(
            record_id=str(identity["record_id"]),
            state=MANUAL_PENDING,
            reason=str(
                raw.get("review_reason")
                or raw.get("review_classification")
                or "PENDING_OPERATOR_REVIEW"
            ),
            decision_authority="PENDING_OPERATOR_REVIEW",
            decided_at=now_iso(),
            source_provenance={
                "source_file": str(identity.get("source_file") or ""),
                **dict(provenance or {}),
            },
        )
        ledger.record_manual_review(decision)
        registered.append(decision.record_id)
    return tuple(registered)


def _operator_state(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    mapping = {
        "APPROVE": RECORD_APPROVED,
        "APPROVED": RECORD_APPROVED,
        "REJECT": RECORD_REJECTED,
        "REJECTED": RECORD_REJECTED,
        "EXCLUDE": RECORD_EXCLUDED,
        "EXCLUDED": RECORD_EXCLUDED,
        "NEEDS_REDACTION": RECORD_NEEDS_REDACTION,
        "PENDING": RECORD_PENDING,
    }
    state = mapping.get(normalized)
    if state is None:
        raise ApprovalError("OPERATOR_DECISION_INVALID")
    return state


__all__ = [
    "AUDIT_SCHEMA_VERSION",
    "ApprovalError",
    "ApprovalLedger",
    "EligibilityResult",
    "FINDING_DISPOSITIONS",
    "FINDING_EXCLUDED",
    "FINDING_FALSE_POSITIVE_REVIEWED",
    "FINDING_PENDING",
    "FINDING_REDACTED",
    "FindingDisposition",
    "MANUAL_APPROVED",
    "MANUAL_EXCLUDED",
    "MANUAL_NEEDS_REDACTION",
    "MANUAL_NOT_REQUIRED",
    "MANUAL_PENDING",
    "MANUAL_REJECTED",
    "MANUAL_STATES",
    "ManualReviewDecision",
    "OPERATOR_DECISION_SCHEMA_VERSION",
    "OperatorAuthorization",
    "RECORD_APPROVED",
    "RECORD_DECISION_SCHEMA_VERSION",
    "RECORD_EXCLUDED",
    "RECORD_NEEDS_REDACTION",
    "RECORD_PENDING",
    "RECORD_REJECTED",
    "RECORD_STATES",
    "RecordDecision",
    "RedactionApproval",
    "RedactionCandidate",
    "SecretFinding",
    "index_manifest_records",
    "now_iso",
    "prepare_redaction",
    "redact_content",
    "seed_pending_findings",
    "seed_pending_manual_reviews",
]
