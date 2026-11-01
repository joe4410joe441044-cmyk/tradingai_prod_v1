"""Advisor and Supervisor access to the read-only knowledge reader.

Both roles use this module. The reader is optional: a missing store returns
an explicit status and leaves the BB context object untouched. Knowledge
text is fenced as untrusted data and is never a trading instruction.
"""

from __future__ import annotations

from typing import Any, Mapping

from .reader import ReaderFilters, ReaderLimits, RequestContext, open_reader


FENCE_START = "BEGIN_UNTRUSTED_KNOWLEDGE"
FENCE_END = "END_UNTRUSTED_KNOWLEDGE"
MAX_CONTEXT_CHARS = 4_000


def query_advisor_knowledge(
    question: str,
    *,
    store_path: str,
    request: RequestContext,
    bb_context: Mapping[str, Any] | None = None,
    filters: ReaderFilters | None = None,
    limits: ReaderLimits | None = None,
    clock=None,
) -> dict[str, Any]:
    """Analysis context. This does not call the production Advisor."""

    return _query(
        question,
        role="ADVISOR",
        purpose="ANALYSIS",
        store_path=store_path,
        request=request,
        bb_context=bb_context,
        filters=filters,
        limits=limits,
        clock=clock,
    )


def query_supervisor_knowledge(
    question: str,
    *,
    store_path: str,
    request: RequestContext,
    bb_context: Mapping[str, Any] | None = None,
    filters: ReaderFilters | None = None,
    limits: ReaderLimits | None = None,
    clock=None,
) -> dict[str, Any]:
    """Audit context. This does not call the production Supervisor."""

    return _query(
        question,
        role="SUPERVISOR",
        purpose="AUDIT",
        store_path=store_path,
        request=request,
        bb_context=bb_context,
        filters=filters,
        limits=limits,
        clock=clock,
    )


def executed_commands(attachment: Mapping[str, Any]) -> tuple[str, ...]:
    """Knowledge text is not dispatched. The command list stays empty."""

    del attachment
    return ()


def _query(
    question: str,
    *,
    role: str,
    purpose: str,
    store_path: str,
    request: RequestContext,
    bb_context: Mapping[str, Any] | None,
    filters: ReaderFilters | None,
    limits: ReaderLimits | None,
    clock,
) -> dict[str, Any]:
    reader, failure = open_reader(store_path, limits)
    if reader is None:
        return _attachment(
            role=role,
            purpose=purpose,
            bb_context=bb_context,
            status=failure or "NOT_AVAILABLE",
            response=None,
            question=question,
        )
    try:
        response = reader.search(
            question,
            request=request,
            filters=filters,
            clock=clock,
        )
    except Exception:
        response = None
        status = "INTERNAL_ERROR"
    else:
        status = response.status
    finally:
        reader.close()
    return _attachment(
        role=role,
        purpose=purpose,
        bb_context=bb_context,
        status=status,
        response=response,
        question=question,
    )


def _attachment(
    *,
    role: str,
    purpose: str,
    bb_context: Mapping[str, Any] | None,
    status: str,
    response,
    question: str,
) -> dict[str, Any]:
    body = _render(response, question)
    truncated = len(body) > MAX_CONTEXT_CHARS
    if truncated:
        body = body[:MAX_CONTEXT_CHARS]
    return {
        "role": role,
        "purpose": purpose,
        "authority": "NONE",
        "trading_control": "FORBIDDEN",
        "bb_context": bb_context,
        "bb_context_unchanged": True,
        "knowledge_status": status,
        "knowledge": None if response is None else response.to_dict(),
        "untrusted_context": body,
        "context_truncated": truncated,
        "system_instruction": False,
    }


def _render(response, question: str) -> str:
    lines = [FENCE_START, "UNTRUSTED_CONTEXT", f"question={question}"]
    if response is None:
        lines.append("status=INTERNAL_ERROR")
    else:
        lines.append(f"status={response.status}")
        lines.append(f"error_code={response.error_code}")
        for hit in response.results:
            lines.append(
                " | ".join(
                    (
                        hit.record_id,
                        hit.source_type,
                        hit.truth_kind,
                        hit.freshness_state,
                        hit.verification_state,
                        hit.snippet.replace("\n", " "),
                    )
                )
            )
    lines.append(FENCE_END)
    return "\n".join(lines)
