"""Question-scoped decision evidence for authenticated answer prompts.

The evidence is read-only. It reuses ``KnowledgeHistoryQueryFacade`` and does
not create a history store. A recorded cycle or trace item stays historical.
It is not a current runtime fact, a specification, or an invented reason.
"""

from __future__ import annotations

import re
from typing import Any

from backend.runtime.knowledge_history_models import (
    KnowledgeHistoryQuery,
    parse_timestamp,
)

MAX_ITEMS = 4
MAX_TEXT_CHARS = 240
_INTENT = re.compile(
    r"(なぜ|なんで|why|reason|判断|意思決定|decision|変更理由|障害|以前|"
    r"設計判断|履歴|問題)",
    re.IGNORECASE,
)
_INJECTION = re.compile(
    r"(?i)(ignore\s+(all\s+|any\s+|previous\s+|prior\s+)*instructions|"
    r"system\s+prompt|you\s+are\s+now|do\s+not\s+follow|"
    r"disregard\s+(all\s+|any\s+|previous\s+)*instructions)"
)
_SECRET = re.compile(
    r"(?i)(api[_-]?key|secret|password|token|credential|private[_-]?key)\s*[:=]"
)
_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_TOPICS = (
    ("EXECUTION", ("execution authority", "執行権限", "執行")),
    ("PAPER", ("paper", "ペーパー")),
    ("MANUAL", ("manual", "手動")),
    ("MONEY_MANAGEMENT", ("money management", "資金管理", "マネーマネジメント")),
)
_DECISION_STATUSES = {"RECORDED", "SUPERSEDED", "REVOKED"}


def neutralize_decision_text(value: str) -> str:
    """Keep recorded history text as data."""

    return _INJECTION.sub("[REMOVED:PROMPT_INJECTION]", value)


def collect_decision_evidence(
    question: str,
    facade: Any = None,
) -> dict[str, Any]:
    """Return bounded historical decision evidence for one question.

    The question is not a query string. Only structured filters already
    accepted by the history facade are forwarded.
    """

    text = question if isinstance(question, str) else ""
    if _INTENT.search(text) is None:
        return _evidence("UNAVAILABLE", "NO_MATCHING_DECISION")
    try:
        result = _facade(facade).query(_query(text, facade))
    except Exception:
        return _evidence("UNAVAILABLE", "DECISION_EXCEPTION")
    if not isinstance(result, dict):
        return _evidence("UNAVAILABLE", "DECISION_EXCEPTION")
    items = _select(text, result.get("items") or [])
    if not items:
        return _evidence("UNAVAILABLE", "NO_RECORDED_DECISION")
    return _evidence("READY", None, items)


def _facade(facade: Any) -> Any:
    if facade is not None:
        return facade
    from backend.runtime.knowledge_history_query import shared_knowledge_history_facade

    return shared_knowledge_history_facade()


def _facade_sources(facade: Any) -> tuple[str, ...]:
    service = getattr(facade, "service", None)
    sources = getattr(service, "_sources", None)
    if isinstance(sources, dict) and sources:
        return tuple(str(name) for name in sources.keys())
    return ("CYCLE_EVIDENCE", "TRADING_TRACE")


def _query(question: str, facade: Any) -> KnowledgeHistoryQuery:
    from backend.ai_advisor.knowledge_history_consumer import classify_advisor_question

    plan = classify_advisor_question(question)
    base = plan.query
    return KnowledgeHistoryQuery(
        cycle_id=getattr(base, "cycle_id", None),
        trace_id=getattr(base, "trace_id", None),
        evidence_id=getattr(base, "evidence_id", None),
        symbol=getattr(base, "symbol", None),
        mode=getattr(base, "mode", None),
        time_from=getattr(base, "time_from", None),
        time_to=getattr(base, "time_to", None),
        evidence_type=getattr(base, "evidence_type", None),
        source=_facade_sources(facade),
        limit=MAX_ITEMS,
        cursor=None,
    )


def _select(question: str, raw_items: Any) -> list[dict[str, Any]]:
    topics = _topics(question)
    selected = []
    if not isinstance(raw_items, list):
        return selected
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        item = _project(raw)
        if item is None or not _matches(topics, item):
            continue
        selected.append(item)
    if _recent(question):
        selected = [item for item in selected if item["decisionTimestamp"] != "UNKNOWN"]
        selected.sort(key=lambda item: (item["decisionTimestamp"], item["decisionId"]))
    return selected[:MAX_ITEMS]


def _topics(question: str) -> tuple[str, ...]:
    folded = question.casefold()
    return tuple(name for name, keys in _TOPICS if any(key.casefold() in folded for key in keys))


def _recent(question: str) -> bool:
    return "最近" in question or "recent" in question.casefold()


