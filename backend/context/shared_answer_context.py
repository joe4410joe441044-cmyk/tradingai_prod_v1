"""Read-only Canonical Context for existing answer generators.

The block is data. It is not a system instruction, a trading control, or a
new public API. This module does not construct a BotManager, import that
module, or call a runtime, exchange, money-management, or supervisor reader.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.context.api_contract import (
    PRODUCTION_API_AVAILABLE,
    PRODUCTION_RUNTIME_CONNECTED,
)
from backend.context.context_views import scrub_context_tree
from backend.context.owner_context_bridge import (
    collection_from_owner_document,
    copied_owner_export,
    existing_owner_from_process,
)

MAX_CONTEXT_BLOCK_CHARS = 12_000
_INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+|previous\s+|prior\s+)*instructions|"
    r"system\s+prompt|you\s+are\s+now|do\s+not\s+follow|"
    r"disregard\s+(all\s+|any\s+|previous\s+)*instructions)"
)
_UNCONNECTED = {
    "realAccount": "UNAVAILABLE",
    "executionAuthority": "UNAVAILABLE",
    "moneyManagementRuntime": "UNAVAILABLE",
    "supervisorRuntime": "UNAVAILABLE",
}


def load_shared_operator_context(
    app: object | None = None,
    question: str | None = None,
    repository: Any = None,
    history_facade: Any = None,
) -> dict[str, Any]:
    """Return a bounded operator attachment. Exceptions become UNAVAILABLE.

    A question selects read-only source, project, decision, and runtime
    evidence. No question means none of those readers run. A failure of one
    reader does not remove the operator view or the other evidence objects.
    """

    generated_at = datetime.now(timezone.utc)
    document = None
    try:
        attachment, document = _operator_attachment(app, generated_at)
    except Exception:
        attachment = _attachment("UNAVAILABLE", "CONTEXT_EXCEPTION", generated_at, None)
    if question is not None:
        attachment["sourceEvidence"] = _source_evidence(question, repository)
        attachment["projectEvidence"] = _project_evidence(question, repository)
        attachment["decisionEvidence"] = _decision_evidence(question, history_facade)
        attachment["runtimeEvidence"] = _runtime_evidence(document)
    return attachment


def render_canonical_context_block(attachment: Mapping[str, Any]) -> str:
    """Render one untrusted read-only block for an Advisor prompt."""

    body = _safe_attachment(attachment)
    retained = {
        key: body.get(key)
        for key in (
            "runtimeEvidence",
            "decisionEvidence",
            "projectEvidence",
            "sourceEvidence",
        )
    }
    text = _bounded_text(body)
    if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
        return text
    body = _without_runtime_detail(body)
    text = _bounded_text(body)
    if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
        return text
    body.pop("runtimeEvidence", None)
    text = _bounded_text(body)
    if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
        return text
    body = _without_decision_detail(body)
    text = _bounded_text(body)
    if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
        return text
    body.pop("decisionEvidence", None)
    text = _bounded_text(body)
    if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
        return text
    body = _without_project_detail(body)
    text = _bounded_text(body)
    if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
        return text
    body.pop("projectEvidence", None)
    text = _bounded_text(body)
    if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
        return text
    evidence = body.get("sourceEvidence")
    if isinstance(evidence, dict):
        reduced = dict(body)
        reduced["sourceEvidence"] = {
            "classification": "UNTRUSTED_SOURCE_EVIDENCE",
            "boundaryStart": "BEGIN_UNTRUSTED_SOURCE_EVIDENCE",
            "boundaryEnd": "END_UNTRUSTED_SOURCE_EVIDENCE",
            "truthKind": "SOURCE_TRUTH",
            "availability": "UNAVAILABLE",
            "reason": "PAYLOAD_LIMIT",
            "sourceRevision": evidence.get("sourceRevision"),
            "sourceRevisionStatus": evidence.get("sourceRevisionStatus", "UNKNOWN"),
            "productionRevision": "UNKNOWN",
            "productionRevisionStatus": "UNKNOWN",
            "singleControllerAsserted": False,
            "items": [],
        }
        text = _bounded_text(reduced)
        if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
            return text
        reduced.pop("sourceEvidence", None)
        text = _bounded_text(reduced)
        if len(text) <= MAX_CONTEXT_BLOCK_CHARS:
            return text
    fallback = _attachment("UNAVAILABLE", "PAYLOAD_LIMIT", datetime.now(timezone.utc), None)
    return _bounded_text(_retain_evidence(fallback, retained))


def provider_payload_with_context(
    payload: Mapping[str, Any],
    canonical_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Copy a provider payload and attach context only when the caller has one."""

    merged = dict(payload)
    if canonical_context is None:
        return merged
    try:
        attached = scrub_context_tree(dict(canonical_context))
        if not isinstance(attached, dict):
            raise TypeError("canonical context must be an object")
        attached.setdefault("classification", "READ_ONLY_DATA")
        attached.setdefault("authority", "NONE")
        merged["canonicalContext"] = attached
    except Exception:
        merged["canonicalContext"] = _attachment(
            "UNAVAILABLE",
            "CONTEXT_EXCEPTION",
            datetime.now(timezone.utc),
            None,
        )
    return merged


