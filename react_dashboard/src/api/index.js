const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, "") ||
  "http://35.194.104.74:8000";

// --------------------------
// safe join
// --------------------------
const join = (path) => {
  const cleanPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${cleanPath}`;
};

// --------------------------
// API Layer
// --------------------------
export const API = {
  // ------------------
  // Market Data
  // ------------------
  price: () => join("/price"),
  balance: () => join("/balance"),
  positions: () => join("/positions"),

  // ------------------
  // AI
  // ------------------
  scores: (symbol = "BTCUSDT") =>
    join(`/ai/scores?symbol=${encodeURIComponent(symbol)}`),

  // ------------------
  // Logs
  // ------------------
  logs: () => join("/logs"),

  // ------------------
  // Bot Control
  // ------------------
  botStatus: () => join("/bot/status"),
  botStart: () => join("/bot/start"),
  botStop: () => join("/bot/stop"),

  // ------------------
  // Summary / Dashboard
  // ------------------
  summary: () => join("/bot/summary"), // ←ここ修正

  // ------------------
  // PnL
  // ------------------
  pnl: () => join("/pnl"),
};