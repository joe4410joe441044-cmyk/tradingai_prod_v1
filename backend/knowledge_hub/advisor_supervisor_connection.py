"""Opt-in read-only connection from Advisor and Supervisor to the Knowledge Hub.

Both roles read the same store through :mod:`backend.knowledge_hub.knowledge_access`.
The connection is default OFF, requires an authenticated operator identity, and
never raises into the existing answer path. A missing, corrupt, timed-out, or
unavailable store leaves the caller's input unchanged.

Knowledge text stays a separate untrusted data block. It is not merged into the
BB context, not promoted to a system instruction, not dispatched as a command,
and never changes trading authority.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .knowledge_access import (
    query_advisor_knowledge,
    query_supervisor_knowledge,
)
from .reader import ReaderFilters, ReaderLimits, RequestContext


ADVISOR_ENABLED_ENV = "KNOWLEDGE_HUB_ADVISOR_ENABLED"
SUPERVISOR_ENABLED_ENV = "KNOWLEDGE_HUB_SUPERVISOR_ENABLED"
STORE_PATH_ENV = "KNOWLEDGE_HUB_STORE_PATH"

_TRUTHY = {"1", "true", "yes", "on"}
_USABLE_STATUS = {"OK", "EMPTY"}
_TRUTH_LABEL = "truthKind=UNTRUSTED_HISTORICAL"
_BOUNDARY_START = "BEGIN_UNTRUSTED_KNOWLEDGE\n"


@dataclass(frozen=True)
class KnowledgeConnection:
    """The result of one connection attempt.

    ``attached`` is false whenever the caller must keep its original input.
    """

    attached: bool
    status: str
    role: str
    block: str | None = None
    attachment: Mapping[str, Any] | None = None


def _flag(name: str, environ: Optional[Mapping[str, str]]) -> bool:
    env = os.environ if environ is None else environ
    raw = str(env.get(name, "")).strip().lower()
    return raw in _TRUTHY


def advisor_knowledge_enabled(
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return whether the Advisor connection is enabled. Default OFF."""

    return _flag(ADVISOR_ENABLED_ENV, environ)


def supervisor_knowledge_enabled(
    environ: Optional[Mapping[str, str]] = None,
) -> bool:
    """Return whether the Supervisor connection is enabled. Default OFF."""

    return _flag(SUPERVISOR_ENABLED_ENV, environ)


def knowledge_store_path(
    environ: Optional[Mapping[str, str]] = None,
) -> str | None:
    """Return the explicit store path. There is no production default."""

    env = os.environ if environ is None else environ
    value = str(env.get(STORE_PATH_ENV, "")).strip()
    return value or None


def operator_request_context(identity: str | None) -> RequestContext | None:
    """Build the trusted caller scope. No identity means no connection."""

    if not isinstance(identity, str):
        return None
    token = identity.strip()
    if not token or token != identity:
        return None
    return RequestContext(caller_scope="OPERATOR", caller_id=identity)


def advisor_knowledge_block(
    question: str,
    *,
    store_path: str,
    identity: str | None,
    bb_context: Mapping[str, Any] | None = None,
    filters: ReaderFilters | None = None,
    limits: ReaderLimits | None = None,
    environ: Optional[Mapping[str, str]] = None,
    clock: Any = None,
) -> KnowledgeConnection:
    """Return a fenced knowledge block for the Advisor, or ``attached=False``."""

    if not advisor_knowledge_enabled(environ):
        return KnowledgeConnection(False, "DISABLED", "ADVISOR")
    request = operator_request_context(identity)
    if request is None:
        return KnowledgeConnection(False, "UNAUTHENTICATED", "ADVISOR")
    if not isinstance(store_path, str) or not store_path.strip():
        return KnowledgeConnection(False, "NOT_CONFIGURED", "ADVISOR")
    try:
        attachment = query_advisor_knowledge(
            question,
            store_path=store_path,
            request=request,
            bb_context=bb_context,
            filters=filters,
            limits=limits,
            clock=clock,
        )
    except Exception:
        return KnowledgeConnection(False, "INTERNAL_ERROR", "ADVISOR")
    return _connection("ADVISOR", attachment)