def _operator_attachment(
    app: object | None, generated_at: datetime
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    owner = _owner(app)
    if owner is None:
        return _attachment("UNAVAILABLE", "OWNER_UNAVAILABLE", generated_at, None), None
    document = copied_owner_export(owner)
    if document.get("availability") != "READY":
        return (
            _attachment("UNAVAILABLE", "OWNER_SNAPSHOT_UNAVAILABLE", generated_at, None),
            document,
        )
    collected = collection_from_owner_document(document, generated_at)
    view = scrub_context_tree(collected.operator_view)
    if not isinstance(view, dict):
        return _attachment("UNAVAILABLE", "CONTEXT_UNAVAILABLE", generated_at, None), document
    return _attachment("READY", None, generated_at, view), document


def _retain_evidence(
    fallback: dict[str, Any], retained: Mapping[str, Any]
) -> dict[str, Any]:
    """Keep bounded evidence when the operator view itself exceeds the block."""

    candidate = dict(fallback)
    for key in (
        "runtimeEvidence",
        "decisionEvidence",
        "projectEvidence",
        "sourceEvidence",
    ):
        value = retained.get(key)
        if not isinstance(value, dict):
            continue
        trial = dict(candidate)
        trial[key] = value
        if len(_bounded_text(trial)) <= MAX_CONTEXT_BLOCK_CHARS:
            candidate = trial
            continue
        compact = _compact_evidence(key, value)
        if compact is None:
            continue
        trial = dict(candidate)
        trial[key] = compact
        if len(_bounded_text(trial)) <= MAX_CONTEXT_BLOCK_CHARS:
            candidate = trial
    return candidate


def _compact_evidence(key: str, value: dict[str, Any]) -> dict[str, Any] | None:
    holder = {key: value}
    if key == "runtimeEvidence":
        return _without_runtime_detail(holder).get(key)
    if key == "decisionEvidence":
        return _without_decision_detail(holder).get(key)
    if key == "projectEvidence":
        return _without_project_detail(holder).get(key)
    if key == "sourceEvidence":
        return {
            "classification": "UNTRUSTED_SOURCE_EVIDENCE",
            "boundaryStart": "BEGIN_UNTRUSTED_SOURCE_EVIDENCE",
            "boundaryEnd": "END_UNTRUSTED_SOURCE_EVIDENCE",
            "truthKind": "SOURCE_TRUTH",
            "availability": value.get("availability", "UNKNOWN"),
            "reason": value.get("reason") or "PAYLOAD_LIMIT",
            "sourceRevision": value.get("sourceRevision"),
            "sourceRevisionStatus": value.get("sourceRevisionStatus", "UNKNOWN"),
            "productionRevision": "UNKNOWN",
            "productionRevisionStatus": "UNKNOWN",
            "singleControllerAsserted": False,
            "items": [],
        }
    return None


def _without_runtime_detail(body: dict[str, Any]) -> dict[str, Any]:
    runtime = body.get("runtimeEvidence")
    if not isinstance(runtime, dict):
        return body
    reduced = dict(body)
    reduced["runtimeEvidence"] = {
        "classification": "READ_ONLY_RUNTIME_EVIDENCE",
        "boundaryStart": "BEGIN_UNTRUSTED_RUNTIME_EVIDENCE",
        "boundaryEnd": "END_UNTRUSTED_RUNTIME_EVIDENCE",
        "truthKind": "RUNTIME_TRUTH",
        "availability": "UNAVAILABLE",
        "reason": "PAYLOAD_LIMIT",
        "productionRuntimeConnected": False,
        "domains": {},
    }
    return reduced


def _runtime_evidence(document: dict[str, Any] | None) -> dict[str, Any]:
    try:
        from backend.context.runtime_evidence import collect_runtime_evidence

        evidence = collect_runtime_evidence(document)
        if isinstance(evidence, dict):
            return evidence
    except Exception:
        pass
    return {
        "classification": "READ_ONLY_RUNTIME_EVIDENCE",
        "truthKind": "RUNTIME_TRUTH",
        "productionRuntimeConnected": False,
        "domains": {},
        "reason": "RUNTIME_EXCEPTION",
    }


def _without_decision_detail(body: dict[str, Any]) -> dict[str, Any]:
    decision = body.get("decisionEvidence")
    if not isinstance(decision, dict):
        return body
    reduced = dict(body)
    reduced["decisionEvidence"] = {
        "classification": "UNTRUSTED_DECISION_EVIDENCE",
        "boundaryStart": "BEGIN_UNTRUSTED_DECISION_EVIDENCE",
        "boundaryEnd": "END_UNTRUSTED_DECISION_EVIDENCE",
        "truthKind": "DECISION_TRUTH",
        "temporalScope": "HISTORICAL",
        "currentApplicability": "UNKNOWN",
        "availability": "UNAVAILABLE",
        "reason": "PAYLOAD_LIMIT",
        "productionRuntimeConnected": False,
        "items": [],
    }
    return reduced


def _decision_evidence(question: str, facade: Any) -> dict[str, Any]:
    try:
        from backend.context.decision_evidence import collect_decision_evidence

        evidence = collect_decision_evidence(question, facade)
        if isinstance(evidence, dict):
            return evidence
    except Exception:
        pass
    return {
        "classification": "UNTRUSTED_DECISION_EVIDENCE",
        "truthKind": "DECISION_TRUTH",
        "temporalScope": "HISTORICAL",
        "currentApplicability": "UNKNOWN",
        "availability": "UNAVAILABLE",
        "reason": "DECISION_EXCEPTION",
        "productionRuntimeConnected": False,
        "items": [],
    }


def _without_project_detail(body: dict[str, Any]) -> dict[str, Any]:
    project = body.get("projectEvidence")
    if not isinstance(project, dict):
        return body
    reduced = dict(body)
    reduced["projectEvidence"] = {
        "classification": "UNTRUSTED_PROJECT_EVIDENCE",
        "boundaryStart": "BEGIN_UNTRUSTED_PROJECT_EVIDENCE",
        "boundaryEnd": "END_UNTRUSTED_PROJECT_EVIDENCE",
        "truthKind": "PROJECT_TRUTH",
        "availability": "UNAVAILABLE",
        "reason": "PAYLOAD_LIMIT",
        "designStatus": project.get("designStatus", "UNKNOWN"),
        "implementationStatus": project.get("implementationStatus", "UNKNOWN"),
        "integrationStatus": "UNKNOWN",
        "deploymentStatus": project.get("deploymentStatus", "UNKNOWN"),
        "runtimeStatus": "UNKNOWN",
        "productionRuntimeConnected": False,
        "productionRevision": "UNKNOWN",
        "documents": [],
    }
    return reduced


def _project_evidence(question: str, repository: Any) -> dict[str, Any]:
    try:
        from backend.context.project_evidence import collect_project_evidence

        evidence = collect_project_evidence(question, repository)
        if isinstance(evidence, dict):
            return evidence
    except Exception:
        pass
    return {
        "classification": "UNTRUSTED_PROJECT_EVIDENCE",
        "truthKind": "PROJECT_TRUTH",
        "availability": "UNAVAILABLE",
        "reason": "PROJECT_EXCEPTION",
        "designStatus": "UNKNOWN",
        "implementationStatus": "UNKNOWN",
        "integrationStatus": "UNKNOWN",
        "deploymentStatus": "UNKNOWN",
        "runtimeStatus": "UNKNOWN",
        "productionRuntimeConnected": False,
        "productionRevision": "UNKNOWN",
        "documents": [],
    }


def _source_evidence(question: str, repository: Any) -> dict[str, Any]:
    try:
        from backend.context.source_evidence import collect_source_evidence

        evidence = collect_source_evidence(question, repository)
        if isinstance(evidence, dict):
            return evidence
    except Exception:
        pass
    return {
        "classification": "UNTRUSTED_SOURCE_EVIDENCE",
        "truthKind": "SOURCE_TRUTH",
        "availability": "UNAVAILABLE",
        "reason": "SOURCE_EXCEPTION",
        "sourceRevision": None,
        "sourceRevisionStatus": "UNAVAILABLE",
        "productionRevision": "UNKNOWN",
        "productionRevisionStatus": "UNKNOWN",
        "singleControllerAsserted": False,
        "items": [],
    }


def _safe_attachment(attachment: Mapping[str, Any]) -> dict[str, Any]:
    try:
        body = scrub_context_tree(dict(attachment))
        if isinstance(body, dict):
            return body
    except Exception:
        pass
    return _attachment(
        "UNAVAILABLE",
        "CONTEXT_EXCEPTION",
        datetime.now(timezone.utc),
        None,
    )


def _bounded_text(body: Mapping[str, Any]) -> str:
    return _INJECTION.sub("[REMOVED:PROMPT_INJECTION]", _labeled(body))


def _owner(app: object | None) -> Any:
    state = getattr(app, "state", None)
    lookup = getattr(state, "context_owner_lookup", None)
    if callable(lookup):
        return lookup()
    return existing_owner_from_process()


def _attachment(
    availability: str,
    reason: str | None,
    generated_at: datetime,
    operator_view: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "classification": "READ_ONLY_DATA",
        "authority": "NONE",
        "tradingControl": "FORBIDDEN",
        "availability": availability,
        "contextGeneratedAt": generated_at.isoformat().replace("+00:00", "Z"),
        "clockPolicy": {
            "contextGeneratedAtIsNotProducerObservedAt": True,
            "snapshotPublishedAtIsNotProducerEvaluatedAt": True,
        },
        "unconnected": dict(_UNCONNECTED),
        "productionRuntimeConnected": PRODUCTION_RUNTIME_CONNECTED,
        "productionApiAvailable": PRODUCTION_API_AVAILABLE,
        "operatorView": operator_view,
    }
    if reason is not None:
        body["reason"] = reason
    return body


def _labeled(body: Mapping[str, Any]) -> str:
    import json

    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return (
        "classification=READ_ONLY_DATA\n"
        "authority=NONE\n"
        "tradingControl=FORBIDDEN\n"
        "instructionBoundary=DATA_ONLY\n"
        f"{encoded}"
    )
