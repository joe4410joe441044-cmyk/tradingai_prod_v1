"""READ-ONLY AI Advisor consumer of the shared knowledge/history query layer.

This module connects the *existing* AI Advisor to the already completed shared
knowledge/history query foundation (WORK I②).  It adds no new knowledge store,
no new trading-trace reader and no new evidence schema: every read goes through
:class:`backend.runtime.knowledge_history_query.KnowledgeHistoryQueryService`.

Guarantees:

* a dedicated, default-OFF feature flag
  (:data:`ADVISOR_KNOWLEDGE_HISTORY_ENABLED_ENV`) gates the whole connection;
* importing or constructing the consumer performs no I/O and runs no query;
* a query only happens at request time, only for a history-relevant question,
  and only when the flag is enabled;
* the query is always bounded, deterministic and never accepts a caller cursor;
* the query result is converted into a bounded, sanitized context block that
  exposes provenance, freshness, availability, partial-result and
  unsupported-filter warnings and an explicit uncertainty level;
* a query failure never breaks the Advisor answer path -- it falls back to the
  existing pipeline and records that the fallback happened.

The consumer is strictly read-only.  It never mutates parameters, settings,
governance, runtime, bots, orders, positions or evidence and never calls an
execution/provider boundary.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from backend.runtime.cycle_evidence import (
    EvidenceType,
    LIFECYCLE_STAGE_NAMES,
)
from backend.runtime.knowledge_history_models import (
    KnowledgeHistoryQuery,
    parse_timestamp,
)
from backend.runtime.knowledge_history_query import (
    KnowledgeHistoryQueryFacade,
    shared_knowledge_history_facade,
)
from backend.runtime.knowledge_history_sanitizer import sanitize_summary

ADVISOR_KNOWLEDGE_HISTORY_ENABLED_ENV = "AI_ADVISOR_KNOWLEDGE_HISTORY_ENABLED"

# Small request-time budget: history evidence must never flood the Advisor
# response.  The hard maximum is still enforced by the shared query contract.
ADVISOR_QUERY_DEFAULT_LIMIT = 8
ADVISOR_CONTEXT_MAX_ITEMS = 12
ADVISOR_CONTEXT_MAX_CHARACTERS = 12_000

MAX_IDENTIFIER_CHARACTERS = 128

_TRUTHY = {"1", "true", "yes", "on"}

_IDENTIFIER_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "cycle_id",
        re.compile(
            r"(?:cycle[\s_-]?id|サイクルid|サイクル)\s*[:=：]?\s*"
            r"([A-Za-z0-9][A-Za-z0-9._:-]{0,127})",
            re.IGNORECASE,
        ),
    ),
    (
        "trace_id",
        re.compile(
            r"(?:trace[\s_-]?id|correlation[\s_-]?id|トレースid)\s*[:=：]?\s*"
            r"([A-Za-z0-9][A-Za-z0-9._:-]{0,127})",
            re.IGNORECASE,
        ),
    ),
    (
        "evidence_id",
        re.compile(
            r"(?:evidence[\s_-]?id|証跡id|エビデンスid)\s*[:=：]?\s*"
            r"([A-Za-z0-9][A-Za-z0-9._:-]{0,127})",
            re.IGNORECASE,
        ),
    ),
)

_BARE_IDENTIFIER_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("cycle_id", re.compile(r"\bcycle-[A-Za-z0-9][A-Za-z0-9._-]{0,120}\b")),
    ("trace_id", re.compile(r"\b(?:trace|correlation)-[A-Za-z0-9][A-Za-z0-9._-]{0,120}\b")),
    ("evidence_id", re.compile(r"\bevidence-[A-Za-z0-9][A-Za-z0-9._-]{0,120}\b")),
)

_SYMBOL_PATTERN = re.compile(
    r"\b([A-Z]{2,10}(?:USDT|USDC|BUSD|TUSD|FDUSD|BTC|ETH|JPY|EUR|GBP))\b"
)
_EXPLICIT_SYMBOL_PATTERN = re.compile(
    r"(?:symbol|銘柄|シンボル)\s*[:=：]\s*([A-Za-z0-9]{2,24})",
    re.IGNORECASE,
)
_STAGE_PATTERN = re.compile(
    r"(?:stage|ステージ)\s*[:=：]?\s*([0-9]{1,2})",
    re.IGNORECASE,
)
_MODE_PATTERN = re.compile(r"(?:mode|モード)\s*[:=：]\s*(PAPER|LIVE)", re.IGNORECASE)
_STATUS_PATTERN = re.compile(
    r"(?:status|ステータス)\s*[:=：]\s*([A-Za-z][A-Za-z0-9_]{0,63})",
    re.IGNORECASE,
)
_EVIDENCE_TYPE_PATTERN = re.compile(
    r"(?:evidence[\s_-]?type|証跡種別)\s*[:=：]\s*([A-Za-z][A-Za-z0-9_]{0,63})",
    re.IGNORECASE,
)
_ISO_TIME_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?)?"
)

_HISTORY_KEYWORDS = re.compile(
    r"(理由|なぜ|なんで|why|reason|decision|judg|判断|意思決定|"
    r"entry|エントリー|エントリ|signal|シグナル|detector|検出|"
    r"parameter|パラメータ|設定変更|変更前|変更後|"
    r"supervisor|スーパーバイザ|警告|warning|"
    r"performance|パフォーマンス|成績|取引結果|損益|pnl|profit|"
    r"履歴|history|trace|トレース|cycle|サイクル|"
    r"evidence|証跡|エビデンス|freshness|鮮度|stale|"
    r"provenance|出典|source|ソース|stage|ステージ|"
    r"recent|最近|直近|flow|流れ|経緯|根拠)",
    re.IGNORECASE,
)

_NAVIGATION_KEYWORDS = re.compile(
    r"(操作方法|使い方|どうやって|how\s+do\s+i|how\s+to|画面|どこを|"
    r"click|クリック|navigate|navigation|open\s+the\s+page)",
    re.IGNORECASE,
)

def advisor_knowledge_history_enabled(
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return whether the Advisor knowledge/history consumer is enabled (default OFF).

    This flag is independent of the Phase A producer flag and of the shared
    ``KNOWLEDGE_HISTORY_QUERY_CONSUMERS_ENABLED`` exposure flag.
    """

    env = os.environ if environ is None else environ
    raw = str(env.get(ADVISOR_KNOWLEDGE_HISTORY_ENABLED_ENV, "")).strip().lower()
    return raw in _TRUTHY


