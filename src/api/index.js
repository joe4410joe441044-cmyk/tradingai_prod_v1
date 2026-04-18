const API_BASE = import.meta.env.VITE_API_BASE || "";

// --------------------------
// パス結合ヘルパー（事故防止）
// --------------------------
const join = (path) => `${API_BASE}${path}`;

export const API = {
  // --------------------------
  // Market Data
  // --------------------------
  price: () => join("/api/price"),
  balance: () => join("/api/balance"),
  positions: () => join("/api/positions"),
  trades: () => join("/api/trades"),

  // --------------------------
  // AI / Analysis
  // --------------------------
  scores: (symbol = "BTCUSDT") =>
    join(`/api/ai/scores?symbol=${symbol}`),

  // --------------------------
  // System Logs
  // --------------------------
  logs: () => join("/api/logs"),

  // --------------------------
  // Bot Control / System Control
  // --------------------------
  botStatus: () => join("/api/bot/status"),
  botStart: () => join("/api/bot/start"),
  botStop: () => join("/api/bot/stop"),

  // --------------------------
  // Asset / Summary（bot.js統合済み）
  // --------------------------
  summary: () => join("/api/bot/summary"),
};