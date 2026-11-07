"""Read-only runtime truth adapters.

These adapters normalize snapshots that the caller has already collected.
They do not start or stop the bot, submit orders, or contact an exchange.
``current_position`` is used only as a pure projection of an injected account
snapshot, and only when the caller also supplies the observation clock.
"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping

from backend.runtime.current_position_view import current_position

from .runtime_projection import (
    parse_producer_time,
    project_account,
    project_execution_control,
    project_position,
    project_small_account,
    project_trading_cycle,
)
from .schema import ContextObservation

_EXECUTION_KEYS = (
    "selectedMode",
    "savedMode",
    "tradeMode",
    "tradeModeCapability",
    "executionMode",
    "execution_mode",
    "controlAuthority",
    "control",
    "entryAuthority",
    "entry_authority",
    "realOrderAllowed",
    "real_order_allowed",
    "botState",
    "loopState",
    "emergencyState",
    "execution",
)
_MM_KEYS = (
    "moneyManagement",
    "capitalEligibility",
    "executabilitySettings",
    "availableCapital",
    "riskBudget",
    "riskPercent",
    "mmStatus",
    "blockers",
)


def _require_mapping(name: str, value: object) -> None:
    if value is None:
        return
    if isinstance(value, Mapping):
        return
    raise TypeError(
        f"{name} must be an injected mapping; live managers are not accepted"
    )


def _has_any(mapping: Mapping[str, object] | None, keys: tuple[str, ...]) -> bool:
    return isinstance(mapping, Mapping) and any(key in mapping for key in keys)


def _position_view_from_bot(bot: Mapping[str, object]) -> Mapping[str, object] | None:
    selected = str(bot.get("selectedMode") or bot.get("savedMode") or "").strip().upper()
    by_mode = bot.get("positionsByMode")
    current = bot.get("currentPosition") if "currentPosition" in bot else None
    if isinstance(current, Mapping):
        view_mode = str(current.get("mode") or "").strip().upper()
        if selected in {"PAPER", "LIVE"} and view_mode in {"PAPER", "LIVE"} and selected != view_mode:
            return {
                "status": "UNKNOWN",
                "mode": selected,
                "reason": "POSITION_CONTRADICTION",
                "freshness": "UNKNOWN",
                "source": current.get("source") or "RUNTIME_POSITION_READER",
            }
        if isinstance(by_mode, Mapping) and view_mode in by_mode and isinstance(by_mode[view_mode], Mapping):
            other = by_mode[view_mode]
            if (current.get("status"), current.get("symbol"), current.get("side")) != (
                other.get("status"),
                other.get("symbol"),
                other.get("side"),
            ):
                return {
                    "status": "UNKNOWN",
                    "mode": view_mode,
                    "reason": "POSITION_CONTRADICTION",
                    "freshness": "UNKNOWN",
                    "source": current.get("source") or "RUNTIME_POSITION_READER",
                }
        return current
    if current is None and "currentPosition" in bot:
        return {
            "status": "UNKNOWN",
            "freshness": "UNKNOWN",
            "source": "RUNTIME_POSITION_READER",
            "reason": "POSITION_SOURCE_UNAVAILABLE",
        }
    if isinstance(by_mode, Mapping):
        if selected in {"PAPER", "LIVE"} and isinstance(by_mode.get(selected), Mapping):
            return by_mode[selected]
        return {
            "status": "UNKNOWN",
            "freshness": "UNKNOWN",
            "source": "RUNTIME_POSITION_READER",
            "reason": "MODE_UNRESOLVED",
        }
    return None


def _account_from_bot(bot: Mapping[str, object]) -> Mapping[str, object] | None:
    runtime = bot.get("accountRuntime")
    if isinstance(runtime, Mapping):
        if "mode" in runtime or "selectedMode" in runtime:
            return runtime
        selected = bot.get("selectedMode") or bot.get("savedMode")
        if selected is None:
            return runtime
        return {**runtime, "selectedMode": selected}
    if "paperAccount" in bot or "realAccount" in bot:
        return {
            "paperAccount": bot.get("paperAccount"),
            "realAccount": bot.get("realAccount"),
            "selectedMode": bot.get("selectedMode") or bot.get("savedMode"),
        }
    return None


def _cycle_from_bot(bot: Mapping[str, object]) -> Mapping[str, object] | None:
    diagnostics = bot.get("tradingCycleDiagnostics")
    return diagnostics if isinstance(diagnostics, Mapping) else None


def _execution_from_bot(bot: Mapping[str, object]) -> Mapping[str, object] | None:
    if not _has_any(bot, _EXECUTION_KEYS):
        return None
    return bot


def _mm_from_bot(bot: Mapping[str, object]) -> Mapping[str, object] | None:
    for key in ("smallAccount", "moneyManagement", "capitalEligibility"):
        value = bot.get(key)
        if isinstance(value, Mapping):
            return value
    if _has_any(bot, ("availableCapital", "riskBudget", "riskPercent", "blockers", "mmStatus")):
        return bot
    return None


def _observation_clock(value: datetime | float | int | str | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = parse_producer_time(value)
        return None if parsed is None else parsed.timestamp()
    parsed = parse_producer_time(value)
    if parsed is None:
        return None
    return parsed.timestamp()


def read_position_truth(
    *,
    position_view: Mapping[str, object] | None = None,
    account: Mapping[str, object] | None = None,
    mode: str | None = None,
    now: datetime | float | int | str | None = None,
    symbol: str | None = None,
    current_price: float | None = None,
    observation: Mapping[str, object] | None = None,
) -> ContextObservation | None:
    """Normalize a position view, or project an injected account with ``current_position``."""

    _require_mapping("position_view", position_view)
    _require_mapping("account", account)
    _require_mapping("observation", observation)
    if position_view is not None:
        return project_position(position_view)
    if account is None:
        return None
    clock = _observation_clock(now)
    if clock is None:
        return project_position(
            {
                "status": "UNKNOWN",
                "mode": mode,
                "freshness": "UNKNOWN",
                "source": "RUNTIME_POSITION_READER",
                "reason": "SOURCE_NOT_CURRENT",
            }
        )
    view = current_position(
        account,
        mode,
        now=clock,
        symbol=symbol,
        current_price=current_price,
        observation=observation,
    )
    return project_position(view)


def read_runtime_sections(
    *,
    bot_status: Mapping[str, object] | None = None,
    account_projection: Mapping[str, object] | None = None,
    mm_projection: Mapping[str, object] | None = None,
    trading_cycle_projection: Mapping[str, object] | None = None,
    position_projection: Mapping[str, object] | None = None,
    position_account: Mapping[str, object] | None = None,
    position_mode: str | None = None,
    position_now: datetime | float | int | str | None = None,
    position_symbol: str | None = None,
    position_price: float | None = None,
    position_observation: Mapping[str, object] | None = None,
    execution_projection: Mapping[str, object] | None = None,
) -> dict[str, ContextObservation]:
    """Return canonical sections for the injected runtime projections."""

    for name, value in (
        ("bot_status", bot_status),
        ("account_projection", account_projection),
        ("mm_projection", mm_projection),
        ("trading_cycle_projection", trading_cycle_projection),
        ("position_projection", position_projection),
        ("position_account", position_account),
        ("position_observation", position_observation),
        ("execution_projection", execution_projection),
    ):
        _require_mapping(name, value)

    sections: dict[str, ContextObservation] = {}
    position_view = position_projection
    if position_view is None and isinstance(bot_status, Mapping):
        position_view = _position_view_from_bot(bot_status)
    position = read_position_truth(
        position_view=position_view,
        account=None if position_view is not None else position_account,
        mode=position_mode,
        now=position_now,
        symbol=position_symbol,
        current_price=position_price,
        observation=position_observation,
    )
    if position is not None:
        sections["position"] = position

    account = account_projection
    if account is None and isinstance(bot_status, Mapping):
        account = _account_from_bot(bot_status)
    if account is not None:
        sections["account"] = project_account(account)

    mm = mm_projection
    if mm is None and isinstance(bot_status, Mapping):
        mm = _mm_from_bot(bot_status)
    if mm is not None:
        sections["smallAccount"] = project_small_account(mm)

    cycle = trading_cycle_projection
    if cycle is None and isinstance(bot_status, Mapping):
        cycle = _cycle_from_bot(bot_status)
    if cycle is not None:
        sections["tradingCycle"] = project_trading_cycle(cycle)

    execution = execution_projection
    if execution is None and isinstance(bot_status, Mapping):
        execution = _execution_from_bot(bot_status)
    if execution is not None:
        sections["executionControl"] = project_execution_control(execution)
    return sections