def supervisor_knowledge_block(
    question: str,
    *,
    store_path: str,
    identity: str | None,
    bb_context: Mapping[str, Any] | None = None,
    filters: ReaderFilters | None = None,
    limits: ReaderLimits | None = None,
    environ: Optional[Mapping[str, str]] = None,
    clock: Any = None,
) -> KnowledgeConnection:
    """Return a fenced knowledge block for the Supervisor, or ``attached=False``."""

    if not supervisor_knowledge_enabled(environ):
        return KnowledgeConnection(False, "DISABLED", "SUPERVISOR")
    request = operator_request_context(identity)
    if request is None:
        return KnowledgeConnection(False, "UNAUTHENTICATED", "SUPERVISOR")
    if not isinstance(store_path, str) or not store_path.strip():
        return KnowledgeConnection(False, "NOT_CONFIGURED", "SUPERVISOR")
    try:
        attachment = query_supervisor_knowledge(
            question,
            store_path=store_path,
            request=request,
            bb_context=bb_context,
            filters=filters,
            limits=limits,
            clock=clock,
        )
    except Exception:
        return KnowledgeConnection(False, "INTERNAL_ERROR", "SUPERVISOR")
    return _connection("SUPERVISOR", attachment)


def attach_advisor_knowledge(
    service_input: Any,
    *,
    question: str,
    identity: str | None,
    store_path: str | None = None,
    bb_context: Mapping[str, Any] | None = None,
    filters: ReaderFilters | None = None,
    limits: ReaderLimits | None = None,
    environ: Optional[Mapping[str, str]] = None,
    clock: Any = None,
) -> Any:
    """Return ``service_input`` with a separate knowledge block when usable.

    The original object is returned unchanged on any failure. The existing
    canonical/BB context field is never edited.
    """

    path = store_path or knowledge_store_path(environ)
    if not path:
        return service_input
    connection = advisor_knowledge_block(
        question,
        store_path=path,
        identity=identity,
        bb_context=bb_context,
        filters=filters,
        limits=limits,
        environ=environ,
        clock=clock,
    )
    if not connection.attached or connection.block is None:
        return service_input
    try:
        return service_input.model_copy(
            update={"knowledgeContextBlock": connection.block}
        )
    except Exception:
        return service_input


def attach_supervisor_knowledge(
    canonical_context: Mapping[str, Any] | None,
    *,
    question: str,
    identity: str | None,
    store_path: str | None = None,
    bb_context: Mapping[str, Any] | None = None,
    filters: ReaderFilters | None = None,
    limits: ReaderLimits | None = None,
    environ: Optional[Mapping[str, str]] = None,
    clock: Any = None,
) -> Mapping[str, Any] | None:
    """Return the BB context plus a separate ``knowledgeContext`` entry.

    The BB mapping itself is copied, not edited. Any failure returns the
    original object so the Supervisor answer path is unchanged.
    """

    path = store_path or knowledge_store_path(environ)
    if not path:
        return canonical_context
    connection = supervisor_knowledge_block(
        question,
        store_path=path,
        identity=identity,
        bb_context=bb_context or canonical_context,
        filters=filters,
        limits=limits,
        environ=environ,
        clock=clock,
    )
    if not connection.attached or connection.block is None:
        return canonical_context
    try:
        merged = dict(canonical_context or {})
        merged["knowledgeContext"] = {
            "classification": "UNTRUSTED_KNOWLEDGE",
            "boundaryStart": "BEGIN_UNTRUSTED_KNOWLEDGE",
            "boundaryEnd": "END_UNTRUSTED_KNOWLEDGE",
            "truthKind": "UNTRUSTED_HISTORICAL",
            "authority": "NONE",
            "tradingControl": "FORBIDDEN",
            "systemInstruction": False,
            "status": connection.status,
            "block": connection.block,
        }
        return merged
    except Exception:
        return canonical_context


def _connection(role: str, attachment: Mapping[str, Any]) -> KnowledgeConnection:
    status = str(attachment.get("knowledge_status") or "INTERNAL_ERROR")
    if status not in _USABLE_STATUS:
        return KnowledgeConnection(False, status, role, attachment=attachment)
    block = attachment.get("untrusted_context")
    if not isinstance(block, str) or not block.strip():
        return KnowledgeConnection(False, status, role, attachment=attachment)
    return KnowledgeConnection(
        True,
        status,
        role,
        block=_label_block(block),
        attachment=attachment,
    )


def _label_block(block: str) -> str:
    if _TRUTH_LABEL in block:
        return block
    if block.startswith(_BOUNDARY_START):
        return _BOUNDARY_START + _TRUTH_LABEL + "\n" + block[len(_BOUNDARY_START) :]
    return _TRUTH_LABEL + "\n" + block


__all__ = [
    "ADVISOR_ENABLED_ENV",
    "SUPERVISOR_ENABLED_ENV",
    "STORE_PATH_ENV",
    "KnowledgeConnection",
    "advisor_knowledge_block",
    "advisor_knowledge_enabled",
    "attach_advisor_knowledge",
    "attach_supervisor_knowledge",
    "knowledge_store_path",
    "operator_request_context",
    "supervisor_knowledge_block",
    "supervisor_knowledge_enabled",
]