def _matches(topics: tuple[str, ...], item: dict[str, Any]) -> bool:
    if not topics:
        return True
    blob = " ".join(
        str(item.get(name) or "")
        for name in (
            "decisionType",
            "decisionTitle",
            "decisionReason",
            "decisionSummary",
            "relatedComponent",
            "mode",
        )
    ).casefold()
    checks = {
        "EXECUTION": "execution" in blob or "執行" in blob,
        "PAPER": item.get("mode") == "PAPER" or "paper" in blob or "ペーパー" in blob,
        "MANUAL": "manual" in blob or "手動" in blob,
        "MONEY_MANAGEMENT": (
            "money" in blob or "資金" in blob or "マネー" in blob
        ),
    }
    return all(checks[topic] for topic in topics)


def _project(raw: dict[str, Any]) -> dict[str, Any] | None:
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    provenance = raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {}
    decision_id = raw.get("evidence_id") or raw.get("event_key")
    if not isinstance(decision_id, str) or not decision_id.strip():
        return None
    timestamp = raw.get("captured_at")
    if not isinstance(timestamp, str) or parse_timestamp(timestamp) is None:
        timestamp = "UNKNOWN"
    reason = _recorded_text(payload, "decision_reason", "reason")
    summary = _recorded_text(payload, "decision_summary")
    component = _optional_text(payload.get("component"))
    related_commit = _commit(payload.get("related_commit") or payload.get("commit_sha"))
    related_document = _document(payload.get("related_document"))
    supersedes = _optional_text(payload.get("supersedes_decision_id"))
    event_id = _optional_text(raw.get("event_id"))
    status = _status(payload.get("decision_status"))
    item = {
        "decisionId": decision_id.strip(),
        "decisionSource": raw.get("source") or "UNKNOWN",
        "decisionType": raw.get("evidence_type") or "UNKNOWN",
        "decisionTitle": component or raw.get("evidence_type") or "UNKNOWN",
        "decisionSummary": summary,
        "decisionReason": reason,
        "decisionTimestamp": timestamp,
        "decisionStatus": status,
        "temporalScope": "HISTORICAL",
        "currentApplicability": "UNKNOWN",
        "mode": raw.get("mode") if isinstance(raw.get("mode"), str) else None,
        "decisionProvenance": {
            "reader": "KnowledgeHistoryQueryFacade",
            "decisionSource": raw.get("source") or "UNKNOWN",
            "readMethod": provenance.get("read_method"),
            "integrity": provenance.get("integrity") or "UNKNOWN",
            "evidenceId": raw.get("evidence_id"),
        },
    }
    if component is not None:
        item["relatedComponent"] = component
    if related_commit is not None:
        item["relatedCommit"] = related_commit
    if related_document is not None:
        item["relatedDocument"] = related_document
    if event_id is not None:
        item["relatedRuntimeEvent"] = event_id
    if supersedes is not None:
        item["supersedesDecisionId"] = supersedes
    rendered = str(item)
    if (
        _SECRET.search(rendered)
        or "REMOVED:SENSITIVE" in rendered
        or "/home/" in rendered
        or "/logs/" in rendered
    ):
        return None
    return item


def _recorded_text(payload: dict[str, Any], *names: str) -> str:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            cleaned = neutralize_decision_text(value.strip())
            if len(cleaned) > MAX_TEXT_CHARS:
                return "UNKNOWN"
            return cleaned
    return "UNKNOWN"


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return neutralize_decision_text(value.strip())[:MAX_TEXT_CHARS]
    return None


def _commit(value: Any) -> str | None:
    if isinstance(value, str) and _COMMIT.fullmatch(value.strip()):
        return value.strip()
    return None


def _document(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("docs/") and ".." not in text.split("/"):
        return text
    return None


def _status(value: Any) -> str:
    if isinstance(value, str) and value.strip().upper() in _DECISION_STATUSES:
        return value.strip().upper()
    return "RECORDED"


def _evidence(
    availability: str,
    reason: str | None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "classification": "UNTRUSTED_DECISION_EVIDENCE",
        "boundaryStart": "BEGIN_UNTRUSTED_DECISION_EVIDENCE",
        "boundaryEnd": "END_UNTRUSTED_DECISION_EVIDENCE",
        "truthKind": "DECISION_TRUTH",
        "temporalScope": "HISTORICAL",
        "currentApplicability": "UNKNOWN",
        "authority": "NONE",
        "tradingControl": "FORBIDDEN",
        "instructionBoundary": "DATA_ONLY",
        "availability": availability,
        "reason": reason,
        "productionRuntimeConnected": False,
        "separatedFrom": ["sourceEvidence", "projectEvidence", "operatorView"],
        "items": items or [],
    }
