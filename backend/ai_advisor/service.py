"""Read-only runtime response service used by the AI Advisor runtime API."""

import math
import time
from datetime import datetime, timezone
from typing import Callable

from backend.ai_advisor.models import (
    AdvisorAuthorityStatus,
    AdvisorBotStatus,
    AdvisorExecutionEntryState,
    AdvisorHealthStatus,
    AdvisorMarketStatus,
    AdvisorMoneyManagementStatus,
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


def _entry_state(value: str) -> AdvisorExecutionEntryState:
    return AdvisorExecutionEntryState(value)


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
            openPosState=snapshot.position_state,
            pendingOrderState=snapshot.pending_order_state,
        ),
        safety=AdvisorSafetyStatus(
            emergencyLocked=snapshot.emergency_locked,
            emergencyState=snapshot.emergency_state,
            dryRun=snapshot.dry_run,
            realOrderAllowed=snapshot.real_order_allowed,
        ),
        market=AdvisorMarketStatus(
            selectionMode=snapshot.selection_mode,
            marketReady=snapshot.market_ready,
            marketStale=snapshot.market_stale,
        ),
        authority=AdvisorAuthorityStatus(
            liveOrderEntryState=_entry_state(snapshot.live_order_entry_state),
            finalExecutionEntryState=_entry_state(
                snapshot.final_execution_entry_state
            ),
            mmExecutionEntryState=_entry_state(snapshot.mm_execution_entry_state),
        ),
        moneyManagement=AdvisorMoneyManagementStatus(
            state=snapshot.mm_state,
            riskState=snapshot.mm_risk_state,
            recommendedAction=snapshot.mm_recommended_action,
            executionEntryState=_entry_state(snapshot.mm_execution_entry_state),
            mmRegime=snapshot.mm_regime,
            equity=snapshot.mm_equity,
            availableCapital=snapshot.mm_available_capital,
            openExposure=snapshot.mm_exposure,
            remainingExposure=snapshot.mm_remaining_exposure,
            openPositionCapacity=snapshot.mm_position_capacity,
            remainingOpenPositionCapacity=snapshot.mm_remaining_position_capacity,
            riskBudget=snapshot.mm_risk_budget,
            drawdownPercent=snapshot.mm_drawdown_percent,
            ruinGuardStatus=snapshot.mm_ruin_guard_status,
            compoundingEnabled=snapshot.mm_compounding_enabled,
            authorityFresh=snapshot.mm_authority_fresh,
            mmCapturedAt=(
                _epoch_iso(float(snapshot.mm_captured_at))
                if isinstance(snapshot.mm_captured_at, (int, float))
                and not isinstance(snapshot.mm_captured_at, bool)
                else None
            ),
        ),
        health=AdvisorHealthStatus(healthState=snapshot.health_state),
        runtime=AdvisorRuntimeMetadata(
            capturedAt=_epoch_iso(captured_at),
            sourceUpdatedAt=source_iso,
            freshness=freshness,
        ),
        warnings=list(dict.fromkeys(warnings)),
    )
