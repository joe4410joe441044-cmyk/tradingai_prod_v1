import { MONITORING_SOURCES, REALIZED_PNL_SEMANTICS } from "./moneyManagementMonitoringContracts.js";
export function monitoringFixture(authority, freshness = "LAST_KNOWN") {
  const asOf = "2026-09-12T00:00:00Z";
  const snapshot = {
    authority, accountingAuthoritySource: MONITORING_SOURCES[authority],
    realizedPnlSemantics: REALIZED_PNL_SEMANTICS[authority],
    source: "MM_RUNTIME_OBSERVATION", capturedAt: asOf, riskState: "NORMAL",
    metrics: { equity: authority === "PAPER" ? "101.25" : "202.50", peakEquity: "250", drawdownPercent: "1.25", realizedPnl: authority === "PAPER" ? "11.25" : "22.50", unrealizedPnl: "3.50", openPositionState: "FLAT" },
    dailyPnl: "2.50", weeklyPnl: "5.50", monthlyPnl: "9.50",
  };
  return freshness === "UNAVAILABLE" ? {
    viewAuthority: authority, dataAuthority: null, availability: "UNAVAILABLE", semantics: "UNAVAILABLE", freshness, source: null, asOf: null, snapshot: null,
  } : {
    viewAuthority: authority, dataAuthority: authority, availability: "AVAILABLE", semantics: "LAST_KNOWN", freshness, source: snapshot.source, asOf, snapshot,
  };
}
export function historyFixture(authority, sequence = 1, timestamp = "2026-09-12T00:00:00Z") {
  return { ...monitoringFixture(authority).snapshot, eventId: `event-${authority}-${sequence}`, sequence, timestamp, state: "NORMAL", eventType: "RUNTIME_METRICS_UPDATED" };
}
export const legacyFixture = {
  eventId: "legacy", sequence: 99, timestamp: "2026-09-12T00:00:00Z", authority: "UNKNOWN", accountingAuthoritySource: null,
  metrics: { equity: "7.91836966", peakEquity: "100.0805801773", drawdownPercent: "92.088" }, state: "LOCKED", eventType: "LOSS_STATE_CHANGED",
};
