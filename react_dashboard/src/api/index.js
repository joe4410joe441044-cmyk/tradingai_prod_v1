const API_BASE = import.meta.env.VITE_API_BASE || "/api";

// --------------------------
// safe join（唯一の責務）
// --------------------------
const join = (path) => {
  const cleanBase = API_BASE.replace(/\/$/, ""); // 末尾スラッシュ削除
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${cleanBase}${cleanPath}`;
};

// --------------------------
// API Layer（統一ルール）
// ※ ここは絶対に /api を書かない
// --------------------------
export const API = {
  // =========================
  // Market Data
  // =========================
  price: () => join("/price"),
  balance: () => join("/balance"),
  positions: () => join("/positions"),
  trades: () => join("/trades"),

  // =========================
  // AI / Analysis
  // =========================
  scores: (symbol = "BTCUSDT") =>
    join(`/ai/scores?symbol=${encodeURIComponent(symbol)}`),

  // =========================
  // Logs
  // =========================
  logs: () => join("/logs"),

  // =========================
  // Bot Control
  // =========================
  botStatus: () => join("/bot/status"),
  botStart: () => join("/bot/start"),
  botStop: () => join("/bot/stop"),

  // =========================
  // Summary
  // =========================
  summary: () => join("/bot/summary"),
};