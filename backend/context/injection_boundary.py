"""Explicit snapshot injection into the verified runtime readers.

Callers pass data they already hold. This module does not fetch a BotManager,
supervisor, account runtime, or exchange. ``generated_at`` is the pack stamp
and is never used as an observation time.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Mapping

from backend.context.runtime_projection import parse_producer_time
from backend.supervisor.snapshot_sources import SnapshotFreshnessPolicy

from .injection_contract import (
    MAX_CYCLE_ID,
    REJECTED,
    SnapshotRejected,
)
from .snapshot_copy import copy_json_snapshot
from .runtime_reader_adapter import (
    VerifiedReaderResult,
    collect_verified_runtime_context,
)
from .runtime_reader_contract import RUNTIME_INSTANCE_NOT_INJECTED, AdapterFailure

_MODES = frozenset({"PAPER", "LIVE"})
_TIME_KEYS = ("timestamp", "evaluatedAt", "sourceUpdatedAt", "diagnosticsGeneratedAt")


def inject_verified_runtime_snapshots(
    *,
    generated_at: datetime,
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
) -> VerifiedReaderResult:
    """Copy injected snapshots and pass the valid ones to the BB-4D adapter."""

    if not _aware(generated_at):
        raise ValueError("generated_at must be timezone-aware")
    failures: list[AdapterFailure] = []
    supplied = False

    position_kwargs, position_supplied = _position_slot(
        failures,
        account=position_account,
        mode=position_mode,
        observed_at=position_observed_at,
        symbol=position_symbol,
        price=position_price,
        observation=position_observation,
    )
    cycle_kwargs, cycle_supplied = _cycle_slot(
        failures,
        decision=trading_decision,
        context=trading_cycle_context,
        runtime_result=trading_cycle_runtime_result,
        evaluated_at=cycle_evaluated_at,
    )
    supervisor_kwargs, supervisor_supplied = _supervisor_slot(
        failures,
        bot_status=supervisor_bot_status,
        governance_status=supervisor_governance_status,
        money_management_status=supervisor_money_management_status,
        health_payload=supervisor_health_payload,
        captured_at=supervisor_captured_at,
        freshness_policy=supervisor_freshness_policy,
    )
    account_kwargs, account_supplied = _mapping_slot(
        failures, "account", "account_projection", account_projection
    )
    mm_kwargs, mm_supplied = _mapping_slot(
        failures, "mm", "mm_projection", mm_projection
    )
    execution_kwargs, execution_supplied = _execution_slot(failures, execution_projection)
    supplied = any(
        (
            position_supplied,
            cycle_supplied,
            supervisor_supplied,
            account_supplied,
            mm_supplied,
            execution_supplied,
        )
    )
    result = collect_verified_runtime_context(
        generated_at=generated_at.astimezone(timezone.utc),
        **position_kwargs,
        **cycle_kwargs,
        **supervisor_kwargs,
        **account_kwargs,
        **mm_kwargs,
        **execution_kwargs,
    )
    adapter_failures = [
        item
        for item in result.adapter_failures
        if not (supplied and item.category == RUNTIME_INSTANCE_NOT_INJECTED)
    ]
    return VerifiedReaderResult(
        collection=result.collection,
        connected_readers=result.connected_readers,
        skipped_readers=result.skipped_readers,
        adapter_failures=tuple(adapter_failures) + tuple(failures),
        runtime_instance_injected=supplied or result.runtime_instance_injected,
    )


def _position_slot(failures, **raw) -> tuple[dict[str, Any], bool]:
    present = any(value is not None for value in raw.values())
    if not present:
        return {}, False
    if raw["mode"] not in _MODES or not _aware(raw["observed_at"]):
        failures.append(AdapterFailure(source="position", category=REJECTED))
        return {}, True
    if raw["symbol"] is not None and not _symbol(raw["symbol"]):
        failures.append(AdapterFailure(source="position", category=REJECTED))
        return {}, True
    if raw["price"] is not None and (
        isinstance(raw["price"], bool) or not isinstance(raw["price"], (int, float))
        or not math.isfinite(raw["price"])
    ):
        failures.append(AdapterFailure(source="position", category=REJECTED))
        return {}, True
    try:
        account = _snapshot(raw["account"])
        observation = None if raw["observation"] is None else _snapshot(raw["observation"])
    except SnapshotRejected:
        failures.append(AdapterFailure(source="position", category=REJECTED))
        return {}, True
    return {
        "position_account": account,
        "position_mode": raw["mode"],
        "position_observed_at": raw["observed_at"],
        "position_symbol": raw["symbol"],
        "position_price": raw["price"],
        "position_observation": observation,
    }, True


def _cycle_slot(failures, *, decision, context, runtime_result, evaluated_at):
    supplied = (decision, context, runtime_result, evaluated_at)
    if all(item is None for item in supplied):
        return {}, False
    if evaluated_at is not None and not _aware(evaluated_at):
        failures.append(AdapterFailure(source="trading_cycle", category=REJECTED))
        return {}, True
    try:
        copied = {
            "trading_decision": None if decision is None else _snapshot(decision),
            "trading_cycle_context": None if context is None else _snapshot(context),
            "trading_cycle_runtime_result": (
                None if runtime_result is None else _snapshot(runtime_result)
            ),
        }
    except SnapshotRejected:
        failures.append(AdapterFailure(source="trading_cycle", category=REJECTED))
        return {}, True
    if not _cycle_ids_ok(copied["trading_decision"], copied["trading_cycle_runtime_result"]):
        failures.append(AdapterFailure(source="trading_cycle", category=REJECTED))
        return {}, True
    if _ids_match(copied["trading_decision"], copied["trading_cycle_runtime_result"]) and not (
        _aware(evaluated_at)
        or _mapping_has_time(copied["trading_decision"])
        or _mapping_has_time(copied["trading_cycle_context"])
        or _mapping_has_time(_strategy(copied["trading_cycle_runtime_result"]))
    ):
        failures.append(AdapterFailure(source="trading_cycle", category=REJECTED))
        return {}, True
    if evaluated_at is not None:
        copied["cycle_evaluated_at"] = evaluated_at
    return copied, True


def _supervisor_slot(failures, **raw) -> tuple[dict[str, Any], bool]:
    documents = (
        raw["bot_status"],
        raw["governance_status"],
        raw["money_management_status"],
        raw["health_payload"],
    )
    if all(item is None for item in documents) and raw["captured_at"] is None and raw["freshness_policy"] is None:
        return {}, False
    if any(item is not None and not isinstance(item, Mapping) for item in documents):
        failures.append(AdapterFailure(source="supervisor", category=REJECTED))
        return {}, True
    if raw["captured_at"] is not None and not _aware(raw["captured_at"]):
        failures.append(AdapterFailure(source="supervisor", category=REJECTED))
        return {}, True
    if raw["freshness_policy"] is not None and not isinstance(
        raw["freshness_policy"], SnapshotFreshnessPolicy
    ):
        failures.append(AdapterFailure(source="supervisor", category=REJECTED))
        return {}, True
    try:
        copied = {
            "supervisor_bot_status": _optional_snapshot(raw["bot_status"]),
            "supervisor_governance_status": _optional_snapshot(raw["governance_status"]),
            "supervisor_money_management_status": _optional_snapshot(
                raw["money_management_status"]
            ),
            "supervisor_health_payload": _optional_snapshot(raw["health_payload"]),
        }
    except SnapshotRejected:
        failures.append(AdapterFailure(source="supervisor", category=REJECTED))
        return {}, True
    if raw["captured_at"] is not None:
        copied["supervisor_captured_at"] = raw["captured_at"]
    if raw["freshness_policy"] is not None:
        copied["supervisor_freshness_policy"] = raw["freshness_policy"]
    return copied, True


def _mapping_slot(failures, source: str, key: str, value):
    if value is None:
        return {}, False
    try:
        return {key: _snapshot(value)}, True
    except SnapshotRejected:
        failures.append(AdapterFailure(source=source, category=REJECTED))
        return {}, True


def _execution_slot(failures, value):
    kwargs, supplied = _mapping_slot(failures, "execution_control", "execution_projection", value)
    projection = kwargs.get("execution_projection")
    if isinstance(projection, dict):
        for name in ("realOrderAllowed", "real_order_allowed"):
            if name in projection and not isinstance(projection[name], bool):
                projection.pop(name)
    return kwargs, supplied


def _optional_snapshot(value):
    if value is None:
        return None
    return _snapshot(value)


def _snapshot(value):
    return copy_json_snapshot(value)


def _aware(value) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def _symbol(value) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 32
        and value.isalnum()
    )


def _cycle_id(value) -> tuple[str | None, bool]:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        return None, False
    if len(value) > MAX_CYCLE_ID:
        return None, False
    return value, True


def _cycle_ids_ok(decision, runtime) -> bool:
    if isinstance(decision, Mapping) and "cycleId" in decision:
        _, ok = _cycle_id(decision.get("cycleId"))
        if not ok:
            return False
    readiness = _readiness(runtime)
    if isinstance(readiness, Mapping) and "cycleId" in readiness:
        _, ok = _cycle_id(readiness.get("cycleId"))
        if not ok:
            return False
    return True


def _ids_match(decision, runtime) -> bool:
    decision_id = None
    if isinstance(decision, Mapping) and "cycleId" in decision:
        decision_id, _ok = _cycle_id(decision.get("cycleId"))
    readiness = _readiness(runtime)
    evaluation_id = None
    if isinstance(readiness, Mapping) and "cycleId" in readiness:
        evaluation_id, _ok = _cycle_id(readiness.get("cycleId"))
    return bool(decision_id and evaluation_id and decision_id == evaluation_id)


def _readiness(runtime):
    if not isinstance(runtime, Mapping):
        return None
    output = runtime.get("strategyOutput")
    if not isinstance(output, Mapping):
        return None
    strategy = output.get("strategy")
    if not isinstance(strategy, Mapping):
        return None
    readiness = strategy.get("entryReadiness")
    return readiness if isinstance(readiness, Mapping) else None


def _strategy(runtime):
    if not isinstance(runtime, Mapping):
        return None
    output = runtime.get("strategyOutput")
    if not isinstance(output, Mapping):
        return None
    strategy = output.get("strategy")
    return strategy if isinstance(strategy, Mapping) else None


def _mapping_has_time(mapping) -> bool:
    if not isinstance(mapping, Mapping):
        return False
    for key in _TIME_KEYS:
        if key in mapping and parse_producer_time(mapping.get(key)) is not None:
            return True
    return False
