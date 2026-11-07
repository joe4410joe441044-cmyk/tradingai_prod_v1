"""Non-refreshing copy of caller-owned snapshot data.

This module does not read a live BotManager, supervisor, account runtime, or
exchange. A copy timestamp is not an observation time. Live runtime fields
stay ``LIVE_SOURCE_NOT_SAFE`` until a runtime owner provides an already
consistent snapshot. This module does not take that owner's lock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from typing import Any, Mapping

from backend.supervisor.snapshot_sources import SnapshotFreshnessPolicy

from .injection_contract import (
    MAX_BYTES,
    MAX_COLLECTION,
    MAX_DEPTH,
    MAX_NODES,
    MAX_STRING,
    REJECTED,
    SnapshotRejected,
)
from .runtime_reader_contract import AdapterFailure

LIVE_SOURCE_NOT_SAFE = "LIVE_SOURCE_NOT_SAFE"
OWNER_PROVIDED_COPY_REQUIRED = "OWNER_PROVIDED_COPY_REQUIRED"
LOCK_NOT_TAKEN = "CONTEXT_DOES_NOT_TAKE_RUNTIME_LOCKS"


@dataclass(frozen=True)
class PreparedSnapshotCopy:
    """Independent snapshot kwargs plus slot failures.

    ``values`` never contains a live runtime object. ``consistency`` records
    that this copy does not prove a stable read of a running producer.
    """

    values: dict[str, Any]
    failures: tuple[AdapterFailure, ...]
    consistency: str = LIVE_SOURCE_NOT_SAFE
    lock_requirement: str = OWNER_PROVIDED_COPY_REQUIRED
    lock_action: str = LOCK_NOT_TAKEN


def copy_json_snapshot(value: Any) -> Any:
    """Return an independent JSON-like copy, or raise ``SnapshotRejected``."""

    seen: set[int] = set()
    budget = {"nodes": 0}
    copied = _copy(value, budget, 0, seen)
    try:
        encoded = json.dumps(copied, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError):
        raise SnapshotRejected from None
    if len(encoded.encode("utf-8")) > MAX_BYTES:
        raise SnapshotRejected
    return copied


def copy_injection_inputs(
    *,
    position_account: Mapping[str, Any] | None = None,
    position_mode: str | None = None,
    position_observed_at: datetime | None = None,
    position_symbol: str | None = None,
    position_price: float | None = None,
    position_observation: Mapping[str, Any] | None = None,
    trading_decision: Mapping[str, Any] | None = None,
    trading_cycle_context: Mapping[str, Any] | None = None,
    trading_cycle_runtime_result: Mapping[str, Any] | None = None,
    cycle_evaluated_at: datetime | None = None,
    supervisor_bot_status: Mapping[str, Any] | None = None,
    supervisor_governance_status: Mapping[str, Any] | None = None,
    supervisor_money_management_status: Mapping[str, Any] | None = None,
    supervisor_health_payload: Mapping[str, Any] | None = None,
    supervisor_captured_at: datetime | None = None,
    supervisor_freshness_policy: Any = None,
    account_projection: Mapping[str, Any] | None = None,
    mm_projection: Mapping[str, Any] | None = None,
    execution_projection: Mapping[str, Any] | None = None,
) -> PreparedSnapshotCopy:
    """Copy injected mappings. Clocks pass through only when already aware.

    Nothing is read from a running runtime. Missing producer times stay missing.
    """

    failures: list[AdapterFailure] = []
    values: dict[str, Any] = {}
    _mapping_into(values, failures, "position", "position_account", position_account)
    _mapping_into(values, failures, "position", "position_observation", position_observation)
    if position_mode is not None:
        values["position_mode"] = position_mode
    if position_symbol is not None:
        values["position_symbol"] = position_symbol
    if position_price is not None:
        values["position_price"] = position_price
    _clock_into(values, failures, "position", "position_observed_at", position_observed_at)
    _mapping_into(values, failures, "trading_cycle", "trading_decision", trading_decision)
    _mapping_into(values, failures, "trading_cycle", "trading_cycle_context", trading_cycle_context)
    _mapping_into(
        values,
        failures,
        "trading_cycle",
        "trading_cycle_runtime_result",
        trading_cycle_runtime_result,
    )
    _clock_into(values, failures, "trading_cycle", "cycle_evaluated_at", cycle_evaluated_at)
    _mapping_into(values, failures, "supervisor", "supervisor_bot_status", supervisor_bot_status)
    _mapping_into(
        values, failures, "supervisor", "supervisor_governance_status", supervisor_governance_status
    )
    _mapping_into(
        values,
        failures,
        "supervisor",
        "supervisor_money_management_status",
        supervisor_money_management_status,
    )
    _mapping_into(values, failures, "supervisor", "supervisor_health_payload", supervisor_health_payload)
    _clock_into(values, failures, "supervisor", "supervisor_captured_at", supervisor_captured_at)
    if supervisor_freshness_policy is not None:
        if isinstance(supervisor_freshness_policy, SnapshotFreshnessPolicy):
            values["supervisor_freshness_policy"] = supervisor_freshness_policy
        else:
            failures.append(AdapterFailure(source="supervisor", category=REJECTED))
    _mapping_into(values, failures, "account", "account_projection", account_projection)
    _mapping_into(values, failures, "mm", "mm_projection", mm_projection)
    if execution_projection is not None:
        try:
            copied = copy_json_snapshot(execution_projection)
        except SnapshotRejected:
            failures.append(AdapterFailure(source="execution_control", category=REJECTED))
        else:
            if isinstance(copied, dict):
                for name in ("realOrderAllowed", "real_order_allowed"):
                    if name in copied and not isinstance(copied[name], bool):
                        copied.pop(name)
            values["execution_projection"] = copied
    return PreparedSnapshotCopy(values=values, failures=tuple(failures))


def _mapping_into(values, failures, source: str, key: str, value) -> None:
    if value is None:
        return
    try:
        values[key] = copy_json_snapshot(value)
    except SnapshotRejected:
        failures.append(AdapterFailure(source=source, category=REJECTED))


def _clock_into(values, failures, source: str, key: str, value) -> None:
    if value is None:
        return
    if isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None:
        values[key] = value
        return
    failures.append(AdapterFailure(source=source, category=REJECTED))


def _copy(value: Any, budget: dict[str, int], depth: int, seen: set[int]) -> Any:
    budget["nodes"] += 1
    if budget["nodes"] > MAX_NODES or depth > MAX_DEPTH:
        raise SnapshotRejected
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        if abs(value) > 10**18:
            raise SnapshotRejected
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SnapshotRejected
        return value
    if isinstance(value, str):
        if len(value) > MAX_STRING:
            raise SnapshotRejected
        return value
    if isinstance(value, (Mapping, list)):
        marker = id(value)
        if marker in seen:
            raise SnapshotRejected
        seen.add(marker)
        try:
            if isinstance(value, Mapping):
                if len(value) > MAX_COLLECTION:
                    raise SnapshotRejected
                copied: dict[str, Any] = {}
                for key, item in value.items():
                    if not isinstance(key, str) or len(key) > MAX_STRING:
                        raise SnapshotRejected
                    copied[key] = _copy(item, budget, depth + 1, seen)
                return copied
            if len(value) > MAX_COLLECTION:
                raise SnapshotRejected
            return [_copy(item, budget, depth + 1, seen) for item in value]
        finally:
            seen.remove(marker)
    raise SnapshotRejected
