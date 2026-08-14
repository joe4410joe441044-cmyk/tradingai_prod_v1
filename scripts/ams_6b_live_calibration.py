"""Run an explicitly market-only AMS-6B public-data campaign."""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json

from backend.auto_market_selection import (
    LiveCalibrationCampaign, LiveReadOnlyValidation, analyze_calibration,
    simulate_anti_flapping_grid,
)
from backend.market.kucoin_futures_public import KucoinFuturesPublicClient
from backend.money_management.capital_eligibility import build_capital_eligibility_contract


SAFETY = {
    "realOrderAllowed": False, "dryRun": True,
    "executionRealOrderDisabled": True, "autoTradeDisabled": True,
    "liveAutoSwitchDisabled": True, "emergencyAvailable": True,
    "governanceAvailable": True,
}


def fixed_market_only_capital(evaluated_at):
    """Synthetic feasibility input; never represented as Live account authority."""
    return build_capital_eligibility_contract(
        equity=Decimal("1000"), available_capital=Decimal("900"),
        risk_budget=Decimal("4.5"), max_position_notional=Decimal("100"),
        total_exposure_percent=Decimal("20"), open_exposure=Decimal("0"),
        position_count=0, pending_order_count=0, mm_regime="CALIBRATION_ONLY",
        policy_version="ams-6b-fixed-market-only", evaluated_at=evaluated_at,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--active-symbol", default="BTCUSDT")
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    validation = LiveReadOnlyValidation(
        KucoinFuturesPublicClient(timeout=10), capital_provider=fixed_market_only_capital,
        active_symbol_provider=lambda: args.active_symbol, safety_provider=lambda: dict(SAFETY),
        position_provider=lambda: "FLAT", pending_order_provider=lambda: False,
        emergency_provider=lambda: True,
    )
    campaign = LiveCalibrationCampaign(validation)
    records = campaign.run(args.count, interval_seconds=args.interval)
    finished = datetime.now(timezone.utc)
    grid = simulate_anti_flapping_grid(records)
    churn_values = [item["hypotheticalSwitchCount"] for item in grid]
    output = {
        "mode": "LIVE_READ_ONLY_CALIBRATION", "marketCalibration": True,
        "authoritativeLiveAccountUsed": False, "mmDependentCalibration": "BLOCKED",
        "startedAt": started.isoformat().replace("+00:00", "Z"),
        "finishedAt": finished.isoformat().replace("+00:00", "Z"),
        "durationSeconds": (finished-started).total_seconds(), "intervalSeconds": args.interval,
        "rateLimitEvidence": {"contractsWeight": 3, "allTickersWeight": 5,
                              "weightPerObservation": 8, "publicPoolVip0Per30Seconds": 2000},
        "safety": {"activeSymbolMutations": 0, "safeSwitchCommits": 0, "realOrders": 0,
                   "executionChanges": 0, "governanceBypass": 0, "emergencyChanges": 0,
                   "credentialLeakage": 0},
        "analysis": analyze_calibration(records),
        "simulation": {
            "parameterCombinations": len(grid),
            "lowestChurnCount": min(churn_values),
            "highestChurnCount": max(churn_values),
            "lowestChurnRegions": [item for item in grid if item["hypotheticalSwitchCount"] == min(churn_values)][:10],
            "highestChurnRegions": [item for item in grid if item["hypotheticalSwitchCount"] == max(churn_values)][:10],
            "runtimeMutationCount": 0,
        },
        }
    if not args.summary_only:
        output["records"] = [record.to_dict() for record in records]
    print(json.dumps(output, default=str, separators=(",", ":")))


if __name__ == "__main__":
    main()
