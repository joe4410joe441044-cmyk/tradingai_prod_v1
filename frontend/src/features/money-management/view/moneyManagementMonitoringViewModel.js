import { displayDecimal } from "./moneyManagementViewModel.js";
import { realizedPnlLabel } from "../contracts/moneyManagementMonitoringContracts.js";

export function createMonitoringViewModel(data) {
  const snapshot = data.monitoring?.snapshot;
  const metrics = snapshot?.metrics;
  const row = (label, key, unit = "USDT", source = metrics) => ({ label, value: displayDecimal(source?.[key], unit) });
  const textRow = (label, value) => ({ label, value: { text: value ?? "—", unavailable: value == null, unit: null } });
  return {
    state: data.monitoringState,
    capital: [row("Equity", "equity"), row("Available Capital", "availableCapital")],
    riskSummary: { rows: [
      row("Risk Limit", "riskLimitAmount"), row("Snapshot Risk", "currentRiskAmount"),
      row("Reserved Risk", "reservedRiskAmount"), row("Risk Budget Remaining", "riskBudgetRemaining"),
      row("Risk Utilization", "riskUtilization", "%"), textRow("Snapshot Risk State", snapshot?.riskState),
    ] },
    exposure: [
      row("Snapshot Exposure", "openExposure", null), row("Exposure Limit (Snapshot Configuration)", "exposureLimit", "%"),
      row("Exposure Utilization", "exposureUtilization", "%"), textRow("Snapshot Position State", metrics?.openPositionState),
    ],
    performance: [
      row(realizedPnlLabel(data.authority), "realizedPnl"), row("Unrealized PnL", "unrealizedPnl"),
      row("Daily P&L", "dailyPnl", "USDT", snapshot), row("Weekly P&L", "weeklyPnl", "USDT", snapshot),
      row("Monthly P&L", "monthlyPnl", "USDT", snapshot), row("Peak Equity", "peakEquity"),
      row("Snapshot Drawdown", "drawdownAmount"), row("Drawdown", "drawdownPercent", "%"),
    ],
  };
}
