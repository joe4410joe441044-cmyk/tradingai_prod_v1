"""Read an already published owner snapshot into the existing context chain.

This module does not construct a BotManager, import the BotManager module, or
call a runtime, account, money-management, supervisor, or exchange reader.
``generated_at`` is the pack stamp. It is passed to the position reader only
as that reader's age clock. Canonical ``observedAt`` still comes from a
producer field inside the stored mapping.
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Mapping

from backend.context.injection_boundary import inject_verified_runtime_snapshots
from backend.context.runtime_collector import RuntimeCollection
from backend.context.runtime_projection import parse_producer_time
from backend.context.snapshot_copy import copy_injection_inputs, copy_json_snapshot

OWNER_MODULE = "backend.bot_manager.bot_manager"
OWNER_SCHEMA = "tradingai-owner-snapshot/v1"
_BLOCKED = (
    "real_account",
    "execution_control",
    "money_management",
    "supervisor",
)
_PAPER = "PAPER"
_CYCLE_CLOCKS = (
    ("strategyOutput", "strategy", "entryReadiness", "evaluatedAt"),
    ("strategyOutput", "strategy", "timestamp"),
    ("strategyOutput", "strategy", "sourceUpdatedAt"),
)


def unavailable_owner_document() -> dict[str, Any]:
    """Same initial document as the owner publisher. It invents no mode."""

    return {
        "schemaVersion": OWNER_SCHEMA,
        "source": "bot_manager_publication",
        "owner": "BotManager",
        "availability": "UNAVAILABLE",
        "publishedAt": None,
        "observedAt": None,
        "producerObservedAt": None,
        "revision": 0,
        "errorState": "NOT_PUBLISHED",
        "unavailable": list(_BLOCKED),
        "payload": {},
    }


def existing_owner_from_process() -> Any:
    """Return the process owner only when its module is already loaded.

    A missing module stays missing. This function does not import it, because
    importing that module reads a dotenv file. It also does not call the
    constructor helper.
    """

    module = sys.modules.get(OWNER_MODULE)
    if module is None:
        return None
    getter = getattr(module, "get_existing_bot_manager", None)
    if not callable(getter):
        return None
    try:
        return getter()
    except Exception:
        return None


def copied_owner_export(owner: Any) -> dict[str, Any]:
    """Copy ``export_context_snapshot`` or return an unavailable document.

    Exceptions are discarded. The returned value is JSON data, not the owner's
    live mapping.
    """

    export = getattr(owner, "export_context_snapshot", None)
    if not callable(export):
        return unavailable_owner_document()
    try:
        copied = copy_json_snapshot(export())
    except Exception:
        return unavailable_owner_document()
    if not _document_ok(copied):
        return unavailable_owner_document()
    return copied


def collection_from_owner_document(
    document: Mapping[str, Any],
    generated_at: datetime,
) -> RuntimeCollection:
    """Run the existing copy and injection chain on one owner document."""

    copied = copy_json_snapshot(document)
    if not _document_ok(copied):
        copied = unavailable_owner_document()
    prepared = copy_injection_inputs(**_injection_kwargs(copied, generated_at))
    result = inject_verified_runtime_snapshots(
        generated_at=generated_at,
        **prepared.values,
    )
    return result.collection


def _document_ok(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("schemaVersion") != OWNER_SCHEMA:
        return False
    if value.get("availability") not in {"UNAVAILABLE", "READY"}:
        return False
    payload = value.get("payload")
    return isinstance(payload, dict)


def _injection_kwargs(
    document: Mapping[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    payload = document.get("payload")
    if not isinstance(payload, dict):
        return {}
    values: dict[str, Any] = {}
    account = payload.get("position_account")
    if payload.get("position_mode") == _PAPER and isinstance(account, dict):
        values["position_account"] = account
        values["position_mode"] = _PAPER
        values["position_observed_at"] = generated_at
    runtime = payload.get("trading_cycle_runtime_result")
    if isinstance(runtime, dict):
        values["trading_cycle_runtime_result"] = runtime
        producer = _cycle_producer_time(runtime)
        if producer is not None:
            values["cycle_evaluated_at"] = producer
    return values


def _cycle_producer_time(runtime: Mapping[str, Any]) -> datetime | None:
    for path in _CYCLE_CLOCKS:
        found = _nested(runtime, path)
        parsed = parse_producer_time(found)
        if parsed is not None:
            return parsed
    return None


def _nested(value: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    return current
