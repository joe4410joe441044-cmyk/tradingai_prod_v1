"""Read-only bridge from verified runtime readers into the context collector.

Instances are injected by the caller. This module does not construct a
BotManager or Supervisor, does not call ``get_status`` or ``get_result``, and
does not contact an exchange. ``generated_at`` is the pack stamp only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.runtime.current_position_view import current_position
from backend.runtime.cycle_diagnostics import build_trading_cycle_diagnostics
from backend.supervisor.snapshot_builder import build_supervisor_snapshot

from .runtime_collector import RuntimeCollection, collect_runtime_context
from .runtime_reader_contract import (
    RUNTIME_INSTANCE_NOT_INJECTED,
    SKIPPED_READERS,
    UNSAFE_READER_SKIPPED,
    AdapterFailure,
    SkippedReader,
)

_MODES = {"PAPER", "LIVE"}


@dataclass(frozen=True)
class VerifiedReaderResult:
    collection: RuntimeCollection
    connected_readers: tuple[str, ...]
    skipped_readers: tuple[SkippedReader, ...]
    adapter_failures: tuple[AdapterFailure, ...]
    runtime_instance_injected: bool


def collect_verified_runtime_context(
    *,
    generated_at: datetime,
    bot_manager: Any = None,
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
    """Call only verified readers, then the existing collector.

    Account, money-management, and execution mappings are forwarded when the
    caller already holds them. Their live producers are not invoked.
    """

    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    connected: list[str] = []
    failures: list[AdapterFailure] = []
    skipped = [SkippedReader(name, safety, reason) for name, safety, reason in SKIPPED_READERS]
    if bot_manager is not None:
        failures.append(
            AdapterFailure(source="bot_manager", category=UNSAFE_READER_SKIPPED)
        )

    supervisor_snapshot = _read_supervisor(
        connected,
        failures,
        bot_status=supervisor_bot_status,
        governance_status=supervisor_governance_status,
        money_management_status=supervisor_money_management_status,
        health_payload=supervisor_health_payload,
        captured_at=supervisor_captured_at,
        freshness_policy=supervisor_freshness_policy,
    )
    position_view = _read_position(
        connected,
        failures,
        account=position_account,
        mode=position_mode,
        observed_at=position_observed_at,
        symbol=position_symbol,
        price=position_price,
        observation=position_observation,
    )
    diagnostics = _read_cycle(
        connected,
        failures,
        decision=trading_decision,
        context=trading_cycle_context,
        runtime_result=trading_cycle_runtime_result,
        evaluated_at=cycle_evaluated_at,
    )
    injected = any(
        value is not None
        for value in (
            bot_manager,
            position_account,
            position_mode,
            position_observed_at,
            position_price,
            position_observation,
            trading_decision,
            trading_cycle_context,
            trading_cycle_runtime_result,
            cycle_evaluated_at,
            supervisor_bot_status,
            supervisor_governance_status,
            supervisor_money_management_status,
            supervisor_health_payload,
            supervisor_captured_at,
            supervisor_freshness_policy,
            account_projection,
            mm_projection,
            execution_projection,
        )
    )
    if not injected:
        failures.append(
            AdapterFailure(source="runtime", category=RUNTIME_INSTANCE_NOT_INJECTED)
        )
    collection = collect_runtime_context(
        generated_at=generated_at.astimezone(timezone.utc),
        supervisor_snapshot=supervisor_snapshot,
        position_view=position_view,
        trading_cycle_projection=diagnostics,
        account_projection=account_projection,
        mm_projection=mm_projection,
        execution_projection=execution_projection,
    )
    return VerifiedReaderResult(
        collection=collection,
        connected_readers=tuple(connected),
        skipped_readers=tuple(skipped),
        adapter_failures=tuple(failures),
        runtime_instance_injected=injected,
    )


def _read_supervisor(connected, failures, **payloads):
    documents = (
        payloads["bot_status"],
        payloads["governance_status"],
        payloads["money_management_status"],
        payloads["health_payload"],
    )
    captured_at = payloads["captured_at"]
    policy = payloads["freshness_policy"]
    if all(item is None for item in documents) and captured_at is None and policy is None:
        return None
    if all(item is None for item in documents):
        failures.append(AdapterFailure(source="supervisor", category="READER_NOT_INJECTED"))
        return None
    if any(item is not None and not isinstance(item, Mapping) for item in documents):
        failures.append(AdapterFailure(source="supervisor", category="READER_REJECTED"))
        return None
    if captured_at is None or policy is None:
        failures.append(AdapterFailure(source="supervisor", category="READER_NOT_INJECTED"))
        return None
    if not isinstance(captured_at, datetime) or captured_at.tzinfo is None:
        failures.append(AdapterFailure(source="supervisor", category="READER_REJECTED"))
        return None
    try:
        snapshot = build_supervisor_snapshot(
            bot_status=payloads["bot_status"],
            governance_status=payloads["governance_status"],
            money_management_status=payloads["money_management_status"],
            health_payload=payloads["health_payload"],
            captured_at=captured_at,
            freshness_policy=policy,
        )
    except Exception:
        failures.append(AdapterFailure(source="supervisor", category="READER_FAILED"))
        return None
    connected.append("build_supervisor_snapshot")
    return snapshot


def _read_position(
    connected, failures, *, account, mode, observed_at, symbol, price, observation
):
    if (
        account is None
        and mode is None
        and observed_at is None
        and price is None
        and observation is None
    ):
        return None
    if (
        not isinstance(account, Mapping)
        or mode not in _MODES
        or (observation is not None and not isinstance(observation, Mapping))
        or (price is not None and (isinstance(price, bool) or not isinstance(price, (int, float))))
    ):
        failures.append(AdapterFailure(source="position", category="READER_REJECTED"))
        return None
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        failures.append(AdapterFailure(source="position", category="READER_NOT_INJECTED"))
        return None
    try:
        view = current_position(
            dict(account),
            mode,
            now=observed_at.timestamp(),
            symbol=symbol,
            current_price=price,
            observation=None if observation is None else dict(observation),
        )
    except Exception:
        failures.append(AdapterFailure(source="position", category="READER_FAILED"))
        return {"status": "UNKNOWN", "freshness": "UNKNOWN", "reason": "READER_FAILED"}
    connected.append("current_position")
    return view


def _read_cycle(connected, failures, *, decision, context, runtime_result, evaluated_at):
    supplied = (decision, context, runtime_result)
    if all(item is None for item in supplied):
        if evaluated_at is not None:
            failures.append(
                AdapterFailure(source="trading_cycle", category="READER_NOT_INJECTED")
            )
        return None
    if any(item is not None and not isinstance(item, Mapping) for item in supplied):
        failures.append(AdapterFailure(source="trading_cycle", category="READER_REJECTED"))
        return None
    if evaluated_at is not None and (
        not isinstance(evaluated_at, datetime) or evaluated_at.tzinfo is None
    ):
        failures.append(AdapterFailure(source="trading_cycle", category="READER_REJECTED"))
        return None
    try:
        diagnostics = build_trading_cycle_diagnostics(
            trading_decision=decision,
            context=context,
            runtime_result=runtime_result,
            evaluated_at=evaluated_at,
        )
    except Exception:
        failures.append(AdapterFailure(source="trading_cycle", category="READER_FAILED"))
        return {"provenance": "UNKNOWN", "freshness": "UNKNOWN"}
    connected.append("build_trading_cycle_diagnostics")
    return diagnostics
