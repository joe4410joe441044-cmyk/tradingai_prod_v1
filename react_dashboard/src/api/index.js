const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

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
  price: () => join("/api/price"),
  balance: () => join("/api/balance"),
  positions: () => join("/api/positions"),

  // ------------------
  // AI
  // ------------------
  scores: (symbol = "BTCUSDT") =>
    join(`/api/ai/scores?symbol=${encodeURIComponent(symbol)}`),

  // ------------------
  // Logs
  // ------------------
  logs: () => join("/api/logs"),

  // ------------------
  // Bot Control
  // ------------------
  botStatus: () => join("/api/bot/status"),
  botStart: () => join("/api/bot/start"),
  botStop: () => join("/api/bot/stop"),

  // ------------------
  // Summary / Dashboard
  // ------------------
  summary: () => join("/api/bot/summary"),

  // ------------------
  // PnL
  // ------------------
  pnl: () => join("/api/pnl"),
};

// --------------------------
// WebSocket Layer (FIXED)
// --------------------------
export const WS = {
  price:
    (import.meta.env.VITE_WS_BASE?.replace(/\/$/, "") ||
      "ws://127.0.0.1:8000") + "/ws/price",
};