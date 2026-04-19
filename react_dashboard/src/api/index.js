const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_BASE ||
  "http://35.194.104.74:8000";

// --------------------------
// 安全なパス結合（/api/api防止）
// --------------------------
const build = (path) => {
  const base = API_BASE.replace(/\/$/, ""); // 末尾スラッシュ削除
  const p = path.startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
};

export const API = {
  // --------------------------
  // Market Data
  // --------------------------
  price: () => build("/api/price"),
  balance: () => build("/api/balance"),
  positions: () => build("/api/positions"),
  trades: () => build("/api/trades"),

  // --------------------------
  // AI / Analysis
  // --------------------------
  scores: (symbol = "BTCUSDT") =>
    build(`/api/ai/scores?symbol=${encodeURIComponent(symbol)}`),

  // --------------------------
  // System Logs
  // --------------------------
  logs: () => build("/api/logs"),

  // --------------------------
  // Bot Control / System Control
  // --------------------------
  botStatus: () => build("/api/bot/status"),
  botStart: () => build("/api/bot/start"),
  botStop: () => build("/api/bot/stop"),

  // --------------------------
  // Summary
  // --------------------------
  summary: () => build("/api/bot/summary"),
};