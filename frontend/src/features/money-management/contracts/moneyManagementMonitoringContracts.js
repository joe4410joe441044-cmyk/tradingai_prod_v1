export const VIEW_AUTHORITIES = Object.freeze(["PAPER", "LIVE"]);
export const HISTORY_AUTHORITIES = Object.freeze(["ALL", "PAPER", "LIVE", "UNKNOWN"]);
export const MONITORING_SOURCES = Object.freeze({
  PAPER: "PAPER_RUNTIME_EQUITY",
  LIVE: "REAL_LIVE_ACCOUNT_EQUITY",
});
export const REALIZED_PNL_SEMANTICS = Object.freeze({
  PAPER: "PAPER_ENGINE_REPORTED_REALIZED_PNL",
  LIVE: "REALIZED_PNL_TODAY",
});
export function requireViewAuthority(value) {
  if (!VIEW_AUTHORITIES.includes(value)) throw new TypeError("Invalid monitoring View");
  return value;
}
export function requireHistoryAuthority(value) {
  if (!HISTORY_AUTHORITIES.includes(value)) throw new TypeError("Invalid history authority");
  return value;
}
export function initialViewAuthority(mode) {
  return VIEW_AUTHORITIES.includes(mode) ? mode : "PAPER";
}
export function realizedPnlLabel(authority) {
  requireViewAuthority(authority);
  return authority === "LIVE" ? "Realized PnL Today" : "Realized PnL (Engine Reported)";
}
export function normalizeMonitoringResponse(raw, authority) {
  requireViewAuthority(authority);
  if (!raw || raw.viewAuthority !== authority) throw new TypeError("Monitoring View mismatch");
  if (raw.availability === "UNAVAILABLE") {
    if (raw.snapshot !== null || raw.dataAuthority !== null || raw.semantics !== "UNAVAILABLE" || raw.freshness !== "UNAVAILABLE") {
      throw new TypeError("Invalid unavailable monitoring response");
    }
    return { ...raw, snapshot: null };
  }
  const snapshot = raw.snapshot;
  if (raw.availability !== "AVAILABLE" || raw.dataAuthority !== authority ||
      raw.semantics !== "LAST_KNOWN" || !["LAST_KNOWN", "STALE"].includes(raw.freshness) ||
      !snapshot || snapshot.authority !== authority ||
      snapshot.accountingAuthoritySource !== MONITORING_SOURCES[authority] ||
      snapshot.realizedPnlSemantics !== REALIZED_PNL_SEMANTICS[authority] ||
      raw.source !== "MM_RUNTIME_OBSERVATION" || snapshot.source !== raw.source ||
      typeof raw.asOf !== "string" || !Number.isFinite(Date.parse(raw.asOf)) ||
      snapshot.capturedAt !== raw.asOf || !snapshot.metrics || Array.isArray(snapshot.metrics) ||
      typeof snapshot.metrics !== "object" || typeof snapshot.riskState !== "string" ||
      (snapshot.metrics.openPositionState != null && typeof snapshot.metrics.openPositionState !== "string")) {
    throw new TypeError("Invalid monitoring snapshot contract");
  }
  return { ...raw, snapshot: { ...snapshot, metrics: { ...snapshot.metrics } } };
}
