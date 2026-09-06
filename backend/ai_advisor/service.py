"""Read-only runtime response service used by the AI Advisor runtime API."""

import math
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from backend.ai_advisor.models import (
    AdvisorBotStatus,
    AdvisorMarketRuntimeStatus,
    AdvisorMoneyManagementRuntimeStatus,
    AdvisorOperationStatus,
    AdvisorRuntimeMetadata,
    AdvisorRuntimeResponse,
    AdvisorSafetyStatus,
    Freshness,
)
from backend.ai_advisor.runtime_reader import (
    RuntimeScalarSnapshot,
    read_runtime_scalars,
)

RUNTIME_FRESHNESS_SECONDS = 10.0


def _epoch_iso(value: float) -> str:
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def _epoch_or_iso(value: Optional[float]) -> Optional[str]:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if not math.isfinite(value):
        return None
    return _epoch_iso(float(value))


def _money_management_runtime(
    snapshot: RuntimeScalarSnapshot,
) -> Optional[AdvisorMoneyManagementRuntimeStatus]:
    if (
        snapshot.mm_regime is None
        and snapshot.mm_equity is None
        and snapshot.mm_available_capital is None
        and snapshot.mm_exposure is None
        and snapshot.mm_remaining_exposure is None
        and snapshot.mm_position_capacity is None
        and snapshot.mm_remaining_position_capacity is None
        and snapshot.mm_risk_budget is None
        and snapshot.mm_drawdown_percent is None
        and snapshot.mm_ruin_guard_status is None
        and snapshot.mm_compounding_enabled is None
        and snapshot.mm_authority_fresh is None
        and snapshot.mm_captured_at is None
    ):
        return None
    return AdvisorMoneyManagementRuntimeStatus(
        regime=snapshot.mm_regime,
        equity=snapshot.mm_equity,
        availableCapital=snapshot.mm_available_capital,
        exposure=snapshot.mm_exposure,
        remainingExposure=snapshot.mm_remaining_exposure,
        positionCapacity=snapshot.mm_position_capacity,
        remainingPositionCapacity=snapshot.mm_remaining_position_capacity,
        riskBudget=snapshot.mm_risk_budget,
        drawdownPercent=snapshot.mm_drawdown_percent,
        ruinGuardStatus=snapshot.mm_ruin_guard_status,
        compoundingEnabled=snapshot.mm_compounding_enabled,
        authorityFresh=snapshot.mm_authority_fresh,
        capturedAt=_epoch_or_iso(snapshot.mm_captured_at),
    )


def _market_runtime(
    snapshot: RuntimeScalarSnapshot,
) -> Optional[AdvisorMarketRuntimeStatus]:
    if snapshot.market_ready is None and snapshot.market_symbol is None:
        return None
    return AdvisorMarketRuntimeStatus(
        ready=snapshot.market_ready,
        symbol=snapshot.market_symbol,
    )


def build_runtime_response(
    *,
    reader: Callable[[], RuntimeScalarSnapshot] = read_runtime_scalars,
    clock: Callable[[], float] = time.time,
) -> AdvisorRuntimeResponse:
    """Build an allowlisted response without mutating the existing runtime."""

    captured_at = float(clock())
    if not math.isfinite(captured_at):
        raise ValueError("clock must return a finite timestamp")
    snapshot = reader()
    warnings = list(snapshot.warnings)
    source_updated_at = snapshot.source_updated_at
    source_iso = None
    freshness = Freshness.UNKNOWN
    if (
        isinstance(source_updated_at, (int, float))
        and not isinstance(source_updated_at, bool)
        and math.isfinite(source_updated_at)
    ):
        if source_updated_at > captured_at:
            warnings.append("SOURCE_TIMESTAMP_IN_FUTURE")
        else:
            source_iso = _epoch_iso(float(source_updated_at))
            age = captured_at - float(source_updated_at)
            if age <= RUNTIME_FRESHNESS_SECONDS:
                freshness = Freshness.FRESH
            else:
                freshness = Freshness.STALE
                warnings.append("RUNTIME_STALE")
    return AdvisorRuntimeResponse(
        bot=AdvisorBotStatus(
            state=snapshot.state,
            mode=snapshot.mode,
            exchange=snapshot.exchange,
            symbol=snapshot.symbol,
        ),
        operation=AdvisorOperationStatus(
            loopEnabled=snapshot.loop_enabled,
            loopState=snapshot.loop_state,
            autoTradeEnabled=snapshot.auto_trade_enabled,
            positionState=snapshot.position_state,
            pendingOrderState=snapshot.pending_order_state,
        ),
        safety=AdvisorSafetyStatus(
            emergencyLocked=snapshot.emergency_locked,
            emergencyState=snapshot.emergency_state,
            dryRun=snapshot.dry_run,
            realOrderAllowed=snapshot.real_order_allowed,
        ),
        runtime=AdvisorRuntimeMetadata(
            capturedAt=_epoch_iso(captured_at),
            sourceUpdatedAt=source_iso,
            freshness=freshness,
        ),
        moneyManagement=_money_management_runtime(snapshot),
        market=_market_runtime(snapshot),
        warnings=list(dict.fromkeys(warnings)),
    )
