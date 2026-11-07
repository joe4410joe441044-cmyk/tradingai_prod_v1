"""Question-scoped project evidence for authenticated answer prompts.

The evidence is read-only data. It reuses ``load_project_truth`` and
``load_authoritative_specifications``. It does not search the filesystem,
accept a caller path, or treat a design document as implementation,
deployment, or runtime truth.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.ai_advisor.authoritative_knowledge import (
    KnowledgeManifestError,
    _load_entry,
    production_knowledge_manifest,
    select_highest_authority,
)
from backend.context.project_truth import load_project_truth

MAX_DOCUMENTS = 2
MAX_EXCERPT_CHARS = 480
_REGISTRY_RELATIVE = Path("docs/ai/PROJECT_STATE.yaml")
_INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+|previous\s+|prior\s+)*instructions|"
    r"system\s+prompt|you\s+are\s+now|do\s+not\s+follow|"
    r"disregard\s+(all\s+|any\s+|previous\s+)*instructions)"
)
_SECRET = re.compile(
    r"(?i)(api[_-]?key|secret|password|token|credential|private[_-]?key)"
)
_AUTHORITY_RANK = {
    "CONSTITUTION": 4,
    "ADR": 3,
    "MASTER_SPEC": 2,
    "FEATURE_SPEC": 1,
}
_TOPICS = (
    ("MONEY_MANAGEMENT", ("money management", "資金管理", "マネーマネジメント")),
    ("MARKET_INTELLIGENCE", ("market intelligence", "マーケットインテリジェンス")),
    ("MARKET_RECORDER", ("market recorder", "マーケットレコーダー")),
    ("SUPERVISOR", ("supervisor", "スーパーバイザー", "スーパーバイザ")),
    ("AI_ADVISOR", ("ai advisor", "アドバイザー", "アドバイザ")),
    ("PLATFORM", ("全体構造", "constitution", "プラットフォーム構造")),
)
_CHANGE_KEYS = ("最近の仕様", "仕様変更", "変更履歴", "recent specification", "changelog")
_HYRO_KEYS = ("hyro", "プロップ")
_PAPER_LIVE_KEYS = ("paperとlive", "paper and live", "paper / live", "paper/live")
_MANUAL_KEYS = ("manual trading", "手動", "manual close")
_CYCLE_KEYS = ("trading cycle", "トレーディングサイクル")
_WORKSTREAMS = {
    "MONEY_MANAGEMENT": "MM",
    "AI_ADVISOR": "BB",
    "SUPERVISOR": "BB",
}


def document_class(authority: str) -> str:
    """Map the existing authority enum onto the answer label."""

    if authority in {"CONSTITUTION", "ADR"}:
        return "AUTHORITATIVE"
    if authority in {"MASTER_SPEC", "FEATURE_SPEC"}:
        return "APPROVED"
    return "UNKNOWN"


def neutralize_project_text(value: str) -> str:
    """Keep document text as data and drop instruction-shaped phrases."""

    return _INJECTION.sub("[REMOVED:PROMPT_INJECTION]", value)


def resolve_authority(entries) -> dict[str, Any]:
    """Prefer the existing authority rank. Same-rank conflicts select nothing."""

    try:
        selected = select_highest_authority(tuple(entries))
    except KnowledgeManifestError as exc:
        reason = "SPEC_CONFLICT" if exc.code == "SAME_AUTHORITY_CONFLICT" else exc.code
        return {"availability": "UNKNOWN", "reason": reason, "entries": ()}
    return {"availability": "READY", "reason": None, "entries": selected}


def collect_project_evidence(
    question: str,
    repository: Path | None = None,
) -> dict[str, Any]:
    """Return bounded project evidence for one question.

    The question selects a fixed topic. It is never a filesystem path.
    """

    text = question if isinstance(question, str) else ""
    folded = text.casefold()
    if any(key in folded for key in _CHANGE_KEYS):
        return _evidence(
            availability="UNKNOWN",
            reason="CHANGE_HISTORY_UNAVAILABLE",
            registry=_unread_registry(),
        )
    if any(key in folded for key in _HYRO_KEYS) or _prop_question(text):
        return _evidence(
            availability="UNKNOWN",
            reason="NO_PROJECT_EVIDENCE",
            registry=_unread_registry(),
        )
    topics = _matched_topics(folded)
    if not topics and _unsupported_design_question(folded):
        return _evidence(
            availability="UNKNOWN",
            reason="NO_AUTHORITATIVE_SPEC",
            registry=_unread_registry(),
        )
    if not topics:
        return _evidence(
            availability="UNKNOWN",
            reason="NO_MATCHING_PROJECT",
            registry=_unread_registry(),
        )

    root = _repository_root(repository)
    if root is None:
        return _evidence(
            availability="UNAVAILABLE",
            reason="PROJECT_ROOT_UNAVAILABLE",
            registry=_unread_registry(),
        )
    try:
        documents, failure = _documents_for_topics(root, topics)
    except KnowledgeManifestError as exc:
        reason = (
            "SPEC_CONFLICT" if exc.code == "SAME_AUTHORITY_CONFLICT" else "SPEC_UNAVAILABLE"
        )
        return _evidence(
            availability="UNKNOWN",
            reason=reason,
            registry=_safe_registry(root, topics),
        )
    except Exception:
        return _evidence(
            availability="UNAVAILABLE",
            reason="PROJECT_EXCEPTION",
            registry=_unread_registry(),
        )

    registry = _safe_registry(root, topics)
    if documents:
        return _evidence(
            availability="READY",
            reason=None,
            documents=documents,
            registry=registry,
            execution_comparison=(
                "UNKNOWN" if _contains(folded, _PAPER_LIVE_KEYS) else None
            ),
        )
    return _evidence(
        availability="UNKNOWN",
        reason=failure or "NO_AUTHORITATIVE_SPEC",
        registry=registry,
    )


def _prop_question(text: str) -> bool:
    return re.search(r"\bprop\b", text, re.IGNORECASE) is not None


def _contains(folded: str, keys: tuple[str, ...]) -> bool:
    return any(key in folded for key in keys)


def _unsupported_design_question(folded: str) -> bool:
    return (
        _contains(folded, _PAPER_LIVE_KEYS)
        or _contains(folded, _MANUAL_KEYS)
        or _contains(folded, _CYCLE_KEYS)
    )


def _matched_topics(folded: str) -> tuple[str, ...]:
    found = [topic for topic, keys in _TOPICS if _contains(folded, keys)]
    return tuple(found)


def _repository_root(repository: Path | None) -> Path | None:
    candidate = repository or Path(__file__).resolve().parents[2]
    try:
        root = Path(candidate).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not root.is_dir():
        return None
    return root


def _registry_file(root: Path) -> Path | None:
    current = root
    for part in _REGISTRY_RELATIVE.parts:
        if part in {"", ".", ".."}:
            return None
        current = current / part
        try:
            if current.is_symlink():
                return None
        except OSError:
            return None
    if not current.is_file():
        return None
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _safe_registry(root: Path, topics: tuple[str, ...]) -> dict[str, Any]:
    path = _registry_file(root)
    if path is None:
        return _unread_registry()
    try:
        truth = load_project_truth(path)
    except Exception:
        return _unread_registry()
    updated = None
    if truth.updatedAt is not None and truth.meta.availability.value == "AVAILABLE":
        updated = truth.updatedAt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    wanted = {_WORKSTREAMS[topic] for topic in topics if topic in _WORKSTREAMS}
    workstreams = []
    for item in truth.workstreams:
        if item.workstreamId not in wanted:
            continue
        workstreams.append(
            {
                "workstreamId": item.workstreamId,
                "registryStatus": item.status.value,
                "verification": item.verification.value,
            }
        )
    availability = truth.meta.availability.value
    return {
        "availability": availability,
        "schemaVersion": truth.schemaVersion if availability == "AVAILABLE" else None,
        "projectUpdatedAt": updated,
        "workstreams": workstreams,
        "reader": "project-truth-registry",
    }


def _unread_registry() -> dict[str, Any]:
    return {
        "availability": "UNAVAILABLE",
        "schemaVersion": None,
        "projectUpdatedAt": None,
        "workstreams": [],
        "reader": "project-truth-registry",
    }


def _documents_for_topics(
    root: Path, topics: tuple[str, ...]
) -> tuple[list[dict[str, Any]], str | None]:
    matched_entries = [
        entry
        for entry in production_knowledge_manifest()
        if any(topic in entry.topics for topic in topics)
    ]
    loaded = {}
    failures = []
    observed = datetime.now(timezone.utc)
    for entry in matched_entries:
        try:
            loaded[entry.sourceId] = _load_entry(
                entry, repository_root=root, loaded_at=observed
            )
        except KnowledgeManifestError as exc:
            failures.append(exc.code)
    if not loaded:
        if failures and all(code == "HASH_MISMATCH" for code in failures):
            return [], "HASH_MISMATCH"
        if failures:
            return [], "SPEC_UNAVAILABLE"
        return [], "NO_AUTHORITATIVE_SPEC"
    chosen = select_highest_authority(tuple(entry for entry in matched_entries if entry.sourceId in loaded))
    selected = []
    for entry in chosen:
        item = loaded[entry.sourceId]
        matched = [topic for topic in item.topics if topic in topics]
        selected.append((item, matched))
    selected.sort(
        key=lambda pair: (
            -_AUTHORITY_RANK.get(pair[0].authorityLevel, 0),
            pair[0].sourceId,
        )
    )
    documents = []
    for item, matched in selected[:MAX_DOCUMENTS]:
        excerpt, excerpt_status = _excerpt(item.excerpt or "")
        documents.append(
            {
                "projectSource": "authoritative-spec-manifest",
                "projectDocument": item.documentPath,
                "projectSection": neutralize_project_text(item.title),
                "projectRevision": item.sourceVersion,
                "projectRevisionKind": "SPEC_VERSION",
                "projectAuthority": item.authorityLevel,
                "documentClass": document_class(item.authorityLevel),
                "projectStatus": "HASH_VERIFIED",
                "contentHash": item.contentHash,
                "topics": matched,
                "excerpt": excerpt,
                "excerptStatus": excerpt_status,
                "projectProvenance": {
                    "reader": "load_authoritative_specifications",
                    "hashVerified": True,
                },
            }
        )
    return documents, None


def _excerpt(value: str) -> tuple[str | None, str]:
    if _SECRET.search(value):
        return None, "SECRET_EXCLUDED"
    cleaned = neutralize_project_text(value).strip()
    if len(cleaned) > MAX_EXCERPT_CHARS:
        return None, "EXCERPT_LIMIT"
    if not cleaned:
        return None, "EXCERPT_UNAVAILABLE"
    return cleaned, "PRESENT"


def _statuses(documents: list[dict[str, Any]], registry: dict[str, Any]) -> dict[str, str]:
    records = registry.get("workstreams") or []
    implementation = "UNKNOWN"
    deployment = "UNKNOWN"
    for record in records:
        if (
            record.get("registryStatus") == "COMPLETE"
            and record.get("verification") == "VERIFIED"
        ):
            implementation = "REGISTRY_COMPLETE"
        if (
            record.get("registryStatus") == "DEPLOYED"
            and record.get("verification") == "VERIFIED"
        ):
            deployment = "REGISTRY_DEPLOYED"
    return {
        "designStatus": "DESIGNED" if documents else "UNKNOWN",
        "implementationStatus": implementation,
        "integrationStatus": "UNKNOWN",
        "deploymentStatus": deployment,
        "runtimeStatus": "UNKNOWN",
    }


def _evidence(
    *,
    availability: str,
    reason: str | None,
    registry: dict[str, Any] | None = None,
    documents: list[dict[str, Any]] | None = None,
    execution_comparison: str | None = None,
) -> dict[str, Any]:
    registry = registry or _unread_registry()
    documents = documents or []
    body = {
        "classification": "UNTRUSTED_PROJECT_EVIDENCE",
        "boundaryStart": "BEGIN_UNTRUSTED_PROJECT_EVIDENCE",
        "boundaryEnd": "END_UNTRUSTED_PROJECT_EVIDENCE",
        "truthKind": "PROJECT_TRUTH",
        "authority": "NONE",
        "tradingControl": "FORBIDDEN",
        "instructionBoundary": "DATA_ONLY",
        "availability": availability,
        "reason": reason,
        "changeHistory": "UNKNOWN",
        "productionRuntimeConnected": False,
        "productionRevision": "UNKNOWN",
        "separatedFrom": ["sourceEvidence", "operatorView"],
        "projectUpdatedAt": registry.get("projectUpdatedAt"),
        "projectProvenance": {
            "reader": registry.get("reader", "project-truth-registry"),
            "projectSource": "docs/ai/PROJECT_STATE.yaml",
        },
        "registry": {
            "availability": registry.get("availability", "UNAVAILABLE"),
            "schemaVersion": registry.get("schemaVersion"),
            "workstreams": registry.get("workstreams") or [],
        },
        "documents": documents,
    }
    body.update(_statuses(documents, registry))
    if execution_comparison is not None:
        body["executionComparison"] = execution_comparison
    return body