@dataclass(frozen=True)
class AdvisorQuestionPlan:
    """A deterministic, read-only query plan for one Advisor question."""

    relevant: bool
    reason: str
    query: Optional[KnowledgeHistoryQuery]
    notes: Tuple[str, ...] = ()


def _first_match(pattern: re.Pattern[str], text: str) -> Optional[str]:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group(1) if match.groups() else match.group(0)


def _extract_identifiers(text: str) -> dict:
    values: dict[str, Optional[str]] = {
        "cycle_id": None,
        "trace_id": None,
        "evidence_id": None,
    }
    for field, pattern in _IDENTIFIER_PATTERNS:
        value = _first_match(pattern, text)
        if value:
            values[field] = value[:MAX_IDENTIFIER_CHARACTERS]
    for field, pattern in _BARE_IDENTIFIER_PATTERNS:
        if values[field] is None:
            value = _first_match(pattern, text)
            if value:
                values[field] = value[:MAX_IDENTIFIER_CHARACTERS]
    return values


def _extract_symbol(text: str) -> Optional[str]:
    value = _first_match(_EXPLICIT_SYMBOL_PATTERN, text)
    if value is None:
        value = _first_match(_SYMBOL_PATTERN, text)
    if value is None:
        return None
    token = value.strip().upper()
    if not token or len(token) > 32:
        return None
    return token


def _extract_stage(text: str, notes: list[str]) -> Optional[int]:
    value = _first_match(_STAGE_PATTERN, text)
    if value is None:
        return None
    try:
        stage = int(value)
    except (TypeError, ValueError):
        notes.append("STAGE_UNPARSEABLE")
        return None
    if stage not in LIFECYCLE_STAGE_NAMES:
        notes.append("STAGE_OUT_OF_RANGE")
        return None
    return stage


def _extract_enum(
    pattern: re.Pattern[str],
    text: str,
    allowed: set[str],
    note: str,
    notes: list[str],
) -> Optional[str]:
    value = _first_match(pattern, text)
    if value is None:
        return None
    token = value.strip().upper()
    if token not in allowed:
        notes.append(note)
        return None
    return token


