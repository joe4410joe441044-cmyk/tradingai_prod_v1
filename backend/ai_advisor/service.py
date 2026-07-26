"""Read-only runtime response service used by the AI Advisor runtime API."""

import math
import time
from datetime import datetime, timezone
from typing import Callable

from backend.ai_advisor.models import (
    AdvisorBotStatus,
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
        warnings=list(dict.fromkeys(warnings)),
    )
