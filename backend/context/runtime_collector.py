"""Read-only collection entry for Canonical AI Context.

Readers are injected. When a reader is absent this module does not create a
BotManager, does not call an exchange, and does not read the live runtime.
Proven-safe normalization stays in the existing composer:

- an injected position view is normalized by ``project_position``
- an injected account snapshot plus an observation clock is projected by
  ``current_position`` inside ``read_position_truth``
- account, MM, trading-cycle, and execution mappings are normalized by the
  existing ``project_*`` readers

``trailing_stop_distance_percent`` is not aliased to ``trailingPercent``.
``currency``, ``takeProfitPercent``, and ``timeExitSeconds`` stay unavailable
unless the injected projection already carries those exact names.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from backend.supervisor.contracts import ReadOnlySupervisorSnapshot

from .collector_contract import (
    PRODUCTION_RUNTIME_CONNECTED,
    READER_FAILED,
    READER_NOT_INJECTED,
    READER_REJECTED,
    READER_UNAVAILABLE,
    SLOT_ACCOUNT,
    SLOT_BOT_STATUS,
    SLOT_CYCLE,
    SLOT_EXECUTION,
    SLOT_MM,
    SLOT_POSITION,
    SLOT_SUPERVISOR,
    ReaderFailure,
    RuntimeCollection,
)
from .context_views import build_operator_context_view, build_public_context_view
from .runtime_composer import compose_tradingai_context
from .runtime_truth import _account_from_bot, _cycle_from_bot, _execution_from_bot, _mm_from_bot, _position_view_from_bot
from .schema import ProjectTruth, SourceTruth

Reader = Callable[[], Any]

_UNAVAILABLE_POSITION = {
    "status": "UNKNOWN",
    "freshness": "UNKNOWN",
    "source": "RUNTIME_POSITION_READER",
    "reason": "READER_UNAVAILABLE",
}


def _failure(source: str, category: str) -> ReaderFailure:
    return ReaderFailure(source=source, category=category)


def _invoke(source: str, reader: Reader) -> tuple[Any, ReaderFailure | None]:
    try:
        value = reader()
    except Exception:
        return None, _failure(source, READER_FAILED)
    if value is None:
        return None, _failure(source, READER_UNAVAILABLE)
    return value, None


def _as_mapping(source: str, value: Any) -> tuple[dict[str, Any] | None, ReaderFailure | None]:
    if isinstance(value, Mapping):
        return dict(value), None
    return None, _failure(source, READER_REJECTED)


def _as_snapshot(
    value: Any,
) -> tuple[ReadOnlySupervisorSnapshot | None, ReaderFailure | None]:
    if isinstance(value, ReadOnlySupervisorSnapshot):
        return value, None
    return None, _failure(SLOT_SUPERVISOR, READER_REJECTED)


def _resolve_snapshot(
    explicit: Any,
    reader: Reader | None,
) -> tuple[ReadOnlySupervisorSnapshot | None, ReaderFailure | None, bool]:
    if explicit is not None:
        snapshot, failure = _as_snapshot(explicit)
        return snapshot, failure, failure is None
    if reader is None:
        return None, _failure(SLOT_SUPERVISOR, READER_NOT_INJECTED), False
    value, failure = _invoke(SLOT_SUPERVISOR, reader)
    if failure is not None:
        return None, failure, False
    snapshot, rejected = _as_snapshot(value)
    return snapshot, rejected, rejected is None


def _resolve_mapping(
    source: str,
    explicit: Any,
    reader: Reader | None,
    *,
    from_status: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, ReaderFailure | None, bool]:
    """Return ``(projection, failure, connected)``.

    ``projection is None`` and ``failure is None`` means the status mapping
    already carries this section, so the composer reads it from there.
    A failure projection blocks that fallback. A missing reader with no
    status evidence stays uninjected and does not invent a value.
    """

    if explicit is not None:
        mapping, failure = _as_mapping(source, explicit)
        if failure is not None:
            return _blocked(source, failure.category), failure, False
        return mapping, None, True
    if reader is not None:
        value, failure = _invoke(source, reader)
        if failure is not None:
            return _blocked(source, failure.category), failure, False
        mapping, rejected = _as_mapping(source, value)
        if rejected is not None:
            return _blocked(source, rejected.category), rejected, False
        return mapping, None, True
    if from_status is not None:
        return None, None, True
    return None, _failure(source, READER_NOT_INJECTED), False


def _blocked(source: str, category: str) -> dict[str, Any]:
    if source == SLOT_POSITION:
        blocked = dict(_UNAVAILABLE_POSITION)
        blocked["reason"] = category
        return blocked
    return {"source": source, "freshness": "UNKNOWN", "readerOutcome": category}


def _status_section(bot_status: Mapping[str, Any] | None, extractor: Callable[[Mapping[str, Any]], Any]) -> Mapping[str, Any] | None:
    if bot_status is None:
        return None
    found = extractor(bot_status)
    return found if isinstance(found, Mapping) else None


def collect_runtime_context(
    *,
    generated_at: datetime,
    supervisor_snapshot: ReadOnlySupervisorSnapshot | None = None,
    supervisor_snapshot_reader: Reader | None = None,
    position_view: Mapping[str, Any] | None = None,
    position_reader: Reader | None = None,
    position_account: Mapping[str, Any] | None = None,
    position_mode: str | None = None,
    position_now: datetime | float | int | str | None = None,
    position_symbol: str | None = None,
    position_price: float | None = None,
    position_observation: Mapping[str, Any] | None = None,
    account_projection: Mapping[str, Any] | None = None,
    account_reader: Reader | None = None,
    mm_projection: Mapping[str, Any] | None = None,
    mm_reader: Reader | None = None,
    trading_cycle_projection: Mapping[str, Any] | None = None,
    trading_cycle_reader: Reader | None = None,
    execution_projection: Mapping[str, Any] | None = None,
    execution_control_reader: Reader | None = None,
    bot_status: Mapping[str, Any] | None = None,
    source_truth: SourceTruth | None = None,
    project_truth: ProjectTruth | None = None,
    max_bytes: int = 262144,
) -> RuntimeCollection:
    """Collect injected runtime facts and split the pack into two views.

    ``generated_at`` is the context stamp only. It is not forwarded as a
    producer timestamp. Uninjected readers stay unavailable.
    """

    failures: list[ReaderFailure] = []
    connected: list[str] = []

    if source_truth is not None and not isinstance(source_truth, SourceTruth):
        source_truth = None
    if project_truth is not None and not isinstance(project_truth, ProjectTruth):
        project_truth = None

    status, status_failure = (None, None)
    if bot_status is not None:
        status, status_failure = _as_mapping(SLOT_BOT_STATUS, bot_status)
        if status_failure is not None:
            failures.append(status_failure)
            status = None

    snapshot, snapshot_failure, snapshot_connected = _resolve_snapshot(
        supervisor_snapshot, supervisor_snapshot_reader
    )
    if snapshot_failure is not None:
        failures.append(snapshot_failure)
    elif snapshot_connected:
        connected.append(SLOT_SUPERVISOR)

    position, position_failure, position_connected = _resolve_mapping(
        SLOT_POSITION,
        position_view,
        position_reader,
        from_status=_status_section(status, _position_view_from_bot),
    )
    use_position_account = False
    position_missing = (
        position_failure is not None
        and position_failure.category == READER_NOT_INJECTED
    )
    if position_missing and position_account is not None:
        if position_account is not None and not isinstance(position_account, Mapping):
            failures.append(_failure(SLOT_POSITION, READER_REJECTED))
            position = _blocked(SLOT_POSITION, READER_REJECTED)
        else:
            use_position_account = True
            position = None
            connected.append(SLOT_POSITION)
    elif position_failure is not None:
        failures.append(position_failure)
    elif position_connected:
        connected.append(SLOT_POSITION)

    account, account_failure, account_connected = _resolve_mapping(
        SLOT_ACCOUNT,
        account_projection,
        account_reader,
        from_status=_status_section(status, _account_from_bot),
    )
    if account_failure is not None:
        failures.append(account_failure)
    elif account_connected:
        connected.append(SLOT_ACCOUNT)
    else:
        failures.append(_failure(SLOT_ACCOUNT, READER_NOT_INJECTED))

    mm, mm_failure, mm_connected = _resolve_mapping(
        SLOT_MM,
        mm_projection,
        mm_reader,
        from_status=_status_section(status, _mm_from_bot),
    )
    if mm_failure is not None:
        failures.append(mm_failure)
    elif mm_connected:
        connected.append(SLOT_MM)
    else:
        failures.append(_failure(SLOT_MM, READER_NOT_INJECTED))

    cycle, cycle_failure, cycle_connected = _resolve_mapping(
        SLOT_CYCLE,
        trading_cycle_projection,
        trading_cycle_reader,
        from_status=_status_section(status, _cycle_from_bot),
    )
    if cycle_failure is not None:
        failures.append(cycle_failure)
    elif cycle_connected:
        connected.append(SLOT_CYCLE)
    else:
        failures.append(_failure(SLOT_CYCLE, READER_NOT_INJECTED))

    execution, execution_failure, execution_connected = _resolve_mapping(
        SLOT_EXECUTION,
        execution_projection,
        execution_control_reader,
        from_status=_status_section(status, _execution_from_bot),
    )
    if execution_failure is not None:
        failures.append(execution_failure)
    elif execution_connected:
        connected.append(SLOT_EXECUTION)
    else:
        failures.append(_failure(SLOT_EXECUTION, READER_NOT_INJECTED))

    context = compose_tradingai_context(
        generated_at=generated_at,
        source_truth=source_truth,
        project_truth=project_truth,
        supervisor_snapshot=snapshot,
        bot_status=status,
        account_projection=account,
        mm_projection=mm,
        trading_cycle_projection=cycle,
        position_projection=position,
        position_account=None if not use_position_account else position_account,
        position_mode=position_mode if use_position_account else None,
        position_now=position_now if use_position_account else None,
        position_symbol=position_symbol if use_position_account else None,
        position_price=position_price if use_position_account else None,
        position_observation=position_observation if use_position_account else None,
        execution_projection=execution,
    )
    failure_records = tuple(failures)
    return RuntimeCollection(
        context=context,
        failures=failure_records,
        connected_sources=tuple(sorted(connected)),
        public_view=build_public_context_view(context, max_bytes=max_bytes),
        operator_view=build_operator_context_view(
            context, reader_failures=failure_records, max_bytes=max_bytes
        ),
        production_runtime_connected=PRODUCTION_RUNTIME_CONNECTED,
    )


collect_tradingai_context = collect_runtime_context