def _extract_time_range(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract only timestamps that are literally present in the question."""

    matches = _ISO_TIME_PATTERN.findall(text)
    valid = [match for match in matches if parse_timestamp(match) is not None]
    if len(valid) >= 2:
        lower, upper = valid[0], valid[1]
        lower_seconds = parse_timestamp(lower)
        upper_seconds = parse_timestamp(upper)
        if lower_seconds is not None and upper_seconds is not None:
            if lower_seconds <= upper_seconds:
                return lower, upper
            return upper, lower
        return lower, upper
    return None, None


def classify_advisor_question(message: Any) -> AdvisorQuestionPlan:
    """Classify a question and build a bounded, safe query plan.

    The classifier is deliberately conservative: it only derives a filter from a
    value that is literally present in the question and never invents an
    identifier, symbol or time period.
    """

    notes: list[str] = []
    if not isinstance(message, str) or not message.strip():
        return AdvisorQuestionPlan(False, "EMPTY_MESSAGE", None, tuple(notes))

    text = message.strip()
    identifiers = _extract_identifiers(text)
    explicit_identifier = any(identifiers.values())

    symbol = _extract_symbol(text)
    stage = _extract_stage(text, notes)
    mode = _extract_enum(
        _MODE_PATTERN, text, {"PAPER", "LIVE"}, "MODE_UNRECOGNIZED", notes
    )
    status = _first_match(_STATUS_PATTERN, text)
    status = status.strip().upper() if status else None
    evidence_type = _extract_enum(
        _EVIDENCE_TYPE_PATTERN,
        text,
        {item.value for item in EvidenceType},
        "EVIDENCE_TYPE_UNRECOGNIZED",
        notes,
    )
    time_from, time_to = _extract_time_range(text)

    history_keyword = bool(_HISTORY_KEYWORDS.search(text))
    navigation_only = bool(_NAVIGATION_KEYWORDS.search(text)) and not history_keyword

    relevant = bool(explicit_identifier or history_keyword)
    if not relevant:
        reason = "NAVIGATION_QUESTION" if navigation_only else "NOT_HISTORY_RELEVANT"
        return AdvisorQuestionPlan(False, reason, None, tuple(notes))

    query = KnowledgeHistoryQuery(
        cycle_id=identifiers["cycle_id"],
        trace_id=identifiers["trace_id"],
        evidence_id=identifiers["evidence_id"],
        stage=stage,
        symbol=symbol,
        mode=mode,
        time_from=time_from,
        time_to=time_to,
        status=status,
        evidence_type=evidence_type,
        limit=ADVISOR_QUERY_DEFAULT_LIMIT,
        cursor=None,
    )
    if not query.requested_filters():
        notes.append("UNSCOPED_HISTORY_QUERY")
    return AdvisorQuestionPlan(True, "HISTORY_RELEVANT", query, tuple(notes))


def _sanitize_record(value: Any) -> dict:
    if not isinstance(value, Mapping):
        return {}
    cleaned, _ = sanitize_summary(dict(value))
    return cleaned


def _bounded_item(item: Mapping[str, Any]) -> dict:
    provenance = item.get("provenance") if isinstance(item.get("provenance"), Mapping) else {}
    small_summary = _sanitize_record(
        {
            "status": item.get("status"),
            "evidence_type": item.get("evidence_type"),
            "source_reference": item.get("source_reference"),
        }
    )
    return {
        "source": item.get("source"),
        "event_key": item.get("event_key"),
        "evidence_id": item.get("evidence_id"),
        "cycle_id": item.get("cycle_id"),
        "trace_id": item.get("trace_id"),
        "stage": item.get("stage"),
        "stage_name": item.get("stage_name"),
        "status": item.get("status"),
        "evidence_type": item.get("evidence_type"),
        "symbol": item.get("symbol"),
        "mode": item.get("mode"),
        "captured_at": item.get("captured_at"),
        "redacted": bool(provenance.get("redacted")),
        "summary": small_summary,
    }


def _derive_uncertainty(result: Mapping[str, Any]) -> str:
    sources = result.get("sources") or []
    states = {str(report.get("availability")) for report in sources if isinstance(report, Mapping)}
    freshness = result.get("freshness") or {}
    overall_freshness = str(freshness.get("overall") or "UNKNOWN")
    if result.get("partial_result") or "ERROR" in states or "NOT_AVAILABLE" in states:
        return "HIGH"
    if (
        overall_freshness in {"STALE", "UNKNOWN"}
        or result.get("unsupported_filters")
        or int(result.get("corruption_count") or 0) > 0
    ):
        return "MEDIUM"
    return "LOW"


def assemble_knowledge_history_context(
    result: Mapping[str, Any],
    plan: AdvisorQuestionPlan,
    *,
    max_items: int = ADVISOR_CONTEXT_MAX_ITEMS,
    max_characters: int = ADVISOR_CONTEXT_MAX_CHARACTERS,
    requested_limit: Optional[int] = None,
) -> dict:
    """Convert one shared query result into a bounded, sanitized context block.

    Raw trace records, oversized payloads, secrets, credentials and private
    environment values are never included.  When evidence is dropped to respect
    the size budget, ``truncated`` is set to true.
    """

    if not isinstance(result, Mapping):
        result = {}

    raw_items = result.get("items") or []
    items = [
        _bounded_item(item)
        for item in raw_items[: max(0, int(max_items))]
        if isinstance(item, Mapping)
    ]
    provenance = [
        _sanitize_record(entry)
        for entry in (result.get("provenance") or [])
        if isinstance(entry, Mapping)
    ]
    sources = [
        {
            "source": report.get("source"),
            "availability": report.get("availability"),
            "items_returned": report.get("items_returned"),
            "corruption_count": report.get("corruption_count"),
            "bounded": report.get("bounded"),
            "read_method": report.get("read_method"),
        }
        for report in (result.get("sources") or [])
        if isinstance(report, Mapping)
    ]
    query_scope = result.get("query") if isinstance(result.get("query"), Mapping) else {}
    query_scope = dict(query_scope)
    query_scope["cursor"] = None  # a caller cursor is never accepted or returned

    context = {
        "knowledge_history_used": True,
        "query_summary": {
            "filters": query_scope,
            "requested_limit": (
                ADVISOR_QUERY_DEFAULT_LIMIT
                if requested_limit is None
                else int(requested_limit)
            ),
            "resolved_limit": result.get("limit"),
            "returned_count": result.get("returned_count", len(items)),
            "has_more": bool(result.get("has_more")),
            "notes": list(plan.notes),
        },
        "returned_count": result.get("returned_count", len(items)),
        "items": items,
        "sources": sources,
        "provenance": provenance,
        "freshness": result.get("freshness") or {},
        "availability": result.get("availability") or {},
        "warnings": list(result.get("warnings") or []),
        "partial_result": bool(result.get("partial_result")),
        "corruption_count": int(result.get("corruption_count") or 0),
        "unsupported_filters": list(result.get("unsupported_filters") or []),
        "uncertainty": _derive_uncertainty(result),
        "fallback": False,
        "truncated": len(raw_items) > len(items),
    }
    context = _enforce_size_budget(context, max_characters=max_characters)
    return context


def _render_size(context: Mapping[str, Any]) -> int:
    return len(json.dumps(context, ensure_ascii=True, default=str).encode("utf-8"))


def _enforce_size_budget(context: dict, *, max_characters: int) -> dict:
    cap = max(512, int(max_characters))
    if _render_size(context) <= cap:
        return context
    context["truncated"] = True
    for key in ("items", "provenance", "warnings"):
        while context.get(key) and _render_size(context) > cap:
            context[key] = list(context[key])[:-1]
    return context


def _not_used_metadata(reason: str, notes: Tuple[str, ...] = ()) -> dict:
    return {
        "knowledge_history_used": False,
        "query_summary": {
            "filters": None,
            "requested_limit": ADVISOR_QUERY_DEFAULT_LIMIT,
            "resolved_limit": None,
            "returned_count": 0,
            "has_more": False,
            "notes": list(notes),
        },
        "returned_count": 0,
        "items": [],
        "sources": [],
        "provenance": [],
        "freshness": {},
        "availability": {},
        "warnings": [],
        "partial_result": False,
        "corruption_count": 0,
        "unsupported_filters": [],
        "uncertainty": "UNKNOWN",
        "fallback": False,
        "truncated": False,
        "reason": reason,
    }


def _fallback_metadata(reason: str, notes: Tuple[str, ...] = ()) -> dict:
    metadata = _not_used_metadata(reason, notes)
    metadata["fallback"] = True
    metadata["uncertainty"] = "HIGH"
    return metadata


class AdvisorKnowledgeHistoryConsumer:
    """Read-only request-time bridge to the shared knowledge/history service.

    Construction is side-effect free: no query is issued and no source file is
    read.  The shared service is resolved lazily on the first real query, so a
    disabled consumer never constructs or touches the shared query layer.
    """

    def __init__(
        self,
        facade: Optional[KnowledgeHistoryQueryFacade] = None,
        *,
        environ: Optional[Mapping[str, str]] = None,
    ):
        self._facade = facade
        self._environ = environ

    @property
    def enabled(self) -> bool:
        return advisor_knowledge_history_enabled(self._environ)

    def _resolve_facade(self) -> KnowledgeHistoryQueryFacade:
        if self._facade is None:
            self._facade = shared_knowledge_history_facade()
        return self._facade

    def metadata_for_message(self, message: Any) -> Optional[dict]:
        """Return Advisor response metadata, or ``None`` when the flag is OFF.

        A ``None`` return means the existing Advisor path is untouched (the
        response gains no knowledge-history field at all).
        """

        if not self.enabled:
            return None
        try:
            plan = classify_advisor_question(message)
        except Exception:  # noqa: BLE001 - planning must never break the answer
            return _fallback_metadata("PLANNING_FAILED")
        if not plan.relevant or plan.query is None:
            return _not_used_metadata(plan.reason, plan.notes)
        try:
            result = self._resolve_facade().query(plan.query)
        except Exception as exc:  # noqa: BLE001 - one failed query must not break the answer
            return _fallback_metadata("QUERY_FAILED", (type(exc).__name__,))
        try:
            return assemble_knowledge_history_context(result, plan)
        except Exception:  # noqa: BLE001 - assembly must never break the answer
            return _fallback_metadata("CONTEXT_ASSEMBLY_FAILED")
